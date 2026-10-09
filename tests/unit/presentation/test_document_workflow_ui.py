from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QLabel,
    QPushButton,
    QWidget,
)

from lexlocal.application.ports.document_workflow import (
    ActiveDocumentReadiness,
    ActiveDocumentResult,
    DocumentWorkflowDisposition,
    DocumentWorkflowStage,
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
from lexlocal.domain.workspace import Workspace
from lexlocal.presentation.controller import PresentationController
from lexlocal.presentation.state import (
    CapabilityEvent,
    CapabilityState,
    DocumentDisplayState,
    DocumentPhaseEvent,
    DocumentReadyEvent,
    OperationCancelledEvent,
    OperationFailedEvent,
    PresentationErrorCode,
    WorkerOperation,
    WorkspaceListEvent,
    WorkspaceSelectedEvent,
)
from lexlocal.presentation.windows.main_window import (
    DocumentCommandBindings,
    MainWindow,
    WorkspaceCommandBindings,
)
from lexlocal.presentation.workflow_worker import (
    CreateWorkspaceCommand,
    DocumentCommand,
    SelectWorkspaceCommand,
)


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication(["lexlocal-document-ui-test"])


@dataclass
class _Commands:
    list_tokens: list[object] = field(default_factory=list)
    create_commands: list[CreateWorkspaceCommand] = field(default_factory=list)
    select_commands: list[SelectWorkspaceCommand] = field(default_factory=list)
    document_commands: list[DocumentCommand] = field(default_factory=list)
    cancellations: list[object] = field(default_factory=list)

    @property
    def workspaces(self) -> WorkspaceCommandBindings:
        return WorkspaceCommandBindings(
            self.list_tokens.append,
            self.create_commands.append,
            self.select_commands.append,
        )

    @property
    def documents(self) -> DocumentCommandBindings:
        def cancel(token: object) -> bool:
            self.cancellations.append(token)
            return True

        return DocumentCommandBindings(self.document_commands.append, cancel)


def _id(identifier_type: type):
    return identifier_type(str(uuid4()))


def _workspace(name: str = "Synthetic Workspace") -> Workspace:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Workspace(_id(WorkspaceId), name, now, now)


def _active_document(
    workspace_id: WorkspaceId,
    readiness: ActiveDocumentReadiness = ActiveDocumentReadiness.READY,
) -> ActiveDocumentResult:
    version_id = _id(DocumentVersionId)
    job_id = _id(ProcessingJobId)
    generation = IndexGeneration(
        _id(IndexGenerationId),
        workspace_id,
        version_id,
        job_id,
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
        job_id,
        "anonymous.pdf",
        2,
        readiness,
        generation,
    )


def _widget(window: MainWindow, widget_type: type[QWidget], name: str):
    widget = window.findChild(widget_type, name)
    assert widget is not None
    return widget


def _selected_window(
    application: QApplication,
) -> tuple[MainWindow, PresentationController, _Commands, Workspace]:
    controller = PresentationController()
    commands = _Commands()
    workspace = _workspace()
    window = MainWindow(
        controller=controller,
        workspace_commands=commands.workspaces,
        document_commands=commands.documents,
    )
    startup = controller.begin(WorkerOperation.STARTUP)
    window.accept_capability(CapabilityEvent(startup, CapabilityState.READY))
    window.accept_workspace_listed(
        WorkspaceListEvent(commands.list_tokens[0], (workspace,))
    )
    workspace_list = _widget(window, QComboBox, "workspaceList")
    workspace_list.setCurrentIndex(0)
    _widget(window, QPushButton, "selectWorkspace").click()
    select = commands.select_commands[0]
    window.accept_workspace_selected(
        WorkspaceSelectedEvent(select.token, workspace.id)
    )
    window.show()
    application.processEvents()
    return window, controller, commands, workspace


def _choose_pdf(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    calls: list[tuple[object, str, str, str]],
) -> None:
    def choose(
        parent: object,
        title: str,
        directory: str,
        file_filter: str,
    ) -> tuple[str, str]:
        calls.append((parent, title, directory, file_filter))
        return path, "PDF files (*.pdf)"

    monkeypatch.setattr(QFileDialog, "getOpenFileName", choose)


def test_dialog_cancel_does_not_start_document_work(
    application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, controller, commands, _ = _selected_window(application)
    _choose_pdf(monkeypatch, "", [])

    _widget(window, QPushButton, "importPdf").click()

    assert commands.document_commands == []
    assert controller.state.document is DocumentDisplayState.EMPTY
    window.close()


def test_single_pdf_selection_stays_private_and_renders_exact_phases(
    application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_path = "/private/synthetic/PRIVATE-PATH-SENTINEL.pdf"
    calls: list[tuple[object, str, str, str]] = []
    window, controller, commands, _ = _selected_window(application)
    _choose_pdf(monkeypatch, private_path, calls)
    status = _widget(window, QLabel, "documentStatus")
    import_pdf = _widget(window, QPushButton, "importPdf")
    cancel = _widget(window, QPushButton, "cancelDocument")

    import_pdf.click()

    assert len(calls) == 1
    assert calls[0][0] is window
    assert calls[0][2] == ""
    assert calls[0][3] == "PDF files (*.pdf)"
    assert len(commands.document_commands) == 1
    command = commands.document_commands[0]
    assert command.selected.value == private_path
    assert private_path not in repr(command)
    assert controller.state.document is DocumentDisplayState.IMPORTING
    assert status.text() == "Importing…"
    assert import_pdf.isEnabled() is False
    assert cancel.isEnabled() is True

    expected = (
        (DocumentWorkflowStage.EXTRACTING, "Extracting text…"),
        (DocumentWorkflowStage.INDEXING, "Building index…"),
        (DocumentWorkflowStage.EMBEDDING, "Generating embeddings…"),
    )
    for stage, text in expected:
        window.accept_document_phase(DocumentPhaseEvent(command.token, stage))
        assert status.text() == text

    displayed = " ".join(label.text() for label in window.findChildren(QLabel))
    assert private_path not in displayed
    window.close()


@pytest.mark.parametrize(
    ("readiness", "status_text"),
    [
        (ActiveDocumentReadiness.READY, "Ready"),
        (ActiveDocumentReadiness.READY_WITH_WARNINGS, "Ready with warnings"),
    ],
)
def test_ready_result_is_retained_and_enables_only_the_chat_section(
    application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    readiness: ActiveDocumentReadiness,
    status_text: str,
) -> None:
    window, controller, commands, workspace = _selected_window(application)
    _choose_pdf(monkeypatch, "/private/not-rendered.pdf", [])
    _widget(window, QPushButton, "importPdf").click()
    command = commands.document_commands[0]
    result = _active_document(workspace.id, readiness)

    window.accept_document_ready(DocumentReadyEvent(command.token, result))

    assert controller.state.active_document is result
    assert controller.state.document is (
        DocumentDisplayState.READY
        if readiness is ActiveDocumentReadiness.READY
        else DocumentDisplayState.READY_WITH_WARNINGS
    )
    assert _widget(window, QLabel, "documentName").text() == (
        "anonymous.pdf — 2 pages"
    )
    assert _widget(window, QLabel, "documentStatus").text() == status_text
    assert _widget(window, QPushButton, "importPdf").isEnabled() is False
    assert _widget(window, QGroupBox, "chatSection").isEnabled() is True
    window.close()


@pytest.mark.parametrize(
    ("disposition", "expected_state", "import_enabled", "status_text"),
    [
        (
            DocumentWorkflowDisposition.NOT_REGISTERED,
            DocumentDisplayState.EMPTY,
            True,
            "Cancelled.",
        ),
        (
            DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            DocumentDisplayState.CANCELLED,
            False,
            "Cancelled; the registered document is incomplete and is not ready.",
        ),
    ],
)
def test_cancellation_disposition_controls_retry_truthfully(
    application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    disposition: DocumentWorkflowDisposition,
    expected_state: DocumentDisplayState,
    import_enabled: bool,
    status_text: str,
) -> None:
    window, controller, commands, _ = _selected_window(application)
    _choose_pdf(monkeypatch, "/private/not-rendered.pdf", [])
    _widget(window, QPushButton, "importPdf").click()
    command = commands.document_commands[0]

    _widget(window, QPushButton, "cancelDocument").click()
    assert commands.cancellations == [command.token]
    assert controller.state.document is DocumentDisplayState.CANCELLING
    window.accept_cancelled(
        OperationCancelledEvent(
            command.token,
            WorkerOperation.DOCUMENT,
            disposition,
        )
    )

    assert controller.state.document is expected_state
    assert controller.state.registered_incomplete_document is (
        disposition is DocumentWorkflowDisposition.REGISTERED_INCOMPLETE
    )
    assert _widget(window, QPushButton, "importPdf").isEnabled() is import_enabled
    assert _widget(window, QLabel, "documentStatus").text() == status_text
    window.close()


@pytest.mark.parametrize(
    ("code", "disposition", "expected_state", "import_enabled", "expected_message"),
    [
        (
            PresentationErrorCode.PDF_UNREADABLE,
            DocumentWorkflowDisposition.NOT_REGISTERED,
            DocumentDisplayState.EMPTY,
            True,
            "The selected PDF cannot be imported.",
        ),
        (
            PresentationErrorCode.PDF_DUPLICATE,
            DocumentWorkflowDisposition.NOT_REGISTERED,
            DocumentDisplayState.EMPTY,
            True,
            "This PDF is already registered in the selected workspace.",
        ),
        (
            PresentationErrorCode.DOCUMENT_FAILED,
            DocumentWorkflowDisposition.NOT_REGISTERED,
            DocumentDisplayState.EMPTY,
            True,
            "Document processing failed; no document was registered.",
        ),
        (
            PresentationErrorCode.NATIVE_TEXT_UNAVAILABLE,
            DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            DocumentDisplayState.FAILED,
            False,
            "This PDF has no usable native text in M1; OCR is unavailable.",
        ),
        (
            PresentationErrorCode.DOCUMENT_REGISTERED_INCOMPLETE,
            DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            DocumentDisplayState.FAILED,
            False,
            "Document processing failed; the registered document is incomplete and is not ready.",
        ),
    ],
)
def test_typed_failure_uses_safe_copy_and_disposition(
    application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    code: PresentationErrorCode,
    disposition: DocumentWorkflowDisposition,
    expected_state: DocumentDisplayState,
    import_enabled: bool,
    expected_message: str,
) -> None:
    private_path = "/private/PRIVATE-PATH-SENTINEL.pdf"
    window, controller, commands, _ = _selected_window(application)
    _choose_pdf(monkeypatch, private_path, [])
    _widget(window, QPushButton, "importPdf").click()
    command = commands.document_commands[0]

    window.accept_failed(
        OperationFailedEvent(
            command.token,
            WorkerOperation.DOCUMENT,
            code,
            disposition,
        )
    )

    assert controller.state.document is expected_state
    assert _widget(window, QPushButton, "importPdf").isEnabled() is import_enabled
    status = _widget(window, QLabel, "documentStatus").text()
    assert status == expected_message
    assert private_path not in status
    window.close()


def test_committed_ready_wins_late_cancel_and_cross_workspace_result_fails_closed(
    application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, controller, commands, workspace = _selected_window(application)
    _choose_pdf(monkeypatch, "/private/not-rendered.pdf", [])
    _widget(window, QPushButton, "importPdf").click()
    command = commands.document_commands[0]
    _widget(window, QPushButton, "cancelDocument").click()
    ready = _active_document(workspace.id)

    window.accept_document_ready(DocumentReadyEvent(command.token, ready))
    window.accept_cancelled(
        OperationCancelledEvent(
            command.token,
            WorkerOperation.DOCUMENT,
            DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
        )
    )

    assert controller.state.document is DocumentDisplayState.READY
    assert controller.state.active_document is ready
    window.close()

    second_window, second_controller, second_commands, _ = _selected_window(application)
    _choose_pdf(monkeypatch, "/private/not-rendered.pdf", [])
    _widget(second_window, QPushButton, "importPdf").click()
    second_command = second_commands.document_commands[0]
    substitution = _active_document(_id(WorkspaceId))
    second_window.accept_document_ready(
        DocumentReadyEvent(second_command.token, substitution)
    )

    assert second_controller.state.document is DocumentDisplayState.EMPTY
    assert second_controller.state.active_document is None
    assert _widget(second_window, QGroupBox, "chatSection").isEnabled() is False
    assert _widget(second_window, QLabel, "documentStatus").text() == (
        "Document processing failed; no document was registered."
    )
    second_window.close()


def test_model_unavailable_disables_document_import(
    application: QApplication,
) -> None:
    controller = PresentationController()
    commands = _Commands()
    window = MainWindow(
        controller=controller,
        workspace_commands=commands.workspaces,
        document_commands=commands.documents,
    )
    startup = controller.begin(WorkerOperation.STARTUP)
    window.accept_capability(
        CapabilityEvent(startup, CapabilityState.MODEL_UNAVAILABLE)
    )
    workspace = _workspace()
    window.accept_workspace_listed(
        WorkspaceListEvent(commands.list_tokens[0], (workspace,))
    )
    selection = controller.begin(WorkerOperation.SELECT_WORKSPACE)
    window.accept_workspace_selected(WorkspaceSelectedEvent(selection, workspace.id))

    assert _widget(window, QGroupBox, "documentSection").isEnabled() is False
    assert _widget(window, QPushButton, "importPdf").isEnabled() is False
    window.close()
