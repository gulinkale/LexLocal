"""Define SDK-free Application contracts for synthetic PDF ingestion."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from lexlocal.application.ports.security import ControlledSourceRef
from lexlocal.domain.documents import DocumentVersion, LogicalDocument
from lexlocal.domain.identifiers import (
    DocumentId,
    DocumentVersionId,
    ProcessingJobId,
    WorkspaceId,
)
from lexlocal.domain.processing import ProcessingJob


class IngestionError(Exception):
    """Base exception for sanitized ingestion failures."""


class InvalidPdfInput(IngestionError):
    """Report invalid caller input before PDF inspection or persistence."""


class UnsupportedPdf(IngestionError):
    """Report a non-PDF or unsupported PDF document."""


class UnreadablePdf(IngestionError):
    """Report a corrupt or unreadable PDF document."""


class ProtectedPdf(IngestionError):
    """Report a password-protected or encrypted PDF document."""


class DuplicateDocument(IngestionError):
    """Report a live duplicate in the selected workspace."""


class IngestionStorageError(IngestionError):
    """Report a sanitized controlled-storage or compensation failure."""

    def __init__(
        self,
        message: str,
        *,
        primary_failure: IngestionError | None = None,
    ) -> None:
        super().__init__(message)
        self.primary_failure = primary_failure


class IngestionPersistenceError(IngestionError):
    """Report a sanitized ingestion persistence failure."""


@dataclass(frozen=True, slots=True)
class StoredBlobId:
    """Identify stored-blob persistence metadata independently from storage."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value:
            raise IngestionPersistenceError("stored blob id is invalid")
        try:
            canonical = str(UUID(self.value))
        except ValueError:
            raise IngestionPersistenceError("stored blob id is invalid") from None
        object.__setattr__(self, "value", canonical)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class PdfInspectionResult:
    """Expose safe PDF container metadata without Qt types."""

    mime_type: str
    page_count: int

    def __post_init__(self) -> None:
        if self.mime_type != "application/pdf":
            raise UnsupportedPdf("PDF type is unsupported")
        if (
            isinstance(self.page_count, bool)
            or not isinstance(self.page_count, int)
            or self.page_count < 0
        ):
            raise UnreadablePdf("PDF metadata is invalid")


class PdfInspector(Protocol):
    """Validate PDF container support and return safe metadata."""

    def inspect(self, source: bytes) -> PdfInspectionResult:
        """Inspect exact source bytes without extracting page text."""

        ...


class DuplicateFingerprint(Protocol):
    """Derive workspace-scoped equality material from a source digest."""

    def fingerprint(
        self,
        workspace_id: WorkspaceId,
        source_sha256: bytes,
    ) -> bytes:
        """Return deterministic equality material for one workspace."""

        ...


@dataclass(frozen=True, slots=True)
class IngestionRegistration:
    """Describe the complete atomic database registration operation."""

    stored_blob_id: StoredBlobId
    controlled_source: ControlledSourceRef = field(repr=False)
    document: LogicalDocument
    version: DocumentVersion
    job: ProcessingJob
    logical_filename: str = field(repr=False)
    pdf: PdfInspectionResult
    byte_size: int
    duplicate_fingerprint: bytes = field(repr=False)
    created_at: datetime
    job_stage: str = "VALIDATING"

    def __post_init__(self) -> None:
        if not isinstance(self.stored_blob_id, StoredBlobId):
            raise IngestionPersistenceError("stored blob id is invalid")
        if not isinstance(self.controlled_source, ControlledSourceRef):
            raise IngestionPersistenceError("controlled source reference is invalid")
        if not isinstance(self.document, LogicalDocument):
            raise IngestionPersistenceError("logical document is invalid")
        if not isinstance(self.version, DocumentVersion):
            raise IngestionPersistenceError("document version is invalid")
        if not isinstance(self.job, ProcessingJob):
            raise IngestionPersistenceError("processing job is invalid")
        if not isinstance(self.logical_filename, str) or not self.logical_filename.strip():
            raise InvalidPdfInput("logical filename must not be empty")
        if not isinstance(self.pdf, PdfInspectionResult):
            raise IngestionPersistenceError("PDF metadata is invalid")
        if (
            isinstance(self.byte_size, bool)
            or not isinstance(self.byte_size, int)
            or self.byte_size < 1
        ):
            raise IngestionPersistenceError("source byte size is invalid")
        if (
            not isinstance(self.duplicate_fingerprint, bytes)
            or len(self.duplicate_fingerprint) != 32
        ):
            raise IngestionPersistenceError("duplicate fingerprint is invalid")
        if (
            not isinstance(self.created_at, datetime)
            or self.created_at.tzinfo is None
            or self.created_at.utcoffset() != timedelta(0)
        ):
            raise IngestionPersistenceError("ingestion timestamp must be UTC")
        if self.job_stage != "VALIDATING":
            raise IngestionPersistenceError("processing job stage is invalid")

        if self.controlled_source.workspace_id != self.document.workspace_id:
            raise IngestionPersistenceError("ingestion workspace relationships are invalid")
        self.version.validate_document(self.document)
        self.job.validate_document_version(self.version)


class IngestionRepository(Protocol):
    """Register one stored source and its initial document graph atomically."""

    def register(self, registration: IngestionRegistration) -> None:
        """Stage the complete ingestion registration in the active transaction."""

        ...


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Return safe identifiers and PDF metadata after committed registration."""

    document_id: DocumentId
    document_version_id: DocumentVersionId
    processing_job_id: ProcessingJobId
    controlled_source: ControlledSourceRef
    pdf: PdfInspectionResult
