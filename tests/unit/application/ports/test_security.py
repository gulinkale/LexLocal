from dataclasses import FrozenInstanceError, fields

import pytest

from lexlocal.application.ports.security import (
    ControlledSourceRef,
    ControlledSourceStorage,
    EncodedSensitivePayload,
    SecurityContextMismatch,
    SecurityContractError,
    SensitivePayloadCodec,
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
from lexlocal.domain.identifiers import DocumentId, WorkspaceId

WORKSPACE_ID = WorkspaceId("550e8400-e29b-41d4-a716-446655440000")
OTHER_WORKSPACE_ID = WorkspaceId("123e4567-e89b-12d3-a456-426614174000")


class _SensitivePayloadCodecDouble:
    def encode(
        self,
        plaintext: bytes,
        *,
        context: SensitivePayloadContext,
        key_reference: WorkspaceKeyReference,
    ) -> EncodedSensitivePayload:
        raise AssertionError("static type-conformance double must not be called")

    def decode(
        self,
        encoded: EncodedSensitivePayload,
        *,
        context: SensitivePayloadContext,
        key_reference: WorkspaceKeyReference,
    ) -> bytes:
        raise AssertionError("static type-conformance double must not be called")


_SENSITIVE_PAYLOAD_CODEC_CONFORMANCE: SensitivePayloadCodec = (
    _SensitivePayloadCodecDouble()
)


class _ControlledSourceStorageDouble:
    def store(
        self,
        workspace_id: WorkspaceId,
        source: bytes,
    ) -> ControlledSourceRef:
        raise AssertionError("static type-conformance double must not be called")

    def read(
        self,
        workspace_id: WorkspaceId,
        reference: ControlledSourceRef,
    ) -> bytes:
        raise AssertionError("static type-conformance double must not be called")

    def delete(
        self,
        workspace_id: WorkspaceId,
        reference: ControlledSourceRef,
    ) -> None:
        raise AssertionError("static type-conformance double must not be called")


_CONTROLLED_SOURCE_STORAGE_CONFORMANCE: ControlledSourceStorage = (
    _ControlledSourceStorageDouble()
)


def test_security_contract_error_is_the_application_security_base_error() -> None:
    error = SecurityContractError("security contract violation")

    assert isinstance(error, Exception)


def test_security_context_mismatch_is_a_security_contract_error() -> None:
    assert issubclass(SecurityContextMismatch, SecurityContractError)


def test_base_error_handler_catches_security_context_mismatch() -> None:
    with pytest.raises(SecurityContractError):
        raise SecurityContextMismatch("security context mismatch")


def test_security_context_mismatch_can_be_caught_specifically() -> None:
    with pytest.raises(SecurityContextMismatch):
        raise SecurityContextMismatch("security context mismatch")


@pytest.mark.parametrize("key_version", [1, 2])
def test_workspace_key_reference_accepts_typed_positive_version(
    key_version: int,
) -> None:
    reference = WorkspaceKeyReference(
        workspace_id=WORKSPACE_ID,
        key_version=key_version,
    )

    assert reference.workspace_id == WORKSPACE_ID
    assert reference.key_version == key_version


@pytest.mark.parametrize(
    "invalid_workspace_id",
    [
        str(WORKSPACE_ID),
        DocumentId(str(WORKSPACE_ID)),
        None,
    ],
)
def test_workspace_key_reference_rejects_non_workspace_identifier(
    invalid_workspace_id: object,
) -> None:
    with pytest.raises(SecurityContractError):
        WorkspaceKeyReference(
            workspace_id=invalid_workspace_id,  # type: ignore[arg-type]
            key_version=1,
        )


@pytest.mark.parametrize(
    "invalid_key_version",
    [0, -1, True, False, 1.0, "1", None],
)
def test_workspace_key_reference_rejects_invalid_key_version(
    invalid_key_version: object,
) -> None:
    with pytest.raises(SecurityContractError):
        WorkspaceKeyReference(
            workspace_id=WORKSPACE_ID,
            key_version=invalid_key_version,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("attribute_name", ["workspace_id", "key_version"])
def test_workspace_key_reference_is_immutable(attribute_name: str) -> None:
    reference = WorkspaceKeyReference(WORKSPACE_ID, 1)

    with pytest.raises(FrozenInstanceError):
        setattr(reference, attribute_name, None)


def test_workspace_key_reference_is_hashable_by_workspace_and_version() -> None:
    first = WorkspaceKeyReference(WORKSPACE_ID, 1)
    equivalent = WorkspaceKeyReference(WORKSPACE_ID, 1)

    assert first == equivalent
    assert hash(first) == hash(equivalent)
    assert len({first, equivalent}) == 1


def test_workspace_key_reference_identity_includes_workspace_and_version() -> None:
    reference = WorkspaceKeyReference(WORKSPACE_ID, 1)

    assert reference != WorkspaceKeyReference(WORKSPACE_ID, 2)
    assert reference != WorkspaceKeyReference(OTHER_WORKSPACE_ID, 1)


def test_workspace_key_reference_contains_only_approved_fields() -> None:
    assert {field.name for field in fields(WorkspaceKeyReference)} == {
        "workspace_id",
        "key_version",
    }


def test_workspace_key_reference_repr_contains_only_safe_reference_metadata() -> None:
    reference = WorkspaceKeyReference(WORKSPACE_ID, 1)
    representation = repr(reference)

    assert "WorkspaceKeyReference" in representation
    assert "workspace_id=" in representation
    assert "key_version=1" in representation


@pytest.mark.parametrize("schema_version", [1, 2])
def test_sensitive_payload_context_accepts_valid_construction(
    schema_version: int,
) -> None:
    context = SensitivePayloadContext(
        workspace_id=WORKSPACE_ID,
        owner_id="document-version-42",
        purpose="supplier-tax-number",
        schema_version=schema_version,
    )

    assert context.workspace_id == WORKSPACE_ID
    assert context.owner_id == "document-version-42"
    assert context.purpose == "supplier-tax-number"
    assert context.schema_version == schema_version


@pytest.mark.parametrize(
    "invalid_workspace_id",
    [
        str(WORKSPACE_ID),
        DocumentId(str(WORKSPACE_ID)),
        None,
    ],
)
def test_sensitive_payload_context_rejects_non_workspace_identifier(
    invalid_workspace_id: object,
) -> None:
    with pytest.raises(SecurityContractError):
        SensitivePayloadContext(
            workspace_id=invalid_workspace_id,  # type: ignore[arg-type]
            owner_id="document-version-42",
            purpose="supplier-tax-number",
            schema_version=1,
        )


@pytest.mark.parametrize("invalid_owner_id", ["", " ", "\t", "\n", None, 42])
def test_sensitive_payload_context_rejects_invalid_owner_id(
    invalid_owner_id: object,
) -> None:
    with pytest.raises(SecurityContractError):
        SensitivePayloadContext(
            workspace_id=WORKSPACE_ID,
            owner_id=invalid_owner_id,  # type: ignore[arg-type]
            purpose="supplier-tax-number",
            schema_version=1,
        )


@pytest.mark.parametrize("invalid_purpose", ["", "   ", "\t", "\n", None, 42])
def test_sensitive_payload_context_rejects_invalid_purpose(
    invalid_purpose: object,
) -> None:
    with pytest.raises(SecurityContractError):
        SensitivePayloadContext(
            workspace_id=WORKSPACE_ID,
            owner_id="document-version-42",
            purpose=invalid_purpose,  # type: ignore[arg-type]
            schema_version=1,
        )


@pytest.mark.parametrize(
    "invalid_schema_version",
    [0, -1, True, False, 1.0, "1", None],
)
def test_sensitive_payload_context_rejects_invalid_schema_version(
    invalid_schema_version: object,
) -> None:
    with pytest.raises(SecurityContractError):
        SensitivePayloadContext(
            workspace_id=WORKSPACE_ID,
            owner_id="document-version-42",
            purpose="supplier-tax-number",
            schema_version=invalid_schema_version,  # type: ignore[arg-type]
        )


def test_sensitive_payload_context_preserves_valid_text_without_trimming() -> None:
    context = SensitivePayloadContext(
        workspace_id=WORKSPACE_ID,
        owner_id="  document-42  ",
        purpose="  tax-number  ",
        schema_version=1,
    )

    assert context.owner_id == "  document-42  "
    assert context.purpose == "  tax-number  "


@pytest.mark.parametrize(
    "attribute_name",
    ["workspace_id", "owner_id", "purpose", "schema_version"],
)
def test_sensitive_payload_context_is_immutable(attribute_name: str) -> None:
    context = SensitivePayloadContext(
        WORKSPACE_ID,
        "document-version-42",
        "supplier-tax-number",
        1,
    )

    with pytest.raises(FrozenInstanceError):
        setattr(context, attribute_name, None)


def test_sensitive_payload_context_is_hashable() -> None:
    first = SensitivePayloadContext(
        WORKSPACE_ID,
        "document-version-42",
        "supplier-tax-number",
        1,
    )
    equivalent = SensitivePayloadContext(
        WORKSPACE_ID,
        "document-version-42",
        "supplier-tax-number",
        1,
    )

    assert hash(first) == hash(equivalent)
    assert len({first, equivalent}) == 1


def test_sensitive_payload_context_identity_includes_all_four_fields() -> None:
    context = SensitivePayloadContext(
        WORKSPACE_ID,
        "document-version-42",
        "supplier-tax-number",
        1,
    )

    assert context == SensitivePayloadContext(
        WORKSPACE_ID,
        "document-version-42",
        "supplier-tax-number",
        1,
    )
    assert context != SensitivePayloadContext(
        OTHER_WORKSPACE_ID,
        "document-version-42",
        "supplier-tax-number",
        1,
    )
    assert context != SensitivePayloadContext(
        WORKSPACE_ID,
        "document-version-43",
        "supplier-tax-number",
        1,
    )
    assert context != SensitivePayloadContext(
        WORKSPACE_ID,
        "document-version-42",
        "supplier-name",
        1,
    )
    assert context != SensitivePayloadContext(
        WORKSPACE_ID,
        "document-version-42",
        "supplier-tax-number",
        2,
    )


def test_sensitive_payload_context_contains_only_approved_fields() -> None:
    assert {field.name for field in fields(SensitivePayloadContext)} == {
        "workspace_id",
        "owner_id",
        "purpose",
        "schema_version",
    }


def _sensitive_payload_context(
    workspace_id: WorkspaceId = WORKSPACE_ID,
    *,
    owner_id: str = "document-version-42",
) -> SensitivePayloadContext:
    return SensitivePayloadContext(
        workspace_id=workspace_id,
        owner_id=owner_id,
        purpose="supplier-tax-number",
        schema_version=1,
    )


def test_encoded_sensitive_payload_is_distinct_from_raw_bytes() -> None:
    encoded = EncodedSensitivePayload(
        payload=b"encoded-provider-output",
        context=_sensitive_payload_context(),
        key_reference=WorkspaceKeyReference(WORKSPACE_ID, 1),
        format_version=1,
    )

    assert not isinstance(encoded, bytes)
    assert isinstance(encoded.payload, bytes)


def test_encoded_sensitive_payload_accepts_matching_workspace_and_preserves_metadata(
) -> None:
    payload = b"encoded-provider-output"
    context = _sensitive_payload_context()
    key_reference = WorkspaceKeyReference(WORKSPACE_ID, 2)

    encoded = EncodedSensitivePayload(
        payload=payload,
        context=context,
        key_reference=key_reference,
        format_version=2,
    )

    assert encoded.payload == payload
    assert encoded.context is context
    assert encoded.key_reference is key_reference
    assert encoded.format_version == 2


def test_encoded_sensitive_payload_accepts_empty_payload() -> None:
    encoded = EncodedSensitivePayload(
        payload=b"",
        context=_sensitive_payload_context(),
        key_reference=WorkspaceKeyReference(WORKSPACE_ID, 1),
        format_version=1,
    )

    assert encoded.payload == b""


@pytest.mark.parametrize(
    "invalid_payload",
    ["hello", bytearray(b"hello"), memoryview(b"hello"), None, 123],
)
def test_encoded_sensitive_payload_rejects_non_bytes_payload(
    invalid_payload: object,
) -> None:
    with pytest.raises(SecurityContractError):
        EncodedSensitivePayload(
            payload=invalid_payload,  # type: ignore[arg-type]
            context=_sensitive_payload_context(),
            key_reference=WorkspaceKeyReference(WORKSPACE_ID, 1),
            format_version=1,
        )


@pytest.mark.parametrize(
    "invalid_context",
    [{}, None, "context", WorkspaceKeyReference(WORKSPACE_ID, 1)],
)
def test_encoded_sensitive_payload_rejects_invalid_context_before_workspace_access(
    invalid_context: object,
) -> None:
    with pytest.raises(SecurityContractError):
        EncodedSensitivePayload(
            payload=b"encoded-provider-output",
            context=invalid_context,  # type: ignore[arg-type]
            key_reference=WorkspaceKeyReference(WORKSPACE_ID, 1),
            format_version=1,
        )


@pytest.mark.parametrize(
    "invalid_key_reference",
    [None, {}, "key-reference", _sensitive_payload_context()],
)
def test_encoded_sensitive_payload_rejects_invalid_key_reference_before_workspace_access(
    invalid_key_reference: object,
) -> None:
    with pytest.raises(SecurityContractError):
        EncodedSensitivePayload(
            payload=b"encoded-provider-output",
            context=_sensitive_payload_context(),
            key_reference=invalid_key_reference,  # type: ignore[arg-type]
            format_version=1,
        )


def test_encoded_sensitive_payload_rejects_workspace_mismatch_specifically() -> None:
    with pytest.raises(SecurityContextMismatch):
        EncodedSensitivePayload(
            payload=b"encoded-provider-output",
            context=_sensitive_payload_context(WORKSPACE_ID),
            key_reference=WorkspaceKeyReference(OTHER_WORKSPACE_ID, 1),
            format_version=1,
        )


def test_encoded_payload_rejects_workspace_mismatch_before_invalid_format() -> None:
    with pytest.raises(SecurityContextMismatch):
        EncodedSensitivePayload(
            payload=b"encoded-provider-output",
            context=_sensitive_payload_context(WORKSPACE_ID),
            key_reference=WorkspaceKeyReference(OTHER_WORKSPACE_ID, 1),
            format_version=0,
        )


@pytest.mark.parametrize(
    "invalid_format_version",
    [0, -1, True, False, 1.0, "1", None],
)
def test_encoded_sensitive_payload_rejects_invalid_format_version(
    invalid_format_version: object,
) -> None:
    with pytest.raises(SecurityContractError):
        EncodedSensitivePayload(
            payload=b"encoded-provider-output",
            context=_sensitive_payload_context(),
            key_reference=WorkspaceKeyReference(WORKSPACE_ID, 1),
            format_version=invalid_format_version,  # type: ignore[arg-type]
        )


def test_encoded_sensitive_payload_accepts_unknown_positive_format_version() -> None:
    encoded = EncodedSensitivePayload(
        payload=b"encoded-provider-output",
        context=_sensitive_payload_context(),
        key_reference=WorkspaceKeyReference(WORKSPACE_ID, 1),
        format_version=999,
    )

    assert encoded.format_version == 999


@pytest.mark.parametrize(
    "attribute_name",
    ["payload", "context", "key_reference", "format_version"],
)
def test_encoded_sensitive_payload_is_immutable(attribute_name: str) -> None:
    encoded = EncodedSensitivePayload(
        b"encoded-provider-output",
        _sensitive_payload_context(),
        WorkspaceKeyReference(WORKSPACE_ID, 1),
        1,
    )

    with pytest.raises(FrozenInstanceError):
        setattr(encoded, attribute_name, None)


def test_encoded_sensitive_payload_is_hashable() -> None:
    first = EncodedSensitivePayload(
        b"encoded-provider-output",
        _sensitive_payload_context(),
        WorkspaceKeyReference(WORKSPACE_ID, 1),
        1,
    )
    equivalent = EncodedSensitivePayload(
        b"encoded-provider-output",
        _sensitive_payload_context(),
        WorkspaceKeyReference(WORKSPACE_ID, 1),
        1,
    )

    assert hash(first) == hash(equivalent)
    assert len({first, equivalent}) == 1


def test_encoded_sensitive_payload_identity_includes_all_four_fields() -> None:
    encoded = EncodedSensitivePayload(
        b"encoded-provider-output",
        _sensitive_payload_context(),
        WorkspaceKeyReference(WORKSPACE_ID, 1),
        1,
    )

    assert encoded == EncodedSensitivePayload(
        b"encoded-provider-output",
        _sensitive_payload_context(),
        WorkspaceKeyReference(WORKSPACE_ID, 1),
        1,
    )
    assert encoded != EncodedSensitivePayload(
        b"different-provider-output",
        _sensitive_payload_context(),
        WorkspaceKeyReference(WORKSPACE_ID, 1),
        1,
    )
    assert encoded != EncodedSensitivePayload(
        b"encoded-provider-output",
        _sensitive_payload_context(owner_id="document-version-43"),
        WorkspaceKeyReference(WORKSPACE_ID, 1),
        1,
    )
    assert encoded != EncodedSensitivePayload(
        b"encoded-provider-output",
        _sensitive_payload_context(),
        WorkspaceKeyReference(WORKSPACE_ID, 2),
        1,
    )
    assert encoded != EncodedSensitivePayload(
        b"encoded-provider-output",
        _sensitive_payload_context(),
        WorkspaceKeyReference(WORKSPACE_ID, 1),
        2,
    )


def test_encoded_sensitive_payload_contains_only_approved_fields() -> None:
    assert {field.name for field in fields(EncodedSensitivePayload)} == {
        "payload",
        "context",
        "key_reference",
        "format_version",
    }


def test_controlled_source_ref_accepts_valid_construction() -> None:
    reference = ControlledSourceRef(
        workspace_id=WORKSPACE_ID,
        value="source-123",
    )

    assert reference.workspace_id == WORKSPACE_ID
    assert reference.value == "source-123"


@pytest.mark.parametrize(
    "invalid_workspace_id",
    [
        str(WORKSPACE_ID),
        DocumentId(str(WORKSPACE_ID)),
        None,
    ],
)
def test_controlled_source_ref_rejects_non_workspace_identifier(
    invalid_workspace_id: object,
) -> None:
    with pytest.raises(SecurityContractError):
        ControlledSourceRef(
            workspace_id=invalid_workspace_id,  # type: ignore[arg-type]
            value="source-123",
        )


def test_controlled_source_ref_rejects_empty_token() -> None:
    with pytest.raises(SecurityContractError):
        ControlledSourceRef(workspace_id=WORKSPACE_ID, value="")


@pytest.mark.parametrize("whitespace_token", [" ", "   ", "\t", "\n"])
def test_controlled_source_ref_rejects_whitespace_only_token(
    whitespace_token: str,
) -> None:
    with pytest.raises(SecurityContractError):
        ControlledSourceRef(
            workspace_id=WORKSPACE_ID,
            value=whitespace_token,
        )


@pytest.mark.parametrize("invalid_token", [None, 123, b"source-123"])
def test_controlled_source_ref_rejects_non_string_token(
    invalid_token: object,
) -> None:
    with pytest.raises(SecurityContractError):
        ControlledSourceRef(
            workspace_id=WORKSPACE_ID,
            value=invalid_token,  # type: ignore[arg-type]
        )


def test_controlled_source_ref_preserves_valid_token_without_trimming() -> None:
    reference = ControlledSourceRef(
        workspace_id=WORKSPACE_ID,
        value="  source-123  ",
    )

    assert reference.value == "  source-123  "


@pytest.mark.parametrize("attribute_name", ["workspace_id", "value"])
def test_controlled_source_ref_is_immutable(attribute_name: str) -> None:
    reference = ControlledSourceRef(WORKSPACE_ID, "source-123")

    with pytest.raises(FrozenInstanceError):
        setattr(reference, attribute_name, None)


def test_controlled_source_ref_is_hashable() -> None:
    first = ControlledSourceRef(WORKSPACE_ID, "source-123")
    equivalent = ControlledSourceRef(WORKSPACE_ID, "source-123")

    assert hash(first) == hash(equivalent)
    assert len({first, equivalent}) == 1


def test_controlled_source_ref_identity_includes_workspace_and_token() -> None:
    reference = ControlledSourceRef(WORKSPACE_ID, "source-123")

    assert reference == ControlledSourceRef(WORKSPACE_ID, "source-123")
    assert reference != ControlledSourceRef(WORKSPACE_ID, "source-456")
    assert reference != ControlledSourceRef(OTHER_WORKSPACE_ID, "source-123")


def test_controlled_source_ref_contains_only_opaque_approved_fields() -> None:
    assert {field.name for field in fields(ControlledSourceRef)} == {
        "workspace_id",
        "value",
    }
