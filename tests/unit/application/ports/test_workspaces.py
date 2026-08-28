"""Tests for Application-owned workspace persistence contracts."""

from collections.abc import Sequence
from datetime import UTC, datetime

from lexlocal.application.ports.workspaces import WorkspaceRepository
from lexlocal.domain.identifiers import WorkspaceId
from lexlocal.domain.workspace import Workspace

WORKSPACE_ID = WorkspaceId("550e8400-e29b-41d4-a716-446655440000")
NOW = datetime(2026, 8, 28, 9, 30, tzinfo=UTC)


class _WorkspaceRepositoryDouble:
    def __init__(self) -> None:
        self.workspace = Workspace(
            id=WORKSPACE_ID,
            display_name="Synthetic Workspace",
            created_at=NOW,
            updated_at=NOW,
        )

    def add(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def get(self, workspace_id: WorkspaceId) -> Workspace | None:
        return self.workspace if workspace_id == self.workspace.id else None

    def list_normal(self) -> Sequence[Workspace]:
        return (self.workspace,)


_REPOSITORY_CONFORMANCE: WorkspaceRepository = _WorkspaceRepositoryDouble()


def test_workspace_repository_double_conforms_to_minimal_contract() -> None:
    repository = _WorkspaceRepositoryDouble()

    assert repository.get(WORKSPACE_ID) == repository.workspace
    assert repository.list_normal() == (repository.workspace,)
