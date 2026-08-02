import logging
import sys
from collections.abc import Iterator
from io import StringIO
from pathlib import Path

import pytest

from lexlocal.bootstrap.logging_setup import SensitiveDataFormatter, configure_logging
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


def _read_log_outputs(
    console: StringIO,
    settings: AppSettings,
) -> tuple[str, str]:
    log_file = settings.log_dir / "lexlocal.log"
    return console.getvalue(), log_file.read_text(encoding="utf-8")


def _assert_in_console_and_file(
    console_output: str,
    file_output: str,
    expected: str,
) -> None:
    assert expected in console_output
    assert expected in file_output


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


def test_logger_exception_redacts_sensitive_exception_message(
    tmp_path: Path,
) -> None:
    console = StringIO()
    settings = _make_settings(tmp_path)
    logger = configure_logging(settings, console_stream=console)

    try:
        raise RuntimeError("password=traceback-secret")
    except RuntimeError:
        logger.exception("Operation failed while opening the workspace")

    _flush_handlers(logger)
    console_output, file_output = _read_log_outputs(console, settings)

    assert "traceback-secret" not in console_output
    assert "traceback-secret" not in file_output
    _assert_in_console_and_file(console_output, file_output, "password=[REDACTED]")
    _assert_in_console_and_file(console_output, file_output, "RuntimeError")
    _assert_in_console_and_file(
        console_output,
        file_output,
        "Operation failed while opening the workspace",
    )
    _assert_in_console_and_file(console_output, file_output, "Traceback (most recent call last)")


def test_error_with_exc_info_redacts_sensitive_exception_message(
    tmp_path: Path,
) -> None:
    console = StringIO()
    settings = _make_settings(tmp_path)
    logger = configure_logging(settings, console_stream=console)

    try:
        raise ValueError("token=exception-token")
    except ValueError:
        logger.error("Model request failed", exc_info=True)

    _flush_handlers(logger)
    console_output, file_output = _read_log_outputs(console, settings)

    assert "exception-token" not in console_output
    assert "exception-token" not in file_output
    _assert_in_console_and_file(console_output, file_output, "token=[REDACTED]")
    _assert_in_console_and_file(console_output, file_output, "ValueError")
    _assert_in_console_and_file(console_output, file_output, "Model request failed")
    _assert_in_console_and_file(console_output, file_output, "Traceback (most recent call last)")


def test_chained_exception_redacts_every_sensitive_exception_message(
    tmp_path: Path,
) -> None:
    console = StringIO()
    settings = _make_settings(tmp_path)
    logger = configure_logging(settings, console_stream=console)

    try:
        try:
            raise ValueError("token=inner-secret")
        except ValueError as exc:
            raise RuntimeError("password=outer-secret") from exc
    except RuntimeError:
        logger.exception("Workspace initialization failed")

    _flush_handlers(logger)
    console_output, file_output = _read_log_outputs(console, settings)

    for secret in ("inner-secret", "outer-secret"):
        assert secret not in console_output
        assert secret not in file_output

    for expected in (
        "token=[REDACTED]",
        "password=[REDACTED]",
        "ValueError",
        "RuntimeError",
        "The above exception was the direct cause",
        "Workspace initialization failed",
    ):
        _assert_in_console_and_file(console_output, file_output, expected)


def test_non_sensitive_exception_keeps_useful_traceback_information(
    tmp_path: Path,
) -> None:
    console = StringIO()
    settings = _make_settings(tmp_path)
    logger = configure_logging(settings, console_stream=console)

    try:
        raise RuntimeError("Local model cache is unavailable")
    except RuntimeError:
        logger.exception("Model startup failed")

    _flush_handlers(logger)
    console_output, file_output = _read_log_outputs(console, settings)

    for expected in (
        "Model startup failed",
        "Traceback (most recent call last)",
        "RuntimeError: Local model cache is unavailable",
        "test_non_sensitive_exception_keeps_useful_traceback_information",
    ):
        _assert_in_console_and_file(console_output, file_output, expected)


def test_formatter_does_not_mutate_arguments_or_exception_information() -> None:
    try:
        raise RuntimeError("token=shared-record-secret")
    except RuntimeError:
        exception_information = sys.exc_info()

    arguments = ("workspace-1",)
    record = logging.LogRecord(
        name="lexlocal",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Operation failed for %s",
        args=arguments,
        exc_info=exception_information,
    )
    formatter = SensitiveDataFormatter("%(levelname)s | %(message)s")

    first_output = formatter.format(record)
    second_output = formatter.format(record)

    assert "shared-record-secret" not in first_output
    assert first_output == second_output
    assert record.msg == "Operation failed for %s"
    assert record.args == arguments
    assert record.exc_info is exception_information
    assert record.exc_text is None
