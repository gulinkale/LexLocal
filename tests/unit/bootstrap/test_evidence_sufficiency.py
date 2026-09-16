"""Tests for Bootstrap-owned evidence-sufficiency composition."""

import ast
from collections.abc import Sequence
from pathlib import Path

import pytest

from lexlocal.application.ports.local_models import (
    ChatInferenceProfile,
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
    ResolvedModelRecord,
)
from lexlocal.bootstrap import evidence_sufficiency as sufficiency_bootstrap
from lexlocal.bootstrap.evidence_sufficiency import (
    EVIDENCE_POLICY_VERSION,
    EVIDENCE_VERIFIER_CONTRACT_VERSION,
    EVIDENCE_VERIFIER_INVOCATION_PROFILE,
    compose_evidence_sufficiency_application,
)
from lexlocal.bootstrap.foundry import LocalModelComposition
from lexlocal.domain.identifiers import LocalModelId


def _status(capability: ModelCapability) -> LocalModelStatus:
    return LocalModelStatus(
        ResolvedModelRecord(
            LocalModelId(
                "10000000-0000-4000-8000-000000000001"
                if capability is ModelCapability.CHAT
                else "10000000-0000-4000-8000-000000000002"
            ),
            "synthetic-chat" if capability is ModelCapability.CHAT else "synthetic-embed",
            "synthetic:1",
            "1",
            capability,
            "local",
            None if capability is ModelCapability.CHAT else 2,
        ),
        ModelReadiness.READY,
        "SyntheticExecutionProvider",
    )


class _ChatProvider:
    def __init__(self, status: LocalModelStatus) -> None:
        self._status = status

    @property
    def status(self) -> LocalModelStatus:
        return self._status

    def generate(
        self,
        prompt: str,
        *,
        profile: ChatInferenceProfile | None = None,
    ) -> str:
        del profile
        return prompt


class _EmbeddingProvider:
    @property
    def status(self) -> LocalModelStatus:
        return _status(ModelCapability.EMBEDDING)

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return tuple((1.0, 0.0) for _ in texts)


class _Cancellation:
    def raise_if_cancelled(self) -> None:
        return None


def _local_models(provider: _ChatProvider) -> LocalModelComposition:
    return LocalModelComposition(
        provider,
        _EmbeddingProvider(),
        provider.status,
        _status(ModelCapability.EMBEDDING),
        lambda: None,
    )


def test_composition_reuses_exact_chat_provider_and_only_wires_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, tuple[object, ...]] = {}
    chat_status = _status(ModelCapability.CHAT)
    provider = _ChatProvider(chat_status)
    cancellation = _Cancellation()

    class _Verifier:
        def __init__(self, *arguments: object) -> None:
            captured["verifier"] = arguments

        @property
        def status(self) -> LocalModelStatus:
            return chat_status

    class _Evaluate:
        def __init__(self, *arguments: object) -> None:
            captured["evaluate"] = arguments

    monkeypatch.setattr(sufficiency_bootstrap, "FoundryEvidenceVerifier", _Verifier)
    monkeypatch.setattr(sufficiency_bootstrap, "EvaluateEvidenceSufficiency", _Evaluate)

    composition = compose_evidence_sufficiency_application(
        _local_models(provider),
        cancellation=cancellation,
    )

    assert captured["verifier"] == (
        provider,
        EVIDENCE_VERIFIER_CONTRACT_VERSION,
        EVIDENCE_VERIFIER_INVOCATION_PROFILE,
        cancellation,
    )
    verifier, policy, policy_cancellation = captured["evaluate"]
    assert verifier.__class__ is _Verifier
    assert policy is composition.policy
    assert policy.evidence_policy_version == EVIDENCE_POLICY_VERSION
    assert policy.verifier_contract_version == EVIDENCE_VERIFIER_CONTRACT_VERSION
    assert policy.verifier_status is chat_status
    assert EVIDENCE_VERIFIER_INVOCATION_PROFILE == ChatInferenceProfile(0.0, 0)
    assert policy_cancellation is cancellation
    assert composition.evaluate_evidence_sufficiency.__class__ is _Evaluate


def test_default_cancellation_is_composed_without_runtime_or_provider_lifecycle() -> None:
    provider = _ChatProvider(_status(ModelCapability.CHAT))
    local_models = _local_models(provider)

    composition = compose_evidence_sufficiency_application(local_models)

    assert composition.policy.verifier_status is provider.status


def test_bootstrap_module_contains_wiring_only() -> None:
    module_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "lexlocal"
        / "bootstrap"
        / "evidence_sufficiency.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert not any(
        module.startswith(
            (
                "foundry_local_sdk",
                "lexlocal.application.embeddings",
                "lexlocal.application.retrieval",
                "lexlocal.application.ports.unit_of_work",
                "lexlocal.infrastructure.persistence",
                "lexlocal.infrastructure.foundry.local_adapter",
            )
        )
        for module in imported_modules
    )
    assert called_names <= {
        "dataclass",
        "_NeverCancelled",
        "ChatInferenceProfile",
        "FoundryEvidenceVerifier",
        "EvidencePolicyIdentity",
        "EvaluateEvidenceSufficiency",
        "EvidenceSufficiencyApplicationComposition",
    }
