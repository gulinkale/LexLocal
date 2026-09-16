"""Tests for deterministic Application evidence-sufficiency evaluation."""

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.application.evidence_sufficiency import EvaluateEvidenceSufficiency
from lexlocal.application.ports.evidence_sufficiency import (
    AggregateEvidenceCoverage,
    EvidenceAssessment,
    EvidencePolicyIdentity,
    EvidenceRelation,
    EvidenceSufficiencyCancelled,
    EvidenceVerifierError,
    EvidenceVerifierRequest,
    EvidenceVerifierResult,
    InvalidEvidenceSufficiencyInput,
)
from lexlocal.application.ports.indexing import PersistedIndexGeneration
from lexlocal.application.ports.local_models import (
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
    ResolvedModelRecord,
)
from lexlocal.application.ports.retrieval import (
    QaRetrievalRequest,
    ResolvedRetrievalGeneration,
    ResolvedRetrievalScope,
    RetrievalConfiguration,
    RetrievalEvidenceRegistration,
    RetrievalRegistration,
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
from lexlocal.domain.processing import (
    IndexGeneration,
    IndexGenerationState,
    ProcessingJobState,
)
from lexlocal.domain.retrieval import (
    Evidence,
    EvidenceRank,
    EvidenceSufficiency,
    PageNumber,
    SimilarityScore,
    SourceLocator,
    SourceLocatorKind,
)

NOW = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)
WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
QA_REQUEST_ID = QaRequestId("20000000-0000-4000-8000-000000000001")
RETRIEVAL_RUN_ID = RetrievalRunId("30000000-0000-4000-8000-000000000001")
MODEL_ID = LocalModelId("40000000-0000-4000-8000-000000000001")
OTHER_MODEL_ID = LocalModelId("40000000-0000-4000-8000-000000000002")
POLICY_VERSION = "evidence-policy-v1"
CONTRACT_VERSION = "evidence-relations-v1"
QUESTION = "Which state does the anonymous synthetic marker have?"


def _status(model_id: LocalModelId = MODEL_ID) -> LocalModelStatus:
    return LocalModelStatus(
        ResolvedModelRecord(
            model_id,
            "synthetic-chat",
            "synthetic-chat:1",
            "1",
            ModelCapability.CHAT,
            "local",
        ),
        ModelReadiness.READY,
        "SyntheticExecutionProvider",
    )


def _generation(
    number: int,
    coverage: ProcessingJobState,
) -> ResolvedRetrievalGeneration:
    generation = IndexGeneration(
        IndexGenerationId(f"50000000-0000-4000-8000-{number:012d}"),
        WORKSPACE_ID,
        DocumentVersionId(f"60000000-0000-4000-8000-{number:012d}"),
        ProcessingJobId(f"70000000-0000-4000-8000-{number:012d}"),
        LocalModelId("80000000-0000-4000-8000-000000000001"),
        "chunk-v1",
        "normalize-v1",
        2,
        IndexGenerationState.ACTIVE,
    )
    return ResolvedRetrievalGeneration(
        DocumentId(f"90000000-0000-4000-8000-{number:012d}"),
        VersionNumber(number),
        f"Anonymous synthetic document {number}",
        PersistedIndexGeneration(generation, NOW, activated_at=NOW),
        coverage,
    )


def _evidence(
    generation: ResolvedRetrievalGeneration,
    number: int,
    score: float,
) -> RetrievalEvidenceRegistration:
    locator = SourceLocator(
        SourceLocatorId(f"a0000000-0000-4000-8000-{number:012d}"),
        WORKSPACE_ID,
        generation.document_version_id,
        DocumentPageId(f"b0000000-0000-4000-8000-{number:012d}"),
        PageNumber(number),
        SourceLocatorKind.PAGE,
    )
    evidence = Evidence(
        EvidenceItemId(f"c0000000-0000-4000-8000-{number:012d}"),
        WORKSPACE_ID,
        RETRIEVAL_RUN_ID,
        generation.document_id,
        generation.document_version_id,
        locator.page_number,
        EvidenceRank(number),
        SimilarityScore(score),
        ChunkId(f"d0000000-0000-4000-8000-{number:012d}"),
        locator.id,
    )
    return RetrievalEvidenceRegistration(
        evidence,
        generation.index_generation_id,
        number - 1,
        locator,
        generation.document_display_name,
        generation.version_number,
        f"Private anonymous synthetic passage {number} Ω",
        NOW,
    )


def _registration(
    evidence_count: int,
    *,
    coverage: tuple[ProcessingJobState, ...] = (ProcessingJobState.READY,),
    scores: tuple[float, ...] | None = None,
    candidate_count: int | None = None,
    configuration: RetrievalConfiguration | None = None,
) -> RetrievalRegistration:
    generations = tuple(
        _generation(index, state) for index, state in enumerate(coverage, start=1)
    )
    scope = ResolvedRetrievalScope(
        QaRetrievalRequest(QA_REQUEST_ID, WORKSPACE_ID, QUESTION),
        generations,
    )
    resolved_scores = (
        tuple(1.0 - index / 100 for index in range(evidence_count))
        if scores is None
        else scores
    )
    assert len(resolved_scores) == evidence_count
    evidence = tuple(
        _evidence(
            generations[(number - 1) % len(generations)],
            number,
            resolved_scores[number - 1],
        )
        for number in range(1, evidence_count + 1)
    )
    return RetrievalRegistration(
        RETRIEVAL_RUN_ID,
        scope,
        RetrievalConfiguration() if configuration is None else configuration,
        max(1, evidence_count) if candidate_count is None else candidate_count,
        evidence,
        NOW,
    )


class _Verifier:
    def __init__(
        self,
        relations: tuple[EvidenceRelation, ...],
        *,
        status: LocalModelStatus | None = None,
        contract_version: str = CONTRACT_VERSION,
        failure: Exception | None = None,
        question_override: str | None = None,
        status_after_verify: LocalModelStatus | None = None,
        repair_used: bool = False,
    ) -> None:
        self._status = _status() if status is None else status
        self.relations = relations
        self.contract_version = contract_version
        self.failure = failure
        self.question_override = question_override
        self.status_after_verify = status_after_verify
        self.repair_used = repair_used
        self.requests: list[EvidenceVerifierRequest] = []

    @property
    def status(self) -> LocalModelStatus:
        return self._status

    def verify(self, request: EvidenceVerifierRequest) -> EvidenceVerifierResult:
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        bound_request = (
            request
            if self.question_override is None
            else EvidenceVerifierRequest(self.question_override, request.evidence)
        )
        result = EvidenceVerifierResult(
            bound_request,
            self._status,
            self.contract_version,
            tuple(
                EvidenceAssessment(item.evidence_item_id, item.rank, relation)
                for item, relation in zip(
                    bound_request.evidence,
                    self.relations,
                    strict=True,
                )
            ),
            self.repair_used,
        )
        if self.status_after_verify is not None:
            self._status = self.status_after_verify
        return result


class _Cancellation:
    def __init__(
        self,
        *,
        cancel_at: int | None = None,
        fail_at: int | None = None,
    ) -> None:
        self.cancel_at = cancel_at
        self.fail_at = fail_at
        self.checks = 0

    def raise_if_cancelled(self) -> None:
        self.checks += 1
        if self.checks == self.cancel_at:
            raise EvidenceSufficiencyCancelled("private cancellation detail")
        if self.checks == self.fail_at:
            raise RuntimeError("private cancellation checker detail")


def _evaluate(
    verifier: _Verifier,
    cancellation: _Cancellation | None = None,
    *,
    policy_status: LocalModelStatus | None = None,
    policy_contract: str = CONTRACT_VERSION,
) -> EvaluateEvidenceSufficiency:
    return EvaluateEvidenceSufficiency(
        verifier,
        EvidencePolicyIdentity(
            POLICY_VERSION,
            policy_contract,
            _status() if policy_status is None else policy_status,
        ),
        _Cancellation() if cancellation is None else cancellation,
    )


@pytest.mark.parametrize(
    ("coverage", "relations", "expected_state", "related_ranks"),
    [
        pytest.param(
            (ProcessingJobState.READY,),
            (EvidenceRelation.SUPPORTS,),
            EvidenceSufficiency.SUFFICIENT,
            (),
            id="ready-supports",
        ),
        pytest.param(
            (ProcessingJobState.READY,),
            (EvidenceRelation.SUPPORTS, EvidenceRelation.RELATED_ONLY),
            EvidenceSufficiency.SUFFICIENT,
            (),
            id="ready-support-plus-related",
        ),
        pytest.param(
            (ProcessingJobState.READY,),
            (EvidenceRelation.SUPPORTS, EvidenceRelation.CONTRADICTS),
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
            (1, 2),
            id="contradiction-veto",
        ),
        pytest.param(
            (ProcessingJobState.READY, ProcessingJobState.READY_WITH_WARNINGS),
            (EvidenceRelation.SUPPORTS,),
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
            (1,),
            id="warning-veto",
        ),
        pytest.param(
            (ProcessingJobState.READY,),
            (EvidenceRelation.RELATED_ONLY,),
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
            (1,),
            id="related-only",
        ),
        pytest.param(
            (ProcessingJobState.READY,),
            (EvidenceRelation.CONTRADICTS,),
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
            (1,),
            id="contradiction-only",
        ),
        pytest.param(
            (ProcessingJobState.READY,),
            (EvidenceRelation.IRRELEVANT,),
            EvidenceSufficiency.INSUFFICIENT,
            (),
            id="all-irrelevant",
        ),
        pytest.param(
            (ProcessingJobState.READY_WITH_WARNINGS,),
            (EvidenceRelation.IRRELEVANT,),
            EvidenceSufficiency.INSUFFICIENT,
            (),
            id="warning-does-not-invent-related-evidence",
        ),
    ],
)
def test_frozen_aggregation_truth_table(
    coverage: tuple[ProcessingJobState, ...],
    relations: tuple[EvidenceRelation, ...],
    expected_state: EvidenceSufficiency,
    related_ranks: tuple[int, ...],
) -> None:
    registration = _registration(len(relations), coverage=coverage)
    verifier = _Verifier(relations)

    result = _evaluate(verifier)(registration)

    assert result.state is expected_state
    assert result.aggregate_coverage is (
        AggregateEvidenceCoverage.READY_WITH_WARNINGS
        if ProcessingJobState.READY_WITH_WARNINGS in coverage
        else AggregateEvidenceCoverage.READY
    )
    assert tuple(item.evidence.rank.value for item in result.related_evidence) == (
        related_ranks
    )
    assert len(verifier.requests) == 1


def test_zero_evidence_is_insufficient_without_verifier_call() -> None:
    registration = _registration(0, coverage=(ProcessingJobState.READY_WITH_WARNINGS,))
    verifier = _Verifier((), failure=AssertionError("verifier must not be called"))

    result = _evaluate(verifier)(registration)

    assert result.state is EvidenceSufficiency.INSUFFICIENT
    assert result.assessments == ()
    assert result.related_evidence == ()
    assert result.aggregate_coverage is AggregateEvidenceCoverage.READY_WITH_WARNINGS
    assert result.relation_counts.total == 0
    assert result.repair_used is False
    assert verifier.requests == []


def test_verifier_receives_exact_question_rank_id_and_excerpt_once() -> None:
    registration = _registration(2)
    verifier = _Verifier(
        (EvidenceRelation.SUPPORTS, EvidenceRelation.RELATED_ONLY),
        repair_used=True,
    )

    result = _evaluate(verifier)(registration)

    assert len(verifier.requests) == 1
    request = verifier.requests[0]
    assert request.question == registration.scope.request.query
    assert tuple(item.evidence_item_id for item in request.evidence) == tuple(
        item.evidence.id for item in registration.evidence
    )
    assert tuple(item.rank for item in request.evidence) == tuple(
        item.evidence.rank for item in registration.evidence
    )
    assert tuple(item.excerpt for item in request.evidence) == tuple(
        item.excerpt for item in registration.evidence
    )
    assert result.retrieval is registration
    assert tuple(item.evidence_item_id for item in result.assessments) == tuple(
        item.evidence.id for item in registration.evidence
    )
    assert result.repair_used is True


def test_related_projection_preserves_rag_order_without_renumbering() -> None:
    registration = _registration(4)
    relations = (
        EvidenceRelation.IRRELEVANT,
        EvidenceRelation.SUPPORTS,
        EvidenceRelation.RELATED_ONLY,
        EvidenceRelation.CONTRADICTS,
    )

    result = _evaluate(_Verifier(relations))(registration)

    assert result.state is EvidenceSufficiency.RELATED_BUT_INSUFFICIENT
    assert result.related_evidence == registration.evidence[1:]
    assert tuple(item.evidence.rank.value for item in result.related_evidence) == (
        2,
        3,
        4,
    )
    assert result.relation_counts.supports == 1
    assert result.relation_counts.related_only == 1
    assert result.relation_counts.contradicts == 1
    assert result.relation_counts.irrelevant == 1


@pytest.mark.parametrize(
    ("score", "candidate_count", "configuration"),
    [
        (0.1, 1, RetrievalConfiguration(1, SimilarityScore(-1.0))),
        (1.0, 999, RetrievalConfiguration(20, SimilarityScore(1.0))),
    ],
)
def test_numeric_retrieval_signals_cannot_override_semantic_relations(
    score: float,
    candidate_count: int,
    configuration: RetrievalConfiguration,
) -> None:
    registration = _registration(
        1,
        scores=(score,),
        candidate_count=candidate_count,
        configuration=configuration,
    )

    result = _evaluate(_Verifier((EvidenceRelation.SUPPORTS,)))(registration)

    assert result.state is EvidenceSufficiency.SUFFICIENT


@pytest.mark.parametrize(
    "relations",
    [
        (EvidenceRelation.SUPPORTS,),
        (EvidenceRelation.RELATED_ONLY,),
        (EvidenceRelation.CONTRADICTS,),
        (EvidenceRelation.IRRELEVANT,),
    ],
)
def test_relation_counts_are_exact_and_safe(
    relations: tuple[EvidenceRelation, ...],
) -> None:
    result = _evaluate(_Verifier(relations))(_registration(1))

    assert result.relation_counts.total == 1
    assert (
        result.relation_counts.supports,
        result.relation_counts.related_only,
        result.relation_counts.contradicts,
        result.relation_counts.irrelevant,
    ) == tuple(int(relations[0] is item) for item in EvidenceRelation)


def test_repeated_mapping_is_deterministic_with_one_operation_per_evaluation() -> None:
    registration = _registration(2)
    verifier = _Verifier(
        (EvidenceRelation.SUPPORTS, EvidenceRelation.IRRELEVANT)
    )
    evaluate = _evaluate(verifier)

    first = evaluate(registration)
    second = evaluate(registration)

    assert first == second
    assert len(verifier.requests) == 2


def test_policy_model_contract_and_request_binding_fail_closed() -> None:
    with pytest.raises(
        InvalidEvidenceSufficiencyInput,
        match="policy binding is invalid",
    ):
        _evaluate(
            _Verifier((EvidenceRelation.SUPPORTS,), status=_status(OTHER_MODEL_ID))
        )

    registration = _registration(1)
    with pytest.raises(EvidenceVerifierError, match="result binding is invalid"):
        _evaluate(
            _Verifier(
                (EvidenceRelation.SUPPORTS,),
                contract_version="other-contract-v1",
            )
        )(registration)
    with pytest.raises(EvidenceVerifierError, match="result binding is invalid"):
        _evaluate(
            _Verifier(
                (EvidenceRelation.SUPPORTS,),
                question_override="Different private synthetic question",
            )
        )(registration)


def test_invalid_retrieval_is_rejected_before_verifier_work() -> None:
    verifier = _Verifier((EvidenceRelation.SUPPORTS,))

    with pytest.raises(
        InvalidEvidenceSufficiencyInput,
        match="retrieval is invalid",
    ):
        _evaluate(verifier)(object())  # type: ignore[arg-type]

    assert verifier.requests == []


@pytest.mark.parametrize(
    "relations",
    [
        (),
        (EvidenceRelation.SUPPORTS, EvidenceRelation.RELATED_ONLY),
    ],
)
def test_incomplete_or_overcomplete_verifier_coverage_fails_operationally(
    relations: tuple[EvidenceRelation, ...],
) -> None:
    verifier = _Verifier(relations)

    with pytest.raises(EvidenceVerifierError) as captured:
        _evaluate(verifier)(_registration(1))

    assert str(captured.value) == "evidence verification failed"
    assert captured.value.__cause__ is None
    assert len(verifier.requests) == 1


def test_model_substitution_after_verification_fails_closed() -> None:
    verifier = _Verifier(
        (EvidenceRelation.SUPPORTS,),
        status_after_verify=_status(OTHER_MODEL_ID),
    )

    with pytest.raises(
        InvalidEvidenceSufficiencyInput,
        match="policy binding is invalid",
    ):
        _evaluate(verifier)(_registration(1))

    assert len(verifier.requests) == 1


@pytest.mark.parametrize("failure_type", [RuntimeError, EvidenceVerifierError])
def test_verifier_failure_is_sanitized_and_never_becomes_a_state(
    failure_type: type[Exception],
) -> None:
    private_detail = "private question, excerpt, model path, and provider output"
    verifier = _Verifier(
        (EvidenceRelation.SUPPORTS,),
        failure=failure_type(private_detail),
    )

    with pytest.raises(EvidenceVerifierError) as captured:
        _evaluate(verifier)(_registration(1))

    assert str(captured.value) == "evidence verification failed"
    assert captured.value.__cause__ is None
    assert private_detail not in str(captured.value)
    assert len(verifier.requests) == 1


def test_verifier_cancellation_is_sanitized_and_not_downgraded() -> None:
    verifier = _Verifier(
        (EvidenceRelation.SUPPORTS,),
        failure=EvidenceSufficiencyCancelled("private cancellation detail"),
    )

    with pytest.raises(EvidenceSufficiencyCancelled) as captured:
        _evaluate(verifier)(_registration(1))

    assert str(captured.value) == "evidence sufficiency evaluation was cancelled"
    assert captured.value.__cause__ is None


@pytest.mark.parametrize(
    ("cancel_at", "expected_calls"),
    [(1, 0), (2, 0), (3, 1), (4, 1)],
)
def test_cancellation_at_each_boundary_prevents_a_final_result(
    cancel_at: int,
    expected_calls: int,
) -> None:
    verifier = _Verifier((EvidenceRelation.SUPPORTS,))
    cancellation = _Cancellation(cancel_at=cancel_at)

    with pytest.raises(EvidenceSufficiencyCancelled) as captured:
        _evaluate(verifier, cancellation)(_registration(1))

    assert captured.value.__cause__ is None
    assert len(verifier.requests) == expected_calls


def test_cancellation_checker_failure_is_sanitized() -> None:
    private_detail = "private cancellation checker detail"

    with pytest.raises(EvidenceVerifierError) as captured:
        _evaluate(_Verifier((EvidenceRelation.SUPPORTS,)), _Cancellation(fail_at=1))(
            _registration(1)
        )

    assert str(captured.value) == "evidence sufficiency cancellation check failed"
    assert captured.value.__cause__ is None
    assert private_detail not in str(captured.value)


def test_result_repr_hides_question_excerpts_ids_and_model_details() -> None:
    registration = _registration(2)
    result = _evaluate(
        _Verifier((EvidenceRelation.SUPPORTS, EvidenceRelation.RELATED_ONLY))
    )(registration)

    rendered = repr(result)
    assert QUESTION not in rendered
    assert all(item.excerpt not in rendered for item in registration.evidence)
    assert str(QA_REQUEST_ID) not in rendered
    assert str(RETRIEVAL_RUN_ID) not in rendered
    assert str(MODEL_ID) not in rendered
    assert "SyntheticExecutionProvider" not in rendered


def test_application_policy_has_no_numeric_persistence_or_concrete_dependencies() -> None:
    policy_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "lexlocal"
        / "application"
        / "evidence_sufficiency.py"
    )
    tree = ast.parse(policy_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }

    assert all(
        not module.startswith(
            (
                "sqlite3",
                "lexlocal.infrastructure",
                "lexlocal.bootstrap",
                "lexlocal.presentation",
            )
        )
        for module in imported_modules
    )
    assert imported_names.isdisjoint(
        {
            "RetrievalConfiguration",
            "SimilarityScore",
            "RetrievalRepository",
            "UnitOfWork",
        }
    )
