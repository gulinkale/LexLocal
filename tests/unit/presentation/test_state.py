from dataclasses import replace
from uuid import uuid4

from lexlocal.domain.identifiers import QaRequestId, WorkspaceId
from lexlocal.presentation.state import (
    CapabilityState,
    DocumentDisplayState,
    OperationCancelledEvent,
    OperationToken,
    PresentationState,
    QuestionDisplayState,
    WorkerOperation,
    WorkspaceDisplayState,
)


def _id(identifier_type: type[WorkspaceId] | type[QaRequestId]):
    return identifier_type(str(uuid4()))


def test_display_state_starts_with_every_action_disabled() -> None:
    state = PresentationState()

    assert state.capability is CapabilityState.STARTING
    assert state.actions.create_workspace is False
    assert state.actions.select_workspace is False
    assert state.actions.import_pdf is False
    assert state.actions.ask is False
    assert state.actions.cancel_document is False
    assert state.actions.cancel_question is False


def test_action_truth_table_uses_only_immutable_display_state() -> None:
    workspace_id = _id(WorkspaceId)
    qa_request_id = _id(QaRequestId)
    ready = replace(
        PresentationState(),
        capability=CapabilityState.READY,
        workspace=WorkspaceDisplayState.SELECTED,
        selected_workspace_id=workspace_id,
    )

    assert ready.actions.import_pdf is True
    assert ready.actions.create_workspace is True
    assert ready.actions.ask is False

    document_ready = replace(ready, document=DocumentDisplayState.READY)
    assert document_ready.actions.ask is True
    assert document_ready.actions.import_pdf is False

    retryable = replace(
        document_ready,
        question=QuestionDisplayState.CANCELLED,
        qa_request_id=qa_request_id,
    )
    assert retryable.actions.ask is False
    assert retryable.actions.retry_question is True

    registered_incomplete = replace(
        ready,
        document=DocumentDisplayState.CANCELLED,
        registered_incomplete_document=True,
    )
    assert registered_incomplete.actions.import_pdf is False

    model_unavailable = replace(ready, capability=CapabilityState.MODEL_UNAVAILABLE)
    assert model_unavailable.actions.create_workspace is True
    assert model_unavailable.actions.import_pdf is False


def test_only_the_owning_active_operation_exposes_cancellation() -> None:
    token = OperationToken(1, 0)
    document = replace(
        PresentationState(),
        capability=CapabilityState.READY,
        document=DocumentDisplayState.INDEXING,
        active_operation=WorkerOperation.DOCUMENT,
        operation_token=token,
    )
    question = replace(
        PresentationState(),
        capability=CapabilityState.READY,
        question=QuestionDisplayState.ASKING,
        active_operation=WorkerOperation.QUESTION,
        operation_token=token,
    )

    assert document.actions.cancel_document is True
    assert document.actions.cancel_question is False
    assert question.actions.cancel_document is False
    assert question.actions.cancel_question is True


def test_private_qa_identity_is_not_exposed_by_event_repr() -> None:
    qa_request_id = _id(QaRequestId)
    event = OperationCancelledEvent(
        OperationToken(1, 0),
        WorkerOperation.QUESTION,
        qa_request_id=qa_request_id,
    )

    assert str(qa_request_id) not in repr(event)
