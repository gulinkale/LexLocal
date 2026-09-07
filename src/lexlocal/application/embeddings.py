"""Validate, normalize, and orchestrate provider-independent embeddings."""

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from math import hypot, isclose, isfinite
from numbers import Real

from lexlocal.application.ports.embeddings import (
    EMBEDDING_DTYPE,
    ChunkEmbedding,
    EmbeddingCancellationCheck,
    EmbeddingCancelled,
    EmbeddingCompatibility,
    EmbeddingError,
    EmbeddingModelIncompatible,
    EmbeddingPersistenceError,
    EmbeddingProviderFailure,
    InvalidEmbeddingInput,
    InvalidEmbeddingVector,
    NormalizedEmbeddingVector,
    PersistedEmbeddingSet,
    QueryEmbedding,
)
from lexlocal.application.ports.indexing import (
    ActivatedIndex,
    IndexChunk,
    IndexingCancelled,
    IndexingError,
    PersistedIndexGeneration,
    StagingEmbeddingHandoff,
)
from lexlocal.application.ports.local_models import (
    EmbeddingProvider,
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
)
from lexlocal.application.ports.unit_of_work import UnitOfWork
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.domain.identifiers import WorkspaceId
from lexlocal.domain.processing import IndexGeneration, IndexGenerationState


def normalize_provider_vectors(
    vectors: Sequence[Sequence[float]],
    *,
    expected_count: int,
    expected_dimensions: int,
) -> tuple[NormalizedEmbeddingVector, ...]:
    """Normalize exact-cardinality provider output using positional mapping."""

    if (
        isinstance(expected_count, bool)
        or not isinstance(expected_count, int)
        or expected_count < 1
        or isinstance(expected_dimensions, bool)
        or not isinstance(expected_dimensions, int)
        or expected_dimensions < 1
    ):
        raise InvalidEmbeddingInput("embedding output expectation is invalid")
    if isinstance(vectors, (str, bytes)):
        raise InvalidEmbeddingVector("embedding provider output is invalid")
    try:
        positional_vectors = tuple(vectors)
    except Exception:
        raise InvalidEmbeddingVector("embedding provider output is invalid") from None
    if len(positional_vectors) != expected_count:
        raise InvalidEmbeddingVector("embedding provider output count is invalid")
    return tuple(
        _normalize_vector(vector, expected_dimensions) for vector in positional_vectors
    )


def prepare_chunk_embeddings(
    handoff: StagingEmbeddingHandoff,
    status: LocalModelStatus,
    vectors: Sequence[Sequence[float]],
    created_at: datetime,
) -> tuple[ChunkEmbedding, ...]:
    """Map normalized provider positions to the exact ordered staging chunks."""

    if not isinstance(handoff, StagingEmbeddingHandoff):
        raise InvalidEmbeddingInput("staging embedding handoff is invalid")
    compatibility = _compatibility(handoff.candidate.generation, status)
    normalized = normalize_provider_vectors(
        vectors,
        expected_count=len(handoff.candidate.chunks),
        expected_dimensions=compatibility.dimensions,
    )
    return tuple(
        ChunkEmbedding(chunk.id, compatibility, vector, created_at)
        for chunk, vector in zip(handoff.candidate.chunks, normalized, strict=True)
    )


def prepare_query_embedding(
    query: str,
    workspace_id: WorkspaceId,
    target: PersistedIndexGeneration,
    status: LocalModelStatus,
    vectors: Sequence[Sequence[float]],
) -> QueryEmbedding:
    """Build an ephemeral query vector for one explicit ACTIVE index target."""

    if not isinstance(query, str) or not query.strip():
        raise InvalidEmbeddingInput("embedding query is invalid")
    if (
        not isinstance(workspace_id, WorkspaceId)
        or not isinstance(target, PersistedIndexGeneration)
        or target.generation.state is not IndexGenerationState.ACTIVE
        or target.generation.workspace_id != workspace_id
    ):
        raise EmbeddingModelIncompatible("query embedding target is invalid")
    compatibility = _compatibility(target.generation, status)
    normalized = normalize_provider_vectors(
        vectors,
        expected_count=1,
        expected_dimensions=compatibility.dimensions,
    )
    return QueryEmbedding(compatibility, normalized[0])


class EmbedStagingChunks:
    """Persist missing chunk vectors before delegating activation to INDEX."""

    def __init__(
        self,
        active_scope: ActiveWorkspaceScope,
        provider: EmbeddingProvider,
        cancellation: EmbeddingCancellationCheck,
        unit_of_work_factory: Callable[[], UnitOfWork],
        finalize_indexing: Callable[[StagingEmbeddingHandoff], ActivatedIndex],
        clock: Callable[[], datetime],
        batch_size: int,
    ) -> None:
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or batch_size < 1
        ):
            raise InvalidEmbeddingInput("embedding batch size is invalid")
        self._active_scope = active_scope
        self._provider = provider
        self._cancellation = cancellation
        self._unit_of_work_factory = unit_of_work_factory
        self._finalize_indexing = finalize_indexing
        self._clock = clock
        self._batch_size = batch_size

    def __call__(self, handoff: StagingEmbeddingHandoff) -> ActivatedIndex:
        """Converge one staging handoff and invoke its sole activation authority."""

        workspace_id = self._workspace_id()
        if (
            not isinstance(handoff, StagingEmbeddingHandoff)
            or handoff.candidate.generation.workspace_id != workspace_id
        ):
            raise EmbeddingModelIncompatible("embedding candidate ownership is invalid")
        compatibility = self._provider_compatibility(handoff)
        self._checkpoint()
        persisted = self._read_persisted(handoff, compatibility)
        missing = self._missing_chunks(handoff, persisted)

        for start in range(0, len(missing), self._batch_size):
            self._checkpoint()
            batch_chunks = missing[start : start + self._batch_size]
            batch = self._generate_batch(handoff, compatibility, batch_chunks)
            self._checkpoint()
            self._persist_batch(handoff, compatibility, batch)
            self._checkpoint()

        complete = self._read_persisted(handoff, compatibility)
        if not complete.is_complete:
            raise EmbeddingPersistenceError("persisted embeddings are incomplete")
        self._checkpoint()
        return self._finalize(handoff)

    def _workspace_id(self) -> WorkspaceId:
        try:
            return self._active_scope.require_workspace_id()
        except Exception:
            raise EmbeddingPersistenceError("active workspace is unavailable") from None

    def _provider_compatibility(
        self,
        handoff: StagingEmbeddingHandoff,
    ) -> EmbeddingCompatibility:
        try:
            status = self._provider.status
        except Exception:
            raise EmbeddingProviderFailure("embedding provider status failed") from None
        return _compatibility(handoff.candidate.generation, status)

    def _read_persisted(
        self,
        handoff: StagingEmbeddingHandoff,
        compatibility: EmbeddingCompatibility,
    ) -> PersistedEmbeddingSet:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                persisted = unit_of_work.embeddings.get_for_candidate(handoff)
        except EmbeddingError:
            raise
        except Exception:
            raise EmbeddingPersistenceError("embedding persistence read failed") from None
        expected_ids = tuple(chunk.id for chunk in handoff.candidate.chunks)
        if (
            not isinstance(persisted, PersistedEmbeddingSet)
            or persisted.compatibility != compatibility
            or persisted.expected_chunk_ids != expected_ids
        ):
            raise EmbeddingPersistenceError("persisted embeddings are incompatible")
        return persisted

    @staticmethod
    def _missing_chunks(
        handoff: StagingEmbeddingHandoff,
        persisted: PersistedEmbeddingSet,
    ) -> tuple[IndexChunk, ...]:
        persisted_ids = {item.chunk_id for item in persisted.embeddings}
        return tuple(
            chunk
            for chunk in handoff.candidate.chunks
            if chunk.id not in persisted_ids
        )

    def _generate_batch(
        self,
        handoff: StagingEmbeddingHandoff,
        compatibility: EmbeddingCompatibility,
        chunks: tuple[IndexChunk, ...],
    ) -> tuple[ChunkEmbedding, ...]:
        current = self._provider_compatibility(handoff)
        if current != compatibility:
            raise EmbeddingModelIncompatible("embedding provider changed")
        texts = tuple(chunk.logical.text for chunk in chunks)
        try:
            vectors = self._provider.embed(texts)
        except EmbeddingError:
            raise
        except Exception:
            raise EmbeddingProviderFailure("embedding provider failed") from None
        normalized = normalize_provider_vectors(
            vectors,
            expected_count=len(chunks),
            expected_dimensions=compatibility.dimensions,
        )
        created_at = self._created_at()
        return tuple(
            ChunkEmbedding(chunk.id, compatibility, vector, created_at)
            for chunk, vector in zip(chunks, normalized, strict=True)
        )

    def _persist_batch(
        self,
        handoff: StagingEmbeddingHandoff,
        compatibility: EmbeddingCompatibility,
        batch: tuple[ChunkEmbedding, ...],
    ) -> None:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                current = unit_of_work.embeddings.get_for_candidate(handoff)
                expected_ids = tuple(chunk.id for chunk in handoff.candidate.chunks)
                if (
                    current.compatibility != compatibility
                    or current.expected_chunk_ids != expected_ids
                ):
                    raise EmbeddingPersistenceError(
                        "persisted embeddings are incompatible"
                    )
                current_ids = {item.chunk_id for item in current.embeddings}
                pending = tuple(
                    item for item in batch if item.chunk_id not in current_ids
                )
                if pending:
                    unit_of_work.embeddings.add_batch(handoff, pending)
                    unit_of_work.commit()
        except EmbeddingError:
            raise
        except Exception:
            raise EmbeddingPersistenceError("embedding batch persistence failed") from None

    def _created_at(self) -> datetime:
        try:
            value = self._clock()
        except Exception:
            raise EmbeddingPersistenceError("embedding clock failed") from None
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() != timedelta(0)
        ):
            raise EmbeddingPersistenceError("embedding clock returned invalid data")
        return value

    def _checkpoint(self) -> None:
        try:
            self._cancellation.raise_if_cancelled()
        except EmbeddingCancelled:
            raise EmbeddingCancelled("embedding was cancelled") from None
        except Exception:
            raise EmbeddingPersistenceError("cancellation check failed") from None

    def _finalize(self, handoff: StagingEmbeddingHandoff) -> ActivatedIndex:
        try:
            result = self._finalize_indexing(handoff)
        except IndexingCancelled:
            raise EmbeddingCancelled("embedding finalization was cancelled") from None
        except (IndexingError, EmbeddingError):
            raise EmbeddingPersistenceError("embedding finalization failed") from None
        except Exception:
            raise EmbeddingPersistenceError("embedding finalization failed") from None
        if not isinstance(result, ActivatedIndex):
            raise EmbeddingPersistenceError("embedding finalization failed")
        return result


class EmbedQuery:
    """Generate one ephemeral query vector for an explicit active index target."""

    def __init__(
        self,
        active_scope: ActiveWorkspaceScope,
        provider: EmbeddingProvider,
    ) -> None:
        self._active_scope = active_scope
        self._provider = provider

    def __call__(
        self,
        query: str,
        target: PersistedIndexGeneration,
    ) -> QueryEmbedding:
        """Return an in-memory vector without opening a persistence scope."""

        try:
            workspace_id = self._active_scope.require_workspace_id()
        except Exception:
            raise EmbeddingPersistenceError("active workspace is unavailable") from None
        if not isinstance(query, str) or not query.strip():
            raise InvalidEmbeddingInput("embedding query is invalid")
        if (
            not isinstance(target, PersistedIndexGeneration)
            or target.generation.state is not IndexGenerationState.ACTIVE
            or target.generation.workspace_id != workspace_id
        ):
            raise EmbeddingModelIncompatible("query embedding target is invalid")
        try:
            status = self._provider.status
        except Exception:
            raise EmbeddingProviderFailure("embedding provider status failed") from None
        _compatibility(target.generation, status)
        try:
            vectors = self._provider.embed((query,))
        except EmbeddingError:
            raise
        except Exception:
            raise EmbeddingProviderFailure("embedding provider failed") from None
        return prepare_query_embedding(query, workspace_id, target, status, vectors)


def _compatibility(
    generation: IndexGeneration,
    status: LocalModelStatus,
) -> EmbeddingCompatibility:
    if not isinstance(generation, IndexGeneration) or not isinstance(status, LocalModelStatus):
        raise EmbeddingModelIncompatible("embedding model compatibility is invalid")
    model = status.model
    if (
        status.readiness is not ModelReadiness.READY
        or model.capability is not ModelCapability.EMBEDDING
        or model.id != generation.embedding_model_id
        or model.dimensions != generation.embedding_dimensions
    ):
        raise EmbeddingModelIncompatible("embedding model compatibility is invalid")
    return EmbeddingCompatibility(
        workspace_id=generation.workspace_id,
        index_generation_id=generation.id,
        embedding_model_id=generation.embedding_model_id,
        chunking_profile_version=generation.chunking_profile_version,
        normalization_profile_version=generation.normalization_profile_version,
        dimensions=generation.embedding_dimensions,
        dtype=EMBEDDING_DTYPE,
        is_unit_normalized=True,
    )


def _normalize_vector(
    vector: Sequence[float],
    expected_dimensions: int,
) -> NormalizedEmbeddingVector:
    if isinstance(vector, (str, bytes)):
        raise InvalidEmbeddingVector("embedding vector is invalid")
    try:
        raw_values = tuple(vector)
    except Exception:
        raise InvalidEmbeddingVector("embedding vector is invalid") from None
    if len(raw_values) != expected_dimensions:
        raise InvalidEmbeddingVector("embedding vector dimension is invalid")
    canonical: list[float] = []
    for value in raw_values:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise InvalidEmbeddingVector("embedding vector value is invalid")
        try:
            converted = float(value)
        except (OverflowError, ValueError):
            raise InvalidEmbeddingVector("embedding vector value is invalid") from None
        if not isfinite(converted):
            raise InvalidEmbeddingVector("embedding vector value is invalid")
        canonical.append(converted)
    norm = hypot(*canonical)
    if not isfinite(norm) or norm <= 0.0:
        raise InvalidEmbeddingVector("embedding vector norm is invalid")
    normalized = tuple(value / norm for value in canonical)
    normalized_norm = hypot(*normalized)
    if not isfinite(normalized_norm) or not isclose(
        normalized_norm,
        1.0,
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        raise InvalidEmbeddingVector("embedding vector norm is invalid")
    return NormalizedEmbeddingVector(normalized)
