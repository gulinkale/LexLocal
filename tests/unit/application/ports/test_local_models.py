"""Tests for SDK-free Application-owned local-model contracts."""

import ast
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from lexlocal.application.ports.local_models import (
    ChatInferenceProvider,
    EmbeddingProvider,
    LocalModelError,
    LocalModelIncompatible,
    LocalModelInferenceError,
    LocalModelPersistenceError,
    LocalModelRuntime,
    LocalModelRuntimeError,
    LocalModelStatus,
    LocalModelUnavailable,
    ModelCapability,
    ModelReadiness,
    ResolvedModelRecord,
    ResolvedModelRepository,
)
from lexlocal.domain.identifiers import LocalModelId

MODEL_ID = LocalModelId("550e8400-e29b-41d4-a716-446655440000")


def make_record(
    *,
    capability: ModelCapability = ModelCapability.CHAT,
    dimensions: int | None = None,
) -> ResolvedModelRecord:
    return ResolvedModelRecord(
        id=MODEL_ID,
        requested_alias="synthetic-model",
        resolved_model_id="synthetic-model:1",
        model_version="1",
        capability=capability,
        provider="foundry",
        dimensions=dimensions,
    )


def test_model_capability_contains_exact_values() -> None:
    assert {capability.value for capability in ModelCapability} == {
        "CHAT",
        "EMBEDDING",
    }


def test_model_readiness_contains_only_observable_progress_states() -> None:
    assert {readiness.value for readiness in ModelReadiness} == {
        "RESOLVED",
        "READY",
    }


def test_resolved_chat_record_preserves_exact_persistable_metadata() -> None:
    record = make_record()

    assert record.id == MODEL_ID
    assert record.requested_alias == "synthetic-model"
    assert record.resolved_model_id == "synthetic-model:1"
    assert record.model_version == "1"
    assert record.capability is ModelCapability.CHAT
    assert record.provider == "foundry"
    assert record.dimensions is None


def test_embedding_record_requires_positive_dimensions() -> None:
    record = make_record(
        capability=ModelCapability.EMBEDDING,
        dimensions=384,
    )

    assert record.dimensions == 384


@pytest.mark.parametrize("dimensions", [None, 0, -1, True, 1.5, "384"])
def test_embedding_record_rejects_invalid_dimensions(dimensions: object) -> None:
    with pytest.raises(LocalModelPersistenceError):
        make_record(
            capability=ModelCapability.EMBEDDING,
            dimensions=dimensions,  # type: ignore[arg-type]
        )


def test_chat_record_rejects_dimensions() -> None:
    with pytest.raises(LocalModelPersistenceError):
        make_record(dimensions=384)


@pytest.mark.parametrize(
    "field_name",
    ["id", "requested_alias", "resolved_model_id", "capability", "provider"],
)
def test_resolved_record_is_immutable(field_name: str) -> None:
    record = make_record()

    with pytest.raises(FrozenInstanceError):
        setattr(record, field_name, None)


def test_runtime_status_keeps_runtime_only_metadata_outside_record() -> None:
    status = LocalModelStatus(
        model=make_record(),
        readiness=ModelReadiness.READY,
        execution_provider="LocalExecutionProvider",
    )

    assert tuple(field.name for field in fields(ResolvedModelRecord)) == (
        "id",
        "requested_alias",
        "resolved_model_id",
        "model_version",
        "capability",
        "provider",
        "dimensions",
    )
    assert tuple(field.name for field in fields(LocalModelStatus)) == (
        "model",
        "readiness",
        "execution_provider",
    )
    assert status.model == make_record()


def test_local_model_errors_share_one_sanitized_application_base() -> None:
    assert all(
        issubclass(error_type, LocalModelError)
        for error_type in (
            LocalModelUnavailable,
            LocalModelIncompatible,
            LocalModelRuntimeError,
            LocalModelInferenceError,
            LocalModelPersistenceError,
        )
    )


def test_ports_expose_only_the_minimal_separate_operations() -> None:
    assert {
        name
        for name, value in vars(LocalModelRuntime).items()
        if callable(value) and not name.startswith("_")
    } == {"resolve_ready", "close"}
    assert {
        name
        for name, value in vars(ChatInferenceProvider).items()
        if callable(value) and not name.startswith("_")
    } == {"generate"}
    assert {
        name
        for name, value in vars(EmbeddingProvider).items()
        if callable(value) and not name.startswith("_")
    } == {"embed"}
    assert {
        name
        for name, value in vars(ResolvedModelRepository).items()
        if callable(value) and not name.startswith("_")
    } == {"get_or_add_exact"}


def test_application_contract_has_no_sdk_or_concrete_dependency() -> None:
    contract_path = (
        Path(__file__).resolve().parents[4]
        / "src"
        / "lexlocal"
        / "application"
        / "ports"
        / "local_models.py"
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
                "openai",
                "lexlocal.infrastructure",
                "lexlocal.bootstrap",
            )
        )
        for module in imported_modules
    )
