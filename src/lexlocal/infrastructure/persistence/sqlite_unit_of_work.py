"""Manage SQLite transactions for application operations."""

import sqlite3
from enum import Enum, auto
from types import TracebackType
from typing import Self

from lexlocal.application.ports.ingestion import IngestionRepository
from lexlocal.application.ports.local_models import ResolvedModelRepository
from lexlocal.application.ports.processing import ProcessingRepository
from lexlocal.application.ports.security import SensitivePayloadCodec
from lexlocal.application.ports.unit_of_work import UnitOfWork
from lexlocal.application.ports.workspaces import WorkspaceRepository
from lexlocal.infrastructure.persistence.sqlite_connection import (
    SQLiteConnectionFactory,
)
from lexlocal.infrastructure.persistence.sqlite_ingestion_repository import (
    SQLiteIngestionRepository,
)
from lexlocal.infrastructure.persistence.sqlite_local_model_repository import (
    SQLiteResolvedModelRepository,
)
from lexlocal.infrastructure.persistence.sqlite_processing_repository import (
    SQLiteProcessingRepository,
)
from lexlocal.infrastructure.persistence.sqlite_workspace_repository import (
    SQLiteWorkspaceRepository,
)
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
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
        name_persistence: InsecureDevelopmentOnlyWorkspaceNamePersistence,
        processing_payload_codec: SensitivePayloadCodec | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._name_persistence = name_persistence
        self._processing_payload_codec = processing_payload_codec
        self._connection: sqlite3.Connection | None = None
        self._workspace_repository: SQLiteWorkspaceRepository | None = None
        self._local_model_repository: SQLiteResolvedModelRepository | None = None
        self._ingestion_repository: SQLiteIngestionRepository | None = None
        self._processing_repository: SQLiteProcessingRepository | None = None
        self._state = _UnitOfWorkState.INACTIVE

    @property
    def workspaces(self) -> WorkspaceRepository:
        """Return the workspace repository bound to the active transaction."""
        if (
            self._state is not _UnitOfWorkState.ACTIVE
            or self._workspace_repository is None
        ):
            raise RuntimeError("Unit of Work transaction is not active")
        return self._workspace_repository

    @property
    def local_models(self) -> ResolvedModelRepository:
        """Return the local-model repository bound to the active transaction."""

        if (
            self._state is not _UnitOfWorkState.ACTIVE
            or self._local_model_repository is None
        ):
            raise RuntimeError("Unit of Work transaction is not active")
        return self._local_model_repository

    @property
    def ingestion(self) -> IngestionRepository:
        """Return the ingestion repository bound to the active transaction."""
        if self._state is not _UnitOfWorkState.ACTIVE or self._ingestion_repository is None:
            raise RuntimeError("Unit of Work transaction is not active")
        return self._ingestion_repository

    @property
    def processing(self) -> ProcessingRepository:
        """Return the configured processing repository for this transaction."""

        if self._state is not _UnitOfWorkState.ACTIVE:
            raise RuntimeError("Unit of Work transaction is not active")
        if self._processing_repository is None:
            raise RuntimeError("processing repository is not configured")
        return self._processing_repository

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
        self._workspace_repository = SQLiteWorkspaceRepository(
            connection,
            self._name_persistence,
        )
        self._local_model_repository = SQLiteResolvedModelRepository(connection)
        self._ingestion_repository = SQLiteIngestionRepository(connection)
        self._processing_repository = (
            SQLiteProcessingRepository(connection, self._processing_payload_codec)
            if self._processing_payload_codec is not None
            else None
        )
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
            self._workspace_repository = None
            self._local_model_repository = None
            self._ingestion_repository = None
            self._processing_repository = None
            self._state = _UnitOfWorkState.INACTIVE

    def commit(self) -> None:
        """Make the current transaction permanent."""

        connection = self.connection
        connection.commit()
        try:
            connection.close()
        finally:
            self._workspace_repository = None
            self._local_model_repository = None
            self._ingestion_repository = None
            self._processing_repository = None
            self._state = _UnitOfWorkState.COMMITTED

    def rollback(self) -> None:
        """Discard the current transaction."""

        connection = self.connection
        connection.rollback()
        try:
            connection.close()
        finally:
            self._workspace_repository = None
            self._local_model_repository = None
            self._ingestion_repository = None
            self._processing_repository = None
            self._state = _UnitOfWorkState.ROLLED_BACK
