"""Integration coverage for the serialized UI-001 one-question workflow."""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from threading import Event
from time import monotonic, sleep

import pytest
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
)
from tests.unit.application.ports.test_chat import (
    ANSWER,
    DOCUMENT_ID,
    QA_REQUEST_ID,
    VERSION_ID,
    WORKSPACE_ID,
    _completion,
    _terminal_graph,
)

from lexlocal.application.ports.chat import (
    ChatCompletionResult,
    ChatIntakeRegistration,
    ChatIntakeResult,
)
from lexlocal.application.ports.document_workflow import (
    ActiveDocumentReadiness,
    ActiveDocumentResult,
    DocumentWorkflowStage,
    SelectedPdfReference,
)
from lexlocal.domain.identifiers import (
    ChatId,
    ChatMessageId,
    IndexGenerationId,
    LocalModelId,
    ProcessingJobId,
    QaRequestId,
    WorkspaceId,
)
from lexlocal.domain.processing import IndexGeneration, IndexGenerationState
from lexlocal.domain.retrieval import EvidenceSufficiency
from lexlocal.domain.workspace import Workspace, WorkspaceProfile
from lexlocal.presentation.controller import PresentationController
from lexlocal.presentation.state import CapabilityState, WorkerOperation
from lexlocal.presentation.windows.main_window import (
    MainWindow,
    QuestionCommandBindings,
)
from lexlocal.presentation.workflow_worker import (
    ChatCancellationAdapter,
    SerializedWorkflowHost,
    ThreadCancellationSource,
    WorkflowWorker,
)


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication(["lexlocal-chat-ui-integration-test"])


def _result(state: EvidenceSufficiency, *, reused: bool = False) -> ChatCompletionResult:
    return ChatCompletionResult(_terminal_graph(_completion(state)), reused)


def _document() -> ActiveDocumentResult:
    job_id = ProcessingJobId("81000000-0000-4000-8000-000000000001")
    return ActiveDocumentResult(
        WORKSPACE_ID,
        DOCUMENT_ID,
        VERSION_ID,
        job_id,
        "anonymous.pdf",
        2,
        ActiveDocumentReadiness.READY,
        IndexGeneration(
            IndexGenerationId("91000000-0000-4000-8000-000000000001"),
            WORKSPACE_ID,
            VERSION_ID,
            job_id,
            LocalModelId("61000000-0000-4000-8000-000000000001"),
            "chunk-v1",
            "normalization-v1",
            2,
            IndexGenerationState.ACTIVE,
        ),
    )


class _Session:
    def __init__(self, cancellation: ThreadCancellationSource) -> None:
        self.cancellation = cancellation
        now = datetime(2026, 1, 1, tzinfo=UTC)
        self.workspace = Workspace(WORKSPACE_ID, "Synthetic Workspace", now, now)
        self.document = _document()
        self.state = EvidenceSufficiency.SUFFICIENT
        self.calls: list[object] = []
        self.intake_committed = Event()
        self.release_completion = Event()
        self.block_completion = False
        self.fail_completion = False

    def list_workspaces(self) -> Sequence[Workspace]:
        return (self.workspace,)

    def create_workspace(
        self,
        display_name: str,
        profile: WorkspaceProfile | None = None,
    ) -> Workspace:
        del display_name, profile
        raise AssertionError

    def select_workspace(self, workspace_id: WorkspaceId) -> WorkspaceId:
        assert workspace_id == WORKSPACE_ID
        return workspace_id

    def initialize_model_runtime(self) -> "_Runtime":
        raise AssertionError

    def build_document(
        self,
        selected: SelectedPdfReference,
        stage_sink: Callable[[DocumentWorkflowStage], None],
    ) -> ActiveDocumentResult:
        del selected, stage_sink
        return self.document

    def materialize_question(
        self,
        document: ActiveDocumentResult,
        question: str,
    ) -> ChatIntakeRegistration:
        self.calls.append(("materialize", question))
        return ChatIntakeRegistration(
            document.workspace_id,
            ChatId("21000000-0000-4000-8000-000000000001"),
            ChatMessageId("41000000-0000-4000-8000-000000000001"),
            QA_REQUEST_ID,
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
        self.calls.append(("intake", registration.qa_request_id))
        self.intake_committed.set()
        return ChatIntakeResult(registration.qa_request_id, False)

    def complete_question(self, qa_request_id: QaRequestId) -> ChatCompletionResult:
        self.calls.append(("complete", qa_request_id))
        if self.block_completion:
            assert self.release_completion.wait(3)
        ChatCancellationAdapter(self.cancellation).raise_if_cancelled()
        if self.fail_completion:
            raise RuntimeError("PRIVATE-PROVIDER-SENTINEL")
        return _result(self.state)

    def close(self) -> None:
        return None


class _Runtime:
    def __init__(self, session: _Session) -> None:
        self.session = session

    def resolve_capabilities(self) -> None:
        return None

    def bind_persisted_identity(self, foundation: object) -> _Session:
        del foundation
        return self.session

    def close(self) -> None:
        return None


class _Foundation:
    def __init__(self, session: _Session) -> None:
        self.session = session

    def list_workspaces(self) -> Sequence[Workspace]:
        return self.session.list_workspaces()

    def create_workspace(
        self,
        display_name: str,
        profile: WorkspaceProfile | None = None,
    ) -> Workspace:
        return self.session.create_workspace(display_name, profile)

    def select_workspace(self, workspace_id: WorkspaceId) -> WorkspaceId:
        return self.session.select_workspace(workspace_id)

    def initialize_model_runtime(self) -> _Runtime:
        return _Runtime(self.session)

    def close(self) -> None:
        return None


class _Builder:
    def __init__(self, session: _Session) -> None:
        self.session = session

    def initialize_foundation(self) -> _Foundation:
        return _Foundation(self.session)


def _wait_until(
    application: QApplication,
    predicate: Callable[[], bool],
    timeout: float = 3.0,
) -> None:
    deadline = monotonic() + timeout
    while not predicate():
        application.processEvents()
        if monotonic() >= deadline:
            raise AssertionError("timed out waiting for Qt event")
        sleep(0.002)
    application.processEvents()


def _stack(
    application: QApplication,
) -> tuple[
    MainWindow,
    PresentationController,
    SerializedWorkflowHost,
    _Session,
]:
    cancellation = ThreadCancellationSource()
    session = _Session(cancellation)
    worker = WorkflowWorker(_Builder(session), cancellation)
    host = SerializedWorkflowHost(worker, cancellation)
    controller = PresentationController()
    window = MainWindow(
        controller=controller,
        question_commands=QuestionCommandBindings(
            host.question_requested.emit,
            host.question_retry_requested.emit,
            host.request_cancellation,
        ),
    )
    worker.initialized.connect(window.accept_capability)
    worker.question_prepared.connect(window.accept_question_prepared)
    worker.question_completed.connect(window.accept_question_completed)
    worker.operation_cancelled.connect(window.accept_cancelled)
    worker.operation_failed.connect(window.accept_failed)
    host.start()
    host.initialize_requested.emit(controller.begin(WorkerOperation.STARTUP))
    _wait_until(
        application,
        lambda: controller.state.capability is CapabilityState.READY,
    )
    controller.select_workspace_locally(WORKSPACE_ID)
    document_token = controller.begin(WorkerOperation.DOCUMENT)
    from lexlocal.presentation.state import DocumentReadyEvent

    controller.accept_document_ready(DocumentReadyEvent(document_token, session.document))
    window.show()
    application.processEvents()
    return window, controller, host, session


@pytest.mark.parametrize(
    ("state", "status", "citation_count"),
    [
        (EvidenceSufficiency.SUFFICIENT, "Grounded answer", 1),
        (
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
            "Related evidence; insufficient support.",
            1,
        ),
        (EvidenceSufficiency.INSUFFICIENT, "Insufficient evidence.", 0),
    ],
)
def test_serialized_intake_completion_and_terminal_rendering(
    application: QApplication,
    state: EvidenceSufficiency,
    status: str,
    citation_count: int,
) -> None:
    window, controller, host, session = _stack(application)
    try:
        session.state = state
        question = "  Exact synthetic question Ω?\n"
        question_input = window.findChild(QPlainTextEdit, "questionInput")
        ask = window.findChild(QPushButton, "askQuestion")
        assert question_input is not None and ask is not None
        question_input.setPlainText(question)
        ask.click()
        _wait_until(application, lambda: controller.state.chat_result is not None)

        assert session.calls == [
            ("materialize", question),
            ("intake", QA_REQUEST_ID),
            ("complete", QA_REQUEST_ID),
        ]
        chat_status = window.findChild(QLabel, "chatStatus")
        answer = window.findChild(QPlainTextEdit, "answerText")
        citations = window.findChild(QListWidget, "citationList")
        assert chat_status is not None and chat_status.text() == status
        assert answer is not None and answer.toPlainText() == ANSWER
        assert citations is not None and citations.count() == citation_count
    finally:
        assert host.shutdown(controller.begin(WorkerOperation.SHUTDOWN))
        window.close()


def test_post_intake_cancellation_enters_chat_and_retry_uses_same_id(
    application: QApplication,
) -> None:
    window, controller, host, session = _stack(application)
    try:
        session.block_completion = True
        question_input = window.findChild(QPlainTextEdit, "questionInput")
        ask = window.findChild(QPushButton, "askQuestion")
        cancel = window.findChild(QPushButton, "cancelQuestion")
        retry = window.findChild(QPushButton, "retryQuestion")
        assert all(item is not None for item in (question_input, ask, cancel, retry))
        assert question_input is not None
        question_input.setPlainText("Synthetic cancellation question?")
        assert ask is not None
        ask.click()
        assert session.intake_committed.wait(2)
        _wait_until(application, lambda: controller.state.qa_request_id == QA_REQUEST_ID)
        assert cancel is not None
        cancel.click()
        session.release_completion.set()
        _wait_until(
            application,
            lambda: controller.state.question.value == "CANCELLED",
        )

        assert session.calls[-1] == ("complete", QA_REQUEST_ID)
        session.block_completion = False
        assert retry is not None
        retry.click()
        _wait_until(application, lambda: controller.state.chat_result is not None)
        assert [call[0] for call in session.calls].count("materialize") == 1
        assert [call[0] for call in session.calls].count("intake") == 1
        assert session.calls[-1] == ("complete", QA_REQUEST_ID)
    finally:
        session.release_completion.set()
        if controller.state.active_operation is None:
            shutdown = controller.begin(WorkerOperation.SHUTDOWN)
        else:
            shutdown = controller.state.operation_token
            assert shutdown is not None
        assert host.shutdown(shutdown)
        window.close()


def test_completion_failure_is_sanitized_and_same_id_remains_retryable(
    application: QApplication,
) -> None:
    window, controller, host, session = _stack(application)
    try:
        session.fail_completion = True
        question_input = window.findChild(QPlainTextEdit, "questionInput")
        ask = window.findChild(QPushButton, "askQuestion")
        assert question_input is not None and ask is not None
        question_input.setPlainText("Synthetic failure question?")
        ask.click()
        _wait_until(application, lambda: controller.state.actions.retry_question)

        status = window.findChild(QLabel, "chatStatus")
        assert status is not None
        assert status.text() == "The question could not be completed."
        assert "PRIVATE-PROVIDER-SENTINEL" not in status.text()
        assert controller.state.qa_request_id == QA_REQUEST_ID
        assert controller.state.chat_result is None
    finally:
        assert host.shutdown(controller.begin(WorkerOperation.SHUTDOWN))
        window.close()
