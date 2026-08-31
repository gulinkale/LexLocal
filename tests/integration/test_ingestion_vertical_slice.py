"""End-to-end tests for the synthetic PDF ingestion vertical slice."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QGuiApplication, QPainter, QPdfWriter

from lexlocal.application.ports.ingestion import (
    DuplicateDocument,
    IngestionPersistenceError,
    IngestionStorageError,
    StoredBlobId,
)
from lexlocal.application.ports.security import (
    ControlledSourceRef,
    SecurityContractError,
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
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import DocumentId, DocumentVersionId, ProcessingJobId, WorkspaceId
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyControlledSourceStorage,
)


@pytest.fixture(scope="module", autouse=True)
def gui_application() -> Iterator[QGuiApplication]:
    existing = QGuiApplication.instance()
    application = existing if isinstance(existing, QGuiApplication) else QGuiApplication([])
    yield application


def _synthetic_pdf() -> bytes:
    output = QByteArray()
    buffer = QBuffer(output)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QPdfWriter(buffer)
    painter = QPainter(writer)
    assert painter.isActive()
    painter.drawRect(20, 20, 24, 24)
    painter.end()
    buffer.close()
    return bytes(output)


class _TrackingStorage:
    def __init__(self, *, fail_store: bool = False) -> None:
        self.delegate = InsecureDevelopmentOnlyControlledSourceStorage()
        self.fail_store = fail_store
        self.stored: list[ControlledSourceRef] = []
        self.deleted: list[ControlledSourceRef] = []

    def store(self, workspace_id: WorkspaceId, source: bytes) -> ControlledSourceRef:
        if self.fail_store:
            raise SecurityContractError("synthetic storage unavailable")
        reference = self.delegate.store(workspace_id, source)
        self.stored.append(reference)
        return reference

    def read(self, workspace_id: WorkspaceId, reference: ControlledSourceRef) -> bytes:
        return self.delegate.read(workspace_id, reference)

    def delete(self, workspace_id: WorkspaceId, reference: ControlledSourceRef) -> None:
        self.delegate.delete(workspace_id, reference)
        self.deleted.append(reference)


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment="test",
        log_level="INFO",
        data_dir=tmp_path,
        security_provider="insecure-development-only",
    )


_T = TypeVar("_T")


def _factory(
    identifier_type: Callable[[str], _T],
    values: list[str],
) -> Callable[[], _T]:
    iterator = iter(values)
    return lambda: identifier_type(next(iterator))


def _compose(
    tmp_path: Path,
    storage: _TrackingStorage,
) -> tuple[
    SQLiteConnectionFactory,
    WorkspaceApplicationComposition,
    IngestionApplicationComposition,
]:
    settings = _settings(tmp_path)
    connection_factory = initialize_persistence(settings)
    workspaces = compose_workspace_application(settings, connection_factory)
    ids = [f"{number:08d}-0000-4000-8000-000000000001" for number in range(1, 9)]
    ingestion = compose_ingestion_application(
        settings,
        connection_factory,
        workspaces.active_scope,
        controlled_source_storage=storage,
        document_id_factory=_factory(DocumentId, ids[0:2]),
        document_version_id_factory=_factory(DocumentVersionId, ids[2:4]),
        processing_job_id_factory=_factory(ProcessingJobId, ids[4:6]),
        stored_blob_id_factory=_factory(StoredBlobId, ids[6:8]),
        clock=lambda: datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC),
    )
    return connection_factory, workspaces, ingestion


def _counts(factory: SQLiteConnectionFactory) -> tuple[int, int, int, int]:
    connection = factory.create()
    try:
        return (
            connection.execute("SELECT COUNT(*) FROM stored_blobs").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0],
            connection.execute(
                "SELECT COUNT(*) FROM document_processing_jobs"
            ).fetchone()[0],
        )
    finally:
        connection.close()


def test_valid_pdf_is_committed_and_exact_bytes_remain_controlled(
    tmp_path: Path,
) -> None:
    storage = _TrackingStorage()
    factory, workspaces, ingestion = _compose(tmp_path, storage)
    workspace = workspaces.create_workspace("Anonymous Workspace")
    workspaces.select_workspace(workspace.id)
    source = _synthetic_pdf()

    result = ingestion.import_pdf(source, "anonymous.pdf")

    assert result.document_id == DocumentId("00000001-0000-4000-8000-000000000001")
    assert result.document_version_id == DocumentVersionId(
        "00000003-0000-4000-8000-000000000001"
    )
    assert result.processing_job_id == ProcessingJobId(
        "00000005-0000-4000-8000-000000000001"
    )
    assert ingestion.controlled_source_storage.read(
        workspace.id, result.controlled_source
    ) == source
    assert _counts(factory) == (1, 1, 1, 1)
    connection = factory.create()
    try:
        blob = connection.execute(
            "SELECT id, created_at FROM stored_blobs"
        ).fetchone()
        assert blob["id"] == "00000007-0000-4000-8000-000000000001"
        assert blob["created_at"] == "2026-01-02T03:04:05.678Z"
    finally:
        connection.close()


def test_same_workspace_duplicate_rolls_back_and_deletes_new_source(
    tmp_path: Path,
) -> None:
    storage = _TrackingStorage()
    factory, workspaces, ingestion = _compose(tmp_path, storage)
    workspace = workspaces.create_workspace("Anonymous Workspace")
    workspaces.select_workspace(workspace.id)
    source = _synthetic_pdf()
    first = ingestion.import_pdf(source, "first.pdf")

    with pytest.raises(DuplicateDocument):
        ingestion.import_pdf(source, "second.pdf")

    assert _counts(factory) == (1, 1, 1, 1)
    assert storage.deleted == [storage.stored[1]]
    assert storage.read(workspace.id, first.controlled_source) == source
    with pytest.raises(SecurityContractError):
        storage.read(workspace.id, storage.stored[1])


def test_same_content_in_different_workspace_is_allowed(tmp_path: Path) -> None:
    storage = _TrackingStorage()
    factory, workspaces, ingestion = _compose(tmp_path, storage)
    first = workspaces.create_workspace("First Anonymous Workspace")
    second = workspaces.create_workspace("Second Anonymous Workspace")
    source = _synthetic_pdf()

    workspaces.select_workspace(first.id)
    ingestion.import_pdf(source, "first.pdf")
    workspaces.select_workspace(second.id)
    ingestion.import_pdf(source, "second.pdf")

    assert _counts(factory) == (2, 2, 2, 2)


def test_storage_failure_creates_no_database_graph(tmp_path: Path) -> None:
    storage = _TrackingStorage(fail_store=True)
    factory, workspaces, ingestion = _compose(tmp_path, storage)
    workspace = workspaces.create_workspace("Anonymous Workspace")
    workspaces.select_workspace(workspace.id)

    with pytest.raises(IngestionStorageError):
        ingestion.import_pdf(_synthetic_pdf(), "anonymous.pdf")

    assert _counts(factory) == (0, 0, 0, 0)


def test_registration_failure_rolls_back_and_deletes_stored_source(
    tmp_path: Path,
) -> None:
    storage = _TrackingStorage()
    factory, workspaces, ingestion = _compose(tmp_path, storage)
    workspace = workspaces.create_workspace("Anonymous Workspace")
    workspaces.select_workspace(workspace.id)
    connection = factory.create()
    connection.execute("DROP TABLE document_processing_jobs")
    connection.close()

    with pytest.raises(IngestionPersistenceError):
        ingestion.import_pdf(_synthetic_pdf(), "anonymous.pdf")

    assert storage.deleted == storage.stored
    with pytest.raises(SecurityContractError):
        storage.read(workspace.id, storage.stored[0])
    connection = factory.create()
    try:
        assert connection.execute("SELECT COUNT(*) FROM stored_blobs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0] == 0
    finally:
        connection.close()
