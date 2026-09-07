"""End-to-end tests for the synthetic local embedding slice."""

import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.application.indexing import FinalizeIndexing
from lexlocal.application.ports.embeddings import (
    EmbeddingCancelled,
    EmbeddingModelIncompatible,
    EmbeddingPersistenceError,
    QueryEmbedding,
)
from lexlocal.application.ports.indexing import (
    ActivatedIndex,
    CandidateChunkSet,
    ChunkConfiguration,
    IndexChunk,
    IndexingPersistenceError,
    LogicalChunk,
    PersistedIndexGeneration,
    StagingEmbeddingHandoff,
)
from lexlocal.application.ports.local_models import (
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
    ResolvedModelRecord,
)
from lexlocal.application.ports.processing import PageExtractionMethod
from lexlocal.application.ports.security import (
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.bootstrap import embeddings as embeddings_bootstrap
from lexlocal.bootstrap.embeddings import compose_embedding_application
from lexlocal.bootstrap.foundry import LocalModelComposition
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import (
    ChunkId,
    DocumentId,
    DocumentPageId,
    DocumentVersionId,
    IndexGenerationId,
    LocalModelId,
    ProcessingJobId,
    SourceLocatorId,
    WorkspaceId,
)
from lexlocal.domain.processing import IndexGeneration, IndexGenerationState
from lexlocal.domain.retrieval import PageNumber
from lexlocal.infrastructure.persistence.migration_runner import run_migrations
from lexlocal.infrastructure.persistence.migrations import (
    default_migrations_dir,
    discover_migrations,
)
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.persistence.sqlite_index_repository import (
    SQLiteIndexRepository,
)
from lexlocal.infrastructure.persistence.sqlite_unit_of_work import SQLiteUnitOfWork
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyPayloadCodec,
)
from lexlocal.infrastructure.security.insecure_development_indexing import (
    InsecureDevelopmentOnlyChunkEqualityToken,
)

WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
OTHER_WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000002")
DOCUMENT_ID = DocumentId("20000000-0000-4000-8000-000000000001")
VERSION_ID = DocumentVersionId("30000000-0000-4000-8000-000000000001")
JOB_ID = ProcessingJobId("40000000-0000-4000-8000-000000000001")
MODEL_ID = LocalModelId("50000000-0000-4000-8000-000000000001")
OTHER_MODEL_ID = LocalModelId("50000000-0000-4000-8000-000000000002")
CHAT_MODEL_ID = LocalModelId("50000000-0000-4000-8000-000000000003")
GENERATION_ID = IndexGenerationId("60000000-0000-4000-8000-000000000001")
PAGE_ID = DocumentPageId("70000000-0000-4000-8000-000000000001")
LOCATOR_ID = SourceLocatorId("80000000-0000-4000-8000-000000000001")
CHUNK_A = ChunkId("90000000-0000-4000-8000-000000000001")
CHUNK_B = ChunkId("90000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 9, 7, 14, 30, 0, 123000, tzinfo=UTC)
TIMESTAMP = "2026-09-07T14:30:00.123Z"


class _Provider:
    def __init__(
        self,
        model_id: LocalModelId = MODEL_ID,
        readiness: ModelReadiness = ModelReadiness.READY,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._status = LocalModelStatus(
            ResolvedModelRecord(
                model_id,
                "qwen3-embedding-0.6b",
                "synthetic-resolved-embedding",
                "1",
                ModelCapability.EMBEDDING,
                "synthetic-local",
                2,
            ),
            readiness,
            "synthetic-execution",
        )

    @property
    def status(self) -> LocalModelStatus:
        return self._status

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        exact = tuple(texts)
        self.calls.append(exact)
        return tuple(
            (3.0, 4.0) if text in {"abcd", "anonymous query"} else (4.0, 3.0)
            for text in exact
        )


class _ChatProvider:
    @property
    def status(self) -> LocalModelStatus:
        return LocalModelStatus(
            ResolvedModelRecord(
                CHAT_MODEL_ID,
                "qwen3-4b",
                "synthetic-resolved-chat",
                "1",
                ModelCapability.CHAT,
                "synthetic-local",
            ),
            ModelReadiness.READY,
            "synthetic-execution",
        )

    def generate(self, prompt: str) -> str:
        raise AssertionError("chat provider is outside the embedding slice")


class _NeverCancelled:
    def raise_if_cancelled(self) -> None:
        return None


class _Cancelled:
    def raise_if_cancelled(self) -> None:
        raise EmbeddingCancelled("synthetic cancellation detail")


class _FailingCommitUnitOfWork(SQLiteUnitOfWork):
    def commit(self) -> None:
        raise RuntimeError("synthetic commit detail")


def _settings(tmp_path: Path, *, batch_size: int = 32) -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment="test",
        log_level="INFO",
        data_dir=tmp_path,
        security_provider="insecure-development-only",
        embedding_batch_size=batch_size,
    )


def _local_models(provider: _Provider) -> LocalModelComposition:
    chat = _ChatProvider()
    return LocalModelComposition(
        chat,
        provider,
        chat.status,
        provider.status,
        lambda: None,
    )


def _database(
    tmp_path: Path,
) -> tuple[SQLiteConnectionFactory, StagingEmbeddingHandoff, ActiveWorkspaceScope]:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    connection = factory.create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
    _insert_graph(connection)
    candidate = _candidate()
    connection.execute("BEGIN")
    SQLiteIndexRepository(
        connection,
        InsecureDevelopmentOnlyPayloadCodec(),
    ).stage_candidate(candidate)
    connection.commit()
    connection.close()
    scope = ActiveWorkspaceScope()
    scope.select(WORKSPACE_ID)
    return factory, StagingEmbeddingHandoff(candidate), scope


def _insert_graph(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN")
    connection.execute(
        "INSERT INTO workspaces (id, name_ciphertext, name_lookup_fingerprint, state, created_at, updated_at) VALUES (?, x'01', x'02', 'ACTIVE', ?, ?)",
        (str(WORKSPACE_ID), TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        "INSERT INTO documents (id, workspace_id, display_name_ciphertext, state, created_at, updated_at) VALUES (?, ?, x'03', 'ACTIVE', ?, ?)",
        (str(DOCUMENT_ID), str(WORKSPACE_ID), TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        "INSERT INTO document_versions (id, workspace_id, document_id, version_number, historical_filename_ciphertext, page_count, state, created_at) VALUES (?, ?, ?, 1, x'04', 1, 'CANDIDATE_PROCESSING', ?)",
        (str(VERSION_ID), str(WORKSPACE_ID), str(DOCUMENT_ID), TIMESTAMP),
    )
    connection.execute(
        "INSERT INTO document_processing_jobs (id, workspace_id, document_version_id, attempt_number, state, stage, created_at) VALUES (?, ?, ?, 1, 'PROCESSING', 'CHUNKING', ?)",
        (str(JOB_ID), str(WORKSPACE_ID), str(VERSION_ID), TIMESTAMP),
    )
    connection.execute(
        "INSERT INTO local_models (id, purpose, provider, requested_alias, resolved_model_id, model_version, dimensions, created_at) VALUES (?, 'EMBEDDING', 'synthetic-local', 'qwen3-embedding-0.6b', 'synthetic-resolved-embedding', '1', 2, ?)",
        (str(MODEL_ID), TIMESTAMP),
    )
    codec = InsecureDevelopmentOnlyPayloadCodec()
    context = SensitivePayloadContext(
        WORKSPACE_ID,
        str(PAGE_ID),
        "document-page-text",
        1,
    )
    payload = codec.encode(
        b"abcdefgh",
        context=context,
        key_reference=WorkspaceKeyReference(WORKSPACE_ID, 1),
    ).payload
    connection.execute(
        "INSERT INTO document_pages (id, workspace_id, document_version_id, page_number, state, extraction_method, text_ciphertext, character_count, created_at, updated_at) VALUES (?, ?, ?, 1, 'READY', 'NATIVE', ?, 8, ?, ?)",
        (str(PAGE_ID), str(WORKSPACE_ID), str(VERSION_ID), payload, TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        "INSERT INTO source_locators (id, workspace_id, document_version_id, page_id, locator_kind, page_number, locator_version, created_at) VALUES (?, ?, ?, ?, 'PAGE', 1, 1, ?)",
        (str(LOCATOR_ID), str(WORKSPACE_ID), str(VERSION_ID), str(PAGE_ID), TIMESTAMP),
    )
    connection.commit()


def _candidate() -> CandidateChunkSet:
    profile = ChunkConfiguration(4, 0).profile
    generation = IndexGeneration(
        GENERATION_ID,
        WORKSPACE_ID,
        VERSION_ID,
        JOB_ID,
        MODEL_ID,
        profile.value,
        "exact-text-v1",
        2,
    )
    token = InsecureDevelopmentOnlyChunkEqualityToken()
    chunks = []
    for order, (chunk_id, start, end, text) in enumerate(
        ((CHUNK_A, 0, 4, "abcd"), (CHUNK_B, 4, 8, "efgh"))
    ):
        logical = LogicalChunk(
            WORKSPACE_ID,
            VERSION_ID,
            PAGE_ID,
            PageNumber(1),
            LOCATOR_ID,
            order,
            order,
            start,
            end,
            text,
            PageExtractionMethod.NATIVE,
            profile,
        )
        chunks.append(IndexChunk(chunk_id, logical, token.fingerprint(logical), NOW))
    return CandidateChunkSet(generation, tuple(chunks), NOW)


def _counts(factory: SQLiteConnectionFactory) -> tuple[int, int]:
    connection = factory.create()
    try:
        return (
            connection.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0],
            connection.execute(
                "SELECT COUNT(*) FROM index_generations WHERE state = 'ACTIVE'"
            ).fetchone()[0],
        )
    finally:
        connection.close()


def test_synthetic_chunks_activate_and_query_remains_ephemeral(tmp_path: Path) -> None:
    factory, handoff, scope = _database(tmp_path)
    provider = _Provider()
    composition = compose_embedding_application(
        _settings(tmp_path, batch_size=1),
        factory,
        scope,
        _local_models(provider),
        clock=lambda: NOW,
    )

    activated = composition.embed_staging_chunks(handoff)

    assert isinstance(activated, ActivatedIndex)
    assert activated.generation.state is IndexGenerationState.ACTIVE
    assert provider.calls == [("abcd",), ("efgh",)]
    assert _counts(factory) == (2, 1)

    target = PersistedIndexGeneration(activated.generation, NOW, NOW)
    before = _counts(factory)
    query = composition.embed_query("anonymous query", target)

    assert isinstance(query, QueryEmbedding)
    assert query.compatibility.embedding_model_id == MODEL_ID
    assert query.compatibility.index_generation_id == GENERATION_ID
    assert query.vector.values == pytest.approx((0.6, 0.8))
    assert provider.calls[-1] == ("anonymous query",)
    assert _counts(factory) == before
    assert not hasattr(activated, "connection")
    assert not hasattr(query, "provider")


def test_finalizer_failure_then_identical_retry_reuses_embeddings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, handoff, scope = _database(tmp_path)
    provider = _Provider()

    class _FailingFinalizer:
        def __init__(self, *arguments: object) -> None:
            pass

        def __call__(self, handoff: StagingEmbeddingHandoff) -> ActivatedIndex:
            raise IndexingPersistenceError("synthetic finalizer detail")

    monkeypatch.setattr(embeddings_bootstrap, "FinalizeIndexing", _FailingFinalizer)
    failed = compose_embedding_application(
        _settings(tmp_path), factory, scope, _local_models(provider), clock=lambda: NOW
    )
    with pytest.raises(EmbeddingPersistenceError) as caught:
        failed.embed_staging_chunks(handoff)

    assert "synthetic finalizer detail" not in str(caught.value)
    assert _counts(factory) == (2, 0)
    first_calls = tuple(provider.calls)

    monkeypatch.setattr(embeddings_bootstrap, "FinalizeIndexing", FinalizeIndexing)
    resumed = compose_embedding_application(
        _settings(tmp_path), factory, scope, _local_models(provider), clock=lambda: NOW
    )
    result = resumed.embed_staging_chunks(handoff)

    assert result.generation.state is IndexGenerationState.ACTIVE
    assert tuple(provider.calls) == first_calls
    assert _counts(factory) == (2, 1)


def test_commit_failure_rolls_back_and_never_activates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, handoff, scope = _database(tmp_path)
    provider = _Provider()
    monkeypatch.setattr(
        embeddings_bootstrap,
        "SQLiteUnitOfWork",
        _FailingCommitUnitOfWork,
    )
    composition = compose_embedding_application(
        _settings(tmp_path), factory, scope, _local_models(provider), clock=lambda: NOW
    )

    with pytest.raises(EmbeddingPersistenceError) as caught:
        composition.embed_staging_chunks(handoff)

    assert "synthetic commit detail" not in str(caught.value)
    assert _counts(factory) == (0, 0)


def test_write_failure_rolls_back_and_never_activates(tmp_path: Path) -> None:
    factory, handoff, scope = _database(tmp_path)
    connection = factory.create()
    connection.execute(
        """
        CREATE TRIGGER reject_synthetic_embedding
        BEFORE INSERT ON embeddings
        BEGIN
            SELECT RAISE(ABORT, 'synthetic write detail');
        END
        """
    )
    connection.close()
    provider = _Provider()
    composition = compose_embedding_application(
        _settings(tmp_path), factory, scope, _local_models(provider), clock=lambda: NOW
    )

    with pytest.raises(EmbeddingPersistenceError) as caught:
        composition.embed_staging_chunks(handoff)

    assert "synthetic write detail" not in str(caught.value)
    assert _counts(factory) == (0, 0)


def test_cancellation_stops_before_vector_or_database_work(tmp_path: Path) -> None:
    factory, handoff, scope = _database(tmp_path)
    provider = _Provider()
    composition = compose_embedding_application(
        _settings(tmp_path),
        factory,
        scope,
        _local_models(provider),
        cancellation=_Cancelled(),
        clock=lambda: NOW,
    )

    with pytest.raises(EmbeddingCancelled) as caught:
        composition.embed_staging_chunks(handoff)

    assert "synthetic cancellation detail" not in str(caught.value)
    assert provider.calls == []
    assert _counts(factory) == (0, 0)


@pytest.mark.parametrize("substitution", ["workspace", "model", "not-ready"])
def test_incompatible_scope_or_model_status_fails_before_persistence(
    tmp_path: Path,
    substitution: str,
) -> None:
    factory, handoff, scope = _database(tmp_path)
    provider = _Provider(
        OTHER_MODEL_ID if substitution == "model" else MODEL_ID,
        ModelReadiness.RESOLVED
        if substitution == "not-ready"
        else ModelReadiness.READY,
    )
    if substitution == "workspace":
        scope.select(OTHER_WORKSPACE_ID)
    composition = compose_embedding_application(
        _settings(tmp_path), factory, scope, _local_models(provider), clock=lambda: NOW
    )

    with pytest.raises(EmbeddingModelIncompatible):
        composition.embed_staging_chunks(handoff)

    assert provider.calls == []
    assert _counts(factory) == (0, 0)
