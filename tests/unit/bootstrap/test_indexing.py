"""Unit tests for Bootstrap-owned indexing composition."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.application.ports.indexing import (
    InvalidChunkConfiguration,
    InvalidIndexingInput,
)
from lexlocal.application.ports.local_models import (
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
    ResolvedModelRecord,
)
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.bootstrap import indexing as indexing_bootstrap
from lexlocal.bootstrap.indexing import compose_indexing_application
from lexlocal.bootstrap.security import SecurityProviderConfigurationError
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import ChunkId, IndexGenerationId, LocalModelId
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyPayloadCodec,
)
from lexlocal.infrastructure.security.insecure_development_indexing import (
    InsecureDevelopmentOnlyChunkEqualityToken,
)

NOW = datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)
MODEL = ResolvedModelRecord(
    LocalModelId("10000000-0000-4000-8000-000000000001"),
    "qwen3-embedding-0.6b",
    "synthetic-resolved",
    "1",
    ModelCapability.EMBEDDING,
    "synthetic",
    8,
)


def _settings(
    tmp_path: Path,
    *,
    environment: str = "test",
    chunk_size: int = 1000,
    overlap: int = 200,
) -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment=environment,
        log_level="INFO",
        data_dir=tmp_path,
        security_provider="insecure-development-only",
        index_chunk_size=chunk_size,
        index_chunk_overlap=overlap,
    )


def _status(
    *,
    model: ResolvedModelRecord = MODEL,
    readiness: ModelReadiness = ModelReadiness.READY,
) -> LocalModelStatus:
    return LocalModelStatus(model, readiness, "synthetic-execution")


def test_composition_wires_exact_configuration_model_and_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    scope = ActiveWorkspaceScope()
    codec = InsecureDevelopmentOnlyPayloadCodec()
    chunk_id = ChunkId("20000000-0000-4000-8000-000000000001")
    generation_id = IndexGenerationId("30000000-0000-4000-8000-000000000001")

    class _UseCase:
        def __init__(self, *arguments: object) -> None:
            captured["arguments"] = arguments

        def __call__(self, processing: object, configuration: object) -> object:
            captured["call"] = (processing, configuration)
            return "synthetic-result"

    monkeypatch.setattr(indexing_bootstrap, "PrepareIndexing", _UseCase)
    composition = compose_indexing_application(
        _settings(tmp_path, chunk_size=256, overlap=32),
        SQLiteConnectionFactory(tmp_path / "unused.db"),
        scope,
        _status(),
        sensitive_payload_codec=codec,
        chunk_id_factory=lambda: chunk_id,
        index_generation_id_factory=lambda: generation_id,
        clock=lambda: NOW,
    )

    assert composition.configuration.chunk_size == 256
    assert composition.configuration.overlap == 32
    arguments = captured["arguments"]
    assert isinstance(arguments, tuple)
    assert arguments[0] is scope
    assert arguments[1] is MODEL
    assert isinstance(arguments[3], InsecureDevelopmentOnlyChunkEqualityToken)
    assert arguments[5]() == chunk_id
    assert arguments[6]() == generation_id
    assert arguments[7]() == NOW
    sentinel = object()
    assert composition.prepare_index(sentinel) == "synthetic-result"  # type: ignore[arg-type]
    assert captured["call"] == (sentinel, composition.configuration)
    with pytest.raises(RuntimeError, match="transaction is not active"):
        _ = composition.unit_of_work_factory().indexing


def test_production_rejects_insecure_indexing_before_composition(
    tmp_path: Path,
) -> None:
    with pytest.raises(SecurityProviderConfigurationError):
        compose_indexing_application(
            _settings(tmp_path, environment="production"),
            SQLiteConnectionFactory(tmp_path / "unused.db"),
            ActiveWorkspaceScope(),
            _status(),
        )


@pytest.mark.parametrize(
    ("chunk_size", "overlap"),
    [(0, 0), (100, -1), (100, 100), (100, 101)],
)
def test_invalid_index_configuration_fails_during_composition(
    tmp_path: Path, chunk_size: int, overlap: int
) -> None:
    with pytest.raises(InvalidChunkConfiguration):
        compose_indexing_application(
            _settings(tmp_path, chunk_size=chunk_size, overlap=overlap),
            SQLiteConnectionFactory(tmp_path / "unused.db"),
            ActiveWorkspaceScope(),
            _status(),
        )


def test_non_ready_or_incompatible_model_metadata_fails_closed(tmp_path: Path) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "unused.db")
    with pytest.raises(InvalidIndexingInput, match="status is unavailable"):
        compose_indexing_application(
            _settings(tmp_path),
            factory,
            ActiveWorkspaceScope(),
            None,  # type: ignore[arg-type]
        )
    with pytest.raises(InvalidIndexingInput, match="status is unavailable"):
        compose_indexing_application(
            _settings(tmp_path),
            factory,
            ActiveWorkspaceScope(),
            _status(readiness=ModelReadiness.RESOLVED),
        )
    chat_model = ResolvedModelRecord(
        LocalModelId("10000000-0000-4000-8000-000000000002"),
        "chat",
        "chat-resolved",
        None,
        ModelCapability.CHAT,
        "synthetic",
    )
    with pytest.raises(InvalidIndexingInput, match="status is unavailable"):
        compose_indexing_application(
            _settings(tmp_path),
            factory,
            ActiveWorkspaceScope(),
            _status(model=chat_model),
        )
