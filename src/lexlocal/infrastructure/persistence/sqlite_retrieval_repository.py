"""Persist and reconstruct exact QA retrieval graphs in an active transaction."""

import sqlite3
from datetime import datetime, timedelta

from lexlocal.application.ports.embeddings import (
    EMBEDDING_DTYPE,
    ChunkEmbedding,
    EmbeddingCompatibility,
)
from lexlocal.application.ports.indexing import PersistedIndexGeneration
from lexlocal.application.ports.retrieval import (
    IncompatibleRetrievalScope,
    NoEligibleIndex,
    QaRetrievalRequest,
    ResolvedRetrievalGeneration,
    ResolvedRetrievalScope,
    RetrievalCandidate,
    RetrievalCandidateSet,
    RetrievalConfiguration,
    RetrievalError,
    RetrievalEvidenceRegistration,
    RetrievalIntegrityError,
    RetrievalPersistenceError,
    RetrievalRegistration,
    RetrievalRepository,
)
from lexlocal.application.ports.security import (
    EncodedSensitivePayload,
    SensitivePayloadCodec,
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
from lexlocal.domain.documents import VersionNumber
from lexlocal.domain.identifiers import (
    ChunkId,
    DocumentId,
    DocumentPageId,
    DocumentVersionId,
    EvidenceItemId,
    IndexGenerationId,
    LocalModelId,
    ProcessingJobId,
    QaRequestId,
    RetrievalRunId,
    SourceLocatorId,
    WorkspaceId,
)
from lexlocal.domain.processing import (
    IndexGeneration,
    IndexGenerationState,
    ProcessingJobState,
)
from lexlocal.domain.retrieval import (
    Evidence,
    EvidenceAvailability,
    EvidenceRank,
    PageNumber,
    SimilarityScore,
    SourceLocator,
    SourceLocatorKind,
)
from lexlocal.infrastructure.persistence.sqlite_embedding_repository import (
    SQLiteEmbeddingRepository,
)
from lexlocal.infrastructure.persistence.sqlite_index_repository import (
    SQLiteIndexRepository,
)

_CODEC_FORMAT_VERSION = 1
_PAYLOAD_SCHEMA_VERSION = 1
_QUERY_PURPOSE = "retrieval-query"
_EVIDENCE_EXCERPT_PURPOSE = "retrieval-evidence-excerpt"
_EVIDENCE_DOCUMENT_NAME_PURPOSE = "retrieval-evidence-document-name"
_DOCUMENT_NAME_PURPOSE = "document-display-name"


class SQLiteRetrievalRepository(RetrievalRepository):
    """Map exact QA scope, candidate, run, and evidence data without finalization."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        payload_codec: SensitivePayloadCodec,
    ) -> None:
        self._connection = connection
        self._payload_codec = payload_codec
        self._index_repository = SQLiteIndexRepository(connection, payload_codec)
        self._embedding_repository = SQLiteEmbeddingRepository(connection, payload_codec)

    def get_for_qa_request(
        self,
        workspace_id: WorkspaceId,
        qa_request_id: QaRequestId,
    ) -> RetrievalRegistration | None:
        """Reconstruct the sole complete committed run for one exact QA owner."""

        self._require_transaction()
        if not isinstance(workspace_id, WorkspaceId) or not isinstance(
            qa_request_id, QaRequestId
        ):
            raise RetrievalPersistenceError("retrieval lookup is invalid")
        try:
            rows = self._connection.execute(
                """
                SELECT * FROM retrieval_runs
                WHERE qa_request_id = ?
                ORDER BY id
                """,
                (str(qa_request_id),),
            ).fetchall()
            if not rows:
                return None
            if len(rows) != 1:
                raise RetrievalPersistenceError("QA retrieval state is ambiguous")
            return self._map_registration(rows[0], workspace_id, qa_request_id)
        except RetrievalPersistenceError:
            raise
        except RetrievalError:
            raise RetrievalPersistenceError(
                "retrieval reconstruction failed"
            ) from None
        except Exception:
            raise RetrievalPersistenceError(
                "retrieval reconstruction failed"
            ) from None

    def resolve_scope(self, request: QaRetrievalRequest) -> ResolvedRetrievalScope:
        """Resolve the authoritative QA versions and exact eligible ACTIVE generations."""

        self._require_transaction()
        if not isinstance(request, QaRetrievalRequest):
            raise RetrievalPersistenceError("retrieval scope request is invalid")
        try:
            self._validate_qa_owner(request)
            scope_rows = self._qa_scope_rows(request)
            selected_rows = self._select_scope_rows(request, scope_rows)
            generation_rows = tuple(
                self._active_generation_rows(request.workspace_id, row)
                for row in selected_rows
            )
            if all(not rows for rows in generation_rows):
                raise NoEligibleIndex("retrieval scope has no eligible ACTIVE index")
            if any(len(rows) != 1 for rows in generation_rows):
                raise RetrievalIntegrityError(
                    "retrieval scope generation state is invalid"
                )
            generations = tuple(
                self._map_resolved_generation(scope_row, rows[0])
                for scope_row, rows in zip(
                    selected_rows,
                    generation_rows,
                    strict=True,
                )
            )
            return ResolvedRetrievalScope(request, generations)
        except (NoEligibleIndex, IncompatibleRetrievalScope, RetrievalIntegrityError):
            raise
        except RetrievalError:
            raise RetrievalIntegrityError("retrieval scope is invalid") from None
        except Exception:
            raise RetrievalIntegrityError("retrieval scope is invalid") from None

    def load_candidates(self, scope: ResolvedRetrievalScope) -> RetrievalCandidateSet:
        """Decode the complete exact chunk/vector graph for one resolved scope."""

        self._require_transaction()
        if not isinstance(scope, ResolvedRetrievalScope):
            raise RetrievalPersistenceError("retrieval candidate request is invalid")
        try:
            current = self.resolve_scope(scope.request)
            if current != scope:
                raise RetrievalIntegrityError("retrieval scope is stale")
            candidates: list[RetrievalCandidate] = []
            for resolved in scope.generations:
                candidates.extend(self._generation_candidates(resolved))
            return RetrievalCandidateSet(scope, tuple(candidates))
        except (NoEligibleIndex, IncompatibleRetrievalScope, RetrievalIntegrityError):
            raise
        except RetrievalError:
            raise RetrievalIntegrityError("retrieval candidates are invalid") from None
        except Exception:
            raise RetrievalIntegrityError("retrieval candidates are invalid") from None

    def add(self, registration: RetrievalRegistration) -> None:
        """Stage one complete QA retrieval graph in the caller-owned transaction."""

        self._require_transaction()
        if not isinstance(registration, RetrievalRegistration):
            raise RetrievalPersistenceError("retrieval registration is invalid")
        try:
            current = self.resolve_scope(registration.scope.request)
            if current != registration.scope:
                raise RetrievalPersistenceError("retrieval registration scope is stale")
            candidates = self.load_candidates(current)
            if len(candidates.candidates) != registration.candidate_count:
                raise RetrievalPersistenceError(
                    "retrieval candidate count is inconsistent"
                )
            self._validate_evidence_candidates(registration, candidates)

            query_payload = self._encode_text(
                registration.scope.request.query,
                workspace_id=registration.workspace_id,
                owner_id=str(registration.retrieval_run_id),
                purpose=_QUERY_PURPOSE,
            )
            cursor = self._connection.execute(
                """
                INSERT INTO retrieval_runs (
                    id, workspace_id, purpose, qa_request_id,
                    analysis_generation_section_id, query_ciphertext,
                    embedding_model_id, top_k, candidate_count,
                    retrieval_policy_version, created_at, min_similarity
                )
                SELECT ?, ?, 'QA', ?, NULL, ?, ?, ?, ?, ?, ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM retrieval_runs WHERE qa_request_id = ?
                )
                """,
                (
                    str(registration.retrieval_run_id),
                    str(registration.workspace_id),
                    str(registration.qa_request_id),
                    query_payload,
                    str(registration.embedding_model_id),
                    registration.configuration.top_k,
                    registration.candidate_count,
                    registration.retrieval_policy_version,
                    self._timestamp(registration.created_at),
                    registration.configuration.min_similarity.value,
                    str(registration.qa_request_id),
                ),
            )
            if cursor.rowcount != 1:
                raise RetrievalPersistenceError("QA retrieval already exists")
            self._connection.executemany(
                """
                INSERT INTO retrieval_run_generations (
                    retrieval_run_id, workspace_id, index_generation_id
                ) VALUES (?, ?, ?)
                """,
                tuple(
                    (
                        str(registration.retrieval_run_id),
                        str(registration.workspace_id),
                        str(generation_id),
                    )
                    for generation_id in registration.scope.generation_ids
                ),
            )
            for item in registration.evidence:
                self._insert_evidence(item)
        except RetrievalError:
            raise
        except Exception:
            raise RetrievalPersistenceError("retrieval persistence failed") from None

    def _validate_qa_owner(self, request: QaRetrievalRequest) -> None:
        row = self._connection.execute(
            """
            SELECT q.workspace_id, w.state AS workspace_state
            FROM qa_requests AS q
            LEFT JOIN workspaces AS w ON w.id = q.workspace_id
            WHERE q.id = ?
            """,
            (str(request.qa_request_id),),
        ).fetchone()
        if (
            row is None
            or row["workspace_id"] != str(request.workspace_id)
            or row["workspace_state"] != "ACTIVE"
        ):
            raise RetrievalIntegrityError("QA retrieval owner is invalid")

    def _qa_scope_rows(self, request: QaRetrievalRequest) -> tuple[sqlite3.Row, ...]:
        rows = self._connection.execute(
            """
            SELECT s.workspace_id, s.document_id, s.document_version_id,
                   d.state AS document_state, d.display_name_ciphertext,
                   v.document_id AS version_document_id,
                   v.workspace_id AS version_workspace_id,
                   v.version_number, v.state AS version_state
            FROM qa_scope_versions AS s
            LEFT JOIN documents AS d
              ON d.id = s.document_id AND d.workspace_id = s.workspace_id
            LEFT JOIN document_versions AS v
              ON v.id = s.document_version_id AND v.workspace_id = s.workspace_id
            WHERE s.qa_request_id = ?
            ORDER BY s.document_id, s.document_version_id
            """,
            (str(request.qa_request_id),),
        ).fetchall()
        if not rows:
            raise NoEligibleIndex("retrieval scope has no eligible ACTIVE index")
        document_ids = tuple(row["document_id"] for row in rows)
        if len(set(document_ids)) != len(document_ids) or any(
            row["workspace_id"] != str(request.workspace_id)
            or row["version_workspace_id"] != str(request.workspace_id)
            or row["version_document_id"] != row["document_id"]
            or row["document_state"] != "ACTIVE"
            or row["version_state"] != "ACTIVE"
            or not isinstance(row["display_name_ciphertext"], bytes)
            for row in rows
        ):
            raise RetrievalIntegrityError("QA retrieval scope is invalid")
        return tuple(rows)

    @staticmethod
    def _select_scope_rows(
        request: QaRetrievalRequest,
        rows: tuple[sqlite3.Row, ...],
    ) -> tuple[sqlite3.Row, ...]:
        if request.document_ids is None:
            return rows
        selected = tuple(
            row for row in rows if DocumentId(row["document_id"]) in request.document_ids
        )
        if {DocumentId(row["document_id"]) for row in selected} != set(
            request.document_ids
        ):
            raise RetrievalIntegrityError("QA retrieval narrowing is invalid")
        return selected

    def _active_generation_rows(
        self,
        workspace_id: WorkspaceId,
        scope_row: sqlite3.Row,
    ) -> tuple[sqlite3.Row, ...]:
        return tuple(
            self._connection.execute(
                """
                SELECT g.*, m.purpose AS model_purpose,
                       m.dimensions AS model_dimensions,
                       j.workspace_id AS job_workspace_id,
                       j.document_version_id AS job_version_id,
                       j.state AS job_state, j.stage AS job_stage
                FROM index_generations AS g
                LEFT JOIN local_models AS m ON m.id = g.embedding_model_id
                LEFT JOIN document_processing_jobs AS j
                  ON j.id = g.processing_job_id AND j.workspace_id = g.workspace_id
                WHERE g.workspace_id = ? AND g.document_version_id = ?
                  AND g.state = 'ACTIVE'
                ORDER BY g.id
                """,
                (str(workspace_id), scope_row["document_version_id"]),
            ).fetchall()
        )

    def _map_resolved_generation(
        self,
        scope_row: sqlite3.Row,
        generation_row: sqlite3.Row,
    ) -> ResolvedRetrievalGeneration:
        if (
            generation_row["workspace_id"] != scope_row["workspace_id"]
            or generation_row["document_version_id"]
            != scope_row["document_version_id"]
            or generation_row["state"] != "ACTIVE"
            or generation_row["model_purpose"] != "EMBEDDING"
            or generation_row["model_dimensions"]
            != generation_row["embedding_dimensions"]
            or generation_row["job_workspace_id"] != scope_row["workspace_id"]
            or generation_row["job_version_id"] != scope_row["document_version_id"]
            or generation_row["job_state"] not in ("READY", "READY_WITH_WARNINGS")
            or generation_row["job_stage"] != "CHUNKING"
            or generation_row["vector_dtype"] != EMBEDDING_DTYPE
            or not isinstance(generation_row["chunk_count"], int)
            or generation_row["chunk_count"] < 1
            or generation_row["activated_at"] is None
            or generation_row["archived_at"] is not None
        ):
            raise RetrievalIntegrityError("retrieval generation mapping is invalid")
        workspace_id = WorkspaceId(generation_row["workspace_id"])
        document_id = DocumentId(scope_row["document_id"])
        generation = IndexGeneration(
            IndexGenerationId(generation_row["id"]),
            workspace_id,
            DocumentVersionId(generation_row["document_version_id"]),
            ProcessingJobId(generation_row["processing_job_id"]),
            LocalModelId(generation_row["embedding_model_id"]),
            generation_row["chunking_profile_version"],
            generation_row["normalization_profile_version"],
            generation_row["embedding_dimensions"],
            IndexGenerationState.ACTIVE,
        )
        persisted = PersistedIndexGeneration(
            generation,
            self._parse_timestamp(generation_row["created_at"]),
            self._parse_timestamp(generation_row["activated_at"]),
        )
        display_name = self._decode_text(
            scope_row["display_name_ciphertext"],
            workspace_id=workspace_id,
            owner_id=str(document_id),
            purpose=_DOCUMENT_NAME_PURPOSE,
        )
        return ResolvedRetrievalGeneration(
            document_id,
            VersionNumber(scope_row["version_number"]),
            display_name,
            persisted,
            ProcessingJobState(generation_row["job_state"]),
        )

    def _generation_candidates(
        self,
        resolved: ResolvedRetrievalGeneration,
    ) -> tuple[RetrievalCandidate, ...]:
        generation = resolved.persisted.generation
        rows = self._connection.execute(
            """
            SELECT c.id AS chunk_id, c.workspace_id AS chunk_workspace_id,
                   c.index_generation_id AS chunk_generation_id,
                   c.document_version_id AS chunk_version_id,
                   c.page_id AS chunk_page_id,
                   c.source_locator_id AS chunk_locator_id,
                   c.document_order, c.page_order, c.text_ciphertext,
                   c.normalized_text_fingerprint, c.character_count,
                   c.token_count_estimate, c.extraction_method,
                   c.created_at AS chunk_created_at,
                   c.source_start_offset, c.source_end_offset,
                   e.chunk_id AS embedding_chunk_id,
                   e.workspace_id AS embedding_workspace_id,
                   e.index_generation_id AS embedding_generation_id,
                   e.embedding_model_id, e.dimensions, e.dtype,
                   e.is_unit_normalized, e.vector_ciphertext,
                   e.created_at AS embedding_created_at,
                   p.workspace_id AS page_workspace_id,
                   p.document_version_id AS page_version_id,
                   p.page_number, p.state AS page_state,
                   p.extraction_method AS page_extraction_method,
                   p.text_ciphertext AS page_text_ciphertext,
                   p.character_count AS page_character_count,
                   l.workspace_id AS locator_workspace_id,
                   l.document_version_id AS locator_version_id,
                   l.page_id AS locator_page_id,
                   l.locator_kind, l.page_number AS locator_page_number,
                   l.locator_version, l.geometry_json_ciphertext
            FROM chunks AS c
            LEFT JOIN embeddings AS e ON e.chunk_id = c.id
            LEFT JOIN document_pages AS p ON p.id = c.page_id
            LEFT JOIN source_locators AS l ON l.id = c.source_locator_id
            WHERE c.index_generation_id = ? OR e.index_generation_id = ?
            ORDER BY c.document_order, c.id
            """,
            (str(generation.id), str(generation.id)),
        ).fetchall()
        if len(rows) != self._generation_chunk_count(generation.id) or not rows:
            raise RetrievalIntegrityError("retrieval candidate graph is incomplete")
        if tuple(row["document_order"] for row in rows) != tuple(range(len(rows))):
            raise RetrievalIntegrityError("retrieval candidate order is invalid")
        return tuple(self._map_candidate(row, resolved) for row in rows)

    def _generation_chunk_count(self, generation_id: IndexGenerationId) -> int:
        row = self._connection.execute(
            "SELECT chunk_count FROM index_generations WHERE id = ?",
            (str(generation_id),),
        ).fetchone()
        if row is None or not isinstance(row["chunk_count"], int):
            raise RetrievalIntegrityError("retrieval generation count is invalid")
        return row["chunk_count"]

    def _map_candidate(
        self,
        row: sqlite3.Row,
        resolved: ResolvedRetrievalGeneration,
    ) -> RetrievalCandidate:
        generation = resolved.persisted.generation
        if not self._valid_candidate_row(row, resolved):
            raise RetrievalIntegrityError("retrieval candidate mapping is invalid")
        chunk_id = ChunkId(row["chunk_id"])
        page_id = DocumentPageId(row["chunk_page_id"])
        locator = SourceLocator(
            SourceLocatorId(row["chunk_locator_id"]),
            generation.workspace_id,
            generation.document_version_id,
            page_id,
            PageNumber(row["page_number"]),
            SourceLocatorKind(row["locator_kind"]),
        )
        compatibility = EmbeddingCompatibility(
            generation.workspace_id,
            generation.id,
            generation.embedding_model_id,
            generation.chunking_profile_version,
            generation.normalization_profile_version,
            generation.embedding_dimensions,
        )
        passage = self._index_repository._decode_chunk_text(
            row["text_ciphertext"], generation.workspace_id, chunk_id
        )
        page_text = self._decode_text(
            row["page_text_ciphertext"],
            workspace_id=generation.workspace_id,
            owner_id=str(page_id),
            purpose="document-page-text",
        )
        start = row["source_start_offset"]
        end = row["source_end_offset"]
        if (
            page_text[start:end] != passage
            or len(page_text) != row["page_character_count"]
            or len(passage) != row["character_count"]
            or len(passage) != end - start
        ):
            raise RetrievalIntegrityError("retrieval source range is invalid")
        embedding = ChunkEmbedding(
            chunk_id,
            compatibility,
            self._embedding_repository._decode_vector(
                row["vector_ciphertext"], chunk_id, compatibility
            ),
            self._parse_timestamp(row["embedding_created_at"]),
        )
        self._parse_timestamp(row["chunk_created_at"])
        return RetrievalCandidate(
            resolved,
            embedding,
            row["document_order"],
            locator,
            passage,
        )

    @staticmethod
    def _valid_candidate_row(
        row: sqlite3.Row,
        resolved: ResolvedRetrievalGeneration,
    ) -> bool:
        generation = resolved.persisted.generation
        return (
            row["chunk_workspace_id"] == str(generation.workspace_id)
            and row["chunk_generation_id"] == str(generation.id)
            and row["chunk_version_id"] == str(generation.document_version_id)
            and row["embedding_chunk_id"] == row["chunk_id"]
            and row["embedding_workspace_id"] == str(generation.workspace_id)
            and row["embedding_generation_id"] == str(generation.id)
            and row["embedding_model_id"] == str(generation.embedding_model_id)
            and row["dimensions"] == generation.embedding_dimensions
            and row["dtype"] == EMBEDDING_DTYPE
            and row["is_unit_normalized"] == 1
            and row["page_workspace_id"] == str(generation.workspace_id)
            and row["page_version_id"] == str(generation.document_version_id)
            and row["page_state"] == "READY"
            and row["page_extraction_method"] == "NATIVE"
            and row["extraction_method"] == "NATIVE"
            and row["locator_workspace_id"] == str(generation.workspace_id)
            and row["locator_version_id"] == str(generation.document_version_id)
            and row["locator_page_id"] == row["chunk_page_id"]
            and row["locator_page_number"] == row["page_number"]
            and row["locator_kind"] == "PAGE"
            and row["locator_version"] == 1
            and row["geometry_json_ciphertext"] is None
            and isinstance(row["document_order"], int)
            and row["document_order"] >= 0
            and isinstance(row["page_order"], int)
            and row["page_order"] >= 0
            and isinstance(row["source_start_offset"], int)
            and isinstance(row["source_end_offset"], int)
            and row["source_start_offset"] >= 0
            and row["source_end_offset"] > row["source_start_offset"]
            and row["token_count_estimate"] is None
            and isinstance(row["normalized_text_fingerprint"], bytes)
            and bool(row["normalized_text_fingerprint"])
        )

    def _map_registration(
        self,
        row: sqlite3.Row,
        workspace_id: WorkspaceId,
        qa_request_id: QaRequestId,
    ) -> RetrievalRegistration:
        if (
            row["workspace_id"] != str(workspace_id)
            or row["purpose"] != "QA"
            or row["qa_request_id"] != str(qa_request_id)
            or row["analysis_generation_section_id"] is not None
        ):
            raise RetrievalPersistenceError("retrieval owner mapping is invalid")
        retrieval_run_id = RetrievalRunId(row["id"])
        query = self._decode_text(
            row["query_ciphertext"],
            workspace_id=workspace_id,
            owner_id=str(retrieval_run_id),
            purpose=_QUERY_PURPOSE,
        )
        generation_rows = self._retrieval_generation_rows(retrieval_run_id, workspace_id)
        selected_document_ids = tuple(
            dict.fromkeys(DocumentId(item["document_id"]) for item in generation_rows)
        )
        full_request = QaRetrievalRequest(
            qa_request_id,
            workspace_id,
            query,
        )
        full_document_ids = tuple(
            DocumentId(item["document_id"])
            for item in self._qa_scope_rows(full_request)
        )
        document_ids = (
            None
            if selected_document_ids == full_document_ids
            else selected_document_ids
        )
        request = QaRetrievalRequest(
            qa_request_id,
            workspace_id,
            query,
            document_ids,
        )
        scope = self.resolve_scope(request)
        persisted_generation_ids = tuple(
            IndexGenerationId(item["index_generation_id"]) for item in generation_rows
        )
        if persisted_generation_ids != scope.generation_ids:
            raise RetrievalPersistenceError(
                "retrieval generation snapshot is inconsistent"
            )
        candidates = self.load_candidates(scope)
        if row["candidate_count"] != len(candidates.candidates):
            raise RetrievalPersistenceError(
                "retrieval candidate count is inconsistent"
            )
        configuration = RetrievalConfiguration(
            row["top_k"],
            SimilarityScore(row["min_similarity"]),
        )
        evidence = self._map_evidence_rows(
            retrieval_run_id,
            workspace_id,
            scope,
        )
        registration = RetrievalRegistration(
            retrieval_run_id,
            scope,
            configuration,
            row["candidate_count"],
            evidence,
            self._parse_timestamp(row["created_at"]),
            row["retrieval_policy_version"],
        )
        if row["embedding_model_id"] != str(registration.embedding_model_id):
            raise RetrievalPersistenceError("retrieval model mapping is invalid")
        self._validate_evidence_candidates(registration, candidates)
        return registration

    def _retrieval_generation_rows(
        self,
        retrieval_run_id: RetrievalRunId,
        workspace_id: WorkspaceId,
    ) -> tuple[sqlite3.Row, ...]:
        rows = self._connection.execute(
            """
            SELECT rg.retrieval_run_id, rg.workspace_id, rg.index_generation_id,
                   g.document_version_id, v.document_id
            FROM retrieval_run_generations AS rg
            LEFT JOIN index_generations AS g
              ON g.id = rg.index_generation_id AND g.workspace_id = rg.workspace_id
            LEFT JOIN document_versions AS v
              ON v.id = g.document_version_id AND v.workspace_id = g.workspace_id
            WHERE rg.retrieval_run_id = ?
            ORDER BY v.document_id, g.document_version_id, rg.index_generation_id
            """,
            (str(retrieval_run_id),),
        ).fetchall()
        if not rows or any(
            row["retrieval_run_id"] != str(retrieval_run_id)
            or row["workspace_id"] != str(workspace_id)
            or row["document_version_id"] is None
            or row["document_id"] is None
            for row in rows
        ):
            raise RetrievalPersistenceError(
                "retrieval generation snapshot is invalid"
            )
        return tuple(rows)

    def _map_evidence_rows(
        self,
        retrieval_run_id: RetrievalRunId,
        workspace_id: WorkspaceId,
        scope: ResolvedRetrievalScope,
    ) -> tuple[RetrievalEvidenceRegistration, ...]:
        rows = self._connection.execute(
            """
            SELECT e.*, c.index_generation_id, c.document_order,
                   c.document_version_id AS chunk_version_id,
                   l.workspace_id AS locator_workspace_id,
                   l.document_version_id AS locator_version_id,
                   l.page_id AS locator_page_id,
                   l.page_number AS locator_page_number,
                   l.locator_kind, l.locator_version,
                   l.geometry_json_ciphertext
            FROM evidence_items AS e
            LEFT JOIN chunks AS c
              ON c.id = e.chunk_id AND c.workspace_id = e.workspace_id
            LEFT JOIN source_locators AS l
              ON l.id = e.source_locator_id AND l.workspace_id = e.workspace_id
            WHERE e.retrieval_run_id = ?
            ORDER BY e.rank
            """,
            (str(retrieval_run_id),),
        ).fetchall()
        generations = {item.index_generation_id: item for item in scope.generations}
        result: list[RetrievalEvidenceRegistration] = []
        for row in rows:
            if (
                row["workspace_id"] != str(workspace_id)
                or row["retrieval_run_id"] != str(retrieval_run_id)
                or row["availability"] != EvidenceAvailability.AVAILABLE.value
                or row["chunk_id"] is None
                or row["source_locator_id"] is None
                or row["index_generation_id"] is None
                or row["chunk_version_id"] != row["document_version_id"]
                or row["locator_workspace_id"] != str(workspace_id)
                or row["locator_version_id"] != row["document_version_id"]
                or row["locator_page_number"] != row["page_number"]
                or row["locator_kind"] != "PAGE"
                or row["locator_version"] != 1
                or row["geometry_json_ciphertext"] is not None
            ):
                raise RetrievalPersistenceError("retrieval evidence mapping is invalid")
            evidence_id = EvidenceItemId(row["id"])
            generation_id = IndexGenerationId(row["index_generation_id"])
            resolved = generations.get(generation_id)
            if resolved is None:
                raise RetrievalPersistenceError("retrieval evidence ownership is invalid")
            source_locator = SourceLocator(
                SourceLocatorId(row["source_locator_id"]),
                workspace_id,
                DocumentVersionId(row["document_version_id"]),
                DocumentPageId(row["locator_page_id"]),
                PageNumber(row["page_number"]),
                SourceLocatorKind(row["locator_kind"]),
            )
            evidence = Evidence(
                evidence_id,
                workspace_id,
                retrieval_run_id,
                DocumentId(row["document_id"]),
                DocumentVersionId(row["document_version_id"]),
                PageNumber(row["page_number"]),
                EvidenceRank(row["rank"]),
                SimilarityScore(row["similarity_score"]),
                ChunkId(row["chunk_id"]),
                SourceLocatorId(row["source_locator_id"]),
                EvidenceAvailability.AVAILABLE,
            )
            result.append(
                RetrievalEvidenceRegistration(
                    evidence,
                    generation_id,
                    row["document_order"],
                    source_locator,
                    self._decode_text(
                        row["document_display_name_ciphertext"],
                        workspace_id=workspace_id,
                        owner_id=str(evidence_id),
                        purpose=_EVIDENCE_DOCUMENT_NAME_PURPOSE,
                    ),
                    VersionNumber(row["version_number"]),
                    self._decode_text(
                        row["excerpt_ciphertext"],
                        workspace_id=workspace_id,
                        owner_id=str(evidence_id),
                        purpose=_EVIDENCE_EXCERPT_PURPOSE,
                    ),
                    self._parse_timestamp(row["created_at"]),
                )
            )
        return tuple(result)

    @staticmethod
    def _validate_evidence_candidates(
        registration: RetrievalRegistration,
        candidates: RetrievalCandidateSet,
    ) -> None:
        by_chunk_id = {item.chunk_id: item for item in candidates.candidates}
        evidence_ids = tuple(item.evidence.id for item in registration.evidence)
        chunk_ids = tuple(item.evidence.chunk_id for item in registration.evidence)
        if len(set(evidence_ids)) != len(evidence_ids) or len(set(chunk_ids)) != len(
            chunk_ids
        ):
            raise RetrievalPersistenceError("retrieval evidence set is inconsistent")
        for item in registration.evidence:
            chunk_id = item.evidence.chunk_id
            candidate = by_chunk_id.get(chunk_id) if chunk_id is not None else None
            if (
                candidate is None
                or item.index_generation_id
                != candidate.generation.index_generation_id
                or item.document_order != candidate.document_order
                or item.source_locator != candidate.source_locator
                or item.evidence.document_id != candidate.generation.document_id
                or item.evidence.document_version_id
                != candidate.generation.document_version_id
                or item.evidence.page_number
                != candidate.source_locator.page_number
                or item.document_display_name
                != candidate.generation.document_display_name
                or item.version_number != candidate.generation.version_number
                or item.excerpt != candidate.passage
            ):
                raise RetrievalPersistenceError(
                    "retrieval evidence source is inconsistent"
                )

    def _insert_evidence(self, item: RetrievalEvidenceRegistration) -> None:
        evidence = item.evidence
        evidence_id = str(evidence.id)
        document_name = self._encode_text(
            item.document_display_name,
            workspace_id=evidence.workspace_id,
            owner_id=evidence_id,
            purpose=_EVIDENCE_DOCUMENT_NAME_PURPOSE,
        )
        excerpt = self._encode_text(
            item.excerpt,
            workspace_id=evidence.workspace_id,
            owner_id=evidence_id,
            purpose=_EVIDENCE_EXCERPT_PURPOSE,
        )
        self._connection.execute(
            """
            INSERT INTO evidence_items (
                id, workspace_id, retrieval_run_id, rank, chunk_id,
                source_locator_id, document_id, document_version_id,
                document_display_name_ciphertext, version_number,
                page_number, excerpt_ciphertext, similarity_score,
                availability, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'AVAILABLE', ?)
            """,
            (
                evidence_id,
                str(evidence.workspace_id),
                str(evidence.retrieval_run_id),
                evidence.rank.value,
                str(evidence.chunk_id),
                str(evidence.source_locator_id),
                str(evidence.document_id),
                str(evidence.document_version_id),
                document_name,
                item.version_number.value,
                evidence.page_number.value,
                excerpt,
                evidence.similarity_score.value,
                self._timestamp(item.created_at),
            ),
        )

    def _encode_text(
        self,
        value: str,
        *,
        workspace_id: WorkspaceId,
        owner_id: str,
        purpose: str,
    ) -> bytes:
        context, key = self._security_values(workspace_id, owner_id, purpose)
        encoded = self._payload_codec.encode(
            value.encode("utf-8"),
            context=context,
            key_reference=key,
        )
        if (
            not isinstance(encoded, EncodedSensitivePayload)
            or encoded.context != context
            or encoded.key_reference != key
            or encoded.format_version != _CODEC_FORMAT_VERSION
        ):
            raise RetrievalPersistenceError("retrieval payload is invalid")
        return encoded.payload

    def _decode_text(
        self,
        payload: object,
        *,
        workspace_id: WorkspaceId,
        owner_id: str,
        purpose: str,
    ) -> str:
        if not isinstance(payload, bytes):
            raise RetrievalPersistenceError("retrieval payload is invalid")
        context, key = self._security_values(workspace_id, owner_id, purpose)
        plaintext = self._payload_codec.decode(
            EncodedSensitivePayload(payload, context, key, _CODEC_FORMAT_VERSION),
            context=context,
            key_reference=key,
        )
        if not isinstance(plaintext, bytes):
            raise RetrievalPersistenceError("retrieval payload is invalid")
        try:
            return plaintext.decode("utf-8")
        except UnicodeDecodeError:
            raise RetrievalPersistenceError("retrieval payload is invalid") from None

    @staticmethod
    def _security_values(
        workspace_id: WorkspaceId,
        owner_id: str,
        purpose: str,
    ) -> tuple[SensitivePayloadContext, WorkspaceKeyReference]:
        return (
            SensitivePayloadContext(
                workspace_id,
                owner_id,
                purpose,
                _PAYLOAD_SCHEMA_VERSION,
            ),
            WorkspaceKeyReference(workspace_id, 1),
        )

    def _require_transaction(self) -> None:
        if not self._connection.in_transaction:
            raise RetrievalPersistenceError("retrieval transaction is not active")

    @staticmethod
    def _timestamp(value: datetime) -> str:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise RetrievalPersistenceError("retrieval timestamp is invalid")
        canonical = value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if SQLiteRetrievalRepository._parse_timestamp(canonical) != value:
            raise RetrievalPersistenceError("retrieval timestamp is invalid")
        return canonical

    @staticmethod
    def _parse_timestamp(value: object) -> datetime:
        if not isinstance(value, str) or not value.endswith("Z"):
            raise RetrievalPersistenceError("retrieval timestamp is invalid")
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError:
            raise RetrievalPersistenceError("retrieval timestamp is invalid") from None
        canonical = parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if parsed.utcoffset() != timedelta(0) or value != canonical:
            raise RetrievalPersistenceError("retrieval timestamp is invalid")
        return parsed
