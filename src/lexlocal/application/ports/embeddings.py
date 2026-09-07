"""Define SDK- and persistence-free Application embedding contracts."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import hypot, isclose, isfinite
from typing import Protocol

from lexlocal.application.ports.indexing import StagingEmbeddingHandoff
from lexlocal.domain.identifiers import (
    ChunkId,
    IndexGenerationId,
    LocalModelId,
    WorkspaceId,
)

EMBEDDING_DTYPE = "float32"


class EmbeddingError(Exception):
    """Base exception for sanitized embedding failures."""


class InvalidEmbeddingInput(EmbeddingError):
    """Report malformed embedding input or metadata."""


class EmbeddingModelIncompatible(EmbeddingError):
    """Report that exact model/index compatibility is unavailable."""


class InvalidEmbeddingVector(EmbeddingError):
    """Report invalid provider vector shape or numeric content."""


class EmbeddingProviderFailure(EmbeddingError):
    """Report a sanitized embedding-provider dependency failure."""


class EmbeddingPersistenceError(EmbeddingError):
    """Report a sanitized embedding persistence contract failure."""


class EmbeddingCancelled(EmbeddingError):
    """Report cooperative cancellation before complete embedding success."""


class EmbeddingCancellationCheck(Protocol):
    """Raise when cooperative embedding cancellation has been requested."""

    def raise_if_cancelled(self) -> None:
        """Raise EmbeddingCancelled when cancellation is requested."""

        ...


@dataclass(frozen=True, slots=True)
class EmbeddingCompatibility:
    """Carry exact index/model metadata shared by chunk and query vectors."""

    workspace_id: WorkspaceId
    index_generation_id: IndexGenerationId
    embedding_model_id: LocalModelId
    chunking_profile_version: str
    normalization_profile_version: str
    dimensions: int
    dtype: str = EMBEDDING_DTYPE
    is_unit_normalized: bool = True

    def __post_init__(self) -> None:
        if (
            not isinstance(self.workspace_id, WorkspaceId)
            or not isinstance(self.index_generation_id, IndexGenerationId)
            or not isinstance(self.embedding_model_id, LocalModelId)
            or not isinstance(self.chunking_profile_version, str)
            or not self.chunking_profile_version.strip()
            or not isinstance(self.normalization_profile_version, str)
            or not self.normalization_profile_version.strip()
            or isinstance(self.dimensions, bool)
            or not isinstance(self.dimensions, int)
            or self.dimensions < 1
            or self.dtype != EMBEDDING_DTYPE
            or self.is_unit_normalized is not True
        ):
            raise InvalidEmbeddingInput("embedding compatibility is invalid")


@dataclass(frozen=True, slots=True)
class NormalizedEmbeddingVector:
    """Hold an immutable finite unit vector without exposing its values in repr."""

    values: tuple[float, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.values, tuple)
            or not self.values
            or not all(type(value) is float and isfinite(value) for value in self.values)
        ):
            raise InvalidEmbeddingVector("normalized embedding vector is invalid")
        norm = hypot(*self.values)
        if not isfinite(norm) or not isclose(norm, 1.0, rel_tol=1e-6, abs_tol=1e-6):
            raise InvalidEmbeddingVector("normalized embedding vector is invalid")

    @property
    def dimensions(self) -> int:
        """Return the vector dimension without exposing its values."""

        return len(self.values)


@dataclass(frozen=True, slots=True)
class ChunkEmbedding:
    """Bind one normalized vector to exact chunk/index compatibility metadata."""

    chunk_id: ChunkId
    compatibility: EmbeddingCompatibility
    vector: NormalizedEmbeddingVector = field(repr=False)
    created_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.chunk_id, ChunkId)
            or not isinstance(self.compatibility, EmbeddingCompatibility)
            or not isinstance(self.vector, NormalizedEmbeddingVector)
            or self.vector.dimensions != self.compatibility.dimensions
        ):
            raise EmbeddingPersistenceError("chunk embedding is invalid")
        _require_utc(self.created_at)


@dataclass(frozen=True, slots=True)
class PersistedEmbeddingSet:
    """Represent the compatible persisted subset for one expected chunk set."""

    compatibility: EmbeddingCompatibility
    expected_chunk_ids: tuple[ChunkId, ...]
    embeddings: tuple[ChunkEmbedding, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.compatibility, EmbeddingCompatibility)
            or not isinstance(self.expected_chunk_ids, tuple)
            or not self.expected_chunk_ids
            or not all(isinstance(chunk_id, ChunkId) for chunk_id in self.expected_chunk_ids)
            or len(set(self.expected_chunk_ids)) != len(self.expected_chunk_ids)
            or not isinstance(self.embeddings, tuple)
            or not all(isinstance(item, ChunkEmbedding) for item in self.embeddings)
        ):
            raise EmbeddingPersistenceError("persisted embedding set is invalid")
        actual_ids = tuple(item.chunk_id for item in self.embeddings)
        if (
            len(set(actual_ids)) != len(actual_ids)
            or any(item.compatibility != self.compatibility for item in self.embeddings)
            or actual_ids
            != tuple(chunk_id for chunk_id in self.expected_chunk_ids if chunk_id in actual_ids)
        ):
            raise EmbeddingPersistenceError("persisted embedding set is invalid")

    @property
    def is_complete(self) -> bool:
        """Return whether every expected chunk has one compatible embedding."""

        return tuple(item.chunk_id for item in self.embeddings) == self.expected_chunk_ids


@dataclass(frozen=True, slots=True)
class QueryEmbedding:
    """Return one ephemeral vector for an explicit ACTIVE index target."""

    compatibility: EmbeddingCompatibility
    vector: NormalizedEmbeddingVector = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.compatibility, EmbeddingCompatibility)
            or not isinstance(self.vector, NormalizedEmbeddingVector)
            or self.vector.dimensions != self.compatibility.dimensions
        ):
            raise InvalidEmbeddingInput("query embedding is invalid")


class EmbeddingRepository(Protocol):
    """Read and append candidate embeddings in the active transaction."""

    def get_for_candidate(
        self,
        handoff: StagingEmbeddingHandoff,
    ) -> PersistedEmbeddingSet:
        """Return compatible rows in candidate chunk order, including an empty subset."""

        ...

    def add_batch(
        self,
        handoff: StagingEmbeddingHandoff,
        embeddings: tuple[ChunkEmbedding, ...],
    ) -> None:
        """Append one complete validated batch without transaction finalization."""

        ...


def _require_utc(value: object) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise EmbeddingPersistenceError("embedding timestamp is invalid")
