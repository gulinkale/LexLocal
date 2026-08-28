"""Integration tests for workspace repository transaction ownership."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.bootstrap.persistence import initialize_persistence
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import WorkspaceId
from lexlocal.domain.workspace import Workspace
from lexlocal.infrastructure.persistence.sqlite_connection import (
    SQLiteConnectionFactory,
)
from lexlocal.infrastructure.persistence.sqlite_unit_of_work import SQLiteUnitOfWork
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
)

WORKSPACE_ID = WorkspaceId("550e8400-e29b-41d4-a716-446655440000")
NOW = datetime(2026, 8, 28, 9, 30, tzinfo=UTC)


def make_factory(tmp_path: Path) -> SQLiteConnectionFactory:
    return initialize_persistence(
        AppSettings(
            app_name="LexLocal",
            environment="test",
            log_level="INFO",
            data_dir=tmp_path,
            security_provider="insecure-development-only",
        )
    )


def make_unit_of_work(factory: SQLiteConnectionFactory) -> SQLiteUnitOfWork:
    return SQLiteUnitOfWork(
        factory,
        InsecureDevelopmentOnlyWorkspaceNamePersistence(),
    )


def make_workspace() -> Workspace:
    return Workspace(
        id=WORKSPACE_ID,
        display_name="Synthetic Workspace",
        created_at=NOW,
        updated_at=NOW,
    )


def workspace_count(factory: SQLiteConnectionFactory) -> int:
    connection = factory.create()
    try:
        row = connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()
    finally:
        connection.close()
    assert row is not None
    return int(row[0])


def test_commit_persists_workspace_without_later_placeholder_rows(
    tmp_path: Path,
) -> None:
    factory = make_factory(tmp_path)
    unit_of_work = make_unit_of_work(factory)

    with unit_of_work:
        unit_of_work.workspaces.add(make_workspace())
        unit_of_work.commit()

    connection = factory.create()
    try:
        counts = {
            table: int(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
            for table in (
                "workspaces",
                "workspace_key_records",
                "analyses",
                "activity_events",
            )
        }
    finally:
        connection.close()

    assert counts == {
        "workspaces": 1,
        "workspace_key_records": 0,
        "analyses": 0,
        "activity_events": 0,
    }


def test_exception_rolls_back_workspace_insert(tmp_path: Path) -> None:
    factory = make_factory(tmp_path)
    unit_of_work = make_unit_of_work(factory)

    with pytest.raises(RuntimeError, match="synthetic failure"):
        with unit_of_work:
            unit_of_work.workspaces.add(make_workspace())
            raise RuntimeError("synthetic failure")

    assert workspace_count(factory) == 0


def test_omitted_commit_rolls_back_workspace_insert(tmp_path: Path) -> None:
    factory = make_factory(tmp_path)
    unit_of_work = make_unit_of_work(factory)

    with unit_of_work:
        unit_of_work.workspaces.add(make_workspace())

    assert workspace_count(factory) == 0


def test_repository_is_unavailable_after_commit_and_scope_exit(tmp_path: Path) -> None:
    unit_of_work = make_unit_of_work(make_factory(tmp_path))

    with unit_of_work:
        unit_of_work.workspaces.add(make_workspace())
        unit_of_work.commit()

        with pytest.raises(RuntimeError, match="transaction is not active"):
            _ = unit_of_work.workspaces

    with pytest.raises(RuntimeError, match="transaction is not active"):
        _ = unit_of_work.workspaces


def test_reused_unit_of_work_creates_fresh_transaction_bound_repository(
    tmp_path: Path,
) -> None:
    unit_of_work = make_unit_of_work(make_factory(tmp_path))

    with unit_of_work:
        first_repository = unit_of_work.workspaces
        unit_of_work.rollback()

    with unit_of_work:
        second_repository = unit_of_work.workspaces
        unit_of_work.rollback()

    assert first_repository is not second_repository
