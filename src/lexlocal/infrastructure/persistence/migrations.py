"""Discover and describe SQL migration files."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


def default_migrations_dir() -> Path:
    """Return the directory containing packaged SQL migrations."""

    return Path(__file__).with_name("sql_migrations")


_MIGRATION_FILENAME_PATTERN = re.compile(r"^(?P<version>\d+)_[a-z0-9_]+\.sql$")


@dataclass(frozen=True, slots=True)
class Migration:
    """A versioned SQL migration file."""

    version: int
    filename: str
    checksum_sha256: str
    sql: str


def discover_migrations(
    migrations_dir: Path,
) -> tuple[Migration, ...]:
    """Load valid SQL migrations in version order."""

    migrations: list[Migration] = []
    seen_versions: set[int] = set()

    for path in sorted(migrations_dir.glob("*.sql")):
        match = _MIGRATION_FILENAME_PATTERN.fullmatch(path.name)
        if match is None:
            raise ValueError(f"Invalid migration filename: {path.name}")

        version = int(match.group("version"))

        if version <= 0:
            raise ValueError(f"Migration version must be positive: {path.name}")

        if version in seen_versions:
            raise ValueError(f"Duplicate migration version: {version}")

        migration_bytes = path.read_bytes()

        migrations.append(
            Migration(
                version=version,
                filename=path.name,
                checksum_sha256=hashlib.sha256(migration_bytes).hexdigest(),
                sql=migration_bytes.decode("utf-8"),
            )
        )
        seen_versions.add(version)

    return tuple(
        sorted(
            migrations,
            key=lambda migration: migration.version,
        )
    )
