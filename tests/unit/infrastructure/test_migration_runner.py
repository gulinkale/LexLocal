"""Unit tests for the SQLite migration runner."""

from pathlib import Path

import pytest

from lexlocal.infrastructure.persistence.migration_runner import (
    AppliedMigration,
    MigrationHistoryError,
    load_applied_migrations,
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
) -> Migration:
    """Create a migration for focused unit tests."""

    return Migration(
        version=version,
        filename=filename,
        checksum_sha256=checksum,
        sql="SELECT 1;",
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
