"""Unit tests for Bootstrap-owned local-model composition and lifetime."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lexlocal.application.ports.local_models import (
    LocalModelIncompatible,
    LocalModelPersistenceError,
    LocalModelRuntimeError,
    LocalModelStatus,
    LocalModelUnavailable,
    ModelCapability,
    ModelReadiness,
    ResolvedModelRecord,
)
from lexlocal.bootstrap import foundry as foundry_bootstrap
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import LocalModelId

CHAT_ID = LocalModelId("550e8400-e29b-41d4-a716-446655440000")
EMBEDDING_ID = LocalModelId("123e4567-e89b-12d3-a456-426614174000")
STORED_CHAT_ID = LocalModelId("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def settings() -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment="test",
        log_level="INFO",
        data_dir=Path("synthetic-data"),
        security_provider="insecure-development-only",
        chat_model_alias="configured-chat",
        embedding_model_alias="configured-embedding",
    )


def record(
    model_id: LocalModelId,
    alias: str,
    capability: ModelCapability,
) -> ResolvedModelRecord:
    return ResolvedModelRecord(
        id=model_id,
        requested_alias=alias,
        resolved_model_id=f"{alias}:1",
        model_version="1",
        capability=capability,
        provider="FoundryLocal",
        dimensions=384 if capability is ModelCapability.EMBEDDING else None,
    )


class FakeRuntime:
    def __init__(
        self,
        *,
        failure_by_capability: dict[ModelCapability, Exception] | None = None,
        close_error: Exception | None = None,
    ) -> None:
        self.failure_by_capability = failure_by_capability or {}
        self.close_error = close_error
        self.resolve_calls: list[tuple[LocalModelId, str, ModelCapability]] = []
        self.close_calls = 0

    def resolve_ready(
        self,
        *,
        model_id: LocalModelId,
        requested_alias: str,
        capability: ModelCapability,
    ) -> LocalModelStatus:
        self.resolve_calls.append((model_id, requested_alias, capability))
        failure = self.failure_by_capability.get(capability)
        if failure is not None:
            raise failure
        return LocalModelStatus(
            model=record(model_id, requested_alias, capability),
            readiness=ModelReadiness.READY,
            execution_provider="LocalExecutionProvider",
        )

    def adopt_persisted_record(
        self,
        status: LocalModelStatus,
        persisted: ResolvedModelRecord,
    ) -> LocalModelStatus:
        return LocalModelStatus(
            model=persisted,
            readiness=status.readiness,
            execution_provider=status.execution_provider,
        )

    def chat_provider(self, status: LocalModelStatus) -> object:
        return SimpleNamespace(status=status, generate=lambda _prompt: "synthetic")

    def embedding_provider(self, status: LocalModelStatus) -> object:
        return SimpleNamespace(status=status, embed=lambda _texts: [[1.0]])

    def close(self) -> None:
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


class FakeRepository:
    def __init__(
        self,
        *,
        replacements: dict[ModelCapability, ResolvedModelRecord] | None = None,
        failure_on: ModelCapability | None = None,
    ) -> None:
        self.replacements = replacements or {}
        self.failure_on = failure_on
        self.records: list[ResolvedModelRecord] = []

    def get_or_add_exact(self, model: ResolvedModelRecord) -> ResolvedModelRecord:
        self.records.append(model)
        if model.capability is self.failure_on:
            raise LocalModelPersistenceError("persistence failed")
        return self.replacements.get(model.capability, model)


class FakeUnitOfWork:
    def __init__(self, repository: FakeRepository) -> None:
        self.local_models = repository
        self.commit_calls = 0

    def __enter__(self) -> FakeUnitOfWork:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def commit(self) -> None:
        self.commit_calls += 1


def install_unit_of_work(
    monkeypatch: pytest.MonkeyPatch,
    repository: FakeRepository,
) -> FakeUnitOfWork:
    unit_of_work = FakeUnitOfWork(repository)
    constructor = Mock(return_value=unit_of_work)
    monkeypatch.setattr(foundry_bootstrap, "SQLiteUnitOfWork", constructor)
    return unit_of_work


def model_id_factory() -> Callable[[], LocalModelId]:
    model_ids = iter((CHAT_ID, EMBEDDING_ID))
    return lambda: next(model_ids)


def test_success_composes_one_runtime_exact_aliases_and_atomic_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = FakeRuntime()
    runtime_factory = Mock(return_value=runtime)
    repository = FakeRepository()
    unit_of_work = install_unit_of_work(monkeypatch, repository)

    composition = foundry_bootstrap.compose_local_models(
        settings(),
        Mock(),
        runtime_factory=runtime_factory,
        model_id_factory=model_id_factory(),
    )

    assert runtime.resolve_calls == [
        (CHAT_ID, "configured-chat", ModelCapability.CHAT),
        (EMBEDDING_ID, "configured-embedding", ModelCapability.EMBEDDING),
    ]
    assert [item.capability for item in repository.records] == [
        ModelCapability.CHAT,
        ModelCapability.EMBEDDING,
    ]
    assert composition.chat.status == composition.chat_status
    assert composition.embedding.status == composition.embedding_status
    assert unit_of_work.commit_calls == 1
    runtime_factory.assert_called_once_with()
    assert runtime.close_calls == 0

    composition.close()
    assert runtime.close_calls == 1


def test_existing_record_reuse_publishes_persisted_stable_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = FakeRuntime()
    persisted_chat = record(
        STORED_CHAT_ID,
        "configured-chat",
        ModelCapability.CHAT,
    )
    repository = FakeRepository(
        replacements={ModelCapability.CHAT: persisted_chat}
    )
    install_unit_of_work(monkeypatch, repository)

    composition = foundry_bootstrap.compose_local_models(
        settings(),
        Mock(),
        runtime_factory=lambda: runtime,
        model_id_factory=model_id_factory(),
    )

    assert composition.chat_status.model.id == STORED_CHAT_ID
    assert composition.chat.status.model.id == STORED_CHAT_ID


@pytest.mark.parametrize(
    "failure",
    [
        LocalModelUnavailable("unavailable"),
        LocalModelIncompatible("incompatible"),
        LocalModelRuntimeError("load failed"),
        LocalModelRuntimeError("health failed"),
    ],
)
def test_second_model_failure_closes_without_persistence_or_fallback(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    runtime = FakeRuntime(
        failure_by_capability={ModelCapability.EMBEDDING: failure}
    )
    constructor = Mock()
    monkeypatch.setattr(foundry_bootstrap, "SQLiteUnitOfWork", constructor)

    with pytest.raises(type(failure)):
        foundry_bootstrap.compose_local_models(
            settings(),
            Mock(),
            runtime_factory=lambda: runtime,
            model_id_factory=model_id_factory(),
        )

    assert [call[1] for call in runtime.resolve_calls] == [
        "configured-chat",
        "configured-embedding",
    ]
    constructor.assert_not_called()
    assert runtime.close_calls == 1


def test_persistence_failure_does_not_commit_and_closes_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = FakeRuntime()
    repository = FakeRepository(
        failure_on=ModelCapability.EMBEDDING
    )
    unit_of_work = install_unit_of_work(monkeypatch, repository)

    with pytest.raises(LocalModelPersistenceError):
        foundry_bootstrap.compose_local_models(
            settings(),
            Mock(),
            runtime_factory=lambda: runtime,
            model_id_factory=model_id_factory(),
        )

    assert unit_of_work.commit_calls == 0
    assert [item.capability for item in repository.records] == [
        ModelCapability.CHAT,
        ModelCapability.EMBEDDING,
    ]
    assert runtime.close_calls == 1


def test_cleanup_failure_does_not_replace_primary_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = LocalModelUnavailable("primary failure")
    runtime = FakeRuntime(
        failure_by_capability={ModelCapability.CHAT: primary},
        close_error=LocalModelRuntimeError("cleanup failure"),
    )

    with pytest.raises(LocalModelUnavailable, match="primary failure"):
        foundry_bootstrap.compose_local_models(
            settings(),
            Mock(),
            runtime_factory=lambda: runtime,
            model_id_factory=model_id_factory(),
        )

    assert runtime.close_calls == 1
