from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from unittest.mock import Mock

import pytest

from lexlocal.application.ports.security import (
    ControlledSourceStorage,
    SensitivePayloadCodec,
)
from lexlocal.bootstrap import security as security_bootstrap
from lexlocal.bootstrap.security import (
    SecurityProviderConfigurationError,
    SecurityProviders,
    create_security_providers,
)
from lexlocal.bootstrap.settings import AppSettings, load_settings
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyControlledSourceStorage,
    InsecureDevelopmentOnlyPayloadCodec,
)

_PAYLOAD_CODEC_CONFORMANCE: SensitivePayloadCodec = (
    InsecureDevelopmentOnlyPayloadCodec()
)
_CONTROLLED_SOURCE_STORAGE_CONFORMANCE: ControlledSourceStorage = (
    InsecureDevelopmentOnlyControlledSourceStorage()
)


def _settings(
    security_provider: str,
    *,
    environment: str = "development",
) -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment=environment,
        log_level="INFO",
        data_dir=Path("synthetic-data"),
        security_provider=security_provider,
    )


def test_security_providers_is_immutable_and_has_only_approved_ports() -> None:
    providers = create_security_providers(
        _settings("insecure-development-only")
    )

    assert [field.name for field in fields(SecurityProviders)] == [
        "payload_codec",
        "controlled_source_storage",
    ]
    attribute_name = "payload_codec"
    with pytest.raises(FrozenInstanceError):
        setattr(providers, attribute_name, providers.payload_codec)


@pytest.mark.parametrize("environment", ["development", "test"])
def test_bootstrap_composes_both_application_security_ports(
    environment: str,
) -> None:
    providers = create_security_providers(
        _settings(
            "insecure-development-only",
            environment=environment,
        )
    )

    payload_codec: SensitivePayloadCodec = providers.payload_codec
    controlled_source_storage: ControlledSourceStorage = (
        providers.controlled_source_storage
    )

    assert isinstance(payload_codec, InsecureDevelopmentOnlyPayloadCodec)
    assert isinstance(
        controlled_source_storage,
        InsecureDevelopmentOnlyControlledSourceStorage,
    )


@pytest.mark.parametrize(
    "environment",
    ["development", "test", "production"],
)
def test_unknown_security_provider_fails_in_every_environment(
    environment: str,
) -> None:
    with pytest.raises(SecurityProviderConfigurationError):
        create_security_providers(
            _settings(
                "unknown-provider",
                environment=environment,
            )
        )


@pytest.mark.parametrize(
    "security_provider",
    ["insecure-development-only", ""],
)
def test_production_fails_before_insecure_provider_construction(
    security_provider: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload_codec_factory = Mock()
    controlled_storage_factory = Mock()
    monkeypatch.setattr(
        security_bootstrap,
        "InsecureDevelopmentOnlyPayloadCodec",
        payload_codec_factory,
    )
    monkeypatch.setattr(
        security_bootstrap,
        "InsecureDevelopmentOnlyControlledSourceStorage",
        controlled_storage_factory,
    )

    with pytest.raises(SecurityProviderConfigurationError) as exc_info:
        create_security_providers(
            _settings(
                security_provider,
                environment="production",
            )
        )

    assert "release-safe security provider" in str(exc_info.value)
    payload_codec_factory.assert_not_called()
    controlled_storage_factory.assert_not_called()


def test_security_provider_configuration_failure_is_sanitized() -> None:
    settings = _settings("synthetic-unsupported-provider")

    with pytest.raises(SecurityProviderConfigurationError) as exc_info:
        create_security_providers(settings)

    message = str(exc_info.value)
    assert settings.security_provider not in message
    assert "payload" not in message
    assert "source" not in message
    assert "key" not in message
    assert "path" not in message


@pytest.mark.parametrize(
    ("environ", "accepted"),
    [
        pytest.param({}, True, id="development-default"),
        pytest.param(
            {"LEXLOCAL_ENV": "test"},
            True,
            id="test-default",
        ),
        pytest.param(
            {
                "LEXLOCAL_ENV": "production",
                "LEXLOCAL_SECURITY_PROVIDER": "insecure-development-only",
            },
            False,
            id="production-insecure",
        ),
        pytest.param(
            {"LEXLOCAL_SECURITY_PROVIDER": "unknown-provider"},
            False,
            id="development-unknown",
        ),
        pytest.param(
            {
                "LEXLOCAL_ENV": "test",
                "LEXLOCAL_SECURITY_PROVIDER": "unknown-provider",
            },
            False,
            id="test-unknown",
        ),
        pytest.param(
            {
                "LEXLOCAL_ENV": "production",
                "LEXLOCAL_SECURITY_PROVIDER": "unknown-provider",
            },
            False,
            id="production-unknown",
        ),
        pytest.param(
            {"LEXLOCAL_ENV": "production"},
            False,
            id="production-missing",
        ),
    ],
)
def test_settings_to_security_composition_matrix(
    environ: dict[str, str],
    accepted: bool,
) -> None:
    settings = load_settings(environ)

    if accepted:
        providers = create_security_providers(settings)
        payload_codec: SensitivePayloadCodec = providers.payload_codec
        controlled_storage: ControlledSourceStorage = (
            providers.controlled_source_storage
        )

        assert isinstance(payload_codec, InsecureDevelopmentOnlyPayloadCodec)
        assert isinstance(
            controlled_storage,
            InsecureDevelopmentOnlyControlledSourceStorage,
        )
        return

    with pytest.raises(SecurityProviderConfigurationError) as exc_info:
        create_security_providers(settings)

    message = str(exc_info.value)
    if settings.security_provider:
        assert settings.security_provider not in message
    for sensitive_term in ("payload", "source", "key", "path"):
        assert sensitive_term not in message
