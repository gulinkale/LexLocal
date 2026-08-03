"""Unit tests for the reusable Foundry Local infrastructure adapter."""

from __future__ import annotations

from collections.abc import Iterable
from types import SimpleNamespace

import pytest

from lexlocal.infrastructure.foundry import FoundryLocalAdapter, FoundryLocalError


def chunk(content: str | None = None, *, choices: bool = True) -> SimpleNamespace:
    """Create a small streaming response chunk fake."""

    if not choices:
        return SimpleNamespace(choices=[])
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
    )


class FakeClient:
    def __init__(
        self,
        chunks: Iterable[object] = (),
        *,
        inference_error: Exception | None = None,
    ) -> None:
        self._chunks = chunks
        self._inference_error = inference_error

    def complete_streaming_chat(self, messages: list[dict[str, str]]) -> Iterable[object]:
        assert messages == [{"role": "user", "content": "test prompt"}]
        if self._inference_error is not None:
            raise self._inference_error
        return self._chunks


class FakeModel:
    def __init__(
        self,
        client: FakeClient,
        *,
        cached: bool = True,
        load_error: Exception | None = None,
    ) -> None:
        self.id = "resolved-local-model:1"
        self.info = SimpleNamespace(
            runtime=SimpleNamespace(execution_provider="LocalExecutionProvider")
        )
        self.is_cached = cached
        self._client = client
        self._load_error = load_error
        self.download_calls = 0
        self.load_calls = 0
        self.unload_calls = 0

    def download(self) -> None:
        self.download_calls += 1

    def load(self) -> None:
        self.load_calls += 1
        if self._load_error is not None:
            raise self._load_error

    def get_chat_client(self) -> FakeClient:
        return self._client

    def unload(self) -> None:
        self.unload_calls += 1


class FakeCatalog:
    def __init__(self, model: FakeModel | None) -> None:
        self._model = model
        self.requested_aliases: list[str] = []

    def get_model(self, model_alias: str) -> FakeModel | None:
        self.requested_aliases.append(model_alias)
        return self._model


class FakeManager:
    def __init__(self, model: FakeModel | None) -> None:
        self.catalog = FakeCatalog(model)
        self.preparation_calls = 0

    def download_and_register_eps(self) -> None:
        self.preparation_calls += 1


def infer(
    model: FakeModel,
    *,
    cached_only: bool = False,
) -> tuple[object, FakeManager, list[str]]:
    """Run one adapter lifecycle with fake infrastructure objects."""

    manager = FakeManager(model)
    output: list[str] = []
    result = FoundryLocalAdapter(manager).infer(
        model_alias="test-model",
        prompt="test prompt",
        cached_only=cached_only,
        output=output.append,
    )
    return result, manager, output


def test_successful_lifecycle_downloads_loads_infers_and_unloads() -> None:
    model = FakeModel(FakeClient([chunk("Local "), chunk("inference works.")]))

    result, manager, output = infer(model)

    assert result.content == "Local inference works."
    assert result.model_id == "resolved-local-model:1"
    assert result.execution_provider == "LocalExecutionProvider"
    assert manager.catalog.requested_aliases == ["test-model"]
    assert manager.preparation_calls == 1
    assert model.download_calls == 1
    assert model.load_calls == 1
    assert model.unload_calls == 1
    assert "Meaningful assistant content received: yes" in output


@pytest.mark.parametrize(
    "chunks",
    [
        [],
        [chunk(choices=False)],
        [chunk(None)],
        [chunk(""), chunk("  \n")],
    ],
    ids=["empty-stream", "missing-choices", "missing-content", "whitespace-only"],
)
def test_missing_or_whitespace_only_output_fails_and_unloads(
    chunks: list[object],
) -> None:
    model = FakeModel(FakeClient(chunks))

    with pytest.raises(FoundryLocalError, match="no meaningful assistant content"):
        infer(model)

    assert model.unload_calls == 1


def test_inference_failure_propagates_and_unloads() -> None:
    model = FakeModel(
        FakeClient(inference_error=RuntimeError("inference failed"))
    )

    with pytest.raises(RuntimeError, match="inference failed"):
        infer(model)

    assert model.unload_calls == 1


def test_load_failure_propagates_without_unload() -> None:
    model = FakeModel(
        FakeClient([chunk("unused")]),
        load_error=RuntimeError("load failed"),
    )

    with pytest.raises(RuntimeError, match="load failed"):
        infer(model)

    assert model.load_calls == 1
    assert model.unload_calls == 0


def test_cached_only_rejects_uncached_model_without_download_or_load() -> None:
    model = FakeModel(FakeClient([chunk("unused")]), cached=False)
    manager = FakeManager(model)

    with pytest.raises(FoundryLocalError, match="not available in the local cache"):
        FoundryLocalAdapter(manager).infer(
            model_alias="test-model",
            prompt="test prompt",
            cached_only=True,
        )

    assert manager.preparation_calls == 0
    assert model.download_calls == 0
    assert model.load_calls == 0
    assert model.unload_calls == 0


def test_cached_only_success_never_prepares_or_downloads() -> None:
    model = FakeModel(FakeClient([chunk("Cached inference works.")]))

    result, manager, output = infer(model, cached_only=True)

    assert result.content == "Cached inference works."
    assert manager.preparation_calls == 0
    assert model.download_calls == 0
    assert model.load_calls == 1
    assert model.unload_calls == 1
    assert "Model download: skipped; cached model required" in output


def test_missing_catalog_model_fails_before_load() -> None:
    manager = FakeManager(None)

    with pytest.raises(FoundryLocalError, match="not found in the local catalog"):
        FoundryLocalAdapter(manager).infer(
            model_alias="missing-model",
            prompt="test prompt",
            cached_only=True,
        )

    assert manager.preparation_calls == 0
