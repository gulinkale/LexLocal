"""Adapt Foundry Local behind SDK-free Application capability ports."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from lexlocal.application.ports.local_models import (
    ChatInferenceProvider,
    EmbeddingProvider,
    LocalModelIncompatible,
    LocalModelInferenceError,
    LocalModelRuntimeError,
    LocalModelStatus,
    LocalModelUnavailable,
    ModelCapability,
    ModelReadiness,
    ResolvedModelRecord,
)
from lexlocal.domain.identifiers import LocalModelId

DEFAULT_VALIDATION_MODEL_ALIAS = "qwen2.5-0.5b"
_CHAT_HEALTH_PROMPT = "Reply with one synthetic readiness word."
_EMBEDDING_HEALTH_TEXT = "anonymous synthetic readiness fixture"

DiagnosticOutput = Callable[[str], None]


class _Catalog(Protocol):
    def get_model(self, model_alias: str) -> Any:
        """Resolve one exact model alias."""


class _Manager(Protocol):
    catalog: _Catalog

    def download_and_register_eps(self) -> None:
        """Prepare local execution providers for the operator-only CLI."""


@dataclass(slots=True)
class _ResolvedHandle:
    model: Any
    status: LocalModelStatus
    loaded: bool = False


class FoundryLocalRuntime:
    """Own one cached-only Foundry runtime and its exact resolved handles."""

    def __init__(self, manager: _Manager) -> None:
        self._manager = manager
        self._handles: dict[LocalModelId, _ResolvedHandle] = {}
        self._closed = False

    @classmethod
    def initialize(cls, *, app_name: str = "lexlocal") -> FoundryLocalRuntime:
        """Initialize the SDK once and translate native initialization failures."""

        try:
            from foundry_local_sdk import (  # type: ignore[import-untyped]
                Configuration,
                FoundryLocalManager,
            )

            FoundryLocalManager.initialize(Configuration(app_name=app_name))
            return cls(FoundryLocalManager.instance)
        except Exception:
            raise LocalModelRuntimeError(
                "local model runtime initialization failed"
            ) from None

    def resolve_ready(
        self,
        *,
        model_id: LocalModelId,
        requested_alias: str,
        capability: ModelCapability,
    ) -> LocalModelStatus:
        """Resolve and health-check one exact cached model without substitution."""

        self._require_open()
        if model_id in self._handles:
            raise LocalModelRuntimeError("local model identity is already resolved")

        try:
            model = self._manager.catalog.get_model(requested_alias)
        except Exception:
            raise LocalModelUnavailable("requested local model is unavailable") from None
        if model is None:
            raise LocalModelUnavailable("requested local model is unavailable")

        try:
            is_cached = model.is_cached
        except Exception:
            raise LocalModelUnavailable("requested local model is unavailable") from None
        if is_cached is not True:
            raise LocalModelUnavailable("requested local model is unavailable")

        identity = _safe_identity(model, requested_alias=requested_alias)
        dimensions = self._health_check(model, capability)
        record = ResolvedModelRecord(
            id=model_id,
            requested_alias=requested_alias,
            resolved_model_id=identity.resolved_model_id,
            model_version=identity.model_version,
            capability=capability,
            provider=identity.provider,
            dimensions=dimensions,
        )
        status = LocalModelStatus(
            model=record,
            readiness=ModelReadiness.READY,
            execution_provider=identity.execution_provider,
        )
        self._handles[model_id] = _ResolvedHandle(model=model, status=status)
        return status

    def chat_provider(self, status: LocalModelStatus) -> ChatInferenceProvider:
        """Bind chat inference to one already-resolved exact identity."""

        return FoundryLocalChatProvider(self, self._require_status(status, ModelCapability.CHAT))

    def embedding_provider(
        self,
        status: LocalModelStatus,
    ) -> EmbeddingProvider:
        """Bind embedding inference to one already-resolved exact identity."""

        return FoundryLocalEmbeddingProvider(
            self,
            self._require_status(status, ModelCapability.EMBEDDING),
        )

    def adopt_persisted_record(
        self,
        status: LocalModelStatus,
        persisted: ResolvedModelRecord,
    ) -> LocalModelStatus:
        """Rebind a resolved handle to an exact reused persisted stable ID."""

        handle = self._handles.get(status.model.id)
        if handle is None or handle.status != status:
            raise LocalModelRuntimeError("local model status is not resolved")
        resolved_identity = (
            status.model.requested_alias,
            status.model.resolved_model_id,
            status.model.model_version,
            status.model.capability,
            status.model.provider,
            status.model.dimensions,
        )
        persisted_identity = (
            persisted.requested_alias,
            persisted.resolved_model_id,
            persisted.model_version,
            persisted.capability,
            persisted.provider,
            persisted.dimensions,
        )
        if resolved_identity != persisted_identity:
            raise LocalModelRuntimeError("persisted local model identity conflicts")
        if persisted.id != status.model.id and persisted.id in self._handles:
            raise LocalModelRuntimeError("persisted local model identity conflicts")

        rebound = LocalModelStatus(
            model=persisted,
            readiness=status.readiness,
            execution_provider=status.execution_provider,
        )
        if persisted.id != status.model.id:
            del self._handles[status.model.id]
            self._handles[persisted.id] = handle
        handle.status = rebound
        return rebound

    def close(self) -> None:
        """Unload every loaded exact handle; repeated close calls are harmless."""

        if self._closed:
            return
        self._closed = True
        cleanup_failed = False
        for handle in self._handles.values():
            if not handle.loaded:
                continue
            try:
                handle.model.unload()
            except Exception:
                cleanup_failed = True
            finally:
                handle.loaded = False
        if cleanup_failed:
            raise LocalModelRuntimeError("local model cleanup failed") from None

    def _health_check(
        self,
        model: Any,
        capability: ModelCapability,
    ) -> int | None:
        loaded = False
        primary: Exception | None = None
        dimensions: int | None = None
        try:
            model.load()
            loaded = True
        except Exception:
            primary = LocalModelRuntimeError("local model load failed")
        try:
            if primary is not None:
                raise primary
            if capability is ModelCapability.CHAT:
                client = model.get_chat_client()
                _collect_meaningful_content(
                    client.complete_streaming_chat(
                        [{"role": "user", "content": _CHAT_HEALTH_PROMPT}]
                    )
                )
            else:
                client = model.get_embedding_client()
                vectors = _extract_vectors(
                    client.generate_embeddings([_EMBEDDING_HEALTH_TEXT]),
                    expected_count=1,
                )
                dimensions = len(vectors[0])
        except (LocalModelIncompatible, LocalModelRuntimeError) as error:
            primary = error
        except Exception:
            primary = LocalModelIncompatible(
                "local model capability health validation failed"
            )
        cleanup_failed = False
        if loaded:
            try:
                model.unload()
            except Exception:
                cleanup_failed = True
        if primary is not None:
            raise primary from None
        if cleanup_failed:
            raise LocalModelRuntimeError("local model cleanup failed") from None
        return dimensions

    def _chat(self, model_id: LocalModelId, prompt: str) -> str:
        handle = self._load_exact(model_id, ModelCapability.CHAT)
        try:
            client = handle.model.get_chat_client()
            return _collect_meaningful_content(
                client.complete_streaming_chat([{"role": "user", "content": prompt}])
            )
        except Exception:
            self._cleanup_after_failure(handle)
            raise LocalModelInferenceError("local chat inference failed") from None

    def _embed(
        self,
        model_id: LocalModelId,
        texts: Sequence[str],
    ) -> Sequence[Sequence[float]]:
        handle = self._load_exact(model_id, ModelCapability.EMBEDDING)
        try:
            client = handle.model.get_embedding_client()
            vectors = _extract_vectors(
                client.generate_embeddings(list(texts)),
                expected_count=len(texts),
            )
            expected_dimensions = handle.status.model.dimensions
            if any(len(vector) != expected_dimensions for vector in vectors):
                raise LocalModelIncompatible("embedding dimensions are incompatible")
            return vectors
        except Exception:
            self._cleanup_after_failure(handle)
            raise LocalModelInferenceError("local embedding inference failed") from None

    def _load_exact(
        self,
        model_id: LocalModelId,
        capability: ModelCapability,
    ) -> _ResolvedHandle:
        self._require_open()
        handle = self._handles.get(model_id)
        if handle is None or handle.status.model.capability is not capability:
            raise LocalModelRuntimeError("local model identity is not resolved")
        if not handle.loaded:
            try:
                handle.model.load()
            except Exception:
                raise LocalModelRuntimeError("local model load failed") from None
            handle.loaded = True
        return handle

    def _cleanup_after_failure(self, handle: _ResolvedHandle) -> None:
        if not handle.loaded:
            return
        try:
            handle.model.unload()
        except Exception:
            pass
        finally:
            handle.loaded = False

    def _require_status(
        self,
        status: LocalModelStatus,
        capability: ModelCapability,
    ) -> LocalModelStatus:
        self._require_open()
        handle = self._handles.get(status.model.id)
        if handle is None or handle.status != status or status.model.capability is not capability:
            raise LocalModelRuntimeError("local model status is not resolved")
        return status

    def _require_open(self) -> None:
        if self._closed:
            raise LocalModelRuntimeError("local model runtime is closed")


@dataclass(frozen=True, slots=True)
class FoundryLocalChatProvider:
    """Provide SDK-free chat inference for one exact resolved handle."""

    _runtime: FoundryLocalRuntime
    status: LocalModelStatus

    def generate(self, prompt: str) -> str:
        """Generate meaningful text without exposing native response objects."""

        return self._runtime._chat(self.status.model.id, prompt)


@dataclass(frozen=True, slots=True)
class FoundryLocalEmbeddingProvider:
    """Provide SDK-free embeddings for one exact resolved handle."""

    _runtime: FoundryLocalRuntime
    status: LocalModelStatus

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Generate validated finite vectors with the health-checked dimension."""

        return self._runtime._embed(self.status.model.id, texts)


@dataclass(frozen=True, slots=True)
class _SafeIdentity:
    resolved_model_id: str
    model_version: str | None
    provider: str
    execution_provider: str


def _safe_identity(model: Any, *, requested_alias: str) -> _SafeIdentity:
    try:
        resolved_model_id = model.id
        resolved_alias = model.alias
        info = model.info
        version = info.version
        provider = info.provider_type
        runtime = info.runtime
        execution_provider = runtime.execution_provider
    except Exception:
        raise LocalModelUnavailable("local model identity is unavailable") from None
    if not isinstance(resolved_model_id, str) or not resolved_model_id.strip():
        raise LocalModelUnavailable("local model identity is unavailable")
    if resolved_alias != requested_alias:
        raise LocalModelUnavailable("local model identity is unavailable")
    if not isinstance(execution_provider, str) or not execution_provider.strip():
        raise LocalModelUnavailable("local execution provider is unavailable")
    if not isinstance(provider, str) or not provider.strip():
        raise LocalModelUnavailable("local model provider is unavailable")
    if isinstance(version, bool) or not isinstance(version, (int, str, type(None))):
        raise LocalModelUnavailable("local model identity is unavailable")
    model_version = None if version is None else str(version)
    if model_version is not None and not model_version.strip():
        raise LocalModelUnavailable("local model identity is unavailable")
    return _SafeIdentity(
        resolved_model_id,
        model_version,
        provider,
        execution_provider,
    )


def _collect_meaningful_content(chunks: Iterable[object]) -> str:
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
        raise LocalModelIncompatible("local chat result is incompatible")
    return content


def _extract_vectors(response: object, *, expected_count: int) -> list[list[float]]:
    data = getattr(response, "data", None)
    if not isinstance(data, list) or len(data) != expected_count or not data:
        raise LocalModelIncompatible("embedding result shape is incompatible")
    vectors: list[list[float]] = []
    for item in data:
        raw_vector = getattr(item, "embedding", None)
        if not isinstance(raw_vector, list) or not raw_vector:
            raise LocalModelIncompatible("embedding result shape is incompatible")
        vector: list[float] = []
        for value in raw_vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise LocalModelIncompatible("embedding values are incompatible")
            canonical = float(value)
            if not math.isfinite(canonical):
                raise LocalModelIncompatible("embedding values are incompatible")
            vector.append(canonical)
        vectors.append(vector)
    return vectors


class FoundryLocalError(RuntimeError):
    """Operator-only FOUNDRY-001 CLI failure."""


@dataclass(frozen=True, slots=True)
class FoundryInferenceResult:
    """Operator-only CLI result with safe identity metadata."""

    content: str
    model_id: str
    execution_provider: str


class FoundryLocalAdapter:
    """Preserve the explicit FOUNDRY-001 operator preparation workflow."""

    def __init__(self, manager: _Manager) -> None:
        self._manager = manager

    @classmethod
    def initialize(cls, *, app_name: str = "lexlocal") -> FoundryLocalAdapter:
        from foundry_local_sdk import (
            Configuration,
            FoundryLocalManager,
        )

        FoundryLocalManager.initialize(Configuration(app_name=app_name))
        return cls(FoundryLocalManager.instance)

    def infer(
        self,
        *,
        model_alias: str,
        prompt: str,
        cached_only: bool = False,
        output: DiagnosticOutput | None = None,
    ) -> FoundryInferenceResult:
        emit = output if output is not None else lambda _message: None
        if not cached_only:
            self._manager.download_and_register_eps()
        model = self._manager.catalog.get_model(model_alias)
        if model is None:
            raise FoundryLocalError("requested model was not found")
        if cached_only and model.is_cached is not True:
            raise FoundryLocalError("requested model is not cached")
        if not cached_only:
            model.download()
        identity = _safe_identity(model, requested_alias=model_alias)
        loaded = False
        try:
            model.load()
            loaded = True
            content = _collect_meaningful_content(
                model.get_chat_client().complete_streaming_chat(
                    [{"role": "user", "content": prompt}]
                )
            )
            emit("Meaningful assistant content received: yes")
            return FoundryInferenceResult(
                content, identity.resolved_model_id, identity.execution_provider
            )
        except Exception as error:
            if isinstance(error, FoundryLocalError):
                raise
            raise FoundryLocalError("local inference failed") from None
        finally:
            if loaded:
                model.unload()
