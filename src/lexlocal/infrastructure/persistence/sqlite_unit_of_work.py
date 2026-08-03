"""Manage SQLite transactions for application operations."""

import sqlite3
from enum import Enum, auto
from types import TracebackType
from typing import Self

from lexlocal.application.ports.unit_of_work import UnitOfWork
from lexlocal.infrastructure.persistence.sqlite_connection import (
    SQLiteConnectionFactory,
)


class _UnitOfWorkState(Enum):
    INACTIVE = auto()
    ACTIVE = auto()
    COMMITTED = auto()
    ROLLED_BACK = auto()


class SQLiteUnitOfWork(UnitOfWork):
    """Manage one SQLite transaction and its connection."""

    def __init__(
        self,
        connection_factory: SQLiteConnectionFactory,
    ) -> None:
        self._connection_factory = connection_factory
        self._connection: sqlite3.Connection | None = None
        self._state = _UnitOfWorkState.INACTIVE

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the active SQLite connection."""

        if self._state is not _UnitOfWorkState.ACTIVE or self._connection is None:
            raise RuntimeError("Unit of Work transaction is not active")

        return self._connection

    def __enter__(self) -> Self:
        """Open a connection and begin a transaction."""

        if self._state is not _UnitOfWorkState.INACTIVE or self._connection is not None:
            raise RuntimeError("Unit of Work is already active")

        connection = self._connection_factory.create()

        try:
            connection.execute("BEGIN")
        except Exception:
            connection.close()
            raise

        self._connection = connection
        self._state = _UnitOfWorkState.ACTIVE
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
            if self._state is _UnitOfWorkState.ACTIVE and connection.in_transaction:
                connection.rollback()
        finally:
            connection.close()
            self._connection = None
            self._state = _UnitOfWorkState.INACTIVE

    def commit(self) -> None:
        """Make the current transaction permanent."""

        connection = self.connection
        connection.commit()
        try:
            connection.close()
        finally:
            self._state = _UnitOfWorkState.COMMITTED

    def rollback(self) -> None:
        """Discard the current transaction."""

        connection = self.connection
        connection.rollback()
        try:
            connection.close()
        finally:
            self._state = _UnitOfWorkState.ROLLED_BACK
