"""End-to-end tests for the synthetic native-PDF processing slice."""

from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QGuiApplication, QPainter, QPdfWriter

from lexlocal.application.ports.ingestion import PdfInspectionResult, StoredBlobId
from lexlocal.application.ports.processing import (
    CancellationCheck,
    NativePdfExtractionError,
    ProcessedPageState,
    ProcessingCancelled,
    ProcessingPersistenceError,
    ProcessingSourceError,
    UnusableNativeText,
)
from lexlocal.bootstrap.ingestion import (
    IngestionApplicationComposition,
    compose_ingestion_application,
)
from lexlocal.bootstrap.persistence import (
    WorkspaceApplicationComposition,
    compose_workspace_application,
    initialize_persistence,
)
from lexlocal.bootstrap.processing import (
    ProcessingApplicationComposition,
    compose_processing_application,
)
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.documents import DocumentVersionState
from lexlocal.domain.identifiers import (
    DocumentId,
    DocumentPageId,
    DocumentVersionId,
    ProcessingJobId,
    SourceLocatorId,
)
from lexlocal.domain.processing import ProcessingJobState
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyControlledSourceStorage,
)

_NOW = datetime(2026, 2, 3, 4, 5, 6, 789000, tzinfo=UTC)
_T = TypeVar("_T")


@pytest.fixture(scope="module", autouse=True)
def gui_application() -> Iterator[QGuiApplication]:
    existing = QGuiApplication.instance()
    application = existing if isinstance(existing, QGuiApplication) else QGuiApplication([])
    yield application


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment="test",
        log_level="INFO",
        data_dir=tmp_path,
        security_provider="insecure-development-only",
    )


def _factory(identifier_type: Callable[[str], _T], prefix: int) -> Callable[[], _T]:
    values = iter(
        f"{prefix:08d}-0000-4000-8000-{number:012d}" for number in range(1, 10)
    )
    return lambda: identifier_type(next(values))


def _synthetic_pdf(texts: tuple[str, ...]) -> bytes:
    output = QByteArray()
    buffer = QBuffer(output)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QPdfWriter(buffer)
    painter = QPainter(writer)
    assert painter.isActive()
    for index, text in enumerate(texts):
        if index:
            assert writer.newPage()
        if text:
            painter.drawText(40, 80, text)
    painter.end()
    buffer.close()
    data = output.data()
    return data if isinstance(data, bytes) else bytes(data)


class _NeverCancelled:
    def raise_if_cancelled(self) -> None:
        return None


class _CancelAt:
    def __init__(self, checkpoint: int) -> None:
        self._checkpoint = checkpoint
        self._count = 0

    def raise_if_cancelled(self) -> None:
        self._count += 1
        if self._count == self._checkpoint:
            raise ProcessingCancelled("synthetic cancellation")


class _AcceptingInspector:
    def inspect(self, _source: bytes) -> PdfInspectionResult:
        return PdfInspectionResult("application/pdf", 1)


def _compose(
    tmp_path: Path,
    *,
    cancellation: CancellationCheck | None = None,
    accepting_inspector: bool = False,
) -> tuple[
    SQLiteConnectionFactory,
    WorkspaceApplicationComposition,
    IngestionApplicationComposition,
    ProcessingApplicationComposition,
]:
    settings = _settings(tmp_path)
    factory = initialize_persistence(settings)
    workspaces = compose_workspace_application(settings, factory)
    ingestion = compose_ingestion_application(
        settings,
        factory,
        workspaces.active_scope,
        pdf_inspector=_AcceptingInspector() if accepting_inspector else None,
        document_id_factory=_factory(DocumentId, 10),
        document_version_id_factory=_factory(DocumentVersionId, 20),
        processing_job_id_factory=_factory(ProcessingJobId, 30),
        stored_blob_id_factory=_factory(StoredBlobId, 40),
        clock=lambda: _NOW,
    )
    processing = compose_processing_application(
        settings,
        factory,
        workspaces.active_scope,
        ingestion,
        cancellation=_NeverCancelled() if cancellation is None else cancellation,
        page_id_factory=_factory(DocumentPageId, 50),
        source_locator_id_factory=_factory(SourceLocatorId, 60),
        clock=lambda: _NOW,
    )
    return factory, workspaces, ingestion, processing


def _states(factory: SQLiteConnectionFactory) -> tuple[str, str, str, int, int, int, int]:
    connection = factory.create()
    try:
        version = connection.execute("SELECT state FROM document_versions").fetchone()
        job = connection.execute(
            "SELECT state, stage FROM document_processing_jobs"
        ).fetchone()
        return (
            version["state"],
            job["state"],
            job["stage"],
            connection.execute("SELECT COUNT(*) FROM document_pages").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM source_locators").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM index_generations").fetchone()[0],
            connection.execute(
                "SELECT COUNT(*) FROM index_generations WHERE state = 'ACTIVE'"
            ).fetchone()[0],
        )
    finally:
        connection.close()


def test_real_ingestion_to_exact_chunking_handoff_uses_shared_storage(
    tmp_path: Path,
) -> None:
    factory, workspaces, ingestion, processing = _compose(tmp_path)
    workspace = workspaces.create_workspace("Anonymous Processing Workspace")
    workspaces.select_workspace(workspace.id)
    source = _synthetic_pdf(("Anonymous first page", ""))

    imported = ingestion.import_pdf(source, "anonymous.pdf")
    result = processing.process_pdf(imported)

    assert ingestion.controlled_source_storage.read(
        workspace.id, imported.controlled_source
    ) == source
    assert tuple(page.text for page in result.pages) == ("Anonymous first page", "")
    assert tuple(page.page_number.value for page in result.pages) == (1, 2)
    assert tuple(page.state for page in result.pages) == (
        ProcessedPageState.READY,
        ProcessedPageState.WARNING,
    )
    assert all(page.extraction_method.value == "NATIVE" for page in result.pages)
    assert all(page.source_locator.page_id == page.id for page in result.pages)
    assert result.job_state is ProcessingJobState.PROCESSING
    assert result.stage == "CHUNKING"
    with processing.unit_of_work_factory() as unit_of_work:
        handoff = unit_of_work.processing.list_pages_for_chunking(
            workspace.id, result.document_version_id
        )
    assert handoff == result.pages
    assert _states(factory) == (
        DocumentVersionState.CANDIDATE_PROCESSING.value,
        ProcessingJobState.PROCESSING.value,
        "CHUNKING",
        2,
        2,
        0,
        0,
    )


def test_new_storage_instance_cannot_read_ingested_source(tmp_path: Path) -> None:
    factory, workspaces, ingestion, _processing = _compose(tmp_path)
    workspace = workspaces.create_workspace("Anonymous Processing Workspace")
    workspaces.select_workspace(workspace.id)
    imported = ingestion.import_pdf(_synthetic_pdf(("Anonymous",)), "anonymous.pdf")
    replaced = replace(
        ingestion,
        controlled_source_storage=InsecureDevelopmentOnlyControlledSourceStorage(),
    )
    processing = compose_processing_application(
        _settings(tmp_path), factory, workspaces.active_scope, replaced
    )

    with pytest.raises(ProcessingSourceError) as captured:
        processing.process_pdf(imported)

    assert imported.controlled_source.value not in str(captured.value)
    assert _states(factory)[3:] == (0, 0, 0, 0)


def test_missing_or_cross_workspace_scope_rejects_source(tmp_path: Path) -> None:
    factory, workspaces, ingestion, processing = _compose(tmp_path)
    first = workspaces.create_workspace("First Anonymous Workspace")
    second = workspaces.create_workspace("Second Anonymous Workspace")
    workspaces.select_workspace(first.id)
    imported = ingestion.import_pdf(_synthetic_pdf(("Anonymous",)), "anonymous.pdf")

    workspaces.active_scope.clear()
    with pytest.raises(ProcessingSourceError):
        processing.process_pdf(imported)
    workspaces.select_workspace(second.id)
    with pytest.raises(ProcessingSourceError):
        processing.process_pdf(imported)

    assert _states(factory)[1:3] == ("QUEUED", "VALIDATING")


@pytest.mark.parametrize(
    ("source", "expected_error"),
    [
        (b"%PDF-corrupted-synthetic", NativePdfExtractionError),
        (_synthetic_pdf(("",)), UnusableNativeText),
    ],
    ids=["corrupted", "all-unusable"],
)
def test_invalid_native_text_inputs_fail_without_partial_pages(
    tmp_path: Path,
    source: bytes,
    expected_error: type[Exception],
) -> None:
    factory, workspaces, ingestion, processing = _compose(
        tmp_path,
        accepting_inspector=source.startswith(b"%PDF-corrupted"),
    )
    workspace = workspaces.create_workspace("Anonymous Processing Workspace")
    workspaces.select_workspace(workspace.id)
    imported = ingestion.import_pdf(source, "anonymous.pdf")

    with pytest.raises(expected_error) as captured:
        processing.process_pdf(imported)

    assert repr(source) not in str(captured.value)
    assert _states(factory)[3:] == (0, 0, 0, 0)


@pytest.mark.parametrize("checkpoint", [2, 5, 8], ids=["pre-read", "between-page", "pre-commit"])
def test_cancellation_leaves_no_successful_page_set(
    tmp_path: Path,
    checkpoint: int,
) -> None:
    factory, workspaces, ingestion, processing = _compose(
        tmp_path, cancellation=_CancelAt(checkpoint)
    )
    workspace = workspaces.create_workspace("Anonymous Processing Workspace")
    workspaces.select_workspace(workspace.id)
    imported = ingestion.import_pdf(
        _synthetic_pdf(("Anonymous first", "Anonymous second")), "anonymous.pdf"
    )

    with pytest.raises(ProcessingCancelled):
        processing.process_pdf(imported)

    states = _states(factory)
    assert states[:3] == ("CANDIDATE_CANCELLED", "CANCELLED", "CLEANING_UP")
    assert states[3:] == (0, 0, 0, 0)


def test_page_write_failure_rolls_back_and_records_safe_terminal_state(
    tmp_path: Path,
) -> None:
    factory, workspaces, ingestion, processing = _compose(tmp_path)
    workspace = workspaces.create_workspace("Anonymous Processing Workspace")
    workspaces.select_workspace(workspace.id)
    imported = ingestion.import_pdf(_synthetic_pdf(("Anonymous",)), "anonymous.pdf")
    connection = factory.create()
    connection.execute(
        """
        CREATE TRIGGER fail_page_write BEFORE INSERT ON document_pages
        BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END
        """
    )
    connection.close()

    with pytest.raises(ProcessingPersistenceError) as captured:
        processing.process_pdf(imported)

    assert captured.value.__cause__ is None
    assert _states(factory) == (
        "CANDIDATE_FAILED",
        "FAILED",
        "CLEANING_UP",
        0,
        0,
        0,
        0,
    )
