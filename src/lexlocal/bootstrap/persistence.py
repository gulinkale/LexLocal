"""Initialize SQLite persistence during application startup."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from lexlocal.application.ports.unit_of_work import UnitOfWork
from lexlocal.application.workspaces import (
    ActiveWorkspaceScope,
    CreateWorkspace,
    ListWorkspaces,
    SelectWorkspace,
)
from lexlocal.bootstrap.security import create_security_providers
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import WorkspaceId
from lexlocal.infrastructure.persistence.migration_runner import (
    run_migrations,
)
from lexlocal.infrastructure.persistence.migrations import (
    default_migrations_dir,
    discover_migrations,
)
from lexlocal.infrastructure.persistence.sqlite_connection import (
    SQLiteConnectionFactory,
)
from lexlocal.infrastructure.persistence.sqlite_unit_of_work import (
    SQLiteUnitOfWork,
)
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
)


@dataclass(frozen=True, slots=True)
class WorkspaceApplicationComposition:
    """Expose the composed workspace use cases and their shared active scope."""

    create_workspace: CreateWorkspace
    list_workspaces: ListWorkspaces
    select_workspace: SelectWorkspace
    active_scope: ActiveWorkspaceScope


def initialize_persistence(
    settings: AppSettings,
) -> SQLiteConnectionFactory:
    """Prepare the application database and return its connection factory."""

    connection_factory = SQLiteConnectionFactory(settings.database_path)

    migrations = discover_migrations(default_migrations_dir())

    if not migrations:
        raise RuntimeError("No database migrations were found")

    connection = connection_factory.create()

    try:
        run_migrations(connection, migrations)
    finally:
        connection.close()

    return connection_factory


def compose_workspace_application(
    settings: AppSettings,
    connection_factory: SQLiteConnectionFactory,
) -> WorkspaceApplicationComposition:
    """Compose the synthetic workspace vertical slice after security validation."""
    create_security_providers(settings)
    name_persistence = InsecureDevelopmentOnlyWorkspaceNamePersistence()
    active_scope = ActiveWorkspaceScope()

    def unit_of_work_factory() -> UnitOfWork:
        return SQLiteUnitOfWork(connection_factory, name_persistence)

    def workspace_id_factory() -> WorkspaceId:
        return WorkspaceId(str(uuid4()))

    def clock() -> datetime:
        now = datetime.now(UTC)
        return now.replace(microsecond=(now.microsecond // 1_000) * 1_000)

    return WorkspaceApplicationComposition(
        create_workspace=CreateWorkspace(
            unit_of_work_factory,
            workspace_id_factory,
            clock,
        ),
        list_workspaces=ListWorkspaces(unit_of_work_factory),
        select_workspace=SelectWorkspace(unit_of_work_factory, active_scope),
        active_scope=active_scope,
    )
