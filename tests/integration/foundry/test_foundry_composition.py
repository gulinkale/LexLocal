"""Integration tests for real Foundry runtime and SQLite composition boundaries."""

from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace

import pytest

from lexlocal.application.ports.local_models import LocalModelIncompatible
from lexlocal.bootstrap.foundry import compose_local_models
from lexlocal.bootstrap.persistence import initialize_persistence
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.infrastructure.foundry.local_adapter import FoundryLocalRuntime


class ChatClient:
    def complete_streaming_chat(
        self,
        _messages: list[dict[str, str]],
    ) -> Iterable[object]:
        return [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="ready"))]
            )
        ]


class EmbeddingClient:
    def __init__(self, vector: list[float]) -> None:
        self.vector = vector

    def generate_embeddings(self, _texts: list[str]) -> object:
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=self.vector)]
        )


class Model:
    def __init__(self, alias: str, client: object) -> None:
        self.alias = alias
        self.id = f"{alias}:1"
        self.info = SimpleNamespace(
            version=1,
            provider_type="FoundryLocal",
            runtime=SimpleNamespace(execution_provider="LocalExecutionProvider"),
        )
        self.is_cached = True
        self.client = client
        self.load_calls = 0
        self.unload_calls = 0

    def load(self) -> None:
        self.load_calls += 1

    def unload(self) -> None:
        self.unload_calls += 1

    def get_chat_client(self) -> object:
        if not isinstance(self.client, ChatClient):
            raise RuntimeError("incompatible client")
        return self.client

    def get_embedding_client(self) -> object:
        if not isinstance(self.client, EmbeddingClient):
            raise RuntimeError("incompatible client")
        return self.client


class Catalog:
    def __init__(self, models: dict[str, Model]) -> None:
        self.models = models
        self.aliases: list[str] = []

    def get_model(self, alias: str) -> Model | None:
        self.aliases.append(alias)
        return self.models.get(alias)


class Manager:
    def __init__(self, models: dict[str, Model]) -> None:
        self.catalog = Catalog(models)

    def download_and_register_eps(self) -> None:
        raise AssertionError("composition attempted online preparation")


def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment="test",
        log_level="INFO",
        data_dir=tmp_path,
        security_provider="insecure-development-only",
        chat_model_alias="integration-chat",
        embedding_model_alias="integration-embedding",
    )


def runtime_with_models(
    *,
    embedding_vector: list[float] | None = None,
) -> tuple[FoundryLocalRuntime, Manager]:
    manager = Manager(
        {
            "integration-chat": Model("integration-chat", ChatClient()),
            "integration-embedding": Model(
                "integration-embedding",
                EmbeddingClient(
                    [1.0, 2.0, 3.0]
                    if embedding_vector is None
                    else embedding_vector
                ),
            ),
        }
    )
    return FoundryLocalRuntime(manager), manager


def persisted_rows(tmp_path: Path) -> list[tuple[str, str, str]]:
    factory = initialize_persistence(settings(tmp_path))
    connection = factory.create()
    try:
        rows = connection.execute(
            """
            SELECT id, requested_alias, purpose
            FROM local_models
            ORDER BY purpose
            """
        ).fetchall()
    finally:
        connection.close()
    return [(str(row[0]), str(row[1]), str(row[2])) for row in rows]


def test_real_runtime_and_uow_compose_both_exact_identities_atomically(
    tmp_path: Path,
) -> None:
    app_settings = settings(tmp_path)
    factory = initialize_persistence(app_settings)
    runtime, manager = runtime_with_models()

    composition = compose_local_models(
        app_settings,
        factory,
        runtime_factory=lambda: runtime,
    )

    assert manager.catalog.aliases == [
        "integration-chat",
        "integration-embedding",
    ]
    assert composition.chat.status == composition.chat_status
    assert composition.embedding.status == composition.embedding_status
    assert composition.chat_status.model.dimensions is None
    assert composition.embedding_status.model.dimensions == 3
    rows = persisted_rows(tmp_path)
    assert [(row[1], row[2]) for row in rows] == [
        ("integration-chat", "CHAT"),
        ("integration-embedding", "EMBEDDING"),
    ]
    composition.close()


def test_second_composition_reuses_both_persisted_stable_ids(tmp_path: Path) -> None:
    app_settings = settings(tmp_path)
    factory = initialize_persistence(app_settings)
    first_runtime, _ = runtime_with_models()
    first = compose_local_models(
        app_settings,
        factory,
        runtime_factory=lambda: first_runtime,
    )
    first_ids = {
        first.chat_status.model.id,
        first.embedding_status.model.id,
    }
    first.close()

    second_runtime, _ = runtime_with_models()
    second = compose_local_models(
        app_settings,
        factory,
        runtime_factory=lambda: second_runtime,
    )

    assert {
        second.chat_status.model.id,
        second.embedding_status.model.id,
    } == first_ids
    assert len(persisted_rows(tmp_path)) == 2
    second.close()


def test_invalid_second_model_persists_no_partial_chat_identity(
    tmp_path: Path,
) -> None:
    app_settings = settings(tmp_path)
    factory = initialize_persistence(app_settings)
    runtime, manager = runtime_with_models(embedding_vector=[])

    with pytest.raises(LocalModelIncompatible):
        compose_local_models(
            app_settings,
            factory,
            runtime_factory=lambda: runtime,
        )

    assert manager.catalog.aliases == [
        "integration-chat",
        "integration-embedding",
    ]
    assert persisted_rows(tmp_path) == []
