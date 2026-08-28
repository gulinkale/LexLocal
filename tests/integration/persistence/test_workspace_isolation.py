"""Integration evidence for workspace scope and database ownership isolation."""

import sqlite3
from pathlib import Path

import pytest

from lexlocal.application.workspaces import WorkspaceNotFound
from lexlocal.bootstrap.persistence import (
    WorkspaceApplicationComposition,
    compose_workspace_application,
    initialize_persistence,
)
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import WorkspaceId
from lexlocal.infrastructure.persistence.sqlite_connection import (
    SQLiteConnectionFactory,
)


def make_composition(
    tmp_path: Path,
) -> tuple[WorkspaceApplicationComposition, SQLiteConnectionFactory]:
    settings = AppSettings(
        app_name="LexLocal",
        environment="test",
        log_level="INFO",
        data_dir=tmp_path,
        security_provider="insecure-development-only",
    )
    connection_factory = initialize_persistence(settings)
    return (
        compose_workspace_application(settings, connection_factory),
        connection_factory,
    )


def set_workspace_state(
    connection_factory: SQLiteConnectionFactory,
    workspace_id: WorkspaceId,
    state: str,
) -> None:
    connection = connection_factory.create()
    try:
        connection.execute(
            "UPDATE workspaces SET state = ? WHERE id = ?",
            (state, str(workspace_id)),
        )
    finally:
        connection.close()


def test_successfully_resolved_active_workspace_replaces_sole_scope(
    tmp_path: Path,
) -> None:
    composition, _ = make_composition(tmp_path)
    workspace_a = composition.create_workspace("Synthetic Workspace A")
    workspace_b = composition.create_workspace("Synthetic Workspace B")

    composition.select_workspace(workspace_a.id)
    assert composition.active_scope.require_workspace_id() == workspace_a.id

    assert composition.select_workspace(workspace_b.id) == workspace_b.id
    assert composition.active_scope.require_workspace_id() == workspace_b.id


@pytest.mark.parametrize(
    "unavailable_state",
    [None, "ARCHIVED", "DELETING", "DELETION_RECOVERY"],
    ids=["missing", "archived", "deleting", "deletion-recovery"],
)
def test_unavailable_workspace_cannot_replace_existing_scope(
    tmp_path: Path,
    unavailable_state: str | None,
) -> None:
    composition, connection_factory = make_composition(tmp_path)
    workspace_a = composition.create_workspace("Synthetic Workspace A")
    workspace_b = composition.create_workspace("Synthetic Workspace B")
    composition.select_workspace(workspace_a.id)

    candidate_id = workspace_b.id
    if unavailable_state is None:
        candidate_id = WorkspaceId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    else:
        set_workspace_state(connection_factory, workspace_b.id, unavailable_state)

    with pytest.raises(WorkspaceNotFound, match="workspace is unavailable"):
        composition.select_workspace(candidate_id)

    assert composition.active_scope.require_workspace_id() == workspace_a.id


def test_composite_foreign_key_rejects_cross_workspace_ownership(
    tmp_path: Path,
) -> None:
    composition, connection_factory = make_composition(tmp_path)
    workspace_a = composition.create_workspace("Synthetic Workspace A")
    workspace_b = composition.create_workspace("Synthetic Workspace B")
    document_id = "11111111-1111-4111-8111-111111111111"
    version_id = "22222222-2222-4222-8222-222222222222"
    timestamp = "2026-08-28T12:00:00.000Z"

    connection = connection_factory.create()
    try:
        connection.execute(
            """
            INSERT INTO documents (
                id, workspace_id, display_name_ciphertext, state,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'ACTIVE', ?, ?)
            """,
            (
                document_id,
                str(workspace_a.id),
                b"synthetic-document",
                timestamp,
                timestamp,
            ),
        )

        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            connection.execute(
                """
                INSERT INTO document_versions (
                    id, workspace_id, document_id, version_number,
                    historical_filename_ciphertext, state, created_at
                ) VALUES (?, ?, ?, 1, ?, 'CANDIDATE_PROCESSING', ?)
                """,
                (
                    version_id,
                    str(workspace_b.id),
                    document_id,
                    b"synthetic-filename",
                    timestamp,
                ),
            )
    finally:
        connection.close()
