"""Unit tests for the SQLite migration runner."""

from pathlib import Path

import pytest

from lexlocal.infrastructure.persistence.migration_runner import (
    AppliedMigration,
    MigrationExecutionError,
    MigrationHistoryError,
    load_applied_migrations,
    run_migrations,
    select_pending_migrations,
)
from lexlocal.infrastructure.persistence.migrations import Migration
from lexlocal.infrastructure.persistence.sqlite_connection import (
    SQLiteConnectionFactory,
)


def make_migration(
    version: int,
    filename: str,
    checksum: str,
    sql: str = "SELECT 1;",
) -> Migration:
    """Create a migration for focused unit tests."""

    return Migration(
        version=version,
        filename=filename,
        checksum_sha256=checksum,
        sql=sql,
    )


def test_returns_empty_result_when_tracking_table_does_not_exist(
    tmp_path: Path,
) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    connection = factory.create()

    try:
        applied = load_applied_migrations(connection)
    finally:
        connection.close()

    assert applied == {}


def test_loads_applied_migrations(
    tmp_path: Path,
) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    connection = factory.create()

    try:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                filename TEXT NOT NULL,
                checksum_sha256 TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO schema_migrations (
                version,
                filename,
                checksum_sha256,
                applied_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                1,
                "001_initial.sql",
                "abc123",
                "2026-07-31T12:00:00Z",
            ),
        )

        applied = load_applied_migrations(connection)
    finally:
        connection.close()

    assert list(applied) == [1]
    assert applied[1].version == 1
    assert applied[1].filename == "001_initial.sql"
    assert applied[1].checksum_sha256 == "abc123"


def test_returns_only_pending_migrations() -> None:
    first = make_migration(
        1,
        "001_initial.sql",
        "checksum-1",
    )
    second = make_migration(
        2,
        "002_second.sql",
        "checksum-2",
    )

    applied = {
        1: AppliedMigration(
            version=1,
            filename="001_initial.sql",
            checksum_sha256="checksum-1",
        )
    }

    pending = select_pending_migrations(
        (first, second),
        applied,
    )

    assert pending == (second,)


def test_rejects_changed_applied_migration() -> None:
    migration = make_migration(
        1,
        "001_initial.sql",
        "new-checksum",
    )

    applied = {
        1: AppliedMigration(
            version=1,
            filename="001_initial.sql",
            checksum_sha256="old-checksum",
        )
    }

    with pytest.raises(
        MigrationHistoryError,
        match="checksum mismatch",
    ):
        select_pending_migrations((migration,), applied)


def test_rejects_missing_applied_migration_file() -> None:
    applied = {
        1: AppliedMigration(
            version=1,
            filename="001_initial.sql",
            checksum_sha256="checksum-1",
        )
    }

    with pytest.raises(
        MigrationHistoryError,
        match="file is missing",
    ):
        select_pending_migrations((), applied)


def test_rejects_renamed_applied_migration() -> None:
    migration = make_migration(
        1,
        "001_renamed.sql",
        "checksum-1",
    )

    applied = {
        1: AppliedMigration(
            version=1,
            filename="001_initial.sql",
            checksum_sha256="checksum-1",
        )
    }

    with pytest.raises(
        MigrationHistoryError,
        match="filename mismatch",
    ):
        select_pending_migrations((migration,), applied)


def test_applies_pending_migrations_in_order_and_records_them(
    tmp_path: Path,
) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    connection = factory.create()

    first = make_migration(
        1,
        "001_initial.sql",
        "checksum-1",
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            filename TEXT NOT NULL,
            checksum_sha256 TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );

        CREATE TABLE example_records (
            id INTEGER PRIMARY KEY,
            value TEXT NOT NULL
        );
        """,
    )

    second = make_migration(
        2,
        "002_insert_record.sql",
        "checksum-2",
        """
        INSERT INTO example_records (value)
        VALUES ('created-by-second-migration');
        """,
    )

    try:
        applied = run_migrations(
            connection,
            (first, second),
        )

        records = connection.execute(
            """
            SELECT value
            FROM example_records
            ORDER BY id
            """
        ).fetchall()

        history = load_applied_migrations(connection)

        applied_again = run_migrations(
            connection,
            (first, second),
        )
    finally:
        connection.close()

    assert [migration.version for migration in applied] == [1, 2]
    assert [row["value"] for row in records] == ["created-by-second-migration"]
    assert list(history) == [1, 2]
    assert applied_again == ()


def test_rolls_back_all_changes_when_migration_fails(
    tmp_path: Path,
) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    connection = factory.create()

    broken = make_migration(
        1,
        "001_broken.sql",
        "checksum-1",
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            filename TEXT NOT NULL,
            checksum_sha256 TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );

        CREATE TABLE should_not_remain (
            id INTEGER PRIMARY KEY
        );

        INSERT INTO table_that_does_not_exist (id)
        VALUES (1);
        """,
    )

    try:
        with pytest.raises(MigrationExecutionError):
            run_migrations(connection, (broken,))

        remaining_tables = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN (
                  'schema_migrations',
                  'should_not_remain'
              )
            """
        ).fetchall()
    finally:
        connection.close()

    assert remaining_tables == []
