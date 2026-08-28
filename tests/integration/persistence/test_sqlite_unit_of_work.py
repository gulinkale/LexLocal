"""Integration tests for the SQLite Unit of Work."""

import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

from lexlocal.infrastructure.persistence.sqlite_connection import (
    SQLiteConnectionFactory,
)
from lexlocal.infrastructure.persistence.sqlite_unit_of_work import (
    SQLiteUnitOfWork as _SQLiteUnitOfWork,
)
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
)


class SQLiteUnitOfWork(_SQLiteUnitOfWork):
    """Supply the explicit development adapter to legacy UoW behavior tests."""

    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        super().__init__(
            connection_factory,
            InsecureDevelopmentOnlyWorkspaceNamePersistence(),
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


def test_connection_access_outside_scope_fails(tmp_path: Path) -> None:
    unit_of_work = SQLiteUnitOfWork(SQLiteConnectionFactory(tmp_path / "lexlocal.db"))

    with pytest.raises(RuntimeError, match="transaction is not active"):
        _ = unit_of_work.connection


@pytest.mark.parametrize("operation", ["commit", "rollback"])
def test_finalization_outside_scope_fails(
    tmp_path: Path,
    operation: str,
) -> None:
    unit_of_work = SQLiteUnitOfWork(SQLiteConnectionFactory(tmp_path / "lexlocal.db"))

    with pytest.raises(RuntimeError, match="transaction is not active"):
        getattr(unit_of_work, operation)()


def test_repeated_entry_while_active_fails(tmp_path: Path) -> None:
    unit_of_work = SQLiteUnitOfWork(SQLiteConnectionFactory(tmp_path / "lexlocal.db"))

    with unit_of_work:
        with pytest.raises(RuntimeError, match="already active"):
            unit_of_work.__enter__()


def test_sql_access_after_commit_is_rejected_and_cannot_autocommit(
    tmp_path: Path,
) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    create_test_table(factory)
    unit_of_work = SQLiteUnitOfWork(factory)

    with unit_of_work:
        connection = unit_of_work.connection
        connection.execute("INSERT INTO test_records (value) VALUES ('committed')")
        unit_of_work.commit()

        with pytest.raises(RuntimeError, match="transaction is not active"):
            _ = unit_of_work.connection
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("INSERT INTO test_records (value) VALUES ('escaped')")

    assert read_values(factory) == ["committed"]


def test_sql_access_after_rollback_is_rejected_and_cannot_autocommit(
    tmp_path: Path,
) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    create_test_table(factory)
    unit_of_work = SQLiteUnitOfWork(factory)

    with unit_of_work:
        connection = unit_of_work.connection
        connection.execute("INSERT INTO test_records (value) VALUES ('rolled-back')")
        unit_of_work.rollback()

        with pytest.raises(RuntimeError, match="transaction is not active"):
            _ = unit_of_work.connection
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("INSERT INTO test_records (value) VALUES ('escaped')")

    assert read_values(factory) == []


@pytest.mark.parametrize(
    ("first_operation", "second_operation"),
    [
        ("commit", "commit"),
        ("rollback", "rollback"),
        ("rollback", "commit"),
        ("commit", "rollback"),
    ],
)
def test_finalized_transaction_rejects_another_finalization(
    tmp_path: Path,
    first_operation: str,
    second_operation: str,
) -> None:
    unit_of_work = SQLiteUnitOfWork(SQLiteConnectionFactory(tmp_path / "lexlocal.db"))

    with unit_of_work:
        getattr(unit_of_work, first_operation)()

        with pytest.raises(RuntimeError, match="transaction is not active"):
            getattr(unit_of_work, second_operation)()


def test_begin_failure_closes_new_connection() -> None:
    connection = Mock(spec=sqlite3.Connection)
    connection.execute.side_effect = sqlite3.OperationalError("begin failed")
    connection_factory = Mock()
    connection_factory.create.return_value = connection
    unit_of_work = SQLiteUnitOfWork(connection_factory)

    with pytest.raises(sqlite3.OperationalError, match="begin failed"):
        unit_of_work.__enter__()

    connection.close.assert_called_once_with()
    with pytest.raises(RuntimeError, match="transaction is not active"):
        _ = unit_of_work.connection


def test_unit_of_work_can_be_reused_after_scope_exit(tmp_path: Path) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    create_test_table(factory)
    unit_of_work = SQLiteUnitOfWork(factory)

    with unit_of_work:
        unit_of_work.connection.execute(
            "INSERT INTO test_records (value) VALUES ('first-scope')"
        )
        unit_of_work.commit()

    with unit_of_work:
        unit_of_work.connection.execute(
            "INSERT INTO test_records (value) VALUES ('second-scope')"
        )
        unit_of_work.commit()

    assert read_values(factory) == ["first-scope", "second-scope"]
