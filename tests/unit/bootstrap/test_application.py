"""Unit tests for the real application startup sequence."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from lexlocal.bootstrap import application as application_bootstrap
from lexlocal.bootstrap.persistence import initialize_persistence
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.infrastructure.persistence.migration_runner import MigrationHistoryError


def make_settings(data_dir: Path) -> AppSettings:
    """Create application settings for startup tests."""

    return AppSettings(
        app_name="LexLocal",
        environment="test",
        log_level="INFO",
        data_dir=data_dir,
    )


def test_run_initializes_persistence_before_showing_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path)
    events: list[str] = []
    logger = Mock()
    connection_factory = Mock()
    qt_application = Mock()
    qt_application.exec.return_value = 0
    main_window = Mock()

    def load() -> AppSettings:
        events.append("load_settings")
        return settings

    def configure(actual_settings: AppSettings) -> Mock:
        assert actual_settings is settings
        events.append("configure_logging")
        return logger

    monkeypatch.setattr(application_bootstrap, "load_settings", load)
    monkeypatch.setattr(application_bootstrap, "configure_logging", configure)

    def initialize(actual_settings: AppSettings) -> Mock:
        assert actual_settings is settings
        events.append("initialize_persistence")
        return connection_factory

    def create(argv: object) -> tuple[Mock, Mock]:
        assert argv == ["lexlocal-test"]
        events.append("create_application")
        return qt_application, main_window

    def show() -> None:
        events.append("show_window")

    def execute() -> int:
        events.append("execute_event_loop")
        return 0

    monkeypatch.setattr(application_bootstrap, "initialize_persistence", initialize)
    monkeypatch.setattr(application_bootstrap, "create_application", create)
    main_window.show.side_effect = show
    qt_application.exec.side_effect = execute

    exit_code = application_bootstrap.run(["lexlocal-test"])

    assert exit_code == 0
    assert events == [
        "load_settings",
        "configure_logging",
        "initialize_persistence",
        "create_application",
        "show_window",
        "execute_event_loop",
    ]
    logger.info.assert_any_call("Application starting")
    logger.info.assert_any_call("Application stopped; exit_code=%d", 0)


def test_persistence_failure_prevents_ui_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path)
    create_application = Mock()

    monkeypatch.setattr(application_bootstrap, "load_settings", lambda: settings)
    monkeypatch.setattr(application_bootstrap, "configure_logging", lambda actual_settings: Mock())
    monkeypatch.setattr(application_bootstrap, "create_application", create_application)

    def fail_initialization(actual_settings: AppSettings) -> None:
        assert actual_settings is settings
        raise RuntimeError("migration failed")

    monkeypatch.setattr(
        application_bootstrap,
        "initialize_persistence",
        fail_initialization,
    )

    with pytest.raises(RuntimeError, match="migration failed"):
        application_bootstrap.run(["lexlocal-test"])

    create_application.assert_not_called()


def test_real_migration_history_failure_prevents_ui_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path)
    factory = initialize_persistence(settings)
    connection = factory.create()

    try:
        connection.execute(
            "UPDATE schema_migrations SET checksum_sha256 = ? WHERE version = 1",
            ("0" * 64,),
        )
    finally:
        connection.close()

    create_application = Mock()
    monkeypatch.setattr(application_bootstrap, "load_settings", lambda: settings)
    monkeypatch.setattr(
        application_bootstrap,
        "configure_logging",
        lambda actual_settings: Mock(),
    )
    monkeypatch.setattr(application_bootstrap, "create_application", create_application)

    with pytest.raises(MigrationHistoryError, match="checksum mismatch"):
        application_bootstrap.run(["lexlocal-test"])

    create_application.assert_not_called()
