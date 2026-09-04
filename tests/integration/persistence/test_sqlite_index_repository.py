"""Integration tests for SQLite staging-index persistence."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.application.ports.indexing import (
    CandidateChunkSet,
    ChunkConfiguration,
    ChunkProfile,
    IndexChunk,
    IndexingPersistenceError,
    LogicalChunk,
)
from lexlocal.application.ports.processing import PageExtractionMethod
from lexlocal.application.ports.security import (
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
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
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyPayloadCodec,
)
from lexlocal.infrastructure.security.insecure_development_indexing import (
    InsecureDevelopmentOnlyChunkEqualityToken,
)

WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
VERSION_ID = DocumentVersionId("20000000-0000-4000-8000-000000000001")
JOB_ID = ProcessingJobId("30000000-0000-4000-8000-000000000001")
MODEL_ID = LocalModelId("40000000-0000-4000-8000-000000000001")
GENERATION_ID = IndexGenerationId("50000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)
PROFILE = ChunkConfiguration(4, 1).profile


@pytest.fixture
def database(tmp_path: Path) -> sqlite3.Connection:
    connection = SQLiteConnectionFactory(tmp_path / "lexlocal.db").create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
    _insert_graph(connection)
    connection.commit()
    yield connection
    connection.close()


def _encode_page(workspace_id: WorkspaceId, page_id: DocumentPageId, text: str) -> bytes:
    codec = InsecureDevelopmentOnlyPayloadCodec()
    context = SensitivePayloadContext(workspace_id, str(page_id), "document-page-text", 1)
    return codec.encode(
        text.encode(),
        context=context,
        key_reference=WorkspaceKeyReference(workspace_id, 1),
    ).payload


def _insert_graph(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN")
    connection.execute(
        "INSERT INTO workspaces (id, name_ciphertext, name_lookup_fingerprint, state, created_at, updated_at) VALUES (?, x'01', x'02', 'ACTIVE', ?, ?)",
        (str(WORKSPACE_ID), "2026-01-01T00:00:00.000Z", "2026-01-01T00:00:00.000Z"),
    )
    connection.execute(
        "INSERT INTO documents (id, workspace_id, display_name_ciphertext, state, created_at, updated_at) VALUES ('d', ?, x'03', 'ACTIVE', ?, ?)",
        (str(WORKSPACE_ID), "2026-01-01T00:00:00.000Z", "2026-01-01T00:00:00.000Z"),
    )
    connection.execute(
        "INSERT INTO document_versions (id, workspace_id, document_id, version_number, historical_filename_ciphertext, page_count, state, created_at) VALUES (?, ?, 'd', 1, x'04', 3, 'CANDIDATE_PROCESSING', ?)",
        (str(VERSION_ID), str(WORKSPACE_ID), "2026-01-01T00:00:00.000Z"),
    )
    connection.execute(
        "INSERT INTO document_processing_jobs (id, workspace_id, document_version_id, attempt_number, state, stage, created_at) VALUES (?, ?, ?, 1, 'PROCESSING', 'CHUNKING', ?)",
        (str(JOB_ID), str(WORKSPACE_ID), str(VERSION_ID), "2026-01-01T00:00:00.000Z"),
    )
    connection.execute(
        "INSERT INTO local_models (id, purpose, provider, requested_alias, resolved_model_id, dimensions, created_at) VALUES (?, 'EMBEDDING', 'synthetic', 'fixture', 'fixture-model', 8, ?)",
        (str(MODEL_ID), "2026-01-01T00:00:00.000Z"),
    )
    for number, text, state in (
        (1, "A🙂BC\nD", "READY"),
        (2, " \t", "WARNING"),
        (3, "xyz", "READY"),
    ):
        page_id = DocumentPageId(f"60000000-0000-4000-8000-{number:012d}")
        locator_id = SourceLocatorId(f"70000000-0000-4000-8000-{number:012d}")
        connection.execute(
            "INSERT INTO document_pages (id, workspace_id, document_version_id, page_number, state, extraction_method, text_ciphertext, character_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'NATIVE', ?, ?, ?, ?)",
            (
                str(page_id),
                str(WORKSPACE_ID),
                str(VERSION_ID),
                number,
                state,
                _encode_page(WORKSPACE_ID, page_id, text),
                len(text),
                "2026-01-01T00:00:00.000Z",
                "2026-01-01T00:00:00.000Z",
            ),
        )
        connection.execute(
            "INSERT INTO source_locators (id, workspace_id, document_version_id, page_id, locator_kind, page_number, locator_version, created_at) VALUES (?, ?, ?, ?, 'PAGE', ?, 1, ?)",
            (
                str(locator_id),
                str(WORKSPACE_ID),
                str(VERSION_ID),
                str(page_id),
                number,
                "2026-01-01T00:00:00.000Z",
            ),
        )


def _candidate() -> CandidateChunkSet:
    generation = IndexGeneration(
        GENERATION_ID,
        WORKSPACE_ID,
        VERSION_ID,
        JOB_ID,
        MODEL_ID,
        PROFILE.value,
        "exact-text-v1",
        8,
    )
    token = InsecureDevelopmentOnlyChunkEqualityToken()
    specifications = ((1, 0, 4, "A🙂BC"), (1, 3, 6, "C\nD"), (3, 0, 3, "xyz"))
    chunks = []
    for order, (page_number, start, end, text) in enumerate(specifications):
        logical = LogicalChunk(
            WORKSPACE_ID,
            VERSION_ID,
            DocumentPageId(f"60000000-0000-4000-8000-{page_number:012d}"),
            PageNumber(page_number),
            SourceLocatorId(f"70000000-0000-4000-8000-{page_number:012d}"),
            order,
            0 if order != 1 else 1,
            start,
            end,
            text,
            PageExtractionMethod.NATIVE,
            PROFILE,
        )
        chunks.append(
            IndexChunk(
                ChunkId(f"80000000-0000-4000-8000-{order + 1:012d}"),
                logical,
                token.fingerprint(logical),
                NOW,
            )
        )
    return CandidateChunkSet(generation, tuple(chunks), NOW)


def test_complete_candidate_round_trips_exactly(database: sqlite3.Connection) -> None:
    database.execute("BEGIN")
    repository = SQLiteIndexRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    candidate = _candidate()

    repository.stage_candidate(candidate)
    restored = repository.get_candidate(WORKSPACE_ID, VERSION_ID, GENERATION_ID)

    assert restored == candidate
    rows = database.execute("SELECT * FROM chunks ORDER BY document_order").fetchall()
    assert [row["source_start_offset"] for row in rows] == [0, 3, 0]
    assert [row["source_end_offset"] for row in rows] == [4, 6, 3]
    assert all(row["token_count_estimate"] is None for row in rows)
    assert all(row["extraction_method"] == "NATIVE" for row in rows)
    assert (
        database.execute(
            "SELECT COUNT(*) FROM index_generations WHERE state = 'ACTIVE'"
        ).fetchone()[0]
        == 0
    )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE chunks SET source_start_offset = -1 WHERE document_order = 0",
        "UPDATE chunks SET source_end_offset = source_start_offset WHERE document_order = 0",
    ],
)
def test_migration_offset_constraints_reject_invalid_ranges(
    database: sqlite3.Connection,
    statement: str,
) -> None:
    database.execute("BEGIN")
    repository = SQLiteIndexRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    repository.stage_candidate(_candidate())

    with pytest.raises(sqlite3.IntegrityError):
        database.execute(statement)


def test_exact_identity_is_required_for_handoff(database: sqlite3.Connection) -> None:
    database.execute("BEGIN")
    repository = SQLiteIndexRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    repository.stage_candidate(_candidate())

    other_workspace = WorkspaceId("10000000-0000-4000-8000-000000000002")
    other_version = DocumentVersionId("20000000-0000-4000-8000-000000000002")
    assert repository.get_candidate(other_workspace, VERSION_ID, GENERATION_ID) is None
    assert repository.get_candidate(WORKSPACE_ID, other_version, GENERATION_ID) is None


def test_generation_discovery_is_scoped_ordered_and_state_neutral(
    database: sqlite3.Connection,
) -> None:
    database.execute("BEGIN")
    repository = SQLiteIndexRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    candidate = _candidate()
    repository.stage_candidate(candidate)
    database.execute(
        """
        INSERT INTO index_generations (
            id, workspace_id, document_version_id, processing_job_id, state,
            embedding_model_id, chunking_profile_version,
            normalization_profile_version, embedding_dimensions, vector_dtype,
            chunk_count, created_at, activated_at
        ) VALUES (?, ?, ?, ?, 'ACTIVE', ?, 'incompatible-profile',
                  'exact-text-v1', 8, 'float32', 0, ?, ?)
        """,
        (
            "50000000-0000-4000-8000-000000000002",
            str(WORKSPACE_ID),
            str(VERSION_ID),
            str(JOB_ID),
            str(MODEL_ID),
            "2026-01-02T03:04:06.678Z",
            "2026-01-02T03:04:07.678Z",
        ),
    )

    discovered = repository.list_generations(WORKSPACE_ID, VERSION_ID, JOB_ID)

    assert [item.generation.id for item in discovered] == [
        GENERATION_ID,
        IndexGenerationId("50000000-0000-4000-8000-000000000002"),
    ]
    assert [item.generation.state for item in discovered] == [
        IndexGenerationState.STAGING,
        IndexGenerationState.ACTIVE,
    ]
    assert discovered[1].generation.chunking_profile_version == "incompatible-profile"
    assert (
        repository.list_generations(
            WorkspaceId("10000000-0000-4000-8000-000000000002"), VERSION_ID, JOB_ID
        )
        == ()
    )


def test_staging_replacement_preserves_generation_and_replaces_complete_set(
    database: sqlite3.Connection,
) -> None:
    database.execute("BEGIN")
    repository = SQLiteIndexRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    candidate = _candidate()
    repository.stage_candidate(candidate)
    replacement = CandidateChunkSet(
        candidate.generation,
        tuple(
            replace(
                chunk,
                id=ChunkId(f"90000000-0000-4000-8000-{index + 1:012d}"),
            )
            for index, chunk in enumerate(candidate.chunks)
        ),
        candidate.created_at,
    )

    repository.replace_staging_candidate(replacement)
    restored = repository.get_candidate(WORKSPACE_ID, VERSION_ID, GENERATION_ID)

    assert restored == replacement
    assert restored is not None and restored.created_at == candidate.created_at
    assert database.execute("SELECT COUNT(*) FROM index_generations").fetchone()[0] == 1
    assert database.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 3


def test_incomplete_staging_chunk_set_can_be_rebuilt_completely(
    database: sqlite3.Connection,
) -> None:
    database.execute("BEGIN")
    repository = SQLiteIndexRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    candidate = _candidate()
    repository.stage_candidate(candidate)
    database.execute("DELETE FROM chunks WHERE document_order = 1")

    repository.replace_staging_candidate(candidate)

    assert repository.get_candidate(WORKSPACE_ID, VERSION_ID, GENERATION_ID) == candidate


def test_failed_staging_replacement_can_restore_the_previous_complete_set(
    database: sqlite3.Connection,
) -> None:
    database.execute("BEGIN")
    repository = SQLiteIndexRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    candidate = _candidate()
    repository.stage_candidate(candidate)
    database.execute("SAVEPOINT before_replacement")
    database.execute(
        "CREATE TEMP TRIGGER fail_replacement BEFORE INSERT ON chunks "
        "WHEN NEW.id LIKE '90000000%' "
        "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"
    )
    replacement = CandidateChunkSet(
        candidate.generation,
        tuple(
            replace(
                chunk,
                id=ChunkId(f"90000000-0000-4000-8000-{index + 1:012d}"),
            )
            for index, chunk in enumerate(candidate.chunks)
        ),
        candidate.created_at,
    )

    with pytest.raises(IndexingPersistenceError):
        repository.replace_staging_candidate(replacement)
    database.execute("ROLLBACK TO before_replacement")

    assert repository.get_candidate(WORKSPACE_ID, VERSION_ID, GENERATION_ID) == candidate


def test_active_or_incompatible_metadata_cannot_be_replaced(
    database: sqlite3.Connection,
) -> None:
    database.execute("BEGIN")
    repository = SQLiteIndexRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    candidate = _candidate()
    repository.stage_candidate(candidate)
    mismatched_generation = replace(
        candidate.generation,
        chunking_profile_version="different-profile",
    )
    mismatched_chunks = tuple(
        replace(
            chunk,
            logical=replace(
                chunk.logical,
                profile=ChunkProfile("different-profile"),
            ),
        )
        for chunk in candidate.chunks
    )

    with pytest.raises(IndexingPersistenceError, match="metadata is invalid"):
        repository.replace_staging_candidate(
            CandidateChunkSet(mismatched_generation, mismatched_chunks, NOW)
        )

    database.execute(
        "UPDATE index_generations SET state = 'ACTIVE', activated_at = ? WHERE id = ?",
        ("2026-01-02T03:04:06.678Z", str(GENERATION_ID)),
    )
    with pytest.raises(IndexingPersistenceError):
        repository.replace_staging_candidate(candidate)


def test_malformed_discovery_metadata_fails_sanitized(
    database: sqlite3.Connection,
) -> None:
    database.execute("BEGIN")
    repository = SQLiteIndexRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    repository.stage_candidate(_candidate())
    database.execute("UPDATE local_models SET dimensions = 9 WHERE id = ?", (str(MODEL_ID),))

    with pytest.raises(IndexingPersistenceError) as captured:
        repository.list_generations(WORKSPACE_ID, VERSION_ID, JOB_ID)

    assert str(MODEL_ID) not in str(captured.value)
    assert captured.value.__cause__ is None


def test_wrong_source_slice_fails_sanitized(database: sqlite3.Connection) -> None:
    database.execute("BEGIN")
    repository = SQLiteIndexRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    candidate = _candidate()
    bad_logical = candidate.chunks[0].logical
    bad_logical = LogicalChunk(
        bad_logical.workspace_id,
        bad_logical.document_version_id,
        bad_logical.page_id,
        bad_logical.page_number,
        bad_logical.source_locator_id,
        bad_logical.document_order,
        bad_logical.page_order,
        bad_logical.source_start_offset,
        bad_logical.source_end_offset,
        "nope",
        bad_logical.extraction_method,
        bad_logical.profile,
    )
    bad = CandidateChunkSet(
        candidate.generation,
        (IndexChunk(candidate.chunks[0].id, bad_logical, b"opaque", NOW),) + candidate.chunks[1:],
        NOW,
    )

    with pytest.raises(IndexingPersistenceError) as captured:
        repository.stage_candidate(bad)

    assert "nope" not in str(captured.value)
    assert database.execute("SELECT COUNT(*) FROM index_generations").fetchone()[0] == 0


@pytest.mark.parametrize(
    "logical_change",
    [
        {"workspace_id": WorkspaceId("10000000-0000-4000-8000-000000000002")},
        {"page_id": DocumentPageId("60000000-0000-4000-8000-000000000099")},
        {"source_locator_id": SourceLocatorId("70000000-0000-4000-8000-000000000099")},
    ],
)
def test_missing_or_cross_workspace_page_graph_is_not_normalized(
    database: sqlite3.Connection,
    logical_change: dict[str, object],
) -> None:
    database.execute("BEGIN")
    repository = SQLiteIndexRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    candidate = _candidate()
    logical = replace(candidate.chunks[0].logical, **logical_change)
    generation = candidate.generation
    if "workspace_id" in logical_change:
        generation = replace(generation, workspace_id=logical.workspace_id)
        chunks = tuple(
            replace(chunk, logical=replace(chunk.logical, workspace_id=logical.workspace_id))
            for chunk in candidate.chunks
        )
    else:
        chunks = (replace(candidate.chunks[0], logical=logical),) + candidate.chunks[1:]
    malformed = CandidateChunkSet(generation, chunks, NOW)

    with pytest.raises(IndexingPersistenceError) as captured:
        repository.stage_candidate(malformed)

    assert str(logical.workspace_id) not in str(captured.value)
    assert database.execute("SELECT COUNT(*) FROM index_generations").fetchone()[0] == 0


def test_wrong_version_or_processing_job_is_rejected_without_normalization(
    database: sqlite3.Connection,
) -> None:
    database.execute("BEGIN")
    repository = SQLiteIndexRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    candidate = _candidate()
    wrong_job = replace(
        candidate.generation,
        processing_job_id=ProcessingJobId("30000000-0000-4000-8000-000000000099"),
    )
    with pytest.raises(IndexingPersistenceError):
        repository.stage_candidate(
            CandidateChunkSet(wrong_job, candidate.chunks, candidate.created_at)
        )

    wrong_version_id = DocumentVersionId("20000000-0000-4000-8000-000000000099")
    wrong_version = replace(candidate.generation, document_version_id=wrong_version_id)
    wrong_chunks = tuple(
        replace(
            chunk,
            logical=replace(chunk.logical, document_version_id=wrong_version_id),
        )
        for chunk in candidate.chunks
    )
    with pytest.raises(IndexingPersistenceError):
        repository.stage_candidate(
            CandidateChunkSet(wrong_version, wrong_chunks, candidate.created_at)
        )

    assert database.execute("SELECT COUNT(*) FROM index_generations").fetchone()[0] == 0


def test_duplicate_logical_equality_is_rejected_before_writes(
    database: sqlite3.Connection,
) -> None:
    database.execute("BEGIN")
    repository = SQLiteIndexRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    candidate = _candidate()
    duplicate = replace(candidate.chunks[1], equality_token=candidate.chunks[0].equality_token)
    malformed = CandidateChunkSet(
        candidate.generation,
        (candidate.chunks[0], duplicate, candidate.chunks[2]),
        NOW,
    )

    with pytest.raises(IndexingPersistenceError, match="equality is invalid"):
        repository.stage_candidate(malformed)

    assert database.execute("SELECT COUNT(*) FROM index_generations").fetchone()[0] == 0


@pytest.mark.parametrize("failure_order", [1, 2])
def test_chunk_insert_failure_can_be_rolled_back_without_partial_set(
    database: sqlite3.Connection,
    failure_order: int,
) -> None:
    database.execute("BEGIN")
    database.execute(
        "CREATE TEMP TRIGGER fail_chunk BEFORE INSERT ON chunks "
        f"WHEN NEW.document_order = {failure_order} "
        "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"
    )
    repository = SQLiteIndexRepository(database, InsecureDevelopmentOnlyPayloadCodec())

    with pytest.raises(IndexingPersistenceError):
        repository.stage_candidate(_candidate())
    database.rollback()

    assert database.execute("SELECT COUNT(*) FROM index_generations").fetchone()[0] == 0
    assert database.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0


def test_corrupt_chunk_payload_and_utf8_fail_sanitized(database: sqlite3.Connection) -> None:
    database.execute("BEGIN")
    repository = SQLiteIndexRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    repository.stage_candidate(_candidate())
    database.execute("UPDATE chunks SET text_ciphertext = x'ff' WHERE document_order = 0")

    with pytest.raises(IndexingPersistenceError) as captured:
        repository.get_candidate(WORKSPACE_ID, VERSION_ID, GENERATION_ID)

    assert captured.value.__cause__ is None


def test_corrupt_equality_and_locator_mapping_fail_closed(
    database: sqlite3.Connection,
) -> None:
    database.execute("BEGIN")
    repository = SQLiteIndexRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    repository.stage_candidate(_candidate())
    database.execute("UPDATE chunks SET normalized_text_fingerprint = x'' WHERE document_order = 0")

    with pytest.raises(IndexingPersistenceError):
        repository.get_candidate(WORKSPACE_ID, VERSION_ID, GENERATION_ID)


def test_repository_requires_an_active_transaction(database: sqlite3.Connection) -> None:
    repository = SQLiteIndexRepository(database, InsecureDevelopmentOnlyPayloadCodec())

    with pytest.raises(IndexingPersistenceError, match="transaction is not active"):
        repository.stage_candidate(_candidate())
