"""Unit tests for migration discovery."""

import hashlib
from pathlib import Path

import pytest

from lexlocal.infrastructure.persistence.migrations import (
    discover_migrations,
)


def test_discovers_migrations_in_version_order(
    tmp_path: Path,
) -> None:
    (tmp_path / "002_second.sql").write_text(
        "SELECT 2;",
        encoding="utf-8",
    )
    first_sql = "SELECT 1;"
    (tmp_path / "001_first.sql").write_text(
        first_sql,
        encoding="utf-8",
    )

    migrations = discover_migrations(tmp_path)

    assert [migration.version for migration in migrations] == [1, 2]
    assert migrations[0].filename == "001_first.sql"
    assert migrations[0].sql == first_sql
    assert migrations[0].checksum_sha256 == hashlib.sha256(first_sql.encode("utf-8")).hexdigest()


def test_rejects_invalid_migration_filename(
    tmp_path: Path,
) -> None:
    (tmp_path / "initial.sql").write_text(
        "SELECT 1;",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="Invalid migration filename",
    ):
        discover_migrations(tmp_path)


def test_rejects_duplicate_migration_versions(
    tmp_path: Path,
) -> None:
    (tmp_path / "001_first.sql").write_text(
        "SELECT 1;",
        encoding="utf-8",
    )
    (tmp_path / "001_duplicate.sql").write_text(
        "SELECT 2;",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="Duplicate migration version",
    ):
        discover_migrations(tmp_path)


def test_rejects_zero_migration_version(
    tmp_path: Path,
) -> None:
    (tmp_path / "000_invalid.sql").write_text(
        "SELECT 1;",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="Migration version must be positive",
    ):
        discover_migrations(tmp_path)
