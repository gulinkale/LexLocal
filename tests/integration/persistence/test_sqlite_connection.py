"""Integration tests for the SQLite connection factory."""

import sqlite3
from pathlib import Path

import pytest

from lexlocal.infrastructure.persistence.sqlite_connection import (
    SQLiteConnectionFactory,
)


def test_factory_creates_database_and_parent_directory(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "data" / "lexlocal.db"
    factory = SQLiteConnectionFactory(database_path)

    connection = factory.create()

    try:
        assert database_path.exists()
    finally:
        connection.close()


def test_factory_enables_foreign_keys(tmp_path: Path) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    connection = factory.create()

    try:
        row = connection.execute("PRAGMA foreign_keys").fetchone()

        assert row is not None
        assert row[0] == 1
    finally:
        connection.close()


def test_factory_configures_busy_timeout(tmp_path: Path) -> None:
    factory = SQLiteConnectionFactory(
        tmp_path / "lexlocal.db",
        busy_timeout_ms=2_500,
    )
    connection = factory.create()

    try:
        row = connection.execute("PRAGMA busy_timeout").fetchone()

        assert row is not None
        assert row[0] == 2_500
    finally:
        connection.close()


def test_factory_uses_named_rows(tmp_path: Path) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    connection = factory.create()

    try:
        connection.execute("CREATE TABLE examples (id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute(
            "INSERT INTO examples(name) VALUES (?)",
            ("LexLocal",),
        )

        row = connection.execute("SELECT id, name FROM examples").fetchone()

        assert isinstance(row, sqlite3.Row)
        assert row["name"] == "LexLocal"
    finally:
        connection.close()


def test_factory_rejects_negative_busy_timeout(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="busy_timeout_ms must be non-negative",
    ):
        SQLiteConnectionFactory(
            tmp_path / "lexlocal.db",
            busy_timeout_ms=-1,
        )


def test_factory_enables_wal_mode(tmp_path: Path) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    connection = factory.create()

    try:
        row = connection.execute("PRAGMA journal_mode").fetchone()

        assert row is not None
        assert str(row[0]).lower() == "wal"
    finally:
        connection.close()


def test_factory_configures_normal_synchronous(
    tmp_path: Path,
) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    connection = factory.create()

    try:
        row = connection.execute("PRAGMA synchronous").fetchone()

        assert row is not None
        assert row[0] == 1
    finally:
        connection.close()
