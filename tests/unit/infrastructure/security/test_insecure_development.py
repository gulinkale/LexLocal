from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lexlocal.application.ports.security import (
    ControlledSourceRef,
    EncodedSensitivePayload,
    SecurityContextMismatch,
    SecurityContractError,
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
from lexlocal.domain.identifiers import WorkspaceId
from lexlocal.infrastructure.security import insecure_development
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyControlledSourceStorage,
    InsecureDevelopmentOnlyPayloadCodec,
)

WORKSPACE_ID = WorkspaceId("550e8400-e29b-41d4-a716-446655440000")
OTHER_WORKSPACE_ID = WorkspaceId("123e4567-e89b-12d3-a456-426614174000")
REQUIRED_RISK_LABELS = (
    "DEVELOPMENT ONLY",
    "SYNTHETIC FIXTURES ONLY",
    "NOT RELEASE SAFE",
    "NOT FOR REAL USER DOCUMENTS",
)


@pytest.mark.parametrize(
    "documented_object",
    [
        insecure_development,
        InsecureDevelopmentOnlyPayloadCodec,
        InsecureDevelopmentOnlyControlledSourceStorage,
    ],
)
def test_insecure_development_providers_have_required_risk_labels(
    documented_object: object,
) -> None:
    docstring = documented_object.__doc__

    assert docstring is not None
    assert all(label in docstring for label in REQUIRED_RISK_LABELS)


def _context(
    workspace_id: WorkspaceId = WORKSPACE_ID,
    *,
    owner_id: str = "synthetic-owner",
    purpose: str = "synthetic-field",
    schema_version: int = 1,
) -> SensitivePayloadContext:
    return SensitivePayloadContext(
        workspace_id=workspace_id,
        owner_id=owner_id,
        purpose=purpose,
        schema_version=schema_version,
    )


def test_synthetic_bytes_round_trip_without_transformation() -> None:
    codec = InsecureDevelopmentOnlyPayloadCodec()
    context = _context()
    key_reference = WorkspaceKeyReference(WORKSPACE_ID, 3)
    plaintext = b"anonymous synthetic fixture"

    encoded = codec.encode(
        plaintext,
        context=context,
        key_reference=key_reference,
    )

    assert encoded.payload == plaintext
    assert codec.decode(
        encoded,
        context=context,
        key_reference=key_reference,
    ) == plaintext


def test_empty_bytes_round_trip() -> None:
    codec = InsecureDevelopmentOnlyPayloadCodec()
    context = _context()
    key_reference = WorkspaceKeyReference(WORKSPACE_ID, 1)

    encoded = codec.encode(
        b"",
        context=context,
        key_reference=key_reference,
    )

    assert encoded.payload == b""
    assert codec.decode(
        encoded,
        context=context,
        key_reference=key_reference,
    ) == b""


def test_encode_returns_immutable_typed_envelope_with_exact_metadata() -> None:
    codec = InsecureDevelopmentOnlyPayloadCodec()
    context = _context(
        owner_id="  synthetic-owner  ",
        purpose="  synthetic-field  ",
        schema_version=2,
    )
    key_reference = WorkspaceKeyReference(WORKSPACE_ID, 4)

    encoded = codec.encode(
        b"synthetic metadata fixture",
        context=context,
        key_reference=key_reference,
    )

    assert isinstance(encoded, EncodedSensitivePayload)
    assert encoded.context is context
    assert encoded.key_reference is key_reference
    assert encoded.format_version == 1
    attribute_name = "payload"
    with pytest.raises(FrozenInstanceError):
        setattr(encoded, attribute_name, b"replacement")


def test_encode_rejects_context_and_key_from_different_workspaces() -> None:
    codec = InsecureDevelopmentOnlyPayloadCodec()

    with pytest.raises(SecurityContextMismatch):
        codec.encode(
            b"synthetic fixture",
            context=_context(WORKSPACE_ID),
            key_reference=WorkspaceKeyReference(OTHER_WORKSPACE_ID, 1),
        )


@pytest.mark.parametrize(
    "mismatch",
    ["workspace", "owner", "purpose", "schema", "key-reference"],
)
def test_decode_rejects_exact_context_or_key_substitution(mismatch: str) -> None:
    codec = InsecureDevelopmentOnlyPayloadCodec()
    encoded_context = _context()
    encoded_key_reference = WorkspaceKeyReference(WORKSPACE_ID, 1)
    encoded = codec.encode(
        b"synthetic isolation fixture",
        context=encoded_context,
        key_reference=encoded_key_reference,
    )
    caller_context = encoded_context
    caller_key_reference = encoded_key_reference

    if mismatch == "workspace":
        caller_context = _context(OTHER_WORKSPACE_ID)
    elif mismatch == "owner":
        caller_context = _context(owner_id="other-synthetic-owner")
    elif mismatch == "purpose":
        caller_context = _context(purpose="other-synthetic-field")
    elif mismatch == "schema":
        caller_context = _context(schema_version=2)
    else:
        caller_key_reference = WorkspaceKeyReference(WORKSPACE_ID, 2)

    with pytest.raises(SecurityContextMismatch):
        codec.decode(
            encoded,
            context=caller_context,
            key_reference=caller_key_reference,
        )


def test_decode_rejects_unsupported_positive_format_version() -> None:
    codec = InsecureDevelopmentOnlyPayloadCodec()
    context = _context()
    key_reference = WorkspaceKeyReference(WORKSPACE_ID, 1)
    encoded = EncodedSensitivePayload(
        payload=b"synthetic fixture",
        context=context,
        key_reference=key_reference,
        format_version=2,
    )

    with pytest.raises(SecurityContractError) as exc_info:
        codec.decode(
            encoded,
            context=context,
            key_reference=key_reference,
        )

    assert type(exc_info.value) is SecurityContractError


def test_decode_rejects_workspace_mismatch_before_unsupported_format() -> None:
    codec = InsecureDevelopmentOnlyPayloadCodec()
    context = _context()
    key_reference = WorkspaceKeyReference(WORKSPACE_ID, 1)
    encoded = EncodedSensitivePayload(
        payload=b"synthetic isolation fixture",
        context=context,
        key_reference=key_reference,
        format_version=2,
    )

    with pytest.raises(SecurityContextMismatch):
        codec.decode(
            encoded,
            context=_context(OTHER_WORKSPACE_ID),
            key_reference=key_reference,
        )


def test_codec_does_not_write_to_filesystem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    codec = InsecureDevelopmentOnlyPayloadCodec()
    context = _context()
    key_reference = WorkspaceKeyReference(WORKSPACE_ID, 1)

    encoded = codec.encode(
        b"synthetic filesystem fixture",
        context=context,
        key_reference=key_reference,
    )
    codec.decode(
        encoded,
        context=context,
        key_reference=key_reference,
    )

    assert list(tmp_path.iterdir()) == []


def test_controlled_storage_store_read_delete_lifecycle() -> None:
    storage = InsecureDevelopmentOnlyControlledSourceStorage()
    source = b"anonymous synthetic source"

    reference = storage.store(WORKSPACE_ID, source)

    assert isinstance(reference, ControlledSourceRef)
    assert storage.read(WORKSPACE_ID, reference) == source
    storage.delete(WORKSPACE_ID, reference)
    with pytest.raises(SecurityContractError):
        storage.read(WORKSPACE_ID, reference)
    with pytest.raises(SecurityContractError):
        storage.delete(WORKSPACE_ID, reference)


def test_controlled_storage_supports_empty_bytes() -> None:
    storage = InsecureDevelopmentOnlyControlledSourceStorage()

    reference = storage.store(WORKSPACE_ID, b"")

    assert storage.read(WORKSPACE_ID, reference) == b""
    storage.delete(WORKSPACE_ID, reference)


def test_controlled_storage_returns_fresh_opaque_workspace_owned_references() -> None:
    storage = InsecureDevelopmentOnlyControlledSourceStorage()

    first = storage.store(WORKSPACE_ID, b"same synthetic source")
    second = storage.store(WORKSPACE_ID, b"same synthetic source")

    assert isinstance(first, ControlledSourceRef)
    assert first.workspace_id == WORKSPACE_ID
    assert isinstance(first.value, str)
    assert first.value.strip()
    assert first != second
    assert not any(isinstance(value, Path) for value in (first.workspace_id, first.value))


def test_controlled_storage_rejects_cross_workspace_read() -> None:
    storage = InsecureDevelopmentOnlyControlledSourceStorage()
    source = b"workspace-a synthetic source"
    reference = storage.store(WORKSPACE_ID, source)

    with pytest.raises(SecurityContextMismatch):
        storage.read(OTHER_WORKSPACE_ID, reference)

    assert storage.read(WORKSPACE_ID, reference) == source


def test_controlled_storage_rejects_cross_workspace_delete_without_data_loss() -> None:
    storage = InsecureDevelopmentOnlyControlledSourceStorage()
    source = b"workspace-a retained synthetic source"
    reference = storage.store(WORKSPACE_ID, source)

    with pytest.raises(SecurityContextMismatch):
        storage.delete(OTHER_WORKSPACE_ID, reference)

    assert storage.read(WORKSPACE_ID, reference) == source


@pytest.mark.parametrize("operation", ["read", "delete"])
def test_controlled_storage_rejects_unknown_same_workspace_reference(
    operation: str,
) -> None:
    storage = InsecureDevelopmentOnlyControlledSourceStorage()
    reference = ControlledSourceRef(WORKSPACE_ID, "unissued-synthetic-reference")

    with pytest.raises(SecurityContractError) as exc_info:
        if operation == "read":
            storage.read(WORKSPACE_ID, reference)
        else:
            storage.delete(WORKSPACE_ID, reference)

    assert type(exc_info.value) is SecurityContractError
    assert exc_info.value.__cause__ is None


def test_controlled_storage_failure_is_sanitized() -> None:
    storage = InsecureDevelopmentOnlyControlledSourceStorage()
    source = b"synthetic payload must not leak"
    unrelated_source = b"unrelated synthetic payload"
    reference = storage.store(WORKSPACE_ID, source)
    storage.store(OTHER_WORKSPACE_ID, unrelated_source)
    storage.delete(WORKSPACE_ID, reference)

    with pytest.raises(SecurityContractError) as exc_info:
        storage.read(WORKSPACE_ID, reference)

    message = str(exc_info.value)
    assert source.decode() not in message
    assert unrelated_source.decode() not in message
    assert reference.value not in message
    assert str(OTHER_WORKSPACE_ID) not in message


@pytest.mark.parametrize("operation", ["read", "delete"])
@pytest.mark.parametrize("reference_state", ["unknown", "deleted"])
def test_controlled_storage_checks_workspace_before_reference_state(
    operation: str,
    reference_state: str,
) -> None:
    storage = InsecureDevelopmentOnlyControlledSourceStorage()
    if reference_state == "deleted":
        reference = storage.store(WORKSPACE_ID, b"deleted synthetic source")
        storage.delete(WORKSPACE_ID, reference)
    else:
        reference = ControlledSourceRef(
            WORKSPACE_ID,
            "unknown-synthetic-reference",
        )

    with pytest.raises(SecurityContextMismatch):
        if operation == "read":
            storage.read(OTHER_WORKSPACE_ID, reference)
        else:
            storage.delete(OTHER_WORKSPACE_ID, reference)


def test_controlled_storage_does_not_write_to_filesystem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    initial_contents = set(tmp_path.iterdir())
    storage = InsecureDevelopmentOnlyControlledSourceStorage()

    reference = storage.store(WORKSPACE_ID, b"synthetic filesystem source")
    storage.read(WORKSPACE_ID, reference)
    storage.delete(WORKSPACE_ID, reference)

    assert set(tmp_path.iterdir()) == initial_contents
