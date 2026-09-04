"""Transaction-level tests for Application indexing orchestration."""

from datetime import UTC, datetime
from types import TracebackType
from typing import Self

import pytest

from lexlocal.application.indexing import PrepareIndexing
from lexlocal.application.ports.indexing import (
    AmbiguousIndexGeneration,
    CandidateChunkSet,
    ChunkConfiguration,
    IndexingCancelled,
    IndexingPersistenceError,
    InvalidIndexingInput,
    LogicalChunk,
    NoEligibleChunks,
    PersistedIndexGeneration,
    ReusedActiveIndex,
    StagingEmbeddingHandoff,
)
from lexlocal.application.ports.local_models import (
    ModelCapability,
    ResolvedModelRecord,
)
from lexlocal.application.ports.processing import (
    PageExtractionMethod,
    ProcessedPage,
    ProcessedPageState,
    ProcessingResult,
)
from lexlocal.application.workspaces import ActiveWorkspaceScope
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
from lexlocal.domain.processing import IndexGeneration, IndexGenerationState
from lexlocal.domain.retrieval import PageNumber, SourceLocator, SourceLocatorKind

WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
VERSION_ID = DocumentVersionId("20000000-0000-4000-8000-000000000001")
JOB_ID = ProcessingJobId("30000000-0000-4000-8000-000000000001")
MODEL_ID = LocalModelId("40000000-0000-4000-8000-000000000001")
GENERATION_ID = IndexGenerationId("50000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


class _Cancellation:
    def __init__(self, fail_at: int | None = None) -> None:
        self.calls = 0
        self.fail_at = fail_at

    def raise_if_cancelled(self) -> None:
        self.calls += 1
        if self.calls == self.fail_at:
            raise IndexingCancelled("fixture detail")


class _Token:
    def fingerprint(self, chunk: LogicalChunk) -> bytes:
        return repr(chunk).encode()


class _Ids:
    def __init__(
        self,
        kind: type[ChunkId] | type[IndexGenerationId],
        events: list[str] | None = None,
    ) -> None:
        self.kind = kind
        self.events = events
        self.calls = 0

    def __call__(self) -> ChunkId | IndexGenerationId:
        self.calls += 1
        if self.events is not None:
            self.events.append("chunk-id" if self.kind is ChunkId else "generation-id")
        return self.kind(f"90000000-0000-4000-8000-{self.calls:012d}")


class _Repository:
    def __init__(self) -> None:
        self.generations: list[PersistedIndexGeneration] = []
        self.candidates: dict[IndexGenerationId, CandidateChunkSet] = {}
        self.writes = 0
        self.fail_discovery = False
        self.fail_write = False

    def list_generations(
        self,
        workspace_id: WorkspaceId,
        document_version_id: DocumentVersionId,
        processing_job_id: ProcessingJobId,
    ) -> tuple[PersistedIndexGeneration, ...]:
        if self.fail_discovery:
            raise RuntimeError("sensitive discovery detail")
        return tuple(
            item
            for item in self.generations
            if item.generation.workspace_id == workspace_id
            and item.generation.document_version_id == document_version_id
            and item.generation.processing_job_id == processing_job_id
        )

    def stage_candidate(self, candidate: CandidateChunkSet) -> None:
        if self.fail_write:
            raise RuntimeError("sensitive write detail")
        self.writes += 1
        self.generations.append(
            PersistedIndexGeneration(candidate.generation, candidate.created_at)
        )
        self.candidates[candidate.generation.id] = candidate

    def replace_staging_candidate(self, candidate: CandidateChunkSet) -> None:
        self.writes += 1
        self.candidates[candidate.generation.id] = candidate

    def get_candidate(
        self,
        workspace_id: WorkspaceId,
        document_version_id: DocumentVersionId,
        index_generation_id: IndexGenerationId,
    ) -> CandidateChunkSet | None:
        candidate = self.candidates.get(index_generation_id)
        if candidate is None:
            return None
        if (
            candidate.generation.workspace_id != workspace_id
            or candidate.generation.document_version_id != document_version_id
        ):
            return None
        return candidate


class _UnitOfWork:
    def __init__(
        self,
        repository: _Repository,
        events: list[str],
        *,
        fail_commit: bool = False,
    ) -> None:
        self.indexing = repository
        self.events = events
        self.fail_commit = fail_commit
        self.committed = False
        self.snapshot: (
            tuple[
                list[PersistedIndexGeneration],
                dict[IndexGenerationId, CandidateChunkSet],
                int,
            ]
            | None
        ) = None

    def __enter__(self) -> Self:
        self.events.append("enter")
        self.snapshot = (
            list(self.indexing.generations),
            dict(self.indexing.candidates),
            self.indexing.writes,
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if not self.committed and self.snapshot is not None:
            generations, candidates, writes = self.snapshot
            self.indexing.generations[:] = generations
            self.indexing.candidates.clear()
            self.indexing.candidates.update(candidates)
            self.indexing.writes = writes
        self.events.append("exit")

    def commit(self) -> None:
        self.events.append("commit")
        if self.fail_commit:
            raise RuntimeError("sensitive native detail")
        self.committed = True


class _UowFactory:
    def __init__(self, repository: _Repository, *, fail_write_commit: bool = False) -> None:
        self.repository = repository
        self.events: list[str] = []
        self.calls = 0
        self.fail_write_commit = fail_write_commit

    def __call__(self) -> _UnitOfWork:
        self.calls += 1
        self.events.append(f"factory-{self.calls}")
        return _UnitOfWork(
            self.repository,
            self.events,
            fail_commit=self.fail_write_commit and self.calls % 2 == 0,
        )


def _processing(
    *,
    workspace_id: WorkspaceId = WORKSPACE_ID,
    text: str = "abcdef",
) -> ProcessingResult:
    page_id = DocumentPageId("60000000-0000-4000-8000-000000000001")
    page_number = PageNumber(1)
    page = ProcessedPage(
        page_id,
        workspace_id,
        VERSION_ID,
        page_number,
        text,
        (
            ProcessedPageState.READY
            if any(not character.isspace() for character in text)
            else ProcessedPageState.WARNING
        ),
        PageExtractionMethod.NATIVE,
        SourceLocator(
            SourceLocatorId("70000000-0000-4000-8000-000000000001"),
            workspace_id,
            VERSION_ID,
            page_id,
            page_number,
            SourceLocatorKind.PAGE,
        ),
    )
    return ProcessingResult(
        DocumentId("80000000-0000-4000-8000-000000000001"),
        VERSION_ID,
        JOB_ID,
        (page,),
    )


def _model() -> ResolvedModelRecord:
    return ResolvedModelRecord(
        MODEL_ID,
        "synthetic-embedding",
        "synthetic-resolved",
        None,
        ModelCapability.EMBEDDING,
        "synthetic",
        8,
    )


def _use_case(
    repository: _Repository,
    *,
    cancellation: _Cancellation | None = None,
    fail_write_commit: bool = False,
) -> tuple[PrepareIndexing, _UowFactory, _Ids, _Ids]:
    scope = ActiveWorkspaceScope()
    scope.select(WORKSPACE_ID)
    uows = _UowFactory(repository, fail_write_commit=fail_write_commit)
    chunk_ids = _Ids(ChunkId, uows.events)
    generation_ids = _Ids(IndexGenerationId, uows.events)
    use_case = PrepareIndexing(
        scope,
        _model(),
        cancellation or _Cancellation(),
        _Token(),
        uows,
        chunk_ids,  # type: ignore[arg-type]
        generation_ids,  # type: ignore[arg-type]
        lambda: NOW,
    )
    return use_case, uows, chunk_ids, generation_ids


def test_new_candidate_and_identical_repeat_are_idempotent() -> None:
    repository = _Repository()
    use_case, uows, chunk_ids, generation_ids = _use_case(repository)

    first = use_case(_processing(), ChunkConfiguration(4, 1))
    first_chunk_id_calls = chunk_ids.calls
    second = use_case(_processing(), ChunkConfiguration(4, 1))

    assert isinstance(first, StagingEmbeddingHandoff)
    assert isinstance(second, StagingEmbeddingHandoff)
    assert first.candidate.generation.id == second.candidate.generation.id
    assert first.candidate == second.candidate
    assert len(repository.generations) == 1
    assert len(repository.candidates) == 1
    assert generation_ids.calls == 1
    assert chunk_ids.calls == first_chunk_id_calls
    assert uows.calls == 4
    assert uows.events.index("exit") < uows.events.index("chunk-id")
    assert uows.events.index("chunk-id") < uows.events.index("factory-2")


def test_compatible_active_returns_without_chunking_or_write() -> None:
    repository = _Repository()
    active = IndexGeneration(
        GENERATION_ID,
        WORKSPACE_ID,
        VERSION_ID,
        JOB_ID,
        MODEL_ID,
        ChunkConfiguration(4, 1).profile.value,
        "exact-text-v1",
        8,
        IndexGenerationState.ACTIVE,
    )
    repository.generations.append(PersistedIndexGeneration(active, NOW, NOW))
    use_case, uows, chunk_ids, generation_ids = _use_case(repository)

    result = use_case(_processing(), ChunkConfiguration(4, 1))

    assert isinstance(result, ReusedActiveIndex)
    assert result.persisted.generation.id == GENERATION_ID
    assert repository.writes == 0
    assert chunk_ids.calls == generation_ids.calls == 0
    assert uows.calls == 1


def test_incompatible_generation_is_untouched_and_new_staging_is_created() -> None:
    repository = _Repository()
    incompatible = IndexGeneration(
        GENERATION_ID,
        WORKSPACE_ID,
        VERSION_ID,
        JOB_ID,
        MODEL_ID,
        "other-profile",
        "exact-text-v1",
        8,
    )
    repository.generations.append(PersistedIndexGeneration(incompatible, NOW))
    use_case, _, _, generation_ids = _use_case(repository)

    result = use_case(_processing(), ChunkConfiguration(4, 1))

    assert isinstance(result, StagingEmbeddingHandoff)
    assert repository.generations[0].generation == incompatible
    assert len(repository.generations) == 2
    assert generation_ids.calls == 1


def test_ambiguous_state_fails_before_writes() -> None:
    repository = _Repository()
    for number in (1, 2):
        generation = IndexGeneration(
            IndexGenerationId(f"50000000-0000-4000-8000-{number:012d}"),
            WORKSPACE_ID,
            VERSION_ID,
            JOB_ID,
            MODEL_ID,
            ChunkConfiguration(4, 1).profile.value,
            "exact-text-v1",
            8,
        )
        repository.generations.append(PersistedIndexGeneration(generation, NOW))
    use_case, uows, _, _ = _use_case(repository)

    with pytest.raises(AmbiguousIndexGeneration, match="ambiguous"):
        use_case(_processing(), ChunkConfiguration(4, 1))

    assert repository.writes == 0
    assert uows.calls == 1


def test_scope_substitution_and_empty_output_fail_without_writes() -> None:
    repository = _Repository()
    use_case, _, _, _ = _use_case(repository)

    with pytest.raises(InvalidIndexingInput, match="ownership is invalid"):
        use_case(_processing(workspace_id=WorkspaceId("10000000-0000-4000-8000-000000000002")))
    with pytest.raises(NoEligibleChunks, match="no eligible chunks"):
        use_case(_processing(text=" \t"))

    assert repository.writes == 0


def test_commit_failure_is_sanitized_and_retry_converges() -> None:
    repository = _Repository()
    failing, _, _, _ = _use_case(repository, fail_write_commit=True)

    with pytest.raises(IndexingPersistenceError, match="candidate persistence failed") as error:
        failing(_processing(), ChunkConfiguration(4, 1))

    assert "sensitive native detail" not in str(error.value)
    assert repository.generations == []
    retry, _, _, _ = _use_case(repository)
    assert isinstance(retry(_processing(), ChunkConfiguration(4, 1)), StagingEmbeddingHandoff)
    assert len(repository.generations) == 1


@pytest.mark.parametrize("failure", ["read", "write"])
def test_repository_failures_are_sanitized_and_rolled_back(failure: str) -> None:
    repository = _Repository()
    repository.fail_discovery = failure == "read"
    repository.fail_write = failure == "write"
    use_case, _, _, _ = _use_case(repository)

    with pytest.raises(IndexingPersistenceError) as captured:
        use_case(_processing(), ChunkConfiguration(4, 1))

    assert "sensitive" not in str(captured.value)
    assert repository.generations == []
    assert repository.candidates == {}


def test_no_active_workspace_fails_before_uow_or_identity_use() -> None:
    repository = _Repository()
    uows = _UowFactory(repository)
    chunk_ids = _Ids(ChunkId)
    generation_ids = _Ids(IndexGenerationId)
    use_case = PrepareIndexing(
        ActiveWorkspaceScope(),
        _model(),
        _Cancellation(),
        _Token(),
        uows,
        chunk_ids,  # type: ignore[arg-type]
        generation_ids,  # type: ignore[arg-type]
        lambda: NOW,
    )

    with pytest.raises(IndexingPersistenceError, match="active workspace is unavailable"):
        use_case(_processing())

    assert uows.calls == 0
    assert chunk_ids.calls == generation_ids.calls == 0


def test_cancellation_never_commits_partial_state() -> None:
    repository = _Repository()
    use_case, uows, _, _ = _use_case(repository, cancellation=_Cancellation(fail_at=8))

    with pytest.raises(IndexingCancelled):
        use_case(_processing(), ChunkConfiguration(4, 1))

    assert "commit" not in uows.events
    assert repository.generations == []
