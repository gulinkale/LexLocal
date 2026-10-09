"""Tests for the path-private document-workflow contracts."""

from lexlocal.application.ports.document_workflow import (
    ActiveDocumentReadiness,
    ActiveDocumentResult,
    DocumentProcessingFailure,
    DocumentWorkflowCancellationCheck,
    DocumentWorkflowDisposition,
    DocumentWorkflowError,
    DocumentWorkflowStage,
    DocumentWorkflowStageSink,
    SelectedPdfReader,
    SelectedPdfReference,
    SelectedPdfSource,
)
from lexlocal.domain.identifiers import (
    DocumentId,
    DocumentVersionId,
    IndexGenerationId,
    LocalModelId,
    ProcessingJobId,
    WorkspaceId,
)
from lexlocal.domain.processing import IndexGeneration, IndexGenerationState

_WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
_DOCUMENT_ID = DocumentId("10000000-0000-4000-8000-000000000002")
_VERSION_ID = DocumentVersionId("10000000-0000-4000-8000-000000000003")
_JOB_ID = ProcessingJobId("10000000-0000-4000-8000-000000000004")
_GENERATION_ID = IndexGenerationId("10000000-0000-4000-8000-000000000005")
_MODEL_ID = LocalModelId("10000000-0000-4000-8000-000000000006")


class _Reader:
    def read(self, selected: SelectedPdfReference) -> SelectedPdfSource:
        assert isinstance(selected, SelectedPdfReference)
        return SelectedPdfSource(b"%PDF-exact", "anonymous.pdf")


class _Cancellation:
    def raise_if_cancelled(self) -> None:
        return None


class _Sink:
    def __call__(self, stage: DocumentWorkflowStage) -> None:
        assert isinstance(stage, DocumentWorkflowStage)


_READER_CONFORMANCE: SelectedPdfReader = _Reader()
_CANCELLATION_CONFORMANCE: DocumentWorkflowCancellationCheck = _Cancellation()
_SINK_CONFORMANCE: DocumentWorkflowStageSink = _Sink()


def _result() -> ActiveDocumentResult:
    generation = IndexGeneration(
        _GENERATION_ID,
        _WORKSPACE_ID,
        _VERSION_ID,
        _JOB_ID,
        _MODEL_ID,
        "chunk-profile-v1",
        "normalization-v1",
        8,
        IndexGenerationState.ACTIVE,
    )
    return ActiveDocumentResult(
        workspace_id=_WORKSPACE_ID,
        document_id=_DOCUMENT_ID,
        document_version_id=_VERSION_ID,
        processing_job_id=_JOB_ID,
        logical_filename="anonymous.pdf",
        page_count=1,
        readiness=ActiveDocumentReadiness.READY,
        active_generation=generation,
    )


def test_protocol_doubles_conform_without_sdk_or_path_types() -> None:
    selected = SelectedPdfReference("/private/synthetic/anonymous.pdf")

    source = _READER_CONFORMANCE.read(selected)
    _CANCELLATION_CONFORMANCE.raise_if_cancelled()
    _SINK_CONFORMANCE(DocumentWorkflowStage.IMPORTING)

    assert source.source == b"%PDF-exact"
    assert source.logical_filename == "anonymous.pdf"


def test_contract_repr_hides_path_bytes_and_logical_filename() -> None:
    private_path = "/private/synthetic/anonymous.pdf"
    selected = SelectedPdfReference(private_path)
    source = SelectedPdfSource(b"%PDF-private-source", "anonymous.pdf")
    result = _result()

    assert private_path not in repr(selected)
    assert "private-source" not in repr(source)
    assert "anonymous.pdf" not in repr(source)
    assert "anonymous.pdf" not in repr(result)


def test_active_result_exposes_only_safe_terminal_metadata() -> None:
    result = _result()

    assert result.workspace_id == _WORKSPACE_ID
    assert result.document_id == _DOCUMENT_ID
    assert result.document_version_id == _VERSION_ID
    assert result.processing_job_id == _JOB_ID
    assert result.logical_filename == "anonymous.pdf"
    assert result.page_count == 1
    assert result.readiness is ActiveDocumentReadiness.READY
    assert result.active_generation.id == _GENERATION_ID


def test_errors_expose_only_the_safe_registration_disposition() -> None:
    not_registered = DocumentWorkflowError("document workflow failed")
    registered = DocumentProcessingFailure(
        "document processing failed",
        disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
    )

    assert (
        not_registered.disposition
        is DocumentWorkflowDisposition.NOT_REGISTERED
    )
    assert (
        registered.disposition
        is DocumentWorkflowDisposition.REGISTERED_INCOMPLETE
    )
    assert "private" not in repr(registered)
