from dataclasses import fields
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
    assert settings.chat_model_alias == "qwen3-4b"
    assert settings.embedding_model_alias == "qwen3-embedding-0.6b"
    assert settings.index_chunk_size == 1000
    assert settings.index_chunk_overlap == 200


def test_load_settings_accepts_explicit_values(tmp_path: Path) -> None:
    settings = load_settings(
        {
            "LEXLOCAL_ENV": "test",
            "LEXLOCAL_LOG_LEVEL": "debug",
            "LEXLOCAL_DATA_DIR": str(tmp_path),
            "LEXLOCAL_SECURITY_PROVIDER": "explicit-provider",
            "LEXLOCAL_CHAT_MODEL_ALIAS": "  explicit-chat  ",
            "LEXLOCAL_EMBEDDING_MODEL_ALIAS": "explicit-embedding:2",
            "LEXLOCAL_INDEX_CHUNK_SIZE": " 256 ",
            "LEXLOCAL_INDEX_CHUNK_OVERLAP": "32",
        }
    )

    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
    assert settings.data_dir == tmp_path
    assert settings.security_provider == "explicit-provider"
    assert settings.chat_model_alias == "explicit-chat"
    assert settings.embedding_model_alias == "explicit-embedding:2"
    assert settings.index_chunk_size == 256
    assert settings.index_chunk_overlap == 32


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
    "variable",
    ["LEXLOCAL_CHAT_MODEL_ALIAS", "LEXLOCAL_EMBEDDING_MODEL_ALIAS"],
)
@pytest.mark.parametrize("invalid_alias", ["", "   ", "remote/model", "https://model"])
def test_load_settings_rejects_invalid_model_alias(
    variable: str,
    invalid_alias: str,
) -> None:
    with pytest.raises(ValueError, match="must be a non-empty local model alias"):
        load_settings({variable: invalid_alias})


def test_settings_have_no_remote_or_cloud_configuration_surface() -> None:
    field_names = {field.name for field in fields(load_settings({}))}

    assert not field_names & {
        "endpoint",
        "cloud_provider",
        "azure_endpoint",
        "openai_api_key",
    }


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


@pytest.mark.parametrize(
    "environ",
    [
        {"LEXLOCAL_INDEX_CHUNK_SIZE": "0"},
        {"LEXLOCAL_INDEX_CHUNK_SIZE": "invalid"},
        {"LEXLOCAL_INDEX_CHUNK_OVERLAP": "-1"},
        {
            "LEXLOCAL_INDEX_CHUNK_SIZE": "200",
            "LEXLOCAL_INDEX_CHUNK_OVERLAP": "200",
        },
    ],
)
def test_load_settings_rejects_invalid_index_chunk_configuration(
    environ: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        load_settings(environ)
