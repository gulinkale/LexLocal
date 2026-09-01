"""Integration tests for SQLite native-processing persistence."""

import sqlite3
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from lexlocal.application.ports.ingestion import (
    IngestionRegistration,
    PdfInspectionResult,
    StoredBlobId,
)
from lexlocal.application.ports.processing import (
    PageExtractionMethod,
    ProcessedPage,
    ProcessedPageState,
    ProcessingFailureKind,
    ProcessingPageBatch,
    ProcessingPersistenceError,
    ProcessingTarget,
    ProcessingTerminalUpdate,
)
from lexlocal.application.ports.security import (
    ControlledSourceRef,
    EncodedSensitivePayload,
    SecurityContextMismatch,
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
from lexlocal.domain.documents import (
    DocumentVersion,
    DocumentVersionState,
    LogicalDocument,
    VersionNumber,
)
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
from lexlocal.infrastructure.persistence.migration_runner import run_migrations
from lexlocal.infrastructure.persistence.migrations import (
    default_migrations_dir,
    discover_migrations,
)
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.persistence.sqlite_ingestion_repository import (
    SQLiteIngestionRepository,
)
from lexlocal.infrastructure.persistence.sqlite_processing_repository import (
    SQLiteProcessingRepository,
)

_NOW = datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)
_WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
_DOCUMENT_ID = DocumentId("10000000-0000-4000-8000-000000000002")
_VERSION_ID = DocumentVersionId("10000000-0000-4000-8000-000000000003")
_JOB_ID = ProcessingJobId("10000000-0000-4000-8000-000000000004")


class _ContextBindingCodec:
    def encode(
        self,
        plaintext: bytes,
        *,
        context: SensitivePayloadContext,
        key_reference: WorkspaceKeyReference,
    ) -> EncodedSensitivePayload:
        marker = sha256(
            f"{context.workspace_id}:{context.owner_id}:{context.purpose}:"
            f"{context.schema_version}:{key_reference.key_version}".encode()
        ).digest()
        return EncodedSensitivePayload(
            marker + plaintext[::-1], context, key_reference, 1
        )

    def decode(
        self,
        encoded: EncodedSensitivePayload,
        *,
        context: SensitivePayloadContext,
        key_reference: WorkspaceKeyReference,
    ) -> bytes:
        expected = self.encode(
            b"", context=context, key_reference=key_reference
        ).payload
        if not encoded.payload.startswith(expected):
            raise SecurityContextMismatch("synthetic context mismatch")
        return encoded.payload[len(expected) :][::-1]


@pytest.fixture
def database(tmp_path: Path) -> sqlite3.Connection:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    connection = factory.create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
    _register_ingestion_graph(connection)
    connection.commit()
    yield connection
    connection.close()


def _register_ingestion_graph(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN")
    connection.execute(
        """
        INSERT INTO workspaces (
            id, name_ciphertext, name_lookup_fingerprint, state,
            created_at, updated_at
        ) VALUES (?, x'01', x'02', 'ACTIVE', ?, ?)
        """,
        (str(_WORKSPACE_ID), "2026-01-01T00:00:00.000Z", "2026-01-01T00:00:00.000Z"),
    )
    document = LogicalDocument(_DOCUMENT_ID, _WORKSPACE_ID)
    version = DocumentVersion(
        _VERSION_ID, _WORKSPACE_ID, _DOCUMENT_ID, VersionNumber(1)
    )
    job = ProcessingJob(
        _JOB_ID, _WORKSPACE_ID, _VERSION_ID, AttemptNumber(1)
    )
    SQLiteIngestionRepository(connection).register(
        IngestionRegistration(
            stored_blob_id=StoredBlobId("10000000-0000-4000-8000-000000000005"),
            controlled_source=ControlledSourceRef(
                _WORKSPACE_ID, "opaque-synthetic-reference"
            ),
            document=document,
            version=version,
            job=job,
            logical_filename="anonymous.pdf",
            pdf=PdfInspectionResult("application/pdf", 2),
            byte_size=42,
            duplicate_fingerprint=b"f" * 32,
            created_at=_NOW,
        )
    )


def _target() -> ProcessingTarget:
    return ProcessingTarget(_WORKSPACE_ID, _DOCUMENT_ID, _VERSION_ID, _JOB_ID, 2)


def _repository(connection: sqlite3.Connection) -> SQLiteProcessingRepository:
    return SQLiteProcessingRepository(connection, _ContextBindingCodec())


def _start(connection: sqlite3.Connection) -> SQLiteProcessingRepository:
    connection.execute("BEGIN")
    repository = _repository(connection)
    graph = repository.get_initial_graph(_target())
    repository.start(
        _target(), graph.job.transition_to(ProcessingJobState.PROCESSING), _NOW
    )
    return repository


def _page(number: int, text: str) -> ProcessedPage:
    page_id = DocumentPageId(f"20000000-0000-4000-8000-{number:012d}")
    page_number = PageNumber(number)
    return ProcessedPage(
        id=page_id,
        workspace_id=_WORKSPACE_ID,
        document_version_id=_VERSION_ID,
        page_number=page_number,
        text=text,
        state=(
            ProcessedPageState.READY
            if any(not character.isspace() for character in text)
            else ProcessedPageState.WARNING
        ),
        extraction_method=PageExtractionMethod.NATIVE,
        source_locator=SourceLocator(
            id=SourceLocatorId(f"30000000-0000-4000-8000-{number:012d}"),
            workspace_id=_WORKSPACE_ID,
            document_version_id=_VERSION_ID,
            page_id=page_id,
            page_number=page_number,
            kind=SourceLocatorKind.PAGE,
        ),
    )


def _batch() -> ProcessingPageBatch:
    return ProcessingPageBatch(
        _target(), (_page(1, "  Tam metin\n"), _page(2, "\t ")), _NOW
    )


def test_exact_page_and_locator_set_round_trips_without_plaintext(database: sqlite3.Connection) -> None:
    repository = _start(database)
    repository.stage_pages(_batch())

    stored_rows = database.execute(
        "SELECT * FROM document_pages ORDER BY page_number"
    ).fetchall()
    locator_rows = database.execute(
        "SELECT * FROM source_locators ORDER BY page_number"
    ).fetchall()
    assert stored_rows[0]["text_ciphertext"] != b"  Tam metin\n"
    assert stored_rows[0]["normalized_text_fingerprint"] is None
    assert stored_rows[1]["state"] == "WARNING"
    assert stored_rows[0]["extraction_method"] == "NATIVE"
    assert stored_rows[0]["character_count"] == len("  Tam metin\n")
    assert stored_rows[0]["word_count"] == 0
    assert stored_rows[0]["created_at"] == "2026-01-02T03:04:05.678Z"
    assert locator_rows[0]["locator_kind"] == "PAGE"
    assert locator_rows[0]["geometry_json_ciphertext"] is None
    assert locator_rows[0]["locator_version"] == 1

    pages = repository.list_pages_for_chunking(_WORKSPACE_ID, _VERSION_ID)

    assert tuple(page.page_number.value for page in pages) == (1, 2)
    assert tuple(page.text for page in pages) == ("  Tam metin\n", "\t ")
    assert tuple(page.state for page in pages) == (
        ProcessedPageState.READY,
        ProcessedPageState.WARNING,
    )
    assert all(page.source_locator.page_id == page.id for page in pages)
    job = database.execute(
        "SELECT state, stage, progress_current, progress_total FROM document_processing_jobs"
    ).fetchone()
    assert tuple(job) == ("PROCESSING", "CHUNKING", 2, 2)
    assert database.execute("SELECT COUNT(*) FROM index_generations").fetchone()[0] == 0


def test_initial_graph_and_start_are_exact_and_conditional(database: sqlite3.Connection) -> None:
    repository = _start(database)
    row = database.execute(
        "SELECT state, stage, started_at FROM document_processing_jobs"
    ).fetchone()
    assert tuple(row) == ("PROCESSING", "EXTRACTING_NATIVE_TEXT", "2026-01-02T03:04:05.678Z")

    with pytest.raises(ProcessingPersistenceError, match="unavailable"):
        repository.get_initial_graph(_target())


def test_wrong_workspace_and_stale_state_fail_without_values(database: sqlite3.Connection) -> None:
    database.execute("BEGIN")
    repository = _repository(database)
    foreign = WorkspaceId("90000000-0000-4000-8000-000000000001")
    target = ProcessingTarget(foreign, _DOCUMENT_ID, _VERSION_ID, _JOB_ID, 2)

    with pytest.raises(ProcessingPersistenceError) as captured:
        repository.get_initial_graph(target)

    assert str(foreign) not in str(captured.value)
    assert captured.value.__cause__ is None


def test_context_substitution_and_corrupt_utf8_fail_sanitized(database: sqlite3.Connection) -> None:
    repository = _start(database)
    repository.stage_pages(_batch())
    database.execute(
        """
        UPDATE document_pages
        SET text_ciphertext = (
            SELECT text_ciphertext FROM document_pages WHERE page_number = 1
        )
        WHERE page_number = 2
        """
    )

    with pytest.raises(ProcessingPersistenceError) as captured:
        repository.list_pages_for_chunking(_WORKSPACE_ID, _VERSION_ID)

    assert captured.value.__cause__ is None
    page = _page(1, "unused")
    context = SensitivePayloadContext(
        _WORKSPACE_ID, str(page.id), "document-page-text", 1
    )
    key_reference = WorkspaceKeyReference(_WORKSPACE_ID, 1)
    invalid_utf8_payload = _ContextBindingCodec().encode(
        b"\xff", context=context, key_reference=key_reference
    ).payload
    database.execute(
        "UPDATE document_pages SET text_ciphertext = ? WHERE page_number = 1",
        (invalid_utf8_payload,),
    )
    with pytest.raises(ProcessingPersistenceError) as invalid_utf8:
        repository.list_pages_for_chunking(_WORKSPACE_ID, _VERSION_ID)
    assert invalid_utf8.value.__cause__ is None


def test_corrupt_locator_and_page_count_are_rejected(database: sqlite3.Connection) -> None:
    repository = _start(database)
    repository.stage_pages(_batch())
    database.execute(
        "UPDATE source_locators SET locator_kind = 'OCR_BOUNDS' WHERE page_number = 1"
    )

    with pytest.raises(ProcessingPersistenceError) as locator_error:
        repository.list_pages_for_chunking(_WORKSPACE_ID, _VERSION_ID)

    assert locator_error.value.__cause__ is None
    database.execute("UPDATE source_locators SET locator_kind = 'PAGE'")
    database.execute("UPDATE document_versions SET page_count = 3")
    with pytest.raises(ProcessingPersistenceError, match="incomplete") as count_error:
        repository.list_pages_for_chunking(_WORKSPACE_ID, _VERSION_ID)
    assert count_error.value.__cause__ is None


@pytest.mark.parametrize(
    ("statement", "value"),
    [
        ("UPDATE document_pages SET state = ? WHERE page_number = 1", "FAILED"),
        (
            "UPDATE document_pages SET extraction_method = ? WHERE page_number = 1",
            "OCR",
        ),
        (
            "UPDATE document_pages SET updated_at = ? WHERE page_number = 1",
            "not-a-timestamp",
        ),
    ],
)
def test_corrupt_page_mapping_is_rejected(
    database: sqlite3.Connection,
    statement: str,
    value: str,
) -> None:
    repository = _start(database)
    repository.stage_pages(_batch())
    database.execute(statement, (value,))

    with pytest.raises(ProcessingPersistenceError) as captured:
        repository.list_pages_for_chunking(_WORKSPACE_ID, _VERSION_ID)

    assert captured.value.__cause__ is None


def test_preexisting_page_rows_fail_closed(database: sqlite3.Connection) -> None:
    repository = _start(database)
    batch = _batch()
    repository.stage_pages(batch)

    with pytest.raises(ProcessingPersistenceError, match="already exist"):
        repository.stage_pages(batch)


@pytest.mark.parametrize(
    ("kind", "job_state", "version_state"),
    [
        (
            ProcessingFailureKind.EXTRACTION,
            ProcessingJobState.FAILED,
            "CANDIDATE_FAILED",
        ),
        (
            ProcessingFailureKind.CANCELLED,
            ProcessingJobState.CANCELLED,
            "CANDIDATE_CANCELLED",
        ),
    ],
)
def test_terminal_state_mapping_uses_only_fixed_safe_classification(
    database: sqlite3.Connection,
    kind: ProcessingFailureKind,
    job_state: ProcessingJobState,
    version_state: str,
) -> None:
    database.execute("BEGIN")
    repository = _repository(database)
    graph = repository.get_initial_graph(_target())
    source_job = graph.job
    if job_state is ProcessingJobState.FAILED:
        source_job = graph.job.transition_to(ProcessingJobState.PROCESSING)
        repository.start(_target(), source_job, _NOW)
    update = ProcessingTerminalUpdate(
        _target(),
        graph.version.transition_to(DocumentVersionState(version_state)),
        source_job.transition_to(job_state),
        kind,
        _NOW,
    )
    repository.record_terminal(update)

    job = database.execute(
        "SELECT state, stage, error_code, error_metadata_json FROM document_processing_jobs"
    ).fetchone()
    assert tuple(job) == (job_state.value, "CLEANING_UP", kind.value, None)


def test_repository_requires_active_transaction(database: sqlite3.Connection) -> None:
    repository = _repository(database)

    with pytest.raises(ProcessingPersistenceError, match="transaction is not active"):
        repository.get_initial_graph(_target())
