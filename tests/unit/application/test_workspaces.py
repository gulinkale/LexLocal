"""Unit tests for minimal workspace Application behavior."""

from collections.abc import Sequence
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

import pytest

from lexlocal.application.ports.workspaces import (
    WorkspaceConflict,
    WorkspaceRepository,
)
from lexlocal.application.workspaces import (
    ActiveWorkspaceRequired,
    ActiveWorkspaceScope,
    CreateWorkspace,
    ListWorkspaces,
    SelectWorkspace,
    WorkspaceNotFound,
)
from lexlocal.domain.errors import InvalidDomainValue
from lexlocal.domain.identifiers import DocumentId, WorkspaceId
from lexlocal.domain.workspace import Workspace, WorkspaceProfile, WorkspaceState

WORKSPACE_ID = WorkspaceId("550e8400-e29b-41d4-a716-446655440000")
OTHER_WORKSPACE_ID = WorkspaceId("123e4567-e89b-12d3-a456-426614174000")
NOW = datetime(2026, 8, 28, 9, 30, tzinfo=UTC)


def make_workspace(
    workspace_id: WorkspaceId = WORKSPACE_ID,
    state: WorkspaceState = WorkspaceState.ACTIVE,
) -> Workspace:
    return Workspace(
        id=workspace_id,
        display_name="Synthetic Workspace",
        created_at=NOW,
        updated_at=NOW,
        state=state,
    )


class _FakeWorkspaceRepository:
    def __init__(self, workspaces: Sequence[Workspace] = ()) -> None:
        self.workspaces = {workspace.id: workspace for workspace in workspaces}
        self.added: list[Workspace] = []
        self.add_error: Exception | None = None

    def add(self, workspace: Workspace) -> None:
        if self.add_error is not None:
            raise self.add_error
        self.added.append(workspace)
        self.workspaces[workspace.id] = workspace

    def get(self, workspace_id: WorkspaceId) -> Workspace | None:
        workspace = self.workspaces.get(workspace_id)
        if workspace is None or workspace.state is not WorkspaceState.ACTIVE:
            return None
        return workspace

    def list_normal(self) -> Sequence[Workspace]:
        return tuple(
            workspace
            for workspace in self.workspaces.values()
            if workspace.state is WorkspaceState.ACTIVE
        )


class _FakeUnitOfWork:
    def __init__(self, repository: WorkspaceRepository) -> None:
        self.workspaces = repository
        self.entered = False
        self.exited = False
        self.commits = 0
        self.exit_exception_type: type[BaseException] | None = None

    def __enter__(self) -> Self:
        self.entered = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exited = True
        self.exit_exception_type = exc_type

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass


class _UnitOfWorkFactory:
    def __init__(self, repository: WorkspaceRepository) -> None:
        self.repository = repository
        self.created: list[_FakeUnitOfWork] = []

    def __call__(self) -> _FakeUnitOfWork:
        unit_of_work = _FakeUnitOfWork(self.repository)
        self.created.append(unit_of_work)
        return unit_of_work


def test_create_workspace_builds_active_aggregate_and_commits_once() -> None:
    repository = _FakeWorkspaceRepository()
    unit_of_work_factory = _UnitOfWorkFactory(repository)
    create = CreateWorkspace(
        unit_of_work_factory,
        lambda: WORKSPACE_ID,
        lambda: NOW,
    )

    workspace = create("Synthetic Workspace", WorkspaceProfile.LITIGATION)

    assert workspace == Workspace(
        id=WORKSPACE_ID,
        display_name="Synthetic Workspace",
        created_at=NOW,
        updated_at=NOW,
        profile=WorkspaceProfile.LITIGATION,
    )
    assert repository.added == [workspace]
    assert unit_of_work_factory.created[0].commits == 1
    assert unit_of_work_factory.created[0].exited is True


def test_create_workspace_failure_does_not_commit() -> None:
    repository = _FakeWorkspaceRepository()
    repository.add_error = WorkspaceConflict("workspace conflict")
    unit_of_work_factory = _UnitOfWorkFactory(repository)
    create = CreateWorkspace(
        unit_of_work_factory,
        lambda: WORKSPACE_ID,
        lambda: NOW,
    )

    with pytest.raises(WorkspaceConflict, match="workspace conflict"):
        create("Synthetic Workspace")

    unit_of_work = unit_of_work_factory.created[0]
    assert unit_of_work.commits == 0
    assert unit_of_work.exit_exception_type is WorkspaceConflict


def test_list_workspaces_returns_only_repository_normal_list_without_selecting() -> None:
    active = make_workspace()
    archived = make_workspace(OTHER_WORKSPACE_ID, WorkspaceState.ARCHIVED)
    repository = _FakeWorkspaceRepository((active, archived))
    active_scope = ActiveWorkspaceScope()

    result = ListWorkspaces(_UnitOfWorkFactory(repository))()

    assert result == (active,)
    with pytest.raises(ActiveWorkspaceRequired):
        active_scope.require_workspace_id()


def test_select_workspace_sets_and_replaces_the_sole_scope() -> None:
    first = make_workspace()
    second = make_workspace(OTHER_WORKSPACE_ID)
    repository = _FakeWorkspaceRepository((first, second))
    active_scope = ActiveWorkspaceScope()
    select = SelectWorkspace(_UnitOfWorkFactory(repository), active_scope)

    assert select(first.id) == first.id
    assert active_scope.require_workspace_id() == first.id
    assert select(second.id) == second.id
    assert active_scope.require_workspace_id() == second.id


@pytest.mark.parametrize(
    "state",
    [
        WorkspaceState.ARCHIVED,
        WorkspaceState.DELETING,
        WorkspaceState.DELETION_RECOVERY,
    ],
)
def test_select_workspace_rejects_non_active_state_and_preserves_selection(
    state: WorkspaceState,
) -> None:
    active = make_workspace()
    unavailable = make_workspace(OTHER_WORKSPACE_ID, state)
    repository = _FakeWorkspaceRepository((active, unavailable))
    active_scope = ActiveWorkspaceScope()
    active_scope.select(active.id)
    select = SelectWorkspace(_UnitOfWorkFactory(repository), active_scope)

    with pytest.raises(WorkspaceNotFound, match="workspace is unavailable"):
        select(unavailable.id)

    assert active_scope.require_workspace_id() == active.id


def test_select_missing_workspace_preserves_selection() -> None:
    active_scope = ActiveWorkspaceScope()
    active_scope.select(WORKSPACE_ID)
    select = SelectWorkspace(
        _UnitOfWorkFactory(_FakeWorkspaceRepository()),
        active_scope,
    )

    with pytest.raises(WorkspaceNotFound, match="workspace is unavailable"):
        select(OTHER_WORKSPACE_ID)

    assert active_scope.require_workspace_id() == WORKSPACE_ID


def test_active_workspace_scope_clear_returns_to_absent_state() -> None:
    active_scope = ActiveWorkspaceScope()
    active_scope.select(WORKSPACE_ID)

    active_scope.clear()

    with pytest.raises(ActiveWorkspaceRequired, match="active workspace is required"):
        active_scope.require_workspace_id()


@pytest.mark.parametrize(
    "invalid_id",
    [str(WORKSPACE_ID), DocumentId(str(WORKSPACE_ID))],
)
def test_selection_rejects_non_workspace_identifier_before_repository_access(
    invalid_id: object,
) -> None:
    repository = _FakeWorkspaceRepository((make_workspace(),))
    unit_of_work_factory = _UnitOfWorkFactory(repository)
    select = SelectWorkspace(unit_of_work_factory, ActiveWorkspaceScope())

    with pytest.raises(InvalidDomainValue):
        select(invalid_id)  # type: ignore[arg-type]

    assert unit_of_work_factory.created == []
