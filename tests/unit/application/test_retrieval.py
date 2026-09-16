"""Tests for pure deterministic QA retrieval ranking."""

from datetime import UTC, datetime, timedelta

import pytest

from lexlocal.application.ports.embeddings import (
    ChunkEmbedding,
    EmbeddingCompatibility,
    NormalizedEmbeddingVector,
    QueryEmbedding,
)
from lexlocal.application.ports.indexing import PersistedIndexGeneration
from lexlocal.application.ports.retrieval import (
    IncompatibleRetrievalScope,
    InvalidRetrievalInput,
    NoEligibleIndex,
    QaRetrievalRequest,
    ResolvedRetrievalGeneration,
    ResolvedRetrievalScope,
    RetrievalCandidate,
    RetrievalCandidateSet,
    RetrievalConfiguration,
    RetrievalError,
    RetrievalIntegrityError,
    RetrievalPersistenceError,
    RetrievalRegistration,
)
from lexlocal.application.retrieval import (
    PrepareRetrieval,
    StageRetrieval,
    rank_retrieval_candidates,
)
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.domain.documents import VersionNumber
from lexlocal.domain.identifiers import (
    ChunkId,
    DocumentId,
    DocumentPageId,
    DocumentVersionId,
    EvidenceItemId,
    IndexGenerationId,
    LocalModelId,
    ProcessingJobId,
    QaRequestId,
    RetrievalRunId,
    SourceLocatorId,
    WorkspaceId,
)
from lexlocal.domain.processing import (
    IndexGeneration,
    IndexGenerationState,
    ProcessingJobState,
)
from lexlocal.domain.retrieval import (
    PageNumber,
    SimilarityScore,
    SourceLocator,
    SourceLocatorKind,
)

NOW = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)
WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
QA_REQUEST_ID = QaRequestId("20000000-0000-4000-8000-000000000001")
MODEL_ID = LocalModelId("30000000-0000-4000-8000-000000000001")
DEFAULT_CONFIGURATION = RetrievalConfiguration()
RETRIEVAL_RUN_ID = RetrievalRunId("b0000000-0000-4000-8000-000000000001")


def _resolved(
    *,
    document: int = 1,
    version: int = 1,
    generation: int = 1,
    activated_at: datetime = NOW,
) -> ResolvedRetrievalGeneration:
    index = IndexGeneration(
        IndexGenerationId(f"40000000-0000-4000-8000-{generation:012d}"),
        WORKSPACE_ID,
        DocumentVersionId(f"50000000-0000-4000-8000-{version:012d}"),
        ProcessingJobId(f"60000000-0000-4000-8000-{generation:012d}"),
        MODEL_ID,
        "chunk-v1",
        "normalize-v1",
        2,
        IndexGenerationState.ACTIVE,
    )
    return ResolvedRetrievalGeneration(
        DocumentId(f"70000000-0000-4000-8000-{document:012d}"),
        VersionNumber(version),
        f"Anonymous document {document}",
        PersistedIndexGeneration(index, NOW, activated_at=activated_at),
        ProcessingJobState.READY,
    )


def _scope(*generations: ResolvedRetrievalGeneration) -> ResolvedRetrievalScope:
    return ResolvedRetrievalScope(
        QaRetrievalRequest(QA_REQUEST_ID, WORKSPACE_ID, "synthetic query"),
        generations or (_resolved(),),
    )


def _candidate(
    generation: ResolvedRetrievalGeneration,
    *,
    chunk: int,
    order: int,
    vector: tuple[float, float],
    passage: str | None = None,
    created_at: datetime = NOW,
) -> RetrievalCandidate:
    compatibility = EmbeddingCompatibility(
        WORKSPACE_ID,
        generation.index_generation_id,
        MODEL_ID,
        "chunk-v1",
        "normalize-v1",
        2,
    )
    locator = SourceLocator(
        SourceLocatorId(f"80000000-0000-4000-8000-{chunk:012d}"),
        WORKSPACE_ID,
        generation.document_version_id,
        DocumentPageId(f"90000000-0000-4000-8000-{chunk:012d}"),
        PageNumber(order + 1),
        SourceLocatorKind.PAGE,
    )
    return RetrievalCandidate(
        generation,
        ChunkEmbedding(
            ChunkId(f"a0000000-0000-4000-8000-{chunk:012d}"),
            compatibility,
            NormalizedEmbeddingVector(vector),
            created_at,
        ),
        order,
        locator,
        passage or f"Synthetic passage {chunk}",
    )


def _query(scope: ResolvedRetrievalScope) -> QueryEmbedding:
    return QueryEmbedding(
        scope.query_compatibility,
        NormalizedEmbeddingVector((1.0, 0.0)),
    )


def _logical_result(
    candidates: RetrievalCandidateSet,
    configuration: RetrievalConfiguration = DEFAULT_CONFIGURATION,
) -> tuple[tuple[int, float, str, int, str], ...]:
    result = rank_retrieval_candidates(candidates, _query(candidates.scope), configuration)
    return tuple(
        (
            item.rank.value,
            item.similarity_score.value,
            str(item.candidate.generation.document_id),
            item.candidate.document_order,
            str(item.candidate.chunk_id),
        )
        for item in result.evidence
    )


class _RetrievalRepositoryDouble:
    def __init__(
        self,
        generations: tuple[ResolvedRetrievalGeneration, ...],
        candidates: tuple[RetrievalCandidate, ...],
        *,
        existing: RetrievalRegistration | None = None,
        resolve_error: Exception | None = None,
        add_error: Exception | None = None,
    ) -> None:
        self.generations = generations
        self.candidates = candidates
        self.existing = existing
        self.resolve_error = resolve_error
        self.add_error = add_error
        self.calls: list[str] = []
        self.requests: list[QaRetrievalRequest] = []
        self.added: list[RetrievalRegistration] = []

    def get_for_qa_request(
        self,
        workspace_id: WorkspaceId,
        qa_request_id: QaRequestId,
    ) -> RetrievalRegistration | None:
        self.calls.append("get")
        assert workspace_id == WORKSPACE_ID
        assert qa_request_id == QA_REQUEST_ID
        return self.existing

    def resolve_scope(self, request: QaRetrievalRequest) -> ResolvedRetrievalScope:
        self.calls.append("resolve")
        self.requests.append(request)
        if self.resolve_error is not None:
            raise self.resolve_error
        return ResolvedRetrievalScope(request, self.generations)

    def load_candidates(self, scope: ResolvedRetrievalScope) -> RetrievalCandidateSet:
        self.calls.append("load")
        return RetrievalCandidateSet(scope, self.candidates)

    def add(self, registration: RetrievalRegistration) -> None:
        self.calls.append("add")
        if self.add_error is not None:
            raise self.add_error
        self.added.append(registration)


class _ReadUnitOfWork:
    def __init__(self, factory: "_ReadUnitOfWorkFactory") -> None:
        self.retrieval = factory.repository
        self._factory = factory
        self._active = False

    def __enter__(self) -> "_ReadUnitOfWork":
        self._active = True
        self._factory.active_count += 1
        return self

    def __exit__(self, *args: object) -> None:
        if self._active:
            self._factory.active_count -= 1
            self._active = False

    def commit(self) -> None:
        raise AssertionError("RAG must not commit")

    def rollback(self) -> None:
        raise AssertionError("RAG must not roll back")


class _ReadUnitOfWorkFactory:
    def __init__(self, repository: _RetrievalRepositoryDouble) -> None:
        self.repository = repository
        self.active_count = 0
        self.created = 0

    def __call__(self) -> _ReadUnitOfWork:
        self.created += 1
        return _ReadUnitOfWork(self)


class _EmbedQueryDouble:
    def __init__(
        self,
        unit_of_work_factory: _ReadUnitOfWorkFactory,
        *,
        vector: tuple[float, float] = (1.0, 0.0),
        error: Exception | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._vector = vector
        self._error = error
        self.calls: list[tuple[str, PersistedIndexGeneration]] = []

    def __call__(
        self,
        query: str,
        target: PersistedIndexGeneration,
    ) -> QueryEmbedding:
        assert self._unit_of_work_factory.active_count == 0
        self.calls.append((query, target))
        if self._error is not None:
            raise self._error
        generation = target.generation
        return QueryEmbedding(
            EmbeddingCompatibility(
                generation.workspace_id,
                generation.id,
                generation.embedding_model_id,
                generation.chunking_profile_version,
                generation.normalization_profile_version,
                generation.embedding_dimensions,
            ),
            NormalizedEmbeddingVector(self._vector),
        )


def _selected_scope() -> ActiveWorkspaceScope:
    scope = ActiveWorkspaceScope()
    scope.select(WORKSPACE_ID)
    return scope


def _prepare(
    repository: _RetrievalRepositoryDouble,
    *,
    embed_error: Exception | None = None,
    clock: object = NOW,
    run_id_factory: object = RETRIEVAL_RUN_ID,
) -> tuple[PrepareRetrieval, _EmbedQueryDouble, _ReadUnitOfWorkFactory, list[int]]:
    factory = _ReadUnitOfWorkFactory(repository)
    embed_query = _EmbedQueryDouble(factory, error=embed_error)
    evidence_calls: list[int] = []

    def evidence_id_factory() -> EvidenceItemId:
        evidence_calls.append(len(evidence_calls) + 1)
        return EvidenceItemId(
            f"c0000000-0000-4000-8000-{len(evidence_calls):012d}"
        )

    use_case = PrepareRetrieval(
        _selected_scope(),
        factory,  # type: ignore[arg-type]
        embed_query,  # type: ignore[arg-type]
        lambda: run_id_factory,  # type: ignore[return-value]
        evidence_id_factory,
        lambda: clock,  # type: ignore[return-value]
    )
    return use_case, embed_query, factory, evidence_calls


def test_cosine_scores_sort_descending_and_keep_exact_full_passages() -> None:
    generation = _resolved()
    scope = _scope(generation)
    candidates = RetrievalCandidateSet(
        scope,
        (
            _candidate(generation, chunk=1, order=0, vector=(0.0, 1.0)),
            _candidate(
                generation,
                chunk=2,
                order=1,
                vector=(0.6, 0.8),
                passage=" Exact full passage Ω\n",
            ),
            _candidate(generation, chunk=3, order=2, vector=(1.0, 0.0)),
        ),
    )

    result = rank_retrieval_candidates(candidates, _query(scope), RetrievalConfiguration())

    assert result.candidate_count == 3
    assert tuple(item.similarity_score.value for item in result.evidence) == (
        1.0,
        0.6,
        0.0,
    )
    assert result.evidence[1].candidate.passage == " Exact full passage Ω\n"


def test_exact_ties_use_frozen_canonical_key_independent_of_input_order() -> None:
    first = _resolved(document=1, version=1, generation=1)
    second = _resolved(document=1, version=2, generation=2)
    third = _resolved(document=2, version=3, generation=3)
    scope = _scope(third, second, first)
    items = (
        _candidate(third, chunk=5, order=0, vector=(1.0, 0.0)),
        _candidate(second, chunk=4, order=0, vector=(1.0, 0.0)),
        _candidate(first, chunk=3, order=2, vector=(1.0, 0.0)),
        _candidate(first, chunk=2, order=1, vector=(1.0, 0.0)),
        _candidate(first, chunk=1, order=0, vector=(1.0, 0.0)),
    )

    forward = _logical_result(RetrievalCandidateSet(scope, items))
    reverse = _logical_result(RetrievalCandidateSet(scope, tuple(reversed(items))))

    assert forward == reverse
    assert tuple((item[2], item[3], item[4]) for item in forward) == (
        (str(first.document_id), 0, str(items[4].chunk_id)),
        (str(first.document_id), 1, str(items[3].chunk_id)),
        (str(first.document_id), 2, str(items[2].chunk_id)),
        (str(second.document_id), 0, str(items[1].chunk_id)),
        (str(third.document_id), 0, str(items[0].chunk_id)),
    )


def test_canonical_float32_round_trip_self_similarity_is_bounded_to_one() -> None:
    generation = _resolved()
    scope = _scope(generation)
    float32_vector = (0.6000000238418579, 0.800000011920929)
    candidate = _candidate(
        generation,
        chunk=1,
        order=0,
        vector=float32_vector,
    )
    query = QueryEmbedding(
        scope.query_compatibility,
        NormalizedEmbeddingVector(float32_vector),
    )

    result = rank_retrieval_candidates(
        RetrievalCandidateSet(scope, (candidate,)),
        query,
        RetrievalConfiguration(),
    )

    assert result.evidence[0].similarity_score == SimilarityScore(1.0)


def test_threshold_is_inclusive_before_top_k_and_candidate_count_is_prefilter() -> None:
    generation = _resolved()
    scope = _scope(generation)
    candidate_set = RetrievalCandidateSet(
        scope,
        (
            _candidate(generation, chunk=1, order=0, vector=(1.0, 0.0)),
            _candidate(generation, chunk=2, order=1, vector=(0.6, 0.8)),
            _candidate(generation, chunk=3, order=2, vector=(0.0, 1.0)),
        ),
    )

    result = rank_retrieval_candidates(
        candidate_set,
        _query(scope),
        RetrievalConfiguration(top_k=1, min_similarity=SimilarityScore(0.6)),
    )

    assert result.candidate_count == 3
    assert len(result.evidence) == 1
    assert result.evidence[0].similarity_score == SimilarityScore(1.0)

    inclusive = rank_retrieval_candidates(
        candidate_set,
        _query(scope),
        RetrievalConfiguration(top_k=5, min_similarity=SimilarityScore(0.6)),
    )
    assert tuple(item.similarity_score.value for item in inclusive.evidence) == (1.0, 0.6)


def test_valid_candidates_below_threshold_produce_successful_empty_ranking() -> None:
    generation = _resolved()
    scope = _scope(generation)
    candidates = RetrievalCandidateSet(
        scope,
        (_candidate(generation, chunk=1, order=0, vector=(0.0, 1.0)),),
    )

    result = rank_retrieval_candidates(
        candidates,
        _query(scope),
        RetrievalConfiguration(min_similarity=SimilarityScore(0.1)),
    )

    assert result.candidate_count == 1
    assert result.evidence == ()


def test_fewer_candidates_than_top_k_returns_every_remaining_candidate() -> None:
    generation = _resolved()
    scope = _scope(generation)
    candidates = RetrievalCandidateSet(
        scope,
        (
            _candidate(generation, chunk=1, order=0, vector=(1.0, 0.0)),
            _candidate(generation, chunk=2, order=1, vector=(0.0, 1.0)),
        ),
    )

    result = rank_retrieval_candidates(candidates, _query(scope), RetrievalConfiguration())

    assert len(result.evidence) == 2


def test_query_must_target_the_canonical_representative_and_exact_cohort() -> None:
    first = _resolved(document=1, version=1, generation=1)
    second = _resolved(document=2, version=2, generation=2)
    scope = _scope(second, first)
    candidates = RetrievalCandidateSet(
        scope,
        (
            _candidate(first, chunk=1, order=0, vector=(1.0, 0.0)),
            _candidate(second, chunk=2, order=0, vector=(1.0, 0.0)),
        ),
    )
    wrong_target = QueryEmbedding(
        EmbeddingCompatibility(
            WORKSPACE_ID,
            second.index_generation_id,
            MODEL_ID,
            "chunk-v1",
            "normalize-v1",
            2,
        ),
        NormalizedEmbeddingVector((1.0, 0.0)),
    )

    with pytest.raises(RetrievalIntegrityError, match="compatibility is invalid"):
        rank_retrieval_candidates(candidates, wrong_target, RetrievalConfiguration())


def test_logical_ranking_ignores_embedding_timestamps_and_input_order() -> None:
    generation = _resolved(activated_at=NOW + timedelta(seconds=5))
    scope = _scope(generation)
    first = _candidate(
        generation,
        chunk=1,
        order=0,
        vector=(0.6, 0.8),
        created_at=NOW,
    )
    second = _candidate(
        generation,
        chunk=2,
        order=1,
        vector=(0.8, 0.6),
        created_at=NOW + timedelta(days=2),
    )

    result = _logical_result(RetrievalCandidateSet(scope, (first, second)))
    reordered = _logical_result(RetrievalCandidateSet(scope, (second, first)))

    assert result == reordered
    assert tuple(item[1] for item in result) == (0.8, 0.6)


def test_ranking_errors_do_not_expose_passage_or_vector_values() -> None:
    generation = _resolved()
    candidate = _candidate(
        generation,
        chunk=1,
        order=0,
        vector=(1.0, 0.0),
        passage="private synthetic passage",
    )
    scope = _scope(generation)
    candidates = RetrievalCandidateSet(scope, (candidate,))
    wrong_query = QueryEmbedding(
        EmbeddingCompatibility(
            WORKSPACE_ID,
            generation.index_generation_id,
            MODEL_ID,
            "chunk-v1",
            "normalize-v1",
            3,
        ),
        NormalizedEmbeddingVector((1.0, 0.0, 0.0)),
    )

    with pytest.raises(RetrievalIntegrityError) as raised:
        rank_retrieval_candidates(candidates, wrong_query, RetrievalConfiguration())

    message = str(raised.value)
    assert "private synthetic passage" not in message
    assert "1.0" not in message


def test_prepare_uses_scope_once_then_embeds_and_builds_exact_registration() -> None:
    first = _resolved(document=1, version=1, generation=1)
    second = _resolved(document=2, version=2, generation=2)
    candidates = (
        _candidate(second, chunk=3, order=0, vector=(0.0, 1.0)),
        _candidate(first, chunk=2, order=1, vector=(0.6, 0.8)),
        _candidate(
            first,
            chunk=1,
            order=0,
            vector=(1.0, 0.0),
            passage=" Exact synthetic evidence Ω\n",
        ),
    )
    repository = _RetrievalRepositoryDouble((second, first), candidates)
    prepare, embed_query, factory, evidence_calls = _prepare(repository)
    configuration = RetrievalConfiguration(
        top_k=2,
        min_similarity=SimilarityScore(0.1),
    )

    registration = prepare(
        QA_REQUEST_ID,
        " exact synthetic query \n",
        configuration,
    )

    assert repository.calls == ["get", "resolve", "load"]
    assert factory.created == 1
    assert factory.active_count == 0
    assert embed_query.calls == [
        (" exact synthetic query \n", first.persisted),
    ]
    assert registration.retrieval_run_id == RETRIEVAL_RUN_ID
    assert registration.scope.generations == (first, second)
    assert registration.configuration == configuration
    assert registration.candidate_count == 3
    assert tuple(item.evidence.rank.value for item in registration.evidence) == (1, 2)
    assert tuple(item.evidence.similarity_score.value for item in registration.evidence) == (
        1.0,
        0.6,
    )
    assert registration.evidence[0].excerpt == " Exact synthetic evidence Ω\n"
    assert registration.evidence[0].source_locator == candidates[2].source_locator
    assert registration.evidence[0].created_at == NOW
    assert evidence_calls == [1, 2]
    assert repository.added == []


def test_prepare_preserves_exact_optional_document_narrowing() -> None:
    generation = _resolved()
    repository = _RetrievalRepositoryDouble(
        (generation,),
        (_candidate(generation, chunk=1, order=0, vector=(1.0, 0.0)),),
    )
    prepare, _, _, _ = _prepare(repository)

    registration = prepare(
        QA_REQUEST_ID,
        "synthetic query",
        DEFAULT_CONFIGURATION,
        (generation.document_id,),
    )

    assert repository.requests[0].document_ids == (generation.document_id,)
    assert registration.scope.request.document_ids == (generation.document_id,)


def test_missing_workspace_fails_before_repository_or_query_embedding() -> None:
    generation = _resolved()
    repository = _RetrievalRepositoryDouble(
        (generation,),
        (_candidate(generation, chunk=1, order=0, vector=(1.0, 0.0)),),
    )
    factory = _ReadUnitOfWorkFactory(repository)
    embed_query = _EmbedQueryDouble(factory)
    prepare = PrepareRetrieval(
        ActiveWorkspaceScope(),
        factory,  # type: ignore[arg-type]
        embed_query,  # type: ignore[arg-type]
        lambda: RETRIEVAL_RUN_ID,
        lambda: EvidenceItemId("c0000000-0000-4000-8000-000000000001"),
        lambda: NOW,
    )

    with pytest.raises(RetrievalPersistenceError, match="workspace is unavailable"):
        prepare(QA_REQUEST_ID, "synthetic query", DEFAULT_CONFIGURATION)

    assert factory.created == 0
    assert repository.calls == []
    assert embed_query.calls == []


def test_invalid_configuration_fails_before_repository_or_query_embedding() -> None:
    generation = _resolved()
    repository = _RetrievalRepositoryDouble(
        (generation,),
        (_candidate(generation, chunk=1, order=0, vector=(1.0, 0.0)),),
    )
    prepare, embed_query, factory, _ = _prepare(repository)

    with pytest.raises(InvalidRetrievalInput, match="configuration is invalid"):
        prepare(
            QA_REQUEST_ID,
            "synthetic query",
            object(),  # type: ignore[arg-type]
        )

    assert factory.created == 0
    assert repository.calls == []
    assert embed_query.calls == []


@pytest.mark.parametrize(
    "repository",
    [
        _RetrievalRepositoryDouble((), ()),
        _RetrievalRepositoryDouble(
            (_resolved(),),
            (),
            resolve_error=RetrievalIntegrityError("synthetic corrupt state"),
        ),
    ],
)
def test_scope_or_candidate_failure_happens_before_query_inference(
    repository: _RetrievalRepositoryDouble,
) -> None:
    prepare, embed_query, _, _ = _prepare(repository)

    with pytest.raises((NoEligibleIndex, RetrievalIntegrityError)):
        prepare(QA_REQUEST_ID, "synthetic query", DEFAULT_CONFIGURATION)

    assert embed_query.calls == []


def test_incompatible_generation_cohort_fails_before_query_inference() -> None:
    first = _resolved()
    incompatible_index = IndexGeneration(
        IndexGenerationId("40000000-0000-4000-8000-000000000002"),
        WORKSPACE_ID,
        DocumentVersionId("50000000-0000-4000-8000-000000000002"),
        ProcessingJobId("60000000-0000-4000-8000-000000000002"),
        MODEL_ID,
        "other-chunk-profile",
        "normalize-v1",
        2,
        IndexGenerationState.ACTIVE,
    )
    second = ResolvedRetrievalGeneration(
        DocumentId("70000000-0000-4000-8000-000000000002"),
        VersionNumber(2),
        "Anonymous document 2",
        PersistedIndexGeneration(incompatible_index, NOW, activated_at=NOW),
        ProcessingJobState.READY,
    )
    repository = _RetrievalRepositoryDouble((second, first), ())
    prepare, embed_query, _, _ = _prepare(repository)

    with pytest.raises(IncompatibleRetrievalScope):
        prepare(QA_REQUEST_ID, "synthetic query", DEFAULT_CONFIGURATION)

    assert repository.calls == ["get", "resolve"]
    assert embed_query.calls == []


def test_successful_empty_threshold_result_is_staging_ready() -> None:
    generation = _resolved()
    repository = _RetrievalRepositoryDouble(
        (generation,),
        (_candidate(generation, chunk=1, order=0, vector=(0.0, 1.0)),),
    )
    prepare, embed_query, _, evidence_calls = _prepare(repository)

    registration = prepare(
        QA_REQUEST_ID,
        "synthetic query",
        RetrievalConfiguration(min_similarity=SimilarityScore(0.1)),
    )

    assert len(embed_query.calls) == 1
    assert registration.candidate_count == 1
    assert registration.evidence == ()
    assert evidence_calls == []


def test_compatible_committed_retry_skips_inference_ids_time_and_write() -> None:
    generation = _resolved()
    first_repository = _RetrievalRepositoryDouble(
        (generation,),
        (_candidate(generation, chunk=1, order=0, vector=(1.0, 0.0)),),
    )
    first_prepare, _, _, _ = _prepare(first_repository)
    committed = first_prepare(
        QA_REQUEST_ID,
        "synthetic query",
        DEFAULT_CONFIGURATION,
    )
    retry_repository = _RetrievalRepositoryDouble(
        (generation,),
        (),
        existing=committed,
    )
    factory = _ReadUnitOfWorkFactory(retry_repository)
    embed_query = _EmbedQueryDouble(factory, error=AssertionError("must not infer"))

    def forbidden_factory() -> object:
        raise AssertionError("must not create identities or time")

    retry = PrepareRetrieval(
        _selected_scope(),
        factory,  # type: ignore[arg-type]
        embed_query,  # type: ignore[arg-type]
        forbidden_factory,  # type: ignore[arg-type]
        forbidden_factory,  # type: ignore[arg-type]
        forbidden_factory,  # type: ignore[arg-type]
    )

    prepared = retry(QA_REQUEST_ID, "synthetic query", DEFAULT_CONFIGURATION)
    result = StageRetrieval(_selected_scope())(prepared, retry_repository)

    assert prepared is committed
    assert result.registration is committed
    assert result.reused is True
    assert retry_repository.calls == ["get", "resolve", "get"]
    assert retry_repository.added == []
    assert embed_query.calls == []


@pytest.mark.parametrize(
    ("query", "configuration"),
    [
        ("different synthetic query", DEFAULT_CONFIGURATION),
        (
            "synthetic query",
            RetrievalConfiguration(min_similarity=SimilarityScore(0.5)),
        ),
    ],
)
def test_same_qa_retry_with_conflicting_query_or_configuration_fails_closed(
    query: str,
    configuration: RetrievalConfiguration,
) -> None:
    generation = _resolved()
    initial_repository = _RetrievalRepositoryDouble(
        (generation,),
        (_candidate(generation, chunk=1, order=0, vector=(1.0, 0.0)),),
    )
    initial, _, _, _ = _prepare(initial_repository)
    committed = initial(QA_REQUEST_ID, "synthetic query", DEFAULT_CONFIGURATION)
    repository = _RetrievalRepositoryDouble((generation,), (), existing=committed)
    retry, embed_query, _, _ = _prepare(repository)

    with pytest.raises(RetrievalIntegrityError, match="incompatible"):
        retry(QA_REQUEST_ID, query, configuration)

    assert repository.calls == ["get", "resolve"]
    assert embed_query.calls == []


def test_staging_rechecks_and_reuses_concurrent_equivalent_committed_run() -> None:
    generation = _resolved()
    candidates = (_candidate(generation, chunk=1, order=0, vector=(1.0, 0.0)),)
    first_repository = _RetrievalRepositoryDouble((generation,), candidates)
    first_prepare, _, _, _ = _prepare(first_repository)
    prepared = first_prepare(
        QA_REQUEST_ID,
        "synthetic query",
        DEFAULT_CONFIGURATION,
    )
    second_repository = _RetrievalRepositoryDouble((generation,), candidates)
    second_prepare, _, _, _ = _prepare(
        second_repository,
        clock=NOW + timedelta(seconds=1),
        run_id_factory=RetrievalRunId(
            "b0000000-0000-4000-8000-000000000002"
        ),
    )
    committed = second_prepare(
        QA_REQUEST_ID,
        "synthetic query",
        DEFAULT_CONFIGURATION,
    )
    staging_repository = _RetrievalRepositoryDouble(
        (generation,),
        candidates,
        existing=committed,
    )

    result = StageRetrieval(_selected_scope())(prepared, staging_repository)

    assert result.reused is True
    assert result.registration is committed
    assert result.registration.retrieval_run_id != prepared.retrieval_run_id
    assert staging_repository.added == []


def test_staging_is_transaction_neutral_and_conflicts_fail_closed() -> None:
    generation = _resolved()
    candidates = (_candidate(generation, chunk=1, order=0, vector=(1.0, 0.0)),)
    repository = _RetrievalRepositoryDouble((generation,), candidates)
    prepare, _, _, _ = _prepare(repository)
    registration = prepare(
        QA_REQUEST_ID,
        "synthetic query",
        DEFAULT_CONFIGURATION,
    )

    result = StageRetrieval(_selected_scope())(registration, repository)

    assert result.reused is False
    assert result.registration is registration
    assert repository.added == [registration]

    conflict = _RetrievalRepositoryDouble(
        (generation,),
        candidates,
        existing=registration,
    )
    other_registration = RetrievalRegistration(
        RetrievalRunId("b0000000-0000-4000-8000-000000000003"),
        registration.scope,
        RetrievalConfiguration(min_similarity=SimilarityScore(0.5)),
        registration.candidate_count,
        (),
        NOW,
    )
    with pytest.raises(RetrievalIntegrityError, match="incompatible"):
        StageRetrieval(_selected_scope())(other_registration, conflict)

    assert conflict.added == []


def test_staging_rechecks_the_sole_active_workspace_before_repository_use() -> None:
    generation = _resolved()
    candidates = (_candidate(generation, chunk=1, order=0, vector=(1.0, 0.0)),)
    repository = _RetrievalRepositoryDouble((generation,), candidates)
    prepare, _, _, _ = _prepare(repository)
    registration = prepare(
        QA_REQUEST_ID,
        "synthetic query",
        DEFAULT_CONFIGURATION,
    )
    repository.calls.clear()
    changed_scope = ActiveWorkspaceScope()
    changed_scope.select(WorkspaceId("10000000-0000-4000-8000-000000000002"))

    with pytest.raises(RetrievalIntegrityError, match="ownership is invalid"):
        StageRetrieval(changed_scope)(registration, repository)

    assert repository.calls == []


def test_provider_and_staging_failures_are_sanitized() -> None:
    generation = _resolved()
    candidates = (_candidate(generation, chunk=1, order=0, vector=(1.0, 0.0)),)
    repository = _RetrievalRepositoryDouble((generation,), candidates)
    prepare, _, _, _ = _prepare(
        repository,
        embed_error=RuntimeError("private provider detail"),
    )

    with pytest.raises(RetrievalError) as provider_error:
        prepare(QA_REQUEST_ID, "synthetic query", DEFAULT_CONFIGURATION)
    assert "private provider detail" not in str(provider_error.value)

    clean_prepare, _, _, _ = _prepare(repository)
    registration = clean_prepare(
        QA_REQUEST_ID,
        "synthetic query",
        DEFAULT_CONFIGURATION,
    )
    failing_repository = _RetrievalRepositoryDouble(
        (generation,),
        candidates,
        add_error=RuntimeError("private SQL detail"),
    )
    with pytest.raises(RetrievalPersistenceError) as persistence_error:
        StageRetrieval(_selected_scope())(registration, failing_repository)
    assert "private SQL detail" not in str(persistence_error.value)


def test_invalid_or_duplicate_injected_identities_fail_before_staging() -> None:
    generation = _resolved()
    candidates = (
        _candidate(generation, chunk=1, order=0, vector=(1.0, 0.0)),
        _candidate(generation, chunk=2, order=1, vector=(0.6, 0.8)),
    )
    repository = _RetrievalRepositoryDouble((generation,), candidates)
    invalid_run_prepare, _, _, _ = _prepare(
        repository,
        run_id_factory="private invalid identifier",
    )

    with pytest.raises(RetrievalPersistenceError) as invalid_run:
        invalid_run_prepare(
            QA_REQUEST_ID,
            "synthetic query",
            DEFAULT_CONFIGURATION,
        )
    assert "private invalid identifier" not in str(invalid_run.value)

    factory = _ReadUnitOfWorkFactory(repository)
    embed_query = _EmbedQueryDouble(factory)
    duplicate_id = EvidenceItemId("c0000000-0000-4000-8000-000000000001")
    duplicate_evidence_prepare = PrepareRetrieval(
        _selected_scope(),
        factory,  # type: ignore[arg-type]
        embed_query,
        lambda: RETRIEVAL_RUN_ID,
        lambda: duplicate_id,
        lambda: NOW,
    )

    with pytest.raises(RetrievalPersistenceError, match="registration creation failed"):
        duplicate_evidence_prepare(
            QA_REQUEST_ID,
            "synthetic query",
            DEFAULT_CONFIGURATION,
        )
    assert repository.added == []


@pytest.mark.parametrize(
    "invalid_clock",
    [
        datetime(2026, 9, 7, 9, 0),
        NOW + timedelta(microseconds=1),
        "private clock value",
    ],
)
def test_invalid_clock_is_rejected_without_leaking_value(invalid_clock: object) -> None:
    generation = _resolved()
    repository = _RetrievalRepositoryDouble(
        (generation,),
        (_candidate(generation, chunk=1, order=0, vector=(1.0, 0.0)),),
    )
    prepare, _, _, _ = _prepare(repository, clock=invalid_clock)

    with pytest.raises(RetrievalPersistenceError) as raised:
        prepare(QA_REQUEST_ID, "synthetic query", DEFAULT_CONFIGURATION)

    assert str(invalid_clock) not in str(raised.value)
