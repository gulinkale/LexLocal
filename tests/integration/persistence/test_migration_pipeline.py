"""Integration tests for the real SQLite migration pipeline."""

from pathlib import Path

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
