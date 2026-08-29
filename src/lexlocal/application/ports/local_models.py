"""Define SDK-free Application contracts for local model capabilities."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from lexlocal.domain.identifiers import LocalModelId


class LocalModelError(Exception):
    """Base exception for sanitized local-model failures."""


class LocalModelUnavailable(LocalModelError):
    """Report that a required local model is unavailable."""


class LocalModelIncompatible(LocalModelError):
    """Report that a resolved model cannot provide its required capability."""


class LocalModelRuntimeError(LocalModelError):
    """Report a sanitized local runtime or lifecycle failure."""


class LocalModelInferenceError(LocalModelError):
    """Report a sanitized chat or embedding inference failure."""


class LocalModelPersistenceError(LocalModelError):
    """Report a sanitized resolved-model persistence failure."""


class ModelCapability(StrEnum):
    """Identify the two local-model capabilities required by M1."""

    CHAT = "CHAT"
    EMBEDDING = "EMBEDDING"


class ModelReadiness(StrEnum):
    """Represent safe observable runtime compatibility progress."""

    RESOLVED = "RESOLVED"
    READY = "READY"


@dataclass(frozen=True, slots=True)
class ResolvedModelRecord:
    """Represent exact schema-supported local-model identity metadata."""

    id: LocalModelId
    requested_alias: str
    resolved_model_id: str
    model_version: str | None
    capability: ModelCapability
    provider: str
    dimensions: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, LocalModelId):
            raise LocalModelPersistenceError("local model id is invalid")
        self._require_text(self.requested_alias, "requested alias")
        self._require_text(self.resolved_model_id, "resolved model id")
        if self.model_version is not None:
            self._require_text(self.model_version, "model version")
        if not isinstance(self.capability, ModelCapability):
            raise LocalModelPersistenceError("model capability is invalid")
        self._require_text(self.provider, "model provider")

        if self.capability is ModelCapability.CHAT:
            if self.dimensions is not None:
                raise LocalModelPersistenceError(
                    "chat model dimensions must be absent"
                )
        elif (
            isinstance(self.dimensions, bool)
            or not isinstance(self.dimensions, int)
            or self.dimensions < 1
        ):
            raise LocalModelPersistenceError(
                "embedding model dimensions must be a positive integer"
            )

    @staticmethod
    def _require_text(value: object, name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise LocalModelPersistenceError(f"{name} must be non-empty")


@dataclass(frozen=True, slots=True)
class LocalModelStatus:
    """Expose safe runtime-only compatibility state for one resolved model."""

    model: ResolvedModelRecord
    readiness: ModelReadiness
    execution_provider: str

    def __post_init__(self) -> None:
        if not isinstance(self.model, ResolvedModelRecord):
            raise LocalModelRuntimeError("resolved model metadata is invalid")
        if not isinstance(self.readiness, ModelReadiness):
            raise LocalModelRuntimeError("model readiness is invalid")
        if (
            not isinstance(self.execution_provider, str)
            or not self.execution_provider.strip()
        ):
            raise LocalModelRuntimeError("execution provider must be non-empty")


class LocalModelRuntime(Protocol):
    """Resolve one cached model and publish status only after compatibility health."""

    def resolve_ready(
        self,
        *,
        model_id: LocalModelId,
        requested_alias: str,
        capability: ModelCapability,
    ) -> LocalModelStatus:
        """Return exact ready metadata or fail closed without substitution."""

        ...

    def close(self) -> None:
        """Release every model handle owned by this runtime."""

        ...


class ChatInferenceProvider(Protocol):
    """Generate local chat text without exposing provider response types."""

    @property
    def status(self) -> LocalModelStatus:
        """Return safe identity and readiness metadata for this capability."""

        ...

    def generate(self, prompt: str) -> str:
        """Return generated text through the configured exact local model."""

        ...


class EmbeddingProvider(Protocol):
    """Generate local vectors without exposing provider response types."""

    @property
    def status(self) -> LocalModelStatus:
        """Return safe identity and readiness metadata for this capability."""

        ...

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Return one validated vector per supplied text."""

        ...


class ResolvedModelRepository(Protocol):
    """Store or reuse only an exact resolved-model identity."""

    def get_or_add_exact(
        self,
        model: ResolvedModelRecord,
    ) -> ResolvedModelRecord:
        """Return an exact match, add a new record, or reject a conflict."""

        ...
