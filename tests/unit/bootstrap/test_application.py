"""Unit tests for the staged desktop application startup sequence."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lexlocal.bootstrap import application as application_bootstrap
from lexlocal.bootstrap.persistence import initialize_persistence
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.infrastructure.persistence.migration_runner import MigrationHistoryError


def make_settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment="test",
        log_level="INFO",
        data_dir=data_dir,
        security_provider="insecure-development-only",
    )


def _install_successful_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    events: list[str],
    *,
    event_loop_error: Exception | None = None,
    shutdown_result: bool = True,
) -> tuple[Mock, SimpleNamespace]:
    settings = make_settings(tmp_path)
    logger = Mock()
    connection_factory = Mock()
    security = Mock()
    qt_application = Mock()
    main_window = Mock()
    ui = SimpleNamespace(
        main_window=main_window,
        start=Mock(side_effect=lambda: events.append("start_ui")),
        shutdown=Mock(
            side_effect=lambda: events.append("shutdown_ui") or shutdown_result
        ),
    )
    if event_loop_error is None:
        qt_application.exec.side_effect = lambda: events.append("event_loop") or 0
    else:
        qt_application.exec.side_effect = event_loop_error
    main_window.show.side_effect = lambda: events.append("show_window")

    monkeypatch.setattr(
        application_bootstrap,
        "load_settings",
        lambda: events.append("settings") or settings,
    )
    monkeypatch.setattr(
        application_bootstrap,
        "configure_logging",
        lambda actual: events.append("logging") or logger,
    )
    monkeypatch.setattr(
        application_bootstrap,
        "initialize_persistence",
        lambda actual: events.append("persistence") or connection_factory,
    )
    monkeypatch.setattr(
        application_bootstrap,
        "create_security_providers",
        lambda actual: events.append("security") or security,
    )
    monkeypatch.setattr(
        application_bootstrap,
        "_qt_application",
        lambda argv: events.append("qt_shell") or qt_application,
    )

    def compose(actual_settings: object, actual_factory: object, actual_security: object):
        assert actual_settings is settings
        assert actual_factory is connection_factory
        assert actual_security is security
        events.append("compose_ui")
        return ui

    monkeypatch.setattr(application_bootstrap, "compose_ui_application", compose)
    return logger, ui


def test_run_preserves_required_startup_and_shutdown_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    logger, ui = _install_successful_startup(monkeypatch, tmp_path, events)

    assert application_bootstrap.run(["lexlocal-test"]) == 0
    assert events == [
        "settings",
        "logging",
        "persistence",
        "security",
        "qt_shell",
        "compose_ui",
        "show_window",
        "start_ui",
        "event_loop",
        "shutdown_ui",
    ]
    ui.shutdown.assert_called_once_with()
    logger.info.assert_any_call("Application starting")
    logger.info.assert_any_call("Application stopped; exit_code=%d", 0)


def test_event_loop_failure_preserves_primary_and_still_shuts_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    _logger, ui = _install_successful_startup(
        monkeypatch,
        tmp_path,
        events,
        event_loop_error=RuntimeError("event loop failed"),
    )

    with pytest.raises(RuntimeError, match="event loop failed"):
        application_bootstrap.run([])

    ui.shutdown.assert_called_once_with()


def test_worker_shutdown_failure_is_fatal_after_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    _install_successful_startup(
        monkeypatch,
        tmp_path,
        events,
        shutdown_result=False,
    )

    with pytest.raises(RuntimeError, match="worker did not stop safely"):
        application_bootstrap.run([])


@pytest.mark.parametrize("failing_stage", ["persistence", "security"])
def test_pre_shell_fatal_stage_never_creates_normal_ui(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_stage: str,
) -> None:
    settings = make_settings(tmp_path)
    create_shell = Mock()
    compose_ui = Mock()
    monkeypatch.setattr(application_bootstrap, "load_settings", lambda: settings)
    monkeypatch.setattr(application_bootstrap, "configure_logging", lambda _value: Mock())
    monkeypatch.setattr(application_bootstrap, "_qt_application", create_shell)
    monkeypatch.setattr(application_bootstrap, "compose_ui_application", compose_ui)

    if failing_stage == "persistence":
        monkeypatch.setattr(
            application_bootstrap,
            "initialize_persistence",
            Mock(side_effect=RuntimeError("persistence failed")),
        )
    else:
        monkeypatch.setattr(
            application_bootstrap,
            "initialize_persistence",
            lambda _value: Mock(),
        )
        monkeypatch.setattr(
            application_bootstrap,
            "create_security_providers",
            Mock(side_effect=RuntimeError("security failed")),
        )

    with pytest.raises(RuntimeError, match=f"{failing_stage} failed"):
        application_bootstrap.run([])

    create_shell.assert_not_called()
    compose_ui.assert_not_called()


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

    create_shell = Mock()
    monkeypatch.setattr(application_bootstrap, "load_settings", lambda: settings)
    monkeypatch.setattr(application_bootstrap, "configure_logging", lambda _value: Mock())
    monkeypatch.setattr(application_bootstrap, "_qt_application", create_shell)

    with pytest.raises(MigrationHistoryError, match="checksum mismatch"):
        application_bootstrap.run(["lexlocal-test"])

    create_shell.assert_not_called()
