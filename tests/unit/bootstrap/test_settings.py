from pathlib import Path

import pytest

from lexlocal.bootstrap.settings import load_settings


def test_load_settings_uses_defaults() -> None:
    settings = load_settings({})

    assert settings.app_name == "LexLocal"
    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.data_dir == Path.home() / ".lexlocal"
    assert settings.log_dir == settings.data_dir / "logs"
    assert settings.security_provider == "insecure-development-only"


def test_load_settings_accepts_explicit_values(tmp_path: Path) -> None:
    settings = load_settings(
        {
            "LEXLOCAL_ENV": "test",
            "LEXLOCAL_LOG_LEVEL": "debug",
            "LEXLOCAL_DATA_DIR": str(tmp_path),
            "LEXLOCAL_SECURITY_PROVIDER": "explicit-provider",
        }
    )

    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
    assert settings.data_dir == tmp_path
    assert settings.security_provider == "explicit-provider"


@pytest.mark.parametrize("environment", ["development", "test"])
def test_load_settings_defaults_non_release_security_provider(
    environment: str,
) -> None:
    settings = load_settings({"LEXLOCAL_ENV": environment})

    assert settings.security_provider == "insecure-development-only"


@pytest.mark.parametrize("configured_provider", [None, "", "   "])
def test_load_settings_does_not_default_production_to_insecure_provider(
    configured_provider: str | None,
) -> None:
    environ = {"LEXLOCAL_ENV": "production"}
    if configured_provider is not None:
        environ["LEXLOCAL_SECURITY_PROVIDER"] = configured_provider

    settings = load_settings(environ)

    assert settings.security_provider == ""
    assert settings.security_provider != "insecure-development-only"


def test_load_settings_preserves_unknown_provider_for_later_selection() -> None:
    settings = load_settings(
        {"LEXLOCAL_SECURITY_PROVIDER": "unknown-provider"}
    )

    assert settings.security_provider == "unknown-provider"


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("LEXLOCAL_ENV", "invalid"),
        ("LEXLOCAL_LOG_LEVEL", "verbose"),
    ],
)
def test_load_settings_rejects_invalid_values(
    variable: str,
    value: str,
) -> None:
    with pytest.raises(ValueError):
        load_settings({variable: value})
