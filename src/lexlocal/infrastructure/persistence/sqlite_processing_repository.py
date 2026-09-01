"""Persist native PDF processing results in an existing SQLite transaction."""

import sqlite3
from datetime import datetime, timedelta

from lexlocal.application.ports.processing import (
    PageExtractionMethod,
    ProcessedPage,
    ProcessedPageState,
    ProcessingGraph,
    ProcessingPageBatch,
    ProcessingPersistenceError,
    ProcessingRepository,
    ProcessingTarget,
    ProcessingTerminalUpdate,
)
from lexlocal.application.ports.security import (
    EncodedSensitivePayload,
    SensitivePayloadCodec,
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
from lexlocal.domain.documents import DocumentVersion, DocumentVersionState, VersionNumber
from lexlocal.domain.identifiers import (
    DocumentId,
    DocumentPageId,
    DocumentVersionId,
    ProcessingJobId,
    SourceLocatorId,
    WorkspaceId,
)
from lexlocal.domain.processing import AttemptNumber, ProcessingJob, ProcessingJobState
from lexlocal.domain.retrieval import PageNumber, SourceLocator, SourceLocatorKind


class SQLiteProcessingRepository(ProcessingRepository):
    """Map processing values without owning transaction finalization."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        payload_codec: SensitivePayloadCodec,
    ) -> None:
        self._connection = connection
        self._payload_codec = payload_codec

    def get_initial_graph(self, target: ProcessingTarget) -> ProcessingGraph:
        """Load the exact queued ingestion graph for Domain validation."""

        self._require_transaction()
        if not isinstance(target, ProcessingTarget):
            raise ProcessingPersistenceError("processing target is invalid")
        try:
            row = self._connection.execute(
                """
                SELECT
                    v.id AS version_id,
                    v.workspace_id AS version_workspace_id,
                    v.document_id,
                    v.version_number,
                    v.state AS version_state,
                    v.page_count,
                    j.id AS job_id,
                    j.workspace_id AS job_workspace_id,
                    j.document_version_id AS job_version_id,
                    j.attempt_number,
                    j.state AS job_state,
                    j.stage AS job_stage
                FROM document_versions AS v
                JOIN documents AS d
                  ON d.id = v.document_id AND d.workspace_id = v.workspace_id
                JOIN document_processing_jobs AS j
                  ON j.document_version_id = v.id AND j.workspace_id = v.workspace_id
                WHERE v.id = ? AND v.workspace_id = ? AND v.document_id = ?
                  AND j.id = ?
                """,
                (
                    str(target.document_version_id),
                    str(target.workspace_id),
                    str(target.document_id),
                    str(target.processing_job_id),
                ),
            ).fetchone()
            if row is None or row["job_stage"] != "VALIDATING":
                raise ProcessingPersistenceError("processing graph is unavailable")
            graph = ProcessingGraph(
                version=DocumentVersion(
                    id=DocumentVersionId(row["version_id"]),
                    workspace_id=WorkspaceId(row["version_workspace_id"]),
                    document_id=DocumentId(row["document_id"]),
                    version_number=VersionNumber(row["version_number"]),
                    state=DocumentVersionState(row["version_state"]),
                ),
                job=ProcessingJob(
                    id=ProcessingJobId(row["job_id"]),
                    workspace_id=WorkspaceId(row["job_workspace_id"]),
                    document_version_id=DocumentVersionId(row["job_version_id"]),
                    attempt_number=AttemptNumber(row["attempt_number"]),
                    state=ProcessingJobState(row["job_state"]),
                ),
                page_count=row["page_count"],
            )
            graph.validate_target(target)
            return graph
        except ProcessingPersistenceError:
            raise
        except (sqlite3.DatabaseError, TypeError, ValueError):
            raise ProcessingPersistenceError("processing graph is invalid") from None

    def start(
        self,
        target: ProcessingTarget,
        job: ProcessingJob,
        started_at: datetime,
    ) -> None:
        """Conditionally stage the queued-to-processing transition."""

        self._require_transaction()
        if (
            not isinstance(target, ProcessingTarget)
            or not isinstance(job, ProcessingJob)
            or job.id != target.processing_job_id
            or job.workspace_id != target.workspace_id
            or job.document_version_id != target.document_version_id
            or job.state is not ProcessingJobState.PROCESSING
        ):
            raise ProcessingPersistenceError("processing start is invalid")
        timestamp = self._timestamp(started_at)
        try:
            cursor = self._connection.execute(
                """
                UPDATE document_processing_jobs
                SET state = 'PROCESSING', stage = 'EXTRACTING_NATIVE_TEXT',
                    progress_current = 0, progress_total = ?, started_at = ?,
                    heartbeat_at = ?, error_code = NULL, error_metadata_json = NULL
                WHERE id = ? AND workspace_id = ? AND document_version_id = ?
                  AND state = 'QUEUED' AND stage = 'VALIDATING'
                  AND EXISTS (
                      SELECT 1 FROM document_versions AS v
                      WHERE v.id = document_processing_jobs.document_version_id
                        AND v.workspace_id = document_processing_jobs.workspace_id
                        AND v.document_id = ?
                        AND v.state = 'CANDIDATE_PROCESSING'
                  )
                """,
                (
                    target.expected_page_count,
                    timestamp,
                    timestamp,
                    str(target.processing_job_id),
                    str(target.workspace_id),
                    str(target.document_version_id),
                    str(target.document_id),
                ),
            )
            if cursor.rowcount != 1:
                raise ProcessingPersistenceError("processing start state is stale")
        except ProcessingPersistenceError:
            raise
        except sqlite3.DatabaseError:
            raise ProcessingPersistenceError("processing start failed") from None

    def stage_pages(self, batch: ProcessingPageBatch) -> None:
        """Stage the complete page/locator set and CHUNKING handoff."""

        self._require_transaction()
        if not isinstance(batch, ProcessingPageBatch):
            raise ProcessingPersistenceError("processing page batch is invalid")
        timestamp = self._timestamp(batch.updated_at)
        try:
            existing = self._connection.execute(
                """
                SELECT 1 FROM document_pages
                WHERE workspace_id = ? AND document_version_id = ? LIMIT 1
                """,
                (str(batch.target.workspace_id), str(batch.target.document_version_id)),
            ).fetchone()
            if existing is not None:
                raise ProcessingPersistenceError("processing pages already exist")

            for page in batch.pages:
                encoded_text = self._encode_page_text(page)
                self._connection.execute(
                    """
                    INSERT INTO document_pages (
                        id, workspace_id, document_version_id, page_number,
                        state, extraction_method, text_ciphertext,
                        normalized_text_fingerprint, character_count, word_count,
                        warning_codes_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, 0, NULL, ?, ?)
                    """,
                    (
                        str(page.id),
                        str(page.workspace_id),
                        str(page.document_version_id),
                        page.page_number.value,
                        page.state.value,
                        page.extraction_method.value,
                        encoded_text,
                        len(page.text),
                        timestamp,
                        timestamp,
                    ),
                )
                self._connection.execute(
                    """
                    INSERT INTO source_locators (
                        id, workspace_id, document_version_id, page_id,
                        locator_kind, page_number, geometry_json_ciphertext,
                        locator_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, 1, ?)
                    """,
                    (
                        str(page.source_locator.id),
                        str(page.source_locator.workspace_id),
                        str(page.source_locator.document_version_id),
                        str(page.source_locator.page_id),
                        page.source_locator.kind.value,
                        page.source_locator.page_number.value,
                        timestamp,
                    ),
                )

            cursor = self._connection.execute(
                """
                UPDATE document_processing_jobs
                SET stage = 'CHUNKING', progress_current = ?, progress_total = ?,
                    heartbeat_at = ?
                WHERE id = ? AND workspace_id = ? AND document_version_id = ?
                  AND state = 'PROCESSING' AND stage = 'EXTRACTING_NATIVE_TEXT'
                  AND EXISTS (
                      SELECT 1 FROM document_versions AS v
                      WHERE v.id = document_processing_jobs.document_version_id
                        AND v.workspace_id = document_processing_jobs.workspace_id
                        AND v.document_id = ?
                        AND v.state = 'CANDIDATE_PROCESSING'
                  )
                """,
                (
                    len(batch.pages),
                    batch.target.expected_page_count,
                    timestamp,
                    str(batch.target.processing_job_id),
                    str(batch.target.workspace_id),
                    str(batch.target.document_version_id),
                    str(batch.target.document_id),
                ),
            )
            if cursor.rowcount != 1:
                raise ProcessingPersistenceError("processing handoff state is stale")
        except ProcessingPersistenceError:
            raise
        except Exception:
            raise ProcessingPersistenceError("processing page persistence failed") from None

    def record_terminal(self, update: ProcessingTerminalUpdate) -> None:
        """Stage one fixed safe failure or cancellation transition."""

        self._require_transaction()
        if not isinstance(update, ProcessingTerminalUpdate):
            raise ProcessingPersistenceError("processing terminal update is invalid")
        timestamp = self._timestamp(update.completed_at)
        try:
            version_cursor = self._connection.execute(
                """
                UPDATE document_versions SET state = ?
                WHERE id = ? AND workspace_id = ? AND document_id = ?
                  AND state = 'CANDIDATE_PROCESSING'
                """,
                (
                    update.version.state.value,
                    str(update.target.document_version_id),
                    str(update.target.workspace_id),
                    str(update.target.document_id),
                ),
            )
            job_cursor = self._connection.execute(
                """
                UPDATE document_processing_jobs
                SET state = ?, stage = 'CLEANING_UP', error_code = ?,
                    error_metadata_json = NULL, completed_at = ?, heartbeat_at = ?
                WHERE id = ? AND workspace_id = ? AND document_version_id = ?
                  AND state IN ('QUEUED', 'PROCESSING')
                """,
                (
                    update.job.state.value,
                    update.failure_kind.value,
                    timestamp,
                    timestamp,
                    str(update.target.processing_job_id),
                    str(update.target.workspace_id),
                    str(update.target.document_version_id),
                ),
            )
            if version_cursor.rowcount != 1 or job_cursor.rowcount != 1:
                raise ProcessingPersistenceError("processing terminal state is stale")
        except ProcessingPersistenceError:
            raise
        except Exception:
            raise ProcessingPersistenceError("processing terminal update failed") from None

    def list_pages_for_chunking(
        self,
        workspace_id: WorkspaceId,
        document_version_id: DocumentVersionId,
    ) -> tuple[ProcessedPage, ...]:
        """Return exact ordered page/provenance values for INDEX-001."""

        self._require_transaction()
        if not isinstance(workspace_id, WorkspaceId) or not isinstance(
            document_version_id, DocumentVersionId
        ):
            raise ProcessingPersistenceError("processing handoff request is invalid")
        try:
            metadata = self._connection.execute(
                """
                SELECT v.page_count
                FROM document_versions AS v
                WHERE v.id = ? AND v.workspace_id = ?
                  AND v.state = 'CANDIDATE_PROCESSING'
                  AND EXISTS (
                      SELECT 1 FROM document_processing_jobs AS j
                      WHERE j.document_version_id = v.id
                        AND j.workspace_id = v.workspace_id
                        AND j.state = 'PROCESSING' AND j.stage = 'CHUNKING'
                  )
                """,
                (str(document_version_id), str(workspace_id)),
            ).fetchone()
            if metadata is None or isinstance(metadata["page_count"], bool) or not isinstance(
                metadata["page_count"], int
            ):
                raise ProcessingPersistenceError("processing handoff is unavailable")
            rows = self._connection.execute(
                """
                SELECT
                    p.id AS page_id, p.workspace_id, p.document_version_id,
                    p.page_number, p.state AS page_state, p.extraction_method,
                    p.text_ciphertext, p.character_count, p.word_count,
                    p.normalized_text_fingerprint, p.warning_codes_json,
                    p.created_at, p.updated_at,
                    l.id AS locator_id, l.locator_kind, l.page_number AS locator_page_number,
                    l.geometry_json_ciphertext, l.locator_version, l.created_at AS locator_created_at
                FROM document_pages AS p
                JOIN source_locators AS l
                  ON l.page_id = p.id AND l.workspace_id = p.workspace_id
                WHERE p.workspace_id = ? AND p.document_version_id = ?
                ORDER BY p.page_number
                """,
                (str(workspace_id), str(document_version_id)),
            ).fetchall()
            if len(rows) != metadata["page_count"]:
                raise ProcessingPersistenceError("processing handoff is incomplete")
            pages = tuple(
                self._map_page(row, workspace_id, document_version_id) for row in rows
            )
            if tuple(page.page_number.value for page in pages) != tuple(
                range(1, metadata["page_count"] + 1)
            ):
                raise ProcessingPersistenceError("processing handoff order is invalid")
            return pages
        except ProcessingPersistenceError:
            raise
        except Exception:
            raise ProcessingPersistenceError("processing handoff is invalid") from None

    def _map_page(
        self,
        row: sqlite3.Row,
        workspace_id: WorkspaceId,
        document_version_id: DocumentVersionId,
    ) -> ProcessedPage:
        if (
            row["workspace_id"] != str(workspace_id)
            or row["document_version_id"] != str(document_version_id)
            or row["locator_kind"] != SourceLocatorKind.PAGE.value
            or row["locator_page_number"] != row["page_number"]
            or row["locator_version"] != 1
            or row["geometry_json_ciphertext"] is not None
            or row["normalized_text_fingerprint"] is not None
            or row["warning_codes_json"] is not None
            or row["word_count"] != 0
        ):
            raise ProcessingPersistenceError("processing handoff mapping is invalid")
        self._parse_timestamp(row["created_at"])
        self._parse_timestamp(row["updated_at"])
        self._parse_timestamp(row["locator_created_at"])
        page_id = DocumentPageId(row["page_id"])
        page_number = PageNumber(row["page_number"])
        text = self._decode_page_text(
            row["text_ciphertext"], workspace_id, page_id
        )
        if row["character_count"] != len(text):
            raise ProcessingPersistenceError("processing handoff mapping is invalid")
        locator = SourceLocator(
            id=SourceLocatorId(row["locator_id"]),
            workspace_id=workspace_id,
            document_version_id=document_version_id,
            page_id=page_id,
            page_number=page_number,
            kind=SourceLocatorKind(row["locator_kind"]),
        )
        return ProcessedPage(
            id=page_id,
            workspace_id=workspace_id,
            document_version_id=document_version_id,
            page_number=page_number,
            text=text,
            state=ProcessedPageState(row["page_state"]),
            extraction_method=PageExtractionMethod(row["extraction_method"]),
            source_locator=locator,
        )

    def _encode_page_text(self, page: ProcessedPage) -> bytes:
        context, key_reference = self._page_security_values(page.workspace_id, page.id)
        encoded = self._payload_codec.encode(
            page.text.encode("utf-8"),
            context=context,
            key_reference=key_reference,
        )
        if (
            not isinstance(encoded, EncodedSensitivePayload)
            or encoded.context != context
            or encoded.key_reference != key_reference
            or encoded.format_version != 1
        ):
            raise ProcessingPersistenceError("processing page payload is invalid")
        return encoded.payload

    def _decode_page_text(
        self,
        payload: object,
        workspace_id: WorkspaceId,
        page_id: DocumentPageId,
    ) -> str:
        if not isinstance(payload, bytes):
            raise ProcessingPersistenceError("processing handoff payload is invalid")
        context, key_reference = self._page_security_values(workspace_id, page_id)
        encoded = EncodedSensitivePayload(payload, context, key_reference, 1)
        plaintext = self._payload_codec.decode(
            encoded,
            context=context,
            key_reference=key_reference,
        )
        if not isinstance(plaintext, bytes):
            raise ProcessingPersistenceError("processing handoff payload is invalid")
        return plaintext.decode("utf-8")

    @staticmethod
    def _page_security_values(
        workspace_id: WorkspaceId,
        page_id: DocumentPageId,
    ) -> tuple[SensitivePayloadContext, WorkspaceKeyReference]:
        return (
            SensitivePayloadContext(
                workspace_id,
                str(page_id),
                "document-page-text",
                1,
            ),
            WorkspaceKeyReference(workspace_id, 1),
        )

    def _require_transaction(self) -> None:
        if not self._connection.in_transaction:
            raise ProcessingPersistenceError("processing transaction is not active")

    @staticmethod
    def _timestamp(value: datetime) -> str:
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() != timedelta(0)
        ):
            raise ProcessingPersistenceError("processing timestamp is invalid")
        return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    @staticmethod
    def _parse_timestamp(value: object) -> None:
        if not isinstance(value, str) or not value.endswith("Z"):
            raise ProcessingPersistenceError("processing handoff timestamp is invalid")
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        canonical = parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if parsed.utcoffset() != timedelta(0) or value != canonical:
            raise ProcessingPersistenceError("processing handoff timestamp is invalid")
