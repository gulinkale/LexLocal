"""Tests for the cached-only Foundry Local Infrastructure adapter."""

from __future__ import annotations

import math
import sys
from collections.abc import Iterable
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lexlocal.application.ports.local_models import (
    ChatInferenceProfile,
    EmbeddingProvider,
    LocalModelIncompatible,
    LocalModelInferenceError,
    LocalModelRuntimeError,
    LocalModelStatus,
    LocalModelUnavailable,
    ModelCapability,
    ModelReadiness,
)
from lexlocal.domain.identifiers import LocalModelId
from lexlocal.infrastructure.foundry.local_adapter import (
    FoundryLocalAdapter,
    FoundryLocalRuntime,
)

CHAT_ID = LocalModelId("550e8400-e29b-41d4-a716-446655440000")
EMBEDDING_ID = LocalModelId("123e4567-e89b-12d3-a456-426614174000")


def chunk(content: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
    )


def embedding_response(*vectors: object) -> SimpleNamespace:
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=vector) for vector in vectors]
    )


class FakeChatClient:
    def __init__(
        self,
        chunks: Iterable[object] = (),
        error: Exception | None = None,
    ) -> None:
        self.chunks = chunks
        self.error = error
        self.messages: list[list[dict[str, str]]] = []
        self.settings = SimpleNamespace(temperature=None, random_seed=None)
        self.observed_settings: list[tuple[object, object]] = []

    def complete_streaming_chat(
        self,
        messages: list[dict[str, str]],
    ) -> Iterable[object]:
        self.messages.append(messages)
        self.observed_settings.append(
            (self.settings.temperature, self.settings.random_seed)
        )
        if self.error is not None:
            raise self.error
        return self.chunks


class FakeEmbeddingClient:
    def __init__(self, response: object, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.inputs: list[list[str]] = []

    def generate_embeddings(self, inputs: list[str]) -> object:
        self.inputs.append(inputs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeModel:
    def __init__(
        self,
        *,
        chat_client: object | None = None,
        embedding_client: object | None = None,
        alias: str | None = None,
        cached: bool = True,
        load_error: Exception | None = None,
        unload_error: Exception | None = None,
    ) -> None:
        self.id = "resolved-model:7"
        self.alias = alias
        self.info = SimpleNamespace(
            version=7,
            provider_type="FoundryLocal",
            runtime=SimpleNamespace(execution_provider="LocalExecutionProvider"),
        )
        self.is_cached = cached
        self.chat_client = chat_client
        self.embedding_client = embedding_client
        self.load_error = load_error
        self.unload_error = unload_error
        self.load_calls = 0
        self.unload_calls = 0
        self.download_calls = 0

    def download(self) -> None:
        self.download_calls += 1

    def load(self) -> None:
        self.load_calls += 1
        if self.load_error is not None:
            raise self.load_error

    def unload(self) -> None:
        self.unload_calls += 1
        if self.unload_error is not None:
            raise self.unload_error

    def get_chat_client(self) -> object:
        if self.chat_client is None:
            raise RuntimeError("native client detail")
        return self.chat_client

    def get_embedding_client(self) -> object:
        if self.embedding_client is None:
            raise RuntimeError("native client detail")
        return self.embedding_client


class FakeCatalog:
    def __init__(self, models: dict[str, FakeModel]) -> None:
        self.models = models
        self.requested_aliases: list[str] = []

    def get_model(self, alias: str) -> FakeModel | None:
        self.requested_aliases.append(alias)
        model = self.models.get(alias)
        if model is not None and model.alias is None:
            model.alias = alias
        return model


class FakeManager:
    def __init__(
        self,
        models: dict[str, FakeModel],
        *,
        allow_preparation: bool = False,
    ) -> None:
        self.catalog = FakeCatalog(models)
        self.allow_preparation = allow_preparation
        self.preparation_calls = 0

    def download_and_register_eps(self) -> None:
        if not self.allow_preparation:
            raise AssertionError("normal runtime attempted online preparation")
        self.preparation_calls += 1


def resolve_chat(model: FakeModel) -> tuple[FoundryLocalRuntime, LocalModelStatus]:
    runtime = FoundryLocalRuntime(FakeManager({"exact-chat": model}))
    status = runtime.resolve_ready(
        model_id=CHAT_ID,
        requested_alias="exact-chat",
        capability=ModelCapability.CHAT,
    )
    return runtime, status


def resolve_embedding(
    model: FakeModel,
) -> tuple[FoundryLocalRuntime, LocalModelStatus]:
    runtime = FoundryLocalRuntime(FakeManager({"exact-embedding": model}))
    status = runtime.resolve_ready(
        model_id=EMBEDDING_ID,
        requested_alias="exact-embedding",
        capability=ModelCapability.EMBEDDING,
    )
    return runtime, status


def test_initialize_configures_sdk_once(monkeypatch: pytest.MonkeyPatch) -> None:
    manager_type = SimpleNamespace(initialize=Mock(), instance=FakeManager({}))
    configuration = Mock(return_value="configuration")
    fake_sdk = SimpleNamespace(
        Configuration=configuration,
        FoundryLocalManager=manager_type,
    )
    monkeypatch.setitem(sys.modules, "foundry_local_sdk", fake_sdk)

    runtime = FoundryLocalRuntime.initialize(app_name="synthetic-app")

    configuration.assert_called_once_with(app_name="synthetic-app")
    manager_type.initialize.assert_called_once_with("configuration")
    assert isinstance(runtime, FoundryLocalRuntime)


def test_initialize_failure_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    initialize = Mock(side_effect=RuntimeError("native cache path"))
    fake_sdk = SimpleNamespace(
        Configuration=Mock(return_value="configuration"),
        FoundryLocalManager=SimpleNamespace(initialize=initialize, instance=None),
    )
    monkeypatch.setitem(sys.modules, "foundry_local_sdk", fake_sdk)

    with pytest.raises(
        LocalModelRuntimeError,
        match="local model runtime initialization failed",
    ) as captured:
        FoundryLocalRuntime.initialize()

    assert captured.value.__cause__ is None


def test_exact_chat_resolution_health_and_safe_metadata() -> None:
    client = FakeChatClient([chunk("ready")])
    model = FakeModel(chat_client=client)
    manager = FakeManager({"exact-chat": model})
    runtime = FoundryLocalRuntime(manager)

    status = runtime.resolve_ready(
        model_id=CHAT_ID,
        requested_alias="exact-chat",
        capability=ModelCapability.CHAT,
    )

    assert manager.catalog.requested_aliases == ["exact-chat"]
    assert status.model.id == CHAT_ID
    assert status.model.requested_alias == "exact-chat"
    assert status.model.resolved_model_id == "resolved-model:7"
    assert status.model.model_version == "7"
    assert status.model.provider == "FoundryLocal"
    assert status.model.dimensions is None
    assert status.readiness is ModelReadiness.READY
    assert status.execution_provider == "LocalExecutionProvider"
    assert model.load_calls == model.unload_calls == 1


def test_embedding_health_captures_dimension_and_inference_reuses_handle() -> None:
    client = FakeEmbeddingClient(embedding_response([1, 2.5, -3]))
    model = FakeModel(embedding_client=client)
    runtime, status = resolve_embedding(model)
    provider = runtime.embedding_provider(status)

    first = provider.embed(["synthetic one"])
    second = provider.embed(["synthetic two"])

    assert status.model.dimensions == 3
    assert first == second == [[1.0, 2.5, -3.0]]
    assert model.load_calls == 2
    assert model.unload_calls == 1
    runtime.close()
    assert model.unload_calls == 2


def test_embedding_multi_input_preserves_positional_mapping_and_sdk_free_values() -> None:
    client = FakeEmbeddingClient(embedding_response([1.0, 0.0, 0.0]))
    model = FakeModel(embedding_client=client)
    runtime, status = resolve_embedding(model)
    provider: EmbeddingProvider = runtime.embedding_provider(status)
    client.response = embedding_response([3, 0, 4], [-1.0, 2.5, 0.0])

    vectors = provider.embed(["synthetic first", "synthetic second"])

    assert provider.status is status
    assert status.readiness is ModelReadiness.READY
    assert status.model.capability is ModelCapability.EMBEDDING
    assert status.model.id == EMBEDDING_ID
    assert status.model.dimensions == 3
    assert client.inputs[-1] == ["synthetic first", "synthetic second"]
    assert vectors == [[3.0, 0.0, 4.0], [-1.0, 2.5, 0.0]]
    assert all(isinstance(vector, list) for vector in vectors)
    assert all(type(value) is float for vector in vectors for value in vector)


@pytest.mark.parametrize(
    "response",
    [
        embedding_response([1.0, 2.0]),
        embedding_response([1.0, 2.0], [3.0, 4.0], [5.0, 6.0]),
    ],
)
def test_embedding_inference_rejects_missing_or_extra_positional_outputs(
    response: object,
) -> None:
    client = FakeEmbeddingClient(embedding_response([1.0, 2.0]))
    model = FakeModel(embedding_client=client)
    runtime, status = resolve_embedding(model)
    client.response = response

    with pytest.raises(LocalModelInferenceError) as captured:
        runtime.embedding_provider(status).embed(["synthetic first", "synthetic second"])

    assert str(captured.value) == "local embedding inference failed"
    assert captured.value.__cause__ is None
    assert model.unload_calls == 2


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(data=[SimpleNamespace()]),
        embedding_response([True, 1.0]),
        embedding_response([object(), 1.0]),
        embedding_response([math.nan, 1.0]),
        embedding_response([math.inf, 1.0]),
        embedding_response([-math.inf, 1.0]),
    ],
)
def test_embedding_inference_rejects_malformed_values_with_sanitized_failure(
    response: object,
) -> None:
    client = FakeEmbeddingClient(embedding_response([1.0, 2.0]))
    model = FakeModel(embedding_client=client)
    runtime, status = resolve_embedding(model)
    client.response = response

    with pytest.raises(LocalModelInferenceError) as captured:
        runtime.embedding_provider(status).embed(["anonymous synthetic input"])

    assert str(captured.value) == "local embedding inference failed"
    assert captured.value.__cause__ is None
    assert model.unload_calls == 2


def test_embedding_provider_rejects_status_not_exactly_bound_to_runtime() -> None:
    client = FakeEmbeddingClient(embedding_response([1.0, 2.0]))
    model = FakeModel(embedding_client=client)
    runtime, status = resolve_embedding(model)
    forged_status = LocalModelStatus(
        model=status.model,
        readiness=ModelReadiness.READY,
        execution_provider="DifferentExecutionProvider",
    )

    with pytest.raises(LocalModelRuntimeError, match="status is not resolved") as captured:
        runtime.embedding_provider(forged_status)

    assert captured.value.__cause__ is None
    assert model.load_calls == model.unload_calls == 1


def test_embedding_runtime_failure_is_sanitized_and_unloads() -> None:
    client = FakeEmbeddingClient(embedding_response([1.0, 2.0]))
    model = FakeModel(embedding_client=client)
    runtime, status = resolve_embedding(model)
    client.error = RuntimeError("native vector, cache path, and provider detail")

    with pytest.raises(LocalModelInferenceError) as captured:
        runtime.embedding_provider(status).embed(["private synthetic input"])

    assert str(captured.value) == "local embedding inference failed"
    assert captured.value.__cause__ is None
    assert model.unload_calls == 2


def test_chat_inference_returns_sdk_free_text_and_reuses_loaded_handle() -> None:
    client = FakeChatClient([chunk("synthetic answer")])
    model = FakeModel(chat_client=client)
    manager = FakeManager({"exact-chat": model})
    runtime = FoundryLocalRuntime(manager)
    status = runtime.resolve_ready(
        model_id=CHAT_ID,
        requested_alias="exact-chat",
        capability=ModelCapability.CHAT,
    )
    provider = runtime.chat_provider(status)

    assert provider.generate("anonymous prompt") == "synthetic answer"
    assert provider.generate("second anonymous prompt") == "synthetic answer"
    assert model.load_calls == 2
    assert manager.catalog.requested_aliases == ["exact-chat"]
    runtime.close()
    assert model.unload_calls == 2


def test_chat_inference_preserves_ordinary_response_bytes() -> None:
    client = FakeChatClient([chunk("  synthetic"), chunk(" answer\n")])
    model = FakeModel(chat_client=client)
    runtime, status = resolve_chat(model)

    result = runtime.chat_provider(status).generate("anonymous prompt")

    assert result == "  synthetic answer\n"
    assert client.observed_settings[-1] == (None, None)


def test_chat_inference_applies_and_restores_exact_call_profile() -> None:
    client = FakeChatClient([chunk("synthetic answer")])
    model = FakeModel(chat_client=client)
    runtime, status = resolve_chat(model)
    profile = ChatInferenceProfile(temperature=0.0, random_seed=0)

    result = runtime.chat_provider(status).generate(
        "anonymous prompt",
        profile=profile,
    )

    assert result == "synthetic answer"
    assert client.observed_settings[-1] == (0.0, 0)
    assert client.settings.temperature is None
    assert client.settings.random_seed is None


def test_chat_inference_returns_only_content_after_one_reasoning_envelope() -> None:
    client = FakeChatClient(
        [
            chunk("<thi"),
            chunk("nk>anonymous synthetic reasoning"),
            chunk("</think>\n\n"),
            chunk('{"answer":"synthetic"}'),
        ]
    )
    model = FakeModel(chat_client=client)
    runtime, status = resolve_chat(model)

    result = runtime.chat_provider(status).generate("anonymous prompt")

    assert result == '\n\n{"answer":"synthetic"}'


@pytest.mark.parametrize(
    "response",
    [
        "<think>unterminated synthetic reasoning",
        "<think>synthetic reasoning</think>   ",
        "prefix<think>synthetic reasoning</think>final",
        "<thinking>synthetic reasoning</thinking>final",
        "<think>one</think><think>two</think>final",
        "<think>synthetic reasoning</think>final</think>",
    ],
)
def test_chat_inference_rejects_malformed_or_ambiguous_reasoning_envelope(
    response: str,
) -> None:
    client = FakeChatClient([chunk(response)])
    model = FakeModel(chat_client=client)
    runtime, status = resolve_chat(model)

    with pytest.raises(LocalModelInferenceError) as captured:
        runtime.chat_provider(status).generate("anonymous prompt")

    assert str(captured.value) == "local chat inference failed"
    assert captured.value.__cause__ is None
    assert response not in str(captured.value)
    assert model.unload_calls == 2


@pytest.mark.parametrize("alias", ["missing", "alternate"])
def test_missing_alias_fails_without_alternate_lookup(alias: str) -> None:
    manager = FakeManager({})
    runtime = FoundryLocalRuntime(manager)

    with pytest.raises(LocalModelUnavailable) as captured:
        runtime.resolve_ready(
            model_id=CHAT_ID,
            requested_alias=alias,
            capability=ModelCapability.CHAT,
        )

    assert manager.catalog.requested_aliases == [alias]
    assert captured.value.__cause__ is None


def test_uncached_model_fails_before_load() -> None:
    model = FakeModel(chat_client=FakeChatClient([chunk("unused")]), cached=False)

    with pytest.raises(LocalModelUnavailable):
        resolve_chat(model)

    assert model.load_calls == 0


def test_catalog_result_with_different_alias_is_rejected() -> None:
    model = FakeModel(
        chat_client=FakeChatClient([chunk("unused")]),
        alias="substituted-alias",
    )

    with pytest.raises(LocalModelUnavailable):
        resolve_chat(model)

    assert model.load_calls == 0


@pytest.mark.parametrize(
    "model",
    [
        FakeModel(chat_client=None),
        FakeModel(chat_client=FakeChatClient([])),
        FakeModel(chat_client=FakeChatClient([chunk("  ")])),
    ],
)
def test_incompatible_chat_health_fails_and_unloads(model: FakeModel) -> None:
    with pytest.raises(LocalModelIncompatible) as captured:
        resolve_chat(model)

    assert model.unload_calls == 1
    assert captured.value.__cause__ is None


@pytest.mark.parametrize(
    "response",
    [
        embedding_response(),
        embedding_response([]),
        embedding_response([math.nan]),
        embedding_response([math.inf]),
        embedding_response([True]),
    ],
)
def test_invalid_embedding_health_fails_closed(response: object) -> None:
    model = FakeModel(embedding_client=FakeEmbeddingClient(response))

    with pytest.raises(LocalModelIncompatible):
        resolve_embedding(model)

    assert model.unload_calls == 1


def test_wrong_embedding_dimension_fails_and_unloads_loaded_handle() -> None:
    client = FakeEmbeddingClient(embedding_response([1.0, 2.0]))
    model = FakeModel(embedding_client=client)
    runtime, status = resolve_embedding(model)
    client.response = embedding_response([1.0])

    with pytest.raises(LocalModelInferenceError):
        runtime.embedding_provider(status).embed(["synthetic"])

    assert model.unload_calls == 2


def test_load_failure_is_sanitized() -> None:
    model = FakeModel(
        chat_client=FakeChatClient([chunk("unused")]),
        load_error=RuntimeError("native path and URI"),
    )

    with pytest.raises(LocalModelRuntimeError) as captured:
        resolve_chat(model)

    assert "native" not in str(captured.value)
    assert captured.value.__cause__ is None


def test_inference_failure_is_sanitized_and_unloads() -> None:
    client = FakeChatClient([chunk("ready")])
    model = FakeModel(chat_client=client)
    runtime, status = resolve_chat(model)
    client.error = RuntimeError("prompt content and native cache path")

    with pytest.raises(LocalModelInferenceError) as captured:
        runtime.chat_provider(status).generate("private fixture")

    assert str(captured.value) == "local chat inference failed"
    assert captured.value.__cause__ is None
    assert model.unload_calls == 2


def test_primary_health_failure_wins_over_cleanup_failure() -> None:
    model = FakeModel(
        chat_client=FakeChatClient([]),
        unload_error=RuntimeError("cleanup detail"),
    )

    with pytest.raises(LocalModelIncompatible):
        resolve_chat(model)


def test_successful_health_with_cleanup_failure_reports_runtime_error() -> None:
    model = FakeModel(
        chat_client=FakeChatClient([chunk("ready")]),
        unload_error=RuntimeError("cleanup detail"),
    )

    with pytest.raises(LocalModelRuntimeError, match="cleanup failed") as captured:
        resolve_chat(model)

    assert captured.value.__cause__ is None


def test_close_is_idempotent_and_attempts_every_loaded_handle() -> None:
    chat = FakeModel(chat_client=FakeChatClient([chunk("ready")]))
    embedding = FakeModel(
        embedding_client=FakeEmbeddingClient(embedding_response([1.0]))
    )
    runtime = FoundryLocalRuntime(
        FakeManager({"chat": chat, "embedding": embedding})
    )
    chat_status = runtime.resolve_ready(
        model_id=CHAT_ID,
        requested_alias="chat",
        capability=ModelCapability.CHAT,
    )
    embedding_status = runtime.resolve_ready(
        model_id=EMBEDDING_ID,
        requested_alias="embedding",
        capability=ModelCapability.EMBEDDING,
    )
    runtime.chat_provider(chat_status).generate("synthetic")
    runtime.embedding_provider(embedding_status).embed(["synthetic"])

    runtime.close()
    runtime.close()

    assert chat.unload_calls == 2
    assert embedding.unload_calls == 2


def test_close_attempts_all_handles_when_one_cleanup_fails() -> None:
    chat = FakeModel(chat_client=FakeChatClient([chunk("ready")]))
    embedding = FakeModel(
        embedding_client=FakeEmbeddingClient(embedding_response([1.0]))
    )
    runtime = FoundryLocalRuntime(
        FakeManager({"chat": chat, "embedding": embedding})
    )
    chat_status = runtime.resolve_ready(
        model_id=CHAT_ID,
        requested_alias="chat",
        capability=ModelCapability.CHAT,
    )
    embedding_status = runtime.resolve_ready(
        model_id=EMBEDDING_ID,
        requested_alias="embedding",
        capability=ModelCapability.EMBEDDING,
    )
    runtime.chat_provider(chat_status).generate("synthetic")
    runtime.embedding_provider(embedding_status).embed(["synthetic"])
    chat.unload_error = RuntimeError("native cleanup detail")

    with pytest.raises(LocalModelRuntimeError, match="cleanup failed"):
        runtime.close()

    assert chat.unload_calls == 2
    assert embedding.unload_calls == 2


@pytest.mark.parametrize("cached_only", [False, True])
def test_operator_adapter_preserves_explicit_preparation_modes(
    cached_only: bool,
) -> None:
    model = FakeModel(chat_client=FakeChatClient([chunk("synthetic result")]))
    manager = FakeManager({"operator-model": model}, allow_preparation=True)

    result = FoundryLocalAdapter(manager).infer(
        model_alias="operator-model",
        prompt="anonymous operator fixture",
        cached_only=cached_only,
    )

    assert result.content == "synthetic result"
    assert manager.preparation_calls == (0 if cached_only else 1)
    assert model.download_calls == (0 if cached_only else 1)
    assert model.unload_calls == 1
