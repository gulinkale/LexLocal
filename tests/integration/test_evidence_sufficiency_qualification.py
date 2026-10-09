"""Qualification evidence for the fixed anonymous RAG-002 corpus."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from lexlocal.application.ports.evidence_sufficiency import (
    AggregateEvidenceCoverage,
    EvidenceRelation,
    EvidenceRelationCounts,
    EvidenceSufficiencyError,
    EvidenceSufficiencyResult,
)
from lexlocal.application.ports.indexing import PersistedIndexGeneration
from lexlocal.application.ports.local_models import (
    ChatInferenceProfile,
    ChatInferenceProvider,
    LocalModelStatus,
    LocalModelUnavailable,
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
    EVIDENCE_VERIFIER_INVOCATION_PROFILE,
    compose_evidence_sufficiency_application,
)
from lexlocal.bootstrap.foundry import LocalModelComposition
from lexlocal.bootstrap.settings import load_settings
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
from lexlocal.infrastructure.foundry.local_adapter import FoundryLocalRuntime

_OPT_IN_ENVIRONMENT_VARIABLE = "LEXLOCAL_RUN_RAG002_QUALIFICATION"
_REPEAT_COUNT = 3
_NOW = datetime(2026, 9, 11, 16, 0, tzinfo=UTC)
_WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
_QA_REQUEST_ID = QaRequestId("20000000-0000-4000-8000-000000000001")
_RETRIEVAL_RUN_ID = RetrievalRunId("30000000-0000-4000-8000-000000000001")
_CHAT_MODEL_ID = LocalModelId("40000000-0000-4000-8000-000000000001")


@dataclass(frozen=True, slots=True)
class _QualificationCase:
    name: str
    question: str = field(repr=False)
    excerpts: tuple[str, ...] = field(repr=False)
    relations: tuple[EvidenceRelation, ...]
    state: EvidenceSufficiency


_CASES = (
    _QualificationCase(
        "direct-support",
        "What color is the anonymous synthetic marker?",
        ("The anonymous synthetic marker is blue.",),
        (EvidenceRelation.SUPPORTS,),
        EvidenceSufficiency.SUFFICIENT,
    ),
    _QualificationCase(
        "paraphrased-support",
        "What powers the anonymous synthetic beacon?",
        ("The same anonymous synthetic beacon gets all of its energy from sunlight.",),
        (EvidenceRelation.SUPPORTS,),
        EvidenceSufficiency.SUFFICIENT,
    ),
    _QualificationCase(
        "related-non-answer",
        "What color is the anonymous synthetic marker?",
        ("The anonymous synthetic marker is stored in cabinet seven.",),
        (EvidenceRelation.RELATED_ONLY,),
        EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
    ),
    _QualificationCase(
        "lexical-hard-negative",
        "What color is the anonymous synthetic marker?",
        (
            "The anonymous report lists marker color categories but does not state "
            "the synthetic marker's color.",
        ),
        (EvidenceRelation.RELATED_ONLY,),
        EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
    ),
    _QualificationCase(
        "genuine-contradiction",
        "What color is the anonymous synthetic marker?",
        (
            "The anonymous synthetic marker is blue.",
            "The same anonymous synthetic marker is orange.",
        ),
        (EvidenceRelation.CONTRADICTS, EvidenceRelation.CONTRADICTS),
        EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
    ),
    _QualificationCase(
        "irrelevant",
        "What color is the anonymous synthetic marker?",
        ("An unrelated synthetic clock ticks once per minute.",),
        (EvidenceRelation.IRRELEVANT,),
        EvidenceSufficiency.INSUFFICIENT,
    ),
)


def _status(
    capability: ModelCapability,
    *,
    model_id: LocalModelId = _CHAT_MODEL_ID,
) -> LocalModelStatus:
    return LocalModelStatus(
        ResolvedModelRecord(
            model_id,
            "qwen3-4b" if capability is ModelCapability.CHAT else "unused-embedding",
            "anonymous-synthetic:1",
            "1",
            capability,
            "local",
            None if capability is ModelCapability.CHAT else 2,
        ),
        ModelReadiness.READY,
        "LocalExecutionProvider",
    )


def _registration(case: _QualificationCase) -> RetrievalRegistration:
    generation = IndexGeneration(
        IndexGenerationId("50000000-0000-4000-8000-000000000001"),
        _WORKSPACE_ID,
        DocumentVersionId("60000000-0000-4000-8000-000000000001"),
        ProcessingJobId("70000000-0000-4000-8000-000000000001"),
        LocalModelId("80000000-0000-4000-8000-000000000001"),
        "chunk-v1",
        "normalize-v1",
        2,
        IndexGenerationState.ACTIVE,
    )
    resolved = ResolvedRetrievalGeneration(
        DocumentId("90000000-0000-4000-8000-000000000001"),
        VersionNumber(1),
        "Anonymous synthetic qualification document",
        PersistedIndexGeneration(generation, _NOW, activated_at=_NOW),
        ProcessingJobState.READY,
    )
    evidence = tuple(
        _evidence(resolved, index, excerpt)
        for index, excerpt in enumerate(case.excerpts, start=1)
    )
    return RetrievalRegistration(
        _RETRIEVAL_RUN_ID,
        ResolvedRetrievalScope(
            QaRetrievalRequest(
                _QA_REQUEST_ID,
                _WORKSPACE_ID,
                case.question,
            ),
            (resolved,),
        ),
        RetrievalConfiguration(),
        max(1, len(evidence)),
        evidence,
        _NOW,
    )


def _evidence(
    generation: ResolvedRetrievalGeneration,
    rank: int,
    excerpt: str,
) -> RetrievalEvidenceRegistration:
    locator = SourceLocator(
        SourceLocatorId(f"a0000000-0000-4000-8000-{rank:012d}"),
        _WORKSPACE_ID,
        generation.document_version_id,
        DocumentPageId(f"b0000000-0000-4000-8000-{rank:012d}"),
        PageNumber(rank),
        SourceLocatorKind.PAGE,
    )
    return RetrievalEvidenceRegistration(
        Evidence(
            EvidenceItemId(f"c0000000-0000-4000-8000-{rank:012d}"),
            _WORKSPACE_ID,
            _RETRIEVAL_RUN_ID,
            generation.document_id,
            generation.document_version_id,
            locator.page_number,
            EvidenceRank(rank),
            SimilarityScore(1.0 - rank / 100),
            ChunkId(f"d0000000-0000-4000-8000-{rank:012d}"),
            locator.id,
        ),
        generation.index_generation_id,
        rank - 1,
        locator,
        generation.document_display_name,
        generation.version_number,
        excerpt,
        _NOW,
    )


def _output(relations: tuple[EvidenceRelation, ...]) -> str:
    return json.dumps(
        {
            "assessments": [
                {"evidence": f"E{index}", "relation": relation.value}
                for index, relation in enumerate(relations, start=1)
            ]
        }
    )


class _QueuedChatProvider:
    def __init__(self, outputs: list[str], status: LocalModelStatus) -> None:
        self.outputs = outputs
        self._status = status
        self.calls = 0
        self.profiles: list[ChatInferenceProfile | None] = []

    @property
    def status(self) -> LocalModelStatus:
        return self._status

    def generate(
        self,
        _prompt: str,
        *,
        profile: ChatInferenceProfile | None = None,
    ) -> str:
        self.calls += 1
        self.profiles.append(profile)
        return self.outputs.pop(0)


class _UnusedEmbeddingProvider:
    @property
    def status(self) -> LocalModelStatus:
        return _status(
            ModelCapability.EMBEDDING,
            model_id=LocalModelId("40000000-0000-4000-8000-000000000002"),
        )

    def embed(self, _texts: Sequence[str]) -> Sequence[Sequence[float]]:
        raise AssertionError("qualification must not invoke query embedding")


def _local_models(
    provider: ChatInferenceProvider,
    status: LocalModelStatus,
    close: Callable[[], None],
) -> LocalModelComposition:
    return LocalModelComposition(
        provider,
        _UnusedEmbeddingProvider(),
        status,
        _UnusedEmbeddingProvider().status,
        close,
    )


def _chat_snapshot_projection(result: EvidenceSufficiencyResult) -> tuple[object, ...]:
    return (
        result.state,
        (
            result.retrieval.workspace_id,
            result.retrieval.qa_request_id,
            result.retrieval.retrieval_run_id,
            result.policy.evidence_policy_version,
            result.aggregate_coverage,
            result.relation_counts,
            result.repair_used,
        ),
        tuple(
            (assessment.evidence_item_id, assessment.relation)
            for assessment in result.assessments
        ),
    )


def test_fixed_fake_provider_corpus_is_stable_for_eighteen_runs() -> None:
    outputs = [
        _output(case.relations)
        for case in _CASES
        for _ in range(_REPEAT_COUNT)
    ]
    provider = _QueuedChatProvider(outputs, _status(ModelCapability.CHAT))
    composition = compose_evidence_sufficiency_application(
        _local_models(provider, provider.status, lambda: None)
    )

    observations: dict[str, set[tuple[object, ...]]] = {
        case.name: set() for case in _CASES
    }
    for case in _CASES:
        registration = _registration(case)
        for _ in range(_REPEAT_COUNT):
            result = composition.evaluate_evidence_sufficiency(registration)
            observations[case.name].add(
                (
                    tuple(item.relation for item in result.assessments),
                    result.state,
                    result.repair_used,
                )
            )

    assert provider.calls == len(_CASES) * _REPEAT_COUNT
    assert provider.profiles == [
        EVIDENCE_VERIFIER_INVOCATION_PROFILE
    ] * (len(_CASES) * _REPEAT_COUNT)
    assert not provider.outputs
    assert all(len(values) == 1 for values in observations.values())
    assert all(
        observations[case.name] == {(case.relations, case.state, False)}
        for case in _CASES
    )


@pytest.mark.parametrize("repair_used", [False, True])
def test_result_projects_losslessly_to_frozen_chat_snapshot(
    repair_used: bool,
) -> None:
    case = _CASES[0]
    outputs = (
        ["not-json", _output(case.relations)]
        if repair_used
        else [_output(case.relations)]
    )
    provider = _QueuedChatProvider(outputs, _status(ModelCapability.CHAT))
    composition = compose_evidence_sufficiency_application(
        _local_models(provider, provider.status, lambda: None)
    )

    result = composition.evaluate_evidence_sufficiency(_registration(case))
    state, header, relations = _chat_snapshot_projection(result)

    assert state is case.state
    assert header == (
        _WORKSPACE_ID,
        _QA_REQUEST_ID,
        _RETRIEVAL_RUN_ID,
        result.policy.evidence_policy_version,
        AggregateEvidenceCoverage.READY,
        EvidenceRelationCounts(1, 0, 0, 0),
        repair_used,
    )
    assert relations == tuple(
        (item.evidence.id, relation)
        for item, relation in zip(
            result.retrieval.evidence,
            case.relations,
            strict=True,
        )
    )
    serialized = repr((state, header, relations))
    assert case.question not in serialized
    assert all(excerpt not in serialized for excerpt in case.excerpts)


def test_zero_evidence_projects_to_the_frozen_empty_snapshot_shape() -> None:
    case = _QualificationCase(
        "zero-evidence",
        "What color is the anonymous synthetic marker?",
        (),
        (),
        EvidenceSufficiency.INSUFFICIENT,
    )
    provider = _QueuedChatProvider([], _status(ModelCapability.CHAT))
    composition = compose_evidence_sufficiency_application(
        _local_models(provider, provider.status, lambda: None)
    )

    result = composition.evaluate_evidence_sufficiency(_registration(case))
    state, header, relations = _chat_snapshot_projection(result)

    assert state is EvidenceSufficiency.INSUFFICIENT
    assert header[-3:] == (
        AggregateEvidenceCoverage.READY,
        EvidenceRelationCounts(0, 0, 0, 0),
        False,
    )
    assert relations == ()
    assert provider.calls == 0


@pytest.mark.foundry_smoke
@pytest.mark.skipif(
    os.environ.get(_OPT_IN_ENVIRONMENT_VARIABLE) != "1",
    reason=(
        f"set {_OPT_IN_ENVIRONMENT_VARIABLE}=1 to run cached/offline qualification"
    ),
)
def test_cached_configured_chat_model_is_stable_on_fixed_corpus() -> None:
    settings = load_settings()
    runtime: FoundryLocalRuntime | None = None
    try:
        runtime = FoundryLocalRuntime.initialize(
            model_cache_dir=settings.foundry_model_cache_dir,
        )
        status = runtime.resolve_ready(
            model_id=_CHAT_MODEL_ID,
            requested_alias=settings.chat_model_alias,
            capability=ModelCapability.CHAT,
        )
        provider = runtime.chat_provider(status)
    except LocalModelUnavailable:
        if runtime is not None:
            runtime.close()
        pytest.skip("exact configured cached local chat model is not READY")

    local_models = _local_models(provider, status, runtime.close)
    composition = compose_evidence_sufficiency_application(local_models)
    try:
        observations: dict[str, set[tuple[object, ...]]] = {
            case.name: set() for case in _CASES
        }
        run_results: list[tuple[object, ...]] = []
        for case in _CASES:
            registration = _registration(case)
            for run_number in range(1, _REPEAT_COUNT + 1):
                try:
                    result = composition.evaluate_evidence_sufficiency(registration)
                except EvidenceSufficiencyError as error:
                    run_results.append(
                        (case.name, run_number, "OPERATIONAL_FAILURE", type(error).__name__)
                    )
                    continue
                observed = (
                    tuple(item.relation for item in result.assessments),
                    result.state,
                )
                observations[case.name].add(observed)
                run_results.append((case.name, run_number, *observed))

        expected = {
            case.name: (case.relations, case.state) for case in _CASES
        }
        failures = tuple(
            result
            for result in run_results
            if len(result) != 4
            or result[2:] != expected[str(result[0])]
        )
        assert len(run_results) == len(_CASES) * _REPEAT_COUNT
        assert not failures, f"live qualification failures: {failures!r}"
        assert all(len(values) == 1 for values in observations.values())
    finally:
        local_models.close()
