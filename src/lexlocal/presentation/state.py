"""Define immutable UI-001 display state and worker boundary values."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from lexlocal.application.ports.chat import ChatCompletionResult, ChatIntakeResult
from lexlocal.application.ports.document_workflow import (
    ActiveDocumentReadiness,
    ActiveDocumentResult,
    DocumentWorkflowDisposition,
    DocumentWorkflowStage,
)
from lexlocal.domain.identifiers import QaRequestId, WorkspaceId
from lexlocal.domain.workspace import Workspace


class CapabilityState(StrEnum):
    """Represent the safe aggregate local capability state."""

    STARTING = "STARTING"
    READY = "READY"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    FATAL_STARTUP = "FATAL_STARTUP"


class WorkspaceDisplayState(StrEnum):
    """Represent the process-local workspace selection state."""

    NO_SELECTION = "NO_SELECTION"
    CREATING = "CREATING"
    SELECTED = "SELECTED"
    FAILED = "FAILED"


class WorkspaceNotice(StrEnum):
    """Identify fixed workspace-panel status copy without carrying payload text."""

    LISTED = "LISTED"
    CREATED = "CREATED"
    SELECTED = "SELECTED"


class DocumentDisplayState(StrEnum):
    """Represent truthful document-workflow display phases."""

    EMPTY = "EMPTY"
    IMPORTING = "IMPORTING"
    EXTRACTING = "EXTRACTING"
    INDEXING = "INDEXING"
    EMBEDDING = "EMBEDDING"
    READY = "READY"
    READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class DocumentNotice(StrEnum):
    """Identify fixed non-error document status copy."""

    CANCELLED = "CANCELLED"


class QuestionDisplayState(StrEnum):
    """Represent the one-question M1 display state."""

    IDLE = "IDLE"
    PREPARING = "PREPARING"
    ASKING = "ASKING"
    CANCELLING = "CANCELLING"
    GROUNDED = "GROUNDED"
    RELATED_NON_ANSWER = "RELATED_NON_ANSWER"
    INSUFFICIENT_NON_ANSWER = "INSUFFICIENT_NON_ANSWER"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WorkerOperation(StrEnum):
    """Identify the bounded commands serialized by the M1 worker."""

    STARTUP = "STARTUP"
    LIST_WORKSPACES = "LIST_WORKSPACES"
    CREATE_WORKSPACE = "CREATE_WORKSPACE"
    SELECT_WORKSPACE = "SELECT_WORKSPACE"
    DOCUMENT = "DOCUMENT"
    QUESTION = "QUESTION"
    SHUTDOWN = "SHUTDOWN"


class PresentationErrorCode(StrEnum):
    """Expose fixed safe failure categories instead of exception text."""

    STARTUP_FAILED = "STARTUP_FAILED"
    WORKSPACE_UNAVAILABLE = "WORKSPACE_UNAVAILABLE"
    WORKSPACE_OPERATION_FAILED = "WORKSPACE_OPERATION_FAILED"
    PDF_UNREADABLE = "PDF_UNREADABLE"
    PDF_DUPLICATE = "PDF_DUPLICATE"
    NATIVE_TEXT_UNAVAILABLE = "NATIVE_TEXT_UNAVAILABLE"
    DOCUMENT_FAILED = "DOCUMENT_FAILED"
    DOCUMENT_REGISTERED_INCOMPLETE = "DOCUMENT_REGISTERED_INCOMPLETE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    INDEX_UNAVAILABLE = "INDEX_UNAVAILABLE"
    QUESTION_FAILED = "QUESTION_FAILED"
    QUESTION_DRAFT_INTERRUPTED = "QUESTION_DRAFT_INTERRUPTED"
    QUESTION_CANCELLED = "QUESTION_CANCELLED"
    CITATION_UNAVAILABLE = "CITATION_UNAVAILABLE"


PRESENTATION_MESSAGES: Mapping[PresentationErrorCode, str] = MappingProxyType({
    PresentationErrorCode.STARTUP_FAILED: "LexLocal could not start safely.",
    PresentationErrorCode.WORKSPACE_UNAVAILABLE: "Select a workspace first.",
    PresentationErrorCode.WORKSPACE_OPERATION_FAILED: (
        "The workspace operation could not be completed."
    ),
    PresentationErrorCode.PDF_UNREADABLE: "The selected PDF cannot be imported.",
    PresentationErrorCode.PDF_DUPLICATE: (
        "This PDF is already registered in the selected workspace."
    ),
    PresentationErrorCode.NATIVE_TEXT_UNAVAILABLE: (
        "This PDF has no usable native text in M1; OCR is unavailable."
    ),
    PresentationErrorCode.DOCUMENT_FAILED: (
        "Document processing failed; no document was registered."
    ),
    PresentationErrorCode.DOCUMENT_REGISTERED_INCOMPLETE: (
        "Document processing failed; the registered document is incomplete and is not ready."
    ),
    PresentationErrorCode.MODEL_UNAVAILABLE: (
        "Required local models are unavailable. No cloud fallback was used."
    ),
    PresentationErrorCode.INDEX_UNAVAILABLE: (
        "The document index is unavailable or inconsistent."
    ),
    PresentationErrorCode.QUESTION_FAILED: "The question could not be completed.",
    PresentationErrorCode.QUESTION_DRAFT_INTERRUPTED: (
        "Question intake was saved, but completion did not start. Retry this question."
    ),
    PresentationErrorCode.QUESTION_CANCELLED: (
        "The question was cancelled; no completed answer was saved."
    ),
    PresentationErrorCode.CITATION_UNAVAILABLE: "Citation is unavailable.",
})


@dataclass(frozen=True, slots=True)
class OperationToken:
    """Correlate one command without carrying protected business identity."""

    number: int
    workspace_epoch: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.number, bool)
            or not isinstance(self.number, int)
            or self.number < 1
            or isinstance(self.workspace_epoch, bool)
            or not isinstance(self.workspace_epoch, int)
            or self.workspace_epoch < 0
        ):
            raise ValueError("operation token is invalid")


@dataclass(frozen=True, slots=True)
class ActionAvailability:
    """Expose the fixed enablement truth table independently of widgets."""

    create_workspace: bool
    select_workspace: bool
    import_pdf: bool
    cancel_document: bool
    ask: bool
    retry_question: bool
    cancel_question: bool
    open_citation: bool


@dataclass(frozen=True, slots=True)
class PresentationState:
    """Hold immutable session-only display state on the GUI thread."""

    capability: CapabilityState = CapabilityState.STARTING
    workspace: WorkspaceDisplayState = WorkspaceDisplayState.NO_SELECTION
    document: DocumentDisplayState = DocumentDisplayState.EMPTY
    question: QuestionDisplayState = QuestionDisplayState.IDLE
    active_operation: WorkerOperation | None = None
    operation_token: OperationToken | None = None
    workspaces: tuple[Workspace, ...] = field(default=(), repr=False)
    active_workspace: Workspace | None = field(default=None, repr=False)
    selected_workspace_id: WorkspaceId | None = field(default=None, repr=False)
    active_document: ActiveDocumentResult | None = field(default=None, repr=False)
    qa_request_id: QaRequestId | None = field(default=None, repr=False)
    chat_result: ChatCompletionResult | None = field(default=None, repr=False)
    registered_incomplete_document: bool = False
    workspace_notice: WorkspaceNotice | None = None
    document_notice: DocumentNotice | None = None
    error_code: PresentationErrorCode | None = None
    shutting_down: bool = False

    @property
    def actions(self) -> ActionAvailability:
        """Derive action enablement without a second mutable flag set."""

        idle = self.active_operation is None and not self.shutting_down
        models_ready = self.capability is CapabilityState.READY
        workspace_available = self.capability in (
            CapabilityState.READY,
            CapabilityState.MODEL_UNAVAILABLE,
        )
        workspace_selected = (
            self.workspace is WorkspaceDisplayState.SELECTED
            and self.selected_workspace_id is not None
        )
        document_ready = self.document in (
            DocumentDisplayState.READY,
            DocumentDisplayState.READY_WITH_WARNINGS,
        )
        terminal_question = self.question in (
            QuestionDisplayState.GROUNDED,
            QuestionDisplayState.RELATED_NON_ANSWER,
            QuestionDisplayState.INSUFFICIENT_NON_ANSWER,
        )
        return ActionAvailability(
            create_workspace=(idle and workspace_available),
            select_workspace=(idle and workspace_available),
            import_pdf=(
                idle
                and models_ready
                and workspace_selected
                and self.document is DocumentDisplayState.EMPTY
                and not self.registered_incomplete_document
            ),
            cancel_document=(
                self.active_operation is WorkerOperation.DOCUMENT
                and self.document
                in (
                    DocumentDisplayState.IMPORTING,
                    DocumentDisplayState.EXTRACTING,
                    DocumentDisplayState.INDEXING,
                    DocumentDisplayState.EMBEDDING,
                )
            ),
            ask=(
                idle
                and models_ready
                and document_ready
                and self.qa_request_id is None
            ),
            retry_question=(
                idle
                and self.qa_request_id is not None
                and self.question
                in (QuestionDisplayState.FAILED, QuestionDisplayState.CANCELLED)
            ),
            cancel_question=(
                self.active_operation is WorkerOperation.QUESTION
                and self.question
                in (QuestionDisplayState.PREPARING, QuestionDisplayState.ASKING)
            ),
            open_citation=(idle and terminal_question and self.chat_result is not None),
        )

@dataclass(frozen=True, slots=True)
class CapabilityEvent:
    token: OperationToken
    state: CapabilityState


@dataclass(frozen=True, slots=True)
class WorkspaceListEvent:
    token: OperationToken
    workspaces: tuple[Workspace, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class WorkspaceEvent:
    token: OperationToken
    workspace: Workspace = field(repr=False)


@dataclass(frozen=True, slots=True)
class WorkspaceSelectedEvent:
    token: OperationToken
    workspace_id: WorkspaceId = field(repr=False)


@dataclass(frozen=True, slots=True)
class DocumentPhaseEvent:
    token: OperationToken
    stage: DocumentWorkflowStage


@dataclass(frozen=True, slots=True)
class DocumentReadyEvent:
    token: OperationToken
    result: ActiveDocumentResult = field(repr=False)


@dataclass(frozen=True, slots=True)
class QuestionPreparedEvent:
    token: OperationToken
    result: ChatIntakeResult = field(repr=False)


@dataclass(frozen=True, slots=True)
class QuestionCompletedEvent:
    token: OperationToken
    result: ChatCompletionResult = field(repr=False)


@dataclass(frozen=True, slots=True)
class OperationCancelledEvent:
    token: OperationToken
    operation: WorkerOperation
    disposition: DocumentWorkflowDisposition | None = None
    qa_request_id: QaRequestId | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class OperationFailedEvent:
    token: OperationToken
    operation: WorkerOperation
    code: PresentationErrorCode
    disposition: DocumentWorkflowDisposition | None = None
    qa_request_id: QaRequestId | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ShutdownEvent:
    token: OperationToken


def document_state_for_stage(stage: DocumentWorkflowStage) -> DocumentDisplayState:
    """Map the Application's fixed phase to its display-only equivalent."""

    return {
        DocumentWorkflowStage.IMPORTING: DocumentDisplayState.IMPORTING,
        DocumentWorkflowStage.EXTRACTING: DocumentDisplayState.EXTRACTING,
        DocumentWorkflowStage.INDEXING: DocumentDisplayState.INDEXING,
        DocumentWorkflowStage.EMBEDDING: DocumentDisplayState.EMBEDDING,
    }[stage]


def document_state_for_result(result: ActiveDocumentResult) -> DocumentDisplayState:
    """Map only the two authoritative activated readiness values."""

    return {
        ActiveDocumentReadiness.READY: DocumentDisplayState.READY,
        ActiveDocumentReadiness.READY_WITH_WARNINGS:
            DocumentDisplayState.READY_WITH_WARNINGS,
    }[result.readiness]
