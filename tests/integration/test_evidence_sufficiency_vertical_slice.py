"""Synthetic RAG-to-evidence-sufficiency vertical-slice tests."""

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import pytest

from lexlocal.application.ports.evidence_sufficiency import (
    AggregateEvidenceCoverage,
    EvidenceRelation,
    EvidenceSufficiencyCancelled,
    EvidenceVerifierError,
    InvalidEvidenceSufficiencyInput,
)
from lexlocal.application.ports.indexing import PersistedIndexGeneration
from lexlocal.application.ports.local_models import (
    ChatInferenceProfile,
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
from lexlocal.bootstrap.evidence_sufficiency import (
    EVIDENCE_POLICY_VERSION,
    EVIDENCE_VERIFIER_CONTRACT_VERSION,
    EVIDENCE_VERIFIER_INVOCATION_PROFILE,
    compose_evidence_sufficiency_application,
)
from lexlocal.bootstrap.foundry import LocalModelComposition
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

NOW = datetime(2026, 9, 11, 15, 0, tzinfo=UTC)
WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
QA_REQUEST_ID = QaRequestId("20000000-0000-4000-8000-000000000001")
RETRIEVAL_RUN_ID = RetrievalRunId("30000000-0000-4000-8000-000000000001")
CHAT_MODEL_ID = LocalModelId("40000000-0000-4000-8000-000000000001")
OTHER_MODEL_ID = LocalModelId("40000000-0000-4000-8000-000000000002")
QUESTION = "Which state does the anonymous synthetic marker have?"


def _status(
    *,
    model_id: LocalModelId = CHAT_MODEL_ID,
    readiness: ModelReadiness = ModelReadiness.READY,
    capability: ModelCapability = ModelCapability.CHAT,
) -> LocalModelStatus:
    return LocalModelStatus(
        ResolvedModelRecord(
            model_id,
            "synthetic-chat" if capability is ModelCapability.CHAT else "synthetic-embed",
            "synthetic:1",
            "1",
            capability,
            "local",
            None if capability is ModelCapability.CHAT else 2,
        ),
        readiness,
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
        SimilarityScore(1.0 - number / 100),
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
        f"Anonymous synthetic passage {number} Ω",
        NOW,
    )


def _registration(
    evidence_count: int,
    *,
    coverage: tuple[ProcessingJobState, ...] = (ProcessingJobState.READY,),
) -> RetrievalRegistration:
    generations = tuple(
        _generation(index, state) for index, state in enumerate(coverage, start=1)
    )
    evidence = tuple(
        _evidence(generations[(number - 1) % len(generations)], number)
        for number in range(1, evidence_count + 1)
    )
    return RetrievalRegistration(
        RETRIEVAL_RUN_ID,
        ResolvedRetrievalScope(
            QaRetrievalRequest(QA_REQUEST_ID, WORKSPACE_ID, QUESTION),
            generations,
        ),
        RetrievalConfiguration(),
        max(1, evidence_count),
        evidence,
        NOW,
    )


def _output(relations: tuple[EvidenceRelation, ...]) -> str:
    return json.dumps(
        {
            "assessments": [
                {"evidence": f"E{index}", "relation": relation.value}
                for index, relation in reversed(tuple(enumerate(relations, start=1)))
            ]
        }
    )


class _ChatProvider:
    def __init__(
        self,
        outputs: list[str | Exception],
        *,
        status: LocalModelStatus | None = None,
        after_generate: Callable[[], None] | None = None,
    ) -> None:
        self.outputs = outputs
        self._status = _status() if status is None else status
        self.after_generate = after_generate
        self.prompts: list[str] = []
        self.profiles: list[ChatInferenceProfile | None] = []

    @property
    def status(self) -> LocalModelStatus:
        return self._status

    def generate(
        self,
        prompt: str,
        *,
        profile: ChatInferenceProfile | None = None,
    ) -> str:
        self.prompts.append(prompt)
        self.profiles.append(profile)
        output = self.outputs.pop(0)
        if self.after_generate is not None:
            self.after_generate()
        if isinstance(output, Exception):
            raise output
        return output


class _EmbeddingProvider:
    @property
    def status(self) -> LocalModelStatus:
        return _status(
            model_id=LocalModelId("40000000-0000-4000-8000-000000000003"),
            capability=ModelCapability.EMBEDDING,
        )

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        raise AssertionError("query and chunk embedding must not run")


class _Cancellation:
    def __init__(self) -> None:
        self.cancelled = False

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise EvidenceSufficiencyCancelled("private cancellation detail")


def _local_models(
    provider: _ChatProvider,
    *,
    chat_status: LocalModelStatus | None = None,
) -> LocalModelComposition:
    return LocalModelComposition(
        provider,
        _EmbeddingProvider(),
        provider.status if chat_status is None else chat_status,
        _EmbeddingProvider().status,
        lambda: (_ for _ in ()).throw(AssertionError("runtime must not be closed")),
    )


@pytest.mark.parametrize(
    ("coverage", "relations", "expected_state", "related_ranks"),
    [
        pytest.param(
            (ProcessingJobState.READY,),
            (EvidenceRelation.SUPPORTS,),
            EvidenceSufficiency.SUFFICIENT,
            (),
            id="sufficient",
        ),
        pytest.param(
            (ProcessingJobState.READY,),
            (EvidenceRelation.RELATED_ONLY,),
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
            (1,),
            id="related-but-insufficient",
        ),
        pytest.param(
            (ProcessingJobState.READY,),
            (EvidenceRelation.IRRELEVANT,),
            EvidenceSufficiency.INSUFFICIENT,
            (),
            id="insufficient",
        ),
        pytest.param(
            (ProcessingJobState.READY_WITH_WARNINGS,),
            (EvidenceRelation.SUPPORTS,),
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
            (1,),
            id="warning-veto",
        ),
        pytest.param(
            (ProcessingJobState.READY,),
            (EvidenceRelation.CONTRADICTS, EvidenceRelation.CONTRADICTS),
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
            (1, 2),
            id="contradiction-veto",
        ),
    ],
)
def test_synthetic_rag_values_flow_to_all_frozen_states(
    coverage: tuple[ProcessingJobState, ...],
    relations: tuple[EvidenceRelation, ...],
    expected_state: EvidenceSufficiency,
    related_ranks: tuple[int, ...],
) -> None:
    provider = _ChatProvider([_output(relations)])
    composition = compose_evidence_sufficiency_application(_local_models(provider))
    registration = _registration(len(relations), coverage=coverage)

    result = composition.evaluate_evidence_sufficiency(registration)

    assert result.state is expected_state
    assert result.retrieval is registration
    assert result.policy is composition.policy
    assert result.policy.evidence_policy_version == EVIDENCE_POLICY_VERSION
    assert result.policy.verifier_contract_version == EVIDENCE_VERIFIER_CONTRACT_VERSION
    assert tuple(item.relation for item in result.assessments) == relations
    assert tuple(item.rank.value for item in result.assessments) == tuple(
        range(1, len(relations) + 1)
    )
    assert tuple(item.evidence.rank.value for item in result.related_evidence) == (
        related_ranks
    )
    assert result.aggregate_coverage is (
        AggregateEvidenceCoverage.READY_WITH_WARNINGS
        if ProcessingJobState.READY_WITH_WARNINGS in coverage
        else AggregateEvidenceCoverage.READY
    )
    assert len(provider.prompts) == 1
    assert provider.profiles == [EVIDENCE_VERIFIER_INVOCATION_PROFILE]


def test_zero_evidence_is_insufficient_without_model_work() -> None:
    provider = _ChatProvider([AssertionError("model must not run")])
    composition = compose_evidence_sufficiency_application(_local_models(provider))

    result = composition.evaluate_evidence_sufficiency(_registration(0))

    assert result.state is EvidenceSufficiency.INSUFFICIENT
    assert result.assessments == ()
    assert result.related_evidence == ()
    assert result.repair_used is False
    assert provider.prompts == []


def test_one_repair_stays_inside_the_shared_provider_verifier() -> None:
    provider = _ChatProvider(["not-json", _output((EvidenceRelation.SUPPORTS,))])
    composition = compose_evidence_sufficiency_application(_local_models(provider))

    result = composition.evaluate_evidence_sufficiency(_registration(1))

    assert result.state is EvidenceSufficiency.SUFFICIENT
    assert result.repair_used is True
    assert len(provider.prompts) == 2
    assert json.loads(provider.prompts[0])["attempt"] == "initial"
    assert json.loads(provider.prompts[1])["attempt"] == "repair"


@pytest.mark.parametrize("cancel_after_inference", [False, True])
def test_cancellation_discards_work_without_an_alternate_path(
    cancel_after_inference: bool,
) -> None:
    cancellation = _Cancellation()
    cancellation.cancelled = not cancel_after_inference
    provider = _ChatProvider(
        [_output((EvidenceRelation.SUPPORTS,))],
        after_generate=(lambda: setattr(cancellation, "cancelled", True))
        if cancel_after_inference
        else None,
    )
    composition = compose_evidence_sufficiency_application(
        _local_models(provider),
        cancellation=cancellation,
    )

    with pytest.raises(EvidenceSufficiencyCancelled) as captured:
        composition.evaluate_evidence_sufficiency(_registration(1))

    assert captured.value.__cause__ is None
    assert len(provider.prompts) == int(cancel_after_inference)


def test_provider_failures_are_sanitized_and_never_become_a_decision() -> None:
    private_detail = "private question excerpt path output and provider detail"
    provider = _ChatProvider([RuntimeError(private_detail)])
    composition = compose_evidence_sufficiency_application(_local_models(provider))

    with pytest.raises(EvidenceVerifierError) as captured:
        composition.evaluate_evidence_sufficiency(_registration(1))

    assert str(captured.value) == "evidence verification failed"
    assert captured.value.__cause__ is None
    assert private_detail not in str(captured.value)


@pytest.mark.parametrize(
    "provider_status",
    [
        _status(readiness=ModelReadiness.RESOLVED),
        _status(capability=ModelCapability.EMBEDDING),
    ],
)
def test_non_ready_or_wrong_capability_provider_fails_at_composition(
    provider_status: LocalModelStatus,
) -> None:
    provider = _ChatProvider([], status=provider_status)

    with pytest.raises(EvidenceVerifierError, match="verifier is unavailable"):
        compose_evidence_sufficiency_application(_local_models(provider))


def test_model_substitution_between_provider_and_composition_fails_closed() -> None:
    provider = _ChatProvider([_output((EvidenceRelation.SUPPORTS,))])

    with pytest.raises(
        InvalidEvidenceSufficiencyInput,
        match="policy binding is invalid",
    ):
        compose_evidence_sufficiency_application(
            _local_models(provider, chat_status=_status(model_id=OTHER_MODEL_ID))
        )
