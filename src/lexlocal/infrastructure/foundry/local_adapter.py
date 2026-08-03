"""Reusable Foundry Local runtime and chat-inference lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

DEFAULT_VALIDATION_MODEL_ALIAS = "qwen2.5-0.5b"

DiagnosticOutput = Callable[[str], None]


class FoundryLocalError(RuntimeError):
    """Raised when local inference cannot produce a meaningful response."""


class _Catalog(Protocol):
    def get_model(self, model_alias: str) -> Any:
        """Resolve a model alias."""


class _Manager(Protocol):
    catalog: _Catalog

    def download_and_register_eps(self) -> None:
        """Prepare local execution providers."""


@dataclass(frozen=True, slots=True)
class FoundryInferenceResult:
    """Meaningful local inference content and sanitized runtime identity."""

    content: str
    model_id: str
    execution_provider: str


class FoundryLocalAdapter:
    """Own Foundry Local initialization and one-model inference lifecycles."""

    def __init__(self, manager: _Manager) -> None:
        self._manager = manager

    @classmethod
    def initialize(cls, *, app_name: str = "lexlocal") -> FoundryLocalAdapter:
        """Initialize the real SDK runtime and return its infrastructure adapter."""

        from foundry_local_sdk import (  # type: ignore[import-untyped]
            Configuration,
            FoundryLocalManager,
        )

        configuration = Configuration(app_name=app_name)
        FoundryLocalManager.initialize(configuration)
        return cls(FoundryLocalManager.instance)

    def infer(
        self,
        *,
        model_alias: str,
        prompt: str,
        cached_only: bool = False,
        output: DiagnosticOutput | None = None,
    ) -> FoundryInferenceResult:
        """Resolve, prepare, load, invoke, validate, and unload a local model."""

        emit = output if output is not None else _discard_output

        if cached_only:
            emit("Execution-provider download preparation: skipped in cached-only mode")
        else:
            emit("Preparing execution providers...")
            self._manager.download_and_register_eps()

        model = self._manager.catalog.get_model(model_alias)
        if model is None:
            raise FoundryLocalError(
                f"Model alias was not found in the local catalog: {model_alias}"
            )

        model_id, execution_provider = _model_metadata(model)
        emit(f"Resolved model identity: {model_id}")
        emit(f"Execution provider: {execution_provider}")

        if cached_only:
            if not bool(model.is_cached):
                raise FoundryLocalError(
                    f"Model is not available in the local cache: {model_alias}"
                )
            emit("Model download: skipped; cached model required")
        else:
            emit("Downloading model if required...")
            model.download()

        loaded = False

        try:
            emit("Loading model...")
            model.load()
            loaded = True

            client = model.get_chat_client()
            messages = [{"role": "user", "content": prompt}]
            content = _collect_meaningful_content(
                client.complete_streaming_chat(messages)
            )
            emit("Meaningful assistant content received: yes")
            emit(f"Assistant content length: {len(content)} characters")
            return FoundryInferenceResult(
                content=content,
                model_id=model_id,
                execution_provider=execution_provider,
            )
        finally:
            if loaded:
                emit("Unloading model...")
                model.unload()


def _collect_meaningful_content(chunks: Iterable[object]) -> str:
    """Collect streamed assistant text and reject missing meaningful content."""

    content_parts: list[str] = []

    for chunk in chunks:
        choices = getattr(chunk, "choices", None)
        if not choices:
            continue

        delta = getattr(choices[0], "delta", None)
        content = getattr(delta, "content", None)

        if isinstance(content, str):
            content_parts.append(content)

    content = "".join(content_parts)
    if not content.strip():
        raise FoundryLocalError(
            "Foundry Local inference returned no meaningful assistant content"
        )

    return content


def _model_metadata(model: Any) -> tuple[str, str]:
    """Return only sanitized model identity and execution-provider metadata."""

    model_id = str(getattr(model, "id", "not exposed"))
    model_info = getattr(model, "info", None)
    runtime = getattr(model_info, "runtime", None)
    execution_provider = str(
        getattr(runtime, "execution_provider", None) or "not exposed"
    )
    return model_id, execution_provider


def _discard_output(message: str) -> None:
    """Ignore optional lifecycle diagnostics."""
