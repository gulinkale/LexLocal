"""Focused UI-001 Step 6 question-workflow presentation tests."""

from dataclasses import dataclass, field

import pytest
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QWidget,
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

from lexlocal.application.ports.chat import ChatCompletionResult, ChatIntakeResult
from lexlocal.application.ports.document_workflow import (
    ActiveDocumentReadiness,
    ActiveDocumentResult,
)
from lexlocal.domain.identifiers import (
    IndexGenerationId,
    LocalModelId,
    ProcessingJobId,
    QaRequestId,
)
from lexlocal.domain.processing import IndexGeneration, IndexGenerationState
from lexlocal.domain.retrieval import EvidenceSufficiency
from lexlocal.presentation.controller import PresentationController
from lexlocal.presentation.state import (
    CapabilityEvent,
    CapabilityState,
    DocumentReadyEvent,
    OperationCancelledEvent,
    OperationFailedEvent,
    PresentationErrorCode,
    QuestionCompletedEvent,
    QuestionDisplayState,
    QuestionPreparedEvent,
    WorkerOperation,
)
from lexlocal.presentation.windows.main_window import (
    MainWindow,
    QuestionCommandBindings,
)
from lexlocal.presentation.workflow_worker import QuestionCommand, RetryQuestionCommand


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication(["lexlocal-chat-ui-test"])


@dataclass
class _Commands:
    questions: list[QuestionCommand] = field(default_factory=list)
    retries: list[RetryQuestionCommand] = field(default_factory=list)
    cancellations: list[object] = field(default_factory=list)

    @property
    def bindings(self) -> QuestionCommandBindings:
        def cancel(token: object) -> bool:
            self.cancellations.append(token)
            return True

        return QuestionCommandBindings(
            self.questions.append,
            self.retries.append,
            cancel,
        )


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


def _result(state: EvidenceSufficiency, *, reused: bool = False) -> ChatCompletionResult:
    return ChatCompletionResult(_terminal_graph(_completion(state)), reused)


def _widget(window: MainWindow, widget_type: type[QWidget], name: str):
    result = window.findChild(widget_type, name)
    assert result is not None
    return result


def _ready_window(
    application: QApplication,
) -> tuple[MainWindow, PresentationController, _Commands]:
    controller = PresentationController()
    commands = _Commands()
    window = MainWindow(controller=controller, question_commands=commands.bindings)
    startup = controller.begin(WorkerOperation.STARTUP)
    controller.accept_capability(CapabilityEvent(startup, CapabilityState.READY))
    controller.select_workspace_locally(WORKSPACE_ID)
    document_token = controller.begin(WorkerOperation.DOCUMENT)
    controller.accept_document_ready(DocumentReadyEvent(document_token, _document()))
    window.show()
    application.processEvents()
    return window, controller, commands


def _start_question(
    application: QApplication,
    window: MainWindow,
    controller: PresentationController,
    question: str,
) -> object:
    question_input = _widget(window, QPlainTextEdit, "questionInput")
    ask = _widget(window, QPushButton, "askQuestion")
    question_input.setPlainText(question)
    application.processEvents()
    ask.click()
    application.processEvents()
    token = controller.state.operation_token
    assert token is not None
    return token


def test_ask_preserves_exact_question_and_uses_one_intake_command(
    application: QApplication,
) -> None:
    window, controller, commands = _ready_window(application)
    exact_question = "  What is the synthetic state? Ω\n"
    question_input = _widget(window, QPlainTextEdit, "questionInput")
    ask = _widget(window, QPushButton, "askQuestion")
    question_input.setPlainText(" \n")
    application.processEvents()
    assert ask.isEnabled() is False

    token = _start_question(application, window, controller, exact_question)

    assert len(commands.questions) == 1
    assert commands.questions[0].question == exact_question
    assert exact_question not in repr(commands.questions[0])
    assert controller.state.question is QuestionDisplayState.PREPARING
    assert _widget(window, QLabel, "chatStatus").text() == "Preparing question…"
    assert _widget(window, QPushButton, "cancelQuestion").isEnabled() is True
    assert token == commands.questions[0].token
    window.close()


@pytest.mark.parametrize(
    ("state", "display", "citation_count"),
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
def test_three_terminal_outcomes_render_exact_answer_and_ordered_citations(
    application: QApplication,
    state: EvidenceSufficiency,
    display: str,
    citation_count: int,
) -> None:
    window, controller, _commands = _ready_window(application)
    token = _start_question(application, window, controller, "Synthetic question?")
    window.accept_question_prepared(
        QuestionPreparedEvent(token, ChatIntakeResult(QA_REQUEST_ID, False))
    )
    window.accept_question_completed(QuestionCompletedEvent(token, _result(state)))
    application.processEvents()

    assert _widget(window, QLabel, "chatStatus").text() == display
    assert _widget(window, QPlainTextEdit, "answerText").toPlainText() == ANSWER
    citations = _widget(window, QListWidget, "citationList")
    assert citations.count() == citation_count
    assert [citations.item(index).text() for index in range(citations.count())] == [
        f"E{index}" for index in range(1, citation_count + 1)
    ]
    assert controller.state.chat_result is not None
    assert controller.state.actions.ask is False
    assert controller.state.actions.retry_question is False
    window.close()


def test_committed_identity_survives_cancel_and_retry_skips_intake(
    application: QApplication,
) -> None:
    window, controller, commands = _ready_window(application)
    token = _start_question(application, window, controller, "Synthetic question?")
    window.accept_question_prepared(
        QuestionPreparedEvent(token, ChatIntakeResult(QA_REQUEST_ID, False))
    )
    _widget(window, QPushButton, "cancelQuestion").click()
    assert commands.cancellations == [token]
    window.accept_cancelled(
        OperationCancelledEvent(
            token,
            WorkerOperation.QUESTION,
            qa_request_id=QA_REQUEST_ID,
        )
    )
    application.processEvents()

    assert controller.state.qa_request_id == QA_REQUEST_ID
    assert _widget(window, QPushButton, "retryQuestion").isEnabled() is True
    _widget(window, QPushButton, "retryQuestion").click()

    assert len(commands.questions) == 1
    assert len(commands.retries) == 1
    assert commands.retries[0].qa_request_id == QA_REQUEST_ID
    assert str(QA_REQUEST_ID) not in repr(commands.retries[0])
    window.close()


def test_precommit_failure_allows_new_intake_but_draft_gap_keeps_same_id(
    application: QApplication,
) -> None:
    window, controller, _commands = _ready_window(application)
    token = _start_question(application, window, controller, "Synthetic question?")
    window.accept_failed(
        OperationFailedEvent(
            token,
            WorkerOperation.QUESTION,
            PresentationErrorCode.QUESTION_FAILED,
        )
    )
    application.processEvents()
    assert controller.state.qa_request_id is None
    assert controller.state.actions.ask is True
    assert controller.state.actions.retry_question is False

    retry_token = controller.begin(WorkerOperation.QUESTION)
    window.accept_question_prepared(
        QuestionPreparedEvent(retry_token, ChatIntakeResult(QA_REQUEST_ID, False))
    )
    window.accept_failed(
        OperationFailedEvent(
            retry_token,
            WorkerOperation.QUESTION,
            PresentationErrorCode.QUESTION_DRAFT_INTERRUPTED,
            qa_request_id=QA_REQUEST_ID,
        )
    )
    application.processEvents()
    assert controller.state.qa_request_id == QA_REQUEST_ID
    assert controller.state.actions.retry_question is True
    assert "completion did not start" in _widget(
        window, QLabel, "chatStatus"
    ).text()
    window.close()


def test_mismatched_or_stale_terminal_result_never_overwrites_current_state(
    application: QApplication,
) -> None:
    window, controller, _commands = _ready_window(application)
    token = _start_question(application, window, controller, "Synthetic question?")
    other_id = QaRequestId("30000000-0000-4000-8000-000000000099")
    window.accept_question_prepared(
        QuestionPreparedEvent(token, ChatIntakeResult(other_id, False))
    )
    window.accept_question_completed(
        QuestionCompletedEvent(token, _result(EvidenceSufficiency.SUFFICIENT))
    )

    assert controller.state.question is QuestionDisplayState.FAILED
    assert controller.state.chat_result is None
    assert _widget(window, QPlainTextEdit, "answerText").toPlainText() == ""
    before = controller.state
    window.accept_question_completed(
        QuestionCompletedEvent(token, _result(EvidenceSufficiency.SUFFICIENT))
    )
    assert controller.state is before
    window.close()


def test_workspace_change_clears_question_and_terminal_display(
    application: QApplication,
) -> None:
    window, controller, _commands = _ready_window(application)
    question_input = _widget(window, QPlainTextEdit, "questionInput")
    question_input.setPlainText("Private synthetic question")
    controller.select_workspace_locally(
        type(WORKSPACE_ID)("10000000-0000-4000-8000-000000000099")
    )
    application.processEvents()

    assert question_input.toPlainText() == ""
    assert _widget(window, QPlainTextEdit, "answerText").toPlainText() == ""
    assert _widget(window, QListWidget, "citationList").count() == 0
    window.close()


def test_compatible_reused_terminal_is_rendered_once_and_disables_new_work(
    application: QApplication,
) -> None:
    window, controller, commands = _ready_window(application)
    token = _start_question(application, window, controller, "Synthetic question?")
    window.accept_question_prepared(
        QuestionPreparedEvent(token, ChatIntakeResult(QA_REQUEST_ID, True))
    )
    window.accept_question_completed(
        QuestionCompletedEvent(
            token,
            _result(EvidenceSufficiency.SUFFICIENT, reused=True),
        )
    )
    application.processEvents()

    assert controller.state.chat_result is not None
    assert controller.state.chat_result.reused is True
    assert _widget(window, QPushButton, "askQuestion").isEnabled() is False
    assert _widget(window, QPushButton, "retryQuestion").isEnabled() is False
    assert len(commands.questions) == 1
    assert commands.retries == []
    window.close()
