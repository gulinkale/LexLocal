"""Tests for synthetic-only workspace-name persistence values."""

import pytest

from lexlocal.application.ports.security import (
    EncodedSensitivePayload,
    SecurityContextMismatch,
    SecurityContractError,
)
from lexlocal.domain.identifiers import WorkspaceId
from lexlocal.infrastructure.security import insecure_development_workspace
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
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
        insecure_development_workspace,
        InsecureDevelopmentOnlyWorkspaceNamePersistence,
    ],
)
def test_workspace_name_adapter_has_all_required_risk_labels(
    documented_object: object,
) -> None:
    docstring = documented_object.__doc__

    assert docstring is not None
    assert all(label in docstring for label in REQUIRED_RISK_LABELS)


def test_documentation_does_not_claim_protected_or_release_capabilities() -> None:
    documentation = " ".join(
        (
            insecure_development_workspace.__doc__ or "",
            InsecureDevelopmentOnlyWorkspaceNamePersistence.__doc__ or "",
        )
    ).lower()

    assert "encryption" not in documentation
    assert "hmac" not in documentation
    assert "confidentiality" not in documentation
    assert "production safe" not in documentation


def test_exact_unicode_display_name_round_trips_without_normalization() -> None:
    adapter = InsecureDevelopmentOnlyWorkspaceNamePersistence()
    display_name = "  Synthetic Çalışma Alanı K  "

    encoded = adapter.encode(WORKSPACE_ID, display_name)

    assert encoded.payload == display_name.encode("utf-8")
    assert adapter.decode(WORKSPACE_ID, encoded) == display_name


def test_encode_uses_exact_frozen_metadata() -> None:
    adapter = InsecureDevelopmentOnlyWorkspaceNamePersistence()

    encoded = adapter.encode(WORKSPACE_ID, "Synthetic Workspace")

    assert isinstance(encoded, EncodedSensitivePayload)
    assert encoded.context.workspace_id == WORKSPACE_ID
    assert encoded.context.owner_id == str(WORKSPACE_ID)
    assert encoded.context.purpose == "workspace-display-name"
    assert encoded.context.schema_version == 1
    assert encoded.key_reference.workspace_id == WORKSPACE_ID
    assert encoded.key_reference.key_version == 1
    assert encoded.format_version == 1


def test_restore_payload_reconstructs_matching_metadata_for_decode() -> None:
    adapter = InsecureDevelopmentOnlyWorkspaceNamePersistence()
    display_name = "Anonymous Synthetic Workspace"
    stored_payload = adapter.encode(WORKSPACE_ID, display_name).payload

    restored = adapter.restore_payload(WORKSPACE_ID, stored_payload)

    assert adapter.decode(WORKSPACE_ID, restored) == display_name
    assert restored.context.owner_id == str(WORKSPACE_ID)
    assert restored.context.purpose == "workspace-display-name"
    assert restored.context.schema_version == 1
    assert restored.key_reference.key_version == 1
    assert restored.format_version == 1


def test_lookup_token_is_deterministic_for_exact_input() -> None:
    adapter = InsecureDevelopmentOnlyWorkspaceNamePersistence()
    display_name = "Synthetic Workspace"

    first = adapter.lookup_token(display_name)
    second = adapter.lookup_token(display_name)

    assert first == second
    assert isinstance(first, bytes)
    assert len(first) == 32


def test_lookup_token_changes_for_relevant_exact_input_difference() -> None:
    adapter = InsecureDevelopmentOnlyWorkspaceNamePersistence()

    original = adapter.lookup_token("Synthetic Workspace")
    changed_case = adapter.lookup_token("synthetic Workspace")
    surrounding_space = adapter.lookup_token(" Synthetic Workspace ")

    assert len({original, changed_case, surrounding_space}) == 3


def test_workspace_context_changes_encoded_identity_not_exact_name_token() -> None:
    adapter = InsecureDevelopmentOnlyWorkspaceNamePersistence()
    display_name = "Synthetic Workspace"

    first = adapter.encode(WORKSPACE_ID, display_name)
    second = adapter.encode(OTHER_WORKSPACE_ID, display_name)

    assert first.payload == second.payload
    assert first.context != second.context
    assert first.key_reference != second.key_reference


def test_decode_rejects_workspace_substitution_through_existing_contract() -> None:
    adapter = InsecureDevelopmentOnlyWorkspaceNamePersistence()
    encoded = adapter.encode(WORKSPACE_ID, "Synthetic Workspace")

    with pytest.raises(SecurityContextMismatch):
        adapter.decode(OTHER_WORKSPACE_ID, encoded)


def test_empty_display_name_round_trips_and_has_deterministic_token() -> None:
    adapter = InsecureDevelopmentOnlyWorkspaceNamePersistence()

    encoded = adapter.encode(WORKSPACE_ID, "")
    first_token = adapter.lookup_token("")
    second_token = adapter.lookup_token("")

    assert encoded.payload == b""
    assert adapter.decode(WORKSPACE_ID, encoded) == ""
    assert first_token == second_token


@pytest.mark.parametrize("invalid_name", [None, b"synthetic", 123])
def test_invalid_display_name_failure_is_sanitized(invalid_name: object) -> None:
    adapter = InsecureDevelopmentOnlyWorkspaceNamePersistence()

    with pytest.raises(SecurityContractError) as exc_info:
        adapter.encode(WORKSPACE_ID, invalid_name)  # type: ignore[arg-type]

    assert type(exc_info.value) is SecurityContractError
    assert repr(invalid_name) not in str(exc_info.value)


def test_invalid_utf8_payload_failure_does_not_expose_payload() -> None:
    adapter = InsecureDevelopmentOnlyWorkspaceNamePersistence()
    invalid_payload = b"\xffsynthetic-private-value"
    encoded = adapter.restore_payload(WORKSPACE_ID, invalid_payload)

    with pytest.raises(SecurityContractError) as exc_info:
        adapter.decode(WORKSPACE_ID, encoded)

    assert type(exc_info.value) is SecurityContractError
    assert repr(invalid_payload) not in str(exc_info.value)
    assert "synthetic-private-value" not in str(exc_info.value)
