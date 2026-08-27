"""DEVELOPMENT ONLY.

SYNTHETIC FIXTURES ONLY.
NOT RELEASE SAFE.
NOT FOR REAL USER DOCUMENTS.

Provide intentionally insecure in-memory providers for synthetic development data.
"""

from uuid import uuid4

from lexlocal.application.ports.security import (
    ControlledSourceRef,
    EncodedSensitivePayload,
    SecurityContextMismatch,
    SecurityContractError,
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
from lexlocal.domain.identifiers import WorkspaceId

_FORMAT_VERSION = 1


class InsecureDevelopmentOnlyPayloadCodec:
    """DEVELOPMENT ONLY.

    SYNTHETIC FIXTURES ONLY.
    NOT RELEASE SAFE.
    NOT FOR REAL USER DOCUMENTS.

    Wrap synthetic bytes without encryption.
    """

    def encode(
        self,
        plaintext: bytes,
        *,
        context: SensitivePayloadContext,
        key_reference: WorkspaceKeyReference,
    ) -> EncodedSensitivePayload:
        """Wrap bytes with the exact supplied application security metadata."""
        if context.workspace_id != key_reference.workspace_id:
            raise SecurityContextMismatch(
                "context and key reference must belong to the same workspace"
            )

        return EncodedSensitivePayload(
            payload=plaintext,
            context=context,
            key_reference=key_reference,
            format_version=_FORMAT_VERSION,
        )

    def decode(
        self,
        encoded: EncodedSensitivePayload,
        *,
        context: SensitivePayloadContext,
        key_reference: WorkspaceKeyReference,
    ) -> bytes:
        """Return bytes only when caller intent exactly matches the envelope."""
        if encoded.context != context:
            raise SecurityContextMismatch(
                "supplied context does not match encoded payload context"
            )
        if encoded.key_reference != key_reference:
            raise SecurityContextMismatch(
                "supplied key reference does not match encoded payload key reference"
            )
        if encoded.format_version != _FORMAT_VERSION:
            raise SecurityContractError("unsupported encoded payload format version")

        return encoded.payload


class InsecureDevelopmentOnlyControlledSourceStorage:
    """DEVELOPMENT ONLY.

    SYNTHETIC FIXTURES ONLY.
    NOT RELEASE SAFE.
    NOT FOR REAL USER DOCUMENTS.

    Keep synthetic controlled-source bytes only in process memory.
    """

    def __init__(self) -> None:
        self._sources: dict[ControlledSourceRef, bytes] = {}

    def store(
        self,
        workspace_id: WorkspaceId,
        source: bytes,
    ) -> ControlledSourceRef:
        """Store bytes under a fresh opaque workspace-owned reference."""
        if not isinstance(source, bytes):
            raise SecurityContractError("source must be bytes")

        reference = ControlledSourceRef(
            workspace_id=workspace_id,
            value=str(uuid4()),
        )
        self._sources[reference] = source
        return reference

    def read(
        self,
        workspace_id: WorkspaceId,
        reference: ControlledSourceRef,
    ) -> bytes:
        """Return bytes for a live reference owned by the caller workspace."""
        if workspace_id != reference.workspace_id:
            raise SecurityContextMismatch(
                "caller workspace does not own controlled source reference"
            )

        try:
            return self._sources[reference]
        except KeyError:
            raise SecurityContractError(
                "controlled source reference is unavailable"
            ) from None

    def delete(
        self,
        workspace_id: WorkspaceId,
        reference: ControlledSourceRef,
    ) -> None:
        """Remove a live reference owned by the caller workspace."""
        if workspace_id != reference.workspace_id:
            raise SecurityContextMismatch(
                "caller workspace does not own controlled source reference"
            )

        try:
            del self._sources[reference]
        except KeyError:
            raise SecurityContractError(
                "controlled source reference is unavailable"
            ) from None
