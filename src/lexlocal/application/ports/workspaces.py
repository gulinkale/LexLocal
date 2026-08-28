"""Define Application-owned workspace persistence contracts."""

from collections.abc import Sequence
from typing import Protocol

from lexlocal.domain.identifiers import WorkspaceId
from lexlocal.domain.workspace import Workspace


class WorkspaceConflict(Exception):
    """Report that a workspace cannot be added without exposing persistence."""


class WorkspacePersistenceError(Exception):
    """Report a sanitized workspace persistence contract failure."""


class WorkspaceRepository(Protocol):
    """Persist and load workspaces required by normal M1 behavior."""

    def add(self, workspace: Workspace) -> None:
        """Stage a valid workspace in the current transaction."""

        ...

    def get(self, workspace_id: WorkspaceId) -> Workspace | None:
        """Return an active workspace, or None when it is unavailable."""

        ...

    def list_normal(self) -> Sequence[Workspace]:
        """Return active workspaces without promising an order."""

        ...
