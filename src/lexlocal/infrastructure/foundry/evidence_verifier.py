"""Verify evidence relations through an injected exact local chat provider."""

from __future__ import annotations

import json

from lexlocal.application.ports.evidence_sufficiency import (
    EvidenceAssessment,
    EvidenceRelation,
    EvidenceSufficiencyCancellationCheck,
    EvidenceSufficiencyCancelled,
    EvidenceVerifierError,
    EvidenceVerifierRequest,
    EvidenceVerifierResult,
)
from lexlocal.application.ports.local_models import (
    ChatInferenceProfile,
    ChatInferenceProvider,
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
)


class _InvalidVerifierOutput(Exception):
    """Mark untrusted output as invalid without retaining its value."""


_RELATION_DEFINITIONS = {
    EvidenceRelation.SUPPORTS.value: (
        "The item contains question-answering information and belongs to a coherent, "
        "non-conflicting selected evidence set that provides enough information to "
        "answer the exact question. Negative, corrective, or alternative direct "
        "answers remain SUPPORTS and must not be treated as contradictions merely "
        "because they differ from an assumed answer."
    ),
    EvidenceRelation.RELATED_ONLY.value: (
        "The item explicitly concerns the question-relevant subject or fact, but "
        "does not provide enough information to answer the asked value or property "
        "under the complete selected evidence set."
    ),
    EvidenceRelation.CONTRADICTS.value: (
        "The item is question-answering evidence that genuinely conflicts with "
        "another selected evidence item about the same question-relevant fact. "
        "Classify all items participating in that genuine conflict as CONTRADICTS; "
        "do not arbitrarily treat one side as the expected or correct answer."
    ),
    EvidenceRelation.IRRELEVANT.value: (
        "The item provides no meaningful question-answering information and does not "
        "explicitly concern the question-relevant subject or fact. Superficial lexical "
        "overlap alone is insufficient to make it RELATED_ONLY."
    ),
}
_ASSESSMENT_CONTEXT = (
    "Assess every evidence item against the exact question in the context of the "
    "complete supplied selected evidence set. A genuine conflict takes precedence "
    "over otherwise question-answering support. After ruling out SUPPORTS and "
    "CONTRADICTS, classify an item as RELATED_ONLY when it explicitly concerns the "
    "question-relevant subject or fact even if it gives a different property or says "
    "the asked value is absent. Use IRRELEVANT only when that explicit link is absent."
)


class FoundryEvidenceVerifier:
    """Adapt one injected chat provider to the strict evidence-verifier port."""

    def __init__(
        self,
        provider: ChatInferenceProvider,
        verifier_contract_version: str,
        invocation_profile: ChatInferenceProfile,
        cancellation: EvidenceSufficiencyCancellationCheck,
    ) -> None:
        self._provider = provider
        self._verifier_contract_version = self._require_version(
            verifier_contract_version
        )
        if not isinstance(invocation_profile, ChatInferenceProfile):
            raise EvidenceVerifierError("evidence verifier profile is invalid")
        self._invocation_profile = invocation_profile
        self._cancellation = cancellation
        self._status = self._read_ready_status()

    @property
    def status(self) -> LocalModelStatus:
        """Return the exact injected READY chat-model identity."""

        return self._status

    def verify(self, request: EvidenceVerifierRequest) -> EvidenceVerifierResult:
        """Return one complete typed assessment set or a sanitized failure."""

        if not isinstance(request, EvidenceVerifierRequest):
            raise EvidenceVerifierError("evidence verification request is invalid")
        self._check_cancellation()
        self._require_bound_status()
        initial_prompt = self._prompt(request, repair=False)
        self._check_cancellation()
        initial_output = self._generate(initial_prompt)
        self._check_cancellation()
        self._require_bound_status()
        try:
            assessments = self._parse(initial_output, request)
            repair_used = False
        except _InvalidVerifierOutput:
            self._check_cancellation()
            self._require_bound_status()
            repair_prompt = self._prompt(request, repair=True)
            self._check_cancellation()
            repair_output = self._generate(repair_prompt)
            self._check_cancellation()
            self._require_bound_status()
            try:
                assessments = self._parse(repair_output, request)
            except _InvalidVerifierOutput:
                raise EvidenceVerifierError("evidence verifier output is invalid") from None
            repair_used = True
        self._check_cancellation()
        try:
            return EvidenceVerifierResult(
                request,
                self._status,
                self._verifier_contract_version,
                assessments,
                repair_used,
            )
        except Exception:
            raise EvidenceVerifierError("evidence verifier output is invalid") from None

    def _generate(self, prompt: str) -> object:
        try:
            return self._provider.generate(prompt, profile=self._invocation_profile)
        except Exception:
            raise EvidenceVerifierError("evidence verifier inference failed") from None

    def _parse(
        self,
        output: object,
        request: EvidenceVerifierRequest,
    ) -> tuple[EvidenceAssessment, ...]:
        if not isinstance(output, str):
            raise _InvalidVerifierOutput
        try:
            decoded = json.loads(output, object_pairs_hook=_unique_object)
        except Exception:
            raise _InvalidVerifierOutput from None
        if not isinstance(decoded, dict) or set(decoded) != {"assessments"}:
            raise _InvalidVerifierOutput
        items = decoded["assessments"]
        if not isinstance(items, list):
            raise _InvalidVerifierOutput

        expected = {item.label: item for item in request.evidence}
        relations: dict[str, EvidenceRelation] = {}
        for item in items:
            if not isinstance(item, dict) or set(item) != {"evidence", "relation"}:
                raise _InvalidVerifierOutput
            label = item["evidence"]
            relation_value = item["relation"]
            if (
                type(label) is not str
                or type(relation_value) is not str
                or label not in expected
                or label in relations
            ):
                raise _InvalidVerifierOutput
            try:
                relations[label] = EvidenceRelation(relation_value)
            except ValueError:
                raise _InvalidVerifierOutput from None
        if set(relations) != set(expected):
            raise _InvalidVerifierOutput
        return tuple(
            EvidenceAssessment(
                item.evidence_item_id,
                item.rank,
                relations[item.label],
            )
            for item in request.evidence
        )

    def _prompt(self, request: EvidenceVerifierRequest, *, repair: bool) -> str:
        envelope = {
            "task": "classify-evidence-relations",
            "verifier_contract_version": self._verifier_contract_version,
            "attempt": "repair" if repair else "initial",
            "rules": [
                "Use only the supplied question and evidence passages.",
                "Return JSON only with no additional fields or commentary.",
                "Assess every evidence label exactly once.",
                "Do not provide sufficiency, confidence, rationale, or source metadata.",
            ],
            "assessment_context": _ASSESSMENT_CONTEXT,
            "question": request.question,
            "evidence": [
                {"label": item.label, "excerpt": item.excerpt}
                for item in request.evidence
            ],
            "allowed_relations": [item.value for item in EvidenceRelation],
            "relation_definitions": _RELATION_DEFINITIONS,
            "output_schema": {
                "assessments": [
                    {"evidence": "E{rank}", "relation": "<allowed_relation>"}
                ]
            },
        }
        return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))

    def _read_ready_status(self) -> LocalModelStatus:
        try:
            status = self._provider.status
        except Exception:
            raise EvidenceVerifierError("evidence verifier is unavailable") from None
        if (
            not isinstance(status, LocalModelStatus)
            or status.readiness is not ModelReadiness.READY
            or status.model.capability is not ModelCapability.CHAT
        ):
            raise EvidenceVerifierError("evidence verifier is unavailable")
        return status

    def _require_bound_status(self) -> None:
        try:
            current = self._provider.status
        except Exception:
            raise EvidenceVerifierError("evidence verifier is unavailable") from None
        if current != self._status:
            raise EvidenceVerifierError("evidence verifier identity changed")

    def _check_cancellation(self) -> None:
        try:
            self._cancellation.raise_if_cancelled()
        except EvidenceSufficiencyCancelled:
            raise EvidenceSufficiencyCancelled(
                "evidence verification was cancelled"
            ) from None
        except Exception:
            raise EvidenceVerifierError(
                "evidence verification cancellation check failed"
            ) from None

    @staticmethod
    def _require_version(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise EvidenceVerifierError("evidence verifier contract is invalid")
        return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidVerifierOutput
        result[key] = value
    return result
