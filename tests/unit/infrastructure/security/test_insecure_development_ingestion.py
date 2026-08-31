"""Tests for the synthetic-only ingestion duplicate token adapter."""

from hashlib import sha256

import pytest

from lexlocal.application.ports.ingestion import (
    DuplicateFingerprint,
    IngestionPersistenceError,
)
from lexlocal.domain.identifiers import WorkspaceId
from lexlocal.infrastructure.security import insecure_development_ingestion
from lexlocal.infrastructure.security.insecure_development_ingestion import (
    InsecureDevelopmentOnlyDuplicateFingerprint,
)

WORKSPACE_ID = WorkspaceId("550e8400-e29b-41d4-a716-446655440000")
OTHER_WORKSPACE_ID = WorkspaceId("123e4567-e89b-12d3-a456-426614174000")
DIGEST = sha256(b"anonymous synthetic PDF bytes").digest()
OTHER_DIGEST = sha256(b"different anonymous synthetic PDF bytes").digest()
PREFIX = b"lexlocal/insecure-development-only/document-duplicate/v1\x00"
REQUIRED_RISK_LABELS = (
    "DEVELOPMENT ONLY",
    "SYNTHETIC FIXTURES ONLY",
    "NOT RELEASE SAFE",
    "NOT FOR REAL USER DOCUMENTS",
)


_CONFORMANCE: DuplicateFingerprint = InsecureDevelopmentOnlyDuplicateFingerprint()


def test_exact_domain_separated_token_is_deterministic() -> None:
    adapter = InsecureDevelopmentOnlyDuplicateFingerprint()
    expected = sha256(
        PREFIX + str(WORKSPACE_ID).encode("utf-8") + b"\x00" + DIGEST
    ).digest()

    first = adapter.fingerprint(WORKSPACE_ID, DIGEST)
    second = adapter.fingerprint(WORKSPACE_ID, DIGEST)

    assert first == second == expected
    assert type(first) is bytes
    assert len(first) == 32


def test_workspace_and_source_digest_both_change_token() -> None:
    adapter = InsecureDevelopmentOnlyDuplicateFingerprint()

    original = adapter.fingerprint(WORKSPACE_ID, DIGEST)
    other_workspace = adapter.fingerprint(OTHER_WORKSPACE_ID, DIGEST)
    other_source = adapter.fingerprint(WORKSPACE_ID, OTHER_DIGEST)

    assert len({original, other_workspace, other_source}) == 3


@pytest.mark.parametrize("invalid_digest", [b"", b"short", b"x" * 31, b"x" * 33])
def test_invalid_digest_is_rejected_without_content_leak(invalid_digest: bytes) -> None:
    with pytest.raises(
        IngestionPersistenceError,
        match="source digest is invalid",
    ) as captured:
        InsecureDevelopmentOnlyDuplicateFingerprint().fingerprint(
            WORKSPACE_ID,
            invalid_digest,
        )

    assert captured.value.__cause__ is None
    assert repr(invalid_digest) not in str(captured.value)


@pytest.mark.parametrize(
    "documented_object",
    [
        insecure_development_ingestion,
        InsecureDevelopmentOnlyDuplicateFingerprint,
    ],
)
def test_adapter_has_all_required_risk_labels(documented_object: object) -> None:
    documentation = documented_object.__doc__

    assert documentation is not None
    assert all(label in documentation for label in REQUIRED_RISK_LABELS)


def test_documentation_makes_no_release_security_claim() -> None:
    documentation = " ".join(
        (
            insecure_development_ingestion.__doc__ or "",
            InsecureDevelopmentOnlyDuplicateFingerprint.__doc__ or "",
        )
    ).lower()

    assert "hmac" not in documentation
    assert "encryption" not in documentation
    assert "keyed" not in documentation
    assert "confidentiality" not in documentation
    assert "production-safe" not in documentation
