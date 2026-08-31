"""Integration tests for persistence bootstrap composition."""

import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

from lexlocal.bootstrap import persistence as persistence_bootstrap
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.infrastructure.persistence.migration_runner import (
    MigrationExecutionError,
    MigrationHistoryError,
)
from lexlocal.infrastructure.persistence.migrations import (
    Migration,
    default_migrations_dir,
    discover_migrations,
)
from lexlocal.infrastructure.persistence.sqlite_connection import (
    SQLiteConnectionFactory,
)


def make_settings(data_dir: Path) -> AppSettings:
    """Create application settings for persistence bootstrap tests."""

    return AppSettings(
        app_name="LexLocal",
        environment="test",
        log_level="INFO",
        data_dir=data_dir,
    )


def make_migration(version: int, sql: str = "SELECT 1;") -> Migration:
    """Create a deterministic migration for bootstrap failure tests."""

    return Migration(
        version=version,
        filename=f"{version:03d}_test.sql",
        checksum_sha256=f"checksum-{version}",
        sql=sql,
    )


def test_initialize_persistence_uses_database_path_from_settings(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)

    connection_factory = persistence_bootstrap.initialize_persistence(settings)

    assert connection_factory.database_path == settings.database_path
    assert settings.database_path.exists()

    connection = connection_factory.create()

    try:
        applied_versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    finally:
        connection.close()

    expected_versions = [
        migration.version
        for migration in discover_migrations(default_migrations_dir())
    ]
    assert [int(row["version"]) for row in applied_versions] == expected_versions


@pytest.mark.parametrize("migration_sql", ["SELECT 1;", "SELECT missing_column;"])
def test_bootstrap_connection_closes_on_success_and_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    migration_sql: str,
) -> None:
    settings = make_settings(tmp_path)
    real_factory = SQLiteConnectionFactory(settings.database_path)
    connection = real_factory.create()
    observed_factory = Mock(spec=SQLiteConnectionFactory)
    observed_factory.create.return_value = connection
    migration = make_migration(
        1,
        f"""
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            filename TEXT NOT NULL,
            checksum_sha256 TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );
        {migration_sql}
        """,
    )

    monkeypatch.setattr(
        persistence_bootstrap,
        "SQLiteConnectionFactory",
        Mock(return_value=observed_factory),
    )
    monkeypatch.setattr(
        persistence_bootstrap,
        "discover_migrations",
        Mock(return_value=(migration,)),
    )

    if migration_sql == "SELECT 1;":
        assert persistence_bootstrap.initialize_persistence(settings) is observed_factory
    else:
        with pytest.raises(MigrationExecutionError):
            persistence_bootstrap.initialize_persistence(settings)

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")


def test_empty_migration_set_is_rejected_before_opening_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path)
    factory_class = Mock()
    monkeypatch.setattr(persistence_bootstrap, "SQLiteConnectionFactory", factory_class)
    monkeypatch.setattr(persistence_bootstrap, "discover_migrations", Mock(return_value=()))

    with pytest.raises(RuntimeError, match="No database migrations were found"):
        persistence_bootstrap.initialize_persistence(settings)

    factory_class.return_value.create.assert_not_called()


def test_real_checksum_mismatch_propagates(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    factory = persistence_bootstrap.initialize_persistence(settings)
    connection = factory.create()

    try:
        connection.execute(
            "UPDATE schema_migrations SET checksum_sha256 = ? WHERE version = 1",
            ("0" * 64,),
        )
    finally:
        connection.close()

    with pytest.raises(MigrationHistoryError, match="checksum mismatch"):
        persistence_bootstrap.initialize_persistence(settings)


def test_real_invalid_prefix_history_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path)
    migrations = (make_migration(1), make_migration(2))
    factory = SQLiteConnectionFactory(settings.database_path)
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
                version, filename, checksum_sha256, applied_at
            ) VALUES (2, '002_test.sql', 'checksum-2', '2026-08-02T00:00:00Z')
            """
        )
    finally:
        connection.close()

    monkeypatch.setattr(
        persistence_bootstrap,
        "discover_migrations",
        Mock(return_value=migrations),
    )

    with pytest.raises(MigrationHistoryError, match="not a valid prefix"):
        persistence_bootstrap.initialize_persistence(settings)


def test_bootstrap_failure_leaves_no_partial_migration_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path)
    broken = make_migration(
        1,
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            filename TEXT NOT NULL,
            checksum_sha256 TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );
        CREATE TABLE should_not_remain (id INTEGER PRIMARY KEY);
        INSERT INTO missing_table (id) VALUES (1);
        """,
    )
    monkeypatch.setattr(
        persistence_bootstrap,
        "discover_migrations",
        Mock(return_value=(broken,)),
    )

    with pytest.raises(MigrationExecutionError):
        persistence_bootstrap.initialize_persistence(settings)

    connection = SQLiteConnectionFactory(settings.database_path).create()
    try:
        tables = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table'
              AND name IN ('schema_migrations', 'should_not_remain')
            """
        ).fetchall()
    finally:
        connection.close()

    assert tables == []
