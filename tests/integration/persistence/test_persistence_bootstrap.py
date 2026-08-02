"""Integration tests for persistence bootstrap composition."""

from pathlib import Path

from lexlocal.bootstrap.persistence import initialize_persistence
from lexlocal.bootstrap.settings import AppSettings


def test_initialize_persistence_uses_database_path_from_settings(
    tmp_path: Path,
) -> None:
    settings = AppSettings(
        app_name="LexLocal",
        environment="test",
        log_level="INFO",
        data_dir=tmp_path,
    )

    connection_factory = initialize_persistence(settings)

    assert connection_factory.database_path == settings.database_path
    assert settings.database_path.exists()

    connection = connection_factory.create()

    try:
        applied_versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    finally:
        connection.close()

    assert [int(row["version"]) for row in applied_versions] == [1]
