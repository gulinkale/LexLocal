"""Orchestrate and rank deterministic QA retrieval without owning transactions."""

from collections.abc import Callable
from datetime import datetime, timedelta
from math import fsum, isfinite

from lexlocal.application.ports.embeddings import EmbeddingError, QueryEmbedding
from lexlocal.application.ports.indexing import PersistedIndexGeneration
from lexlocal.application.ports.retrieval import (
    InvalidRetrievalInput,
    QaRetrievalRequest,
    RankedRetrievalEvidence,
    ResolvedRetrievalScope,
    RetrievalCandidate,
    RetrievalCandidateSet,
    RetrievalConfiguration,
    RetrievalError,
    RetrievalEvidenceRegistration,
    RetrievalIntegrityError,
    RetrievalPersistenceError,
    RetrievalRanking,
    RetrievalRegistration,
    RetrievalRepository,
    RetrievalResult,
)
from lexlocal.application.ports.unit_of_work import UnitOfWork
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.domain.identifiers import (
    DocumentId,
    EvidenceItemId,
    QaRequestId,
    RetrievalRunId,
    WorkspaceId,
)
from lexlocal.domain.retrieval import Evidence, EvidenceRank, SimilarityScore


class PrepareRetrieval:
    """Prepare one complete QA retrieval graph before final-write staging."""

    def __init__(
        self,
        active_scope: ActiveWorkspaceScope,
        unit_of_work_factory: Callable[[], UnitOfWork],
        embed_query: Callable[[str, PersistedIndexGeneration], QueryEmbedding],
        retrieval_run_id_factory: Callable[[], RetrievalRunId],
        evidence_item_id_factory: Callable[[], EvidenceItemId],
        clock: Callable[[], datetime],
    ) -> None:
        self._active_scope = active_scope
        self._unit_of_work_factory = unit_of_work_factory
        self._embed_query = embed_query
        self._retrieval_run_id_factory = retrieval_run_id_factory
        self._evidence_item_id_factory = evidence_item_id_factory
        self._clock = clock

    def __call__(
        self,
        qa_request_id: QaRequestId,
        query: str,
        configuration: RetrievalConfiguration,
        document_ids: tuple[DocumentId, ...] | None = None,
    ) -> RetrievalRegistration:
        """Return a reused registration or a fully prepared new registration."""

        workspace_id = self._workspace_id()
        if not isinstance(configuration, RetrievalConfiguration):
            raise InvalidRetrievalInput("retrieval configuration is invalid")
        request = QaRetrievalRequest(
            qa_request_id,
            workspace_id,
            query,
            document_ids,
        )
        existing, candidates = self._read_state(request, configuration)
        if existing is not None:
            return existing
        if candidates is None:
            raise RetrievalIntegrityError("retrieval candidates are unavailable")

        query_embedding = self._query_embedding(request, candidates.scope)
        ranking = rank_retrieval_candidates(
            candidates,
            query_embedding,
            configuration,
        )
        return self._registration(ranking)

    def _workspace_id(self) -> WorkspaceId:
        try:
            workspace_id = self._active_scope.require_workspace_id()
        except Exception:
            raise RetrievalPersistenceError(
                "active workspace is unavailable"
            ) from None
        if not isinstance(workspace_id, WorkspaceId):
            raise RetrievalPersistenceError("active workspace is unavailable")
        return workspace_id

    def _read_state(
        self,
        request: QaRetrievalRequest,
        configuration: RetrievalConfiguration,
    ) -> tuple[RetrievalRegistration | None, RetrievalCandidateSet | None]:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                repository = unit_of_work.retrieval
                existing = repository.get_for_qa_request(
                    request.workspace_id,
                    request.qa_request_id,
                )
                if existing is not None:
                    resolved = repository.resolve_scope(request)
                    _require_reusable(existing, resolved, configuration)
                    return existing, None
                scope = repository.resolve_scope(request)
                return None, repository.load_candidates(scope)
        except RetrievalError:
            raise
        except Exception:
            raise RetrievalPersistenceError("retrieval preparation failed") from None

    def _query_embedding(
        self,
        request: QaRetrievalRequest,
        scope: ResolvedRetrievalScope,
    ) -> QueryEmbedding:
        try:
            return self._embed_query(
                request.query,
                scope.representative.persisted,
            )
        except EmbeddingError:
            raise RetrievalError("retrieval query embedding failed") from None
        except Exception:
            raise RetrievalError("retrieval query embedding failed") from None

    def _registration(self, ranking: RetrievalRanking) -> RetrievalRegistration:
        try:
            created_at = self._created_at()
            retrieval_run_id = self._retrieval_run_id_factory()
            if not isinstance(retrieval_run_id, RetrievalRunId):
                raise TypeError
            evidence_item_ids = tuple(
                self._evidence_item_id_factory() for _ in ranking.evidence
            )
            if (
                not all(isinstance(item, EvidenceItemId) for item in evidence_item_ids)
                or len(set(evidence_item_ids)) != len(evidence_item_ids)
            ):
                raise TypeError
            evidence = tuple(
                self._evidence_registration(
                    ranked,
                    evidence_item_id,
                    retrieval_run_id,
                    created_at,
                )
                for ranked, evidence_item_id in zip(
                    ranking.evidence,
                    evidence_item_ids,
                    strict=True,
                )
            )
            return RetrievalRegistration(
                retrieval_run_id,
                ranking.scope,
                ranking.configuration,
                ranking.candidate_count,
                evidence,
                created_at,
            )
        except RetrievalError:
            raise
        except Exception:
            raise RetrievalPersistenceError(
                "retrieval registration creation failed"
            ) from None

    def _evidence_registration(
        self,
        ranked: RankedRetrievalEvidence,
        evidence_item_id: EvidenceItemId,
        retrieval_run_id: RetrievalRunId,
        created_at: datetime,
    ) -> RetrievalEvidenceRegistration:
        candidate = ranked.candidate
        generation = candidate.generation
        evidence = Evidence(
            evidence_item_id,
            generation.workspace_id,
            retrieval_run_id,
            generation.document_id,
            generation.document_version_id,
            candidate.source_locator.page_number,
            ranked.rank,
            ranked.similarity_score,
            candidate.chunk_id,
            candidate.source_locator.id,
        )
        return RetrievalEvidenceRegistration(
            evidence,
            generation.index_generation_id,
            candidate.document_order,
            candidate.source_locator,
            generation.document_display_name,
            generation.version_number,
            candidate.passage,
            created_at,
        )

    def _created_at(self) -> datetime:
        value = self._clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() != timedelta(0)
            or value.microsecond % 1000 != 0
        ):
            raise RetrievalPersistenceError("retrieval clock returned invalid data")
        return value


class StageRetrieval:
    """Stage one prepared graph through the caller's active repository only."""

    def __init__(self, active_scope: ActiveWorkspaceScope) -> None:
        self._active_scope = active_scope

    def __call__(
        self,
        registration: RetrievalRegistration,
        repository: RetrievalRepository,
    ) -> RetrievalResult:
        """Stage or reuse a graph without committing or rolling back its transaction."""

        workspace_id = self._workspace_id()
        if (
            not isinstance(registration, RetrievalRegistration)
            or registration.workspace_id != workspace_id
        ):
            raise RetrievalIntegrityError("retrieval staging ownership is invalid")
        try:
            existing = repository.get_for_qa_request(
                workspace_id,
                registration.qa_request_id,
            )
            if existing is not None:
                if not _same_retrieval_intent(existing, registration):
                    raise RetrievalIntegrityError(
                        "existing QA retrieval is incompatible"
                    )
                return RetrievalResult(existing, reused=True)
            repository.add(registration)
            return RetrievalResult(registration, reused=False)
        except RetrievalError:
            raise
        except Exception:
            raise RetrievalPersistenceError("retrieval staging failed") from None

    def _workspace_id(self) -> WorkspaceId:
        try:
            workspace_id = self._active_scope.require_workspace_id()
        except Exception:
            raise RetrievalPersistenceError(
                "active workspace is unavailable"
            ) from None
        if not isinstance(workspace_id, WorkspaceId):
            raise RetrievalPersistenceError("active workspace is unavailable")
        return workspace_id


def rank_retrieval_candidates(
    candidates: RetrievalCandidateSet,
    query_embedding: QueryEmbedding,
    configuration: RetrievalConfiguration,
) -> RetrievalRanking:
    """Score, filter, and rank one complete compatible candidate set."""

    if not isinstance(candidates, RetrievalCandidateSet):
        raise RetrievalIntegrityError("retrieval candidates are invalid")
    if not isinstance(query_embedding, QueryEmbedding):
        raise RetrievalIntegrityError("query embedding is invalid")
    if not isinstance(configuration, RetrievalConfiguration):
        raise RetrievalIntegrityError("retrieval configuration is invalid")
    _validate_query_compatibility(candidates.scope, query_embedding)

    scored = tuple(
        (_cosine_score(query_embedding, candidate), candidate)
        for candidate in candidates.candidates
    )
    eligible = tuple(
        item
        for item in scored
        if item[0].value >= configuration.min_similarity.value
    )
    ordered = sorted(eligible, key=_ranking_key)[: configuration.top_k]
    evidence = tuple(
        RankedRetrievalEvidence(EvidenceRank(rank), score, candidate)
        for rank, (score, candidate) in enumerate(ordered, start=1)
    )
    return RetrievalRanking(
        scope=candidates.scope,
        configuration=configuration,
        candidate_count=len(scored),
        evidence=evidence,
    )


def _validate_query_compatibility(
    scope: ResolvedRetrievalScope,
    query_embedding: QueryEmbedding,
) -> None:
    if query_embedding.compatibility != scope.query_compatibility:
        raise RetrievalIntegrityError("query embedding compatibility is invalid")


def _cosine_score(
    query_embedding: QueryEmbedding,
    candidate: RetrievalCandidate,
) -> SimilarityScore:
    query_values = query_embedding.vector.values
    candidate_values = candidate.embedding.vector.values
    if len(query_values) != len(candidate_values):
        raise RetrievalIntegrityError("retrieval vector dimensions are inconsistent")
    score = fsum(
        left * right
        for left, right in zip(query_values, candidate_values, strict=True)
    )
    if not isfinite(score):
        raise RetrievalIntegrityError("retrieval similarity score is invalid")
    # Accepted vectors may be canonical float32 round-trips whose dot product differs
    # from the mathematical cosine bound by a few machine units.
    bounded_score = min(1.0, max(-1.0, score))
    return SimilarityScore(bounded_score)


def _ranking_key(
    item: tuple[SimilarityScore, RetrievalCandidate],
) -> tuple[float, str, str, str, int, str]:
    score, candidate = item
    generation = candidate.generation
    return (
        -score.value,
        str(generation.document_id),
        str(generation.document_version_id),
        str(generation.index_generation_id),
        candidate.document_order,
        str(candidate.chunk_id),
    )


def _require_reusable(
    existing: RetrievalRegistration,
    resolved: ResolvedRetrievalScope,
    configuration: RetrievalConfiguration,
) -> None:
    if (
        not isinstance(existing, RetrievalRegistration)
        or existing.qa_request_id != resolved.request.qa_request_id
        or existing.workspace_id != resolved.request.workspace_id
        or existing.scope.request.query != resolved.request.query
        or existing.scope.generations != resolved.generations
        or existing.configuration != configuration
    ):
        raise RetrievalIntegrityError("existing QA retrieval is incompatible")


def _same_retrieval_intent(
    existing: RetrievalRegistration,
    prepared: RetrievalRegistration,
) -> bool:
    return (
        existing.qa_request_id == prepared.qa_request_id
        and existing.workspace_id == prepared.workspace_id
        and existing.scope.request.query == prepared.scope.request.query
        and existing.scope.generations == prepared.scope.generations
        and existing.configuration == prepared.configuration
        and existing.candidate_count == prepared.candidate_count
        and existing.retrieval_policy_version == prepared.retrieval_policy_version
        and tuple(_evidence_intent(item) for item in existing.evidence)
        == tuple(_evidence_intent(item) for item in prepared.evidence)
    )


def _evidence_intent(
    item: RetrievalEvidenceRegistration,
) -> tuple[object, ...]:
    evidence = item.evidence
    return (
        evidence.workspace_id,
        evidence.document_id,
        evidence.document_version_id,
        evidence.page_number,
        evidence.rank,
        evidence.similarity_score,
        evidence.chunk_id,
        evidence.source_locator_id,
        evidence.availability,
        item.index_generation_id,
        item.document_order,
        item.source_locator,
        item.document_display_name,
        item.version_number,
        item.excerpt,
    )
