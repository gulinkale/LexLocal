"""Unit tests for the Foundry Local validation script."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "validate_foundry_local.py"
_SPEC = importlib.util.spec_from_file_location("validate_foundry_local", _SCRIPT_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

ValidationError = _MODULE.ValidationError
collect_meaningful_content = _MODULE.collect_meaningful_content
validate_with_manager = _MODULE.validate_with_manager


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
        stream_error: Exception | None = None,
    ) -> None:
        self._chunks = chunks
        self._stream_error = stream_error

    def complete_streaming_chat(self, messages: list[dict[str, str]]) -> Iterable[object]:
        assert messages
        if self._stream_error is not None:
            raise self._stream_error
        return self._chunks


class FakeModel:
    def __init__(
        self,
        client: FakeClient,
        *,
        cached: bool = True,
        load_error: Exception | None = None,
    ) -> None:
        self.id = "qwen2.5-0.5b-cpu:1"
        self.info = SimpleNamespace(
            runtime=SimpleNamespace(execution_provider="CPUExecutionProvider")
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

    def unload(self) -> None:
        self.unload_calls += 1

    def get_chat_client(self) -> FakeClient:
        return self._client


class FakeManager:
    def __init__(
        self,
        model: FakeModel | None,
        *,
        preparation_error: Exception | None = None,
    ) -> None:
        self.catalog = SimpleNamespace(get_model=lambda alias: model)
        self._preparation_error = preparation_error
        self.preparation_calls = 0

    def download_and_register_eps(self) -> None:
        self.preparation_calls += 1
        if self._preparation_error is not None:
            raise self._preparation_error


def run_validation(
    model: FakeModel,
    *,
    cached_only: bool = False,
) -> tuple[str, list[str], FakeManager]:
    """Run validation with fakes and collect sanitized status output."""

    manager = FakeManager(model)
    output: list[str] = []
    content = validate_with_manager(
        manager,
        cached_only=cached_only,
        output=output.append,
    )
    return content, output, manager


def test_meaningful_streamed_content_succeeds_and_unloads() -> None:
    model = FakeModel(FakeClient([chunk("Local inference works.")]))

    content, output, manager = run_validation(model)

    assert content == "Local inference works."
    assert "Meaningful assistant content received: yes" in output
    assert manager.preparation_calls == 1
    assert model.download_calls == 1
    assert model.load_calls == 1
    assert model.unload_calls == 1


@pytest.mark.parametrize(
    "chunks",
    [
        [],
        [chunk(choices=False)],
        [chunk(None)],
        [chunk(""), chunk("   \n")],
    ],
    ids=["empty-stream", "no-choices", "no-content", "whitespace-content"],
)
def test_meaningless_stream_fails_and_unloads(chunks: list[object]) -> None:
    model = FakeModel(FakeClient(chunks))

    with pytest.raises(ValidationError, match="no meaningful assistant content"):
        run_validation(model)

    assert model.unload_calls == 1


def test_multiple_content_chunks_are_collected() -> None:
    content = collect_meaningful_content(
        [chunk("Local "), chunk(choices=False), chunk("inference "), chunk("works.")]
    )

    assert content == "Local inference works."


def test_streaming_failure_propagates_and_unloads() -> None:
    model = FakeModel(
        FakeClient(stream_error=RuntimeError("stream failed"))
    )

    with pytest.raises(RuntimeError, match="stream failed"):
        run_validation(model)

    assert model.unload_calls == 1


def test_load_failure_does_not_unload_model() -> None:
    model = FakeModel(
        FakeClient([chunk("unused")]),
        load_error=RuntimeError("load failed"),
    )

    with pytest.raises(RuntimeError, match="load failed"):
        run_validation(model)

    assert model.load_calls == 1
    assert model.unload_calls == 0


def test_model_lookup_failure_does_not_report_success() -> None:
    output: list[str] = []
    manager = FakeManager(None)

    with pytest.raises(ValidationError, match="not found"):
        validate_with_manager(manager, output=output.append)

    assert not any("Meaningful assistant content received" in line for line in output)


def test_preparation_failure_propagates_without_model_lifecycle() -> None:
    model = FakeModel(FakeClient([chunk("unused")]))
    manager = FakeManager(model, preparation_error=RuntimeError("preparation failed"))

    with pytest.raises(RuntimeError, match="preparation failed"):
        validate_with_manager(manager, output=lambda line: None)

    assert model.download_calls == 0
    assert model.load_calls == 0
    assert model.unload_calls == 0


def test_cached_only_mode_skips_download_preparation() -> None:
    model = FakeModel(FakeClient([chunk("Cached inference works.")]))

    content, _, manager = run_validation(model, cached_only=True)

    assert content == "Cached inference works."
    assert manager.preparation_calls == 0
    assert model.download_calls == 0
    assert model.unload_calls == 1


def test_cached_only_mode_rejects_uncached_model_without_loading() -> None:
    model = FakeModel(FakeClient([chunk("unused")]), cached=False)

    with pytest.raises(ValidationError, match="not available in the local cache"):
        run_validation(model, cached_only=True)

    assert model.download_calls == 0
    assert model.load_calls == 0
    assert model.unload_calls == 0
