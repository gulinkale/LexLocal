"""Run the bounded UI-001 workflow session on one serialized Qt thread."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Protocol

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from lexlocal.application.ports.chat import (
    ChatCancellationCheck,
    ChatCancelled,
    ChatCompletionResult,
    ChatIntakeRegistration,
    ChatIntakeResult,
)
from lexlocal.application.ports.document_workflow import (
    ActiveDocumentResult,
    DocumentDuplicate,
    DocumentUnusableNativeText,
    DocumentWorkflowCancellationCheck,
    DocumentWorkflowCancelled,
    DocumentWorkflowDisposition,
    DocumentWorkflowError,
    DocumentWorkflowStage,
    InvalidSelectedPdf,
    SelectedPdfReadError,
    SelectedPdfReference,
)
from lexlocal.application.ports.embeddings import (
    EmbeddingCancellationCheck,
    EmbeddingCancelled,
)
from lexlocal.application.ports.evidence_sufficiency import (
    EvidenceSufficiencyCancellationCheck,
    EvidenceSufficiencyCancelled,
)
from lexlocal.application.ports.indexing import (
    IndexingCancellationCheck,
    IndexingCancelled,
)
from lexlocal.application.ports.processing import (
    CancellationCheck,
    ProcessingCancelled,
)
from lexlocal.domain.identifiers import QaRequestId, WorkspaceId
from lexlocal.domain.workspace import Workspace, WorkspaceProfile
from lexlocal.presentation.state import (
    CapabilityEvent,
    CapabilityState,
    DocumentPhaseEvent,
    DocumentReadyEvent,
    OperationCancelledEvent,
    OperationFailedEvent,
    OperationToken,
    PresentationErrorCode,
    QuestionCompletedEvent,
    QuestionPreparedEvent,
    ShutdownEvent,
    WorkerOperation,
    WorkspaceEvent,
    WorkspaceListEvent,
    WorkspaceSelectedEvent,
)


class WorkerFoundation(Protocol):
    """Expose model-independent worker-owned Application composition."""

    def list_workspaces(self) -> Sequence[Workspace]: ...

    def create_workspace(
        self,
        display_name: str,
        profile: WorkspaceProfile | None = None,
    ) -> Workspace: ...

    def select_workspace(self, workspace_id: WorkspaceId) -> WorkspaceId: ...

    def initialize_model_runtime(self) -> "WorkerModelRuntime": ...

    def close(self) -> None: ...


class WorkerModelRuntime(Protocol):
    """Separate runtime health from persisted-identity binding for safe startup."""

    def resolve_capabilities(self) -> None: ...

    def bind_persisted_identity(
        self,
        foundation: WorkerFoundation,
    ) -> "WorkerSession": ...

    def close(self) -> None: ...


class WorkerSession(WorkerFoundation, Protocol):
    """Expose only the already-owned Application commands needed by M1."""

    def build_document(
        self,
        selected: SelectedPdfReference,
        stage_sink: Callable[[DocumentWorkflowStage], None],
    ) -> ActiveDocumentResult: ...

    def materialize_question(
        self,
        document: ActiveDocumentResult,
        question: str,
    ) -> ChatIntakeRegistration: ...

    def start_question(
        self,
        registration: ChatIntakeRegistration,
    ) -> ChatIntakeResult: ...

    def complete_question(self, qa_request_id: QaRequestId) -> ChatCompletionResult: ...


class WorkerSessionBuilder(Protocol):
    """Build one foundation before attempting the sole local runtime."""

    def initialize_foundation(self) -> WorkerFoundation: ...


class ThreadCancellationSource:
    """Provide one token-scoped thread-safe cooperative cancellation flag."""

    __slots__ = ("_active", "_event", "_lock", "_pending")

    def __init__(self) -> None:
        self._event = Event()
        self._lock = Lock()
        self._active: OperationToken | None = None
        self._pending: set[OperationToken] = set()

    def begin(self, token: OperationToken) -> None:
        with self._lock:
            if self._active is not None:
                raise RuntimeError("a worker operation is already active")
            self._active = token
            cancelled_before_admission = token in self._pending
            self._pending.clear()
            if cancelled_before_admission:
                self._event.set()
            else:
                self._event.clear()

    def cancel(self, token: OperationToken | None = None) -> bool:
        """Set the current flag directly from the GUI thread."""

        with self._lock:
            if self._active is None:
                if token is None:
                    return False
                self._pending.add(token)
                return True
            if token is not None and token != self._active:
                return False
            self._event.set()
            return True

    def finish(self, token: OperationToken) -> None:
        with self._lock:
            if self._active == token:
                self._active = None
                self._event.clear()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()


class DocumentCancellationAdapter:
    """Adapt the shared flag to the document coordinator's exact vocabulary."""

    def __init__(self, source: ThreadCancellationSource) -> None:
        self._source = source

    def raise_if_cancelled(self) -> None:
        if self._source.is_cancelled:
            raise DocumentWorkflowCancelled("document workflow was cancelled")


class ProcessingCancellationAdapter:
    """Adapt the shared flag to native processing."""

    def __init__(self, source: ThreadCancellationSource) -> None:
        self._source = source

    def raise_if_cancelled(self) -> None:
        if self._source.is_cancelled:
            raise ProcessingCancelled("processing was cancelled")


class IndexingCancellationAdapter:
    """Adapt the shared flag to indexing."""

    def __init__(self, source: ThreadCancellationSource) -> None:
        self._source = source

    def raise_if_cancelled(self) -> None:
        if self._source.is_cancelled:
            raise IndexingCancelled("indexing was cancelled")


class EmbeddingCancellationAdapter:
    """Adapt the shared flag to embedding."""

    def __init__(self, source: ThreadCancellationSource) -> None:
        self._source = source

    def raise_if_cancelled(self) -> None:
        if self._source.is_cancelled:
            raise EmbeddingCancelled("embedding was cancelled")


class EvidenceCancellationAdapter:
    """Adapt the shared flag to evidence-sufficiency evaluation."""

    def __init__(self, source: ThreadCancellationSource) -> None:
        self._source = source

    def raise_if_cancelled(self) -> None:
        if self._source.is_cancelled:
            raise EvidenceSufficiencyCancelled(
                "evidence-sufficiency evaluation was cancelled"
            )


class ChatCancellationAdapter:
    """Adapt the shared flag to CHAT intake and completion."""

    def __init__(self, source: ThreadCancellationSource) -> None:
        self._source = source

    def raise_if_cancelled(self) -> None:
        if self._source.is_cancelled:
            raise ChatCancelled("CHAT completion was cancelled")


_DOCUMENT_ADAPTER: type[DocumentWorkflowCancellationCheck] = DocumentCancellationAdapter
_PROCESSING_ADAPTER: type[CancellationCheck] = ProcessingCancellationAdapter
_INDEXING_ADAPTER: type[IndexingCancellationCheck] = IndexingCancellationAdapter
_EMBEDDING_ADAPTER: type[EmbeddingCancellationCheck] = EmbeddingCancellationAdapter
_EVIDENCE_ADAPTER: type[EvidenceSufficiencyCancellationCheck] = (
    EvidenceCancellationAdapter
)
_CHAT_ADAPTER: type[ChatCancellationCheck] = ChatCancellationAdapter


@dataclass(frozen=True, slots=True)
class CreateWorkspaceCommand:
    token: OperationToken
    display_name: str = field(repr=False)
    profile: WorkspaceProfile | None = None


@dataclass(frozen=True, slots=True)
class SelectWorkspaceCommand:
    token: OperationToken
    workspace_id: WorkspaceId = field(repr=False)


@dataclass(frozen=True, slots=True)
class DocumentCommand:
    token: OperationToken
    selected: SelectedPdfReference = field(repr=False)


@dataclass(frozen=True, slots=True)
class QuestionCommand:
    token: OperationToken
    document: ActiveDocumentResult = field(repr=False)
    question: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class RetryQuestionCommand:
    token: OperationToken
    qa_request_id: QaRequestId = field(repr=False)


class WorkflowWorker(QObject):
    """Serialize the finite M1 command set without owning business decisions."""

    initialized = Signal(object)
    workspace_listed = Signal(object)
    workspace_created = Signal(object)
    workspace_selected = Signal(object)
    document_phase_changed = Signal(object)
    document_ready = Signal(object)
    question_prepared = Signal(object)
    question_completed = Signal(object)
    operation_cancelled = Signal(object)
    operation_failed = Signal(object)
    shutdown_complete = Signal(object)

    def __init__(
        self,
        builder: WorkerSessionBuilder,
        cancellation: ThreadCancellationSource,
    ) -> None:
        super().__init__()
        self._builder = builder
        self._cancellation = cancellation
        self._foundation: WorkerFoundation | None = None
        self._runtime: WorkerModelRuntime | None = None
        self._session: WorkerSession | None = None
        self._initialization_attempted = False
        self._closed = False

    @Slot(object)
    def initialize(self, token_value: object) -> None:
        token = self._token(token_value)
        if token is None:
            return
        if self._initialization_attempted:
            self.initialized.emit(CapabilityEvent(token, CapabilityState.FATAL_STARTUP))
            return
        self._initialization_attempted = True
        try:
            self._foundation = self._builder.initialize_foundation()
        except Exception:
            self._close_all()
            self.initialized.emit(CapabilityEvent(token, CapabilityState.FATAL_STARTUP))
            return

        try:
            self._runtime = self._foundation.initialize_model_runtime()
            self._runtime.resolve_capabilities()
        except Exception:
            self._close_runtime()
            self.initialized.emit(
                CapabilityEvent(token, CapabilityState.MODEL_UNAVAILABLE)
            )
            return

        try:
            self._session = self._runtime.bind_persisted_identity(self._foundation)
        except Exception:
            self._close_all()
            self.initialized.emit(CapabilityEvent(token, CapabilityState.FATAL_STARTUP))
            return

        self.initialized.emit(CapabilityEvent(token, CapabilityState.READY))

    @Slot(object)
    def list_workspaces(self, token_value: object) -> None:
        token = self._start(token_value, WorkerOperation.LIST_WORKSPACES)
        if token is None:
            return
        try:
            foundation = self._require_foundation()
            values = tuple(foundation.list_workspaces())
            if not all(isinstance(item, Workspace) for item in values):
                raise RuntimeError
            self.workspace_listed.emit(WorkspaceListEvent(token, values))
        except Exception:
            self._emit_failure(
                token,
                WorkerOperation.LIST_WORKSPACES,
                PresentationErrorCode.WORKSPACE_OPERATION_FAILED,
            )
        finally:
            self._cancellation.finish(token)

    @Slot(object)
    def create_workspace(self, command_value: object) -> None:
        if not isinstance(command_value, CreateWorkspaceCommand):
            return
        token = self._start(command_value.token, WorkerOperation.CREATE_WORKSPACE)
        if token is None:
            return
        try:
            workspace = self._require_foundation().create_workspace(
                command_value.display_name,
                command_value.profile,
            )
            if not isinstance(workspace, Workspace):
                raise RuntimeError
            self.workspace_created.emit(WorkspaceEvent(token, workspace))
        except Exception:
            self._emit_failure(
                token,
                WorkerOperation.CREATE_WORKSPACE,
                PresentationErrorCode.WORKSPACE_OPERATION_FAILED,
            )
        finally:
            self._cancellation.finish(token)

    @Slot(object)
    def select_workspace(self, command_value: object) -> None:
        if not isinstance(command_value, SelectWorkspaceCommand):
            return
        token = self._start(command_value.token, WorkerOperation.SELECT_WORKSPACE)
        if token is None:
            return
        try:
            workspace_id = self._require_foundation().select_workspace(
                command_value.workspace_id
            )
            if not isinstance(workspace_id, WorkspaceId):
                raise RuntimeError
            self.workspace_selected.emit(WorkspaceSelectedEvent(token, workspace_id))
        except Exception:
            self._emit_failure(
                token,
                WorkerOperation.SELECT_WORKSPACE,
                PresentationErrorCode.WORKSPACE_OPERATION_FAILED,
            )
        finally:
            self._cancellation.finish(token)

    @Slot(object)
    def run_document(self, command_value: object) -> None:
        if not isinstance(command_value, DocumentCommand):
            return
        token = self._start(command_value.token, WorkerOperation.DOCUMENT)
        if token is None:
            return
        try:
            result = self._require_session().build_document(
                command_value.selected,
                lambda stage: self.document_phase_changed.emit(
                    DocumentPhaseEvent(token, stage)
                ),
            )
            if not isinstance(result, ActiveDocumentResult):
                raise RuntimeError
            # A returned result is already durably ACTIVE. Do not relabel it from a
            # cancellation flag that raced after final activation.
            self.document_ready.emit(DocumentReadyEvent(token, result))
        except DocumentWorkflowCancelled as error:
            self.operation_cancelled.emit(
                OperationCancelledEvent(
                    token,
                    WorkerOperation.DOCUMENT,
                    error.disposition,
                )
            )
        except DocumentWorkflowError as error:
            self._emit_failure(
                token,
                WorkerOperation.DOCUMENT,
                self._document_error_code(error),
                disposition=error.disposition,
            )
        except Exception:
            self._emit_failure(
                token,
                WorkerOperation.DOCUMENT,
                PresentationErrorCode.DOCUMENT_FAILED,
            )
        finally:
            self._cancellation.finish(token)

    @Slot(object)
    def run_question(self, command_value: object) -> None:
        if not isinstance(command_value, QuestionCommand):
            return
        token = self._start(command_value.token, WorkerOperation.QUESTION)
        if token is None:
            return
        qa_request_id: QaRequestId | None = None
        try:
            session = self._require_session()
            registration = session.materialize_question(
                command_value.document,
                command_value.question,
            )
            if not isinstance(registration, ChatIntakeRegistration):
                raise RuntimeError
            intake = session.start_question(registration)
            if (
                not isinstance(intake, ChatIntakeResult)
                or intake.qa_request_id != registration.qa_request_id
            ):
                raise RuntimeError
            qa_request_id = intake.qa_request_id
            self.question_prepared.emit(QuestionPreparedEvent(token, intake))
            # Intentionally enter CompleteChat even when cancellation raced with the
            # durable intake commit. CHAT owns recording CANCELLED for this exact ID.
            result = session.complete_question(qa_request_id)
            if (
                not isinstance(result, ChatCompletionResult)
                or result.graph.target.qa_request_id != qa_request_id
                or result.graph.target.workspace_id != command_value.document.workspace_id
                or len(result.graph.target.scope_versions) != 1
                or result.graph.target.scope_versions[0].document_id
                != command_value.document.document_id
                or result.graph.target.scope_versions[0].document_version_id
                != command_value.document.document_version_id
            ):
                raise RuntimeError
            self.question_completed.emit(QuestionCompletedEvent(token, result))
        except ChatCancelled:
            self.operation_cancelled.emit(
                OperationCancelledEvent(
                    token,
                    WorkerOperation.QUESTION,
                    qa_request_id=qa_request_id,
                )
            )
        except Exception:
            self._emit_failure(
                token,
                WorkerOperation.QUESTION,
                PresentationErrorCode.QUESTION_FAILED,
                qa_request_id=qa_request_id,
            )
        finally:
            self._cancellation.finish(token)

    @Slot(object)
    def retry_question(self, command_value: object) -> None:
        if not isinstance(command_value, RetryQuestionCommand):
            return
        token = self._start(command_value.token, WorkerOperation.QUESTION)
        if token is None:
            return
        try:
            result = self._require_session().complete_question(
                command_value.qa_request_id
            )
            if (
                not isinstance(result, ChatCompletionResult)
                or result.graph.target.qa_request_id != command_value.qa_request_id
            ):
                raise RuntimeError
            self.question_completed.emit(QuestionCompletedEvent(token, result))
        except ChatCancelled:
            self.operation_cancelled.emit(
                OperationCancelledEvent(
                    token,
                    WorkerOperation.QUESTION,
                    qa_request_id=command_value.qa_request_id,
                )
            )
        except Exception:
            self._emit_failure(
                token,
                WorkerOperation.QUESTION,
                PresentationErrorCode.QUESTION_FAILED,
                qa_request_id=command_value.qa_request_id,
            )
        finally:
            self._cancellation.finish(token)

    @Slot(object)
    def shutdown(self, token_value: object) -> None:
        """Close worker-owned resources on this object's owning thread."""

        token = self._token(token_value)
        if token is None:
            return
        self._close_all()
        self.shutdown_complete.emit(ShutdownEvent(token))

    def _start(
        self,
        token_value: object,
        operation: WorkerOperation,
    ) -> OperationToken | None:
        token = self._token(token_value)
        if token is None:
            return None
        try:
            self._cancellation.begin(token)
        except Exception:
            self._emit_failure(
                token,
                operation,
                PresentationErrorCode.STARTUP_FAILED,
            )
            return None
        return token

    @staticmethod
    def _token(value: object) -> OperationToken | None:
        return value if isinstance(value, OperationToken) else None

    def _require_foundation(self) -> WorkerFoundation:
        if self._foundation is None or self._closed:
            raise RuntimeError
        return self._foundation

    def _require_session(self) -> WorkerSession:
        if self._session is None or self._closed:
            raise RuntimeError
        return self._session

    def _close_runtime(self) -> None:
        runtime, self._runtime = self._runtime, None
        if runtime is not None:
            try:
                runtime.close()
            except Exception:
                pass

    def _close_all(self) -> None:
        if self._closed:
            return
        self._closed = True
        session, self._session = self._session, None
        runtime, self._runtime = self._runtime, None
        foundation, self._foundation = self._foundation, None
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
            return
        if runtime is not None:
            try:
                runtime.close()
            except Exception:
                pass
        if foundation is not None:
            try:
                foundation.close()
            except Exception:
                pass

    @staticmethod
    def _document_error_code(error: DocumentWorkflowError) -> PresentationErrorCode:
        if isinstance(error, DocumentDuplicate):
            return PresentationErrorCode.PDF_DUPLICATE
        if isinstance(error, (InvalidSelectedPdf, SelectedPdfReadError)):
            return PresentationErrorCode.PDF_UNREADABLE
        if isinstance(error, DocumentUnusableNativeText):
            return PresentationErrorCode.NATIVE_TEXT_UNAVAILABLE
        if error.disposition is DocumentWorkflowDisposition.REGISTERED_INCOMPLETE:
            return PresentationErrorCode.DOCUMENT_REGISTERED_INCOMPLETE
        return PresentationErrorCode.DOCUMENT_FAILED

    def _emit_failure(
        self,
        token: OperationToken,
        operation: WorkerOperation,
        code: PresentationErrorCode,
        *,
        disposition: DocumentWorkflowDisposition | None = None,
        qa_request_id: QaRequestId | None = None,
    ) -> None:
        self.operation_failed.emit(
            OperationFailedEvent(
                token,
                operation,
                code,
                disposition,
                qa_request_id,
            )
        )


class SerializedWorkflowHost(QObject):
    """Own one long-lived QThread and submit only the finite worker commands."""

    initialize_requested = Signal(object)
    list_workspaces_requested = Signal(object)
    create_workspace_requested = Signal(object)
    select_workspace_requested = Signal(object)
    document_requested = Signal(object)
    question_requested = Signal(object)
    question_retry_requested = Signal(object)
    shutdown_requested = Signal(object)
    shutdown_finished = Signal()

    def __init__(
        self,
        worker: WorkflowWorker,
        cancellation: ThreadCancellationSource,
    ) -> None:
        super().__init__()
        self._worker = worker
        self._cancellation = cancellation
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        connection = Qt.ConnectionType.QueuedConnection
        self.initialize_requested.connect(worker.initialize, connection)
        self.list_workspaces_requested.connect(worker.list_workspaces, connection)
        self.create_workspace_requested.connect(worker.create_workspace, connection)
        self.select_workspace_requested.connect(worker.select_workspace, connection)
        self.document_requested.connect(worker.run_document, connection)
        self.question_requested.connect(worker.run_question, connection)
        self.question_retry_requested.connect(worker.retry_question, connection)
        self.shutdown_requested.connect(worker.shutdown, connection)
        worker.shutdown_complete.connect(
            lambda _event: self._thread.quit(),
            Qt.ConnectionType.DirectConnection,
        )
        self._thread.finished.connect(self._announce_shutdown_finished)

    @property
    def worker_thread(self) -> QThread:
        return self._thread

    def start(self) -> None:
        self._thread.start()

    def request_cancellation(self, token: OperationToken | None = None) -> bool:
        return self._cancellation.cancel(token)

    def request_shutdown(
        self,
        active_token: OperationToken | None,
        shutdown_token: OperationToken,
    ) -> bool:
        """Request cooperative cancellation and queue owning-thread cleanup."""

        if active_token is None:
            self._cancellation.cancel()
        else:
            self._cancellation.cancel(active_token)
        if not self._thread.isRunning():
            return True
        self.shutdown_requested.emit(shutdown_token)
        return False

    def shutdown(
        self,
        token: OperationToken,
        timeout_ms: int = 5000,
        *,
        active_token: OperationToken | None = None,
    ) -> bool:
        """Cancel, close on the worker thread, quit, and join without termination."""

        already_stopped = self.request_shutdown(active_token, token)
        if already_stopped:
            return True
        return self._thread.wait(timeout_ms)

    @Slot()
    def _announce_shutdown_finished(self) -> None:
        self.shutdown_finished.emit()
