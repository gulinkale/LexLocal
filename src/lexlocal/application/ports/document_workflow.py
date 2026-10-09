"""Define path-private Application contracts for one M1 document workflow."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from lexlocal.domain.identifiers import (
    DocumentId,
    DocumentVersionId,
    ProcessingJobId,
    WorkspaceId,
)
from lexlocal.domain.processing import IndexGeneration, IndexGenerationState


class DocumentWorkflowDisposition(StrEnum):
    """Describe whether this attempt durably registered an incomplete document."""

    NOT_REGISTERED = "NOT_REGISTERED"
    REGISTERED_INCOMPLETE = "REGISTERED_INCOMPLETE"


class DocumentWorkflowError(Exception):
    """Base exception for sanitized document-workflow failures."""

    def __init__(
        self,
        message: str,
        *,
        disposition: DocumentWorkflowDisposition = (
            DocumentWorkflowDisposition.NOT_REGISTERED
        ),
    ) -> None:
        if not isinstance(disposition, DocumentWorkflowDisposition):
            raise ValueError("document workflow disposition is invalid")
        super().__init__(message)
        self.disposition = disposition


class InvalidSelectedPdf(DocumentWorkflowError):
    """Report an invalid selected-file or reader result contract."""


class SelectedPdfReadError(DocumentWorkflowError):
    """Report a sanitized external-file read failure."""


class DocumentWorkflowUnavailable(DocumentWorkflowError):
    """Report that the active document workflow cannot start."""


class DocumentWorkflowProgressError(DocumentWorkflowError):
    """Report that the injected progress boundary failed."""


class DocumentImportFailure(DocumentWorkflowError):
    """Report a sanitized ingestion-stage failure."""


class DocumentDuplicate(DocumentImportFailure):
    """Report the existing same-workspace duplicate outcome."""


class DocumentProcessingFailure(DocumentWorkflowError):
    """Report a sanitized native-processing-stage failure."""


class DocumentUnusableNativeText(DocumentProcessingFailure):
    """Report that M1 found no usable native text and cannot use OCR."""


class DocumentIndexingFailure(DocumentWorkflowError):
    """Report a sanitized indexing-stage failure."""


class DocumentEmbeddingFailure(DocumentWorkflowError):
    """Report a sanitized embedding/finalization-stage failure."""


class DocumentWorkflowCancelled(DocumentWorkflowError):
    """Report cooperative cancellation before a safe workflow result exists."""


class DocumentWorkflowStage(StrEnum):
    """Expose truthful coarse phases without fabricating numeric progress."""

    IMPORTING = "IMPORTING"
    EXTRACTING = "EXTRACTING"
    INDEXING = "INDEXING"
    EMBEDDING = "EMBEDDING"


class ActiveDocumentReadiness(StrEnum):
    """Expose the two approved terminal document readiness states."""

    READY = "READY"
    READY_WITH_WARNINGS = "READY_WITH_WARNINGS"


@dataclass(frozen=True, slots=True)
class SelectedPdfReference:
    """Carry one selected physical location without exposing it through repr."""

    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value:
            raise InvalidSelectedPdf("selected PDF reference is invalid")


@dataclass(frozen=True, slots=True)
class SelectedPdfSource:
    """Return exact source bytes and a path-free logical filename."""

    source: bytes = field(repr=False)
    logical_filename: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.source, bytes) or not self.source:
            raise InvalidSelectedPdf("selected PDF source is invalid")
        _require_logical_filename(self.logical_filename)


class SelectedPdfReader(Protocol):
    """Read one explicitly selected regular file outside Presentation."""

    def read(self, selected: SelectedPdfReference) -> SelectedPdfSource:
        """Return exact bytes and basename without persisting or exposing the path."""

        ...


class DocumentWorkflowCancellationCheck(Protocol):
    """Raise when cooperative cancellation has been requested."""

    def raise_if_cancelled(self) -> None:
        """Raise DocumentWorkflowCancelled when cancellation is requested."""

        ...


class DocumentWorkflowStageSink(Protocol):
    """Receive fixed workflow phases without a Qt dependency."""

    def __call__(self, stage: DocumentWorkflowStage) -> None:
        """Publish one phase before its owning operation starts."""

        ...


@dataclass(frozen=True, slots=True)
class ActiveDocumentResult:
    """Expose one exact active document/index without source or page payloads."""

    workspace_id: WorkspaceId
    document_id: DocumentId
    document_version_id: DocumentVersionId
    processing_job_id: ProcessingJobId
    logical_filename: str = field(repr=False)
    page_count: int
    readiness: ActiveDocumentReadiness
    active_generation: IndexGeneration

    def __post_init__(self) -> None:
        if (
            not isinstance(self.workspace_id, WorkspaceId)
            or not isinstance(self.document_id, DocumentId)
            or not isinstance(self.document_version_id, DocumentVersionId)
            or not isinstance(self.processing_job_id, ProcessingJobId)
        ):
            raise DocumentIndexingFailure("active document identity is invalid")
        _require_logical_filename(self.logical_filename)
        if (
            isinstance(self.page_count, bool)
            or not isinstance(self.page_count, int)
            or self.page_count < 1
        ):
            raise DocumentProcessingFailure("active document page count is invalid")
        if not isinstance(self.readiness, ActiveDocumentReadiness):
            raise DocumentIndexingFailure("active document readiness is invalid")
        if (
            not isinstance(self.active_generation, IndexGeneration)
            or self.active_generation.state is not IndexGenerationState.ACTIVE
            or self.active_generation.workspace_id != self.workspace_id
            or self.active_generation.document_version_id != self.document_version_id
            or self.active_generation.processing_job_id != self.processing_job_id
        ):
            raise DocumentIndexingFailure("active document generation is invalid")


def _require_logical_filename(value: object) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise InvalidSelectedPdf("selected PDF filename is invalid")
