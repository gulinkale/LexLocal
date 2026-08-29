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
        security_provider="insecure-development-only",
    )


def test_run_initializes_persistence_before_showing_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path)
    events: list[str] = []
    logger = Mock()
    connection_factory = Mock()
    workspace_application = Mock()
    local_models = Mock()
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

    def compose(actual_settings: AppSettings, actual_factory: Mock) -> Mock:
        assert actual_settings is settings
        assert actual_factory is connection_factory
        events.append("compose_workspace_application")
        return workspace_application

    def compose_models(actual_settings: AppSettings, actual_factory: Mock) -> Mock:
        assert actual_settings is settings
        assert actual_factory is connection_factory
        events.append("compose_local_models")
        local_models.close.side_effect = lambda: events.append("close_local_models")
        return local_models

    def show() -> None:
        events.append("show_window")

    def execute() -> int:
        events.append("execute_event_loop")
        return 0

    monkeypatch.setattr(application_bootstrap, "initialize_persistence", initialize)
    monkeypatch.setattr(
        application_bootstrap,
        "compose_workspace_application",
        compose,
    )
    monkeypatch.setattr(application_bootstrap, "create_application", create)
    monkeypatch.setattr(application_bootstrap, "compose_local_models", compose_models)
    main_window.show.side_effect = show
    qt_application.exec.side_effect = execute

    exit_code = application_bootstrap.run(["lexlocal-test"])

    assert exit_code == 0
    assert events == [
        "load_settings",
        "configure_logging",
        "initialize_persistence",
        "compose_workspace_application",
        "compose_local_models",
        "create_application",
        "show_window",
        "execute_event_loop",
        "close_local_models",
    ]
    logger.info.assert_any_call("Application starting")
    logger.info.assert_any_call("Application stopped; exit_code=%d", 0)


def test_local_model_composition_failure_prevents_ui_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path)
    create_application = Mock()
    composition_error = RuntimeError("local model composition failed")

    monkeypatch.setattr(application_bootstrap, "load_settings", lambda: settings)
    monkeypatch.setattr(
        application_bootstrap,
        "configure_logging",
        lambda _settings: Mock(),
    )
    monkeypatch.setattr(
        application_bootstrap,
        "initialize_persistence",
        lambda _settings: Mock(),
    )
    monkeypatch.setattr(
        application_bootstrap,
        "compose_workspace_application",
        lambda _settings, _factory: Mock(),
    )
    monkeypatch.setattr(
        application_bootstrap,
        "compose_local_models",
        Mock(side_effect=composition_error),
    )
    monkeypatch.setattr(application_bootstrap, "create_application", create_application)

    with pytest.raises(RuntimeError, match="local model composition failed"):
        application_bootstrap.run([])

    create_application.assert_not_called()


def test_event_loop_failure_still_closes_local_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path)
    local_models = Mock()
    qt_application = Mock()
    qt_application.exec.side_effect = RuntimeError("event loop failed")

    monkeypatch.setattr(application_bootstrap, "load_settings", lambda: settings)
    monkeypatch.setattr(
        application_bootstrap,
        "configure_logging",
        lambda _settings: Mock(),
    )
    monkeypatch.setattr(
        application_bootstrap,
        "initialize_persistence",
        lambda _settings: Mock(),
    )
    monkeypatch.setattr(
        application_bootstrap,
        "compose_workspace_application",
        lambda _settings, _factory: Mock(),
    )
    monkeypatch.setattr(
        application_bootstrap,
        "compose_local_models",
        lambda _settings, _factory: local_models,
    )
    monkeypatch.setattr(
        application_bootstrap,
        "create_application",
        lambda _argv: (qt_application, Mock()),
    )

    with pytest.raises(RuntimeError, match="event loop failed"):
        application_bootstrap.run([])

    local_models.close.assert_called_once_with()


def test_cleanup_failure_does_not_replace_event_loop_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path)
    local_models = Mock()
    local_models.close.side_effect = RuntimeError("cleanup failed")
    qt_application = Mock()
    qt_application.exec.side_effect = RuntimeError("event loop failed")

    monkeypatch.setattr(application_bootstrap, "load_settings", lambda: settings)
    monkeypatch.setattr(
        application_bootstrap,
        "configure_logging",
        lambda _settings: Mock(),
    )
    monkeypatch.setattr(
        application_bootstrap,
        "initialize_persistence",
        lambda _settings: Mock(),
    )
    monkeypatch.setattr(
        application_bootstrap,
        "compose_workspace_application",
        lambda _settings, _factory: Mock(),
    )
    monkeypatch.setattr(
        application_bootstrap,
        "compose_local_models",
        lambda _settings, _factory: local_models,
    )
    monkeypatch.setattr(
        application_bootstrap,
        "create_application",
        lambda _argv: (qt_application, Mock()),
    )

    with pytest.raises(RuntimeError, match="event loop failed"):
        application_bootstrap.run([])

    local_models.close.assert_called_once_with()


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
