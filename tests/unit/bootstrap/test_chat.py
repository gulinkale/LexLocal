"""Unit tests for grounded CHAT Bootstrap composition."""

import ast
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.application.ports.evidence_sufficiency import EvidencePolicyIdentity
from lexlocal.application.ports.local_models import (
    ChatInferenceProfile,
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
    ResolvedModelRecord,
)
from lexlocal.application.ports.retrieval import RetrievalConfiguration
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.bootstrap import chat as chat_bootstrap
from lexlocal.bootstrap.chat import (
    ChatBootstrapConfigurationError,
    compose_chat_application,
)
from lexlocal.bootstrap.evidence_sufficiency import (
    EvidenceSufficiencyApplicationComposition,
)
from lexlocal.bootstrap.foundry import LocalModelComposition
from lexlocal.bootstrap.retrieval import RetrievalApplicationComposition
from lexlocal.bootstrap.security import SecurityProviderConfigurationError
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import (
    ActivityEventId,
    ChatMessageId,
    CitationId,
    LocalModelId,
)
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyPayloadCodec,
)

NOW = datetime(2026, 9, 17, 10, 0, tzinfo=UTC)


def _status(
    model_id: str = "10000000-0000-4000-8000-000000000001",
    capability: ModelCapability = ModelCapability.CHAT,
) -> LocalModelStatus:
    return LocalModelStatus(
        ResolvedModelRecord(
            LocalModelId(model_id),
            "synthetic-chat" if capability is ModelCapability.CHAT else "synthetic-embedding",
            "synthetic-chat:1" if capability is ModelCapability.CHAT else "synthetic-embedding:1",
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
        del prompt, profile
        return '{"answer":"synthetic","citations":["E1"]}'


class _EmbeddingProvider:
    @property
    def status(self) -> LocalModelStatus:
        raise AssertionError("embedding provider must not be inspected")

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        raise AssertionError("embedding provider must not run")


class _Cancellation:
    def raise_if_cancelled(self) -> None:
        return None


def _settings(tmp_path: Path, *, environment: str = "test") -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment=environment,
        log_level="INFO",
        data_dir=tmp_path,
        security_provider="insecure-development-only",
    )


def _dependencies(status: LocalModelStatus):
    provider = _ChatProvider(status)
    local_models = LocalModelComposition(
        provider,
        _EmbeddingProvider(),
        status,
        _status(
            "10000000-0000-4000-8000-000000000002",
            ModelCapability.EMBEDDING,
        ),
        lambda: None,
    )
    prepare = object()
    stage = object()
    evaluate = object()
    unit_of_work_factory = object()
    retrieval = RetrievalApplicationComposition(
        prepare,  # type: ignore[arg-type]
        stage,  # type: ignore[arg-type]
        RetrievalConfiguration(),
        unit_of_work_factory,  # type: ignore[arg-type]
    )
    sufficiency = EvidenceSufficiencyApplicationComposition(
        evaluate,  # type: ignore[arg-type]
        EvidencePolicyIdentity(
            "evidence-policy-v2",
            "evidence-relations-v2",
            status,
        ),
    )
    return provider, local_models, retrieval, sufficiency


def test_composition_reuses_exact_provider_and_wires_existing_use_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, tuple[object, ...]] = {}
    status = _status()
    provider, local_models, retrieval, sufficiency = _dependencies(status)
    scope = ActiveWorkspaceScope()
    cancellation = _Cancellation()
    answer_id = ChatMessageId("20000000-0000-4000-8000-000000000001")
    citation_id = CitationId("30000000-0000-4000-8000-000000000001")
    activity_id = ActivityEventId("40000000-0000-4000-8000-000000000001")

    class _UnitOfWork:
        def __init__(self, *arguments: object) -> None:
            captured["unit_of_work"] = arguments

    class _Complete:
        def __init__(self, *arguments: object) -> None:
            captured["complete"] = arguments

    monkeypatch.setattr(chat_bootstrap, "SQLiteUnitOfWork", _UnitOfWork)
    monkeypatch.setattr(chat_bootstrap, "CompleteChat", _Complete)

    composition = compose_chat_application(
        _settings(tmp_path),
        SQLiteConnectionFactory(tmp_path / "unused.db"),
        scope,
        local_models,
        retrieval,
        sufficiency,
        cancellation=cancellation,
        answer_message_id_factory=lambda: answer_id,
        citation_id_factory=lambda: citation_id,
        activity_event_id_factory=lambda: activity_id,
        clock=lambda: NOW,
    )

    arguments = captured["complete"]
    assert arguments[0] is scope
    assert arguments[2] is retrieval.prepare_retrieval
    assert arguments[3] is retrieval.stage_retrieval
    assert arguments[4] is sufficiency.evaluate_evidence_sufficiency
    assert arguments[5] is provider
    assert arguments[6] is status
    assert arguments[7] == "evidence-policy-v2"
    assert arguments[8] is retrieval.configuration
    assert arguments[9] is cancellation
    assert arguments[10]() == answer_id
    assert arguments[11]() == citation_id
    assert arguments[12]() == activity_id
    assert arguments[13]() == NOW
    assert composition.complete_chat.__class__ is _Complete

    composition.unit_of_work_factory()
    uow_arguments = captured["unit_of_work"]
    assert uow_arguments[0].database_path == tmp_path / "unused.db"
    assert isinstance(uow_arguments[2], InsecureDevelopmentOnlyPayloadCodec)


def test_model_substitution_fails_closed_at_composition(tmp_path: Path) -> None:
    provider, local_models, retrieval, sufficiency = _dependencies(_status())
    del provider
    mismatched = EvidenceSufficiencyApplicationComposition(
        sufficiency.evaluate_evidence_sufficiency,
        EvidencePolicyIdentity(
            "evidence-policy-v2",
            "evidence-relations-v2",
            _status("10000000-0000-4000-8000-000000000099"),
        ),
    )

    with pytest.raises(
        ChatBootstrapConfigurationError,
        match="verifier model binding is invalid",
    ):
        compose_chat_application(
            _settings(tmp_path),
            SQLiteConnectionFactory(tmp_path / "unused.db"),
            ActiveWorkspaceScope(),
            local_models,
            retrieval,
            mismatched,
        )


def test_production_fails_before_accessing_protected_or_model_dependencies(
    tmp_path: Path,
) -> None:
    class _Forbidden:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"dependency accessed: {name}")

    forbidden = _Forbidden()
    with pytest.raises(SecurityProviderConfigurationError):
        compose_chat_application(
            _settings(tmp_path, environment="production"),
            SQLiteConnectionFactory(tmp_path / "unused.db"),
            ActiveWorkspaceScope(),
            forbidden,  # type: ignore[arg-type]
            forbidden,  # type: ignore[arg-type]
            forbidden,  # type: ignore[arg-type]
        )


def test_bootstrap_module_contains_wiring_only() -> None:
    module_path = Path(__file__).resolve().parents[3] / "src" / "lexlocal" / "bootstrap" / "chat.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(
        module.startswith(
            (
                "foundry_local_sdk",
                "lexlocal.infrastructure.foundry",
                "lexlocal.infrastructure.persistence.sqlite_chat_repository",
                "lexlocal.infrastructure.persistence.sqlite_retrieval_repository",
            )
        )
        for module in imported_modules
    )
