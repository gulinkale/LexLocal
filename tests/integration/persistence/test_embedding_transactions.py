"""Integration tests for embedding orchestration transaction boundaries."""

import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.application.embeddings import EmbedStagingChunks
from lexlocal.application.ports.embeddings import EmbeddingPersistenceError
from lexlocal.application.ports.indexing import (
    ActivatedIndex,
    CandidateChunkSet,
    ChunkConfiguration,
    IndexChunk,
    LogicalChunk,
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
from lexlocal.domain.identifiers import (
    ChunkId,
    DocumentPageId,
    DocumentVersionId,
    IndexGenerationId,
    LocalModelId,
    ProcessingJobId,
    SourceLocatorId,
    WorkspaceId,
)
from lexlocal.domain.processing import IndexGeneration
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
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
)

WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
VERSION_ID = DocumentVersionId("20000000-0000-4000-8000-000000000001")
JOB_ID = ProcessingJobId("30000000-0000-4000-8000-000000000001")
MODEL_ID = LocalModelId("40000000-0000-4000-8000-000000000001")
GENERATION_ID = IndexGenerationId("50000000-0000-4000-8000-000000000001")
PAGE_ID = DocumentPageId("60000000-0000-4000-8000-000000000001")
LOCATOR_ID = SourceLocatorId("70000000-0000-4000-8000-000000000001")
CHUNK_A = ChunkId("80000000-0000-4000-8000-000000000001")
CHUNK_B = ChunkId("80000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 9, 7, 9, 15, 30, 456000, tzinfo=UTC)
TIMESTAMP = "2026-09-07T09:15:30.456Z"


class _Provider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._status = LocalModelStatus(
            ResolvedModelRecord(
                MODEL_ID,
                "synthetic-embedding",
                "synthetic/resolved-embedding",
                "1",
                ModelCapability.EMBEDDING,
                "local-synthetic",
                2,
            ),
            ModelReadiness.READY,
            "SyntheticExecutionProvider",
        )

    @property
    def status(self) -> LocalModelStatus:
        return self._status

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        exact = tuple(texts)
        self.calls.append(exact)
        return tuple((1.0, 0.0) if text == "abcd" else (0.0, 1.0) for text in exact)


class _NeverCancelled:
    def raise_if_cancelled(self) -> None:
        return None


class _FailingCommitSQLiteUnitOfWork(SQLiteUnitOfWork):
    def commit(self) -> None:
        raise RuntimeError("synthetic commit detail")


def _database(tmp_path: Path) -> tuple[SQLiteConnectionFactory, StagingEmbeddingHandoff]:
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
    return factory, StagingEmbeddingHandoff(candidate)


def _insert_graph(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN")
    connection.execute(
        "INSERT INTO workspaces (id, name_ciphertext, name_lookup_fingerprint, state, created_at, updated_at) VALUES (?, x'01', x'02', 'ACTIVE', ?, ?)",
        (str(WORKSPACE_ID), TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        "INSERT INTO documents (id, workspace_id, display_name_ciphertext, state, created_at, updated_at) VALUES ('synthetic-document', ?, x'03', 'ACTIVE', ?, ?)",
        (str(WORKSPACE_ID), TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        "INSERT INTO document_versions (id, workspace_id, document_id, version_number, historical_filename_ciphertext, page_count, state, created_at) VALUES (?, ?, 'synthetic-document', 1, x'04', 1, 'CANDIDATE_PROCESSING', ?)",
        (str(VERSION_ID), str(WORKSPACE_ID), TIMESTAMP),
    )
    connection.execute(
        "INSERT INTO document_processing_jobs (id, workspace_id, document_version_id, attempt_number, state, stage, created_at) VALUES (?, ?, ?, 1, 'PROCESSING', 'CHUNKING', ?)",
        (str(JOB_ID), str(WORKSPACE_ID), str(VERSION_ID), TIMESTAMP),
    )
    connection.execute(
        "INSERT INTO local_models (id, purpose, provider, requested_alias, resolved_model_id, dimensions, created_at) VALUES (?, 'EMBEDDING', 'synthetic', 'fixture', 'synthetic-model', 2, ?)",
        (str(MODEL_ID), TIMESTAMP),
    )
    context = SensitivePayloadContext(
        WORKSPACE_ID,
        str(PAGE_ID),
        "document-page-text",
        1,
    )
    page_payload = InsecureDevelopmentOnlyPayloadCodec().encode(
        b"abcdefgh",
        context=context,
        key_reference=WorkspaceKeyReference(WORKSPACE_ID, 1),
    ).payload
    connection.execute(
        "INSERT INTO document_pages (id, workspace_id, document_version_id, page_number, state, extraction_method, text_ciphertext, character_count, created_at, updated_at) VALUES (?, ?, ?, 1, 'READY', 'NATIVE', ?, 8, ?, ?)",
        (str(PAGE_ID), str(WORKSPACE_ID), str(VERSION_ID), page_payload, TIMESTAMP, TIMESTAMP),
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


def _scope() -> ActiveWorkspaceScope:
    scope = ActiveWorkspaceScope()
    scope.select(WORKSPACE_ID)
    return scope


def _normal_uow_factory(
    factory: SQLiteConnectionFactory,
) -> Callable[[], SQLiteUnitOfWork]:
    return lambda: SQLiteUnitOfWork(
        factory,
        InsecureDevelopmentOnlyWorkspaceNamePersistence(),
        InsecureDevelopmentOnlyPayloadCodec(),
    )


def _unexpected_finalizer(handoff: StagingEmbeddingHandoff) -> ActivatedIndex:
    raise AssertionError("finalizer must not run")


def _stored_chunk_ids(factory: SQLiteConnectionFactory) -> tuple[str, ...]:
    connection = factory.create()
    try:
        return tuple(
            row["chunk_id"]
            for row in connection.execute(
                "SELECT chunk_id FROM embeddings ORDER BY chunk_id"
            ).fetchall()
        )
    finally:
        connection.close()


def test_commit_failure_rolls_back_the_whole_batch(tmp_path: Path) -> None:
    factory, handoff = _database(tmp_path)
    provider = _Provider()

    def failing_uow_factory() -> SQLiteUnitOfWork:
        return _FailingCommitSQLiteUnitOfWork(
            factory,
            InsecureDevelopmentOnlyWorkspaceNamePersistence(),
            InsecureDevelopmentOnlyPayloadCodec(),
        )

    with pytest.raises(EmbeddingPersistenceError) as caught:
        EmbedStagingChunks(
            _scope(),
            provider,
            _NeverCancelled(),
            failing_uow_factory,
            _unexpected_finalizer,
            lambda: NOW,
            2,
        )(handoff)

    assert "synthetic commit detail" not in str(caught.value)
    assert provider.calls == [("abcd", "efgh")]
    assert _stored_chunk_ids(factory) == ()


def test_failed_later_batch_preserves_only_prior_committed_batch(tmp_path: Path) -> None:
    factory, handoff = _database(tmp_path)
    connection = factory.create()
    connection.execute(
        """
        CREATE TRIGGER reject_second_synthetic_embedding
        BEFORE INSERT ON embeddings
        WHEN NEW.chunk_id = '80000000-0000-4000-8000-000000000002'
        BEGIN
            SELECT RAISE(ABORT, 'synthetic write detail');
        END
        """
    )
    connection.close()
    provider = _Provider()

    with pytest.raises(EmbeddingPersistenceError) as caught:
        EmbedStagingChunks(
            _scope(),
            provider,
            _NeverCancelled(),
            _normal_uow_factory(factory),
            _unexpected_finalizer,
            lambda: NOW,
            1,
        )(handoff)

    assert "synthetic write detail" not in str(caught.value)
    assert provider.calls == [("abcd",), ("efgh",)]
    assert _stored_chunk_ids(factory) == (str(CHUNK_A),)
