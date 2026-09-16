"""Compose the shared-runtime evidence-sufficiency application boundary."""

from dataclasses import dataclass

from lexlocal.application.evidence_sufficiency import EvaluateEvidenceSufficiency
from lexlocal.application.ports.evidence_sufficiency import (
    EvidencePolicyIdentity,
    EvidenceSufficiencyCancellationCheck,
)
from lexlocal.application.ports.local_models import ChatInferenceProfile
from lexlocal.bootstrap.foundry import LocalModelComposition
from lexlocal.infrastructure.foundry.evidence_verifier import FoundryEvidenceVerifier

EVIDENCE_POLICY_VERSION = "evidence-policy-v2"
EVIDENCE_VERIFIER_CONTRACT_VERSION = "evidence-relations-v2"
EVIDENCE_VERIFIER_INVOCATION_PROFILE = ChatInferenceProfile(
    temperature=0.0,
    random_seed=0,
)


@dataclass(frozen=True, slots=True)
class EvidenceSufficiencyApplicationComposition:
    """Expose the configured evidence-sufficiency use case and policy identity."""

    evaluate_evidence_sufficiency: EvaluateEvidenceSufficiency
    policy: EvidencePolicyIdentity


class _NeverCancelled:
    def raise_if_cancelled(self) -> None:
        return None


def compose_evidence_sufficiency_application(
    local_models: LocalModelComposition,
    *,
    cancellation: EvidenceSufficiencyCancellationCheck | None = None,
) -> EvidenceSufficiencyApplicationComposition:
    """Wire the existing exact chat provider into the frozen verifier policy."""

    cancellation_check = _NeverCancelled() if cancellation is None else cancellation
    verifier = FoundryEvidenceVerifier(
        local_models.chat,
        EVIDENCE_VERIFIER_CONTRACT_VERSION,
        EVIDENCE_VERIFIER_INVOCATION_PROFILE,
        cancellation_check,
    )
    policy = EvidencePolicyIdentity(
        EVIDENCE_POLICY_VERSION,
        EVIDENCE_VERIFIER_CONTRACT_VERSION,
        local_models.chat_status,
    )
    return EvidenceSufficiencyApplicationComposition(
        EvaluateEvidenceSufficiency(verifier, policy, cancellation_check),
        policy,
    )
