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


def test_load_settings_accepts_explicit_values(tmp_path: Path) -> None:
    settings = load_settings(
        {
            "LEXLOCAL_ENV": "test",
            "LEXLOCAL_LOG_LEVEL": "debug",
            "LEXLOCAL_DATA_DIR": str(tmp_path),
        }
    )

    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
    assert settings.data_dir == tmp_path


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