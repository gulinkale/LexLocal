"""Integration tests for the real SQLite migration pipeline."""

import sqlite3
from pathlib import Path

import pytest

from lexlocal.infrastructure.persistence.migration_runner import (
    MigrationExecutionError,
    load_applied_migrations,
    run_migrations,
)
from lexlocal.infrastructure.persistence.migrations import (
    default_migrations_dir,
    discover_migrations,
)
from lexlocal.infrastructure.persistence.sqlite_connection import (
    SQLiteConnectionFactory,
)


def test_real_migration_pipeline(
    tmp_path: Path,
) -> None:
    """Apply real migrations and verify the persisted database."""

    database_path = tmp_path / "database" / "lexlocal.db"
    factory = SQLiteConnectionFactory(database_path)

    migrations = discover_migrations(default_migrations_dir())

    assert migrations
    assert migrations[0].version == 1
    assert migrations[0].filename == "001_initial.sql"
    assert migrations[-1].filename == "003_chunk_source_offsets.sql"

    first_connection = factory.create()

    try:
        applied_migrations = run_migrations(
            first_connection,
            migrations,
        )
    finally:
        first_connection.close()

    second_connection = factory.create()

    try:
        migration_history = load_applied_migrations(second_connection)

        applied_again = run_migrations(
            second_connection,
            migrations,
        )

        table_rows = second_connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()

        foreign_key_violations = second_connection.execute("PRAGMA foreign_key_check").fetchall()

        integrity_result = second_connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        second_connection.close()

    table_names = {str(row["name"]) for row in table_rows}

    expected_tables = {
        "schema_migrations",
        "workspaces",
        "documents",
        "document_versions",
    }

    assert applied_migrations == migrations
    assert list(migration_history) == [migration.version for migration in migrations]
    assert applied_again == ()
    assert expected_tables <= table_names
    assert foreign_key_violations == []
    assert integrity_result is not None
    assert integrity_result[0] == "ok"


def test_chunk_offset_migration_adds_only_constrained_offset_columns(
    tmp_path: Path,
) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "offsets.db")
    connection = factory.create()
    migrations = discover_migrations(default_migrations_dir())
    run_migrations(connection, migrations)

    columns = {row["name"] for row in connection.execute("PRAGMA table_info(chunks)").fetchall()}
    assert {"source_start_offset", "source_end_offset"} <= columns
    sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'chunks'"
    ).fetchone()["sql"]
    assert "CHECK (source_start_offset >= 0)" in sql
    assert "CHECK (source_end_offset > source_start_offset)" in sql
    assert run_migrations(connection, migrations) == ()
    connection.close()


def test_chunk_offset_migration_fails_closed_for_unexpected_legacy_rows(
    tmp_path: Path,
) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "legacy.db")
    connection = factory.create()
    migrations = discover_migrations(default_migrations_dir())
    run_migrations(connection, migrations[:2])
    connection.executescript(
        """
        BEGIN;
        INSERT INTO workspaces
          (id, name_ciphertext, name_lookup_fingerprint, state, created_at, updated_at)
        VALUES ('w', x'01', x'02', 'ACTIVE', 't', 't');
        INSERT INTO documents
          (id, workspace_id, display_name_ciphertext, state, created_at, updated_at)
        VALUES ('d', 'w', x'03', 'ACTIVE', 't', 't');
        INSERT INTO document_versions
          (id, workspace_id, document_id, version_number,
           historical_filename_ciphertext, state, created_at)
        VALUES ('v', 'w', 'd', 1, x'04', 'CANDIDATE_PROCESSING', 't');
        INSERT INTO document_processing_jobs
          (id, workspace_id, document_version_id, attempt_number, state, stage, created_at)
        VALUES ('j', 'w', 'v', 1, 'PROCESSING', 'CHUNKING', 't');
        INSERT INTO local_models
          (id, purpose, provider, requested_alias, resolved_model_id, dimensions, created_at)
        VALUES ('m', 'EMBEDDING', 'p', 'a', 'r', 4, 't');
        INSERT INTO document_pages
          (id, workspace_id, document_version_id, page_number, state,
           extraction_method, text_ciphertext, character_count, created_at, updated_at)
        VALUES ('p', 'w', 'v', 1, 'READY', 'NATIVE', x'01', 1, 't', 't');
        INSERT INTO source_locators
          (id, workspace_id, document_version_id, page_id, locator_kind,
           page_number, locator_version, created_at)
        VALUES ('l', 'w', 'v', 'p', 'PAGE', 1, 1, 't');
        INSERT INTO index_generations
          (id, workspace_id, document_version_id, processing_job_id, state,
           embedding_model_id, chunking_profile_version, normalization_profile_version,
           embedding_dimensions, vector_dtype, chunk_count, created_at)
        VALUES ('g', 'w', 'v', 'j', 'STAGING', 'm', 'c', 'n', 4, 'float32', 1, 't');
        INSERT INTO chunks
          (id, workspace_id, index_generation_id, document_version_id, page_id,
           source_locator_id, document_order, page_order, text_ciphertext,
           normalized_text_fingerprint, character_count, extraction_method, created_at)
        VALUES ('c', 'w', 'g', 'v', 'p', 'l', 0, 0, x'01', x'02', 1, 'NATIVE', 't');
        COMMIT;
        """
    )

    with pytest.raises(MigrationExecutionError, match="version 3"):
        run_migrations(connection, migrations)

    assert [
        row["version"]
        for row in connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    ] == [1, 2]
    connection.close()


@pytest.mark.parametrize("invalid_format_version", [0, -1])
def test_blob_encryption_format_is_nullable_but_positive_when_present(
    tmp_path: Path,
    invalid_format_version: int,
) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    connection = factory.create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
    connection.execute(
        """
        INSERT INTO workspaces (
            id, name_ciphertext, name_lookup_fingerprint, state, created_at, updated_at
        ) VALUES ('w', x'01', x'02', 'ACTIVE', 't', 't')
        """
    )
    values = ('b', 'w', 'SOURCE_DOCUMENT', 'opaque', 'ACTIVE', 1, 't')
    connection.execute(
        """INSERT INTO stored_blobs
        (id, workspace_id, kind, relative_path, state, size_bytes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        values,
    )
    connection.execute(
        """INSERT INTO stored_blobs
        (id, workspace_id, kind, relative_path, state, size_bytes,
         encryption_format_version, created_at)
        VALUES ('positive', 'w', 'SOURCE_DOCUMENT', 'positive', 'ACTIVE', 1, 1, 't')"""
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """INSERT INTO stored_blobs
            (id, workspace_id, kind, relative_path, state, size_bytes,
             encryption_format_version, created_at)
            VALUES ('bad', 'w', 'SOURCE_DOCUMENT', 'bad', 'ACTIVE', 1, ?, 't')""",
            (invalid_format_version,),
        )
    connection.close()


def test_nullable_format_migration_preserves_existing_blob_relationships(
    tmp_path: Path,
) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "upgrade.db")
    connection = factory.create()
    migrations = discover_migrations(default_migrations_dir())
    run_migrations(connection, migrations[:1])
    connection.executescript(
        """
        BEGIN;
        INSERT INTO workspaces
          (id, name_ciphertext, name_lookup_fingerprint, state, created_at, updated_at)
        VALUES ('w', x'01', x'02', 'ACTIVE', 't', 't');
        INSERT INTO stored_blobs
          (id, workspace_id, kind, relative_path, state, size_bytes,
           encryption_format_version, created_at)
        VALUES ('b', 'w', 'SOURCE_DOCUMENT', 'opaque', 'ACTIVE', 1, 1, 't');
        INSERT INTO documents
          (id, workspace_id, display_name_ciphertext, state, created_at, updated_at)
        VALUES ('d', 'w', x'03', 'ACTIVE', 't', 't');
        INSERT INTO document_versions
          (id, workspace_id, document_id, version_number,
           historical_filename_ciphertext, source_blob_id, state, created_at)
        VALUES ('v', 'w', 'd', 1, x'04', 'b', 'CANDIDATE_PROCESSING', 't');
        COMMIT;
        """
    )

    assert run_migrations(connection, migrations) == migrations[1:]
    row = connection.execute(
        "SELECT source_blob_id FROM document_versions WHERE id = 'v'"
    ).fetchone()
    assert row is not None and row["source_blob_id"] == "b"
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
