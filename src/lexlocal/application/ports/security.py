"""Define application-facing security contracts."""

from dataclasses import dataclass
from typing import Protocol

from lexlocal.domain.identifiers import WorkspaceId


class SecurityContractError(Exception):
    """Base exception for application security contract violations."""


class SecurityContextMismatch(SecurityContractError):
    """Raised when security context, key, or resource ownership does not match."""


@dataclass(frozen=True, slots=True)
class WorkspaceKeyReference:
    """Identify a versioned workspace key without exposing key material."""

    workspace_id: WorkspaceId
    key_version: int

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_id, WorkspaceId):
            raise SecurityContractError("workspace_id must be a WorkspaceId")
        if (
            isinstance(self.key_version, bool)
            or not isinstance(self.key_version, int)
            or self.key_version < 1
        ):
            raise SecurityContractError("key_version must be a positive integer")


@dataclass(frozen=True, slots=True)
class SensitivePayloadContext:
    """Bind a future sensitive payload to its application context."""

    workspace_id: WorkspaceId
    owner_id: str
    purpose: str
    schema_version: int

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_id, WorkspaceId):
            raise SecurityContractError("workspace_id must be a WorkspaceId")
        if not isinstance(self.owner_id, str) or not self.owner_id.strip():
            raise SecurityContractError("owner_id must be a non-empty string")
        if not isinstance(self.purpose, str) or not self.purpose.strip():
            raise SecurityContractError("purpose must be a non-empty string")
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version < 1
        ):
            raise SecurityContractError("schema_version must be a positive integer")


@dataclass(frozen=True, slots=True)
class EncodedSensitivePayload:
    """Represent provider output with its security context and key reference."""

    payload: bytes
    context: SensitivePayloadContext
    key_reference: WorkspaceKeyReference
    format_version: int

    def __post_init__(self) -> None:
        if not isinstance(self.payload, bytes):
            raise SecurityContractError("payload must be bytes")
        if not isinstance(self.context, SensitivePayloadContext):
            raise SecurityContractError(
                "context must be a SensitivePayloadContext"
            )
        if not isinstance(self.key_reference, WorkspaceKeyReference):
            raise SecurityContractError(
                "key_reference must be a WorkspaceKeyReference"
            )
        if self.context.workspace_id != self.key_reference.workspace_id:
            raise SecurityContextMismatch(
                "context and key reference must belong to the same workspace"
            )
        if (
            isinstance(self.format_version, bool)
            or not isinstance(self.format_version, int)
            or self.format_version < 1
        ):
            raise SecurityContractError("format_version must be a positive integer")


@dataclass(frozen=True, slots=True)
class ControlledSourceRef:
    """Identify a workspace-owned controlled source with an opaque token."""

    workspace_id: WorkspaceId
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_id, WorkspaceId):
            raise SecurityContractError("workspace_id must be a WorkspaceId")
        if not isinstance(self.value, str) or not self.value.strip():
            raise SecurityContractError("value must be a non-empty string")


class SensitivePayloadCodec(Protocol):
    """Transform sensitive bytes through a provider-independent boundary."""

    def encode(
        self,
        plaintext: bytes,
        *,
        context: SensitivePayloadContext,
        key_reference: WorkspaceKeyReference,
    ) -> EncodedSensitivePayload:
        """Represent plaintext as provider output bound to its security context."""

        ...

    def decode(
        self,
        encoded: EncodedSensitivePayload,
        *,
        context: SensitivePayloadContext,
        key_reference: WorkspaceKeyReference,
    ) -> bytes:
        """Recover bytes using the caller's expected security context."""

        ...


class ControlledSourceStorage(Protocol):
    """Manage controlled source bytes through opaque workspace-owned references."""

    def store(
        self,
        workspace_id: WorkspaceId,
        source: bytes,
    ) -> ControlledSourceRef:
        """Store source bytes and return an opaque reference."""

        ...

    def read(
        self,
        workspace_id: WorkspaceId,
        reference: ControlledSourceRef,
    ) -> bytes:
        """Read source bytes through a workspace-owned reference."""

        ...

    def delete(
        self,
        workspace_id: WorkspaceId,
        reference: ControlledSourceRef,
    ) -> None:
        """Delete source bytes through a workspace-owned reference."""

        ...
