import logging
from collections.abc import Iterator
from io import StringIO
from pathlib import Path

import pytest

from lexlocal.bootstrap.logging_setup import configure_logging
from lexlocal.bootstrap.settings import AppSettings


def _make_settings(
    data_dir: Path,
    *,
    log_level: str = "INFO",
) -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment="test",
        log_level=log_level,
        data_dir=data_dir,
    )


def _clear_lexlocal_handlers() -> None:
    logger = logging.getLogger("lexlocal")

    for handler in tuple(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def _flush_handlers(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        handler.flush()


@pytest.fixture(autouse=True)
def isolate_logging_state() -> Iterator[None]:
    _clear_lexlocal_handlers()
    yield
    _clear_lexlocal_handlers()


def test_configure_logging_creates_log_directory(
    tmp_path: Path,
) -> None:
    settings = _make_settings(tmp_path)

    configure_logging(settings, console_stream=StringIO())

    assert settings.log_dir.is_dir()


def test_logging_writes_to_console_and_file(
    tmp_path: Path,
) -> None:
    console = StringIO()
    settings = _make_settings(tmp_path)
    logger = configure_logging(settings, console_stream=console)

    logger.info("Application started")
    _flush_handlers(logger)

    log_file = settings.log_dir / "lexlocal.log"

    assert "Application started" in console.getvalue()
    assert log_file.is_file()
    assert "Application started" in log_file.read_text(encoding="utf-8")


def test_info_level_excludes_debug_messages(
    tmp_path: Path,
) -> None:
    console = StringIO()
    settings = _make_settings(tmp_path, log_level="INFO")
    logger = configure_logging(settings, console_stream=console)

    logger.debug("Hidden diagnostic message")
    logger.info("Visible application message")
    _flush_handlers(logger)

    output = console.getvalue()

    assert "Hidden diagnostic message" not in output
    assert "Visible application message" in output


def test_sensitive_values_are_redacted(
    tmp_path: Path,
) -> None:
    console = StringIO()
    settings = _make_settings(tmp_path)
    logger = configure_logging(settings, console_stream=console)

    logger.warning(
        "Authentication failed; password=secret123 token: abc456"
    )
    _flush_handlers(logger)

    log_file = settings.log_dir / "lexlocal.log"
    file_output = log_file.read_text(encoding="utf-8")
    console_output = console.getvalue()

    assert "secret123" not in console_output
    assert "abc456" not in console_output
    assert console_output.count("[REDACTED]") == 2

    assert "secret123" not in file_output
    assert "abc456" not in file_output
    assert file_output.count("[REDACTED]") == 2


def test_reconfiguration_does_not_duplicate_messages(
    tmp_path: Path,
) -> None:
    console = StringIO()
    settings = _make_settings(tmp_path)

    configure_logging(settings, console_stream=console)
    logger = configure_logging(settings, console_stream=console)

    logger.info("Application started")
    _flush_handlers(logger)

    assert console.getvalue().count("Application started") == 1