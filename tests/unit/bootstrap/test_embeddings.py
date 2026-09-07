"""Unit tests for Bootstrap-owned embedding composition."""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.application.ports.local_models import (
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
    ResolvedModelRecord,
)
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.bootstrap import embeddings as embeddings_bootstrap
from lexlocal.bootstrap.embeddings import compose_embedding_application
from lexlocal.bootstrap.foundry import LocalModelComposition
from lexlocal.bootstrap.security import SecurityProviderConfigurationError
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import LocalModelId
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyPayloadCodec,
)

NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
EMBEDDING_MODEL = ResolvedModelRecord(
    LocalModelId("10000000-0000-4000-8000-000000000001"),
    "qwen3-embedding-0.6b",
    "synthetic-embedding",
    "1",
    ModelCapability.EMBEDDING,
    "synthetic-local",
    2,
)
CHAT_MODEL = ResolvedModelRecord(
    LocalModelId("10000000-0000-4000-8000-000000000002"),
    "qwen3-4b",
    "synthetic-chat",
    "1",
    ModelCapability.CHAT,
    "synthetic-local",
)


class _EmbeddingProvider:
    @property
    def status(self) -> LocalModelStatus:
        return LocalModelStatus(
            EMBEDDING_MODEL,
            ModelReadiness.READY,
            "synthetic-execution",
        )

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return tuple((1.0, 0.0) for _ in texts)


class _ChatProvider:
    @property
    def status(self) -> LocalModelStatus:
        return LocalModelStatus(CHAT_MODEL, ModelReadiness.READY, "synthetic-execution")

    def generate(self, prompt: str) -> str:
        return "synthetic"


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
        embedding_batch_size=7,
    )


def _local_models(provider: _EmbeddingProvider) -> LocalModelComposition:
    return LocalModelComposition(
        _ChatProvider(),
        provider,
        _ChatProvider().status,
        provider.status,
        lambda: None,
    )


def test_composition_reuses_exact_provider_and_wires_existing_finalizer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, tuple[object, ...]] = {}
    provider = _EmbeddingProvider()
    scope = ActiveWorkspaceScope()
    cancellation = _Cancellation()

    class _UnitOfWork:
        def __init__(self, *arguments: object) -> None:
            captured["unit_of_work"] = arguments

    class _Finalizer:
        def __init__(self, *arguments: object) -> None:
            captured["finalizer"] = arguments

    class _EmbedStaging:
        def __init__(self, *arguments: object) -> None:
            captured["staging"] = arguments

    class _EmbedQuery:
        def __init__(self, *arguments: object) -> None:
            captured["query"] = arguments

    monkeypatch.setattr(embeddings_bootstrap, "SQLiteUnitOfWork", _UnitOfWork)
    monkeypatch.setattr(embeddings_bootstrap, "FinalizeIndexing", _Finalizer)
    monkeypatch.setattr(embeddings_bootstrap, "EmbedStagingChunks", _EmbedStaging)
    monkeypatch.setattr(embeddings_bootstrap, "EmbedQuery", _EmbedQuery)

    composition = compose_embedding_application(
        _settings(tmp_path),
        SQLiteConnectionFactory(tmp_path / "unused.db"),
        scope,
        _local_models(provider),
        cancellation=cancellation,
        clock=lambda: NOW,
    )

    staging = captured["staging"]
    finalizer = captured["finalizer"]
    query = captured["query"]
    assert staging[0] is scope
    assert staging[1] is provider
    assert staging[2] is cancellation
    assert staging[3] is finalizer[2]
    assert staging[4].__class__ is _Finalizer
    assert staging[5]() == NOW
    assert staging[6] == 7
    assert finalizer[0] is scope
    assert finalizer[1] is cancellation
    assert finalizer[2] is staging[3]
    assert finalizer[3]() == NOW
    assert query == (scope, provider)
    assert composition.embed_staging_chunks.__class__ is _EmbedStaging
    assert composition.embed_query.__class__ is _EmbedQuery

    unit_of_work_factory = staging[3]
    unit_of_work_factory()
    arguments = captured["unit_of_work"]
    assert arguments[0].database_path == tmp_path / "unused.db"
    assert isinstance(arguments[2], InsecureDevelopmentOnlyPayloadCodec)


def test_production_rejects_insecure_composition_before_provider_access(
    tmp_path: Path,
) -> None:
    with pytest.raises(SecurityProviderConfigurationError):
        compose_embedding_application(
            _settings(tmp_path, environment="production"),
            SQLiteConnectionFactory(tmp_path / "unused.db"),
            ActiveWorkspaceScope(),
            None,  # type: ignore[arg-type]
        )
