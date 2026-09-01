"""Compose the synthetic PDF ingestion vertical slice at Bootstrap."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from lexlocal.application.ingestion import ImportSyntheticPdf
from lexlocal.application.ports.ingestion import (
    DuplicateFingerprint,
    PdfInspector,
    StoredBlobId,
)
from lexlocal.application.ports.security import (
    ControlledSourceStorage,
    SensitivePayloadCodec,
)
from lexlocal.application.ports.unit_of_work import UnitOfWork
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.bootstrap.security import create_security_providers
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import (
    DocumentId,
    DocumentVersionId,
    ProcessingJobId,
)
from lexlocal.infrastructure.pdf.qt_pdf import QtPdfInspector
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.persistence.sqlite_unit_of_work import SQLiteUnitOfWork
from lexlocal.infrastructure.security.insecure_development_ingestion import (
    InsecureDevelopmentOnlyDuplicateFingerprint,
)
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
)


@dataclass(frozen=True, slots=True)
class IngestionApplicationComposition:
    """Expose ingestion and its shared Application-owned security boundaries."""

    import_pdf: ImportSyntheticPdf
    controlled_source_storage: ControlledSourceStorage
    sensitive_payload_codec: SensitivePayloadCodec


def compose_ingestion_application(
    settings: AppSettings,
    connection_factory: SQLiteConnectionFactory,
    active_scope: ActiveWorkspaceScope,
    *,
    pdf_inspector: PdfInspector | None = None,
    duplicate_fingerprint: DuplicateFingerprint | None = None,
    controlled_source_storage: ControlledSourceStorage | None = None,
    document_id_factory: Callable[[], DocumentId] | None = None,
    document_version_id_factory: Callable[[], DocumentVersionId] | None = None,
    processing_job_id_factory: Callable[[], ProcessingJobId] | None = None,
    stored_blob_id_factory: Callable[[], StoredBlobId] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> IngestionApplicationComposition:
    """Wire approved development/test ingestion dependencies after security checks."""

    security = create_security_providers(settings)
    storage = (
        security.controlled_source_storage
        if controlled_source_storage is None
        else controlled_source_storage
    )
    name_persistence = InsecureDevelopmentOnlyWorkspaceNamePersistence()

    def unit_of_work_factory() -> UnitOfWork:
        return SQLiteUnitOfWork(connection_factory, name_persistence)

    import_pdf = ImportSyntheticPdf(
        active_scope=active_scope,
        pdf_inspector=QtPdfInspector() if pdf_inspector is None else pdf_inspector,
        duplicate_fingerprint=(
            InsecureDevelopmentOnlyDuplicateFingerprint()
            if duplicate_fingerprint is None
            else duplicate_fingerprint
        ),
        controlled_storage=storage,
        unit_of_work_factory=unit_of_work_factory,
        document_id_factory=document_id_factory or _new_document_id,
        document_version_id_factory=(
            document_version_id_factory or _new_document_version_id
        ),
        processing_job_id_factory=(
            processing_job_id_factory or _new_processing_job_id
        ),
        stored_blob_id_factory=stored_blob_id_factory or _new_stored_blob_id,
        clock=clock or _utc_millisecond_clock,
    )
    return IngestionApplicationComposition(import_pdf, storage, security.payload_codec)


def _new_document_id() -> DocumentId:
    return DocumentId(str(uuid4()))


def _new_document_version_id() -> DocumentVersionId:
    return DocumentVersionId(str(uuid4()))


def _new_processing_job_id() -> ProcessingJobId:
    return ProcessingJobId(str(uuid4()))


def _new_stored_blob_id() -> StoredBlobId:
    return StoredBlobId(str(uuid4()))


def _utc_millisecond_clock() -> datetime:
    now = datetime.now(UTC)
    return now.replace(microsecond=(now.microsecond // 1_000) * 1_000)
