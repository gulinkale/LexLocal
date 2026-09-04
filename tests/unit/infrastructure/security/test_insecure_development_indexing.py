"""Tests for the synthetic development chunk equality token."""

from dataclasses import replace
from pathlib import Path

import lexlocal.infrastructure.security.insecure_development_indexing as module
from lexlocal.application.ports.indexing import (
    ChunkConfiguration,
    ChunkEqualityToken,
    LogicalChunk,
)
from lexlocal.application.ports.processing import PageExtractionMethod
from lexlocal.domain.identifiers import (
    DocumentPageId,
    DocumentVersionId,
    SourceLocatorId,
    WorkspaceId,
)
from lexlocal.domain.retrieval import PageNumber
from lexlocal.infrastructure.security.insecure_development_indexing import (
    InsecureDevelopmentOnlyChunkEqualityToken,
)


def _chunk() -> LogicalChunk:
    return LogicalChunk(
        WorkspaceId("10000000-0000-4000-8000-000000000001"),
        DocumentVersionId("20000000-0000-4000-8000-000000000001"),
        DocumentPageId("30000000-0000-4000-8000-000000000001"),
        PageNumber(1),
        SourceLocatorId("40000000-0000-4000-8000-000000000001"),
        0,
        0,
        0,
        4,
        "text",
        PageExtractionMethod.NATIVE,
        ChunkConfiguration(4, 1).profile,
    )


def test_token_is_deterministic_and_protocol_compatible() -> None:
    provider: ChunkEqualityToken = InsecureDevelopmentOnlyChunkEqualityToken()
    chunk = _chunk()

    assert provider.fingerprint(chunk) == provider.fingerprint(chunk)
    assert len(provider.fingerprint(chunk)) == 32


def test_every_canonical_identity_change_changes_the_token() -> None:
    provider = InsecureDevelopmentOnlyChunkEqualityToken()
    original = _chunk()
    changes = (
        {"workspace_id": WorkspaceId("10000000-0000-4000-8000-000000000002")},
        {"document_version_id": DocumentVersionId("20000000-0000-4000-8000-000000000002")},
        {"page_id": DocumentPageId("30000000-0000-4000-8000-000000000002")},
        {"source_locator_id": SourceLocatorId("40000000-0000-4000-8000-000000000002")},
        {"profile": ChunkConfiguration(5, 1).profile},
        {"source_start_offset": 1, "source_end_offset": 5},
        {"document_order": 1},
        {"page_order": 1},
        {"text": "next"},
    )

    assert all(
        provider.fingerprint(replace(original, **change)) != provider.fingerprint(original)
        for change in changes
    )


def test_required_risk_labels_are_visible() -> None:
    labels = (
        "DEVELOPMENT ONLY",
        "SYNTHETIC FIXTURES ONLY",
        "NOT RELEASE SAFE",
        "NOT FOR REAL USER DOCUMENTS",
    )

    assert all(label in (module.__doc__ or "") for label in labels)
    assert all(
        label in (InsecureDevelopmentOnlyChunkEqualityToken.__doc__ or "") for label in labels
    )
    assert "encryption" not in (module.__doc__ or "").lower()
    assert "confidential" not in (module.__doc__ or "").lower()
    assert Path(module.__file__).name == "insecure_development_indexing.py"
