"""Integration tests for the real SQLite migration pipeline."""

import sqlite3
from pathlib import Path

import pytest

from lexlocal.infrastructure.persistence.migration_runner import (
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
    assert migrations[-1].filename == "002_nullable_blob_encryption_format.sql"

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
