"""Orchestrate exact native-text extraction for one ingested PDF."""

from collections.abc import Callable
from datetime import datetime, timedelta

from lexlocal.application.ports.ingestion import IngestionResult
from lexlocal.application.ports.processing import (
    CancellationCheck,
    NativePdfExtractionError,
    NativePdfPage,
    NativePdfTextExtractor,
    PageExtractionMethod,
    ProcessedPage,
    ProcessedPageState,
    ProcessingCancelled,
    ProcessingError,
    ProcessingFailureKind,
    ProcessingGraph,
    ProcessingPageBatch,
    ProcessingPersistenceError,
    ProcessingResult,
    ProcessingSourceError,
    ProcessingTarget,
    ProcessingTerminalUpdate,
    UnusableNativeText,
)
from lexlocal.application.ports.security import ControlledSourceStorage
from lexlocal.application.ports.unit_of_work import UnitOfWork
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.domain.documents import DocumentVersionState
from lexlocal.domain.identifiers import DocumentPageId, SourceLocatorId
from lexlocal.domain.processing import ProcessingJob, ProcessingJobState
from lexlocal.domain.retrieval import SourceLocator, SourceLocatorKind


class ProcessNativePdfText:
    """Extract and stage exact native page text for the active workspace."""

    def __init__(
        self,
        active_scope: ActiveWorkspaceScope,
        controlled_storage: ControlledSourceStorage,
        extractor: NativePdfTextExtractor,
        cancellation: CancellationCheck,
        unit_of_work_factory: Callable[[], UnitOfWork],
        page_id_factory: Callable[[], DocumentPageId],
        source_locator_id_factory: Callable[[], SourceLocatorId],
        clock: Callable[[], datetime],
    ) -> None:
        self._active_scope = active_scope
        self._controlled_storage = controlled_storage
        self._extractor = extractor
        self._cancellation = cancellation
        self._unit_of_work_factory = unit_of_work_factory
        self._page_id_factory = page_id_factory
        self._source_locator_id_factory = source_locator_id_factory
        self._clock = clock

    def __call__(self, ingestion: IngestionResult) -> ProcessingResult:
        target = self._target(ingestion)

        try:
            self._checkpoint()
        except ProcessingCancelled:
            self._cancel_before_start(target)
            raise ProcessingCancelled("processing was cancelled") from None

        graph: ProcessingGraph | None = None
        started_job: ProcessingJob | None = None
        try:
            with self._unit_of_work_factory() as unit_of_work:
                graph = unit_of_work.processing.get_initial_graph(target)
                graph.validate_target(target)
                started_job = graph.job.transition_to(ProcessingJobState.PROCESSING)
                unit_of_work.processing.start(
                    target,
                    started_job,
                    self._utc_now(),
                )
                unit_of_work.commit()
        except Exception:
            if graph is not None and started_job is not None:
                self._record_terminal(
                    target,
                    graph,
                    started_job,
                    ProcessingFailureKind.PERSISTENCE,
                )
            raise ProcessingPersistenceError("processing could not be started") from None

        if graph is None or started_job is None:
            raise ProcessingPersistenceError("processing could not be started")

        try:
            self._checkpoint()
            source = self._read_source(target, ingestion)
            self._checkpoint()
            native_pages = self._extract_pages(source, target.expected_page_count)
            pages = self._build_pages(target, native_pages)
            self._checkpoint()
            batch = ProcessingPageBatch(target, pages, self._utc_now())
            with self._unit_of_work_factory() as unit_of_work:
                unit_of_work.processing.stage_pages(batch)
                self._checkpoint()
                unit_of_work.commit()
        except Exception as error:
            safe_error = self._safe_processing_error(error)
            self._record_terminal(
                target,
                graph,
                started_job,
                self._failure_kind(safe_error),
            )
            raise safe_error from None

        return ProcessingResult(
            document_id=target.document_id,
            document_version_id=target.document_version_id,
            processing_job_id=target.processing_job_id,
            pages=pages,
        )

    def _target(self, ingestion: IngestionResult) -> ProcessingTarget:
        try:
            workspace_id = self._active_scope.require_workspace_id()
            return ProcessingTarget.from_ingestion(workspace_id, ingestion)
        except ProcessingSourceError:
            raise
        except Exception:
            raise ProcessingSourceError("active processing source is unavailable") from None

    def _checkpoint(self) -> None:
        try:
            self._cancellation.raise_if_cancelled()
        except ProcessingCancelled:
            raise ProcessingCancelled("processing was cancelled") from None
        except Exception:
            raise ProcessingPersistenceError("cancellation check failed") from None

    def _read_source(
        self,
        target: ProcessingTarget,
        ingestion: IngestionResult,
    ) -> bytes:
        try:
            source = self._controlled_storage.read(
                target.workspace_id,
                ingestion.controlled_source,
            )
        except Exception:
            raise ProcessingSourceError("controlled source could not be read") from None
        if not isinstance(source, bytes) or not source:
            raise ProcessingSourceError("controlled source could not be read")
        return source

    def _extract_pages(
        self,
        source: bytes,
        expected_page_count: int,
    ) -> tuple[NativePdfPage, ...]:
        try:
            iterator = iter(self._extractor.extract(source))
        except Exception:
            raise NativePdfExtractionError("native PDF extraction failed") from None

        pages: list[NativePdfPage] = []
        while True:
            self._checkpoint()
            try:
                page = next(iterator)
            except StopIteration:
                break
            except Exception:
                raise NativePdfExtractionError("native PDF extraction failed") from None
            if not isinstance(page, NativePdfPage):
                raise NativePdfExtractionError("native PDF extraction result is invalid")
            expected_number = len(pages) + 1
            if page.page_number.value != expected_number:
                raise NativePdfExtractionError("native PDF page order is invalid")
            pages.append(page)

        if len(pages) != expected_page_count:
            raise NativePdfExtractionError("native PDF page count is invalid")
        if not any(self._has_usable_text(page.text) for page in pages):
            raise UnusableNativeText("PDF contains no usable native text")
        return tuple(pages)

    def _build_pages(
        self,
        target: ProcessingTarget,
        native_pages: tuple[NativePdfPage, ...],
    ) -> tuple[ProcessedPage, ...]:
        pages: list[ProcessedPage] = []
        try:
            for native_page in native_pages:
                page_id = self._page_id_factory()
                locator = SourceLocator(
                    id=self._source_locator_id_factory(),
                    workspace_id=target.workspace_id,
                    document_version_id=target.document_version_id,
                    page_id=page_id,
                    page_number=native_page.page_number,
                    kind=SourceLocatorKind.PAGE,
                )
                pages.append(
                    ProcessedPage(
                        id=page_id,
                        workspace_id=target.workspace_id,
                        document_version_id=target.document_version_id,
                        page_number=native_page.page_number,
                        text=native_page.text,
                        state=(
                            ProcessedPageState.READY
                            if self._has_usable_text(native_page.text)
                            else ProcessedPageState.WARNING
                        ),
                        extraction_method=PageExtractionMethod.NATIVE,
                        source_locator=locator,
                    )
                )
        except ProcessingError:
            raise
        except Exception:
            raise ProcessingPersistenceError(
                "processing identifier factory returned invalid data"
            ) from None
        return tuple(pages)

    @staticmethod
    def _has_usable_text(text: str) -> bool:
        return any(not character.isspace() for character in text)

    def _cancel_before_start(self, target: ProcessingTarget) -> None:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                graph = unit_of_work.processing.get_initial_graph(target)
                graph.validate_target(target)
                update = ProcessingTerminalUpdate(
                    target=target,
                    version=graph.version.transition_to(
                        DocumentVersionState.CANDIDATE_CANCELLED
                    ),
                    job=graph.job.transition_to(ProcessingJobState.CANCELLED),
                    failure_kind=ProcessingFailureKind.CANCELLED,
                    completed_at=self._utc_now(),
                )
                unit_of_work.processing.record_terminal(update)
                unit_of_work.commit()
        except Exception:
            raise ProcessingPersistenceError(
                "processing cancellation could not be recorded"
            ) from None

    def _record_terminal(
        self,
        target: ProcessingTarget,
        graph: ProcessingGraph,
        started_job: ProcessingJob,
        failure_kind: ProcessingFailureKind,
    ) -> None:
        is_cancelled = failure_kind is ProcessingFailureKind.CANCELLED
        try:
            update = ProcessingTerminalUpdate(
                target=target,
                version=graph.version.transition_to(
                    DocumentVersionState.CANDIDATE_CANCELLED
                    if is_cancelled
                    else DocumentVersionState.CANDIDATE_FAILED
                ),
                job=started_job.transition_to(
                    ProcessingJobState.CANCELLED
                    if is_cancelled
                    else ProcessingJobState.FAILED
                ),
                failure_kind=failure_kind,
                completed_at=self._utc_now(),
            )
            with self._unit_of_work_factory() as unit_of_work:
                unit_of_work.processing.record_terminal(update)
                unit_of_work.commit()
        except Exception:
            raise ProcessingPersistenceError(
                "processing terminal state could not be recorded"
            ) from None

    def _utc_now(self) -> datetime:
        try:
            value = self._clock()
        except Exception:
            raise ProcessingPersistenceError("processing clock failed") from None
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() != timedelta(0)
        ):
            raise ProcessingPersistenceError("processing clock returned invalid data")
        return value

    @staticmethod
    def _safe_processing_error(error: Exception) -> ProcessingError:
        if isinstance(error, ProcessingCancelled):
            return ProcessingCancelled("processing was cancelled")
        if isinstance(error, UnusableNativeText):
            return UnusableNativeText("PDF contains no usable native text")
        if isinstance(error, ProcessingSourceError):
            return ProcessingSourceError("controlled source could not be read")
        if isinstance(error, NativePdfExtractionError):
            return NativePdfExtractionError("native PDF extraction failed")
        if isinstance(error, ProcessingPersistenceError):
            return ProcessingPersistenceError("processing persistence failed")
        return ProcessingPersistenceError("processing persistence failed")

    @staticmethod
    def _failure_kind(error: ProcessingError) -> ProcessingFailureKind:
        if isinstance(error, ProcessingCancelled):
            return ProcessingFailureKind.CANCELLED
        if isinstance(error, UnusableNativeText):
            return ProcessingFailureKind.UNUSABLE_TEXT
        if isinstance(error, ProcessingSourceError):
            return ProcessingFailureKind.SOURCE
        if isinstance(error, NativePdfExtractionError):
            return ProcessingFailureKind.EXTRACTION
        return ProcessingFailureKind.PERSISTENCE
