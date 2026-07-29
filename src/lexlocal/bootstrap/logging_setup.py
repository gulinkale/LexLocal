import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from typing import TextIO

from lexlocal.bootstrap.settings import AppSettings

_LOGGER_NAME = "lexlocal"
_LOG_FILE_NAME = "lexlocal.log"

_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

_MAX_LOG_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5

_SENSITIVE_VALUE_PATTERN = re.compile(
    r"""
    \b
    (?P<key>
        password
        |passphrase
        |token
        |api[_-]?key
        |secret
        |encryption[_-]?key
        |recovery[_-]?key
        |document[_-]?text
        |decrypted[_-]?content
        |prompt
    )
    \b
    (?P<separator>\s*[:=]\s*)
    (?P<value>
        "[^"]*"
        |'[^']*'
        |[^,\s;]+
    )
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)


class SensitiveDataFilter(logging.Filter):
    """Redact known sensitive key-value pairs from log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = _redact_sensitive_values(message)
        record.args = ()
        return True


def _redact_sensitive_values(message: str) -> str:
    """Replace known sensitive values with a fixed marker."""

    return _SENSITIVE_VALUE_PATTERN.sub(
        lambda match: (
            f"{match.group('key')}"
            f"{match.group('separator')}"
            "[REDACTED]"
        ),
        message,
    )


def configure_logging(
    settings: AppSettings,
    *,
    console_stream: TextIO | None = None,
) -> logging.Logger:
    """Configure and return the application-wide LexLocal logger."""

    settings.log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(settings.log_level)
    logger.propagate = False
    logger.disabled = False

    _remove_existing_handlers(logger)

    formatter = logging.Formatter(
        fmt=_LOG_FORMAT,
        datefmt=_DATE_FORMAT,
    )
    sensitive_data_filter = SensitiveDataFilter()

    console_handler = logging.StreamHandler(
        console_stream if console_stream is not None else sys.stderr
    )
    console_handler.setLevel(settings.log_level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(sensitive_data_filter)

    file_handler = RotatingFileHandler(
        filename=settings.log_dir / _LOG_FILE_NAME,
        maxBytes=_MAX_LOG_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
        delay=True,
    )
    file_handler.setLevel(settings.log_level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(sensitive_data_filter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


def _remove_existing_handlers(logger: logging.Logger) -> None:
    """Remove handlers previously installed on the LexLocal logger."""

    for handler in tuple(logger.handlers):
        logger.removeHandler(handler)
        handler.close()