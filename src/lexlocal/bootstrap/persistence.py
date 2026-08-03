"""Initialize SQLite persistence during application startup."""

from lexlocal.bootstrap.settings import AppSettings
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
