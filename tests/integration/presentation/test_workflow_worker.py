from collections.abc import Callable, Sequence
from dataclasses import fields
from datetime import UTC, datetime
from threading import Event, Lock
from time import monotonic, sleep
from uuid import uuid4

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from lexlocal.application.ports.chat import (
    ChatCancelled,
    ChatCompletionResult,
    ChatIntakeRegistration,
    ChatIntakeResult,
)
from lexlocal.application.ports.document_workflow import (
    ActiveDocumentReadiness,
    ActiveDocumentResult,
    DocumentWorkflowCancelled,
    DocumentWorkflowStage,
    SelectedPdfReference,
)
from lexlocal.application.ports.embeddings import EmbeddingCancelled
from lexlocal.application.ports.evidence_sufficiency import (
    EvidenceSufficiencyCancelled,
)
from lexlocal.application.ports.indexing import IndexingCancelled
from lexlocal.application.ports.processing import ProcessingCancelled
from lexlocal.domain.identifiers import (
    ChatId,
    ChatMessageId,
    DocumentId,
    DocumentVersionId,
    IndexGenerationId,
    LocalModelId,
    ProcessingJobId,
    QaRequestId,
    WorkspaceId,
)
from lexlocal.domain.processing import IndexGeneration, IndexGenerationState
from lexlocal.domain.workspace import Workspace, WorkspaceProfile
from lexlocal.presentation.controller import PresentationController
from lexlocal.presentation.state import (
    CapabilityEvent,
    CapabilityState,
    DocumentReadyEvent,
    OperationCancelledEvent,
    OperationFailedEvent,
    OperationToken,
    PresentationErrorCode,
    ShutdownEvent,
    WorkerOperation,
)
from lexlocal.presentation.windows.main_window import (
    DocumentCommandBindings,
    MainWindow,
    ShutdownCommandBindings,
)
from lexlocal.presentation.workflow_worker import (
    ChatCancellationAdapter,
    DocumentCancellationAdapter,
    DocumentCommand,
    EmbeddingCancellationAdapter,
    EvidenceCancellationAdapter,
    IndexingCancellationAdapter,
    ProcessingCancellationAdapter,
    QuestionCommand,
    SerializedWorkflowHost,
    ThreadCancellationSource,
    WorkflowWorker,
)


@pytest.fixture(scope="module")
def application() -> QCoreApplication:
    existing = QCoreApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    if existing is not None:
        raise RuntimeError("a non-GUI Qt application already exists")
    return QApplication(["lexlocal-ui001-step3"])


def _id(identifier_type: type):
    return identifier_type(str(uuid4()))


def _active_document(workspace_id: WorkspaceId) -> ActiveDocumentResult:
    version_id = _id(DocumentVersionId)
    processing_job_id = _id(ProcessingJobId)
    return ActiveDocumentResult(
        workspace_id,
        _id(DocumentId),
        version_id,
        processing_job_id,
        "anonymous-synthetic.pdf",
        1,
        ActiveDocumentReadiness.READY,
        IndexGeneration(
            _id(IndexGenerationId),
            workspace_id,
            version_id,
            processing_job_id,
            _id(LocalModelId),
            "chunk-v1",
            "norm-v1",
            3,
            IndexGenerationState.ACTIVE,
        ),
    )


def _wait_until(
    application: QCoreApplication,
    predicate: Callable[[], bool],
    *,
    timeout: float = 3.0,
) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        application.processEvents()
        if predicate():
            return
        sleep(0.005)
    raise AssertionError("timed out waiting for Qt event")


def _event(spy: QSignalSpy, index: int = 0) -> object:
    return spy.at(index)[0]


class _DispatchGate(QObject):
    trigger = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()
        self.trigger.connect(self._block, Qt.ConnectionType.QueuedConnection)

    @Slot()
    def _block(self) -> None:
        self.entered.set()
        assert self.release.wait(3)


class _Session:
    def __init__(self, cancellation: ThreadCancellationSource) -> None:
        self.cancellation = cancellation
        self.started = Event()
        self.release = Event()
        self.after_intake = Event()
        self.calls: list[str] = []
        self.worker_threads: list[QThread] = []
        self.close_thread: QThread | None = None
        self.close_calls = 0
        self.mode = "normal"
        self.active_calls = 0
        self.max_active_calls = 0
        self._lock = Lock()
        self.document = _active_document(_id(WorkspaceId))
        self.qa_request_id = _id(QaRequestId)

    def list_workspaces(self) -> Sequence[Workspace]:
        return ()

    def create_workspace(
        self,
        display_name: str,
        profile: WorkspaceProfile | None = None,
    ) -> Workspace:
        raise NotImplementedError

    def select_workspace(self, workspace_id: WorkspaceId) -> WorkspaceId:
        return workspace_id

    def initialize_model_runtime(self) -> "_Runtime":
        raise AssertionError("bound session must not initialize another runtime")

    def build_document(
        self,
        selected: SelectedPdfReference,
        stage_sink: Callable[[DocumentWorkflowStage], None],
    ) -> ActiveDocumentResult:
        with self._lock:
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
        self.calls.append("document")
        self.worker_threads.append(QThread.currentThread())
        self.started.set()
        stage_sink(DocumentWorkflowStage.INDEXING)
        try:
            if self.mode in ("blocked", "late-success", "failure"):
                assert self.release.wait(3)
            if self.mode == "cancel":
                while not self.cancellation.is_cancelled:
                    sleep(0.002)
                DocumentCancellationAdapter(self.cancellation).raise_if_cancelled()
            if self.mode == "failure":
                raise RuntimeError("PRIVATE-WORKER-SENTINEL")
            return self.document
        finally:
            with self._lock:
                self.active_calls -= 1

    def materialize_question(
        self,
        document: ActiveDocumentResult,
        question: str,
    ) -> ChatIntakeRegistration:
        ChatCancellationAdapter(self.cancellation).raise_if_cancelled()
        self.calls.append("materialize")
        return ChatIntakeRegistration(
            document.workspace_id,
            _id(ChatId),
            _id(ChatMessageId),
            self.qa_request_id,
            document.document_id,
            document.document_version_id,
            document.active_generation,
            question,
            datetime(2026, 1, 1, tzinfo=UTC),
        )

    def start_question(
        self,
        registration: ChatIntakeRegistration,
    ) -> ChatIntakeResult:
        self.calls.append("start")
        self.after_intake.set()
        if self.mode == "question-precommit-cancel":
            while not self.cancellation.is_cancelled:
                sleep(0.002)
            ChatCancellationAdapter(self.cancellation).raise_if_cancelled()
        assert self.release.wait(3)
        return ChatIntakeResult(registration.qa_request_id, False)

    def complete_question(self, qa_request_id: QaRequestId) -> ChatCompletionResult:
        self.calls.append("complete")
        ChatCancellationAdapter(self.cancellation).raise_if_cancelled()
        raise AssertionError("test expects cancellation before completion")

    def close(self) -> None:
        self.close_calls += 1
        self.close_thread = QThread.currentThread()


class _Runtime:
    def __init__(
        self,
        session: _Session,
        *,
        resolve_error: Exception | None = None,
        bind_error: Exception | None = None,
    ) -> None:
        self.session = session
        self.resolve_error = resolve_error
        self.bind_error = bind_error
        self.closed = 0

    def resolve_capabilities(self) -> None:
        if self.resolve_error is not None:
            raise self.resolve_error

    def bind_persisted_identity(self, foundation: "_Foundation") -> _Session:
        if self.bind_error is not None:
            raise self.bind_error
        return self.session

    def close(self) -> None:
        self.closed += 1


class _Foundation:
    def __init__(self, runtime: _Runtime) -> None:
        self.runtime = runtime
        self.closed = 0

    def list_workspaces(self) -> Sequence[Workspace]:
        return ()

    def create_workspace(
        self,
        display_name: str,
        profile: WorkspaceProfile | None = None,
    ) -> Workspace:
        raise NotImplementedError

    def select_workspace(self, workspace_id: WorkspaceId) -> WorkspaceId:
        return workspace_id

    def initialize_model_runtime(self) -> _Runtime:
        return self.runtime

    def close(self) -> None:
        self.closed += 1


class _Builder:
    def __init__(
        self,
        foundation: _Foundation,
        *,
        failure: Exception | None = None,
    ) -> None:
        self.foundation = foundation
        self.failure = failure
        self.calls = 0
        self.thread: QThread | None = None

    def initialize_foundation(self) -> _Foundation:
        self.calls += 1
        self.thread = QThread.currentThread()
        if self.failure is not None:
            raise self.failure
        return self.foundation


def _worker_stack(
    session: _Session,
    *,
    resolve_error: Exception | None = None,
    bind_error: Exception | None = None,
    foundation_error: Exception | None = None,
) -> tuple[
    SerializedWorkflowHost,
    WorkflowWorker,
    _Builder,
    _Foundation,
    _Runtime,
]:
    source = session.cancellation
    runtime = _Runtime(session, resolve_error=resolve_error, bind_error=bind_error)
    foundation = _Foundation(runtime)
    builder = _Builder(foundation, failure=foundation_error)
    worker = WorkflowWorker(builder, source)
    host = SerializedWorkflowHost(worker, source)
    host.start()
    return host, worker, builder, foundation, runtime


def _initialize(
    application: QCoreApplication,
    host: SerializedWorkflowHost,
    worker: WorkflowWorker,
) -> CapabilityEvent:
    spy = QSignalSpy(worker.initialized)
    host.initialize_requested.emit(OperationToken(1, 0))
    _wait_until(application, lambda: spy.count() == 1)
    value = _event(spy)
    assert isinstance(value, CapabilityEvent)
    return value


def _block_worker(host: SerializedWorkflowHost) -> _DispatchGate:
    gate = _DispatchGate()
    gate.moveToThread(host.worker_thread)
    gate.trigger.emit()
    assert gate.entered.wait(2)
    return gate


def _shutdown_window(
    controller: PresentationController,
    host: SerializedWorkflowHost,
) -> MainWindow:
    window = MainWindow(
        controller=controller,
        document_commands=DocumentCommandBindings(
            host.document_requested.emit,
            host.request_cancellation,
        ),
        shutdown_commands=ShutdownCommandBindings(host.request_shutdown),
    )
    host.shutdown_finished.connect(window.accept_shutdown_complete)
    return window


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        ("foundation", CapabilityState.FATAL_STARTUP),
        ("resolve", CapabilityState.MODEL_UNAVAILABLE),
        ("bind", CapabilityState.FATAL_STARTUP),
    ],
)
def test_initialization_classification_depends_on_owning_stage(
    application: QCoreApplication,
    stage: str,
    expected: CapabilityState,
) -> None:
    source = ThreadCancellationSource()
    session = _Session(source)
    shared_error = RuntimeError("PRIVATE-INITIALIZATION-SENTINEL")
    host, worker, builder, foundation, runtime = _worker_stack(
        session,
        foundation_error=shared_error if stage == "foundation" else None,
        resolve_error=shared_error if stage == "resolve" else None,
        bind_error=shared_error if stage == "bind" else None,
    )
    try:
        event = _initialize(application, host, worker)
        assert event.state is expected
        assert builder.calls == 1
        assert builder.thread == host.worker_thread
        retry_spy = QSignalSpy(worker.initialized)
        host.initialize_requested.emit(OperationToken(2, 0))
        _wait_until(application, lambda: retry_spy.count() == 1)
        retry_event = _event(retry_spy)
        assert isinstance(retry_event, CapabilityEvent)
        assert retry_event.state is CapabilityState.FATAL_STARTUP
        assert builder.calls == 1
        if stage == "resolve":
            assert runtime.closed == 1
            assert foundation.closed == 0
        elif stage == "bind":
            assert runtime.closed == 1
            assert foundation.closed == 1
    finally:
        assert host.shutdown(OperationToken(99, 0))


def test_blocked_worker_keeps_gui_heartbeat_alive_and_closes_on_worker_thread(
    application: QCoreApplication,
) -> None:
    source = ThreadCancellationSource()
    session = _Session(source)
    session.mode = "blocked"
    host, worker, _, _, _ = _worker_stack(session)
    ready_spy = QSignalSpy(worker.document_ready)
    timer = QTimer()
    timer.setInterval(2)
    heartbeat = 0

    def tick() -> None:
        nonlocal heartbeat
        heartbeat += 1

    timer.timeout.connect(tick)
    try:
        assert _initialize(application, host, worker).state is CapabilityState.READY
        timer.start()
        host.document_requested.emit(
            DocumentCommand(OperationToken(2, 0), SelectedPdfReference("private.pdf"))
        )
        assert session.started.wait(2)
        _wait_until(application, lambda: heartbeat >= 3)
        assert ready_spy.count() == 0
        session.release.set()
        _wait_until(application, lambda: ready_spy.count() == 1)
        emitted = _event(ready_spy)
        assert isinstance(emitted, DocumentReadyEvent)
        assert session.worker_threads == [host.worker_thread]
    finally:
        timer.stop()
        session.release.set()
        assert host.shutdown(OperationToken(99, 0))
    assert session.close_thread == host.worker_thread
    assert host.worker_thread.isRunning() is False


def test_cancellation_is_observed_while_worker_slot_is_busy(
    application: QCoreApplication,
) -> None:
    source = ThreadCancellationSource()
    session = _Session(source)
    session.mode = "cancel"
    host, worker, _, _, _ = _worker_stack(session)
    cancelled_spy = QSignalSpy(worker.operation_cancelled)
    token = OperationToken(2, 0)
    try:
        assert _initialize(application, host, worker).state is CapabilityState.READY
        host.document_requested.emit(
            DocumentCommand(token, SelectedPdfReference("private.pdf"))
        )
        assert session.started.wait(2)
        assert host.request_cancellation(token) is True
        _wait_until(application, lambda: cancelled_spy.count() == 1)
        event = _event(cancelled_spy)
        assert isinstance(event, OperationCancelledEvent)
        assert event.operation is WorkerOperation.DOCUMENT
    finally:
        assert host.shutdown(OperationToken(99, 0))


def test_document_cancellation_before_worker_admission_is_not_lost(
    application: QCoreApplication,
) -> None:
    source = ThreadCancellationSource()
    session = _Session(source)
    session.mode = "cancel"
    host, worker, _, _, _ = _worker_stack(session)
    cancelled_spy = QSignalSpy(worker.operation_cancelled)
    token = OperationToken(2, 0)
    gate: _DispatchGate | None = None
    try:
        assert _initialize(application, host, worker).state is CapabilityState.READY
        gate = _block_worker(host)
        host.document_requested.emit(
            DocumentCommand(token, SelectedPdfReference("private.pdf"))
        )
        assert host.request_cancellation(token) is True
        assert session.started.is_set() is False

        gate.release.set()
        _wait_until(application, lambda: cancelled_spy.count() == 1)
        event = _event(cancelled_spy)
        assert isinstance(event, OperationCancelledEvent)
        assert event.token == token
        assert event.operation is WorkerOperation.DOCUMENT
    finally:
        if gate is not None:
            gate.release.set()
        assert host.shutdown(OperationToken(99, 0))


def test_question_cancellation_before_worker_admission_is_not_lost(
    application: QCoreApplication,
) -> None:
    source = ThreadCancellationSource()
    session = _Session(source)
    host, worker, _, _, _ = _worker_stack(session)
    cancelled_spy = QSignalSpy(worker.operation_cancelled)
    token = OperationToken(2, 0)
    gate: _DispatchGate | None = None
    try:
        assert _initialize(application, host, worker).state is CapabilityState.READY
        gate = _block_worker(host)
        host.question_requested.emit(
            QuestionCommand(token, session.document, "Anonymous synthetic question?")
        )
        assert host.request_cancellation(token) is True
        assert session.calls == []

        gate.release.set()
        _wait_until(application, lambda: cancelled_spy.count() == 1)
        event = _event(cancelled_spy)
        assert isinstance(event, OperationCancelledEvent)
        assert event.token == token
        assert event.operation is WorkerOperation.QUESTION
        assert event.qa_request_id is None
        assert session.calls == []
    finally:
        if gate is not None:
            gate.release.set()
        assert host.shutdown(OperationToken(99, 0))


def test_pending_cancellation_is_consumed_only_by_its_exact_token() -> None:
    source = ThreadCancellationSource()
    stale = OperationToken(1, 0)
    current = OperationToken(2, 0)

    assert source.cancel(stale) is True
    source.begin(current)
    assert source.is_cancelled is False
    source.finish(current)

    assert source.cancel(current) is True
    assert source.cancel(stale) is True
    source.begin(current)
    assert source.is_cancelled is True
    source.finish(current)

    source.begin(stale)
    assert source.is_cancelled is False
    source.finish(stale)


def test_shutdown_cancels_busy_work_closes_on_owner_thread_and_joins(
    application: QCoreApplication,
) -> None:
    source = ThreadCancellationSource()
    session = _Session(source)
    session.mode = "cancel"
    host, worker, _, _, _ = _worker_stack(session)
    shutdown_spy = QSignalSpy(worker.shutdown_complete)
    try:
        assert _initialize(application, host, worker).state is CapabilityState.READY
        host.document_requested.emit(
            DocumentCommand(OperationToken(2, 0), SelectedPdfReference("private.pdf"))
        )
        assert session.started.wait(2)

        assert host.shutdown(OperationToken(99, 0), timeout_ms=3000) is True

        assert session.close_thread == host.worker_thread
        assert host.worker_thread.isRunning() is False
        assert shutdown_spy.count() == 1
        assert _event(shutdown_spy) == ShutdownEvent(OperationToken(99, 0))
    finally:
        if host.worker_thread.isRunning():
            assert host.shutdown(OperationToken(99, 0))


def test_idle_window_close_waits_for_worker_owned_shutdown(
    application: QCoreApplication,
) -> None:
    source = ThreadCancellationSource()
    session = _Session(source)
    host, worker, _, _, _ = _worker_stack(session)
    controller = PresentationController()
    window = _shutdown_window(controller, host)
    try:
        assert _initialize(application, host, worker).state is CapabilityState.READY
        window.show()
        application.processEvents()

        window.close()
        _wait_until(
            application,
            lambda: not host.worker_thread.isRunning() and not window.isVisible(),
        )

        assert controller.state.shutting_down is True
        assert session.close_calls == 1
        assert session.close_thread == host.worker_thread
    finally:
        if host.worker_thread.isRunning():
            assert host.shutdown(OperationToken(99, 0))


def test_window_close_during_cancellable_work_uses_cooperative_shutdown(
    application: QCoreApplication,
) -> None:
    source = ThreadCancellationSource()
    session = _Session(source)
    session.mode = "cancel"
    host, worker, _, _, _ = _worker_stack(session)
    controller = PresentationController()
    window = _shutdown_window(controller, host)
    try:
        assert _initialize(application, host, worker).state is CapabilityState.READY
        window.show()
        application.processEvents()
        token = controller.begin(WorkerOperation.DOCUMENT)
        host.document_requested.emit(
            DocumentCommand(token, SelectedPdfReference("private.pdf"))
        )
        assert session.started.wait(2)

        window.close()
        _wait_until(
            application,
            lambda: not host.worker_thread.isRunning() and not window.isVisible(),
        )

        assert source.is_cancelled is False
        assert session.close_calls == 1
        assert session.close_thread == host.worker_thread
    finally:
        if host.worker_thread.isRunning():
            assert host.shutdown(OperationToken(99, 0))


def test_window_close_stays_pending_until_uninterruptible_work_returns(
    application: QCoreApplication,
) -> None:
    source = ThreadCancellationSource()
    session = _Session(source)
    session.mode = "blocked"
    host, worker, _, _, _ = _worker_stack(session)
    controller = PresentationController()
    window = _shutdown_window(controller, host)
    try:
        assert _initialize(application, host, worker).state is CapabilityState.READY
        window.show()
        application.processEvents()
        token = controller.begin(WorkerOperation.DOCUMENT)
        host.document_requested.emit(
            DocumentCommand(token, SelectedPdfReference("private.pdf"))
        )
        assert session.started.wait(2)

        window.close()
        application.processEvents()
        assert window.isVisible() is True
        assert host.worker_thread.isRunning() is True
        assert session.close_calls == 0

        session.release.set()
        _wait_until(
            application,
            lambda: not host.worker_thread.isRunning() and not window.isVisible(),
        )
        assert session.close_calls == 1
        assert session.close_thread == host.worker_thread
    finally:
        session.release.set()
        if host.worker_thread.isRunning():
            assert host.shutdown(OperationToken(99, 0))


def test_late_document_success_is_not_relabelled_cancelled(
    application: QCoreApplication,
) -> None:
    source = ThreadCancellationSource()
    session = _Session(source)
    session.mode = "late-success"
    host, worker, _, _, _ = _worker_stack(session)
    ready_spy = QSignalSpy(worker.document_ready)
    cancelled_spy = QSignalSpy(worker.operation_cancelled)
    token = OperationToken(2, 0)
    try:
        assert _initialize(application, host, worker).state is CapabilityState.READY
        host.document_requested.emit(
            DocumentCommand(token, SelectedPdfReference("private.pdf"))
        )
        assert session.started.wait(2)
        assert host.request_cancellation(token) is True
        session.release.set()
        _wait_until(application, lambda: ready_spy.count() == 1)
        assert cancelled_spy.count() == 0
    finally:
        session.release.set()
        assert host.shutdown(OperationToken(99, 0))


def test_durable_question_identity_is_retained_when_cancellation_races_intake(
    application: QCoreApplication,
) -> None:
    source = ThreadCancellationSource()
    session = _Session(source)
    host, worker, _, _, _ = _worker_stack(session)
    prepared_spy = QSignalSpy(worker.question_prepared)
    cancelled_spy = QSignalSpy(worker.operation_cancelled)
    token = OperationToken(2, 0)
    try:
        assert _initialize(application, host, worker).state is CapabilityState.READY
        host.question_requested.emit(
            QuestionCommand(token, session.document, "Anonymous synthetic question?")
        )
        assert session.after_intake.wait(2)
        assert host.request_cancellation(token) is True
        session.release.set()
        _wait_until(application, lambda: cancelled_spy.count() == 1)
        assert prepared_spy.count() == 1
        event = _event(cancelled_spy)
        assert isinstance(event, OperationCancelledEvent)
        assert event.qa_request_id == session.qa_request_id
        assert session.calls == ["materialize", "start", "complete"]
    finally:
        session.release.set()
        assert host.shutdown(OperationToken(99, 0))


def test_precommit_question_cancellation_does_not_claim_a_durable_identity(
    application: QCoreApplication,
) -> None:
    source = ThreadCancellationSource()
    session = _Session(source)
    session.mode = "question-precommit-cancel"
    host, worker, _, _, _ = _worker_stack(session)
    cancelled_spy = QSignalSpy(worker.operation_cancelled)
    token = OperationToken(2, 0)
    try:
        assert _initialize(application, host, worker).state is CapabilityState.READY
        host.question_requested.emit(
            QuestionCommand(token, session.document, "Anonymous synthetic question?")
        )
        assert session.after_intake.wait(2)
        assert host.request_cancellation(token) is True
        _wait_until(application, lambda: cancelled_spy.count() == 1)
        event = _event(cancelled_spy)
        assert isinstance(event, OperationCancelledEvent)
        assert event.qa_request_id is None
        assert session.calls == ["materialize", "start"]
    finally:
        assert host.shutdown(OperationToken(99, 0))


def test_commands_are_serialized_and_failures_are_safe(
    application: QCoreApplication,
) -> None:
    source = ThreadCancellationSource()
    session = _Session(source)
    session.mode = "failure"
    host, worker, _, _, _ = _worker_stack(session)
    failure_spy = QSignalSpy(worker.operation_failed)
    try:
        assert _initialize(application, host, worker).state is CapabilityState.READY
        host.document_requested.emit(
            DocumentCommand(OperationToken(2, 0), SelectedPdfReference("private-one.pdf"))
        )
        host.document_requested.emit(
            DocumentCommand(OperationToken(3, 0), SelectedPdfReference("private-two.pdf"))
        )
        assert session.started.wait(2)
        session.release.set()
        _wait_until(application, lambda: failure_spy.count() == 2)
        assert session.max_active_calls == 1
        assert session.calls == ["document", "document"]
        for index in range(2):
            event = _event(failure_spy, index)
            assert isinstance(event, OperationFailedEvent)
            assert event.code is PresentationErrorCode.DOCUMENT_FAILED
            assert "PRIVATE-WORKER-SENTINEL" not in repr(event)
            assert not any(
                isinstance(getattr(event, item.name), BaseException)
                for item in fields(event)
            )
    finally:
        session.release.set()
        assert host.shutdown(OperationToken(99, 0))


@pytest.mark.parametrize(
    ("adapter", "expected"),
    [
        (DocumentCancellationAdapter, DocumentWorkflowCancelled),
        (ProcessingCancellationAdapter, ProcessingCancelled),
        (IndexingCancellationAdapter, IndexingCancelled),
        (EmbeddingCancellationAdapter, EmbeddingCancelled),
        (EvidenceCancellationAdapter, EvidenceSufficiencyCancelled),
        (ChatCancellationAdapter, ChatCancelled),
    ],
)
def test_cancellation_adapters_raise_the_exact_owning_exception(
    adapter: type,
    expected: type[Exception],
) -> None:
    source = ThreadCancellationSource()
    token = OperationToken(1, 0)
    source.begin(token)
    assert source.cancel(token)

    with pytest.raises(expected) as captured:
        adapter(source).raise_if_cancelled()

    assert type(captured.value) is expected
