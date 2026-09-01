"""Behavioral tests for native PDF processing orchestration."""

from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from types import TracebackType
from typing import Self, TypeVar

import pytest

from lexlocal.application.ports.ingestion import (
    IngestionRepository,
    IngestionResult,
    PdfInspectionResult,
)
from lexlocal.application.ports.local_models import ResolvedModelRepository
from lexlocal.application.ports.processing import (
    NativePdfExtractionError,
    NativePdfPage,
    ProcessedPage,
    ProcessedPageState,
    ProcessingCancelled,
    ProcessingFailureKind,
    ProcessingGraph,
    ProcessingPageBatch,
    ProcessingPersistenceError,
    ProcessingRepository,
    ProcessingSourceError,
    ProcessingTarget,
    ProcessingTerminalUpdate,
    UnusableNativeText,
)
from lexlocal.application.ports.security import ControlledSourceRef
from lexlocal.application.ports.unit_of_work import UnitOfWork
from lexlocal.application.ports.workspaces import WorkspaceRepository
from lexlocal.application.processing import ProcessNativePdfText
from lexlocal.application.workspaces import ActiveWorkspaceScope
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
from lexlocal.domain.retrieval import PageNumber, SourceLocatorKind

_WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
_OTHER_WORKSPACE_ID = WorkspaceId("20000000-0000-4000-8000-000000000001")
_DOCUMENT_ID = DocumentId("10000000-0000-4000-8000-000000000002")
_VERSION_ID = DocumentVersionId("10000000-0000-4000-8000-000000000003")
_JOB_ID = ProcessingJobId("10000000-0000-4000-8000-000000000004")
_NOW = datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)
_SOURCE = b"anonymous synthetic PDF bytes"


def _ingestion(
    *,
    workspace_id: WorkspaceId = _WORKSPACE_ID,
    page_count: int = 2,
) -> IngestionResult:
    return IngestionResult(
        document_id=_DOCUMENT_ID,
        document_version_id=_VERSION_ID,
        processing_job_id=_JOB_ID,
        controlled_source=ControlledSourceRef(workspace_id, "opaque-synthetic-reference"),
        pdf=PdfInspectionResult("application/pdf", page_count),
    )


def _graph(page_count: int = 2) -> ProcessingGraph:
    return ProcessingGraph(
        version=DocumentVersion(
            id=_VERSION_ID,
            workspace_id=_WORKSPACE_ID,
            document_id=_DOCUMENT_ID,
            version_number=VersionNumber(1),
        ),
        job=ProcessingJob(
            id=_JOB_ID,
            workspace_id=_WORKSPACE_ID,
            document_version_id=_VERSION_ID,
            attempt_number=AttemptNumber(1),
        ),
        page_count=page_count,
    )


class _Storage:
    def __init__(self, events: list[str], *, failure: Exception | None = None) -> None:
        self.events = events
        self.failure = failure
        self.reads: list[tuple[WorkspaceId, ControlledSourceRef]] = []

    def store(self, workspace_id: WorkspaceId, source: bytes) -> ControlledSourceRef:
        raise NotImplementedError

    def read(
        self,
        workspace_id: WorkspaceId,
        reference: ControlledSourceRef,
    ) -> bytes:
        self.events.append("read-source")
        self.reads.append((workspace_id, reference))
        if self.failure is not None:
            raise self.failure
        return _SOURCE

    def delete(self, workspace_id: WorkspaceId, reference: ControlledSourceRef) -> None:
        raise NotImplementedError


class _Extractor:
    def __init__(
        self,
        events: list[str],
        pages: Iterable[NativePdfPage],
        *,
        failure: Exception | None = None,
    ) -> None:
        self.events = events
        self.pages = pages
        self.failure = failure
        self.sources: list[bytes] = []

    def extract(self, source: bytes) -> Iterable[NativePdfPage]:
        self.events.append("extract")
        self.sources.append(source)
        if self.failure is not None:
            raise self.failure
        return self.pages


class _Cancellation:
    def __init__(self, events: list[str], cancel_at: int | None = None) -> None:
        self.events = events
        self.cancel_at = cancel_at
        self.calls = 0

    def raise_if_cancelled(self) -> None:
        self.calls += 1
        self.events.append(f"checkpoint-{self.calls}")
        if self.calls == self.cancel_at:
            raise ProcessingCancelled("unsafe fixture detail")


class _Repository:
    def __init__(
        self,
        events: list[str],
        graph: ProcessingGraph,
        *,
        stage_failure: Exception | None = None,
        terminal_failure: Exception | None = None,
    ) -> None:
        self.events = events
        self.graph = graph
        self.stage_failure = stage_failure
        self.terminal_failure = terminal_failure
        self.batches: list[ProcessingPageBatch] = []
        self.terminal_updates: list[ProcessingTerminalUpdate] = []

    def get_initial_graph(self, target: ProcessingTarget) -> ProcessingGraph:
        self.events.append("get-graph")
        return self.graph

    def start(
        self,
        target: ProcessingTarget,
        job: ProcessingJob,
        started_at: datetime,
    ) -> None:
        self.events.append("start")
        assert job.state is ProcessingJobState.PROCESSING
        assert started_at == _NOW

    def stage_pages(self, batch: ProcessingPageBatch) -> None:
        self.events.append("stage-pages")
        if self.stage_failure is not None:
            raise self.stage_failure
        self.batches.append(batch)

    def record_terminal(self, update: ProcessingTerminalUpdate) -> None:
        self.events.append(f"terminal-{update.failure_kind.value}")
        if self.terminal_failure is not None:
            raise self.terminal_failure
        self.terminal_updates.append(update)

    def list_pages_for_chunking(
        self,
        workspace_id: WorkspaceId,
        document_version_id: DocumentVersionId,
    ) -> Sequence[ProcessedPage]:
        return ()


class _UnitOfWork:
    def __init__(
        self,
        repository: ProcessingRepository,
        events: list[str],
        number: int,
        *,
        fail_commit: bool,
    ) -> None:
        self._repository = repository
        self._events = events
        self._number = number
        self._fail_commit = fail_commit
        self._committed = False

    @property
    def processing(self) -> ProcessingRepository:
        return self._repository

    @property
    def workspaces(self) -> WorkspaceRepository:
        raise NotImplementedError

    @property
    def local_models(self) -> ResolvedModelRepository:
        raise NotImplementedError

    @property
    def ingestion(self) -> IngestionRepository:
        raise NotImplementedError

    def __enter__(self) -> Self:
        self._events.append(f"enter-{self._number}")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if not self._committed:
            self._events.append(f"rollback-{self._number}")

    def commit(self) -> None:
        self._events.append(f"commit-{self._number}")
        if self._fail_commit:
            raise RuntimeError("unsafe database detail")
        self._committed = True

    def rollback(self) -> None:
        self._events.append(f"rollback-{self._number}")


class _UnitOfWorkFactory:
    def __init__(
        self,
        repository: ProcessingRepository,
        events: list[str],
        *,
        failing_commits: set[int] | None = None,
    ) -> None:
        self.repository = repository
        self.events = events
        self.failing_commits = failing_commits or set()
        self.calls = 0

    def __call__(self) -> UnitOfWork:
        self.calls += 1
        return _UnitOfWork(
            self.repository,
            self.events,
            self.calls,
            fail_commit=self.calls in self.failing_commits,
        )


_IdentifierT = TypeVar("_IdentifierT")


def _id_factory(
    identifier_type: Callable[[str], _IdentifierT],
    start: int,
) -> Callable[[], _IdentifierT]:
    counter = start

    def create() -> _IdentifierT:
        nonlocal counter
        value = f"30000000-0000-4000-8000-{counter:012d}"
        counter += 1
        return identifier_type(value)

    return create


def _use_case(
    *,
    pages: Iterable[NativePdfPage] | None = None,
    active_workspace: WorkspaceId = _WORKSPACE_ID,
    cancel_at: int | None = None,
    storage_failure: Exception | None = None,
    extractor_failure: Exception | None = None,
    stage_failure: Exception | None = None,
    terminal_failure: Exception | None = None,
    failing_commits: set[int] | None = None,
    graph: ProcessingGraph | None = None,
) -> tuple[
    ProcessNativePdfText,
    _Storage,
    _Extractor,
    _Cancellation,
    _Repository,
    _UnitOfWorkFactory,
    list[str],
]:
    events: list[str] = []
    active_scope = ActiveWorkspaceScope()
    active_scope.select(active_workspace)
    storage = _Storage(events, failure=storage_failure)
    extractor = _Extractor(
        events,
        pages
        if pages is not None
        else (
            NativePdfPage(PageNumber(1), "  exact first page\n"),
            NativePdfPage(PageNumber(2), "\t  "),
        ),
        failure=extractor_failure,
    )
    cancellation = _Cancellation(events, cancel_at)
    repository = _Repository(
        events,
        graph or _graph(),
        stage_failure=stage_failure,
        terminal_failure=terminal_failure,
    )
    unit_of_work_factory = _UnitOfWorkFactory(
        repository,
        events,
        failing_commits=failing_commits,
    )
    use_case = ProcessNativePdfText(
        active_scope=active_scope,
        controlled_storage=storage,
        extractor=extractor,
        cancellation=cancellation,
        unit_of_work_factory=unit_of_work_factory,
        page_id_factory=_id_factory(DocumentPageId, 1),
        source_locator_id_factory=_id_factory(SourceLocatorId, 101),
        clock=lambda: _NOW,
    )
    return (
        use_case,
        storage,
        extractor,
        cancellation,
        repository,
        unit_of_work_factory,
        events,
    )


def test_exact_mixed_pages_are_staged_in_order_with_page_provenance() -> None:
    use_case, storage, extractor, _, repository, _, events = _use_case()

    result = use_case(_ingestion())

    assert extractor.sources == [_SOURCE]
    assert storage.reads == [(_WORKSPACE_ID, _ingestion().controlled_source)]
    assert tuple(page.page_number.value for page in result.pages) == (1, 2)
    assert tuple(page.text for page in result.pages) == ("  exact first page\n", "\t  ")
    assert tuple(page.state for page in result.pages) == (
        ProcessedPageState.READY,
        ProcessedPageState.WARNING,
    )
    assert all(page.extraction_method.value == "NATIVE" for page in result.pages)
    assert tuple(str(page.id) for page in result.pages) == (
        "30000000-0000-4000-8000-000000000001",
        "30000000-0000-4000-8000-000000000002",
    )
    assert tuple(str(page.source_locator.id) for page in result.pages) == (
        "30000000-0000-4000-8000-000000000101",
        "30000000-0000-4000-8000-000000000102",
    )
    assert all(page.source_locator.kind is SourceLocatorKind.PAGE for page in result.pages)
    assert all(
        page.source_locator.page_id == page.id
        and page.source_locator.page_number == page.page_number
        and page.workspace_id == _WORKSPACE_ID
        and page.document_version_id == _VERSION_ID
        for page in result.pages
    )
    assert repository.batches[0].pages == result.pages
    assert repository.batches[0].updated_at == _NOW
    assert result.job_state is ProcessingJobState.PROCESSING
    assert result.stage == "CHUNKING"
    assert events.index("start") < events.index("read-source") < events.index("extract")
    assert events.index("extract") < events.index("stage-pages") < events.index("commit-2")


def test_workspace_substitution_is_rejected_before_source_access() -> None:
    use_case, storage, extractor, _, _, factory, _ = _use_case(
        active_workspace=_OTHER_WORKSPACE_ID
    )

    with pytest.raises(ProcessingSourceError, match="another workspace"):
        use_case(_ingestion())

    assert storage.reads == []
    assert extractor.sources == []
    assert factory.calls == 0


def test_zero_usable_pages_fails_and_records_sanitized_terminal_state() -> None:
    pages = (
        NativePdfPage(PageNumber(1), ""),
        NativePdfPage(PageNumber(2), " \n\t"),
    )
    use_case, _, _, _, repository, _, _ = _use_case(pages=pages)

    with pytest.raises(UnusableNativeText, match="no usable native text") as captured:
        use_case(_ingestion())

    assert captured.value.__cause__ is None
    assert repository.batches == []
    assert repository.terminal_updates[0].failure_kind is ProcessingFailureKind.UNUSABLE_TEXT
    assert repository.terminal_updates[0].job.state is ProcessingJobState.FAILED
    assert (
        repository.terminal_updates[0].version.state
        is DocumentVersionState.CANDIDATE_FAILED
    )


@pytest.mark.parametrize(
    "pages",
    [
        (NativePdfPage(PageNumber(1), "usable"),),
        (
            NativePdfPage(PageNumber(1), "usable"),
            NativePdfPage(PageNumber(1), "duplicate"),
        ),
        (
            NativePdfPage(PageNumber(2), "out of order"),
            NativePdfPage(PageNumber(1), "usable"),
        ),
    ],
    ids=["missing", "duplicate", "out-of-order"],
)
def test_malformed_extractor_results_are_rejected(
    pages: tuple[NativePdfPage, ...],
) -> None:
    use_case, _, _, _, repository, _, _ = _use_case(pages=pages)

    with pytest.raises(NativePdfExtractionError) as captured:
        use_case(_ingestion())

    assert captured.value.__cause__ is None
    assert repository.batches == []
    assert repository.terminal_updates[0].failure_kind is ProcessingFailureKind.EXTRACTION


@pytest.mark.parametrize(
    "cancel_at",
    [1, 2, 3, 5, 7, 8],
    ids=[
        "pre-start",
        "pre-read",
        "pre-extraction",
        "between-pages",
        "pre-write-transaction",
        "pre-commit",
    ],
)
def test_cancellation_checkpoints_never_return_completed_output(cancel_at: int) -> None:
    use_case, _, _, _, repository, _, _ = _use_case(cancel_at=cancel_at)

    with pytest.raises(ProcessingCancelled, match="processing was cancelled") as captured:
        use_case(_ingestion())

    assert captured.value.__cause__ is None
    assert repository.terminal_updates[-1].failure_kind is ProcessingFailureKind.CANCELLED
    assert repository.terminal_updates[-1].job.state is ProcessingJobState.CANCELLED
    assert (
        repository.terminal_updates[-1].version.state
        is DocumentVersionState.CANDIDATE_CANCELLED
    )
    if cancel_at < 7:
        assert repository.batches == []


def test_final_commit_failure_rolls_back_before_separate_failure_recording() -> None:
    use_case, _, _, _, repository, _, events = _use_case(failing_commits={2})

    with pytest.raises(ProcessingPersistenceError, match="persistence failed"):
        use_case(_ingestion())

    assert events.index("rollback-2") < events.index("terminal-PERSISTENCE")
    assert events.index("terminal-PERSISTENCE") < events.index("commit-3")
    assert repository.terminal_updates[-1].failure_kind is ProcessingFailureKind.PERSISTENCE


@pytest.mark.parametrize(
    ("failure_location", "expected_error", "secret"),
    [
        (
            "storage",
            ProcessingSourceError,
            "secret source locator",
        ),
        (
            "extractor",
            NativePdfExtractionError,
            "native diagnostic and document text",
        ),
        (
            "persistence",
            ProcessingPersistenceError,
            "SQL and database path",
        ),
    ],
)
def test_dependency_failures_are_sanitized(
    failure_location: str,
    expected_error: type[Exception],
    secret: str,
) -> None:
    use_case, _, _, _, _, _, _ = _use_case(
        storage_failure=(
            RuntimeError(secret) if failure_location == "storage" else None
        ),
        extractor_failure=(
            RuntimeError(secret) if failure_location == "extractor" else None
        ),
        stage_failure=(
            RuntimeError(secret) if failure_location == "persistence" else None
        ),
    )

    with pytest.raises(expected_error) as captured:
        use_case(_ingestion())

    assert secret not in str(captured.value)
    assert captured.value.__cause__ is None


def test_terminal_recording_failure_is_sanitized() -> None:
    use_case, _, _, _, _, _, _ = _use_case(
        pages=(NativePdfPage(PageNumber(1), ""), NativePdfPage(PageNumber(2), "")),
        terminal_failure=RuntimeError("unsafe terminal SQL"),
    )

    with pytest.raises(
        ProcessingPersistenceError,
        match="terminal state could not be recorded",
    ) as captured:
        use_case(_ingestion())

    assert "unsafe terminal SQL" not in str(captured.value)
    assert captured.value.__cause__ is None
