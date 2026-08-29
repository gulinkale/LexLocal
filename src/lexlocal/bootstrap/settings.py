import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_ALLOWED_ENVIRONMENTS = frozenset({"development", "test", "production"})
_ALLOWED_LOG_LEVELS = frozenset(
    {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
)
_INSECURE_DEVELOPMENT_PROVIDER = "insecure-development-only"
_DEFAULT_CHAT_MODEL_ALIAS = "qwen3-4b"
_DEFAULT_EMBEDDING_MODEL_ALIAS = "qwen3-embedding-0.6b"
_MODEL_ALIAS_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Runtime configuration required to bootstrap LexLocal."""

    app_name: str
    environment: str
    log_level: str
    data_dir: Path
    security_provider: str = ""
    chat_model_alias: str = _DEFAULT_CHAT_MODEL_ALIAS
    embedding_model_alias: str = _DEFAULT_EMBEDDING_MODEL_ALIAS

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def database_path(self) -> Path:
        """Return the path to the SQLite database file."""
        return self.data_dir / "database" / "lexlocal.db"




def default_data_dir() -> Path:
    """Return the default local application-data directory."""

    return Path.home() / ".lexlocal"


def _load_model_alias(
    values: Mapping[str, str],
    variable: str,
    default: str,
) -> str:
    alias = values.get(variable, default).strip()
    if _MODEL_ALIAS_PATTERN.fullmatch(alias) is None:
        raise ValueError(
            f"{variable} must be a non-empty local model alias"
        )
    return alias


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

    configured_security_provider = values.get("LEXLOCAL_SECURITY_PROVIDER", "").strip()
    security_provider = (
        configured_security_provider
        if configured_security_provider
        else (
            _INSECURE_DEVELOPMENT_PROVIDER
            if environment in {"development", "test"}
            else ""
        )
    )
    chat_model_alias = _load_model_alias(
        values,
        "LEXLOCAL_CHAT_MODEL_ALIAS",
        _DEFAULT_CHAT_MODEL_ALIAS,
    )
    embedding_model_alias = _load_model_alias(
        values,
        "LEXLOCAL_EMBEDDING_MODEL_ALIAS",
        _DEFAULT_EMBEDDING_MODEL_ALIAS,
    )

    return AppSettings(
        app_name="LexLocal",
        environment=environment,
        log_level=log_level,
        data_dir=data_dir,
        security_provider=security_provider,
        chat_model_alias=chat_model_alias,
        embedding_model_alias=embedding_model_alias,
    )
