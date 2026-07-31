"""Manage SQLite transactions for application operations."""

import sqlite3
from types import TracebackType
from typing import Self

from lexlocal.application.ports.unit_of_work import UnitOfWork
from lexlocal.infrastructure.persistence.sqlite_connection import (
    SQLiteConnectionFactory,
)


class SQLiteUnitOfWork(UnitOfWork):
    """Manage one SQLite transaction and its connection."""

    def __init__(
        self,
        connection_factory: SQLiteConnectionFactory,
    ) -> None:
        self._connection_factory = connection_factory
        self._connection: sqlite3.Connection | None = None

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the active SQLite connection."""

        if self._connection is None:
            raise RuntimeError("Unit of Work is not active")

        return self._connection

    def __enter__(self) -> Self:
        """Open a connection and begin a transaction."""

        if self._connection is not None:
            raise RuntimeError("Unit of Work is already active")

        connection = self._connection_factory.create()

        try:
            connection.execute("BEGIN")
        except Exception:
            connection.close()
            raise

        self._connection = connection
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Rollback unfinished work and close the connection."""

        connection = self._connection

        if connection is None:
            return

        try:
            if connection.in_transaction:
                connection.rollback()
        finally:
            connection.close()
            self._connection = None

    def commit(self) -> None:
        """Make the current transaction permanent."""

        self.connection.commit()

    def rollback(self) -> None:
        """Discard the current transaction."""

        self.connection.rollback()
