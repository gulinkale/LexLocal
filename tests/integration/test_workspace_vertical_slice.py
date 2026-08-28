"""End-to-end integration test for the synthetic workspace vertical slice."""

from pathlib import Path

import pytest

from lexlocal.application.workspaces import ActiveWorkspaceRequired, WorkspaceNotFound
from lexlocal.bootstrap.persistence import (
    WorkspaceApplicationComposition,
    compose_workspace_application,
    initialize_persistence,
)
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import WorkspaceId
from lexlocal.domain.workspace import WorkspaceProfile


def make_composition(tmp_path: Path) -> WorkspaceApplicationComposition:
    settings = AppSettings(
        app_name="LexLocal",
        environment="test",
        log_level="INFO",
        data_dir=tmp_path,
        security_provider="insecure-development-only",
    )
    return compose_workspace_application(
        settings,
        initialize_persistence(settings),
    )


def test_create_list_explicit_select_and_require_typed_scope(tmp_path: Path) -> None:
    composition = make_composition(tmp_path)

    created = composition.create_workspace(
        "Synthetic Workspace",
        WorkspaceProfile.GENERAL_LEGAL,
    )

    with pytest.raises(ActiveWorkspaceRequired):
        composition.active_scope.require_workspace_id()
    assert composition.list_workspaces() == (created,)
    assert composition.select_workspace(created.id) == created.id
    selected = composition.active_scope.require_workspace_id()
    assert selected == created.id
    assert isinstance(selected, WorkspaceId)


def test_shared_scope_replacement_failure_and_clear(tmp_path: Path) -> None:
    composition = make_composition(tmp_path)
    first = composition.create_workspace("First Synthetic Workspace")
    second = composition.create_workspace("Second Synthetic Workspace")

    composition.select_workspace(first.id)
    assert composition.select_workspace(second.id) == second.id
    assert composition.active_scope.require_workspace_id() == second.id

    unavailable_id = WorkspaceId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    with pytest.raises(WorkspaceNotFound):
        composition.select_workspace(unavailable_id)
    assert composition.active_scope.require_workspace_id() == second.id

    composition.active_scope.clear()
    with pytest.raises(ActiveWorkspaceRequired):
        composition.active_scope.require_workspace_id()
