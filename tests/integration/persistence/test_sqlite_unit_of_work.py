"""Integration tests for the SQLite Unit of Work."""

import sqlite3
from pathlib import Path

import pytest

from lexlocal.infrastructure.persistence.sqlite_connection import (
    SQLiteConnectionFactory,
)
from lexlocal.infrastructure.persistence.sqlite_unit_of_work import (
    SQLiteUnitOfWork,
)


def create_test_table(
    factory: SQLiteConnectionFactory,
) -> None:
    """Create a simple table outside a Unit of Work."""

    connection = factory.create()

    try:
        connection.execute(
            """
            CREATE TABLE test_records (
                id INTEGER PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
    finally:
        connection.close()


def read_values(
    factory: SQLiteConnectionFactory,
) -> list[str]:
    """Read persisted values using a new connection."""

    connection = factory.create()

    try:
        rows = connection.execute(
            """
            SELECT value
            FROM test_records
            ORDER BY id
            """
        ).fetchall()
    finally:
        connection.close()

    return [str(row["value"]) for row in rows]


def test_commit_makes_changes_permanent(
    tmp_path: Path,
) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    create_test_table(factory)

    unit_of_work = SQLiteUnitOfWork(factory)

    with unit_of_work:
        unit_of_work.connection.execute(
            """
            INSERT INTO test_records (value)
            VALUES (?)
            """,
            ("committed",),
        )
        unit_of_work.commit()

    assert read_values(factory) == ["committed"]


def test_missing_commit_rolls_back_changes(
    tmp_path: Path,
) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    create_test_table(factory)

    unit_of_work = SQLiteUnitOfWork(factory)

    with unit_of_work:
        unit_of_work.connection.execute(
            """
            INSERT INTO test_records (value)
            VALUES (?)
            """,
            ("not-committed",),
        )

    assert read_values(factory) == []


def test_exception_rolls_back_changes(
    tmp_path: Path,
) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    create_test_table(factory)

    unit_of_work = SQLiteUnitOfWork(factory)

    with pytest.raises(
        RuntimeError,
        match="operation failed",
    ):
        with unit_of_work:
            unit_of_work.connection.execute(
                """
                INSERT INTO test_records (value)
                VALUES (?)
                """,
                ("should-be-rolled-back",),
            )

            raise RuntimeError("operation failed")

    assert read_values(factory) == []


def test_explicit_rollback_discards_changes(
    tmp_path: Path,
) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    create_test_table(factory)

    unit_of_work = SQLiteUnitOfWork(factory)

    with unit_of_work:
        unit_of_work.connection.execute(
            """
            INSERT INTO test_records (value)
            VALUES (?)
            """,
            ("rolled-back",),
        )
        unit_of_work.rollback()

    assert read_values(factory) == []


def test_connection_is_closed_after_scope(
    tmp_path: Path,
) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    create_test_table(factory)

    unit_of_work = SQLiteUnitOfWork(factory)

    with unit_of_work:
        connection = unit_of_work.connection
        unit_of_work.commit()

    with pytest.raises(
        sqlite3.ProgrammingError,
        match="closed",
    ):
        connection.execute("SELECT 1")
