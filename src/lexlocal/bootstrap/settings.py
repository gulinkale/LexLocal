import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_ALLOWED_ENVIRONMENTS = frozenset({"development", "test", "production"})
_ALLOWED_LOG_LEVELS = frozenset(
    {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
)


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Runtime configuration required to bootstrap LexLocal."""

    app_name: str
    environment: str
    log_level: str
    data_dir: Path

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"


def default_data_dir() -> Path:
    """Return the default local application-data directory."""

    return Path.home() / ".lexlocal"


def load_settings(
    environ: Mapping[str, str] | None = None,
) -> AppSettings:
    """Load and validate LexLocal settings from environment variables."""

    values = os.environ if environ is None else environ

    environment = values.get("LEXLOCAL_ENV", "development").strip().lower()
    if environment not in _ALLOWED_ENVIRONMENTS:
        allowed = ", ".join(sorted(_ALLOWED_ENVIRONMENTS))
        raise ValueError(
            f"LEXLOCAL_ENV must be one of: {allowed}"
        )

    log_level = values.get("LEXLOCAL_LOG_LEVEL", "INFO").strip().upper()
    if log_level not in _ALLOWED_LOG_LEVELS:
        allowed = ", ".join(sorted(_ALLOWED_LOG_LEVELS))
        raise ValueError(
            f"LEXLOCAL_LOG_LEVEL must be one of: {allowed}"
        )

    configured_data_dir = values.get("LEXLOCAL_DATA_DIR")
    data_dir = (
        Path(configured_data_dir).expanduser()
        if configured_data_dir
        else default_data_dir()
    )

    return AppSettings(
        app_name="LexLocal",
        environment=environment,
        log_level=log_level,
        data_dir=data_dir,
    )