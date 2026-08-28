"""Integration tests for SQLite workspace persistence."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.application.ports.workspaces import (
    WorkspaceConflict,
    WorkspacePersistenceError,
)
from lexlocal.domain.identifiers import DocumentId, WorkspaceId
from lexlocal.domain.workspace import Workspace, WorkspaceProfile, WorkspaceState
from lexlocal.infrastructure.persistence.migration_runner import run_migrations
from lexlocal.infrastructure.persistence.migrations import (
    default_migrations_dir,
    discover_migrations,
)
from lexlocal.infrastructure.persistence.sqlite_connection import (
    SQLiteConnectionFactory,
)
from lexlocal.infrastructure.persistence.sqlite_workspace_repository import (
    SQLiteWorkspaceRepository,
)
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
)

WORKSPACE_ID = WorkspaceId("550e8400-e29b-41d4-a716-446655440000")
OTHER_WORKSPACE_ID = WorkspaceId("123e4567-e89b-12d3-a456-426614174000")
CREATED_AT = datetime(2026, 8, 28, 9, 30, 12, 123000, tzinfo=UTC)
UPDATED_AT = datetime(2026, 8, 28, 10, 45, 33, 987000, tzinfo=UTC)


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    connection = factory.create()
    run_migrations(
        connection,
        discover_migrations(default_migrations_dir()),
    )
    connection.execute("BEGIN")

    try:
        yield connection
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


@pytest.fixture
def repository(
    connection: sqlite3.Connection,
) -> SQLiteWorkspaceRepository:
    return SQLiteWorkspaceRepository(
        connection,
        InsecureDevelopmentOnlyWorkspaceNamePersistence(),
    )


def make_workspace(
    *,
    workspace_id: WorkspaceId = WORKSPACE_ID,
    display_name: str = "Synthetic Çalışma Alanı",
    profile: WorkspaceProfile | None = None,
    state: WorkspaceState = WorkspaceState.ACTIVE,
) -> Workspace:
    return Workspace(
        id=workspace_id,
        display_name=display_name,
        created_at=CREATED_AT,
        updated_at=UPDATED_AT,
        profile=profile,
        state=state,
    )


@pytest.mark.parametrize("profile", [None, WorkspaceProfile.CONTRACT_REVIEW])
def test_add_get_round_trip_all_workspace_fields(
    repository: SQLiteWorkspaceRepository,
    profile: WorkspaceProfile | None,
) -> None:
    workspace = make_workspace(
        display_name="  Synthetic Çalışma Alanı K  ",
        profile=profile,
    )

    repository.add(workspace)

    assert repository.get(workspace.id) == workspace


@pytest.mark.parametrize("profile", [None, WorkspaceProfile.GENERAL_LEGAL])
def test_add_maps_exact_schema_values_and_leaves_later_columns_null(
    connection: sqlite3.Connection,
    repository: SQLiteWorkspaceRepository,
    profile: WorkspaceProfile | None,
) -> None:
    workspace = make_workspace(profile=profile)

    repository.add(workspace)
    row = connection.execute(
        "SELECT * FROM workspaces WHERE id = ?",
        (str(workspace.id),),
    ).fetchone()

    assert row is not None
    assert row["id"] == str(WORKSPACE_ID)
    assert row["name_ciphertext"] == workspace.display_name.encode("utf-8")
    assert isinstance(row["name_lookup_fingerprint"], bytes)
    assert len(row["name_lookup_fingerprint"]) == 32
    assert row["state"] == "ACTIVE"
    assert row["profile"] == (profile.value if profile is not None else None)
    assert row["profile_source"] == ("USER" if profile is not None else None)
    assert row["profile_confirmed_at"] == (
        "2026-08-28T09:30:12.123Z" if profile is not None else None
    )
    assert row["created_at"] == "2026-08-28T09:30:12.123Z"
    assert row["updated_at"] == "2026-08-28T10:45:33.987Z"
    assert row["suggested_profile"] is None
    assert row["suggested_profile_model_id"] is None
    assert row["profile_suggested_at"] is None
    assert row["archived_at"] is None
    assert row["deletion_started_at"] is None


def test_stable_workspace_id_round_trips_without_regeneration(
    repository: SQLiteWorkspaceRepository,
) -> None:
    workspace = make_workspace()

    repository.add(workspace)
    loaded = repository.get(WORKSPACE_ID)

    assert loaded is not None
    assert loaded.id == WORKSPACE_ID
    assert str(loaded.id) == "550e8400-e29b-41d4-a716-446655440000"


def test_get_missing_workspace_returns_none(
    repository: SQLiteWorkspaceRepository,
) -> None:
    assert repository.get(WORKSPACE_ID) is None


@pytest.mark.parametrize(
    "state",
    [
        WorkspaceState.ARCHIVED,
        WorkspaceState.DELETING,
        WorkspaceState.DELETION_RECOVERY,
    ],
)
def test_get_excludes_every_non_active_state(
    repository: SQLiteWorkspaceRepository,
    state: WorkspaceState,
) -> None:
    repository.add(make_workspace(state=state))

    assert repository.get(WORKSPACE_ID) is None


def test_list_normal_returns_only_active_without_order_assumption(
    repository: SQLiteWorkspaceRepository,
) -> None:
    active_first = make_workspace()
    active_second = make_workspace(
        workspace_id=OTHER_WORKSPACE_ID,
        display_name="Other Synthetic Workspace",
    )
    archived = make_workspace(
        workspace_id=WorkspaceId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        display_name="Archived Synthetic Workspace",
        state=WorkspaceState.ARCHIVED,
    )
    repository.add(active_second)
    repository.add(archived)
    repository.add(active_first)

    loaded = repository.list_normal()

    assert {workspace.id for workspace in loaded} == {
        active_first.id,
        active_second.id,
    }


def test_duplicate_id_raises_sanitized_workspace_conflict(
    repository: SQLiteWorkspaceRepository,
) -> None:
    first = make_workspace(display_name="First Synthetic Workspace")
    duplicate = make_workspace(display_name="Private Synthetic Fixture")
    repository.add(first)

    with pytest.raises(WorkspaceConflict) as exc_info:
        repository.add(duplicate)

    assert str(exc_info.value) == "workspace already exists"
    assert "Private Synthetic Fixture" not in str(exc_info.value)
    assert "INSERT" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("column", "corrupt_value"),
    [
        ("created_at", "not-a-timestamp"),
        ("updated_at", "2026-08-28T10:45:33Z"),
    ],
)
def test_corrupt_stored_mapping_raises_sanitized_persistence_error(
    connection: sqlite3.Connection,
    repository: SQLiteWorkspaceRepository,
    column: str,
    corrupt_value: str,
) -> None:
    repository.add(make_workspace(display_name="Private Synthetic Fixture"))
    connection.execute(
        f"UPDATE workspaces SET {column} = ? WHERE id = ?",
        (corrupt_value, str(WORKSPACE_ID)),
    )

    with pytest.raises(WorkspacePersistenceError) as exc_info:
        repository.get(WORKSPACE_ID)

    assert str(exc_info.value) == "workspace data is invalid"
    assert corrupt_value not in str(exc_info.value)
    assert "Private Synthetic Fixture" not in str(exc_info.value)


@pytest.mark.parametrize(
    "invalid_id",
    [str(WORKSPACE_ID), DocumentId(str(WORKSPACE_ID))],
)
def test_get_rejects_non_workspace_identifier_before_sql(
    repository: SQLiteWorkspaceRepository,
    invalid_id: object,
) -> None:
    with pytest.raises(WorkspacePersistenceError, match="workspace id is invalid"):
        repository.get(invalid_id)  # type: ignore[arg-type]


def test_repository_does_not_finalize_caller_transaction(
    connection: sqlite3.Connection,
    repository: SQLiteWorkspaceRepository,
) -> None:
    repository.add(make_workspace())

    assert connection.in_transaction is True
    connection.rollback()
    connection.execute("BEGIN")
    assert repository.get(WORKSPACE_ID) is None
