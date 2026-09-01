"""Transaction rollback tests for SQLite processing page staging."""

from datetime import UTC, datetime
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
    ProcessingPageBatch,
    ProcessingPersistenceError,
    ProcessingTarget,
)
from lexlocal.application.ports.security import ControlledSourceRef
from lexlocal.domain.documents import DocumentVersion, LogicalDocument, VersionNumber
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
from lexlocal.infrastructure.persistence.sqlite_unit_of_work import SQLiteUnitOfWork
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyPayloadCodec,
)
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
)

_NOW = datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)
_WORKSPACE_ID = WorkspaceId("40000000-0000-4000-8000-000000000001")
_DOCUMENT_ID = DocumentId("40000000-0000-4000-8000-000000000002")
_VERSION_ID = DocumentVersionId("40000000-0000-4000-8000-000000000003")
_JOB_ID = ProcessingJobId("40000000-0000-4000-8000-000000000004")


def _setup(tmp_path: Path) -> SQLiteConnectionFactory:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    connection = factory.create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
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
    job = ProcessingJob(_JOB_ID, _WORKSPACE_ID, _VERSION_ID, AttemptNumber(1))
    SQLiteIngestionRepository(connection).register(
        IngestionRegistration(
            StoredBlobId("40000000-0000-4000-8000-000000000005"),
            ControlledSourceRef(_WORKSPACE_ID, "opaque-transaction-source"),
            document,
            version,
            job,
            "anonymous.pdf",
            PdfInspectionResult("application/pdf", 2),
            42,
            b"f" * 32,
            _NOW,
        )
    )
    connection.commit()
    connection.close()
    return factory


def _target() -> ProcessingTarget:
    return ProcessingTarget(_WORKSPACE_ID, _DOCUMENT_ID, _VERSION_ID, _JOB_ID, 2)


def _page(number: int) -> ProcessedPage:
    page_id = DocumentPageId(f"50000000-0000-4000-8000-{number:012d}")
    page_number = PageNumber(number)
    return ProcessedPage(
        page_id,
        _WORKSPACE_ID,
        _VERSION_ID,
        page_number,
        f"synthetic page {number}",
        ProcessedPageState.READY,
        PageExtractionMethod.NATIVE,
        SourceLocator(
            SourceLocatorId(f"60000000-0000-4000-8000-{number:012d}"),
            _WORKSPACE_ID,
            _VERSION_ID,
            page_id,
            page_number,
            SourceLocatorKind.PAGE,
        ),
    )


def _uow(factory: SQLiteConnectionFactory) -> SQLiteUnitOfWork:
    return SQLiteUnitOfWork(
        factory,
        InsecureDevelopmentOnlyWorkspaceNamePersistence(),
        InsecureDevelopmentOnlyPayloadCodec(),
    )


@pytest.mark.parametrize(
    "trigger_sql",
    [
        """
        CREATE TRIGGER fail_second_locator
        BEFORE INSERT ON source_locators
        WHEN NEW.page_number = 2
        BEGIN SELECT RAISE(ABORT, 'synthetic induced failure'); END
        """,
        """
        CREATE TRIGGER fail_chunking_handoff
        BEFORE UPDATE ON document_processing_jobs
        WHEN NEW.stage = 'CHUNKING'
        BEGIN SELECT RAISE(ABORT, 'synthetic induced failure'); END
        """,
    ],
    ids=["middle-locator", "final-state-update"],
)
def test_page_set_and_handoff_roll_back_together(
    tmp_path: Path,
    trigger_sql: str,
) -> None:
    factory = _setup(tmp_path)
    setup_connection = factory.create()
    setup_connection.execute(trigger_sql)
    setup_connection.close()

    with pytest.raises(ProcessingPersistenceError) as captured:
        with _uow(factory) as unit_of_work:
            graph = unit_of_work.processing.get_initial_graph(_target())
            unit_of_work.processing.start(
                _target(),
                graph.job.transition_to(ProcessingJobState.PROCESSING),
                _NOW,
            )
            unit_of_work.processing.stage_pages(
                ProcessingPageBatch(_target(), (_page(1), _page(2)), _NOW)
            )
            unit_of_work.commit()

    assert captured.value.__cause__ is None
    connection = factory.create()
    try:
        assert connection.execute("SELECT COUNT(*) FROM document_pages").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM source_locators").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM index_generations").fetchone()[0] == 0
        job = connection.execute(
            "SELECT state, stage FROM document_processing_jobs"
        ).fetchone()
        assert tuple(job) == ("QUEUED", "VALIDATING")
    finally:
        connection.close()
