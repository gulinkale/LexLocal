"""Unit tests for workspace Bootstrap composition."""

from pathlib import Path

import pytest

from lexlocal.application.workspaces import (
    ActiveWorkspaceRequired,
    ActiveWorkspaceScope,
    CreateWorkspace,
    ListWorkspaces,
    SelectWorkspace,
)
from lexlocal.bootstrap.persistence import compose_workspace_application
from lexlocal.bootstrap.security import SecurityProviderConfigurationError
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.infrastructure.persistence.sqlite_connection import (
    SQLiteConnectionFactory,
)


def make_settings(
    tmp_path: Path,
    *,
    environment: str = "test",
    security_provider: str = "insecure-development-only",
) -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment=environment,
        log_level="INFO",
        data_dir=tmp_path,
        security_provider=security_provider,
    )


def test_compose_workspace_application_exposes_minimal_graph(tmp_path: Path) -> None:
    composition = compose_workspace_application(
        make_settings(tmp_path),
        SQLiteConnectionFactory(tmp_path / "lexlocal.db"),
    )

    assert isinstance(composition.create_workspace, CreateWorkspace)
    assert isinstance(composition.list_workspaces, ListWorkspaces)
    assert isinstance(composition.select_workspace, SelectWorkspace)
    assert isinstance(composition.active_scope, ActiveWorkspaceScope)
    with pytest.raises(ActiveWorkspaceRequired):
        composition.active_scope.require_workspace_id()


def test_production_composition_fails_before_workspace_graph_is_available(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        SecurityProviderConfigurationError,
        match="no release-safe security provider is available",
    ):
        compose_workspace_application(
            make_settings(
                tmp_path,
                environment="production",
                security_provider="insecure-development-only",
            ),
            SQLiteConnectionFactory(tmp_path / "lexlocal.db"),
        )
