"""Tests for Application-owned QA retrieval contracts."""

import ast
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.application.ports.embeddings import (
    ChunkEmbedding,
    EmbeddingCompatibility,
    InvalidEmbeddingVector,
    NormalizedEmbeddingVector,
)
from lexlocal.application.ports.indexing import PersistedIndexGeneration
from lexlocal.application.ports.retrieval import (
    DEFAULT_RETRIEVAL_MIN_SIMILARITY,
    DEFAULT_RETRIEVAL_TOP_K,
    MAX_RETRIEVAL_TOP_K,
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
    RetrievalEvidenceRegistration,
    RetrievalIntegrityError,
    RetrievalPersistenceError,
    RetrievalRanking,
    RetrievalRegistration,
    RetrievalRepository,
    RetrievalResult,
)
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
from lexlocal.domain.processing import IndexGeneration, IndexGenerationState
from lexlocal.domain.retrieval import (
    Evidence,
    EvidenceRank,
    PageNumber,
    SimilarityScore,
    SourceLocator,
    SourceLocatorKind,
)

NOW = datetime(2026, 9, 7, 8, 30, tzinfo=UTC)
WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
OTHER_WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000002")
QA_REQUEST_ID = QaRequestId("20000000-0000-4000-8000-000000000001")
RETRIEVAL_RUN_ID = RetrievalRunId("30000000-0000-4000-8000-000000000001")
MODEL_ID = LocalModelId("40000000-0000-4000-8000-000000000001")


def _resolved(
    number: int = 1,
    *,
    workspace_id: WorkspaceId = WORKSPACE_ID,
    model_id: LocalModelId = MODEL_ID,
    profile: str = "chunk-v1",
) -> ResolvedRetrievalGeneration:
    generation = IndexGeneration(
        IndexGenerationId(f"50000000-0000-4000-8000-{number:012d}"),
        workspace_id,
        DocumentVersionId(f"60000000-0000-4000-8000-{number:012d}"),
        ProcessingJobId(f"70000000-0000-4000-8000-{number:012d}"),
        model_id,
        profile,
        "normalize-v1",
        2,
        IndexGenerationState.ACTIVE,
    )
    return ResolvedRetrievalGeneration(
        DocumentId(f"80000000-0000-4000-8000-{number:012d}"),
        VersionNumber(number),
        f"Synthetic document {number}",
        PersistedIndexGeneration(generation, NOW, activated_at=NOW),
    )


def _request(
    *,
    workspace_id: WorkspaceId = WORKSPACE_ID,
    document_ids: tuple[DocumentId, ...] | None = None,
) -> QaRetrievalRequest:
    return QaRetrievalRequest(
        QA_REQUEST_ID,
        workspace_id,
        " Exact synthetic query \n",
        document_ids,
    )


def _scope(*generations: ResolvedRetrievalGeneration) -> ResolvedRetrievalScope:
    return ResolvedRetrievalScope(_request(), generations or (_resolved(),))


def _candidate(
    generation: ResolvedRetrievalGeneration | None = None,
    *,
    number: int = 1,
    passage: str = "Exact synthetic passage",
) -> RetrievalCandidate:
    resolved = generation or _resolved()
    compatibility = EmbeddingCompatibility(
        resolved.workspace_id,
        resolved.index_generation_id,
        resolved.persisted.generation.embedding_model_id,
        resolved.persisted.generation.chunking_profile_version,
        resolved.persisted.generation.normalization_profile_version,
        resolved.persisted.generation.embedding_dimensions,
    )
    locator = SourceLocator(
        SourceLocatorId(f"90000000-0000-4000-8000-{number:012d}"),
        resolved.workspace_id,
        resolved.document_version_id,
        DocumentPageId(f"a0000000-0000-4000-8000-{number:012d}"),
        PageNumber(number),
        SourceLocatorKind.PAGE,
    )
    return RetrievalCandidate(
        resolved,
        ChunkEmbedding(
            ChunkId(f"b0000000-0000-4000-8000-{number:012d}"),
            compatibility,
            NormalizedEmbeddingVector((0.6, 0.8)),
            NOW,
        ),
        number - 1,
        locator,
        passage,
    )


class _RepositoryDouble:
    def get_for_qa_request(
        self,
        workspace_id: WorkspaceId,
        qa_request_id: QaRequestId,
    ) -> RetrievalRegistration | None:
        return None

    def resolve_scope(self, request: QaRetrievalRequest) -> ResolvedRetrievalScope:
        return _scope()

    def load_candidates(self, scope: ResolvedRetrievalScope) -> RetrievalCandidateSet:
        return RetrievalCandidateSet(scope, (_candidate(),))

    def add(self, registration: RetrievalRegistration) -> None:
        self.registration = registration


_REPOSITORY_CONFORMANCE: RetrievalRepository = _RepositoryDouble()


def test_configuration_uses_frozen_defaults_and_accepts_bounds() -> None:
    default = RetrievalConfiguration()

    assert default.top_k == DEFAULT_RETRIEVAL_TOP_K == 5
    assert default.min_similarity == DEFAULT_RETRIEVAL_MIN_SIMILARITY
    assert RetrievalConfiguration(1, SimilarityScore(-1.0)).top_k == 1
    assert RetrievalConfiguration(
        MAX_RETRIEVAL_TOP_K,
        SimilarityScore(1.0),
    ).top_k == 20


@pytest.mark.parametrize("top_k", [True, 0, 21, 1.0])
def test_configuration_rejects_invalid_top_k_without_coercion(top_k: object) -> None:
    with pytest.raises(InvalidRetrievalInput, match="configuration is invalid"):
        RetrievalConfiguration(top_k=top_k)  # type: ignore[arg-type]


def test_configuration_requires_the_existing_typed_similarity_boundary() -> None:
    with pytest.raises(InvalidRetrievalInput, match="configuration is invalid"):
        RetrievalConfiguration(min_similarity=0.0)  # type: ignore[arg-type]


def test_request_preserves_exact_query_hides_it_and_enforces_qa_owner_scope() -> None:
    document_id = _resolved().document_id
    request = _request(document_ids=(document_id,))

    assert request.qa_request_id == QA_REQUEST_ID
    assert request.query == " Exact synthetic query \n"
    assert request.document_ids == (document_id,)
    assert "Exact synthetic query" not in repr(request)

    with pytest.raises(InvalidRetrievalInput, match="document scope is invalid"):
        _request(document_ids=())
    with pytest.raises(InvalidRetrievalInput, match="document scope is invalid"):
        _request(document_ids=(document_id, document_id))


def test_scope_canonicalizes_representative_and_requires_one_exact_cohort() -> None:
    first = _resolved(1)
    second = _resolved(2)
    scope = _scope(second, first)

    assert scope.generations == (first, second)
    assert scope.representative == first
    assert scope.generation_ids == (first.index_generation_id, second.index_generation_id)
    assert scope.query_compatibility.index_generation_id == first.index_generation_id

    with pytest.raises(IncompatibleRetrievalScope, match="generations are incompatible"):
        _scope(first, _resolved(2, profile="other-profile"))


def test_scope_rejects_missing_cross_workspace_and_non_narrowing_results() -> None:
    with pytest.raises(NoEligibleIndex, match="no eligible index"):
        ResolvedRetrievalScope(_request(), ())
    with pytest.raises(RetrievalIntegrityError, match="ownership is inconsistent"):
        ResolvedRetrievalScope(_request(), (_resolved(workspace_id=OTHER_WORKSPACE_ID),))
    with pytest.raises(RetrievalIntegrityError, match="document scope is inconsistent"):
        ResolvedRetrievalScope(
            _request(document_ids=(_resolved(2).document_id,)),
            (_resolved(1),),
        )


def test_candidate_set_requires_exact_complete_generation_and_provenance_graph() -> None:
    first = _resolved(1)
    second = _resolved(2)
    scope = _scope(first, second)

    complete = RetrievalCandidateSet(
        scope,
        (_candidate(second, number=2), _candidate(first, number=1)),
    )
    assert len(complete.candidates) == 2

    with pytest.raises(RetrievalIntegrityError, match="set is inconsistent"):
        RetrievalCandidateSet(scope, (_candidate(first),))


def test_candidate_rejects_embedding_or_locator_ownership_substitution() -> None:
    first = _resolved(1)
    second = _resolved(2)
    valid = _candidate(first)

    with pytest.raises(RetrievalIntegrityError, match="relationships are invalid"):
        RetrievalCandidate(
            first,
            _candidate(second, number=2).embedding,
            valid.document_order,
            valid.source_locator,
            valid.passage,
        )


def test_candidate_vector_boundary_rejects_nonfinite_values() -> None:
    with pytest.raises(InvalidEmbeddingVector, match="vector is invalid"):
        NormalizedEmbeddingVector((float("nan"), 1.0))


def test_candidate_rejects_dimension_metadata_mismatch() -> None:
    resolved = _resolved()
    valid = _candidate(resolved)
    incompatible = ChunkEmbedding(
        valid.chunk_id,
        EmbeddingCompatibility(
            resolved.workspace_id,
            resolved.index_generation_id,
            MODEL_ID,
            "chunk-v1",
            "normalize-v1",
            3,
        ),
        NormalizedEmbeddingVector((1.0, 0.0, 0.0)),
        NOW,
    )

    with pytest.raises(RetrievalIntegrityError, match="relationships are invalid"):
        RetrievalCandidate(
            resolved,
            incompatible,
            valid.document_order,
            valid.source_locator,
            valid.passage,
        )


def test_registration_is_immutable_exact_and_privacy_safe() -> None:
    resolved = _resolved()
    scope = _scope(resolved)
    candidate = _candidate(resolved, passage="Private synthetic excerpt Ω")
    evidence = Evidence(
        EvidenceItemId("c0000000-0000-4000-8000-000000000001"),
        WORKSPACE_ID,
        RETRIEVAL_RUN_ID,
        resolved.document_id,
        resolved.document_version_id,
        candidate.source_locator.page_number,
        EvidenceRank(1),
        SimilarityScore(1.0),
        candidate.chunk_id,
        candidate.source_locator.id,
    )
    snapshot = RetrievalEvidenceRegistration(
        evidence,
        resolved.index_generation_id,
        candidate.document_order,
        candidate.source_locator,
        resolved.document_display_name,
        resolved.version_number,
        candidate.passage,
        NOW,
    )
    registration = RetrievalRegistration(
        RETRIEVAL_RUN_ID,
        scope,
        RetrievalConfiguration(),
        1,
        (snapshot,),
        NOW,
    )
    result = RetrievalResult(registration, reused=False)

    assert registration.qa_request_id == QA_REQUEST_ID
    assert registration.workspace_id == WORKSPACE_ID
    assert registration.embedding_model_id == MODEL_ID
    assert snapshot.excerpt == candidate.passage
    assert result.reused is False
    assert "Private synthetic excerpt" not in repr(snapshot)
    assert resolved.document_display_name not in repr(snapshot)
    assert "Exact synthetic query" not in repr(registration)
    with pytest.raises(FrozenInstanceError):
        registration.candidate_count = 2  # type: ignore[misc]


def test_ranking_value_supports_successful_empty_threshold_result() -> None:
    scope = _scope()
    ranking = RetrievalRanking(
        scope,
        RetrievalConfiguration(min_similarity=SimilarityScore(1.0)),
        1,
        (),
    )

    assert ranking.candidate_count == 1
    assert ranking.evidence == ()


def test_protocol_and_error_surface_remain_application_owned_and_minimal() -> None:
    assert _REPOSITORY_CONFORMANCE is not None
    assert {
        name
        for name, value in vars(RetrievalRepository).items()
        if callable(value) and not name.startswith("_")
    } == {"get_for_qa_request", "resolve_scope", "load_candidates", "add"}
    assert all(
        issubclass(error_type, RetrievalError)
        for error_type in (
            InvalidRetrievalInput,
            NoEligibleIndex,
            IncompatibleRetrievalScope,
            RetrievalIntegrityError,
            RetrievalPersistenceError,
        )
    )


def test_application_contract_has_no_concrete_or_persistence_imports() -> None:
    contract_path = (
        Path(__file__).resolve().parents[4]
        / "src"
        / "lexlocal"
        / "application"
        / "ports"
        / "retrieval.py"
    )
    tree = ast.parse(contract_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(
        module.startswith(
            (
                "sqlite3",
                "PySide6",
                "foundry_local",
                "lexlocal.infrastructure",
                "lexlocal.bootstrap",
                "lexlocal.presentation",
            )
        )
        for module in imported_modules
    )
