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


class MigrationExecutionError(RuntimeError):
    """Raised when pending migrations cannot be applied."""


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


def _sql_string_literal(value: str) -> str:
    """Return a safely quoted SQLite string literal."""

    escaped_value = value.replace("'", "''")
    return f"'{escaped_value}'"


def run_migrations(
    connection: sqlite3.Connection,
    migrations: tuple[Migration, ...],
) -> tuple[Migration, ...]:
    """Apply all pending migrations in one atomic transaction."""

    applied_migrations = load_applied_migrations(connection)

    pending_migrations = select_pending_migrations(
        migrations,
        applied_migrations,
    )

    if not pending_migrations:
        return ()

    script_parts = ["BEGIN IMMEDIATE;"]

    for migration in pending_migrations:
        script_parts.append(migration.sql)

        script_parts.append(
            f"""
            INSERT INTO schema_migrations (
                version,
                filename,
                checksum_sha256,
                applied_at
            )
            VALUES (
                {migration.version},
                {_sql_string_literal(migration.filename)},
                {_sql_string_literal(migration.checksum_sha256)},
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            );
            """
        )

    script_parts.append("COMMIT;")

    try:
        connection.executescript("\n".join(script_parts))
    except sqlite3.Error as exc:
        if connection.in_transaction:
            connection.rollback()

        first_pending_version = pending_migrations[0].version

        raise MigrationExecutionError(
            f"Failed to apply pending migrations starting at version {first_pending_version}"
        ) from exc

    return pending_migrations
