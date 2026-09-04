"""Persist staging index generations and exact chunks in an active SQLite transaction."""

import sqlite3
from datetime import datetime, timedelta

from lexlocal.application.ports.indexing import (
    CandidateChunkSet,
    ChunkProfile,
    EmbeddingMetadata,
    IndexActivationSnapshot,
    IndexActivationUpdate,
    IndexChunk,
    IndexingPersistenceError,
    IndexRepository,
    LogicalChunk,
    PersistedIndexGeneration,
)
from lexlocal.application.ports.processing import PageExtractionMethod
from lexlocal.application.ports.security import (
    EncodedSensitivePayload,
    SensitivePayloadCodec,
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
from lexlocal.domain.documents import DocumentVersion, DocumentVersionState, VersionNumber
from lexlocal.domain.identifiers import (
    ChunkId,
    DocumentId,
    DocumentPageId,
    DocumentVersionId,
    IndexGenerationId,
    LocalModelId,
    ProcessingJobId,
    SourceLocatorId,
    WorkspaceId,
)
from lexlocal.domain.processing import (
    AttemptNumber,
    IndexGeneration,
    IndexGenerationState,
    ProcessingJob,
    ProcessingJobState,
)
from lexlocal.domain.retrieval import PageNumber


class SQLiteIndexRepository(IndexRepository):
    """Map candidate chunks without owning transaction finalization."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        payload_codec: SensitivePayloadCodec,
    ) -> None:
        self._connection = connection
        self._payload_codec = payload_codec

    def stage_candidate(self, candidate: CandidateChunkSet) -> None:
        """Stage one complete generation and chunk set."""

        self._require_transaction()
        if not isinstance(candidate, CandidateChunkSet):
            raise IndexingPersistenceError("candidate persistence input is invalid")
        try:
            self._validate_candidate_graph(candidate)
            generation = candidate.generation
            timestamp = self._timestamp(candidate.created_at)
            self._connection.execute(
                """
                INSERT INTO index_generations (
                    id, workspace_id, document_version_id, processing_job_id,
                    state, embedding_model_id, chunking_profile_version,
                    normalization_profile_version, embedding_dimensions,
                    vector_dtype, chunk_count, created_at, activated_at, archived_at
                ) VALUES (?, ?, ?, ?, 'STAGING', ?, ?, ?, ?, 'float32', ?, ?, NULL, NULL)
                """,
                (
                    str(generation.id),
                    str(generation.workspace_id),
                    str(generation.document_version_id),
                    str(generation.processing_job_id),
                    str(generation.embedding_model_id),
                    generation.chunking_profile_version,
                    generation.normalization_profile_version,
                    generation.embedding_dimensions,
                    len(candidate.chunks),
                    timestamp,
                ),
            )
            self._insert_chunks(candidate)
        except IndexingPersistenceError:
            raise
        except Exception:
            raise IndexingPersistenceError("candidate persistence failed") from None

    def list_generations(
        self,
        workspace_id: WorkspaceId,
        document_version_id: DocumentVersionId,
        processing_job_id: ProcessingJobId,
    ) -> tuple[PersistedIndexGeneration, ...]:
        """Return scoped generation metadata without deciding compatibility."""

        self._require_transaction()
        if (
            not isinstance(workspace_id, WorkspaceId)
            or not isinstance(document_version_id, DocumentVersionId)
            or not isinstance(processing_job_id, ProcessingJobId)
        ):
            raise IndexingPersistenceError("generation discovery request is invalid")
        try:
            rows = self._connection.execute(
                """
                SELECT g.*, j.document_version_id AS job_version_id,
                       m.purpose AS model_purpose, m.dimensions AS model_dimensions
                FROM index_generations AS g
                JOIN document_processing_jobs AS j
                  ON j.id = g.processing_job_id AND j.workspace_id = g.workspace_id
                JOIN local_models AS m ON m.id = g.embedding_model_id
                WHERE g.workspace_id = ? AND g.document_version_id = ?
                  AND g.processing_job_id = ?
                ORDER BY g.created_at, g.id
                """,
                (str(workspace_id), str(document_version_id), str(processing_job_id)),
            ).fetchall()
            return tuple(
                self._map_persisted_generation(
                    row, workspace_id, document_version_id, processing_job_id
                )
                for row in rows
            )
        except IndexingPersistenceError:
            raise
        except Exception:
            raise IndexingPersistenceError("generation discovery failed") from None

    def replace_staging_candidate(self, candidate: CandidateChunkSet) -> None:
        """Replace one complete STAGING chunk set while preserving its generation."""

        self._require_transaction()
        if not isinstance(candidate, CandidateChunkSet):
            raise IndexingPersistenceError("candidate replacement input is invalid")
        try:
            self._validate_candidate_graph(candidate, allow_existing=True)
            generation = candidate.generation
            matching = tuple(
                item
                for item in self.list_generations(
                    generation.workspace_id,
                    generation.document_version_id,
                    generation.processing_job_id,
                )
                if item.generation.id == generation.id
            )
            if len(matching) != 1:
                raise IndexingPersistenceError("candidate replacement metadata is invalid")
            persisted = matching[0]
            if persisted.generation != generation or persisted.created_at != candidate.created_at:
                raise IndexingPersistenceError("candidate replacement metadata is invalid")
            self._connection.execute(
                "DELETE FROM chunks WHERE index_generation_id = ? AND workspace_id = ?",
                (str(generation.id), str(generation.workspace_id)),
            )
            self._insert_chunks(candidate)
        except IndexingPersistenceError:
            raise
        except Exception:
            raise IndexingPersistenceError("candidate replacement failed") from None

    def get_candidate(
        self,
        workspace_id: WorkspaceId,
        document_version_id: DocumentVersionId,
        index_generation_id: IndexGenerationId,
    ) -> CandidateChunkSet | None:
        """Read an exact staging workspace/version/generation handoff."""

        self._require_transaction()
        if (
            not isinstance(workspace_id, WorkspaceId)
            or not isinstance(document_version_id, DocumentVersionId)
            or not isinstance(index_generation_id, IndexGenerationId)
        ):
            raise IndexingPersistenceError("candidate handoff request is invalid")
        try:
            row = self._connection.execute(
                """
                SELECT g.*, m.purpose AS model_purpose, m.dimensions AS model_dimensions,
                       v.state AS version_state, j.state AS job_state, j.stage AS job_stage,
                       j.document_version_id AS job_version_id
                FROM index_generations AS g
                JOIN document_versions AS v
                  ON v.id = g.document_version_id AND v.workspace_id = g.workspace_id
                JOIN document_processing_jobs AS j
                  ON j.id = g.processing_job_id AND j.workspace_id = g.workspace_id
                JOIN local_models AS m ON m.id = g.embedding_model_id
                WHERE g.id = ? AND g.workspace_id = ? AND g.document_version_id = ?
                """,
                (str(index_generation_id), str(workspace_id), str(document_version_id)),
            ).fetchone()
            if row is None:
                return None
            self._validate_generation_row(row, workspace_id, document_version_id)
            generation = self._map_generation(row)
            rows = self._connection.execute(
                """
                SELECT c.*, p.page_number, p.state AS page_state,
                       p.extraction_method AS page_extraction_method,
                       p.text_ciphertext AS page_text_ciphertext,
                       l.document_version_id AS locator_version_id,
                       l.page_id AS locator_page_id, l.page_number AS locator_page_number,
                       l.locator_kind, l.locator_version, l.geometry_json_ciphertext
                FROM chunks AS c
                JOIN document_pages AS p
                  ON p.id = c.page_id AND p.workspace_id = c.workspace_id
                JOIN source_locators AS l
                  ON l.id = c.source_locator_id AND l.workspace_id = c.workspace_id
                WHERE c.index_generation_id = ? AND c.workspace_id = ?
                ORDER BY c.document_order
                """,
                (str(index_generation_id), str(workspace_id)),
            ).fetchall()
            if len(rows) != row["chunk_count"] or not rows:
                raise IndexingPersistenceError("candidate handoff is incomplete")
            chunks = tuple(self._map_chunk(item, generation, document_version_id) for item in rows)
            return CandidateChunkSet(generation, chunks, self._parse_timestamp(row["created_at"]))
        except IndexingPersistenceError:
            raise
        except Exception:
            raise IndexingPersistenceError("candidate handoff is invalid") from None

    def get_activation_snapshot(
        self,
        workspace_id: WorkspaceId,
        document_version_id: DocumentVersionId,
        processing_job_id: ProcessingJobId,
        index_generation_id: IndexGenerationId,
    ) -> IndexActivationSnapshot:
        """Read the exact candidate, lifecycle, and embedding compatibility metadata."""

        self._require_transaction()
        if (
            not isinstance(workspace_id, WorkspaceId)
            or not isinstance(document_version_id, DocumentVersionId)
            or not isinstance(processing_job_id, ProcessingJobId)
            or not isinstance(index_generation_id, IndexGenerationId)
        ):
            raise IndexingPersistenceError("activation snapshot request is invalid")
        try:
            candidate = self.get_candidate(workspace_id, document_version_id, index_generation_id)
            if candidate is None or candidate.generation.processing_job_id != processing_job_id:
                raise IndexingPersistenceError("activation candidate is unavailable")
            row = self._activation_lifecycle_row(
                workspace_id, document_version_id, processing_job_id
            )
            version = self._map_version(row)
            job = self._map_job(row)
            embeddings = self._embedding_metadata(candidate)
            previous_versions = self._previous_active_versions(row, candidate)
            previous_generations = self._previous_active_generations(row, candidate)
            if len(previous_versions) > 1 or len(previous_generations) > 1:
                raise IndexingPersistenceError("previous active index state is ambiguous")
            warning_count = self._connection.execute(
                "SELECT COUNT(*) FROM document_pages WHERE workspace_id = ? AND document_version_id = ? AND state = 'WARNING'",
                (str(workspace_id), str(document_version_id)),
            ).fetchone()[0]
            return IndexActivationSnapshot(
                candidate,
                version,
                job,
                row["job_stage"],
                embeddings,
                warning_count > 0,
                previous_versions[0] if previous_versions else None,
                previous_generations[0] if previous_generations else None,
            )
        except IndexingPersistenceError:
            raise
        except Exception:
            raise IndexingPersistenceError("activation snapshot is invalid") from None

    def activate_candidate(self, update: IndexActivationUpdate) -> None:
        """Apply guarded terminal lifecycle transitions in the caller's transaction."""

        self._require_transaction()
        if not isinstance(update, IndexActivationUpdate):
            raise IndexingPersistenceError("activation update is invalid")
        try:
            candidate = update.candidate
            generation = candidate.generation
            snapshot = self.get_activation_snapshot(
                generation.workspace_id,
                generation.document_version_id,
                generation.processing_job_id,
                generation.id,
            )
            if snapshot.candidate != candidate or snapshot.has_warnings != update.has_warnings:
                raise IndexingPersistenceError("activation state is stale")
            timestamp = self._timestamp(update.completed_at)
            document_id = str(update.version.document_id)
            self._archive_previous_active(document_id, generation, timestamp)
            ready_state = (
                DocumentVersionState.CANDIDATE_WARNING.value
                if update.has_warnings
                else DocumentVersionState.CANDIDATE_READY.value
            )
            ready_cursor = self._connection.execute(
                """
                UPDATE document_versions SET state = ?
                WHERE id = ? AND workspace_id = ? AND document_id = ?
                  AND state = 'CANDIDATE_PROCESSING'
                """,
                (
                    ready_state,
                    str(generation.document_version_id),
                    str(generation.workspace_id),
                    document_id,
                ),
            )
            version_cursor = self._connection.execute(
                """
                UPDATE document_versions SET state = 'ACTIVE', activated_at = ?
                WHERE id = ? AND workspace_id = ? AND document_id = ? AND state = ?
                """,
                (
                    timestamp,
                    str(generation.document_version_id),
                    str(generation.workspace_id),
                    document_id,
                    ready_state,
                ),
            )
            job_cursor = self._connection.execute(
                """
                UPDATE document_processing_jobs
                SET state = ?, completed_at = ?, heartbeat_at = ?
                WHERE id = ? AND workspace_id = ? AND document_version_id = ?
                  AND state = 'PROCESSING' AND stage = 'CHUNKING'
                """,
                (
                    update.job.state.value,
                    timestamp,
                    timestamp,
                    str(generation.processing_job_id),
                    str(generation.workspace_id),
                    str(generation.document_version_id),
                ),
            )
            generation_cursor = self._connection.execute(
                """
                UPDATE index_generations AS g SET state = 'ACTIVE', activated_at = ?
                WHERE g.id = ? AND g.workspace_id = ? AND g.document_version_id = ?
                  AND g.processing_job_id = ? AND g.state = 'STAGING'
                  AND g.embedding_model_id = ? AND g.embedding_dimensions = ?
                  AND g.chunking_profile_version = ?
                  AND g.normalization_profile_version = ? AND g.vector_dtype = 'float32'
                  AND g.chunk_count = ?
                  AND g.chunk_count = (
                      SELECT COUNT(*) FROM chunks AS c
                      WHERE c.index_generation_id = g.id AND c.workspace_id = g.workspace_id
                  )
                  AND g.chunk_count = (
                      SELECT COUNT(*) FROM embeddings AS e
                      WHERE e.index_generation_id = g.id AND e.workspace_id = g.workspace_id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM chunks AS c
                      LEFT JOIN embeddings AS e
                        ON e.chunk_id = c.id AND e.workspace_id = c.workspace_id
                       AND e.index_generation_id = c.index_generation_id
                      WHERE c.index_generation_id = g.id AND c.workspace_id = g.workspace_id
                        AND (
                            e.chunk_id IS NULL OR e.embedding_model_id <> g.embedding_model_id
                            OR e.dimensions <> g.embedding_dimensions OR e.dtype <> g.vector_dtype
                            OR e.is_unit_normalized <> 1 OR length(e.vector_ciphertext) = 0
                        )
                  )
                """,
                (
                    timestamp,
                    str(generation.id),
                    str(generation.workspace_id),
                    str(generation.document_version_id),
                    str(generation.processing_job_id),
                    str(generation.embedding_model_id),
                    generation.embedding_dimensions,
                    generation.chunking_profile_version,
                    generation.normalization_profile_version,
                    len(candidate.chunks),
                ),
            )
            if (
                ready_cursor.rowcount != 1
                or version_cursor.rowcount != 1
                or job_cursor.rowcount != 1
                or generation_cursor.rowcount != 1
            ):
                raise IndexingPersistenceError("index activation state is stale")
        except IndexingPersistenceError:
            raise
        except Exception:
            raise IndexingPersistenceError("index activation failed") from None

    def _activation_lifecycle_row(
        self,
        workspace_id: WorkspaceId,
        document_version_id: DocumentVersionId,
        processing_job_id: ProcessingJobId,
    ) -> sqlite3.Row:
        row: sqlite3.Row | None = self._connection.execute(
            """
            SELECT v.id AS document_version_id, v.workspace_id, v.document_id,
                   v.version_number, v.state AS version_state,
                   j.id AS processing_job_id, j.attempt_number,
                   j.state AS job_state, j.stage AS job_stage
            FROM document_versions AS v
            JOIN document_processing_jobs AS j
              ON j.document_version_id = v.id AND j.workspace_id = v.workspace_id
            WHERE v.id = ? AND v.workspace_id = ? AND j.id = ?
            """,
            (str(document_version_id), str(workspace_id), str(processing_job_id)),
        ).fetchone()
        if row is None:
            raise IndexingPersistenceError("activation lifecycle is unavailable")
        return row

    @staticmethod
    def _map_version(row: sqlite3.Row) -> DocumentVersion:
        return DocumentVersion(
            DocumentVersionId(row["document_version_id"]),
            WorkspaceId(row["workspace_id"]),
            DocumentId(row["document_id"]),
            VersionNumber(row["version_number"]),
            DocumentVersionState(row["version_state"]),
        )

    @staticmethod
    def _map_job(row: sqlite3.Row) -> ProcessingJob:
        return ProcessingJob(
            ProcessingJobId(row["processing_job_id"]),
            WorkspaceId(row["workspace_id"]),
            DocumentVersionId(row["document_version_id"]),
            AttemptNumber(row["attempt_number"]),
            ProcessingJobState(row["job_state"]),
        )

    def _embedding_metadata(self, candidate: CandidateChunkSet) -> tuple[EmbeddingMetadata, ...]:
        generation = candidate.generation
        rows = self._connection.execute(
            """
            SELECT e.* FROM embeddings AS e
            WHERE e.index_generation_id = ?
               OR e.chunk_id IN (
                   SELECT c.id FROM chunks AS c
                   WHERE c.index_generation_id = ? AND c.workspace_id = ?
               )
            ORDER BY e.chunk_id
            """,
            (str(generation.id), str(generation.id), str(generation.workspace_id)),
        ).fetchall()
        return tuple(
            EmbeddingMetadata(
                ChunkId(row["chunk_id"]),
                WorkspaceId(row["workspace_id"]),
                IndexGenerationId(row["index_generation_id"]),
                LocalModelId(row["embedding_model_id"]),
                row["dimensions"],
                row["dtype"],
                row["is_unit_normalized"] == 1,
                isinstance(row["vector_ciphertext"], bytes) and bool(row["vector_ciphertext"]),
            )
            for row in rows
        )

    def _previous_active_versions(
        self, row: sqlite3.Row, candidate: CandidateChunkSet
    ) -> tuple[DocumentVersion, ...]:
        rows = self._connection.execute(
            """
            SELECT id AS document_version_id, workspace_id, document_id,
                   version_number, state AS version_state
            FROM document_versions
            WHERE workspace_id = ? AND document_id = ? AND state = 'ACTIVE' AND id <> ?
            ORDER BY id
            """,
            (
                str(candidate.generation.workspace_id),
                row["document_id"],
                str(candidate.generation.document_version_id),
            ),
        ).fetchall()
        return tuple(self._map_version(item) for item in rows)

    def _previous_active_generations(
        self, row: sqlite3.Row, candidate: CandidateChunkSet
    ) -> tuple[PersistedIndexGeneration, ...]:
        rows = self._connection.execute(
            """
            SELECT g.*, j.document_version_id AS job_version_id,
                   m.purpose AS model_purpose, m.dimensions AS model_dimensions
            FROM index_generations AS g
            JOIN document_versions AS v
              ON v.id = g.document_version_id AND v.workspace_id = g.workspace_id
            JOIN document_processing_jobs AS j
              ON j.id = g.processing_job_id AND j.workspace_id = g.workspace_id
            JOIN local_models AS m ON m.id = g.embedding_model_id
            WHERE g.workspace_id = ? AND v.document_id = ?
              AND g.state = 'ACTIVE' AND g.id <> ?
            ORDER BY g.id
            """,
            (
                str(candidate.generation.workspace_id),
                row["document_id"],
                str(candidate.generation.id),
            ),
        ).fetchall()
        return tuple(
            self._map_persisted_generation(
                item,
                WorkspaceId(item["workspace_id"]),
                DocumentVersionId(item["document_version_id"]),
                ProcessingJobId(item["processing_job_id"]),
            )
            for item in rows
        )

    def _archive_previous_active(
        self,
        document_id: str,
        generation: IndexGeneration,
        timestamp: str,
    ) -> None:
        self._connection.execute(
            """
            UPDATE index_generations SET state = 'ARCHIVED', archived_at = ?
            WHERE state = 'ACTIVE' AND workspace_id = ? AND id <> ?
              AND document_version_id IN (
                  SELECT id FROM document_versions
                  WHERE workspace_id = ? AND document_id = ?
              )
            """,
            (
                timestamp,
                str(generation.workspace_id),
                str(generation.id),
                str(generation.workspace_id),
                document_id,
            ),
        )
        self._connection.execute(
            """
            UPDATE document_versions SET state = 'ARCHIVED', archived_at = ?
            WHERE state = 'ACTIVE' AND workspace_id = ? AND document_id = ? AND id <> ?
            """,
            (
                timestamp,
                str(generation.workspace_id),
                document_id,
                str(generation.document_version_id),
            ),
        )

    def _validate_candidate_graph(
        self,
        candidate: CandidateChunkSet,
        *,
        allow_existing: bool = False,
    ) -> None:
        generation = candidate.generation
        if generation.state is not IndexGenerationState.STAGING:
            raise IndexingPersistenceError("candidate generation state is invalid")
        if len({chunk.equality_token for chunk in candidate.chunks}) != len(candidate.chunks):
            raise IndexingPersistenceError("candidate chunk equality is invalid")
        if any(
            not chunk.equality_token
            or chunk.logical.extraction_method is not PageExtractionMethod.NATIVE
            for chunk in candidate.chunks
        ):
            raise IndexingPersistenceError("candidate chunk mapping is invalid")
        existing = self._connection.execute(
            "SELECT 1 FROM index_generations WHERE id = ? OR (workspace_id = ? AND document_version_id = ? AND state = 'STAGING')",
            (str(generation.id), str(generation.workspace_id), str(generation.document_version_id)),
        ).fetchone()
        if existing is not None and not allow_existing:
            raise IndexingPersistenceError("candidate generation conflicts")
        row: sqlite3.Row | None = self._connection.execute(
            """
            SELECT v.state AS version_state, j.state AS job_state, j.stage AS job_stage,
                   j.document_version_id AS job_version_id,
                   m.purpose AS model_purpose, m.dimensions AS model_dimensions
            FROM document_versions AS v
            JOIN document_processing_jobs AS j
              ON j.id = ? AND j.workspace_id = v.workspace_id
            JOIN local_models AS m ON m.id = ?
            WHERE v.id = ? AND v.workspace_id = ?
            """,
            (
                str(generation.processing_job_id),
                str(generation.embedding_model_id),
                str(generation.document_version_id),
                str(generation.workspace_id),
            ),
        ).fetchone()
        if (
            row is None
            or row["version_state"] != "CANDIDATE_PROCESSING"
            or row["job_state"] != "PROCESSING"
            or row["job_stage"] != "CHUNKING"
            or row["job_version_id"] != str(generation.document_version_id)
            or row["model_purpose"] != "EMBEDDING"
            or row["model_dimensions"] != generation.embedding_dimensions
        ):
            raise IndexingPersistenceError("candidate relationships are invalid")
        for chunk in candidate.chunks:
            page = self._page_row(chunk.logical)
            page_text = self._decode_page_text(
                page["page_text_ciphertext"], chunk.logical.workspace_id, chunk.logical.page_id
            )
            logical = chunk.logical
            if page_text[logical.source_start_offset : logical.source_end_offset] != logical.text:
                raise IndexingPersistenceError("candidate source range is invalid")

    def _insert_chunks(self, candidate: CandidateChunkSet) -> None:
        generation = candidate.generation
        for chunk in candidate.chunks:
            payload = self._encode_chunk_text(chunk)
            logical = chunk.logical
            self._connection.execute(
                """
                INSERT INTO chunks (
                    id, workspace_id, index_generation_id, document_version_id,
                    page_id, source_locator_id, document_order, page_order,
                    text_ciphertext, normalized_text_fingerprint,
                    character_count, token_count_estimate, extraction_method,
                    created_at, source_start_offset, source_end_offset
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                """,
                (
                    str(chunk.id),
                    str(logical.workspace_id),
                    str(generation.id),
                    str(logical.document_version_id),
                    str(logical.page_id),
                    str(logical.source_locator_id),
                    logical.document_order,
                    logical.page_order,
                    payload,
                    chunk.equality_token,
                    len(logical.text),
                    logical.extraction_method.value,
                    self._timestamp(chunk.created_at),
                    logical.source_start_offset,
                    logical.source_end_offset,
                ),
            )

    def _map_persisted_generation(
        self,
        row: sqlite3.Row,
        workspace_id: WorkspaceId,
        version_id: DocumentVersionId,
        job_id: ProcessingJobId,
    ) -> PersistedIndexGeneration:
        if (
            row["workspace_id"] != str(workspace_id)
            or row["document_version_id"] != str(version_id)
            or row["processing_job_id"] != str(job_id)
            or row["job_version_id"] != str(version_id)
            or row["model_purpose"] != "EMBEDDING"
            or row["model_dimensions"] != row["embedding_dimensions"]
            or row["vector_dtype"] != "float32"
        ):
            raise IndexingPersistenceError("generation discovery mapping is invalid")
        return PersistedIndexGeneration(
            self._map_generation(row),
            self._parse_timestamp(row["created_at"]),
            self._optional_timestamp(row["activated_at"]),
            self._optional_timestamp(row["archived_at"]),
        )

    def _page_row(self, logical: LogicalChunk) -> sqlite3.Row:
        row: sqlite3.Row | None = self._connection.execute(
            """
            SELECT p.page_number, p.state AS page_state,
                   p.extraction_method AS page_extraction_method,
                   p.text_ciphertext AS page_text_ciphertext,
                   l.document_version_id AS locator_version_id,
                   l.page_id AS locator_page_id, l.page_number AS locator_page_number,
                   l.locator_kind, l.locator_version, l.geometry_json_ciphertext
            FROM document_pages AS p
            JOIN source_locators AS l
              ON l.id = ? AND l.workspace_id = p.workspace_id
            WHERE p.id = ? AND p.workspace_id = ? AND p.document_version_id = ?
            """,
            (
                str(logical.source_locator_id),
                str(logical.page_id),
                str(logical.workspace_id),
                str(logical.document_version_id),
            ),
        ).fetchone()
        if row is None or not self._valid_page_row(row, logical):
            raise IndexingPersistenceError("candidate page relationship is invalid")
        return row

    @staticmethod
    def _valid_page_row(row: sqlite3.Row, logical: LogicalChunk) -> bool:
        return (
            row["page_number"] == logical.page_number.value
            and row["page_state"] == "READY"
            and row["page_extraction_method"] == "NATIVE"
            and row["locator_version_id"] == str(logical.document_version_id)
            and row["locator_page_id"] == str(logical.page_id)
            and row["locator_page_number"] == logical.page_number.value
            and row["locator_kind"] == "PAGE"
            and row["locator_version"] == 1
            and row["geometry_json_ciphertext"] is None
        )

    def _validate_generation_row(
        self, row: sqlite3.Row, workspace_id: WorkspaceId, version_id: DocumentVersionId
    ) -> None:
        if (
            row["workspace_id"] != str(workspace_id)
            or row["document_version_id"] != str(version_id)
            or row["job_version_id"] != str(version_id)
            or row["state"] != "STAGING"
            or row["version_state"] != "CANDIDATE_PROCESSING"
            or row["job_state"] != "PROCESSING"
            or row["job_stage"] != "CHUNKING"
            or row["model_purpose"] != "EMBEDDING"
            or row["model_dimensions"] != row["embedding_dimensions"]
            or row["vector_dtype"] != "float32"
            or row["activated_at"] is not None
            or row["archived_at"] is not None
        ):
            raise IndexingPersistenceError("candidate handoff mapping is invalid")

    @staticmethod
    def _map_generation(row: sqlite3.Row) -> IndexGeneration:
        return IndexGeneration(
            IndexGenerationId(row["id"]),
            WorkspaceId(row["workspace_id"]),
            DocumentVersionId(row["document_version_id"]),
            ProcessingJobId(row["processing_job_id"]),
            LocalModelId(row["embedding_model_id"]),
            row["chunking_profile_version"],
            row["normalization_profile_version"],
            row["embedding_dimensions"],
            IndexGenerationState(row["state"]),
        )

    def _map_chunk(
        self, row: sqlite3.Row, generation: IndexGeneration, version_id: DocumentVersionId
    ) -> IndexChunk:
        page_id = DocumentPageId(row["page_id"])
        logical = LogicalChunk(
            WorkspaceId(row["workspace_id"]),
            version_id,
            page_id,
            PageNumber(row["page_number"]),
            SourceLocatorId(row["source_locator_id"]),
            row["document_order"],
            row["page_order"],
            row["source_start_offset"],
            row["source_end_offset"],
            self._decode_chunk_text(
                row["text_ciphertext"], generation.workspace_id, ChunkId(row["id"])
            ),
            PageExtractionMethod(row["extraction_method"]),
            ChunkProfile(generation.chunking_profile_version),
        )
        if (
            row["document_version_id"] != str(version_id)
            or row["index_generation_id"] != str(generation.id)
            or row["token_count_estimate"] is not None
            or row["character_count"] != len(logical.text)
            or logical.extraction_method is not PageExtractionMethod.NATIVE
            or not isinstance(row["normalized_text_fingerprint"], bytes)
            or not row["normalized_text_fingerprint"]
            or not self._valid_page_row(row, logical)
        ):
            raise IndexingPersistenceError("candidate chunk mapping is invalid")
        page_text = self._decode_page_text(
            row["page_text_ciphertext"], generation.workspace_id, page_id
        )
        if page_text[logical.source_start_offset : logical.source_end_offset] != logical.text:
            raise IndexingPersistenceError("candidate source range is invalid")
        return IndexChunk(
            ChunkId(row["id"]),
            logical,
            row["normalized_text_fingerprint"],
            self._parse_timestamp(row["created_at"]),
        )

    def _encode_chunk_text(self, chunk: IndexChunk) -> bytes:
        context, key = self._chunk_security_values(chunk.logical.workspace_id, chunk.id)
        encoded = self._payload_codec.encode(
            chunk.logical.text.encode("utf-8"), context=context, key_reference=key
        )
        if (
            not isinstance(encoded, EncodedSensitivePayload)
            or encoded.context != context
            or encoded.key_reference != key
            or encoded.format_version != 1
        ):
            raise IndexingPersistenceError("candidate chunk payload is invalid")
        return encoded.payload

    def _decode_chunk_text(
        self, payload: object, workspace_id: WorkspaceId, chunk_id: ChunkId
    ) -> str:
        context, key = self._chunk_security_values(workspace_id, chunk_id)
        return self._decode(payload, context, key)

    def _decode_page_text(
        self, payload: object, workspace_id: WorkspaceId, page_id: DocumentPageId
    ) -> str:
        context = SensitivePayloadContext(workspace_id, str(page_id), "document-page-text", 1)
        return self._decode(payload, context, WorkspaceKeyReference(workspace_id, 1))

    def _decode(
        self, payload: object, context: SensitivePayloadContext, key: WorkspaceKeyReference
    ) -> str:
        if not isinstance(payload, bytes):
            raise IndexingPersistenceError("candidate payload is invalid")
        plaintext = self._payload_codec.decode(
            EncodedSensitivePayload(payload, context, key, 1),
            context=context,
            key_reference=key,
        )
        if not isinstance(plaintext, bytes):
            raise IndexingPersistenceError("candidate payload is invalid")
        return plaintext.decode("utf-8")

    @staticmethod
    def _chunk_security_values(
        workspace_id: WorkspaceId, chunk_id: ChunkId
    ) -> tuple[SensitivePayloadContext, WorkspaceKeyReference]:
        return (
            SensitivePayloadContext(workspace_id, str(chunk_id), "index-chunk-text", 1),
            WorkspaceKeyReference(workspace_id, 1),
        )

    def _require_transaction(self) -> None:
        if not self._connection.in_transaction:
            raise IndexingPersistenceError("index transaction is not active")

    @staticmethod
    def _timestamp(value: datetime) -> str:
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() != timedelta(0)
        ):
            raise IndexingPersistenceError("candidate timestamp is invalid")
        return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    @staticmethod
    def _parse_timestamp(value: object) -> datetime:
        if not isinstance(value, str) or not value.endswith("Z"):
            raise IndexingPersistenceError("candidate timestamp is invalid")
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        if value != parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z"):
            raise IndexingPersistenceError("candidate timestamp is invalid")
        return parsed

    @classmethod
    def _optional_timestamp(cls, value: object) -> datetime | None:
        return None if value is None else cls._parse_timestamp(value)
