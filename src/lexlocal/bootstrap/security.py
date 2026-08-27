"""Compose application security dependencies at the Bootstrap boundary."""

from dataclasses import dataclass

from lexlocal.application.ports.security import (
    ControlledSourceStorage,
    SensitivePayloadCodec,
)
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyControlledSourceStorage,
    InsecureDevelopmentOnlyPayloadCodec,
)

_INSECURE_DEVELOPMENT_PROVIDER = "insecure-development-only"


class SecurityProviderConfigurationError(Exception):
    """Report a sanitized Bootstrap security-provider configuration failure."""


@dataclass(frozen=True, slots=True)
class SecurityProviders:
    """Expose resolved security dependencies through Application-owned ports."""

    payload_codec: SensitivePayloadCodec
    controlled_source_storage: ControlledSourceStorage


def create_security_providers(settings: AppSettings) -> SecurityProviders:
    """Compose the configured security dependencies."""
    if settings.environment == "production":
        raise SecurityProviderConfigurationError(
            "no release-safe security provider is available"
        )

    if (
        settings.security_provider != _INSECURE_DEVELOPMENT_PROVIDER
        or settings.environment not in {"development", "test"}
    ):
        raise SecurityProviderConfigurationError(
            "security provider configuration is unsupported"
        )

    return SecurityProviders(
        payload_codec=InsecureDevelopmentOnlyPayloadCodec(),
        controlled_source_storage=(
            InsecureDevelopmentOnlyControlledSourceStorage()
        ),
    )
