"""End-to-end tests for the synthetic processing-to-index slice."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QGuiApplication, QPainter, QPdfWriter

from lexlocal.application.ports.indexing import (
    IndexingCancelled,
    IndexingError,
    IndexingPersistenceError,
    StagingEmbeddingHandoff,
)
from lexlocal.application.ports.ingestion import StoredBlobId
from lexlocal.application.ports.local_models import (
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
    ResolvedModelRecord,
)
from lexlocal.bootstrap import indexing as indexing_bootstrap
from lexlocal.bootstrap.indexing import (
    IndexingApplicationComposition,
    compose_indexing_application,
)
from lexlocal.bootstrap.ingestion import compose_ingestion_application
from lexlocal.bootstrap.persistence import (
    WorkspaceApplicationComposition,
    compose_workspace_application,
    initialize_persistence,
)
from lexlocal.bootstrap.processing import compose_processing_application
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import (
    ChunkId,
    DocumentId,
    DocumentPageId,
    DocumentVersionId,
    IndexGenerationId,
    LocalModelId,
    ProcessingJobId,
    SourceLocatorId,
)
from lexlocal.domain.processing import IndexGenerationState
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.persistence.sqlite_unit_of_work import SQLiteUnitOfWork

NOW = datetime(2026, 2, 3, 4, 5, 6, 789000, tzinfo=UTC)
MODEL = ResolvedModelRecord(
    LocalModelId("90000000-0000-4000-8000-000000000001"),
    "qwen3-embedding-0.6b",
    "synthetic-resolved",
    "1",
    ModelCapability.EMBEDDING,
    "synthetic",
    8,
)
T = TypeVar("T")


@pytest.fixture(scope="module", autouse=True)
def gui_application() -> Iterator[QGuiApplication]:
    existing = QGuiApplication.instance()
    application = existing if isinstance(existing, QGuiApplication) else QGuiApplication([])
    yield application


class _NeverCancelled:
    def raise_if_cancelled(self) -> None:
        return None


class _Cancelled:
    def raise_if_cancelled(self) -> None:
        raise IndexingCancelled("synthetic fixture detail")


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment="test",
        log_level="INFO",
        data_dir=tmp_path,
        security_provider="insecure-development-only",
        index_chunk_size=8,
        index_chunk_overlap=2,
    )


def _factory(identifier_type: Callable[[str], T], prefix: int) -> Callable[[], T]:
    values = iter(f"{prefix:08d}-0000-4000-8000-{number:012d}" for number in range(1, 100))
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


def _compose(
    tmp_path: Path,
    *,
    cancellation: _NeverCancelled | _Cancelled | None = None,
) -> tuple[
    SQLiteConnectionFactory,
    WorkspaceApplicationComposition,
    IndexingApplicationComposition,
    object,
    object,
]:
    settings = _settings(tmp_path)
    connection_factory = initialize_persistence(settings)
    workspaces = compose_workspace_application(settings, connection_factory)
    ingestion = compose_ingestion_application(
        settings,
        connection_factory,
        workspaces.active_scope,
        document_id_factory=_factory(DocumentId, 10),
        document_version_id_factory=_factory(DocumentVersionId, 20),
        processing_job_id_factory=_factory(ProcessingJobId, 30),
        stored_blob_id_factory=_factory(StoredBlobId, 40),
        clock=lambda: NOW,
    )
    processing = compose_processing_application(
        settings,
        connection_factory,
        workspaces.active_scope,
        ingestion,
        page_id_factory=_factory(DocumentPageId, 50),
        source_locator_id_factory=_factory(SourceLocatorId, 60),
        clock=lambda: NOW,
    )
    with processing.unit_of_work_factory() as unit_of_work:
        assert unit_of_work.local_models.get_or_add_exact(MODEL) == MODEL
        unit_of_work.commit()
    indexing = compose_indexing_application(
        settings,
        connection_factory,
        workspaces.active_scope,
        LocalModelStatus(MODEL, ModelReadiness.READY, "synthetic-execution"),
        sensitive_payload_codec=ingestion.sensitive_payload_codec,
        cancellation=cancellation or _NeverCancelled(),
        chunk_id_factory=_factory(ChunkId, 70),
        index_generation_id_factory=_factory(IndexGenerationId, 80),
        clock=lambda: NOW,
    )
    return connection_factory, workspaces, indexing, ingestion, processing


def _processed_result(
    tmp_path: Path,
) -> tuple[
    SQLiteConnectionFactory,
    WorkspaceApplicationComposition,
    IndexingApplicationComposition,
    object,
]:
    connection_factory, workspaces, indexing, ingestion, processing = _compose(tmp_path)
    workspace = workspaces.create_workspace("Anonymous Index Workspace")
    workspaces.select_workspace(workspace.id)
    imported = ingestion.import_pdf(
        _synthetic_pdf(("Anonymous first page", "")),
        "anonymous.pdf",
    )
    return connection_factory, workspaces, indexing, processing.process_pdf(imported)


def test_real_processing_output_reaches_exact_idempotent_staging_handoff(
    tmp_path: Path,
) -> None:
    factory, _workspaces, indexing, processed = _processed_result(tmp_path)

    first = indexing.prepare_index(processed)
    second = indexing.prepare_index(processed)

    assert isinstance(first, StagingEmbeddingHandoff)
    assert second == first
    candidate = first.candidate
    assert candidate.generation.state is IndexGenerationState.STAGING
    assert candidate.generation.embedding_model_id == MODEL.id
    ready_pages = {page.id: page for page in processed.pages if page.state.value == "READY"}
    assert ready_pages
    assert all(chunk.logical.page_id in ready_pages for chunk in candidate.chunks)
    assert all(
        chunk.logical.text
        == ready_pages[chunk.logical.page_id].text[
            chunk.logical.source_start_offset : chunk.logical.source_end_offset
        ]
        for chunk in candidate.chunks
    )
    assert tuple(chunk.logical.document_order for chunk in candidate.chunks) == tuple(
        range(len(candidate.chunks))
    )
    assert all(
        chunk.logical.source_locator_id == ready_pages[chunk.logical.page_id].source_locator.id
        for chunk in candidate.chunks
    )
    assert not hasattr(first, "connection")
    assert not hasattr(first, "codec")
    connection = factory.create()
    assert connection.execute("SELECT COUNT(*) FROM index_generations").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == len(candidate.chunks)
    assert connection.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 0
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM index_generations WHERE state = 'ACTIVE'"
        ).fetchone()[0]
        == 0
    )
    rows = connection.execute(
        "SELECT document_order, source_start_offset, source_end_offset FROM chunks ORDER BY document_order"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        (
            chunk.logical.document_order,
            chunk.logical.source_start_offset,
            chunk.logical.source_end_offset,
        )
        for chunk in candidate.chunks
    ]
    connection.close()


def test_wrong_active_workspace_cannot_substitute_processing_output(tmp_path: Path) -> None:
    factory, workspaces, indexing, processed = _processed_result(tmp_path)
    other = workspaces.create_workspace("Other Anonymous Workspace")
    workspaces.select_workspace(other.id)

    with pytest.raises(IndexingError):
        indexing.prepare_index(processed)

    connection = factory.create()
    assert connection.execute("SELECT COUNT(*) FROM index_generations").fetchone()[0] == 0
    connection.close()


def test_same_workspace_different_version_cannot_reuse_staging_generation(
    tmp_path: Path,
) -> None:
    factory, workspaces, indexing, ingestion, processing = _compose(tmp_path)
    workspace = workspaces.create_workspace("Anonymous Version Isolation Workspace")
    workspaces.select_workspace(workspace.id)
    first_import = ingestion.import_pdf(_synthetic_pdf(("First anonymous source",)), "first.pdf")
    second_import = ingestion.import_pdf(_synthetic_pdf(("Second anonymous source",)), "second.pdf")

    first = indexing.prepare_index(processing.process_pdf(first_import))
    second = indexing.prepare_index(processing.process_pdf(second_import))

    assert isinstance(first, StagingEmbeddingHandoff)
    assert isinstance(second, StagingEmbeddingHandoff)
    assert first.candidate.generation.id != second.candidate.generation.id
    assert (
        first.candidate.generation.document_version_id
        != second.candidate.generation.document_version_id
    )
    connection = factory.create()
    assert connection.execute("SELECT COUNT(*) FROM index_generations").fetchone()[0] == 2
    connection.close()


def test_cancellation_before_index_transaction_creates_no_candidate(tmp_path: Path) -> None:
    factory, workspaces, _indexing, ingestion, processing = _compose(
        tmp_path, cancellation=_Cancelled()
    )
    workspace = workspaces.create_workspace("Anonymous Cancel Workspace")
    workspaces.select_workspace(workspace.id)
    imported = ingestion.import_pdf(_synthetic_pdf(("Anonymous",)), "anonymous.pdf")
    processed = processing.process_pdf(imported)
    cancelled = compose_indexing_application(
        _settings(tmp_path),
        factory,
        workspaces.active_scope,
        LocalModelStatus(MODEL, ModelReadiness.READY, "synthetic-execution"),
        sensitive_payload_codec=ingestion.sensitive_payload_codec,
        cancellation=_Cancelled(),
        chunk_id_factory=_factory(ChunkId, 71),
        index_generation_id_factory=_factory(IndexGenerationId, 81),
        clock=lambda: NOW,
    )

    with pytest.raises(IndexingCancelled):
        cancelled.prepare_index(processed)

    connection = factory.create()
    assert connection.execute("SELECT COUNT(*) FROM index_generations").fetchone()[0] == 0
    connection.close()


def test_index_write_failure_rolls_back_complete_candidate(tmp_path: Path) -> None:
    factory, _workspaces, indexing, processed = _processed_result(tmp_path)
    connection = factory.create()
    connection.execute(
        "CREATE TRIGGER synthetic_index_write_failure BEFORE INSERT ON chunks BEGIN SELECT RAISE(ABORT, 'fixture detail'); END"
    )
    connection.commit()
    connection.close()

    with pytest.raises(IndexingPersistenceError) as captured:
        indexing.prepare_index(processed)

    assert "fixture detail" not in str(captured.value)
    connection = factory.create()
    assert connection.execute("SELECT COUNT(*) FROM index_generations").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
    connection.close()


def test_index_commit_failure_rolls_back_complete_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, _workspaces, indexing, processed = _processed_result(tmp_path)

    class _FailingCommitUnitOfWork(SQLiteUnitOfWork):
        def commit(self) -> None:
            raise RuntimeError("sensitive commit detail")

    monkeypatch.setattr(
        indexing_bootstrap,
        "SQLiteUnitOfWork",
        _FailingCommitUnitOfWork,
    )
    with pytest.raises(IndexingPersistenceError) as captured:
        indexing.prepare_index(processed)

    assert "sensitive" not in str(captured.value)
    connection = factory.create()
    assert connection.execute("SELECT COUNT(*) FROM index_generations").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
    connection.close()
