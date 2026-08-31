"""Tests for Application-owned ingestion contracts."""

from datetime import UTC, datetime

import pytest

from lexlocal.application.ports.ingestion import (
    DuplicateFingerprint,
    IngestionPersistenceError,
    IngestionRegistration,
    IngestionRepository,
    PdfInspectionResult,
    PdfInspector,
    StoredBlobId,
)
from lexlocal.application.ports.security import ControlledSourceRef
from lexlocal.domain.documents import DocumentVersion, LogicalDocument, VersionNumber
from lexlocal.domain.identifiers import (
    DocumentId,
    DocumentVersionId,
    ProcessingJobId,
    WorkspaceId,
)
from lexlocal.domain.processing import AttemptNumber, ProcessingJob

WORKSPACE_ID = WorkspaceId("550e8400-e29b-41d4-a716-446655440000")
DOCUMENT_ID = DocumentId("123e4567-e89b-12d3-a456-426614174000")
VERSION_ID = DocumentVersionId("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
JOB_ID = ProcessingJobId("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
BLOB_ID = StoredBlobId("cccccccc-cccc-cccc-cccc-cccccccccccc")
NOW = datetime(2026, 8, 29, 9, 30, tzinfo=UTC)


class _PdfInspectorDouble:
    def inspect(self, source: bytes) -> PdfInspectionResult:
        assert source
        return PdfInspectionResult("application/pdf", 1)


class _FingerprintDouble:
    def fingerprint(self, workspace_id: WorkspaceId, source_sha256: bytes) -> bytes:
        assert workspace_id == WORKSPACE_ID
        assert len(source_sha256) == 32
        return b"f" * 32


class _RepositoryDouble:
    def register(self, registration: IngestionRegistration) -> None:
        self.registration = registration


_PDF_CONFORMANCE: PdfInspector = _PdfInspectorDouble()
_FINGERPRINT_CONFORMANCE: DuplicateFingerprint = _FingerprintDouble()
_REPOSITORY_CONFORMANCE: IngestionRepository = _RepositoryDouble()


def _registration() -> IngestionRegistration:
    document = LogicalDocument(DOCUMENT_ID, WORKSPACE_ID)
    version = DocumentVersion(VERSION_ID, WORKSPACE_ID, DOCUMENT_ID, VersionNumber(1))
    job = ProcessingJob(JOB_ID, WORKSPACE_ID, VERSION_ID, AttemptNumber(1))
    return IngestionRegistration(
        stored_blob_id=BLOB_ID,
        controlled_source=ControlledSourceRef(WORKSPACE_ID, "opaque-locator"),
        document=document,
        version=version,
        job=job,
        logical_filename="anonymous.pdf",
        pdf=PdfInspectionResult("application/pdf", 1),
        byte_size=20,
        duplicate_fingerprint=b"f" * 32,
        created_at=NOW,
    )


def test_protocol_doubles_conform_and_registration_preserves_exact_graph() -> None:
    registration = _registration()
    repository = _RepositoryDouble()

    repository.register(registration)

    assert repository.registration is registration
    assert registration.version.document_id == registration.document.id
    assert registration.job.document_version_id == registration.version.id
    assert registration.job_stage == "VALIDATING"


def test_stored_blob_id_is_canonical_and_distinct_from_controlled_reference() -> None:
    blob_id = StoredBlobId("CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC")
    reference = ControlledSourceRef(WORKSPACE_ID, str(blob_id))

    assert blob_id == BLOB_ID
    assert str(blob_id) == "cccccccc-cccc-cccc-cccc-cccccccccccc"
    assert blob_id != reference


@pytest.mark.parametrize("invalid_value", ["", "not-a-uuid"])
def test_stored_blob_id_rejects_invalid_values(invalid_value: str) -> None:
    with pytest.raises(IngestionPersistenceError, match="stored blob id is invalid"):
        StoredBlobId(invalid_value)


def test_registration_repr_hides_sensitive_registration_values() -> None:
    registration = _registration()

    representation = repr(registration)

    assert "anonymous.pdf" not in representation
    assert "opaque-locator" not in representation
    assert repr(b"f" * 32) not in representation
