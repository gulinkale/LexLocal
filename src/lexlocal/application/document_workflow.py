"""Coordinate the existing M1 document pipeline without owning its rules."""

from collections.abc import Callable

from lexlocal.application.ports.document_workflow import (
    ActiveDocumentReadiness,
    ActiveDocumentResult,
    DocumentDuplicate,
    DocumentEmbeddingFailure,
    DocumentImportFailure,
    DocumentIndexingFailure,
    DocumentProcessingFailure,
    DocumentUnusableNativeText,
    DocumentWorkflowCancellationCheck,
    DocumentWorkflowCancelled,
    DocumentWorkflowDisposition,
    DocumentWorkflowProgressError,
    DocumentWorkflowStage,
    DocumentWorkflowStageSink,
    DocumentWorkflowUnavailable,
    InvalidSelectedPdf,
    SelectedPdfReader,
    SelectedPdfReadError,
    SelectedPdfReference,
    SelectedPdfSource,
)
from lexlocal.application.ports.embeddings import (
    EmbeddingCancelled,
    EmbeddingError,
)
from lexlocal.application.ports.indexing import (
    ActivatedIndex,
    IndexingCancelled,
    IndexingError,
    IndexPreparationResult,
    ReusedActiveIndex,
    StagingEmbeddingHandoff,
)
from lexlocal.application.ports.ingestion import (
    DuplicateDocument,
    IngestionError,
    IngestionResult,
)
from lexlocal.application.ports.processing import (
    ProcessedPageState,
    ProcessingCancelled,
    ProcessingError,
    ProcessingResult,
    UnusableNativeText,
)
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.domain.identifiers import WorkspaceId
from lexlocal.domain.processing import IndexGeneration, ProcessingJobState


class BuildActiveDocument:
    """Turn one selected PDF into one active index through existing use cases."""

    def __init__(
        self,
        active_scope: ActiveWorkspaceScope,
        selected_pdf_reader: SelectedPdfReader,
        cancellation: DocumentWorkflowCancellationCheck,
        stage_sink: DocumentWorkflowStageSink,
        import_pdf: Callable[[bytes, str], IngestionResult],
        process_pdf: Callable[[IngestionResult], ProcessingResult],
        prepare_indexing: Callable[[ProcessingResult], IndexPreparationResult],
        embed_staging_chunks: Callable[[StagingEmbeddingHandoff], ActivatedIndex],
    ) -> None:
        self._active_scope = active_scope
        self._selected_pdf_reader = selected_pdf_reader
        self._cancellation = cancellation
        self._stage_sink = stage_sink
        self._import_pdf = import_pdf
        self._process_pdf = process_pdf
        self._prepare_indexing = prepare_indexing
        self._embed_staging_chunks = embed_staging_chunks

    def __call__(self, selected: SelectedPdfReference) -> ActiveDocumentResult:
        """Run the exact existing pipeline and return a path-free active result."""

        workspace_id = self._workspace_id()
        self._checkpoint()
        self._emit(DocumentWorkflowStage.IMPORTING)
        self._checkpoint()
        source = self._read(selected)
        self._checkpoint()
        ingestion = self._import(source)
        self._emit(
            DocumentWorkflowStage.EXTRACTING,
            disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
        )
        processing = self._process(ingestion, workspace_id)
        self._checkpoint(
            disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
        )
        self._emit(
            DocumentWorkflowStage.INDEXING,
            disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
        )
        self._checkpoint(
            disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
        )
        preparation = self._prepare(processing, workspace_id)

        if isinstance(preparation, ReusedActiveIndex):
            readiness = (
                ActiveDocumentReadiness.READY_WITH_WARNINGS
                if any(page.state is ProcessedPageState.WARNING for page in processing.pages)
                else ActiveDocumentReadiness.READY
            )
            return self._result(
                workspace_id,
                source,
                processing,
                preparation.persisted.generation,
                readiness,
            )

        self._emit(
            DocumentWorkflowStage.EMBEDDING,
            disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
        )
        self._checkpoint(
            disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
        )
        activated = self._embed(preparation, workspace_id, processing)
        readiness = (
            ActiveDocumentReadiness.READY_WITH_WARNINGS
            if activated.job.state is ProcessingJobState.READY_WITH_WARNINGS
            else ActiveDocumentReadiness.READY
        )
        return self._result(
            workspace_id,
            source,
            processing,
            activated.generation,
            readiness,
        )

    def _workspace_id(self) -> WorkspaceId:
        try:
            return self._active_scope.require_workspace_id()
        except Exception:
            raise DocumentWorkflowUnavailable(
                "active workspace is unavailable"
            ) from None

    def _checkpoint(
        self,
        *,
        disposition: DocumentWorkflowDisposition = (
            DocumentWorkflowDisposition.NOT_REGISTERED
        ),
    ) -> None:
        try:
            self._cancellation.raise_if_cancelled()
        except DocumentWorkflowCancelled:
            raise DocumentWorkflowCancelled(
                "document workflow was cancelled",
                disposition=disposition,
            ) from None
        except Exception:
            raise DocumentWorkflowUnavailable(
                "document workflow cancellation check failed",
                disposition=disposition,
            ) from None

    def _emit(
        self,
        stage: DocumentWorkflowStage,
        *,
        disposition: DocumentWorkflowDisposition = (
            DocumentWorkflowDisposition.NOT_REGISTERED
        ),
    ) -> None:
        try:
            self._stage_sink(stage)
        except Exception:
            raise DocumentWorkflowProgressError(
                "document workflow progress failed",
                disposition=disposition,
            ) from None

    def _read(self, selected: SelectedPdfReference) -> SelectedPdfSource:
        if not isinstance(selected, SelectedPdfReference):
            raise InvalidSelectedPdf("selected PDF reference is invalid")
        try:
            result = self._selected_pdf_reader.read(selected)
        except SelectedPdfReadError:
            raise SelectedPdfReadError("selected PDF could not be read") from None
        except Exception:
            raise SelectedPdfReadError("selected PDF could not be read") from None
        if not isinstance(result, SelectedPdfSource):
            raise SelectedPdfReadError("selected PDF reader returned invalid data")
        return result

    def _import(self, source: SelectedPdfSource) -> IngestionResult:
        try:
            result = self._import_pdf(source.source, source.logical_filename)
        except DuplicateDocument:
            raise DocumentDuplicate(
                "document is already registered in the active workspace"
            ) from None
        except IngestionError:
            raise DocumentImportFailure("document import failed") from None
        except Exception:
            raise DocumentImportFailure("document import failed") from None
        if not isinstance(result, IngestionResult):
            raise DocumentImportFailure("document import returned invalid data")
        return result

    def _process(
        self,
        ingestion: IngestionResult,
        workspace_id: WorkspaceId,
    ) -> ProcessingResult:
        try:
            result = self._process_pdf(ingestion)
        except ProcessingCancelled:
            raise DocumentWorkflowCancelled(
                "document workflow was cancelled",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            ) from None
        except UnusableNativeText:
            raise DocumentUnusableNativeText(
                "document has no usable native text",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            ) from None
        except ProcessingError:
            raise DocumentProcessingFailure(
                "document processing failed",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            ) from None
        except Exception:
            raise DocumentProcessingFailure(
                "document processing failed",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            ) from None
        if (
            not isinstance(result, ProcessingResult)
            or result.document_id != ingestion.document_id
            or result.document_version_id != ingestion.document_version_id
            or result.processing_job_id != ingestion.processing_job_id
            or len(result.pages) != ingestion.pdf.page_count
            or any(page.workspace_id != workspace_id for page in result.pages)
        ):
            raise DocumentProcessingFailure(
                "document processing returned invalid data",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            )
        return result

    def _prepare(
        self,
        processing: ProcessingResult,
        workspace_id: WorkspaceId,
    ) -> IndexPreparationResult:
        try:
            result = self._prepare_indexing(processing)
        except IndexingCancelled:
            raise DocumentWorkflowCancelled(
                "document workflow was cancelled",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            ) from None
        except IndexingError:
            raise DocumentIndexingFailure(
                "document indexing failed",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            ) from None
        except Exception:
            raise DocumentIndexingFailure(
                "document indexing failed",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            ) from None
        if not isinstance(result, (StagingEmbeddingHandoff, ReusedActiveIndex)):
            raise DocumentIndexingFailure(
                "document indexing returned invalid data",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            )
        generation = (
            result.candidate.generation
            if isinstance(result, StagingEmbeddingHandoff)
            else result.persisted.generation
        )
        self._require_generation(generation, processing, workspace_id)
        return result

    def _embed(
        self,
        handoff: StagingEmbeddingHandoff,
        workspace_id: WorkspaceId,
        processing: ProcessingResult,
    ) -> ActivatedIndex:
        try:
            result = self._embed_staging_chunks(handoff)
        except EmbeddingCancelled:
            raise DocumentWorkflowCancelled(
                "document workflow was cancelled",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            ) from None
        except EmbeddingError:
            raise DocumentEmbeddingFailure(
                "document embedding failed",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            ) from None
        except Exception:
            raise DocumentEmbeddingFailure(
                "document embedding failed",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            ) from None
        if not isinstance(result, ActivatedIndex):
            raise DocumentEmbeddingFailure(
                "document embedding returned invalid data",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            )
        generation = result.generation
        try:
            self._require_generation(generation, processing, workspace_id)
            generation.validate_document_version(result.version)
            generation.validate_processing_job(result.job)
        except DocumentIndexingFailure:
            raise DocumentEmbeddingFailure(
                "document embedding returned invalid data",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            ) from None
        except Exception:
            raise DocumentEmbeddingFailure(
                "document embedding returned invalid data",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            ) from None
        if result.version.document_id != processing.document_id:
            raise DocumentEmbeddingFailure(
                "document embedding returned invalid data",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            )
        return result

    @staticmethod
    def _require_generation(
        generation: IndexGeneration,
        processing: ProcessingResult,
        workspace_id: WorkspaceId,
    ) -> None:
        if (
            not isinstance(generation, IndexGeneration)
            or generation.workspace_id != workspace_id
            or generation.document_version_id != processing.document_version_id
            or generation.processing_job_id != processing.processing_job_id
        ):
            raise DocumentIndexingFailure(
                "document index handoff is invalid",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            )

    @staticmethod
    def _result(
        workspace_id: WorkspaceId,
        source: SelectedPdfSource,
        processing: ProcessingResult,
        generation: IndexGeneration,
        readiness: ActiveDocumentReadiness,
    ) -> ActiveDocumentResult:
        try:
            return ActiveDocumentResult(
                workspace_id=workspace_id,
                document_id=processing.document_id,
                document_version_id=processing.document_version_id,
                processing_job_id=processing.processing_job_id,
                logical_filename=source.logical_filename,
                page_count=len(processing.pages),
                readiness=readiness,
                active_generation=generation,
            )
        except DocumentProcessingFailure:
            raise DocumentProcessingFailure(
                "active document result is invalid",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            ) from None
        except Exception:
            raise DocumentIndexingFailure(
                "active document result is invalid",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            ) from None
