"""Tests for Application-owned evidence-sufficiency contracts."""

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.application.ports.evidence_sufficiency import (
    AggregateEvidenceCoverage,
    EvidenceAssessment,
    EvidencePolicyIdentity,
    EvidenceRelation,
    EvidenceRelationCounts,
    EvidenceSufficiencyCancellationCheck,
    EvidenceSufficiencyCancelled,
    EvidenceSufficiencyError,
    EvidenceSufficiencyResult,
    EvidenceVerifier,
    EvidenceVerifierError,
    EvidenceVerifierRequest,
    EvidenceVerifierResult,
    InvalidEvidenceSufficiencyInput,
    VerifierEvidence,
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

NOW = datetime(2026, 9, 10, 8, 30, tzinfo=UTC)
WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
QA_REQUEST_ID = QaRequestId("20000000-0000-4000-8000-000000000001")
RETRIEVAL_RUN_ID = RetrievalRunId("30000000-0000-4000-8000-000000000001")
MODEL_ID = LocalModelId("40000000-0000-4000-8000-000000000001")


def _status(
    *,
    readiness: ModelReadiness = ModelReadiness.READY,
    capability: ModelCapability = ModelCapability.CHAT,
) -> LocalModelStatus:
    return LocalModelStatus(
        ResolvedModelRecord(
            MODEL_ID,
            "synthetic-chat",
            "synthetic-chat:1",
            "1",
            capability,
            "local",
            2 if capability is ModelCapability.EMBEDDING else None,
        ),
        readiness,
        "SyntheticExecutionProvider",
    )


def _registration(*, evidence_count: int = 2) -> RetrievalRegistration:
    generation = IndexGeneration(
        IndexGenerationId("50000000-0000-4000-8000-000000000001"),
        WORKSPACE_ID,
        DocumentVersionId("60000000-0000-4000-8000-000000000001"),
        ProcessingJobId("70000000-0000-4000-8000-000000000001"),
        MODEL_ID,
        "chunk-v1",
        "normalize-v1",
        2,
        IndexGenerationState.ACTIVE,
    )
    resolved = ResolvedRetrievalGeneration(
        DocumentId("80000000-0000-4000-8000-000000000001"),
        VersionNumber(1),
        "Synthetic document",
        PersistedIndexGeneration(generation, NOW, activated_at=NOW),
        ProcessingJobState.READY,
    )
    scope = ResolvedRetrievalScope(
        QaRetrievalRequest(
            QA_REQUEST_ID,
            WORKSPACE_ID,
            "Private synthetic question Ω?",
        ),
        (resolved,),
    )
    evidence = tuple(_evidence(resolved, number) for number in range(1, evidence_count + 1))
    return RetrievalRegistration(
        RETRIEVAL_RUN_ID,
        scope,
        RetrievalConfiguration(),
        2,
        evidence,
        NOW,
    )


def _evidence(
    generation: ResolvedRetrievalGeneration,
    number: int,
) -> RetrievalEvidenceRegistration:
    locator = SourceLocator(
        SourceLocatorId(f"90000000-0000-4000-8000-{number:012d}"),
        WORKSPACE_ID,
        generation.document_version_id,
        DocumentPageId(f"a0000000-0000-4000-8000-{number:012d}"),
        PageNumber(number),
        SourceLocatorKind.PAGE,
    )
    evidence = Evidence(
        EvidenceItemId(f"b0000000-0000-4000-8000-{number:012d}"),
        WORKSPACE_ID,
        RETRIEVAL_RUN_ID,
        generation.document_id,
        generation.document_version_id,
        locator.page_number,
        EvidenceRank(number),
        SimilarityScore(1.0 - number / 10),
        ChunkId(f"c0000000-0000-4000-8000-{number:012d}"),
        locator.id,
    )
    return RetrievalEvidenceRegistration(
        evidence,
        generation.index_generation_id,
        number - 1,
        locator,
        generation.document_display_name,
        generation.version_number,
        f"Private synthetic excerpt {number} Ω",
        NOW,
    )


def _request(registration: RetrievalRegistration) -> EvidenceVerifierRequest:
    return EvidenceVerifierRequest(
        registration.scope.request.query,
        tuple(
            VerifierEvidence(item.evidence.id, item.evidence.rank, item.excerpt)
            for item in registration.evidence
        ),
    )


def _assessments(request: EvidenceVerifierRequest) -> tuple[EvidenceAssessment, ...]:
    relations = (EvidenceRelation.SUPPORTS, EvidenceRelation.RELATED_ONLY)
    return tuple(
        EvidenceAssessment(item.evidence_item_id, item.rank, relations[index])
        for index, item in enumerate(request.evidence)
    )


class _VerifierDouble:
    def __init__(self, status: LocalModelStatus) -> None:
        self._status = status

    @property
    def status(self) -> LocalModelStatus:
        return self._status

    def verify(self, request: EvidenceVerifierRequest) -> EvidenceVerifierResult:
        return EvidenceVerifierResult(
            request,
            self.status,
            "relation-contract-v1",
            _assessments(request),
            False,
        )


class _CancellationDouble:
    def raise_if_cancelled(self) -> None:
        return None


_VERIFIER_CONFORMANCE: EvidenceVerifier = _VerifierDouble(_status())
_CANCELLATION_CONFORMANCE: EvidenceSufficiencyCancellationCheck = _CancellationDouble()


def test_exact_relation_and_coverage_vocabularies() -> None:
    assert {item.value for item in EvidenceRelation} == {
        "SUPPORTS",
        "RELATED_ONLY",
        "CONTRADICTS",
        "IRRELEVANT",
    }
    assert {item.value for item in AggregateEvidenceCoverage} == {
        "READY",
        "READY_WITH_WARNINGS",
    }


def test_request_preserves_exact_private_question_and_ranked_excerpts() -> None:
    registration = _registration()
    request = _request(registration)

    assert request.question == registration.scope.request.query
    assert tuple(item.label for item in request.evidence) == ("E1", "E2")
    assert tuple(item.excerpt for item in request.evidence) == tuple(
        item.excerpt for item in registration.evidence
    )
    rendered = repr(request) + "".join(repr(item) for item in request.evidence)
    assert "Private synthetic" not in rendered
    assert all(str(item.evidence.id) not in rendered for item in registration.evidence)


def test_request_rejects_missing_reordered_or_duplicate_rank_coverage() -> None:
    registration = _registration()
    evidence = _request(registration).evidence

    with pytest.raises(InvalidEvidenceSufficiencyInput, match="request is invalid"):
        EvidenceVerifierRequest("question", ())
    with pytest.raises(InvalidEvidenceSufficiencyInput, match="request is invalid"):
        EvidenceVerifierRequest("question", tuple(reversed(evidence)))
    with pytest.raises(InvalidEvidenceSufficiencyInput, match="request is invalid"):
        EvidenceVerifierRequest("question", (evidence[0], evidence[0]))


def test_verifier_result_binds_complete_ordered_assessments_and_ready_model() -> None:
    request = _request(_registration())
    result = EvidenceVerifierResult(
        request,
        _status(),
        "relation-contract-v1",
        _assessments(request),
        True,
    )

    assert result.status.model.id == MODEL_ID
    assert result.verifier_contract_version == "relation-contract-v1"
    assert tuple(item.label for item in result.assessments) == ("E1", "E2")
    assert result.repair_used is True
    assert "SyntheticExecutionProvider" not in repr(result)


@pytest.mark.parametrize(
    "status",
    [
        _status(readiness=ModelReadiness.RESOLVED),
        _status(capability=ModelCapability.EMBEDDING),
    ],
)
def test_verifier_result_rejects_non_ready_or_non_chat_model(
    status: LocalModelStatus,
) -> None:
    request = _request(_registration())

    with pytest.raises(EvidenceVerifierError, match="result is invalid"):
        EvidenceVerifierResult(
            request,
            status,
            "relation-contract-v1",
            _assessments(request),
            False,
        )


def test_verifier_result_rejects_missing_duplicate_or_reordered_assessments() -> None:
    request = _request(_registration())
    assessments = _assessments(request)

    for invalid in (assessments[:1], (assessments[0], assessments[0]), assessments[::-1]):
        with pytest.raises(EvidenceVerifierError, match="result is invalid"):
            EvidenceVerifierResult(
                request,
                _status(),
                "relation-contract-v1",
                invalid,
                False,
            )


@pytest.mark.parametrize("version", ["", "  ", None, 1])
def test_policy_identity_rejects_invalid_versions(version: object) -> None:
    with pytest.raises(InvalidEvidenceSufficiencyInput, match="identity is invalid"):
        EvidencePolicyIdentity(
            version,  # type: ignore[arg-type]
            "relation-contract-v1",
            _status(),
        )


def test_policy_identity_is_immutable_and_hides_verifier_status() -> None:
    policy = EvidencePolicyIdentity(
        "evidence-policy-v1",
        "relation-contract-v1",
        _status(),
    )

    assert policy.verifier_status.model.id == MODEL_ID
    assert "SyntheticExecutionProvider" not in repr(policy)
    with pytest.raises(FrozenInstanceError):
        policy.evidence_policy_version = "changed"  # type: ignore[misc]


def test_final_result_reuses_exact_rag_identities_and_safe_aggregate_diagnostics() -> None:
    registration = _registration()
    request = _request(registration)
    assessments = _assessments(request)
    counts = EvidenceRelationCounts(1, 1, 0, 0)
    result = EvidenceSufficiencyResult(
        registration,
        EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
        EvidencePolicyIdentity(
            "evidence-policy-v1",
            "relation-contract-v1",
            _status(),
        ),
        assessments,
        registration.evidence,
        AggregateEvidenceCoverage.READY,
        counts,
        False,
    )

    assert result.retrieval is registration
    assert tuple(item.evidence_item_id for item in result.assessments) == tuple(
        item.evidence.id for item in registration.evidence
    )
    assert result.related_evidence == registration.evidence
    assert result.relation_counts.total == 2
    rendered = repr(result)
    assert "Private synthetic" not in rendered
    assert str(QA_REQUEST_ID) not in rendered
    assert str(RETRIEVAL_RUN_ID) not in rendered


def test_final_result_rejects_count_and_related_order_mismatch() -> None:
    registration = _registration()
    request = _request(registration)
    policy = EvidencePolicyIdentity(
        "evidence-policy-v1",
        "relation-contract-v1",
        _status(),
    )

    with pytest.raises(InvalidEvidenceSufficiencyInput, match="result is inconsistent"):
        EvidenceSufficiencyResult(
            registration,
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
            policy,
            _assessments(request),
            tuple(reversed(registration.evidence)),
            AggregateEvidenceCoverage.READY,
            EvidenceRelationCounts(1, 1, 0, 0),
            False,
        )
    with pytest.raises(InvalidEvidenceSufficiencyInput, match="result is inconsistent"):
        EvidenceSufficiencyResult(
            registration,
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
            policy,
            _assessments(request),
            registration.evidence,
            AggregateEvidenceCoverage.READY,
            EvidenceRelationCounts(0, 2, 0, 0),
            False,
        )
    with pytest.raises(InvalidEvidenceSufficiencyInput, match="result is inconsistent"):
        EvidenceSufficiencyResult(
            registration,
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
            policy,
            _assessments(request),
            registration.evidence,
            AggregateEvidenceCoverage.READY,
            EvidenceRelationCounts(1, 0, 0, 0),
            False,
        )
    substituted = (
        EvidenceAssessment(
            EvidenceItemId("b0000000-0000-4000-8000-000000000099"),
            EvidenceRank(1),
            EvidenceRelation.SUPPORTS,
        ),
        _assessments(request)[1],
    )
    with pytest.raises(InvalidEvidenceSufficiencyInput, match="result is inconsistent"):
        EvidenceSufficiencyResult(
            registration,
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
            policy,
            substituted,
            registration.evidence,
            AggregateEvidenceCoverage.READY,
            EvidenceRelationCounts(1, 1, 0, 0),
            False,
        )


def test_final_result_rejects_evidence_from_another_retrieval_safely() -> None:
    registration = _registration()
    other = replace(
        _registration(evidence_count=1).evidence[0],
        excerpt="Different private synthetic excerpt",
    )
    request = _request(registration)

    with pytest.raises(InvalidEvidenceSufficiencyInput, match="result is inconsistent") as error:
        EvidenceSufficiencyResult(
            registration,
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
            EvidencePolicyIdentity(
                "evidence-policy-v1",
                "relation-contract-v1",
                _status(),
            ),
            _assessments(request),
            (other,),
            AggregateEvidenceCoverage.READY,
            EvidenceRelationCounts(1, 1, 0, 0),
            False,
        )

    assert error.value.__cause__ is None


def test_zero_evidence_result_is_an_immutable_insufficient_policy_result() -> None:
    registration = _registration(evidence_count=0)
    result = EvidenceSufficiencyResult(
        registration,
        EvidenceSufficiency.INSUFFICIENT,
        EvidencePolicyIdentity(
            "evidence-policy-v1",
            "relation-contract-v1",
            _status(),
        ),
        (),
        (),
        AggregateEvidenceCoverage.READY,
        EvidenceRelationCounts(0, 0, 0, 0),
        False,
    )

    assert result.assessments == ()
    assert result.related_evidence == ()
    with pytest.raises(FrozenInstanceError):
        result.repair_used = True  # type: ignore[misc]


@pytest.mark.parametrize(
    "state,repair_used",
    [
        (EvidenceSufficiency.SUFFICIENT, False),
        (EvidenceSufficiency.INSUFFICIENT, True),
    ],
)
def test_zero_evidence_rejects_noncanonical_state_or_repair(
    state: EvidenceSufficiency,
    repair_used: bool,
) -> None:
    registration = _registration(evidence_count=0)

    with pytest.raises(InvalidEvidenceSufficiencyInput, match="result is inconsistent"):
        EvidenceSufficiencyResult(
            registration,
            state,
            EvidencePolicyIdentity(
                "evidence-policy-v1",
                "relation-contract-v1",
                _status(),
            ),
            (),
            (),
            AggregateEvidenceCoverage.READY,
            EvidenceRelationCounts(0, 0, 0, 0),
            repair_used,
        )


def test_errors_and_protocols_remain_minimal_and_sanitized() -> None:
    assert all(
        issubclass(error_type, EvidenceSufficiencyError)
        for error_type in (
            InvalidEvidenceSufficiencyInput,
            EvidenceVerifierError,
            EvidenceSufficiencyCancelled,
        )
    )
    assert _VERIFIER_CONFORMANCE.status == _status()
    _CANCELLATION_CONFORMANCE.raise_if_cancelled()
    assert {
        name
        for name, value in vars(EvidenceVerifier).items()
        if callable(value) and not name.startswith("_")
    } == {"verify"}
    assert {
        name
        for name, value in vars(EvidenceSufficiencyCancellationCheck).items()
        if callable(value) and not name.startswith("_")
    } == {"raise_if_cancelled"}

    private_value = "private-synthetic-question"
    with pytest.raises(InvalidEvidenceSufficiencyInput) as captured:
        EvidenceVerifierRequest(private_value, ())
    assert private_value not in str(captured.value)
    assert captured.value.__cause__ is None


def test_application_contract_has_no_sdk_persistence_or_concrete_imports() -> None:
    contract_path = (
        Path(__file__).resolve().parents[4]
        / "src"
        / "lexlocal"
        / "application"
        / "ports"
        / "evidence_sufficiency.py"
    )
    tree = ast.parse(contract_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert all(
        not module.startswith(
            (
                "foundry_local_sdk",
                "openai",
                "sqlite3",
                "lexlocal.infrastructure",
                "lexlocal.bootstrap",
                "lexlocal.presentation",
            )
        )
        for module in imported_modules
    )
