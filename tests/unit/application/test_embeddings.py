"""Tests for provider-independent embedding validation and normalization."""

import ast
import struct
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from lexlocal.application.embeddings import (
    EmbedQuery,
    EmbedStagingChunks,
    normalize_provider_vectors,
    prepare_chunk_embeddings,
    prepare_query_embedding,
)
from lexlocal.application.ports.embeddings import (
    EMBEDDING_DTYPE,
    ChunkEmbedding,
    EmbeddingCancelled,
    EmbeddingCompatibility,
    EmbeddingModelIncompatible,
    EmbeddingPersistenceError,
    EmbeddingProviderFailure,
    InvalidEmbeddingInput,
    InvalidEmbeddingVector,
    NormalizedEmbeddingVector,
    PersistedEmbeddingSet,
)
from lexlocal.application.ports.indexing import (
    ActivatedIndex,
    CandidateChunkSet,
    ChunkProfile,
    IndexChunk,
    IndexingPersistenceError,
    LogicalChunk,
    PersistedIndexGeneration,
    StagingEmbeddingHandoff,
)
from lexlocal.application.ports.local_models import (
    EmbeddingProvider,
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
    ResolvedModelRecord,
)
from lexlocal.application.ports.processing import PageExtractionMethod
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
from lexlocal.domain.retrieval import PageNumber

WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
VERSION_ID = DocumentVersionId("20000000-0000-4000-8000-000000000001")
JOB_ID = ProcessingJobId("30000000-0000-4000-8000-000000000001")
GENERATION_ID = IndexGenerationId("40000000-0000-4000-8000-000000000001")
MODEL_ID = LocalModelId("50000000-0000-4000-8000-000000000001")
OTHER_MODEL_ID = LocalModelId("50000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 9, 5, 8, 30, tzinfo=UTC)
DOCUMENT_ID = DocumentId("15000000-0000-4000-8000-000000000001")


def _generation(
    *,
    state: IndexGenerationState = IndexGenerationState.STAGING,
    model_id: LocalModelId = MODEL_ID,
    dimensions: int = 2,
) -> IndexGeneration:
    return IndexGeneration(
        GENERATION_ID,
        WORKSPACE_ID,
        VERSION_ID,
        JOB_ID,
        model_id,
        "page-codepoint-window-v1",
        "exact-text-v1",
        dimensions,
        state,
    )


def _status(
    *,
    readiness: ModelReadiness = ModelReadiness.READY,
    capability: ModelCapability = ModelCapability.EMBEDDING,
    model_id: LocalModelId = MODEL_ID,
    dimensions: int | None = 2,
) -> LocalModelStatus:
    return LocalModelStatus(
        ResolvedModelRecord(
            model_id,
            "synthetic-embedding",
            "synthetic/resolved-embedding",
            "1",
            capability,
            "local-synthetic",
            dimensions,
        ),
        readiness,
        "SyntheticExecutionProvider",
    )


def _chunk(number: int, document_order: int) -> IndexChunk:
    logical = LogicalChunk(
        WORKSPACE_ID,
        VERSION_ID,
        DocumentPageId(f"60000000-0000-4000-8000-{number:012d}"),
        PageNumber(number),
        SourceLocatorId(f"70000000-0000-4000-8000-{number:012d}"),
        document_order,
        0,
        0,
        4,
        f"t{number:03d}",
        PageExtractionMethod.NATIVE,
        ChunkProfile("page-codepoint-window-v1"),
    )
    return IndexChunk(
        ChunkId(f"80000000-0000-4000-8000-{number:012d}"),
        logical,
        f"token-{number}".encode(),
        NOW,
    )


def _handoff() -> StagingEmbeddingHandoff:
    return StagingEmbeddingHandoff(
        CandidateChunkSet(
            _generation(),
            (_chunk(1, 0), _chunk(2, 1)),
            NOW,
        )
    )


def _active_target() -> PersistedIndexGeneration:
    return PersistedIndexGeneration(
        _generation(state=IndexGenerationState.ACTIVE),
        NOW,
        activated_at=NOW,
    )


def _handoff_with_count(count: int) -> StagingEmbeddingHandoff:
    return StagingEmbeddingHandoff(
        CandidateChunkSet(
            _generation(),
            tuple(_chunk(number, number - 1) for number in range(1, count + 1)),
            NOW,
        )
    )


def _compatibility_for(handoff: StagingEmbeddingHandoff) -> EmbeddingCompatibility:
    generation = handoff.candidate.generation
    return EmbeddingCompatibility(
        generation.workspace_id,
        generation.id,
        generation.embedding_model_id,
        generation.chunking_profile_version,
        generation.normalization_profile_version,
        generation.embedding_dimensions,
    )


def _stored_embedding(
    handoff: StagingEmbeddingHandoff,
    chunk_id: ChunkId,
    raw_vector: tuple[float, float],
) -> ChunkEmbedding:
    vector = normalize_provider_vectors(
        (raw_vector,),
        expected_count=1,
        expected_dimensions=2,
    )[0]
    return ChunkEmbedding(chunk_id, _compatibility_for(handoff), vector, NOW)


class _MemoryEmbeddingRepository:
    def __init__(
        self,
        handoff: StagingEmbeddingHandoff,
        initial: tuple[ChunkEmbedding, ...] = (),
    ) -> None:
        self.handoff = handoff
        self.items = list(initial)
        self.added_batches: list[tuple[ChunkEmbedding, ...]] = []
        self.read_count = 0
        self.omit_on_read: int | None = None
        self.read_error: Exception | None = None

    def get_for_candidate(
        self,
        handoff: StagingEmbeddingHandoff,
    ) -> PersistedEmbeddingSet:
        self.read_count += 1
        if self.read_error is not None:
            raise self.read_error
        order = {
            chunk.id: index for index, chunk in enumerate(handoff.candidate.chunks)
        }
        items = tuple(sorted(self.items, key=lambda item: order[item.chunk_id]))
        if self.omit_on_read == self.read_count and items:
            items = items[:-1]
        return PersistedEmbeddingSet(
            _compatibility_for(handoff),
            tuple(chunk.id for chunk in handoff.candidate.chunks),
            items,
        )

    def add_batch(
        self,
        handoff: StagingEmbeddingHandoff,
        embeddings: tuple[ChunkEmbedding, ...],
    ) -> None:
        existing_ids = {item.chunk_id for item in self.items}
        if any(item.chunk_id in existing_ids for item in embeddings):
            raise EmbeddingPersistenceError("embedding batch conflicts")
        self.added_batches.append(embeddings)
        self.items.extend(embeddings)


class _MemoryUnitOfWork:
    def __init__(self, factory: "_MemoryUnitOfWorkFactory") -> None:
        self._factory = factory
        self.embeddings = factory.repository
        self._active = False

    def __enter__(self) -> "_MemoryUnitOfWork":
        self._active = True
        self._factory.active_count += 1
        return self

    def __exit__(self, *args: object) -> None:
        if self._active:
            self._factory.active_count -= 1
            self._active = False

    def commit(self) -> None:
        self._factory.commit_count += 1


class _MemoryUnitOfWorkFactory:
    def __init__(self, repository: _MemoryEmbeddingRepository) -> None:
        self.repository = repository
        self.active_count = 0
        self.commit_count = 0

    def __call__(self) -> _MemoryUnitOfWork:
        return _MemoryUnitOfWork(self)


class _Provider(EmbeddingProvider):
    def __init__(
        self,
        vectors_by_text: dict[str, tuple[float, float]],
        *,
        active_transactions: Callable[[], int] = lambda: 0,
        statuses: tuple[LocalModelStatus, ...] | None = None,
        result_override: Sequence[Sequence[float]] | None = None,
    ) -> None:
        self._vectors_by_text = vectors_by_text
        self._active_transactions = active_transactions
        self._statuses = (_status(),) if statuses is None else statuses
        self._result_override = result_override
        self.status_reads = 0
        self.calls: list[tuple[str, ...]] = []

    @property
    def status(self) -> LocalModelStatus:
        status = self._statuses[min(self.status_reads, len(self._statuses) - 1)]
        self.status_reads += 1
        return status

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        if self._active_transactions() != 0:
            raise AssertionError("provider inference ran inside a transaction")
        exact = tuple(texts)
        self.calls.append(exact)
        if self._result_override is not None:
            return self._result_override
        return tuple(self._vectors_by_text[text] for text in exact)


class _FailingProvider(_Provider):
    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.calls.append(tuple(texts))
        raise RuntimeError("sensitive provider detail")


class _Cancellation:
    def __init__(self, cancel_at: int | None = None) -> None:
        self.cancel_at = cancel_at
        self.checks = 0

    def raise_if_cancelled(self) -> None:
        self.checks += 1
        if self.checks == self.cancel_at:
            raise EmbeddingCancelled("synthetic cancellation")


class _Finalizer:
    def __init__(
        self,
        repository: _MemoryEmbeddingRepository,
        error: Exception | None = None,
    ) -> None:
        self._repository = repository
        self._error = error
        self.calls: list[StagingEmbeddingHandoff] = []

    def __call__(self, handoff: StagingEmbeddingHandoff) -> ActivatedIndex:
        self.calls.append(handoff)
        if self._error is not None:
            raise self._error
        assert len(self._repository.items) == len(handoff.candidate.chunks)
        return _activated_index(handoff)


def _activated_index(handoff: StagingEmbeddingHandoff) -> ActivatedIndex:
    generation = replace(
        handoff.candidate.generation,
        state=IndexGenerationState.ACTIVE,
    )
    version = DocumentVersion(
        VERSION_ID,
        WORKSPACE_ID,
        DOCUMENT_ID,
        VersionNumber(1),
        DocumentVersionState.ACTIVE,
    )
    job = ProcessingJob(
        JOB_ID,
        WORKSPACE_ID,
        VERSION_ID,
        AttemptNumber(1),
        ProcessingJobState.READY,
    )
    return ActivatedIndex(version, job, generation)


def _selected_scope() -> ActiveWorkspaceScope:
    scope = ActiveWorkspaceScope()
    scope.select(WORKSPACE_ID)
    return scope


def test_normalization_preserves_provider_positions_and_exact_count() -> None:
    skeleton = ((3.0, 4.0), (0.0, 2.0))
    result = normalize_provider_vectors(
        skeleton,
        expected_count=2,
        expected_dimensions=2,
    )

    assert result[0].values == pytest.approx((0.6, 0.8))
    assert result[1].values == (0.0, 1.0)

    with pytest.raises(InvalidEmbeddingVector, match="output count is invalid"):
        normalize_provider_vectors(
            ((3.0, 4.0),),
            expected_count=2,
            expected_dimensions=2,
        )


def test_normalization_is_deterministic() -> None:
    vectors = ((1.5, -2.5, 4.0),)

    first = normalize_provider_vectors(vectors, expected_count=1, expected_dimensions=3)
    second = normalize_provider_vectors(vectors, expected_count=1, expected_dimensions=3)

    assert first == second


def test_normalized_vector_accepts_exact_canonical_float32_values() -> None:
    canonical = struct.unpack("<2f", struct.pack("<2f", 0.6, 0.8))

    vector = NormalizedEmbeddingVector(canonical)

    assert vector.values == canonical


def test_normalized_vector_still_rejects_clearly_non_unit_values() -> None:
    with pytest.raises(InvalidEmbeddingVector, match="vector is invalid"):
        NormalizedEmbeddingVector((0.5, 0.5))


@pytest.mark.parametrize(
    "vector",
    [
        (True, 1.0),
        ("sensitive-vector-value", 1.0),
        (float("nan"), 1.0),
        (float("inf"), 1.0),
        (float("-inf"), 1.0),
        (0.0, 0.0),
        (5e-324, 5e-324),
    ],
)
def test_normalization_rejects_invalid_numeric_content_without_leakage(
    vector: tuple[object, object],
) -> None:
    with pytest.raises(InvalidEmbeddingVector) as caught:
        normalize_provider_vectors(
            cast("tuple[tuple[float, ...], ...]", (vector,)),
            expected_count=1,
            expected_dimensions=2,
        )

    assert "sensitive-vector-value" not in str(caught.value)
    assert repr(vector) not in str(caught.value)


def test_normalization_rejects_dimension_mismatch() -> None:
    with pytest.raises(InvalidEmbeddingVector, match="dimension is invalid"):
        normalize_provider_vectors(
            ((1.0, 2.0, 3.0),),
            expected_count=1,
            expected_dimensions=2,
        )


def test_chunk_embeddings_preserve_exact_ownership_position_and_timestamp() -> None:
    handoff = _handoff()
    result = prepare_chunk_embeddings(
        handoff,
        _status(),
        ((3.0, 4.0), (0.0, 2.0)),
        NOW,
    )

    assert tuple(item.chunk_id for item in result) == tuple(
        chunk.id for chunk in handoff.candidate.chunks
    )
    assert result[0].vector.values == pytest.approx((0.6, 0.8))
    assert result[1].vector.values == (0.0, 1.0)
    assert all(item.created_at is NOW for item in result)
    assert all(item.compatibility.workspace_id == WORKSPACE_ID for item in result)
    assert all(item.compatibility.index_generation_id == GENERATION_ID for item in result)
    assert all(item.compatibility.embedding_model_id == MODEL_ID for item in result)
    assert all(item.compatibility.dtype == EMBEDDING_DTYPE for item in result)


@pytest.mark.parametrize(
    "status",
    [
        _status(readiness=ModelReadiness.RESOLVED),
        _status(capability=ModelCapability.CHAT, dimensions=None),
        _status(model_id=OTHER_MODEL_ID),
        _status(dimensions=3),
    ],
)
def test_chunk_embedding_rejects_incompatible_provider_status(
    status: LocalModelStatus,
) -> None:
    with pytest.raises(EmbeddingModelIncompatible, match="compatibility is invalid"):
        prepare_chunk_embeddings(
            _handoff(),
            status,
            ((3.0, 4.0), (0.0, 2.0)),
            NOW,
        )


def test_query_requires_explicit_active_target_and_returns_ephemeral_metadata() -> None:
    target = _active_target()
    result = prepare_query_embedding(
        "  exact synthetic query\n",
        WORKSPACE_ID,
        target,
        _status(),
        ((3.0, 4.0),),
    )

    assert result.compatibility.workspace_id == target.generation.workspace_id
    assert result.compatibility.index_generation_id == target.generation.id
    assert result.compatibility.embedding_model_id == target.generation.embedding_model_id
    assert result.compatibility.chunking_profile_version == (
        target.generation.chunking_profile_version
    )
    assert result.compatibility.normalization_profile_version == (
        target.generation.normalization_profile_version
    )
    assert result.compatibility.dtype == EMBEDDING_DTYPE
    assert result.vector.values == pytest.approx((0.6, 0.8))
    assert not hasattr(result, "created_at")
    assert not hasattr(result, "chunk_id")


@pytest.mark.parametrize("query", ["", " ", "\n\t"])
def test_query_rejects_empty_or_whitespace_only_text(query: str) -> None:
    with pytest.raises(InvalidEmbeddingInput, match="query is invalid"):
        prepare_query_embedding(
            query,
            WORKSPACE_ID,
            _active_target(),
            _status(),
            ((1.0, 0.0),),
        )


def test_query_rejects_non_active_or_incompatible_explicit_target() -> None:
    staging_target = PersistedIndexGeneration(_generation(), NOW)

    with pytest.raises(EmbeddingModelIncompatible, match="target is invalid"):
        prepare_query_embedding(
            "synthetic query",
            WORKSPACE_ID,
            staging_target,
            _status(),
            ((1.0, 0.0),),
        )

    with pytest.raises(EmbeddingModelIncompatible, match="compatibility is invalid"):
        prepare_query_embedding(
            "synthetic query",
            WORKSPACE_ID,
            _active_target(),
            _status(model_id=OTHER_MODEL_ID),
            ((1.0, 0.0),),
        )

    other_workspace = WorkspaceId("10000000-0000-4000-8000-000000000002")
    with pytest.raises(EmbeddingModelIncompatible, match="target is invalid"):
        prepare_query_embedding(
            "synthetic query",
            other_workspace,
            _active_target(),
            _status(),
            ((1.0, 0.0),),
        )


def test_chunk_orchestration_batches_in_global_order_outside_transactions() -> None:
    handoff = _handoff_with_count(5)
    repository = _MemoryEmbeddingRepository(handoff)
    factory = _MemoryUnitOfWorkFactory(repository)
    provider = _Provider(
        {f"t{number:03d}": (float(number), 1.0) for number in range(1, 6)},
        active_transactions=lambda: factory.active_count,
    )
    finalizer = _Finalizer(repository)
    use_case = EmbedStagingChunks(
        _selected_scope(),
        provider,
        _Cancellation(),
        factory,
        finalizer,
        lambda: NOW,
        2,
    )

    result = use_case(handoff)

    assert result == _activated_index(handoff)
    assert provider.calls == [
        ("t001", "t002"),
        ("t003", "t004"),
        ("t005",),
    ]
    assert [
        tuple(item.chunk_id for item in batch) for batch in repository.added_batches
    ] == [
        tuple(chunk.id for chunk in handoff.candidate.chunks[:2]),
        tuple(chunk.id for chunk in handoff.candidate.chunks[2:4]),
        (handoff.candidate.chunks[4].id,),
    ]
    expected_vectors = tuple(
        normalize_provider_vectors(
            ((float(number), 1.0),),
            expected_count=1,
            expected_dimensions=2,
        )[0]
        for number in range(1, 6)
    )
    assert tuple(item.vector for item in repository.items) == expected_vectors
    assert factory.commit_count == 3
    assert finalizer.calls == [handoff]


def test_existing_compatible_rows_are_skipped_and_partial_resume_converges() -> None:
    handoff = _handoff_with_count(4)
    initial = (
        _stored_embedding(handoff, handoff.candidate.chunks[0].id, (1.0, 1.0)),
        _stored_embedding(handoff, handoff.candidate.chunks[2].id, (3.0, 1.0)),
    )
    repository = _MemoryEmbeddingRepository(handoff, initial)
    factory = _MemoryUnitOfWorkFactory(repository)
    provider = _Provider(
        {"t002": (2.0, 1.0), "t004": (4.0, 1.0)},
        active_transactions=lambda: factory.active_count,
    )
    finalizer = _Finalizer(repository)

    EmbedStagingChunks(
        _selected_scope(),
        provider,
        _Cancellation(),
        factory,
        finalizer,
        lambda: NOW,
        2,
    )(handoff)

    assert provider.calls == [("t002", "t004")]
    assert tuple(item.chunk_id for item in repository.added_batches[0]) == (
        handoff.candidate.chunks[1].id,
        handoff.candidate.chunks[3].id,
    )
    assert len(repository.items) == 4
    assert finalizer.calls == [handoff]


def test_complete_retry_skips_inference_and_finalizer_failure_is_not_success() -> None:
    handoff = _handoff()
    repository = _MemoryEmbeddingRepository(handoff)
    factory = _MemoryUnitOfWorkFactory(repository)
    provider = _Provider(
        {"t001": (1.0, 1.0), "t002": (2.0, 1.0)},
        active_transactions=lambda: factory.active_count,
    )
    failing_finalizer = _Finalizer(
        repository,
        IndexingPersistenceError("sensitive finalizer detail"),
    )
    first = EmbedStagingChunks(
        _selected_scope(),
        provider,
        _Cancellation(),
        factory,
        failing_finalizer,
        lambda: NOW,
        2,
    )

    with pytest.raises(EmbeddingPersistenceError) as caught:
        first(handoff)

    assert "sensitive finalizer detail" not in str(caught.value)
    assert len(repository.items) == 2
    calls_after_first_attempt = tuple(provider.calls)
    successful_finalizer = _Finalizer(repository)
    second = EmbedStagingChunks(
        _selected_scope(),
        provider,
        _Cancellation(),
        factory,
        successful_finalizer,
        lambda: NOW,
        2,
    )

    assert second(handoff) == _activated_index(handoff)
    assert tuple(provider.calls) == calls_after_first_attempt
    assert len(repository.items) == 2
    assert successful_finalizer.calls == [handoff]


def test_incomplete_final_reread_blocks_finalizer() -> None:
    handoff = _handoff()
    repository = _MemoryEmbeddingRepository(handoff)
    repository.omit_on_read = 3
    factory = _MemoryUnitOfWorkFactory(repository)
    provider = _Provider({"t001": (1.0, 0.0), "t002": (0.0, 1.0)})
    finalizer = _Finalizer(repository)

    with pytest.raises(EmbeddingPersistenceError, match="embeddings are incomplete"):
        EmbedStagingChunks(
            _selected_scope(),
            provider,
            _Cancellation(),
            factory,
            finalizer,
            lambda: NOW,
            2,
        )(handoff)

    assert finalizer.calls == []


def test_invalid_provider_batch_is_rejected_before_write_or_finalization() -> None:
    handoff = _handoff()
    repository = _MemoryEmbeddingRepository(handoff)
    factory = _MemoryUnitOfWorkFactory(repository)
    provider = _Provider({}, result_override=((1.0, 0.0),))
    finalizer = _Finalizer(repository)

    with pytest.raises(InvalidEmbeddingVector, match="output count is invalid"):
        EmbedStagingChunks(
            _selected_scope(),
            provider,
            _Cancellation(),
            factory,
            finalizer,
            lambda: NOW,
            2,
        )(handoff)

    assert repository.items == []
    assert repository.added_batches == []
    assert factory.commit_count == 0
    assert finalizer.calls == []


def test_provider_status_change_is_rejected_before_inference() -> None:
    handoff = _handoff()
    repository = _MemoryEmbeddingRepository(handoff)
    factory = _MemoryUnitOfWorkFactory(repository)
    provider = _Provider(
        {},
        statuses=(_status(), _status(model_id=OTHER_MODEL_ID)),
    )

    with pytest.raises(EmbeddingModelIncompatible):
        EmbedStagingChunks(
            _selected_scope(),
            provider,
            _Cancellation(),
            factory,
            _Finalizer(repository),
            lambda: NOW,
            2,
        )(handoff)

    assert provider.calls == []
    assert repository.items == []


def test_cancellation_between_batches_preserves_only_committed_compatible_rows() -> None:
    handoff = _handoff_with_count(4)
    repository = _MemoryEmbeddingRepository(handoff)
    factory = _MemoryUnitOfWorkFactory(repository)
    provider = _Provider(
        {f"t{number:03d}": (float(number), 1.0) for number in range(1, 5)},
    )
    finalizer = _Finalizer(repository)

    with pytest.raises(EmbeddingCancelled, match="embedding was cancelled"):
        EmbedStagingChunks(
            _selected_scope(),
            provider,
            _Cancellation(cancel_at=5),
            factory,
            finalizer,
            lambda: NOW,
            2,
        )(handoff)

    assert provider.calls == [("t001", "t002")]
    assert tuple(item.chunk_id for item in repository.items) == tuple(
        chunk.id for chunk in handoff.candidate.chunks[:2]
    )
    assert factory.commit_count == 1
    assert finalizer.calls == []


@pytest.mark.parametrize("batch_size", [0, -1, True, 1.5])
def test_chunk_orchestration_requires_positive_integer_batch_size(
    batch_size: object,
) -> None:
    handoff = _handoff()
    repository = _MemoryEmbeddingRepository(handoff)

    with pytest.raises(InvalidEmbeddingInput, match="batch size is invalid"):
        EmbedStagingChunks(
            _selected_scope(),
            _Provider({}),
            _Cancellation(),
            _MemoryUnitOfWorkFactory(repository),
            _Finalizer(repository),
            lambda: NOW,
            cast("int", batch_size),
        )


def test_candidate_must_match_the_sole_active_workspace_before_dependencies() -> None:
    handoff = _handoff()
    other_scope = ActiveWorkspaceScope()
    other_scope.select(WorkspaceId("10000000-0000-4000-8000-000000000002"))
    repository = _MemoryEmbeddingRepository(handoff)
    provider = _Provider({})

    with pytest.raises(EmbeddingModelIncompatible, match="ownership is invalid"):
        EmbedStagingChunks(
            other_scope,
            provider,
            _Cancellation(),
            _MemoryUnitOfWorkFactory(repository),
            _Finalizer(repository),
            lambda: NOW,
            2,
        )(handoff)

    assert provider.status_reads == 0
    assert provider.calls == []
    assert repository.read_count == 0


def test_missing_active_workspace_fails_before_dependencies() -> None:
    handoff = _handoff()
    repository = _MemoryEmbeddingRepository(handoff)
    provider = _Provider({})

    with pytest.raises(EmbeddingPersistenceError, match="workspace is unavailable"):
        EmbedStagingChunks(
            ActiveWorkspaceScope(),
            provider,
            _Cancellation(),
            _MemoryUnitOfWorkFactory(repository),
            _Finalizer(repository),
            lambda: NOW,
            2,
        )(handoff)

    assert provider.status_reads == 0
    assert repository.read_count == 0


def test_provider_failure_is_sanitized_and_opens_no_write_transaction() -> None:
    handoff = _handoff()
    repository = _MemoryEmbeddingRepository(handoff)
    factory = _MemoryUnitOfWorkFactory(repository)
    provider = _FailingProvider({})
    finalizer = _Finalizer(repository)

    with pytest.raises(EmbeddingProviderFailure) as caught:
        EmbedStagingChunks(
            _selected_scope(),
            provider,
            _Cancellation(),
            factory,
            finalizer,
            lambda: NOW,
            2,
        )(handoff)

    assert "sensitive provider detail" not in str(caught.value)
    assert factory.commit_count == 0
    assert repository.added_batches == []
    assert finalizer.calls == []


def test_query_use_case_uses_exact_text_and_no_persistence_dependency() -> None:
    provider = _Provider({"  exact synthetic query\n": (3.0, 4.0)})
    use_case = EmbedQuery(_selected_scope(), provider)

    result = use_case("  exact synthetic query\n", _active_target())

    assert provider.calls == [("  exact synthetic query\n",)]
    assert result.compatibility == _compatibility_for(_handoff())
    assert result.vector.values == pytest.approx((0.6, 0.8))
    assert not hasattr(result, "created_at")


def test_query_rejects_non_active_or_cross_workspace_target_before_inference() -> None:
    provider = _Provider({})
    use_case = EmbedQuery(_selected_scope(), provider)

    with pytest.raises(EmbeddingModelIncompatible, match="target is invalid"):
        use_case("synthetic query", PersistedIndexGeneration(_generation(), NOW))

    other_target = replace(
        _active_target(),
        generation=replace(
            _active_target().generation,
            workspace_id=WorkspaceId("10000000-0000-4000-8000-000000000002"),
        ),
    )
    with pytest.raises(EmbeddingModelIncompatible, match="target is invalid"):
        use_case("synthetic query", other_target)

    assert provider.status_reads == 0
    assert provider.calls == []


def test_application_module_has_no_technical_dependencies() -> None:
    module_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "lexlocal"
        / "application"
        / "embeddings.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert all(
        not module.startswith(
            (
                "foundry_local_sdk",
                "numpy",
                "sqlite3",
                "struct",
                "lexlocal.infrastructure",
                "lexlocal.bootstrap",
                "lexlocal.application.ports.security",
            )
        )
        for module in imported_modules
    )
