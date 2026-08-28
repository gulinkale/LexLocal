"""Orchestrate the minimal workspace Application behavior."""

from collections.abc import Callable, Sequence
from datetime import datetime

from lexlocal.application.ports.unit_of_work import UnitOfWork
from lexlocal.domain.errors import InvalidDomainValue
from lexlocal.domain.identifiers import WorkspaceId
from lexlocal.domain.workspace import Workspace, WorkspaceProfile, WorkspaceState


class WorkspaceNotFound(Exception):
    """Report that a workspace is unavailable for normal M1 access."""


class ActiveWorkspaceRequired(Exception):
    """Report that an operation requires an active workspace selection."""


class ActiveWorkspaceScope:
    """Hold the sole workspace identifier selected in this process."""

    __slots__ = ("_workspace_id",)

    def __init__(self) -> None:
        self._workspace_id: WorkspaceId | None = None

    def select(self, workspace_id: WorkspaceId) -> None:
        """Replace the current selection with a typed workspace identifier."""
        if not isinstance(workspace_id, WorkspaceId):
            raise InvalidDomainValue("active workspace id must be a WorkspaceId")
        self._workspace_id = workspace_id

    def clear(self) -> None:
        """Remove the current workspace selection."""
        self._workspace_id = None

    def require_workspace_id(self) -> WorkspaceId:
        """Return the selected workspace identifier or fail closed."""
        if self._workspace_id is None:
            raise ActiveWorkspaceRequired("an active workspace is required")
        return self._workspace_id


class CreateWorkspace:
    """Create one active workspace in an explicit transaction."""

    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWork],
        workspace_id_factory: Callable[[], WorkspaceId],
        clock: Callable[[], datetime],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._workspace_id_factory = workspace_id_factory
        self._clock = clock

    def __call__(
        self,
        display_name: str,
        profile: WorkspaceProfile | None = None,
    ) -> Workspace:
        timestamp = self._clock()
        workspace = Workspace(
            id=self._workspace_id_factory(),
            display_name=display_name,
            created_at=timestamp,
            updated_at=timestamp,
            profile=profile,
        )

        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.workspaces.add(workspace)
            unit_of_work.commit()

        return workspace


class ListWorkspaces:
    """List workspaces available to normal M1 behavior."""

    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWork],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def __call__(self) -> Sequence[Workspace]:
        with self._unit_of_work_factory() as unit_of_work:
            return tuple(unit_of_work.workspaces.list_normal())


class SelectWorkspace:
    """Select an active workspace as the sole downstream Application scope."""

    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWork],
        active_scope: ActiveWorkspaceScope,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._active_scope = active_scope

    def __call__(self, workspace_id: WorkspaceId) -> WorkspaceId:
        if not isinstance(workspace_id, WorkspaceId):
            raise InvalidDomainValue("workspace id must be a WorkspaceId")

        with self._unit_of_work_factory() as unit_of_work:
            workspace = unit_of_work.workspaces.get(workspace_id)

        if workspace is None or workspace.state is not WorkspaceState.ACTIVE:
            raise WorkspaceNotFound("workspace is unavailable")

        self._active_scope.select(workspace.id)
        return workspace.id
