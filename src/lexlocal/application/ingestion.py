"""Orchestrate one synthetic PDF registration in the active workspace."""

from collections.abc import Callable
from datetime import datetime, timedelta
from hashlib import sha256

from lexlocal.application.ports.ingestion import (
    DuplicateDocument,
    DuplicateFingerprint,
    IngestionError,
    IngestionPersistenceError,
    IngestionRegistration,
    IngestionResult,
    IngestionStorageError,
    InvalidPdfInput,
    PdfInspector,
    StoredBlobId,
)
from lexlocal.application.ports.security import (
    ControlledSourceRef,
    ControlledSourceStorage,
)
from lexlocal.application.ports.unit_of_work import UnitOfWork
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.domain.documents import DocumentVersion, LogicalDocument, VersionNumber
from lexlocal.domain.identifiers import (
    DocumentId,
    DocumentVersionId,
    ProcessingJobId,
    WorkspaceId,
)
from lexlocal.domain.processing import AttemptNumber, ProcessingJob


class ImportSyntheticPdf:
    """Validate, store, and atomically register one synthetic PDF."""

    def __init__(
        self,
        active_scope: ActiveWorkspaceScope,
        pdf_inspector: PdfInspector,
        duplicate_fingerprint: DuplicateFingerprint,
        controlled_storage: ControlledSourceStorage,
        unit_of_work_factory: Callable[[], UnitOfWork],
        document_id_factory: Callable[[], DocumentId],
        document_version_id_factory: Callable[[], DocumentVersionId],
        processing_job_id_factory: Callable[[], ProcessingJobId],
        stored_blob_id_factory: Callable[[], StoredBlobId],
        clock: Callable[[], datetime],
    ) -> None:
        self._active_scope = active_scope
        self._pdf_inspector = pdf_inspector
        self._duplicate_fingerprint = duplicate_fingerprint
        self._controlled_storage = controlled_storage
        self._unit_of_work_factory = unit_of_work_factory
        self._document_id_factory = document_id_factory
        self._document_version_id_factory = document_version_id_factory
        self._processing_job_id_factory = processing_job_id_factory
        self._stored_blob_id_factory = stored_blob_id_factory
        self._clock = clock

    def __call__(self, source: bytes, logical_filename: str) -> IngestionResult:
        workspace_id = self._active_scope.require_workspace_id()
        self._validate_input(source, logical_filename)
        pdf = self._pdf_inspector.inspect(source)
        digest = sha256(source).digest()
        try:
            fingerprint = self._duplicate_fingerprint.fingerprint(
                workspace_id,
                digest,
            )
        except IngestionError:
            raise
        except Exception:
            raise IngestionPersistenceError(
                "duplicate fingerprint calculation failed"
            ) from None

        document = LogicalDocument(
            id=self._document_id_factory(),
            workspace_id=workspace_id,
        )
        version = DocumentVersion(
            id=self._document_version_id_factory(),
            workspace_id=workspace_id,
            document_id=document.id,
            version_number=VersionNumber(1),
        )
        job = ProcessingJob(
            id=self._processing_job_id_factory(),
            workspace_id=workspace_id,
            document_version_id=version.id,
            attempt_number=AttemptNumber(1),
        )
        stored_blob_id = self._stored_blob_id_factory()
        timestamp = self._clock()
        self._validate_generated_values(stored_blob_id, timestamp)
        version.validate_document(document)
        job.validate_document_version(version)

        reference = self._store(workspace_id, source)
        registration = IngestionRegistration(
            stored_blob_id=stored_blob_id,
            controlled_source=reference,
            document=document,
            version=version,
            job=job,
            logical_filename=logical_filename,
            pdf=pdf,
            byte_size=len(source),
            duplicate_fingerprint=fingerprint,
            created_at=timestamp,
        )

        try:
            with self._unit_of_work_factory() as unit_of_work:
                unit_of_work.ingestion.register(registration)
                unit_of_work.commit()
        except Exception as error:
            primary = self._safe_registration_failure(error)
            self._compensate(workspace_id, reference, primary)
            raise primary from None

        return IngestionResult(
            document_id=document.id,
            document_version_id=version.id,
            processing_job_id=job.id,
            controlled_source=reference,
            pdf=pdf,
        )

    @staticmethod
    def _validate_input(source: object, logical_filename: object) -> None:
        if not isinstance(source, bytes) or not source:
            raise InvalidPdfInput("source must be non-empty bytes")
        if not isinstance(logical_filename, str) or not logical_filename.strip():
            raise InvalidPdfInput("logical filename must not be empty")

    @staticmethod
    def _validate_generated_values(
        stored_blob_id: object,
        timestamp: object,
    ) -> None:
        if not isinstance(stored_blob_id, StoredBlobId):
            raise IngestionPersistenceError("stored blob id factory returned invalid data")
        if (
            not isinstance(timestamp, datetime)
            or timestamp.tzinfo is None
            or timestamp.utcoffset() != timedelta(0)
        ):
            raise IngestionPersistenceError("ingestion clock must return UTC")

    def _store(
        self,
        workspace_id: WorkspaceId,
        source: bytes,
    ) -> ControlledSourceRef:
        try:
            reference = self._controlled_storage.store(workspace_id, source)
        except Exception:
            raise IngestionStorageError("controlled source storage failed") from None
        if (
            not isinstance(reference, ControlledSourceRef)
            or reference.workspace_id != workspace_id
        ):
            raise IngestionStorageError("controlled source storage returned invalid data")
        return reference

    @staticmethod
    def _safe_registration_failure(error: Exception) -> IngestionError:
        if isinstance(error, DuplicateDocument):
            return DuplicateDocument(
                "document is already registered in the active workspace"
            )
        if isinstance(error, IngestionPersistenceError):
            return IngestionPersistenceError("ingestion registration failed")
        return IngestionPersistenceError("ingestion registration failed")

    def _compensate(
        self,
        workspace_id: WorkspaceId,
        reference: ControlledSourceRef,
        primary: IngestionError,
    ) -> None:
        try:
            self._controlled_storage.delete(workspace_id, reference)
        except Exception:
            raise IngestionStorageError(
                "controlled source compensation failed",
                primary_failure=primary,
            ) from None
