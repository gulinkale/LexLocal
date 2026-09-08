"""Unit tests for Bootstrap-owned retrieval composition."""

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.application.ports.retrieval import RetrievalConfiguration
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.bootstrap import retrieval as retrieval_bootstrap
from lexlocal.bootstrap.retrieval import compose_retrieval_application
from lexlocal.bootstrap.security import SecurityProviderConfigurationError
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import EvidenceItemId, RetrievalRunId
from lexlocal.domain.retrieval import SimilarityScore
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyPayloadCodec,
)

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
RUN_ID = RetrievalRunId("10000000-0000-4000-8000-000000000001")
EVIDENCE_ID = EvidenceItemId("20000000-0000-4000-8000-000000000001")


def _settings(tmp_path: Path, *, environment: str = "test") -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment=environment,
        log_level="INFO",
        data_dir=tmp_path,
        security_provider="insecure-development-only",
        retrieval_top_k=7,
        retrieval_min_similarity=-0.25,
    )


class _EmbeddingComposition:
    def __init__(self, embed_query: object) -> None:
        self.embed_query = embed_query


def test_composition_reuses_embed_query_and_only_wires_existing_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, tuple[object, ...]] = {}
    query = object()
    scope = ActiveWorkspaceScope()

    class _UnitOfWork:
        def __init__(self, *arguments: object) -> None:
            captured["unit_of_work"] = arguments

    class _Prepare:
        def __init__(self, *arguments: object) -> None:
            captured["prepare"] = arguments

    class _Stage:
        def __init__(self, *arguments: object) -> None:
            captured["stage"] = arguments

    monkeypatch.setattr(retrieval_bootstrap, "SQLiteUnitOfWork", _UnitOfWork)
    monkeypatch.setattr(retrieval_bootstrap, "PrepareRetrieval", _Prepare)
    monkeypatch.setattr(retrieval_bootstrap, "StageRetrieval", _Stage)

    composition = compose_retrieval_application(
        _settings(tmp_path),
        SQLiteConnectionFactory(tmp_path / "unused.db"),
        scope,
        _EmbeddingComposition(query),  # type: ignore[arg-type]
        retrieval_run_id_factory=lambda: RUN_ID,
        evidence_item_id_factory=lambda: EVIDENCE_ID,
        clock=lambda: NOW,
    )

    prepare = captured["prepare"]
    assert prepare[0] is scope
    assert prepare[2] is query
    assert prepare[3]() == RUN_ID
    assert prepare[4]() == EVIDENCE_ID
    assert prepare[5]() == NOW
    assert captured["stage"] == (scope,)
    assert composition.configuration == RetrievalConfiguration(
        7,
        SimilarityScore(-0.25),
    )
    assert composition.prepare_retrieval.__class__ is _Prepare
    assert composition.stage_retrieval.__class__ is _Stage

    prepare[1]()
    arguments = captured["unit_of_work"]
    assert arguments[0].database_path == tmp_path / "unused.db"
    assert isinstance(arguments[2], InsecureDevelopmentOnlyPayloadCodec)


def test_production_fails_closed_before_embedding_composition_access(
    tmp_path: Path,
) -> None:
    class _ForbiddenEmbeddings:
        @property
        def embed_query(self) -> object:
            raise AssertionError("embedding path must not be accessed")

    with pytest.raises(SecurityProviderConfigurationError):
        compose_retrieval_application(
            _settings(tmp_path, environment="production"),
            SQLiteConnectionFactory(tmp_path / "unused.db"),
            ActiveWorkspaceScope(),
            _ForbiddenEmbeddings(),  # type: ignore[arg-type]
        )


def test_bootstrap_module_has_no_retrieval_or_provider_business_logic() -> None:
    module_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "lexlocal"
        / "bootstrap"
        / "retrieval.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(
        module.startswith(
            (
                "foundry_local_sdk",
                "lexlocal.infrastructure.foundry",
                "lexlocal.infrastructure.persistence.sqlite_retrieval_repository",
            )
        )
        for module in imported_modules
    )
