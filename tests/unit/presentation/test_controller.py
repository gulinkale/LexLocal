from uuid import uuid4

import pytest

from lexlocal.application.ports.chat import ChatIntakeResult
from lexlocal.application.ports.document_workflow import (
    ActiveDocumentReadiness,
    ActiveDocumentResult,
    DocumentWorkflowDisposition,
)
from lexlocal.domain.identifiers import (
    DocumentId,
    DocumentVersionId,
    IndexGenerationId,
    LocalModelId,
    ProcessingJobId,
    QaRequestId,
    WorkspaceId,
)
from lexlocal.domain.processing import IndexGeneration, IndexGenerationState
from lexlocal.presentation.controller import (
    OperationAlreadyActive,
    PresentationController,
)
from lexlocal.presentation.state import (
    CapabilityEvent,
    CapabilityState,
    DocumentDisplayState,
    DocumentReadyEvent,
    OperationCancelledEvent,
    OperationToken,
    QuestionDisplayState,
    QuestionPreparedEvent,
    WorkerOperation,
)


def _id(identifier_type: type):
    return identifier_type(str(uuid4()))


def _active_document(workspace_id: WorkspaceId) -> ActiveDocumentResult:
    version_id = _id(DocumentVersionId)
    processing_job_id = _id(ProcessingJobId)
    generation = IndexGeneration(
        _id(IndexGenerationId),
        workspace_id,
        version_id,
        processing_job_id,
        _id(LocalModelId),
        "chunk-v1",
        "norm-v1",
        3,
        IndexGenerationState.ACTIVE,
    )
    return ActiveDocumentResult(
        workspace_id,
        _id(DocumentId),
        version_id,
        processing_job_id,
        "synthetic.pdf",
        1,
        ActiveDocumentReadiness.READY,
        generation,
    )


def test_controller_allows_exactly_one_active_operation() -> None:
    controller = PresentationController()

    token = controller.begin(WorkerOperation.STARTUP)

    assert token == OperationToken(1, 0)
    with pytest.raises(OperationAlreadyActive):
        controller.begin(WorkerOperation.DOCUMENT)

    controller.accept_capability(CapabilityEvent(token, CapabilityState.READY))
    assert controller.state.active_operation is None


def test_workspace_epoch_rejects_stale_worker_result() -> None:
    controller = PresentationController()
    workspace_id = _id(WorkspaceId)
    controller.select_workspace_locally(workspace_id)
    stale = OperationToken(99, 0)
    before = controller.state

    controller.accept_document_ready(
        DocumentReadyEvent(stale, _active_document(workspace_id))
    )

    assert controller.state is before


def test_late_active_document_result_wins_after_cancellation_request() -> None:
    controller = PresentationController()
    workspace_id = _id(WorkspaceId)
    controller.select_workspace_locally(workspace_id)
    token = controller.begin(WorkerOperation.DOCUMENT)

    controller.request_cancellation()
    assert controller.state.document is DocumentDisplayState.CANCELLING
    result = _active_document(workspace_id)
    controller.accept_document_ready(DocumentReadyEvent(token, result))

    assert controller.state.document is DocumentDisplayState.READY
    assert controller.state.active_document == result
    assert controller.state.active_operation is None


def test_registered_document_cancellation_blocks_same_session_import() -> None:
    controller = PresentationController()
    controller.select_workspace_locally(_id(WorkspaceId))
    token = controller.begin(WorkerOperation.DOCUMENT)

    controller.accept_cancelled(
        OperationCancelledEvent(
            token,
            WorkerOperation.DOCUMENT,
            DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
        )
    )

    assert controller.state.document is DocumentDisplayState.CANCELLED
    assert controller.state.registered_incomplete_document is True
    assert controller.state.actions.import_pdf is False


def test_durable_intake_identity_survives_question_cancellation() -> None:
    controller = PresentationController()
    qa_request_id = _id(QaRequestId)
    token = controller.begin(WorkerOperation.QUESTION)

    controller.accept_question_prepared(
        QuestionPreparedEvent(token, ChatIntakeResult(qa_request_id, False))
    )
    controller.request_cancellation()
    controller.accept_cancelled(
        OperationCancelledEvent(
            token,
            WorkerOperation.QUESTION,
            qa_request_id=qa_request_id,
        )
    )

    assert controller.state.question is QuestionDisplayState.CANCELLED
    assert controller.state.qa_request_id == qa_request_id
    assert controller.state.actions.retry_question is True
