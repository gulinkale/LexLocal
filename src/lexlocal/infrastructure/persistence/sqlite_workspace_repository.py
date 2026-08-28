"""Implement workspace persistence with an existing SQLite transaction."""

import re
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime

from lexlocal.application.ports.security import SecurityContractError
from lexlocal.application.ports.workspaces import (
    WorkspaceConflict,
    WorkspacePersistenceError,
    WorkspaceRepository,
)
from lexlocal.domain.errors import InvalidDomainValue
from lexlocal.domain.identifiers import WorkspaceId
from lexlocal.domain.workspace import Workspace, WorkspaceProfile, WorkspaceState
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
)

_UTC_MILLISECOND_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z"
)


class SQLiteWorkspaceRepository(WorkspaceRepository):
    """Persist synthetic M1 workspaces on a caller-owned SQLite transaction."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        name_persistence: InsecureDevelopmentOnlyWorkspaceNamePersistence,
    ) -> None:
        self._connection = connection
        self._name_persistence = name_persistence

    def add(self, workspace: Workspace) -> None:
        """Stage one workspace without finalizing the caller's transaction."""
        self._require_active_transaction()
        if not isinstance(workspace, Workspace):
            raise WorkspacePersistenceError("workspace data is invalid")

        try:
            encoded_name = self._name_persistence.encode(
                workspace.id,
                workspace.display_name,
            )
            lookup_token = self._name_persistence.lookup_token(
                workspace.display_name
            )
            created_at = self._serialize_timestamp(workspace.created_at)
            updated_at = self._serialize_timestamp(workspace.updated_at)
            profile = workspace.profile.value if workspace.profile is not None else None
            profile_source = "USER" if workspace.profile is not None else None
            profile_confirmed_at = (
                created_at if workspace.profile is not None else None
            )

            self._connection.execute(
                """
                INSERT INTO workspaces (
                    id,
                    name_ciphertext,
                    name_lookup_fingerprint,
                    state,
                    profile,
                    profile_source,
                    suggested_profile,
                    suggested_profile_model_id,
                    profile_suggested_at,
                    profile_confirmed_at,
                    created_at,
                    updated_at,
                    archived_at,
                    deletion_started_at
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, NULL, NULL)
                """,
                (
                    str(workspace.id),
                    encoded_name.payload,
                    lookup_token,
                    workspace.state.value,
                    profile,
                    profile_source,
                    profile_confirmed_at,
                    created_at,
                    updated_at,
                ),
            )
        except sqlite3.IntegrityError:
            raise WorkspaceConflict("workspace already exists") from None
        except (InvalidDomainValue, SecurityContractError, TypeError, ValueError):
            raise WorkspacePersistenceError("workspace data is invalid") from None
        except sqlite3.DatabaseError:
            raise WorkspacePersistenceError("workspace persistence failed") from None

    def get(self, workspace_id: WorkspaceId) -> Workspace | None:
        """Return one active workspace without exposing unavailable row state."""
        self._require_workspace_id(workspace_id)
        self._require_active_transaction()

        try:
            row = self._connection.execute(
                """
                SELECT
                    id,
                    name_ciphertext,
                    state,
                    profile,
                    created_at,
                    updated_at
                FROM workspaces
                WHERE id = ?
                  AND state = 'ACTIVE'
                """,
                (str(workspace_id),),
            ).fetchone()
        except sqlite3.DatabaseError:
            raise WorkspacePersistenceError("workspace persistence failed") from None

        if row is None:
            return None
        return self._map_row(row)

    def list_normal(self) -> Sequence[Workspace]:
        """Return all active workspaces without defining a public order."""
        self._require_active_transaction()

        try:
            rows = self._connection.execute(
                """
                SELECT
                    id,
                    name_ciphertext,
                    state,
                    profile,
                    created_at,
                    updated_at
                FROM workspaces
                WHERE state = 'ACTIVE'
                """
            ).fetchall()
        except sqlite3.DatabaseError:
            raise WorkspacePersistenceError("workspace persistence failed") from None

        return tuple(self._map_row(row) for row in rows)

    def _map_row(self, row: sqlite3.Row) -> Workspace:
        try:
            workspace_id = WorkspaceId(self._require_string(row["id"]))
            payload = self._require_bytes(row["name_ciphertext"])
            encoded_name = self._name_persistence.restore_payload(
                workspace_id,
                payload,
            )
            display_name = self._name_persistence.decode(
                workspace_id,
                encoded_name,
            )
            profile_value = row["profile"]
            profile = (
                None
                if profile_value is None
                else WorkspaceProfile(self._require_string(profile_value))
            )
            return Workspace(
                id=workspace_id,
                display_name=display_name,
                created_at=self._parse_timestamp(row["created_at"]),
                updated_at=self._parse_timestamp(row["updated_at"]),
                profile=profile,
                state=WorkspaceState(self._require_string(row["state"])),
            )
        except (
            InvalidDomainValue,
            KeyError,
            SecurityContractError,
            TypeError,
            ValueError,
        ):
            raise WorkspacePersistenceError("workspace data is invalid") from None

    def _require_active_transaction(self) -> None:
        if not self._connection.in_transaction:
            raise WorkspacePersistenceError(
                "workspace repository requires an active transaction"
            )

    @staticmethod
    def _require_workspace_id(workspace_id: WorkspaceId) -> None:
        if not isinstance(workspace_id, WorkspaceId):
            raise WorkspacePersistenceError("workspace id is invalid")

    @staticmethod
    def _serialize_timestamp(value: datetime) -> str:
        return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    @staticmethod
    def _parse_timestamp(value: object) -> datetime:
        timestamp = SQLiteWorkspaceRepository._require_string(value)
        if _UTC_MILLISECOND_PATTERN.fullmatch(timestamp) is None:
            raise ValueError("timestamp format is invalid")
        return datetime.strptime(
            timestamp,
            "%Y-%m-%dT%H:%M:%S.%fZ",
        ).replace(tzinfo=UTC)

    @staticmethod
    def _require_string(value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("stored value must be a string")
        return value

    @staticmethod
    def _require_bytes(value: object) -> bytes:
        if not isinstance(value, bytes):
            raise TypeError("stored value must be bytes")
        return value
