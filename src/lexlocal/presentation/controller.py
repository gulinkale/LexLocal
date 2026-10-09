"""Reduce typed worker events into immutable GUI-thread display state."""

from dataclasses import replace

from PySide6.QtCore import QObject, Signal, Slot

from lexlocal.application.ports.document_workflow import DocumentWorkflowDisposition
from lexlocal.domain.identifiers import WorkspaceId
from lexlocal.domain.retrieval import EvidenceSufficiency
from lexlocal.presentation.state import (
    CapabilityEvent,
    DocumentDisplayState,
    DocumentNotice,
    DocumentPhaseEvent,
    DocumentReadyEvent,
    OperationCancelledEvent,
    OperationFailedEvent,
    OperationToken,
    PresentationErrorCode,
    PresentationState,
    QuestionCompletedEvent,
    QuestionDisplayState,
    QuestionPreparedEvent,
    WorkerOperation,
    WorkspaceDisplayState,
    WorkspaceEvent,
    WorkspaceListEvent,
    WorkspaceNotice,
    WorkspaceSelectedEvent,
    document_state_for_result,
    document_state_for_stage,
)


class OperationAlreadyActive(RuntimeError):
    """Reject a second GUI command while the serialized worker is occupied."""


class PresentationController(QObject):
    """Own display state and reject stale worker results before widget handling."""

    state_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._state = PresentationState()
        self._next_operation = 1
        self._workspace_epoch = 0

    @property
    def state(self) -> PresentationState:
        return self._state

    def begin(self, operation: WorkerOperation) -> OperationToken:
        """Reserve the only active operation and return its opaque token."""

        if self._state.active_operation is not None or self._state.shutting_down:
            raise OperationAlreadyActive("a presentation operation is already active")
        token = OperationToken(self._next_operation, self._workspace_epoch)
        self._next_operation += 1
        if operation is WorkerOperation.DOCUMENT:
            state = replace(
                self._state,
                active_operation=operation,
                operation_token=token,
                error_code=None,
                document=DocumentDisplayState.IMPORTING,
                document_notice=None,
            )
        elif operation is WorkerOperation.QUESTION:
            state = replace(
                self._state,
                active_operation=operation,
                operation_token=token,
                error_code=None,
                question=QuestionDisplayState.PREPARING,
            )
        elif operation is WorkerOperation.CREATE_WORKSPACE:
            state = replace(
                self._state,
                active_operation=operation,
                operation_token=token,
                error_code=None,
                workspace=WorkspaceDisplayState.CREATING,
                workspace_notice=None,
            )
        else:
            state = replace(
                self._state,
                active_operation=operation,
                operation_token=token,
                error_code=None,
            )
        self._set_state(state)
        return token

    def request_cancellation(self) -> OperationToken | None:
        """Render a request while the thread-safe source is set by the caller."""

        token = self._state.operation_token
        if self._state.active_operation is WorkerOperation.DOCUMENT:
            self._set_state(
                replace(self._state, document=DocumentDisplayState.CANCELLING)
            )
        elif self._state.active_operation is WorkerOperation.QUESTION:
            self._set_state(
                replace(self._state, question=QuestionDisplayState.CANCELLING)
            )
        return token

    def begin_shutdown(self) -> OperationToken:
        """Invalidate pending results and return the worker shutdown token."""

        token = OperationToken(self._next_operation, self._workspace_epoch)
        self._next_operation += 1
        self._set_state(
            replace(
                self._state,
                shutting_down=True,
                active_operation=WorkerOperation.SHUTDOWN,
                operation_token=token,
            )
        )
        return token

    @Slot(object)
    def accept_capability(self, event: object) -> None:
        if not isinstance(event, CapabilityEvent) or not self._accepts(event.token):
            return
        self._set_state(
            replace(
                self._state,
                capability=event.state,
                active_operation=None,
                operation_token=None,
            )
        )

    @Slot(object)
    def accept_workspace_listed(self, event: object) -> None:
        if not isinstance(event, WorkspaceListEvent) or not self._accepts(event.token):
            return
        active_workspace = next(
            (
                workspace
                for workspace in event.workspaces
                if workspace.id == self._state.selected_workspace_id
            ),
            None,
        )
        self._set_state(
            replace(
                self._state,
                workspaces=event.workspaces,
                active_workspace=active_workspace,
                selected_workspace_id=(
                    active_workspace.id if active_workspace is not None else None
                ),
                workspace=(
                    WorkspaceDisplayState.SELECTED
                    if active_workspace is not None
                    else WorkspaceDisplayState.NO_SELECTION
                ),
                workspace_notice=WorkspaceNotice.LISTED,
                active_operation=None,
                operation_token=None,
            )
        )

    @Slot(object)
    def accept_workspace_created(self, event: object) -> None:
        if not isinstance(event, WorkspaceEvent) or not self._accepts(event.token):
            return
        existing = next(
            (
                workspace
                for workspace in self._state.workspaces
                if workspace.id == event.workspace.id
            ),
            None,
        )
        if existing is not None and existing != event.workspace:
            self._set_state(
                replace(
                    self._state,
                    workspace=(
                        WorkspaceDisplayState.SELECTED
                        if self._state.active_workspace is not None
                        else WorkspaceDisplayState.FAILED
                    ),
                    workspace_notice=None,
                    error_code=PresentationErrorCode.WORKSPACE_OPERATION_FAILED,
                    active_operation=None,
                    operation_token=None,
                )
            )
            return
        workspaces = (
            self._state.workspaces
            if existing is not None
            else (*self._state.workspaces, event.workspace)
        )
        self._set_state(
            replace(
                self._state,
                workspaces=workspaces,
                workspace=(
                    WorkspaceDisplayState.SELECTED
                    if self._state.active_workspace is not None
                    else WorkspaceDisplayState.NO_SELECTION
                ),
                workspace_notice=WorkspaceNotice.CREATED,
                active_operation=None,
                operation_token=None,
            )
        )

    @Slot(object)
    def accept_workspace_selected(self, event: object) -> None:
        if not isinstance(event, WorkspaceSelectedEvent) or not self._accepts(event.token):
            return
        active_workspace = next(
            (
                workspace
                for workspace in self._state.workspaces
                if workspace.id == event.workspace_id
            ),
            None,
        )
        if active_workspace is None:
            self._set_state(
                replace(
                    self._state,
                    workspace=(
                        WorkspaceDisplayState.SELECTED
                        if self._state.active_workspace is not None
                        else WorkspaceDisplayState.FAILED
                    ),
                    workspace_notice=None,
                    error_code=PresentationErrorCode.WORKSPACE_OPERATION_FAILED,
                    active_operation=None,
                    operation_token=None,
                )
            )
            return
        self._workspace_epoch += 1
        self._set_state(
            replace(
                self._state,
                workspace=WorkspaceDisplayState.SELECTED,
                selected_workspace_id=event.workspace_id,
                active_workspace=active_workspace,
                workspace_notice=WorkspaceNotice.SELECTED,
                error_code=None,
                document=DocumentDisplayState.EMPTY,
                active_document=None,
                registered_incomplete_document=False,
                document_notice=None,
                question=QuestionDisplayState.IDLE,
                qa_request_id=None,
                chat_result=None,
                active_operation=None,
                operation_token=None,
            )
        )

    def select_workspace_locally(self, workspace_id: WorkspaceId) -> None:
        """Apply an already validated selection when no worker command is active."""

        if self._state.active_operation is not None:
            raise OperationAlreadyActive("workspace selection cannot change during work")
        self._workspace_epoch += 1
        self._set_state(
            replace(
                self._state,
                workspace=WorkspaceDisplayState.SELECTED,
                selected_workspace_id=workspace_id,
                active_workspace=None,
                document=DocumentDisplayState.EMPTY,
                active_document=None,
                registered_incomplete_document=False,
                question=QuestionDisplayState.IDLE,
                qa_request_id=None,
                chat_result=None,
                error_code=None,
            )
        )

    @Slot(object)
    def accept_document_phase(self, event: object) -> None:
        if not isinstance(event, DocumentPhaseEvent) or not self._accepts(event.token):
            return
        self._set_state(
            replace(
                self._state,
                document=document_state_for_stage(event.stage),
                document_notice=None,
            )
        )

    @Slot(object)
    def accept_document_ready(self, event: object) -> None:
        if not isinstance(event, DocumentReadyEvent) or not self._accepts(event.token):
            return
        if event.result.workspace_id != self._state.selected_workspace_id:
            self._set_state(
                replace(
                    self._state,
                    document=DocumentDisplayState.EMPTY,
                    active_document=None,
                    registered_incomplete_document=False,
                    document_notice=None,
                    error_code=PresentationErrorCode.DOCUMENT_FAILED,
                    active_operation=None,
                    operation_token=None,
                )
            )
            return
        self._set_state(
            replace(
                self._state,
                document=document_state_for_result(event.result),
                active_document=event.result,
                registered_incomplete_document=False,
                document_notice=None,
                error_code=None,
                active_operation=None,
                operation_token=None,
            )
        )

    @Slot(object)
    def accept_question_prepared(self, event: object) -> None:
        if not isinstance(event, QuestionPreparedEvent) or not self._accepts(event.token):
            return
        self._set_state(
            replace(
                self._state,
                question=QuestionDisplayState.ASKING,
                qa_request_id=event.result.qa_request_id,
                chat_result=None,
                error_code=None,
            )
        )

    @Slot(object)
    def accept_question_completed(self, event: object) -> None:
        if not isinstance(event, QuestionCompletedEvent) or not self._accepts(event.token):
            return
        graph = event.result.graph
        document = self._state.active_document
        scope = graph.target.scope_versions
        if (
            self._state.qa_request_id is None
            or graph.target.qa_request_id != self._state.qa_request_id
            or graph.target.workspace_id != self._state.selected_workspace_id
            or document is None
            or len(scope) != 1
            or scope[0].document_id != document.document_id
            or scope[0].document_version_id != document.document_version_id
        ):
            self._set_state(
                replace(
                    self._state,
                    question=QuestionDisplayState.FAILED,
                    chat_result=None,
                    error_code=PresentationErrorCode.QUESTION_FAILED,
                    active_operation=None,
                    operation_token=None,
                )
            )
            return
        display = {
            EvidenceSufficiency.SUFFICIENT: QuestionDisplayState.GROUNDED,
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT:
                QuestionDisplayState.RELATED_NON_ANSWER,
            EvidenceSufficiency.INSUFFICIENT:
                QuestionDisplayState.INSUFFICIENT_NON_ANSWER,
        }[event.result.graph.evidence_state]
        self._set_state(
            replace(
                self._state,
                question=display,
                chat_result=event.result,
                error_code=None,
                active_operation=None,
                operation_token=None,
            )
        )

    @Slot(object)
    def accept_cancelled(self, event: object) -> None:
        if not isinstance(event, OperationCancelledEvent) or not self._accepts(event.token):
            return
        if event.operation is WorkerOperation.DOCUMENT:
            registered = (
                event.disposition is DocumentWorkflowDisposition.REGISTERED_INCOMPLETE
            )
            state = replace(
                self._state,
                document=(
                    DocumentDisplayState.CANCELLED
                    if registered
                    else DocumentDisplayState.EMPTY
                ),
                active_document=None,
                registered_incomplete_document=registered,
                document_notice=DocumentNotice.CANCELLED,
                error_code=None,
                active_operation=None,
                operation_token=None,
            )
        elif event.operation is WorkerOperation.QUESTION:
            state = replace(
                self._state,
                question=QuestionDisplayState.CANCELLED,
                qa_request_id=event.qa_request_id or self._state.qa_request_id,
                chat_result=None,
                error_code=PresentationErrorCode.QUESTION_CANCELLED,
                active_operation=None,
                operation_token=None,
            )
        else:
            state = replace(
                self._state,
                active_operation=None,
                operation_token=None,
            )
        self._set_state(state)

    @Slot(object)
    def accept_failed(self, event: object) -> None:
        if not isinstance(event, OperationFailedEvent) or not self._accepts(event.token):
            return
        if event.operation is WorkerOperation.DOCUMENT:
            registered = (
                event.disposition is DocumentWorkflowDisposition.REGISTERED_INCOMPLETE
            )
            state = replace(
                self._state,
                document=(
                    DocumentDisplayState.FAILED
                    if registered
                    else DocumentDisplayState.EMPTY
                ),
                active_document=None,
                registered_incomplete_document=registered,
                document_notice=None,
                error_code=event.code,
                active_operation=None,
                operation_token=None,
            )
        elif event.operation is WorkerOperation.QUESTION:
            state = replace(
                self._state,
                question=QuestionDisplayState.FAILED,
                qa_request_id=event.qa_request_id or self._state.qa_request_id,
                error_code=event.code,
                active_operation=None,
                operation_token=None,
            )
        elif event.operation in (
            WorkerOperation.LIST_WORKSPACES,
            WorkerOperation.CREATE_WORKSPACE,
            WorkerOperation.SELECT_WORKSPACE,
        ):
            state = replace(
                self._state,
                workspace=(
                    WorkspaceDisplayState.SELECTED
                    if self._state.active_workspace is not None
                    else WorkspaceDisplayState.FAILED
                ),
                workspace_notice=None,
                error_code=event.code,
                active_operation=None,
                operation_token=None,
            )
        else:
            state = replace(
                self._state,
                error_code=event.code,
                active_operation=None,
                operation_token=None,
            )
        self._set_state(state)

    def _accepts(self, token: OperationToken) -> bool:
        return (
            token == self._state.operation_token
            and token.workspace_epoch == self._workspace_epoch
        )

    def _set_state(self, state: PresentationState) -> None:
        self._state = state
        self.state_changed.emit(state)
