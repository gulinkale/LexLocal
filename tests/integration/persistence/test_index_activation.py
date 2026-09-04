"""Integration tests for guarded atomic index activation."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.application.indexing import FinalizeIndexing
from lexlocal.application.ports.indexing import (
    ActivatedIndex,
    CandidateChunkSet,
    ChunkConfiguration,
    IndexChunk,
    IndexingCancelled,
    IndexingPersistenceError,
    InvalidIndexingInput,
    LogicalChunk,
    StagingEmbeddingHandoff,
)
from lexlocal.application.ports.processing import PageExtractionMethod
from lexlocal.application.ports.security import (
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
from lexlocal.application.workspaces import ActiveWorkspaceScope
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
from lexlocal.domain.processing import IndexGeneration
from lexlocal.domain.retrieval import PageNumber
from lexlocal.infrastructure.persistence.migration_runner import run_migrations
from lexlocal.infrastructure.persistence.migrations import (
    default_migrations_dir,
    discover_migrations,
)
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.persistence.sqlite_index_repository import SQLiteIndexRepository
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
CHUNK_ID = ChunkId("80000000-0000-4000-8000-000000000001")
DOCUMENT_ID = DocumentId("90000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)


class _NeverCancelled:
    def raise_if_cancelled(self) -> None:
        return None


class _Cancelled:
    def raise_if_cancelled(self) -> None:
        raise IndexingCancelled("fixture detail")


class _FailingCommitUnitOfWork(SQLiteUnitOfWork):
    def commit(self) -> None:
        raise RuntimeError("sensitive commit detail")


def _encode_page(text: str) -> bytes:
    codec = InsecureDevelopmentOnlyPayloadCodec()
    context = SensitivePayloadContext(WORKSPACE_ID, str(PAGE_ID), "document-page-text", 1)
    return codec.encode(
        text.encode(),
        context=context,
        key_reference=WorkspaceKeyReference(WORKSPACE_ID, 1),
    ).payload


def _candidate() -> CandidateChunkSet:
    profile = ChunkConfiguration(20, 0).profile
    generation = IndexGeneration(
        GENERATION_ID,
        WORKSPACE_ID,
        VERSION_ID,
        JOB_ID,
        MODEL_ID,
        profile.value,
        "exact-text-v1",
        8,
    )
    logical = LogicalChunk(
        WORKSPACE_ID,
        VERSION_ID,
        PAGE_ID,
        PageNumber(1),
        LOCATOR_ID,
        0,
        0,
        0,
        9,
        "synthetic",
        PageExtractionMethod.NATIVE,
        profile,
    )
    chunk = IndexChunk(
        CHUNK_ID,
        logical,
        InsecureDevelopmentOnlyChunkEqualityToken().fingerprint(logical),
        NOW,
    )
    return CandidateChunkSet(generation, (chunk,), NOW)


def _prepare_database(
    tmp_path: Path,
    *,
    warning: bool = False,
    previous_active: bool = False,
) -> tuple[SQLiteConnectionFactory, StagingEmbeddingHandoff]:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    connection = factory.create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
    timestamp = "2026-01-01T00:00:00.000Z"
    connection.execute("BEGIN")
    connection.execute(
        "INSERT INTO workspaces (id, name_ciphertext, name_lookup_fingerprint, state, created_at, updated_at) VALUES (?, x'01', x'02', 'ACTIVE', ?, ?)",
        (str(WORKSPACE_ID), timestamp, timestamp),
    )
    connection.execute(
        "INSERT INTO documents (id, workspace_id, display_name_ciphertext, state, created_at, updated_at) VALUES (?, ?, x'03', 'ACTIVE', ?, ?)",
        (str(DOCUMENT_ID), str(WORKSPACE_ID), timestamp, timestamp),
    )
    if previous_active:
        connection.execute(
            "INSERT INTO document_versions (id, workspace_id, document_id, version_number, historical_filename_ciphertext, state, created_at, activated_at) VALUES ('20000000-0000-4000-8000-000000000099', ?, ?, 1, x'04', 'ACTIVE', ?, ?)",
            (str(WORKSPACE_ID), str(DOCUMENT_ID), timestamp, timestamp),
        )
        connection.execute(
            "INSERT INTO document_processing_jobs (id, workspace_id, document_version_id, attempt_number, state, stage, created_at, completed_at) VALUES ('30000000-0000-4000-8000-000000000099', ?, '20000000-0000-4000-8000-000000000099', 1, 'READY', 'CHUNKING', ?, ?)",
            (str(WORKSPACE_ID), timestamp, timestamp),
        )
    connection.execute(
        "INSERT INTO document_versions (id, workspace_id, document_id, version_number, historical_filename_ciphertext, page_count, state, created_at) VALUES (?, ?, ?, 2, x'04', ?, 'CANDIDATE_PROCESSING', ?)",
        (
            str(VERSION_ID),
            str(WORKSPACE_ID),
            str(DOCUMENT_ID),
            2 if warning else 1,
            timestamp,
        ),
    )
    connection.execute(
        "INSERT INTO document_processing_jobs (id, workspace_id, document_version_id, attempt_number, state, stage, created_at) VALUES (?, ?, ?, 1, 'PROCESSING', 'CHUNKING', ?)",
        (str(JOB_ID), str(WORKSPACE_ID), str(VERSION_ID), timestamp),
    )
    connection.execute(
        "INSERT INTO local_models (id, purpose, provider, requested_alias, resolved_model_id, dimensions, created_at) VALUES (?, 'EMBEDDING', 'synthetic', 'fixture', 'fixture-model', 8, ?)",
        (str(MODEL_ID), timestamp),
    )
    if previous_active:
        connection.execute(
            "INSERT INTO index_generations (id, workspace_id, document_version_id, processing_job_id, state, embedding_model_id, chunking_profile_version, normalization_profile_version, embedding_dimensions, vector_dtype, chunk_count, created_at, activated_at) VALUES ('50000000-0000-4000-8000-000000000099', ?, '20000000-0000-4000-8000-000000000099', '30000000-0000-4000-8000-000000000099', 'ACTIVE', ?, 'prior', 'exact-text-v1', 8, 'float32', 0, ?, ?)",
            (str(WORKSPACE_ID), str(MODEL_ID), timestamp, timestamp),
        )
    connection.execute(
        "INSERT INTO document_pages (id, workspace_id, document_version_id, page_number, state, extraction_method, text_ciphertext, character_count, created_at, updated_at) VALUES (?, ?, ?, 1, 'READY', 'NATIVE', ?, 9, ?, ?)",
        (
            str(PAGE_ID),
            str(WORKSPACE_ID),
            str(VERSION_ID),
            _encode_page("synthetic"),
            timestamp,
            timestamp,
        ),
    )
    connection.execute(
        "INSERT INTO source_locators (id, workspace_id, document_version_id, page_id, locator_kind, page_number, locator_version, created_at) VALUES (?, ?, ?, ?, 'PAGE', 1, 1, ?)",
        (str(LOCATOR_ID), str(WORKSPACE_ID), str(VERSION_ID), str(PAGE_ID), timestamp),
    )
    if warning:
        warning_page = "60000000-0000-4000-8000-000000000002"
        connection.execute(
            "INSERT INTO document_pages (id, workspace_id, document_version_id, page_number, state, extraction_method, text_ciphertext, character_count, created_at, updated_at) VALUES (?, ?, ?, 2, 'WARNING', 'NATIVE', x'', 0, ?, ?)",
            (warning_page, str(WORKSPACE_ID), str(VERSION_ID), timestamp, timestamp),
        )
    connection.commit()
    connection.execute("BEGIN")
    candidate = _candidate()
    SQLiteIndexRepository(connection, InsecureDevelopmentOnlyPayloadCodec()).stage_candidate(
        candidate
    )
    connection.commit()
    connection.close()
    return factory, StagingEmbeddingHandoff(candidate)


def _insert_embedding(factory: SQLiteConnectionFactory) -> None:
    connection = factory.create()
    connection.execute(
        "INSERT INTO embeddings (chunk_id, workspace_id, index_generation_id, embedding_model_id, dimensions, dtype, is_unit_normalized, vector_ciphertext, created_at) VALUES (?, ?, ?, ?, 8, 'float32', 1, x'0102', ?)",
        (
            str(CHUNK_ID),
            str(WORKSPACE_ID),
            str(GENERATION_ID),
            str(MODEL_ID),
            "2026-01-01T00:00:00.000Z",
        ),
    )
    connection.commit()
    connection.close()


def _finalizer(
    factory: SQLiteConnectionFactory,
    *,
    cancellation: _NeverCancelled | _Cancelled | None = None,
    uow_type: type[SQLiteUnitOfWork] = SQLiteUnitOfWork,
) -> FinalizeIndexing:
    scope = ActiveWorkspaceScope()
    scope.select(WORKSPACE_ID)
    return FinalizeIndexing(
        scope,
        cancellation or _NeverCancelled(),
        lambda: uow_type(
            factory,
            InsecureDevelopmentOnlyWorkspaceNamePersistence(),
            InsecureDevelopmentOnlyPayloadCodec(),
        ),
        lambda: NOW,
    )


@pytest.mark.parametrize(
    ("warning", "expected_job_state"),
    [(False, "READY"), (True, "READY_WITH_WARNINGS")],
)
def test_complete_compatible_embeddings_activate_atomically(
    tmp_path: Path, warning: bool, expected_job_state: str
) -> None:
    factory, handoff = _prepare_database(tmp_path, warning=warning)
    _insert_embedding(factory)

    result = _finalizer(factory)(handoff)

    assert isinstance(result, ActivatedIndex)
    connection = factory.create()
    generation = connection.execute(
        "SELECT state, activated_at FROM index_generations WHERE id = ?",
        (str(GENERATION_ID),),
    ).fetchone()
    version = connection.execute(
        "SELECT state, activated_at FROM document_versions WHERE id = ?",
        (str(VERSION_ID),),
    ).fetchone()
    job = connection.execute(
        "SELECT state, completed_at FROM document_processing_jobs WHERE id = ?",
        (str(JOB_ID),),
    ).fetchone()
    assert generation["state"] == version["state"] == "ACTIVE"
    assert job["state"] == expected_job_state
    assert generation["activated_at"] == version["activated_at"] == job["completed_at"]
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM index_generations WHERE state = 'ACTIVE'"
        ).fetchone()[0]
        == 1
    )
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM document_versions WHERE state = 'ACTIVE'"
        ).fetchone()[0]
        == 1
    )
    connection.close()


def test_success_archives_the_supported_previous_active_pair(tmp_path: Path) -> None:
    factory, handoff = _prepare_database(tmp_path, previous_active=True)
    _insert_embedding(factory)

    _finalizer(factory)(handoff)

    connection = factory.create()
    assert (
        connection.execute(
            "SELECT state FROM document_versions WHERE id = '20000000-0000-4000-8000-000000000099'"
        ).fetchone()[0]
        == "ARCHIVED"
    )
    assert (
        connection.execute(
            "SELECT state FROM index_generations WHERE id = '50000000-0000-4000-8000-000000000099'"
        ).fetchone()[0]
        == "ARCHIVED"
    )
    connection.close()


def test_chunks_without_embeddings_never_activate(tmp_path: Path) -> None:
    factory, handoff = _prepare_database(tmp_path)

    with pytest.raises(IndexingPersistenceError, match="incomplete or incompatible"):
        _finalizer(factory)(handoff)

    _assert_staging(factory)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("embedding_model_id", "40000000-0000-4000-8000-000000000002"),
        ("dimensions", 7),
        ("vector_ciphertext", b""),
    ],
)
def test_incompatible_embedding_metadata_blocks_activation(
    tmp_path: Path, column: str, value: object
) -> None:
    factory, handoff = _prepare_database(tmp_path)
    _insert_embedding(factory)
    connection = factory.create()
    if column == "embedding_model_id":
        connection.execute(
            "INSERT INTO local_models (id, purpose, provider, requested_alias, resolved_model_id, dimensions, created_at) VALUES (?, 'EMBEDDING', 'synthetic', 'other', 'other', 8, ?)",
            (value, "2026-01-01T00:00:00.000Z"),
        )
    connection.execute(f"UPDATE embeddings SET {column} = ?", (value,))
    connection.commit()
    connection.close()

    with pytest.raises(IndexingPersistenceError, match="incomplete or incompatible"):
        _finalizer(factory)(handoff)

    _assert_staging(factory)


def test_invalid_dtype_is_rejected_by_schema_and_cannot_activate(tmp_path: Path) -> None:
    factory, handoff = _prepare_database(tmp_path)
    connection = factory.create()
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO embeddings (chunk_id, workspace_id, index_generation_id, embedding_model_id, dimensions, dtype, is_unit_normalized, vector_ciphertext, created_at) VALUES (?, ?, ?, ?, 8, 'float64', 1, x'01', ?)",
            (
                str(CHUNK_ID),
                str(WORKSPACE_ID),
                str(GENERATION_ID),
                str(MODEL_ID),
                "2026-01-01T00:00:00.000Z",
            ),
        )
    connection.rollback()
    connection.close()

    with pytest.raises(IndexingPersistenceError, match="incomplete or incompatible"):
        _finalizer(factory)(handoff)


def test_duplicate_embedding_is_rejected_and_extra_mapping_blocks_activation(
    tmp_path: Path,
) -> None:
    factory, handoff = _prepare_database(tmp_path)
    _insert_embedding(factory)
    connection = factory.create()
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO embeddings (chunk_id, workspace_id, index_generation_id, embedding_model_id, dimensions, dtype, is_unit_normalized, vector_ciphertext, created_at) VALUES (?, ?, ?, ?, 8, 'float32', 1, x'02', ?)",
            (
                str(CHUNK_ID),
                str(WORKSPACE_ID),
                str(GENERATION_ID),
                str(MODEL_ID),
                "2026-01-01T00:00:00.000Z",
            ),
        )
    connection.rollback()
    connection.execute(
        "INSERT INTO index_generations (id, workspace_id, document_version_id, processing_job_id, state, embedding_model_id, chunking_profile_version, normalization_profile_version, embedding_dimensions, vector_dtype, chunk_count, created_at) VALUES ('50000000-0000-4000-8000-000000000002', ?, ?, ?, 'FAILED', ?, 'other', 'exact-text-v1', 8, 'float32', 1, ?)",
        (
            str(WORKSPACE_ID),
            str(VERSION_ID),
            str(JOB_ID),
            str(MODEL_ID),
            "2026-01-01T00:00:00.000Z",
        ),
    )
    connection.execute(
        "INSERT INTO chunks (id, workspace_id, index_generation_id, document_version_id, page_id, source_locator_id, document_order, page_order, text_ciphertext, normalized_text_fingerprint, character_count, extraction_method, created_at, source_start_offset, source_end_offset) VALUES ('80000000-0000-4000-8000-000000000002', ?, '50000000-0000-4000-8000-000000000002', ?, ?, ?, 0, 0, x'01', x'02', 1, 'NATIVE', ?, 0, 1)",
        (
            str(WORKSPACE_ID),
            str(VERSION_ID),
            str(PAGE_ID),
            str(LOCATOR_ID),
            "2026-01-01T00:00:00.000Z",
        ),
    )
    connection.execute(
        "INSERT INTO embeddings (chunk_id, workspace_id, index_generation_id, embedding_model_id, dimensions, dtype, is_unit_normalized, vector_ciphertext, created_at) VALUES ('80000000-0000-4000-8000-000000000002', ?, ?, ?, 8, 'float32', 1, x'02', ?)",
        (
            str(WORKSPACE_ID),
            str(GENERATION_ID),
            str(MODEL_ID),
            "2026-01-01T00:00:00.000Z",
        ),
    )
    connection.commit()
    connection.close()

    with pytest.raises(IndexingPersistenceError, match="incomplete or incompatible"):
        _finalizer(factory)(handoff)

    _assert_staging(factory)


def test_unit_normalization_constraint_rejects_incompatible_storage_metadata(
    tmp_path: Path,
) -> None:
    factory, _ = _prepare_database(tmp_path)
    _insert_embedding(factory)
    connection = factory.create()
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE embeddings SET is_unit_normalized = 0")
    connection.rollback()
    connection.close()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE index_generations SET chunk_count = 2",
        "UPDATE index_generations SET chunking_profile_version = 'stale-profile'",
        "UPDATE index_generations SET state = 'FAILED'",
        "UPDATE document_processing_jobs SET state = 'READY'",
        "UPDATE document_versions SET state = 'CANDIDATE_FAILED'",
    ],
)
def test_incomplete_profile_or_stale_lifecycle_fails_closed(tmp_path: Path, statement: str) -> None:
    factory, handoff = _prepare_database(tmp_path)
    _insert_embedding(factory)
    connection = factory.create()
    connection.execute(statement)
    connection.commit()
    connection.close()

    with pytest.raises(IndexingPersistenceError):
        _finalizer(factory)(handoff)

    connection = factory.create()
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM index_generations WHERE state = 'ACTIVE'"
        ).fetchone()[0]
        == 0
    )
    connection.close()


def test_scope_substitution_fails_before_transaction(tmp_path: Path) -> None:
    factory, handoff = _prepare_database(tmp_path)
    scope = ActiveWorkspaceScope()
    scope.select(WorkspaceId("10000000-0000-4000-8000-000000000002"))
    calls = 0

    def unit_of_work() -> SQLiteUnitOfWork:
        nonlocal calls
        calls += 1
        return SQLiteUnitOfWork(
            factory,
            InsecureDevelopmentOnlyWorkspaceNamePersistence(),
            InsecureDevelopmentOnlyPayloadCodec(),
        )

    finalizer = FinalizeIndexing(scope, _NeverCancelled(), unit_of_work, lambda: NOW)
    with pytest.raises(InvalidIndexingInput, match="ownership is invalid"):
        finalizer(handoff)
    assert calls == 0


def test_cancellation_before_transaction_changes_nothing(tmp_path: Path) -> None:
    factory, handoff = _prepare_database(tmp_path)
    _insert_embedding(factory)

    with pytest.raises(IndexingCancelled):
        _finalizer(factory, cancellation=_Cancelled())(handoff)

    _assert_staging(factory)


def test_concurrent_active_conflict_fails_without_arbitrary_replacement(
    tmp_path: Path,
) -> None:
    factory, handoff = _prepare_database(tmp_path)
    _insert_embedding(factory)
    connection = factory.create()
    connection.execute(
        "INSERT INTO index_generations (id, workspace_id, document_version_id, processing_job_id, state, embedding_model_id, chunking_profile_version, normalization_profile_version, embedding_dimensions, vector_dtype, chunk_count, created_at, activated_at) VALUES ('50000000-0000-4000-8000-000000000002', ?, ?, ?, 'ACTIVE', ?, 'other', 'exact-text-v1', 8, 'float32', 0, ?, ?)",
        (
            str(WORKSPACE_ID),
            str(VERSION_ID),
            str(JOB_ID),
            str(MODEL_ID),
            "2026-01-01T00:00:00.000Z",
            "2026-01-01T00:00:00.000Z",
        ),
    )
    connection.commit()
    connection.close()

    with pytest.raises(IndexingPersistenceError, match="previous active"):
        _finalizer(factory)(handoff)

    connection = factory.create()
    assert (
        connection.execute(
            "SELECT state FROM index_generations WHERE id = ?", (str(GENERATION_ID),)
        ).fetchone()[0]
        == "STAGING"
    )
    assert (
        connection.execute(
            "SELECT state FROM index_generations WHERE id = '50000000-0000-4000-8000-000000000002'"
        ).fetchone()[0]
        == "ACTIVE"
    )
    connection.close()


@pytest.mark.parametrize("failure", ["sql", "commit"])
def test_atomic_failure_preserves_candidate_and_previous_active(
    tmp_path: Path, failure: str
) -> None:
    factory, handoff = _prepare_database(tmp_path, previous_active=True)
    _insert_embedding(factory)
    if failure == "sql":
        connection = factory.create()
        connection.execute(
            "CREATE TRIGGER synthetic_activation_failure BEFORE UPDATE OF state ON index_generations WHEN NEW.state = 'ACTIVE' BEGIN SELECT RAISE(ABORT, 'sensitive trigger detail'); END"
        )
        connection.commit()
        connection.close()

    with pytest.raises(IndexingPersistenceError) as captured:
        _finalizer(
            factory,
            uow_type=_FailingCommitUnitOfWork if failure == "commit" else SQLiteUnitOfWork,
        )(handoff)

    assert "sensitive" not in str(captured.value)
    connection = factory.create()
    rows = connection.execute("SELECT id, state FROM index_generations ORDER BY id").fetchall()
    assert [(row["id"], row["state"]) for row in rows] == [
        (str(GENERATION_ID), "STAGING"),
        ("50000000-0000-4000-8000-000000000099", "ACTIVE"),
    ]
    versions = connection.execute("SELECT id, state FROM document_versions ORDER BY id").fetchall()
    assert [(row["id"], row["state"]) for row in versions] == [
        (str(VERSION_ID), "CANDIDATE_PROCESSING"),
        ("20000000-0000-4000-8000-000000000099", "ACTIVE"),
    ]
    connection.close()


def _assert_staging(factory: SQLiteConnectionFactory) -> None:
    connection = factory.create()
    row = connection.execute(
        "SELECT state, activated_at FROM index_generations WHERE id = ?",
        (str(GENERATION_ID),),
    ).fetchone()
    assert tuple(row) == ("STAGING", None)
    connection.close()
