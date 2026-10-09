"""Behavior tests for the Application-owned document-workflow coordinator."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest

from lexlocal.application.document_workflow import BuildActiveDocument
from lexlocal.application.ports.document_workflow import (
    ActiveDocumentReadiness,
    DocumentDuplicate,
    DocumentEmbeddingFailure,
    DocumentImportFailure,
    DocumentIndexingFailure,
    DocumentProcessingFailure,
    DocumentUnusableNativeText,
    DocumentWorkflowCancelled,
    DocumentWorkflowDisposition,
    DocumentWorkflowProgressError,
    DocumentWorkflowStage,
    DocumentWorkflowUnavailable,
    SelectedPdfReadError,
    SelectedPdfReference,
    SelectedPdfSource,
)
from lexlocal.application.ports.embeddings import (
    EmbeddingCancelled,
    EmbeddingPersistenceError,
)
from lexlocal.application.ports.indexing import (
    ActivatedIndex,
    CandidateChunkSet,
    ChunkConfiguration,
    IndexChunk,
    IndexingCancelled,
    IndexingPersistenceError,
    LogicalChunk,
    PersistedIndexGeneration,
    ReusedActiveIndex,
    StagingEmbeddingHandoff,
)
from lexlocal.application.ports.ingestion import (
    DuplicateDocument,
    IngestionPersistenceError,
    IngestionResult,
    PdfInspectionResult,
)
from lexlocal.application.ports.processing import (
    PageExtractionMethod,
    ProcessedPage,
    ProcessedPageState,
    ProcessingCancelled,
    ProcessingPersistenceError,
    ProcessingResult,
    UnusableNativeText,
)
from lexlocal.application.ports.security import ControlledSourceRef
from lexlocal.application.workspaces import ActiveWorkspaceScope
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
from lexlocal.domain.retrieval import PageNumber, SourceLocator, SourceLocatorKind

_WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
_DOCUMENT_ID = DocumentId("10000000-0000-4000-8000-000000000002")
_VERSION_ID = DocumentVersionId("10000000-0000-4000-8000-000000000003")
_JOB_ID = ProcessingJobId("10000000-0000-4000-8000-000000000004")
_PAGE_ID = DocumentPageId("10000000-0000-4000-8000-000000000005")
_LOCATOR_ID = SourceLocatorId("10000000-0000-4000-8000-000000000006")
_CHUNK_ID = ChunkId("10000000-0000-4000-8000-000000000007")
_GENERATION_ID = IndexGenerationId("10000000-0000-4000-8000-000000000008")
_MODEL_ID = LocalModelId("10000000-0000-4000-8000-000000000009")
_NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)
_SOURCE = b"%PDF-exact-synthetic-source"
_PRIVATE_PATH = "/private/synthetic/anonymous.pdf"


def _scope() -> ActiveWorkspaceScope:
    scope = ActiveWorkspaceScope()
    scope.select(_WORKSPACE_ID)
    return scope


def _ingestion() -> IngestionResult:
    return IngestionResult(
        document_id=_DOCUMENT_ID,
        document_version_id=_VERSION_ID,
        processing_job_id=_JOB_ID,
        controlled_source=ControlledSourceRef(_WORKSPACE_ID, "opaque-source"),
        pdf=PdfInspectionResult("application/pdf", 1),
    )


def _processing(*, warning: bool = False) -> ProcessingResult:
    number = PageNumber(1)
    locator = SourceLocator(
        id=_LOCATOR_ID,
        workspace_id=_WORKSPACE_ID,
        document_version_id=_VERSION_ID,
        page_id=_PAGE_ID,
        page_number=number,
        kind=SourceLocatorKind.PAGE,
    )
    page = ProcessedPage(
        id=_PAGE_ID,
        workspace_id=_WORKSPACE_ID,
        document_version_id=_VERSION_ID,
        page_number=number,
        text="   " if warning else "exact synthetic page",
        state=ProcessedPageState.WARNING if warning else ProcessedPageState.READY,
        extraction_method=PageExtractionMethod.NATIVE,
        source_locator=locator,
    )
    return ProcessingResult(_DOCUMENT_ID, _VERSION_ID, _JOB_ID, (page,))


def _generation(state: IndexGenerationState) -> IndexGeneration:
    return IndexGeneration(
        _GENERATION_ID,
        _WORKSPACE_ID,
        _VERSION_ID,
        _JOB_ID,
        _MODEL_ID,
        ChunkConfiguration(100, 20).profile.value,
        "exact-text-v1",
        8,
        state,
    )


def _staging(processing: ProcessingResult) -> StagingEmbeddingHandoff:
    page = processing.pages[0]
    logical = LogicalChunk(
        workspace_id=_WORKSPACE_ID,
        document_version_id=_VERSION_ID,
        page_id=_PAGE_ID,
        page_number=page.page_number,
        source_locator_id=_LOCATOR_ID,
        document_order=0,
        page_order=0,
        source_start_offset=0,
        source_end_offset=len(page.text),
        text=page.text,
        extraction_method=PageExtractionMethod.NATIVE,
        profile=ChunkConfiguration(100, 20).profile,
    )
    chunk = IndexChunk(_CHUNK_ID, logical, b"equality", _NOW)
    return StagingEmbeddingHandoff(
        CandidateChunkSet(_generation(IndexGenerationState.STAGING), (chunk,), _NOW)
    )


def _activated(*, warning: bool = False) -> ActivatedIndex:
    version = DocumentVersion(
        _VERSION_ID,
        _WORKSPACE_ID,
        _DOCUMENT_ID,
        VersionNumber(1),
        DocumentVersionState.ACTIVE,
    )
    job = ProcessingJob(
        _JOB_ID,
        _WORKSPACE_ID,
        _VERSION_ID,
        AttemptNumber(1),
        ProcessingJobState.READY_WITH_WARNINGS if warning else ProcessingJobState.READY,
    )
    return ActivatedIndex(version, job, _generation(IndexGenerationState.ACTIVE))


class _Cancellation:
    def __init__(self, events: list[str], cancel_at: int | None = None) -> None:
        self._events = events
        self._cancel_at = cancel_at
        self._requested = False
        self.checks = 0

    def cancel(self) -> None:
        self._requested = True

    def raise_if_cancelled(self) -> None:
        self.checks += 1
        self._events.append(f"check:{self.checks}")
        if self._requested or self.checks == self._cancel_at:
            raise DocumentWorkflowCancelled("private cancellation detail")


class _Reader:
    def __init__(self, events: list[str], error: Exception | None = None) -> None:
        self._events = events
        self._error = error

    def read(self, selected: SelectedPdfReference) -> SelectedPdfSource:
        self._events.append("read")
        assert selected.value == _PRIVATE_PATH
        if self._error is not None:
            raise self._error
        return SelectedPdfSource(_SOURCE, "anonymous.pdf")


class _Pipeline:
    def __init__(
        self,
        events: list[str],
        *,
        processing: ProcessingResult | None = None,
        preparation: StagingEmbeddingHandoff | ReusedActiveIndex | None = None,
        fail_at: str | None = None,
        failure: Exception | None = None,
        after_import: Callable[[], None] | None = None,
        after_embed: Callable[[], None] | None = None,
    ) -> None:
        self.events = events
        self.ingestion = _ingestion()
        self.processing = processing or _processing()
        self.preparation = preparation or _staging(self.processing)
        self.activated = _activated(
            warning=any(
                page.state is ProcessedPageState.WARNING for page in self.processing.pages
            )
        )
        self.fail_at = fail_at
        self.failure = failure
        self.after_import = after_import
        self.after_embed = after_embed

    def import_pdf(self, source: bytes, logical_filename: str) -> IngestionResult:
        self.events.append("import")
        assert source is _SOURCE
        assert logical_filename == "anonymous.pdf"
        self._raise("import")
        if self.after_import is not None:
            self.after_import()
        return self.ingestion

    def process_pdf(self, ingestion: IngestionResult) -> ProcessingResult:
        self.events.append("process")
        assert ingestion is self.ingestion
        self._raise("process")
        return self.processing

    def prepare_indexing(
        self,
        processing: ProcessingResult,
    ) -> StagingEmbeddingHandoff | ReusedActiveIndex:
        self.events.append("prepare")
        assert processing is self.processing
        self._raise("prepare")
        return self.preparation

    def embed(self, handoff: StagingEmbeddingHandoff) -> ActivatedIndex:
        self.events.append("embed")
        assert handoff is self.preparation
        self._raise("embed")
        if self.after_embed is not None:
            self.after_embed()
        return self.activated

    def _raise(self, operation: str) -> None:
        if self.fail_at == operation:
            assert self.failure is not None
            raise self.failure


def _workflow(
    events: list[str],
    pipeline: _Pipeline,
    *,
    cancellation: _Cancellation | None = None,
    reader: _Reader | None = None,
    sink_error: Exception | None = None,
    sink_error_at: DocumentWorkflowStage = DocumentWorkflowStage.IMPORTING,
) -> BuildActiveDocument:
    def stage_sink(stage: DocumentWorkflowStage) -> None:
        events.append(f"stage:{stage.value}")
        if sink_error is not None and stage is sink_error_at:
            raise sink_error

    return BuildActiveDocument(
        active_scope=_scope(),
        selected_pdf_reader=reader or _Reader(events),
        cancellation=cancellation or _Cancellation(events),
        stage_sink=stage_sink,
        import_pdf=pipeline.import_pdf,
        process_pdf=pipeline.process_pdf,
        prepare_indexing=pipeline.prepare_indexing,
        embed_staging_chunks=pipeline.embed,
    )


def test_staging_path_preserves_exact_order_handoffs_and_safe_result() -> None:
    events: list[str] = []
    pipeline = _Pipeline(events)

    result = _workflow(events, pipeline)(SelectedPdfReference(_PRIVATE_PATH))

    assert events == [
        "check:1",
        "stage:IMPORTING",
        "check:2",
        "read",
        "check:3",
        "import",
        "stage:EXTRACTING",
        "process",
        "check:4",
        "stage:INDEXING",
        "check:5",
        "prepare",
        "stage:EMBEDDING",
        "check:6",
        "embed",
    ]
    assert result.workspace_id == _WORKSPACE_ID
    assert result.document_id == _DOCUMENT_ID
    assert result.document_version_id == _VERSION_ID
    assert result.processing_job_id == _JOB_ID
    assert result.logical_filename == "anonymous.pdf"
    assert result.page_count == 1
    assert result.readiness is ActiveDocumentReadiness.READY
    assert result.active_generation is pipeline.activated.generation
    assert _PRIVATE_PATH not in repr(result)
    assert _SOURCE.decode() not in repr(result)


def test_missing_active_workspace_fails_before_file_access() -> None:
    events: list[str] = []
    pipeline = _Pipeline(events)
    workflow = BuildActiveDocument(
        active_scope=ActiveWorkspaceScope(),
        selected_pdf_reader=_Reader(events),
        cancellation=_Cancellation(events),
        stage_sink=lambda stage: events.append(f"stage:{stage.value}"),
        import_pdf=pipeline.import_pdf,
        process_pdf=pipeline.process_pdf,
        prepare_indexing=pipeline.prepare_indexing,
        embed_staging_chunks=pipeline.embed,
    )

    with pytest.raises(DocumentWorkflowUnavailable):
        workflow(SelectedPdfReference(_PRIVATE_PATH))

    assert events == []


def test_compatible_active_reuse_skips_embedding_and_preserves_warning() -> None:
    events: list[str] = []
    processing = _processing(warning=True)
    reused = ReusedActiveIndex(
        PersistedIndexGeneration(
            _generation(IndexGenerationState.ACTIVE),
            _NOW,
            activated_at=_NOW,
        )
    )
    pipeline = _Pipeline(events, processing=processing, preparation=reused)

    result = _workflow(events, pipeline)(SelectedPdfReference(_PRIVATE_PATH))

    assert "stage:EMBEDDING" not in events
    assert "embed" not in events
    assert result.readiness is ActiveDocumentReadiness.READY_WITH_WARNINGS
    assert result.active_generation is reused.persisted.generation


@pytest.mark.parametrize("cancel_at", range(1, 7))
def test_cancellation_at_each_coordinator_checkpoint_has_safe_disposition(
    cancel_at: int,
) -> None:
    events: list[str] = []
    cancellation = _Cancellation(events, cancel_at)
    pipeline = _Pipeline(events)

    with pytest.raises(DocumentWorkflowCancelled) as captured:
        _workflow(events, pipeline, cancellation=cancellation)(
            SelectedPdfReference(_PRIVATE_PATH)
        )

    assert cancellation.checks == cancel_at
    assert "private cancellation detail" not in str(captured.value)
    assert _PRIVATE_PATH not in repr(captured.value)
    assert captured.value.disposition is (
        DocumentWorkflowDisposition.NOT_REGISTERED
        if cancel_at <= 3
        else DocumentWorkflowDisposition.REGISTERED_INCOMPLETE
    )


def test_cancellation_arriving_during_ingestion_is_owned_by_processing() -> None:
    events: list[str] = []
    cancellation = _Cancellation(events)
    pipeline: _Pipeline

    def cancel_during_import() -> None:
        cancellation.cancel()
        pipeline.fail_at = "process"
        pipeline.failure = ProcessingCancelled("private processing cancellation")

    pipeline = _Pipeline(events, after_import=cancel_during_import)

    with pytest.raises(DocumentWorkflowCancelled) as captured:
        _workflow(events, pipeline, cancellation=cancellation)(
            SelectedPdfReference(_PRIVATE_PATH)
        )

    assert events[events.index("import") + 1 :] == [
        "stage:EXTRACTING",
        "process",
    ]
    assert (
        captured.value.disposition
        is DocumentWorkflowDisposition.REGISTERED_INCOMPLETE
    )
    assert "private" not in str(captured.value)


def test_cancellation_after_committed_activation_does_not_relabel_ready() -> None:
    events: list[str] = []
    cancellation = _Cancellation(events)
    pipeline = _Pipeline(events, after_embed=cancellation.cancel)

    result = _workflow(events, pipeline, cancellation=cancellation)(
        SelectedPdfReference(_PRIVATE_PATH)
    )

    assert result.readiness is ActiveDocumentReadiness.READY
    assert events[-1] == "embed"


@pytest.mark.parametrize(
    ("operation", "failure", "expected", "disposition"),
    [
        (
            "import",
            IngestionPersistenceError("private import detail"),
            DocumentImportFailure,
            DocumentWorkflowDisposition.NOT_REGISTERED,
        ),
        (
            "process",
            ProcessingPersistenceError("private processing detail"),
            DocumentProcessingFailure,
            DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
        ),
        (
            "process",
            UnusableNativeText("private unusable detail"),
            DocumentUnusableNativeText,
            DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
        ),
        (
            "prepare",
            IndexingPersistenceError("private indexing detail"),
            DocumentIndexingFailure,
            DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
        ),
        (
            "embed",
            EmbeddingPersistenceError("private embedding detail"),
            DocumentEmbeddingFailure,
            DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
        ),
    ],
)
def test_owning_failures_are_sanitized_and_stop_later_calls(
    operation: str,
    failure: Exception,
    expected: type[Exception],
    disposition: DocumentWorkflowDisposition,
) -> None:
    events: list[str] = []
    pipeline = _Pipeline(events, fail_at=operation, failure=failure)

    with pytest.raises(expected) as captured:
        _workflow(events, pipeline)(SelectedPdfReference(_PRIVATE_PATH))

    assert "private" not in str(captured.value)
    assert _PRIVATE_PATH not in repr(captured.value)
    assert captured.value.disposition is disposition
    failed_at = events.index(operation)
    later_operations = {"import", "process", "prepare", "embed"}
    assert not later_operations.intersection(events[failed_at + 1 :])


def test_duplicate_preserves_distinct_duplicate_category() -> None:
    events: list[str] = []
    pipeline = _Pipeline(
        events,
        fail_at="import",
        failure=DuplicateDocument("private duplicate detail"),
    )

    with pytest.raises(DocumentDuplicate) as captured:
        _workflow(events, pipeline)(SelectedPdfReference(_PRIVATE_PATH))

    assert "private" not in str(captured.value)
    assert (
        captured.value.disposition
        is DocumentWorkflowDisposition.NOT_REGISTERED
    )


def test_reader_and_progress_failures_are_sanitized_before_pipeline_calls() -> None:
    private_detail = "private path detail"

    read_events: list[str] = []
    read_pipeline = _Pipeline(read_events)
    with pytest.raises(SelectedPdfReadError) as read_error:
        _workflow(
            read_events,
            read_pipeline,
            reader=_Reader(read_events, RuntimeError(private_detail)),
        )(SelectedPdfReference(_PRIVATE_PATH))
    assert private_detail not in str(read_error.value)
    assert "import" not in read_events

    sink_events: list[str] = []
    sink_pipeline = _Pipeline(sink_events)
    with pytest.raises(DocumentWorkflowProgressError) as sink_error:
        _workflow(
            sink_events,
            sink_pipeline,
            sink_error=RuntimeError(private_detail),
        )(SelectedPdfReference(_PRIVATE_PATH))
    assert private_detail not in str(sink_error.value)
    assert "read" not in sink_events

    registered_events: list[str] = []
    registered_pipeline = _Pipeline(registered_events)
    with pytest.raises(DocumentWorkflowProgressError) as registered_error:
        _workflow(
            registered_events,
            registered_pipeline,
            sink_error=RuntimeError(private_detail),
            sink_error_at=DocumentWorkflowStage.EXTRACTING,
        )(SelectedPdfReference(_PRIVATE_PATH))
    assert (
        registered_error.value.disposition
        is DocumentWorkflowDisposition.REGISTERED_INCOMPLETE
    )
    assert "process" not in registered_events


@pytest.mark.parametrize(
    ("operation", "failure"),
    [
        ("process", ProcessingCancelled("private cancellation")),
        ("prepare", IndexingCancelled("private cancellation")),
        ("embed", EmbeddingCancelled("private cancellation")),
    ],
)
def test_inner_cancellation_is_translated_without_leaking_details(
    operation: str,
    failure: Exception,
) -> None:
    events: list[str] = []
    pipeline = _Pipeline(events, fail_at=operation, failure=failure)

    with pytest.raises(DocumentWorkflowCancelled) as captured:
        _workflow(events, pipeline)(SelectedPdfReference(_PRIVATE_PATH))

    assert "private" not in str(captured.value)
    assert (
        captured.value.disposition
        is DocumentWorkflowDisposition.REGISTERED_INCOMPLETE
    )


def test_invalid_cross_workspace_generation_fails_closed() -> None:
    events: list[str] = []
    pipeline = _Pipeline(events)
    other_workspace = WorkspaceId("20000000-0000-4000-8000-000000000001")
    invalid_generation = replace(
        pipeline.preparation.candidate.generation,
        workspace_id=other_workspace,
    )
    pipeline.preparation = StagingEmbeddingHandoff(
        CandidateChunkSet(
            invalid_generation,
            tuple(
                replace(
                    chunk,
                    logical=replace(chunk.logical, workspace_id=other_workspace),
                )
                for chunk in pipeline.preparation.candidate.chunks
            ),
            _NOW,
        )
    )

    with pytest.raises(DocumentIndexingFailure):
        _workflow(events, pipeline)(SelectedPdfReference(_PRIVATE_PATH))

    assert "embed" not in events


def test_invalid_operation_result_is_not_coerced_into_success() -> None:
    events: list[str] = []
    pipeline = _Pipeline(events)
    pipeline.preparation = cast(
        StagingEmbeddingHandoff,
        object(),
    )

    with pytest.raises(DocumentIndexingFailure):
        _workflow(events, pipeline)(SelectedPdfReference(_PRIVATE_PATH))

    assert "embed" not in events
