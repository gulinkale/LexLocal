"""Define SDK-free Application contracts for native PDF processing."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from lexlocal.application.ports.ingestion import IngestionResult
from lexlocal.domain.documents import DocumentVersion, DocumentVersionState
from lexlocal.domain.identifiers import (
    DocumentId,
    DocumentPageId,
    DocumentVersionId,
    ProcessingJobId,
    WorkspaceId,
)
from lexlocal.domain.processing import ProcessingJob, ProcessingJobState
from lexlocal.domain.retrieval import PageNumber, SourceLocator, SourceLocatorKind


class ProcessingError(Exception):
    """Base exception for sanitized processing failures."""


class ProcessingSourceError(ProcessingError):
    """Report a controlled-source or source-ownership failure."""


class NativePdfExtractionError(ProcessingError):
    """Report a native PDF extraction or result-contract failure."""


class UnusableNativeText(ProcessingError):
    """Report that no page contains usable native text in M1."""


class ProcessingCancelled(ProcessingError):
    """Report cooperative processing cancellation."""


class ProcessingPersistenceError(ProcessingError):
    """Report a sanitized processing persistence failure."""


class PageExtractionMethod(StrEnum):
    """Identify how exact page text was extracted."""

    NATIVE = "NATIVE"


class ProcessedPageState(StrEnum):
    """Describe whether an extracted page has usable native text."""

    READY = "READY"
    WARNING = "WARNING"


class ProcessingFailureKind(StrEnum):
    """Provide fixed, non-sensitive terminal failure classifications."""

    SOURCE = "SOURCE"
    EXTRACTION = "EXTRACTION"
    UNUSABLE_TEXT = "UNUSABLE_TEXT"
    PERSISTENCE = "PERSISTENCE"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class NativePdfPage:
    """Carry exact text for one one-based page from a native extractor."""

    page_number: PageNumber
    text: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.page_number, PageNumber):
            raise NativePdfExtractionError("native page number is invalid")
        if not isinstance(self.text, str):
            raise NativePdfExtractionError("native page text is invalid")


class NativePdfTextExtractor(Protocol):
    """Extract exact native text without exposing PDF SDK types."""

    def extract(self, source: bytes) -> Iterable[NativePdfPage]:
        """Yield exact page text in one-based source order."""

        ...


class CancellationCheck(Protocol):
    """Raise when cooperative cancellation has been requested."""

    def raise_if_cancelled(self) -> None:
        """Raise ProcessingCancelled when cancellation is requested."""

        ...


@dataclass(frozen=True, slots=True)
class ProcessingTarget:
    """Identify the exact committed ingestion graph to process."""

    workspace_id: WorkspaceId
    document_id: DocumentId
    document_version_id: DocumentVersionId
    processing_job_id: ProcessingJobId
    expected_page_count: int

    @classmethod
    def from_ingestion(
        cls,
        workspace_id: WorkspaceId,
        ingestion: IngestionResult,
    ) -> "ProcessingTarget":
        if not isinstance(workspace_id, WorkspaceId):
            raise ProcessingSourceError("processing workspace is invalid")
        if not isinstance(ingestion, IngestionResult):
            raise ProcessingSourceError("ingestion result is invalid")
        if ingestion.controlled_source.workspace_id != workspace_id:
            raise ProcessingSourceError("controlled source belongs to another workspace")
        return cls(
            workspace_id=workspace_id,
            document_id=ingestion.document_id,
            document_version_id=ingestion.document_version_id,
            processing_job_id=ingestion.processing_job_id,
            expected_page_count=ingestion.pdf.page_count,
        )

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_id, WorkspaceId):
            raise ProcessingPersistenceError("processing target is invalid")
        if not isinstance(self.document_id, DocumentId):
            raise ProcessingPersistenceError("processing target is invalid")
        if not isinstance(self.document_version_id, DocumentVersionId):
            raise ProcessingPersistenceError("processing target is invalid")
        if not isinstance(self.processing_job_id, ProcessingJobId):
            raise ProcessingPersistenceError("processing target is invalid")
        if (
            isinstance(self.expected_page_count, bool)
            or not isinstance(self.expected_page_count, int)
            or self.expected_page_count < 0
        ):
            raise ProcessingPersistenceError("processing page count is invalid")


@dataclass(frozen=True, slots=True)
class ProcessingGraph:
    """Expose the strictly reconstructed initial graph for Domain transitions."""

    version: DocumentVersion
    job: ProcessingJob
    page_count: int

    def validate_target(self, target: ProcessingTarget) -> None:
        if not isinstance(target, ProcessingTarget):
            raise ProcessingPersistenceError("processing target is invalid")
        if not isinstance(self.version, DocumentVersion) or not isinstance(
            self.job, ProcessingJob
        ):
            raise ProcessingPersistenceError("processing graph is invalid")
        if (
            self.version.workspace_id != target.workspace_id
            or self.version.document_id != target.document_id
            or self.version.id != target.document_version_id
            or self.job.workspace_id != target.workspace_id
            or self.job.id != target.processing_job_id
            or self.job.document_version_id != target.document_version_id
        ):
            raise ProcessingPersistenceError("processing graph relationships are invalid")
        if (
            self.version.state is not DocumentVersionState.CANDIDATE_PROCESSING
            or self.job.state is not ProcessingJobState.QUEUED
            or isinstance(self.page_count, bool)
            or not isinstance(self.page_count, int)
            or self.page_count != target.expected_page_count
        ):
            raise ProcessingPersistenceError("processing graph state is invalid")
        try:
            self.job.validate_document_version(self.version)
        except Exception:
            raise ProcessingPersistenceError(
                "processing graph relationships are invalid"
            ) from None


@dataclass(frozen=True, slots=True)
class ProcessedPage:
    """Preserve exact page text and provenance for persistence and chunking."""

    id: DocumentPageId
    workspace_id: WorkspaceId
    document_version_id: DocumentVersionId
    page_number: PageNumber
    text: str = field(repr=False)
    state: ProcessedPageState
    extraction_method: PageExtractionMethod
    source_locator: SourceLocator

    def __post_init__(self) -> None:
        if not isinstance(self.id, DocumentPageId):
            raise ProcessingPersistenceError("processed page is invalid")
        if not isinstance(self.workspace_id, WorkspaceId):
            raise ProcessingPersistenceError("processed page is invalid")
        if not isinstance(self.document_version_id, DocumentVersionId):
            raise ProcessingPersistenceError("processed page is invalid")
        if not isinstance(self.page_number, PageNumber):
            raise ProcessingPersistenceError("processed page is invalid")
        if not isinstance(self.text, str):
            raise ProcessingPersistenceError("processed page is invalid")
        if not isinstance(self.state, ProcessedPageState):
            raise ProcessingPersistenceError("processed page is invalid")
        if not isinstance(self.extraction_method, PageExtractionMethod):
            raise ProcessingPersistenceError("processed page is invalid")
        if not isinstance(self.source_locator, SourceLocator):
            raise ProcessingPersistenceError("processed page is invalid")
        expected_state = (
            ProcessedPageState.READY
            if any(not character.isspace() for character in self.text)
            else ProcessedPageState.WARNING
        )
        if self.state is not expected_state:
            raise ProcessingPersistenceError("processed page state is invalid")
        if (
            self.source_locator.workspace_id != self.workspace_id
            or self.source_locator.document_version_id != self.document_version_id
            or self.source_locator.page_id != self.id
            or self.source_locator.page_number != self.page_number
            or self.source_locator.kind is not SourceLocatorKind.PAGE
        ):
            raise ProcessingPersistenceError("processed page relationships are invalid")


@dataclass(frozen=True, slots=True)
class ProcessingPageBatch:
    """Describe one complete atomic page/locator staging operation."""

    target: ProcessingTarget
    pages: tuple[ProcessedPage, ...]
    updated_at: datetime
    next_stage: str = "CHUNKING"

    def __post_init__(self) -> None:
        if not isinstance(self.target, ProcessingTarget):
            raise ProcessingPersistenceError("processing page batch is invalid")
        if not isinstance(self.pages, tuple) or not all(
            isinstance(page, ProcessedPage) for page in self.pages
        ):
            raise ProcessingPersistenceError("processing page batch is invalid")
        if len(self.pages) != self.target.expected_page_count:
            raise ProcessingPersistenceError("processing page batch is incomplete")
        if tuple(page.page_number.value for page in self.pages) != tuple(
            range(1, self.target.expected_page_count + 1)
        ):
            raise ProcessingPersistenceError("processing page order is invalid")
        if len({page.id for page in self.pages}) != len(self.pages) or len(
            {page.source_locator.id for page in self.pages}
        ) != len(self.pages):
            raise ProcessingPersistenceError("processing page identities are invalid")
        if any(
            page.workspace_id != self.target.workspace_id
            or page.document_version_id != self.target.document_version_id
            for page in self.pages
        ):
            raise ProcessingPersistenceError("processing page relationships are invalid")
        _require_utc(self.updated_at)
        if self.next_stage != "CHUNKING":
            raise ProcessingPersistenceError("processing handoff stage is invalid")


@dataclass(frozen=True, slots=True)
class ProcessingTerminalUpdate:
    """Describe a sanitized failure or cancellation state update."""

    target: ProcessingTarget
    version: DocumentVersion
    job: ProcessingJob
    failure_kind: ProcessingFailureKind
    completed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.target, ProcessingTarget):
            raise ProcessingPersistenceError("processing terminal update is invalid")
        if not isinstance(self.version, DocumentVersion) or not isinstance(
            self.job, ProcessingJob
        ):
            raise ProcessingPersistenceError("processing terminal update is invalid")
        if not isinstance(self.failure_kind, ProcessingFailureKind):
            raise ProcessingPersistenceError("processing terminal update is invalid")
        _require_utc(self.completed_at)
        is_cancelled = self.failure_kind is ProcessingFailureKind.CANCELLED
        expected_version_state = (
            DocumentVersionState.CANDIDATE_CANCELLED
            if is_cancelled
            else DocumentVersionState.CANDIDATE_FAILED
        )
        expected_job_state = (
            ProcessingJobState.CANCELLED
            if is_cancelled
            else ProcessingJobState.FAILED
        )
        if (
            self.version.workspace_id != self.target.workspace_id
            or self.version.document_id != self.target.document_id
            or self.version.id != self.target.document_version_id
            or self.job.workspace_id != self.target.workspace_id
            or self.job.id != self.target.processing_job_id
            or self.job.document_version_id != self.target.document_version_id
            or self.version.state is not expected_version_state
            or self.job.state is not expected_job_state
        ):
            raise ProcessingPersistenceError(
                "processing terminal relationships are invalid"
            )


class ProcessingRepository(Protocol):
    """Persist one native-processing attempt in the active transaction."""

    def get_initial_graph(self, target: ProcessingTarget) -> ProcessingGraph:
        """Load the exact queued ingestion graph for Domain validation."""

        ...

    def start(
        self,
        target: ProcessingTarget,
        job: ProcessingJob,
        started_at: datetime,
    ) -> None:
        """Stage the validated queued-to-processing transition."""

        ...

    def stage_pages(self, batch: ProcessingPageBatch) -> None:
        """Stage the complete page/locator set and CHUNKING handoff."""

        ...

    def record_terminal(self, update: ProcessingTerminalUpdate) -> None:
        """Stage one sanitized failure or cancellation transition."""

        ...

    def list_pages_for_chunking(
        self,
        workspace_id: WorkspaceId,
        document_version_id: DocumentVersionId,
    ) -> Sequence[ProcessedPage]:
        """Return exact ordered page/provenance values for INDEX-001."""

        ...


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    """Expose the exact successful native-text handoff."""

    document_id: DocumentId
    document_version_id: DocumentVersionId
    processing_job_id: ProcessingJobId
    pages: tuple[ProcessedPage, ...]
    job_state: ProcessingJobState = ProcessingJobState.PROCESSING
    stage: str = "CHUNKING"

    def __post_init__(self) -> None:
        if not isinstance(self.document_id, DocumentId):
            raise ProcessingPersistenceError("processing result is invalid")
        if not isinstance(self.document_version_id, DocumentVersionId):
            raise ProcessingPersistenceError("processing result is invalid")
        if not isinstance(self.processing_job_id, ProcessingJobId):
            raise ProcessingPersistenceError("processing result is invalid")
        if not isinstance(self.pages, tuple) or not all(
            isinstance(page, ProcessedPage) for page in self.pages
        ):
            raise ProcessingPersistenceError("processing result is invalid")
        if any(
            page.document_version_id != self.document_version_id for page in self.pages
        ) or tuple(page.page_number.value for page in self.pages) != tuple(
            range(1, len(self.pages) + 1)
        ):
            raise ProcessingPersistenceError("processing result relationships are invalid")
        if self.job_state is not ProcessingJobState.PROCESSING or self.stage != "CHUNKING":
            raise ProcessingPersistenceError("processing result state is invalid")


def _require_utc(value: object) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != timedelta(0)
    ):
        raise ProcessingPersistenceError("processing timestamp must be UTC")
