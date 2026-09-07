"""Tests for Application-owned embedding contracts."""

import ast
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

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
    EmbeddingRepository,
    InvalidEmbeddingInput,
    InvalidEmbeddingVector,
    NormalizedEmbeddingVector,
    PersistedEmbeddingSet,
    QueryEmbedding,
)
from lexlocal.application.ports.indexing import StagingEmbeddingHandoff
from lexlocal.domain.identifiers import (
    ChunkId,
    IndexGenerationId,
    LocalModelId,
    WorkspaceId,
)

WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
GENERATION_ID = IndexGenerationId("20000000-0000-4000-8000-000000000001")
MODEL_ID = LocalModelId("30000000-0000-4000-8000-000000000001")
CHUNK_A = ChunkId("40000000-0000-4000-8000-000000000001")
CHUNK_B = ChunkId("40000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 9, 5, 8, 30, tzinfo=UTC)


def _compatibility() -> EmbeddingCompatibility:
    return EmbeddingCompatibility(
        WORKSPACE_ID,
        GENERATION_ID,
        MODEL_ID,
        "page-codepoint-window-v1",
        "exact-text-v1",
        2,
    )


def _embedding(chunk_id: ChunkId) -> ChunkEmbedding:
    return ChunkEmbedding(
        chunk_id,
        _compatibility(),
        NormalizedEmbeddingVector((0.6, 0.8)),
        NOW,
    )


class _RepositoryDouble:
    def get_for_candidate(
        self,
        handoff: StagingEmbeddingHandoff,
    ) -> PersistedEmbeddingSet:
        raise NotImplementedError

    def add_batch(
        self,
        handoff: StagingEmbeddingHandoff,
        embeddings: tuple[ChunkEmbedding, ...],
    ) -> None:
        raise NotImplementedError


class _CancellationDouble:
    def raise_if_cancelled(self) -> None:
        return None


_REPOSITORY_CONFORMANCE: EmbeddingRepository = _RepositoryDouble()
_CANCELLATION_CONFORMANCE: EmbeddingCancellationCheck = _CancellationDouble()


def test_embedding_values_are_immutable_and_hide_vectors() -> None:
    vector = NormalizedEmbeddingVector((0.6, 0.8))
    chunk = ChunkEmbedding(CHUNK_A, _compatibility(), vector, NOW)
    query = QueryEmbedding(_compatibility(), vector)
    attribute_name = "created_at"

    with pytest.raises(FrozenInstanceError):
        setattr(chunk, attribute_name, NOW + timedelta(seconds=1))

    assert "0.6" not in repr(vector)
    assert "0.6" not in repr(chunk)
    assert "0.6" not in repr(query)
    assert vector.dimensions == 2


def test_compatibility_carries_exact_frozen_metadata() -> None:
    compatibility = _compatibility()

    assert compatibility.workspace_id == WORKSPACE_ID
    assert compatibility.index_generation_id == GENERATION_ID
    assert compatibility.embedding_model_id == MODEL_ID
    assert compatibility.chunking_profile_version == "page-codepoint-window-v1"
    assert compatibility.normalization_profile_version == "exact-text-v1"
    assert compatibility.dimensions == 2
    assert compatibility.dtype == EMBEDDING_DTYPE
    assert compatibility.is_unit_normalized is True


@pytest.mark.parametrize(
    ("dtype", "is_unit_normalized"),
    [("float64", True), (EMBEDDING_DTYPE, False)],
)
def test_compatibility_rejects_noncanonical_vector_metadata(
    dtype: str,
    is_unit_normalized: bool,
) -> None:
    with pytest.raises(InvalidEmbeddingInput, match="compatibility is invalid"):
        EmbeddingCompatibility(
            WORKSPACE_ID,
            GENERATION_ID,
            MODEL_ID,
            "page-codepoint-window-v1",
            "exact-text-v1",
            2,
            dtype,
            is_unit_normalized,
        )


@pytest.mark.parametrize(
    "timestamp",
    [
        datetime(2026, 9, 5, 8, 30),
        datetime(2026, 9, 5, 11, 30, tzinfo=timezone(timedelta(hours=3))),
    ],
)
def test_chunk_embedding_requires_explicit_utc_timestamp(timestamp: datetime) -> None:
    with pytest.raises(EmbeddingPersistenceError, match="timestamp is invalid"):
        ChunkEmbedding(
            CHUNK_A,
            _compatibility(),
            NormalizedEmbeddingVector((0.6, 0.8)),
            timestamp,
        )


def test_persisted_set_supports_ordered_partial_and_complete_results() -> None:
    partial = PersistedEmbeddingSet(
        _compatibility(),
        (CHUNK_A, CHUNK_B),
        (_embedding(CHUNK_A),),
    )
    complete = PersistedEmbeddingSet(
        _compatibility(),
        (CHUNK_A, CHUNK_B),
        (_embedding(CHUNK_A), _embedding(CHUNK_B)),
    )

    assert partial.is_complete is False
    assert complete.is_complete is True


def test_persisted_set_rejects_rows_outside_expected_positional_order() -> None:
    with pytest.raises(EmbeddingPersistenceError, match="set is invalid"):
        PersistedEmbeddingSet(
            _compatibility(),
            (CHUNK_A, CHUNK_B),
            (_embedding(CHUNK_B), _embedding(CHUNK_A)),
        )


def test_query_contract_is_ephemeral_and_contains_only_target_metadata_and_vector() -> None:
    assert tuple(field.name for field in fields(QueryEmbedding)) == (
        "compatibility",
        "vector",
    )


def test_protocols_and_errors_expose_the_minimal_application_surface() -> None:
    assert _REPOSITORY_CONFORMANCE is not None
    _CANCELLATION_CONFORMANCE.raise_if_cancelled()
    assert {
        name
        for name, value in vars(EmbeddingRepository).items()
        if callable(value) and not name.startswith("_")
    } == {"get_for_candidate", "add_batch"}
    assert {
        name
        for name, value in vars(EmbeddingCancellationCheck).items()
        if callable(value) and not name.startswith("_")
    } == {"raise_if_cancelled"}
    assert all(
        issubclass(error_type, EmbeddingError)
        for error_type in (
            InvalidEmbeddingInput,
            EmbeddingModelIncompatible,
            InvalidEmbeddingVector,
            EmbeddingProviderFailure,
            EmbeddingPersistenceError,
            EmbeddingCancelled,
        )
    )


def test_application_contract_has_no_technical_provider_or_storage_imports() -> None:
    contract_path = (
        Path(__file__).resolve().parents[4]
        / "src"
        / "lexlocal"
        / "application"
        / "ports"
        / "embeddings.py"
    )
    tree = ast.parse(contract_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert all(
        not module.startswith(
            (
                "foundry_local_sdk",
                "numpy",
                "sqlite3",
                "lexlocal.infrastructure",
                "lexlocal.bootstrap",
                "lexlocal.application.ports.security",
            )
        )
        for module in imported_modules
    )
