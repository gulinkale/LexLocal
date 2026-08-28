"""DEVELOPMENT ONLY.

SYNTHETIC FIXTURES ONLY.
NOT RELEASE SAFE.
NOT FOR REAL USER DOCUMENTS.

Map anonymous synthetic workspace labels to development persistence values.
"""

from hashlib import sha256

from lexlocal.application.ports.security import (
    EncodedSensitivePayload,
    SecurityContractError,
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
from lexlocal.domain.identifiers import WorkspaceId
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyPayloadCodec,
)

_FORMAT_VERSION = 1
_PURPOSE = "workspace-display-name"
_SCHEMA_VERSION = 1
_SYNTHETIC_KEY_VERSION = 1
_LOOKUP_TOKEN_PREFIX = (
    b"lexlocal/insecure-development-only/workspace-name-lookup/v1\x00"
)


class InsecureDevelopmentOnlyWorkspaceNamePersistence:
    """DEVELOPMENT ONLY.

    SYNTHETIC FIXTURES ONLY.
    NOT RELEASE SAFE.
    NOT FOR REAL USER DOCUMENTS.

    Convert exact synthetic workspace labels into development persistence values.
    """

    def __init__(self) -> None:
        self._codec = InsecureDevelopmentOnlyPayloadCodec()

    def encode(
        self,
        workspace_id: WorkspaceId,
        display_name: str,
    ) -> EncodedSensitivePayload:
        """Encode an exact synthetic label with deterministic workspace metadata."""
        context, key_reference = self._metadata(workspace_id)
        return self._codec.encode(
            self._display_name_bytes(display_name),
            context=context,
            key_reference=key_reference,
        )

    def restore_payload(
        self,
        workspace_id: WorkspaceId,
        payload: bytes,
    ) -> EncodedSensitivePayload:
        """Reconstruct the deterministic development metadata for stored bytes."""
        if not isinstance(payload, bytes):
            raise SecurityContractError("workspace name payload must be bytes")

        context, key_reference = self._metadata(workspace_id)
        return EncodedSensitivePayload(
            payload=payload,
            context=context,
            key_reference=key_reference,
            format_version=_FORMAT_VERSION,
        )

    def decode(
        self,
        workspace_id: WorkspaceId,
        encoded: EncodedSensitivePayload,
    ) -> str:
        """Decode an envelope only for its exact deterministic workspace metadata."""
        if not isinstance(encoded, EncodedSensitivePayload):
            raise SecurityContractError(
                "encoded workspace name must be an EncodedSensitivePayload"
            )

        context, key_reference = self._metadata(workspace_id)
        payload = self._codec.decode(
            encoded,
            context=context,
            key_reference=key_reference,
        )

        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            raise SecurityContractError(
                "encoded workspace name is not valid UTF-8"
            ) from None

    def lookup_token(self, display_name: str) -> bytes:
        """Return the deterministic development token for exact label bytes."""
        return sha256(
            _LOOKUP_TOKEN_PREFIX + self._display_name_bytes(display_name)
        ).digest()

    @staticmethod
    def _display_name_bytes(display_name: str) -> bytes:
        if not isinstance(display_name, str):
            raise SecurityContractError("workspace display name must be a string")

        try:
            return display_name.encode("utf-8")
        except UnicodeEncodeError:
            raise SecurityContractError(
                "workspace display name is not valid UTF-8"
            ) from None

    @staticmethod
    def _metadata(
        workspace_id: WorkspaceId,
    ) -> tuple[SensitivePayloadContext, WorkspaceKeyReference]:
        context = SensitivePayloadContext(
            workspace_id=workspace_id,
            owner_id=str(workspace_id),
            purpose=_PURPOSE,
            schema_version=_SCHEMA_VERSION,
        )
        key_reference = WorkspaceKeyReference(
            workspace_id=workspace_id,
            key_version=_SYNTHETIC_KEY_VERSION,
        )
        return context, key_reference
