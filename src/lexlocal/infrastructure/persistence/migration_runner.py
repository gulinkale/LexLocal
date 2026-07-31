"""Run and validate SQLite database migrations."""

import sqlite3
from dataclasses import dataclass

from lexlocal.infrastructure.persistence.migrations import Migration


@dataclass(frozen=True, slots=True)
class AppliedMigration:
    """A migration previously applied to a database."""

    version: int
    filename: str
    checksum_sha256: str


class MigrationHistoryError(RuntimeError):
    """Raised when migration files conflict with database history."""


def load_applied_migrations(
    connection: sqlite3.Connection,
) -> dict[int, AppliedMigration]:
    """Return migrations already applied to the database."""

    table_exists = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'schema_migrations'
        """
    ).fetchone()

    if table_exists is None:
        return {}

    rows = connection.execute(
        """
        SELECT version, filename, checksum_sha256
        FROM schema_migrations
        ORDER BY version
        """
    ).fetchall()

    return {
        int(row["version"]): AppliedMigration(
            version=int(row["version"]),
            filename=str(row["filename"]),
            checksum_sha256=str(row["checksum_sha256"]),
        )
        for row in rows
    }


def select_pending_migrations(
    migrations: tuple[Migration, ...],
    applied_migrations: dict[int, AppliedMigration],
) -> tuple[Migration, ...]:
    """Validate migration history and return migrations not yet applied."""

    migrations_by_version = {migration.version: migration for migration in migrations}

    for version, applied in applied_migrations.items():
        migration = migrations_by_version.get(version)

        if migration is None:
            raise MigrationHistoryError(f"Applied migration file is missing: version {version}")

        if migration.filename != applied.filename:
            raise MigrationHistoryError(f"Migration filename mismatch for version {version}")

        if migration.checksum_sha256 != applied.checksum_sha256:
            raise MigrationHistoryError(f"Migration checksum mismatch for version {version}")

    return tuple(
        migration for migration in migrations if migration.version not in applied_migrations
    )
