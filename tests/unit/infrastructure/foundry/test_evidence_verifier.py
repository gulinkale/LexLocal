"""Tests for strict local evidence-verifier output handling."""

import ast
import json
from pathlib import Path

import pytest

from lexlocal.application.ports.evidence_sufficiency import (
    EvidenceRelation,
    EvidenceSufficiencyCancellationCheck,
    EvidenceSufficiencyCancelled,
    EvidenceVerifier,
    EvidenceVerifierError,
    EvidenceVerifierRequest,
    VerifierEvidence,
)
from lexlocal.application.ports.local_models import (
    ChatInferenceProfile,
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
    ResolvedModelRecord,
)
from lexlocal.domain.identifiers import EvidenceItemId, LocalModelId
from lexlocal.domain.retrieval import EvidenceRank
from lexlocal.infrastructure.foundry.evidence_verifier import FoundryEvidenceVerifier

MODEL_ID = LocalModelId("10000000-0000-4000-8000-000000000001")
OTHER_MODEL_ID = LocalModelId("10000000-0000-4000-8000-000000000002")
EVIDENCE_IDS = (
    EvidenceItemId("20000000-0000-4000-8000-000000000001"),
    EvidenceItemId("20000000-0000-4000-8000-000000000002"),
)
QUESTION = "Exact private synthetic question Ω?"
EXCERPTS = (
    "Exact private synthetic passage one Ω.",
    "Exact private synthetic passage two Ω.",
)
CONTRACT_VERSION = "evidence-relations-v2"
INVOCATION_PROFILE = ChatInferenceProfile(temperature=0.0, random_seed=0)
RELATION_DEFINITIONS = {
    "SUPPORTS": (
        "The item contains question-answering information and belongs to a coherent, "
        "non-conflicting selected evidence set that provides enough information to "
        "answer the exact question. Negative, corrective, or alternative direct "
        "answers remain SUPPORTS and must not be treated as contradictions merely "
        "because they differ from an assumed answer."
    ),
    "RELATED_ONLY": (
        "The item explicitly concerns the question-relevant subject or fact, but "
        "does not provide enough information to answer the asked value or property "
        "under the complete selected evidence set."
    ),
    "CONTRADICTS": (
        "The item is question-answering evidence that genuinely conflicts with "
        "another selected evidence item about the same question-relevant fact. "
        "Classify all items participating in that genuine conflict as CONTRADICTS; "
        "do not arbitrarily treat one side as the expected or correct answer."
    ),
    "IRRELEVANT": (
        "The item provides no meaningful question-answering information and does not "
        "explicitly concern the question-relevant subject or fact. Superficial lexical "
        "overlap alone is insufficient to make it RELATED_ONLY."
    ),
}
ASSESSMENT_CONTEXT = (
    "Assess every evidence item against the exact question in the context of the "
    "complete supplied selected evidence set. A genuine conflict takes precedence "
    "over otherwise question-answering support. After ruling out SUPPORTS and "
    "CONTRADICTS, classify an item as RELATED_ONLY when it explicitly concerns the "
    "question-relevant subject or fact even if it gives a different property or says "
    "the asked value is absent. Use IRRELEVANT only when that explicit link is absent."
)
VALID_OUTPUT = json.dumps(
    {
        "assessments": [
            {"evidence": "E2", "relation": "RELATED_ONLY"},
            {"evidence": "E1", "relation": "SUPPORTS"},
        ]
    }
)


def _status(
    *,
    model_id: LocalModelId = MODEL_ID,
    readiness: ModelReadiness = ModelReadiness.READY,
    capability: ModelCapability = ModelCapability.CHAT,
) -> LocalModelStatus:
    return LocalModelStatus(
        ResolvedModelRecord(
            model_id,
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


def _request() -> EvidenceVerifierRequest:
    return EvidenceVerifierRequest(
        QUESTION,
        tuple(
            VerifierEvidence(evidence_id, EvidenceRank(index), EXCERPTS[index - 1])
            for index, evidence_id in enumerate(EVIDENCE_IDS, start=1)
        ),
    )


def _semantic_request(question: str, excerpts: tuple[str, ...]) -> EvidenceVerifierRequest:
    return EvidenceVerifierRequest(
        question,
        tuple(
            VerifierEvidence(
                EVIDENCE_IDS[index],
                EvidenceRank(index + 1),
                excerpt,
            )
            for index, excerpt in enumerate(excerpts)
        ),
    )


class _Provider:
    def __init__(
        self,
        outputs: list[object],
        *,
        status: LocalModelStatus | None = None,
    ) -> None:
        self.outputs = outputs
        self._status = _status() if status is None else status
        self.status_after_generate: LocalModelStatus | None = None
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
        if isinstance(output, Exception):
            raise output
        if self.status_after_generate is not None:
            self._status = self.status_after_generate
        return output  # type: ignore[return-value]


class _Cancellation:
    def __init__(
        self,
        *,
        cancel_at: int | None = None,
        failure_at: int | None = None,
    ) -> None:
        self.cancel_at = cancel_at
        self.failure_at = failure_at
        self.checks = 0

    def raise_if_cancelled(self) -> None:
        self.checks += 1
        if self.checks == self.cancel_at:
            raise EvidenceSufficiencyCancelled("private cancellation detail")
        if self.checks == self.failure_at:
            raise RuntimeError("private cancellation checker detail")


def _verifier(
    provider: _Provider,
    cancellation: EvidenceSufficiencyCancellationCheck | None = None,
) -> FoundryEvidenceVerifier:
    return FoundryEvidenceVerifier(
        provider,
        CONTRACT_VERSION,
        INVOCATION_PROFILE,
        _Cancellation() if cancellation is None else cancellation,
    )


_VERIFIER_CONFORMANCE: EvidenceVerifier = _verifier(_Provider([VALID_OUTPUT]))


def test_valid_output_is_aligned_to_authoritative_rank_and_sdk_free() -> None:
    provider = _Provider([VALID_OUTPUT])
    verifier = _verifier(provider)

    result = verifier.verify(_request())

    assert verifier.status is provider.status
    assert result.status is provider.status
    assert result.verifier_contract_version == CONTRACT_VERSION
    assert provider.profiles == [INVOCATION_PROFILE]
    assert result.repair_used is False
    assert tuple(item.evidence_item_id for item in result.assessments) == EVIDENCE_IDS
    assert tuple(item.rank.value for item in result.assessments) == (1, 2)
    assert tuple(item.relation for item in result.assessments) == (
        EvidenceRelation.SUPPORTS,
        EvidenceRelation.RELATED_ONLY,
    )
    assert all(type(item.relation) is EvidenceRelation for item in result.assessments)
    assert len(provider.prompts) == 1


def test_prompt_contains_only_exact_labelled_context_and_strict_contract() -> None:
    provider = _Provider([VALID_OUTPUT])
    _verifier(provider).verify(_request())

    prompt = json.loads(provider.prompts[0])

    assert prompt["question"] == QUESTION
    assert prompt["evidence"] == [
        {"label": "E1", "excerpt": EXCERPTS[0]},
        {"label": "E2", "excerpt": EXCERPTS[1]},
    ]
    assert prompt["verifier_contract_version"] == CONTRACT_VERSION
    assert prompt["allowed_relations"] == [item.value for item in EvidenceRelation]
    assert prompt["relation_definitions"] == RELATION_DEFINITIONS
    assert prompt["assessment_context"] == ASSESSMENT_CONTEXT
    assert prompt["attempt"] == "initial"
    assert all(str(value) not in provider.prompts[0] for value in EVIDENCE_IDS)
    assert "workspace" not in provider.prompts[0]
    assert "document" not in provider.prompts[0]
    assert all(set(item) == {"label", "excerpt"} for item in prompt["evidence"])


@pytest.mark.parametrize(
    ("question", "excerpts", "relations"),
    [
        pytest.param(
            "Is the synthetic valve open?",
            ("No. The synthetic valve is closed.",),
            (EvidenceRelation.SUPPORTS,),
            id="negative-direct-answer-supports",
        ),
        pytest.param(
            "Which synthetic door is open?",
            ("Correction: the blue door, not the red door, is open.",),
            (EvidenceRelation.SUPPORTS,),
            id="corrective-alternative-answer-supports",
        ),
        pytest.param(
            "Is the synthetic valve open?",
            (
                "The synthetic valve is open.",
                "The synthetic valve is closed.",
            ),
            (EvidenceRelation.CONTRADICTS, EvidenceRelation.CONTRADICTS),
            id="genuine-conflict-marks-all-participants",
        ),
        pytest.param(
            "When was the synthetic bridge inspected?",
            ("The synthetic bridge is painted blue.",),
            (EvidenceRelation.RELATED_ONLY,),
            id="related-non-answer",
        ),
        pytest.param(
            "When was the synthetic bridge inspected?",
            ("The anonymous garden has three benches.",),
            (EvidenceRelation.IRRELEVANT,),
            id="irrelevant-evidence",
        ),
    ],
)
def test_prompt_enforces_frozen_relation_semantics(
    question: str,
    excerpts: tuple[str, ...],
    relations: tuple[EvidenceRelation, ...],
) -> None:
    request = _semantic_request(question, excerpts)
    output = json.dumps(
        {
            "assessments": [
                {"evidence": f"E{index}", "relation": relation.value}
                for index, relation in enumerate(relations, start=1)
            ]
        }
    )
    provider = _Provider([output])

    result = _verifier(provider).verify(request)
    prompt = json.loads(provider.prompts[0])

    assert prompt["question"] == question
    assert prompt["evidence"] == [
        {"label": f"E{index}", "excerpt": excerpt}
        for index, excerpt in enumerate(excerpts, start=1)
    ]
    assert prompt["relation_definitions"] == RELATION_DEFINITIONS
    assert prompt["assessment_context"] == ASSESSMENT_CONTEXT
    assert tuple(item.relation for item in result.assessments) == relations


@pytest.mark.parametrize(
    "invalid_output",
    [
        "not-json",
        "{}",
        '{"assessments":[],"extra":true}',
        '{"assessments":{}}',
        '{"assessments":[null]}',
        '{"assessments":[{"evidence":"E1"}]}',
        '{"assessments":[{"evidence":"E1","relation":"SUPPORTS","extra":1}]}',
        '{"assessments":[{"evidence":1,"relation":"SUPPORTS"}]}',
        '{"assessments":[{"evidence":"E1","relation":true}]}',
        '{"assessments":[{"evidence":"E1","relation":"CERTAIN"},'
        '{"evidence":"E2","relation":"IRRELEVANT"}]}',
        '{"assessments":[{"evidence":"E3","relation":"SUPPORTS"},'
        '{"evidence":"E2","relation":"IRRELEVANT"}]}',
        '{"assessments":[{"evidence":"E1","relation":"SUPPORTS"},'
        '{"evidence":"E1","relation":"IRRELEVANT"}]}',
        '{"assessments":[{"evidence":"E1","relation":"SUPPORTS"}]}',
        '{"assessments":[{"evidence":"E1","evidence":"E2",'
        '"relation":"SUPPORTS"}]}',
        '{"assessments":[{"evidence":"E1","relation":"SUPPORTS",'
        '"confidence":1.0},{"evidence":"E2","relation":"IRRELEVANT"}]}',
        '{"assessments":[{"evidence":"E1","relation":"SUPPORTS",'
        '"rationale":"private"},{"evidence":"E2","relation":"IRRELEVANT"}]}',
        '{"assessments":[{"evidence":"E1","relation":"SUPPORTS",'
        '"sufficiency":"SUFFICIENT"},{"evidence":"E2",'
        '"relation":"IRRELEVANT"}]}',
    ],
)
def test_invalid_output_gets_only_one_repair_then_fails_safely(
    invalid_output: str,
) -> None:
    provider = _Provider([invalid_output, invalid_output])

    with pytest.raises(EvidenceVerifierError) as captured:
        _verifier(provider).verify(_request())

    assert str(captured.value) == "evidence verifier output is invalid"
    assert captured.value.__cause__ is None
    assert len(provider.prompts) == 2
    assert invalid_output not in provider.prompts[1]


@pytest.mark.parametrize("invalid_output", [None, True, 1, [], {}])
def test_non_text_output_is_strictly_rejected_after_one_repair(
    invalid_output: object,
) -> None:
    provider = _Provider([invalid_output, invalid_output])

    with pytest.raises(EvidenceVerifierError, match="output is invalid"):
        _verifier(provider).verify(_request())

    assert len(provider.prompts) == 2


def test_one_repair_uses_same_provider_contract_question_evidence_and_schema() -> None:
    invalid_output = "private malformed raw output"
    provider = _Provider([invalid_output, VALID_OUTPUT])

    result = _verifier(provider).verify(_request())

    assert result.repair_used is True
    assert len(provider.prompts) == 2
    initial = json.loads(provider.prompts[0])
    repair = json.loads(provider.prompts[1])
    assert initial.pop("attempt") == "initial"
    assert repair.pop("attempt") == "repair"
    assert repair == initial
    assert invalid_output not in provider.prompts[1]
    assert provider.profiles == [INVOCATION_PROFILE, INVOCATION_PROFILE]


@pytest.mark.parametrize(
    "status",
    [
        _status(readiness=ModelReadiness.RESOLVED),
        _status(capability=ModelCapability.EMBEDDING),
    ],
)
def test_constructor_rejects_non_ready_or_non_chat_provider(
    status: LocalModelStatus,
) -> None:
    provider = _Provider([VALID_OUTPUT], status=status)

    with pytest.raises(EvidenceVerifierError, match="verifier is unavailable") as error:
        _verifier(provider)

    assert error.value.__cause__ is None
    assert provider.prompts == []


def test_provider_identity_change_fails_without_repair() -> None:
    provider = _Provider([VALID_OUTPUT])
    verifier = _verifier(provider)
    provider._status = _status(model_id=OTHER_MODEL_ID)

    with pytest.raises(EvidenceVerifierError, match="identity changed") as error:
        verifier.verify(_request())

    assert error.value.__cause__ is None
    assert provider.prompts == []


def test_provider_identity_change_during_inference_fails_without_repair() -> None:
    provider = _Provider([VALID_OUTPUT])
    provider.status_after_generate = _status(model_id=OTHER_MODEL_ID)

    with pytest.raises(EvidenceVerifierError, match="identity changed"):
        _verifier(provider).verify(_request())

    assert len(provider.prompts) == 1


@pytest.mark.parametrize("failure_type", [RuntimeError, EvidenceVerifierError])
def test_provider_failure_is_sanitized_and_never_repaired(
    failure_type: type[Exception],
) -> None:
    provider = _Provider(
        [failure_type("private prompt, model path, URI, and provider object")]
    )

    with pytest.raises(EvidenceVerifierError) as captured:
        _verifier(provider).verify(_request())

    assert str(captured.value) == "evidence verifier inference failed"
    assert captured.value.__cause__ is None
    assert len(provider.prompts) == 1
    assert QUESTION not in str(captured.value)
    assert all(excerpt not in str(captured.value) for excerpt in EXCERPTS)


@pytest.mark.parametrize(
    ("cancel_at", "expected_calls"),
    [(1, 0), (2, 0), (3, 1), (4, 1)],
)
def test_valid_path_cancellation_discards_output_at_every_boundary(
    cancel_at: int,
    expected_calls: int,
) -> None:
    provider = _Provider([VALID_OUTPUT])
    cancellation = _Cancellation(cancel_at=cancel_at)

    with pytest.raises(
        EvidenceSufficiencyCancelled,
        match="evidence verification was cancelled",
    ) as captured:
        _verifier(provider, cancellation).verify(_request())

    assert captured.value.__cause__ is None
    assert len(provider.prompts) == expected_calls


@pytest.mark.parametrize(
    ("cancel_at", "expected_calls"),
    [(4, 1), (5, 1), (6, 2), (7, 2)],
)
def test_repair_path_cancellation_never_returns_or_adds_another_repair(
    cancel_at: int,
    expected_calls: int,
) -> None:
    provider = _Provider(["invalid", VALID_OUTPUT])
    cancellation = _Cancellation(cancel_at=cancel_at)

    with pytest.raises(EvidenceSufficiencyCancelled) as captured:
        _verifier(provider, cancellation).verify(_request())

    assert captured.value.__cause__ is None
    assert len(provider.prompts) == expected_calls


def test_cancellation_checker_failure_is_sanitized_without_provider_use() -> None:
    provider = _Provider([VALID_OUTPUT])

    with pytest.raises(EvidenceVerifierError) as captured:
        _verifier(provider, _Cancellation(failure_at=1)).verify(_request())

    assert str(captured.value) == "evidence verification cancellation check failed"
    assert captured.value.__cause__ is None
    assert provider.prompts == []


def test_adapter_owns_no_runtime_sdk_or_model_lifecycle() -> None:
    adapter_path = (
        Path(__file__).resolve().parents[4]
        / "src"
        / "lexlocal"
        / "infrastructure"
        / "foundry"
        / "evidence_verifier.py"
    )
    tree = ast.parse(adapter_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    called_names = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert all(
        not module.startswith(("foundry_local_sdk", "openai"))
        for module in imported_modules
    )
    assert called_names.isdisjoint(
        {"initialize", "resolve_ready", "prepare", "download", "close"}
    )
    assert _VERIFIER_CONFORMANCE.status.model.id == MODEL_ID
