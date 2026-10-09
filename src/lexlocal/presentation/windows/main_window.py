"""Render the minimal UI-001 desktop shell on the GUI thread."""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lexlocal.application.ports.document_workflow import SelectedPdfReference
from lexlocal.domain.workspace import Workspace
from lexlocal.presentation.controller import PresentationController
from lexlocal.presentation.state import (
    PRESENTATION_MESSAGES,
    CapabilityEvent,
    CapabilityState,
    DocumentDisplayState,
    DocumentNotice,
    OperationToken,
    PresentationErrorCode,
    PresentationState,
    QuestionDisplayState,
    WorkerOperation,
    WorkspaceNotice,
)
from lexlocal.presentation.windows.citation_dialog import (
    CitationDialog,
    CitationUnavailable,
    resolve_citation_detail,
)
from lexlocal.presentation.workflow_worker import (
    CreateWorkspaceCommand,
    DocumentCommand,
    QuestionCommand,
    RetryQuestionCommand,
    SelectWorkspaceCommand,
)

_DEVELOPMENT_WARNING = (
    "Development mode — anonymous synthetic documents only. "
    "Not for real user documents."
)
_NO_ACTIVE_WORKSPACE = "No workspace selected."
_NO_DOCUMENT = "No document selected."
_NO_QUESTION = "No question submitted."


@dataclass(frozen=True, slots=True)
class WorkspaceCommandBindings:
    """Connect the shell to the existing serialized worker command boundary."""

    list_workspaces: Callable[[OperationToken], None]
    create_workspace: Callable[[CreateWorkspaceCommand], None]
    select_workspace: Callable[[SelectWorkspaceCommand], None]


@dataclass(frozen=True, slots=True)
class DocumentCommandBindings:
    """Connect document controls to the existing worker/cancellation boundary."""

    run_document: Callable[[DocumentCommand], None]
    request_cancellation: Callable[[OperationToken], bool]


@dataclass(frozen=True, slots=True)
class QuestionCommandBindings:
    """Connect one-question controls to the existing CHAT worker boundary."""

    run_question: Callable[[QuestionCommand], None]
    retry_question: Callable[[RetryQuestionCommand], None]
    request_cancellation: Callable[[OperationToken], bool]


@dataclass(frozen=True, slots=True)
class ShutdownCommandBindings:
    """Connect a real window close to the worker-owned shutdown lifecycle."""

    request_shutdown: Callable[[OperationToken | None, OperationToken], bool]


class MainWindow(QMainWindow):
    """Show workspace scope without owning Application or Infrastructure behavior."""

    def __init__(
        self,
        *,
        controller: PresentationController | None = None,
        workspace_commands: WorkspaceCommandBindings | None = None,
        document_commands: DocumentCommandBindings | None = None,
        question_commands: QuestionCommandBindings | None = None,
        shutdown_commands: ShutdownCommandBindings | None = None,
    ) -> None:
        super().__init__()
        self._controller = controller or PresentationController()
        self._workspace_commands = workspace_commands
        self._document_commands = document_commands
        self._question_commands = question_commands
        self._shutdown_commands = shutdown_commands
        self._shutdown_requested = False
        self._shutdown_complete = False
        self._rendered_workspace_id = None
        self._citation_dialog: CitationDialog | None = None
        self._citation_mapping_available = False

        self.setWindowTitle("LexLocal")
        self.resize(960, 640)

        self._pages = QStackedWidget()
        self._workflow_page = self._build_workflow_page()
        self._fatal_page = self._build_fatal_page()
        self._pages.addWidget(self._workflow_page)
        self._pages.addWidget(self._fatal_page)
        self.setCentralWidget(self._pages)

        self._controller.state_changed.connect(self._render)
        self._workspace_name.textChanged.connect(self._render_current_state)
        self._workspace_list.currentIndexChanged.connect(self._render_current_state)
        self._create_workspace.clicked.connect(self._request_create_workspace)
        self._select_workspace.clicked.connect(self._request_select_workspace)
        self._import_pdf.clicked.connect(self._request_import_pdf)
        self._cancel_document.clicked.connect(self._request_document_cancellation)
        self._question_input.textChanged.connect(self._render_current_state)
        self._ask_question.clicked.connect(self._request_question)
        self._retry_question.clicked.connect(self._request_question_retry)
        self._cancel_question.clicked.connect(self._request_question_cancellation)
        self._citations.currentRowChanged.connect(self._update_citation_action)
        self._open_citation.clicked.connect(self._open_selected_citation)

        self.setTabOrder(self._workspace_name, self._create_workspace)
        self.setTabOrder(self._create_workspace, self._workspace_list)
        self.setTabOrder(self._workspace_list, self._select_workspace)
        self.setTabOrder(self._select_workspace, self._import_pdf)
        self.setTabOrder(self._import_pdf, self._cancel_document)
        self.setTabOrder(self._cancel_document, self._question_input)
        self.setTabOrder(self._question_input, self._ask_question)
        self.setTabOrder(self._ask_question, self._retry_question)
        self.setTabOrder(self._retry_question, self._cancel_question)
        self.setTabOrder(self._cancel_question, self._citations)
        self.setTabOrder(self._citations, self._open_citation)
        self._render(self._controller.state)

    @property
    def controller(self) -> PresentationController:
        """Expose the Presentation controller for composition and focused tests."""

        return self._controller

    def closeEvent(self, event: QCloseEvent) -> None:
        """Keep the window alive until worker-owned resources close safely."""

        if self._shutdown_complete or self._shutdown_commands is None:
            self._close_citation_dialog()
            event.accept()
            return
        event.ignore()
        if self._shutdown_requested:
            return
        self._shutdown_requested = True
        active_token = self._controller.state.operation_token
        shutdown_token = self._controller.begin_shutdown()
        if self._shutdown_commands.request_shutdown(active_token, shutdown_token):
            self._shutdown_complete = True
            self._close_citation_dialog()
            event.accept()

    @Slot()
    def accept_shutdown_complete(self) -> None:
        """Finish a pending close only after the worker thread has stopped."""

        if not self._shutdown_requested:
            return
        self._shutdown_complete = True
        self.close()

    @Slot(object)
    def accept_capability(self, event: object) -> None:
        """Accept startup state and request the first workspace list when usable."""

        before = self._controller.state
        self._controller.accept_capability(event)
        state = self._controller.state
        if (
            state is not before
            and isinstance(event, CapabilityEvent)
            and event.state
            in (CapabilityState.READY, CapabilityState.MODEL_UNAVAILABLE)
            and self._workspace_commands is not None
        ):
            token = self._controller.begin(WorkerOperation.LIST_WORKSPACES)
            self._workspace_commands.list_workspaces(token)

    @Slot(object)
    def accept_workspace_listed(self, event: object) -> None:
        self._controller.accept_workspace_listed(event)

    @Slot(object)
    def accept_workspace_created(self, event: object) -> None:
        self._controller.accept_workspace_created(event)

    @Slot(object)
    def accept_workspace_selected(self, event: object) -> None:
        self._controller.accept_workspace_selected(event)

    @Slot(object)
    def accept_document_phase(self, event: object) -> None:
        self._controller.accept_document_phase(event)

    @Slot(object)
    def accept_document_ready(self, event: object) -> None:
        self._controller.accept_document_ready(event)

    @Slot(object)
    def accept_question_prepared(self, event: object) -> None:
        self._controller.accept_question_prepared(event)

    @Slot(object)
    def accept_question_completed(self, event: object) -> None:
        self._controller.accept_question_completed(event)

    @Slot(object)
    def accept_cancelled(self, event: object) -> None:
        self._controller.accept_cancelled(event)

    @Slot(object)
    def accept_failed(self, event: object) -> None:
        self._controller.accept_failed(event)

    def _build_workflow_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("workflowPage")
        layout = QVBoxLayout(page)

        self._development_warning = QLabel(_DEVELOPMENT_WARNING)
        self._development_warning.setObjectName("developmentWarning")
        self._development_warning.setWordWrap(True)
        self._development_warning.setAccessibleName("Development safety warning")
        layout.addWidget(self._development_warning)

        self._capability_status = QLabel()
        self._capability_status.setObjectName("capabilityStatus")
        self._capability_status.setWordWrap(True)
        self._capability_status.setAccessibleName("Local model status")
        layout.addWidget(self._capability_status)

        self._workspace_group = self._build_workspace_group()
        layout.addWidget(self._workspace_group)

        self._document_group = QGroupBox("Document")
        self._document_group.setObjectName("documentSection")
        document_layout = QVBoxLayout(self._document_group)
        document_actions = QHBoxLayout()
        self._import_pdf = QPushButton("Import PDF")
        self._import_pdf.setObjectName("importPdf")
        self._import_pdf.setAccessibleName("Import one PDF")
        self._cancel_document = QPushButton("Cancel Processing")
        self._cancel_document.setObjectName("cancelDocument")
        self._cancel_document.setAccessibleName("Cancel document processing")
        document_actions.addWidget(self._import_pdf)
        document_actions.addWidget(self._cancel_document)
        document_actions.addStretch()
        document_layout.addLayout(document_actions)
        document_details = QFormLayout()
        self._document_name = QLabel(_NO_DOCUMENT)
        self._document_name.setObjectName("documentName")
        self._document_name.setAccessibleName("Current document")
        document_details.addRow("Current document", self._document_name)
        document_layout.addLayout(document_details)
        self._document_status = QLabel(_NO_DOCUMENT)
        self._document_status.setObjectName("documentStatus")
        self._document_status.setAccessibleName("Document status")
        document_layout.addWidget(self._document_status)
        self._document_group.setEnabled(False)
        layout.addWidget(self._document_group)

        self._chat_group = QGroupBox("Chat")
        self._chat_group.setObjectName("chatSection")
        chat_layout = QVBoxLayout(self._chat_group)
        question_label = QLabel("Question")
        self._question_input = QPlainTextEdit()
        self._question_input.setObjectName("questionInput")
        self._question_input.setAccessibleName("Question")
        question_label.setBuddy(self._question_input)
        chat_layout.addWidget(question_label)
        chat_layout.addWidget(self._question_input)
        question_actions = QHBoxLayout()
        self._ask_question = QPushButton("Ask")
        self._ask_question.setObjectName("askQuestion")
        self._ask_question.setAccessibleName("Ask question")
        self._retry_question = QPushButton("Retry")
        self._retry_question.setObjectName("retryQuestion")
        self._retry_question.setAccessibleName("Retry question")
        self._cancel_question = QPushButton("Cancel Question")
        self._cancel_question.setObjectName("cancelQuestion")
        self._cancel_question.setAccessibleName("Cancel question")
        question_actions.addWidget(self._ask_question)
        question_actions.addWidget(self._retry_question)
        question_actions.addWidget(self._cancel_question)
        question_actions.addStretch()
        chat_layout.addLayout(question_actions)
        self._chat_status = QLabel(_NO_QUESTION)
        self._chat_status.setObjectName("chatStatus")
        self._chat_status.setAccessibleName("Chat status")
        chat_layout.addWidget(self._chat_status)
        answer_label = QLabel("Answer")
        self._answer = QPlainTextEdit()
        self._answer.setObjectName("answerText")
        self._answer.setAccessibleName("Answer")
        self._answer.setReadOnly(True)
        answer_label.setBuddy(self._answer)
        chat_layout.addWidget(answer_label)
        chat_layout.addWidget(self._answer)
        citations_label = QLabel("Citations")
        self._citations = QListWidget()
        self._citations.setObjectName("citationList")
        self._citations.setAccessibleName("Ordered citations")
        citations_label.setBuddy(self._citations)
        chat_layout.addWidget(citations_label)
        chat_layout.addWidget(self._citations)
        citation_actions = QHBoxLayout()
        self._open_citation = QPushButton("Open Citation")
        self._open_citation.setObjectName("openCitation")
        self._open_citation.setAccessibleName("Open selected citation")
        citation_actions.addWidget(self._open_citation)
        citation_actions.addStretch()
        chat_layout.addLayout(citation_actions)
        self._citation_status = QLabel()
        self._citation_status.setObjectName("citationStatus")
        self._citation_status.setAccessibleName("Citation status")
        chat_layout.addWidget(self._citation_status)
        self._chat_group.setEnabled(False)
        layout.addWidget(self._chat_group)
        layout.addStretch()
        return page

    def _build_workspace_group(self) -> QGroupBox:
        group = QGroupBox("Workspace")
        group.setObjectName("workspaceSection")
        layout = QVBoxLayout(group)

        create_row = QHBoxLayout()
        name_label = QLabel("Workspace name")
        self._workspace_name = QLineEdit()
        self._workspace_name.setObjectName("workspaceName")
        self._workspace_name.setAccessibleName("Workspace name")
        name_label.setBuddy(self._workspace_name)
        self._create_workspace = QPushButton("Create")
        self._create_workspace.setObjectName("createWorkspace")
        self._create_workspace.setAccessibleName("Create workspace")
        create_row.addWidget(name_label)
        create_row.addWidget(self._workspace_name, 1)
        create_row.addWidget(self._create_workspace)
        layout.addLayout(create_row)

        select_row = QHBoxLayout()
        list_label = QLabel("Existing workspace")
        self._workspace_list = QComboBox()
        self._workspace_list.setObjectName("workspaceList")
        self._workspace_list.setAccessibleName("Existing workspaces")
        list_label.setBuddy(self._workspace_list)
        self._select_workspace = QPushButton("Select")
        self._select_workspace.setObjectName("selectWorkspace")
        self._select_workspace.setAccessibleName("Select workspace")
        select_row.addWidget(list_label)
        select_row.addWidget(self._workspace_list, 1)
        select_row.addWidget(self._select_workspace)
        layout.addLayout(select_row)

        details = QFormLayout()
        self._active_workspace = QLabel(_NO_ACTIVE_WORKSPACE)
        self._active_workspace.setObjectName("activeWorkspace")
        self._active_workspace.setAccessibleName("Active workspace")
        details.addRow("Active workspace", self._active_workspace)
        layout.addLayout(details)

        self._workspace_status = QLabel()
        self._workspace_status.setObjectName("workspaceStatus")
        self._workspace_status.setWordWrap(True)
        self._workspace_status.setAccessibleName("Workspace status")
        layout.addWidget(self._workspace_status)
        return group

    def _build_fatal_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("fatalStartupPage")
        layout = QVBoxLayout(page)
        layout.addStretch()
        self._fatal_status = QLabel(
            PRESENTATION_MESSAGES[PresentationErrorCode.STARTUP_FAILED]
        )
        self._fatal_status.setObjectName("fatalStartupStatus")
        self._fatal_status.setWordWrap(True)
        self._fatal_status.setAccessibleName("Fatal startup status")
        layout.addWidget(self._fatal_status)
        close_button = QPushButton("Close")
        close_button.setObjectName("closeApplication")
        close_button.setAccessibleName("Close application")
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)
        layout.addStretch()
        return page

    @Slot()
    def _render_current_state(self) -> None:
        self._render(self._controller.state)

    @Slot(object)
    def _render(self, state: object) -> None:
        if not isinstance(state, PresentationState):
            return
        fatal = state.capability is CapabilityState.FATAL_STARTUP
        if state.selected_workspace_id != self._rendered_workspace_id:
            self._rendered_workspace_id = state.selected_workspace_id
            self._question_input.clear()
            self._answer.clear()
            self._citations.clear()
            self._close_citation_dialog()
        self._pages.setCurrentWidget(self._fatal_page if fatal else self._workflow_page)

        if state.capability is CapabilityState.STARTING:
            self._capability_status.setText("Starting local capabilities…")
        elif state.capability is CapabilityState.MODEL_UNAVAILABLE:
            self._capability_status.setText(
                PRESENTATION_MESSAGES[PresentationErrorCode.MODEL_UNAVAILABLE]
            )
        else:
            self._capability_status.clear()

        self._sync_workspace_list(state)
        commands_available = self._workspace_commands is not None and not fatal
        self._workspace_group.setEnabled(
            commands_available and state.capability is not CapabilityState.STARTING
        )
        self._create_workspace.setEnabled(
            commands_available
            and state.actions.create_workspace
            and bool(self._workspace_name.text().strip())
        )
        self._select_workspace.setEnabled(
            commands_available
            and state.actions.select_workspace
            and isinstance(self._workspace_list.currentData(), Workspace)
        )
        self._active_workspace.setText(
            state.active_workspace.display_name
            if state.active_workspace is not None
            else _NO_ACTIVE_WORKSPACE
        )
        self._workspace_status.setText(self._workspace_status_text(state))

        document_available = (
            self._document_commands is not None
            and state.capability is CapabilityState.READY
            and state.active_workspace is not None
        )
        self._document_group.setEnabled(document_available)
        self._import_pdf.setEnabled(
            document_available and state.actions.import_pdf
        )
        self._cancel_document.setEnabled(
            document_available and state.actions.cancel_document
        )
        self._render_document(state)

        chat_section_available = (
            state.capability is CapabilityState.READY
            and state.active_document is not None
        )
        chat_available = (
            chat_section_available and self._question_commands is not None
        )
        self._chat_group.setEnabled(chat_section_available)
        self._question_input.setEnabled(chat_available and state.actions.ask)
        self._ask_question.setEnabled(
            chat_available
            and state.actions.ask
            and bool(self._question_input.toPlainText().strip())
        )
        self._retry_question.setEnabled(
            chat_available and state.actions.retry_question
        )
        self._cancel_question.setEnabled(
            chat_available and state.actions.cancel_question
        )
        self._render_question(state)

    def _render_question(self, state: PresentationState) -> None:
        if state.error_code in {
            PresentationErrorCode.QUESTION_FAILED,
            PresentationErrorCode.QUESTION_DRAFT_INTERRUPTED,
            PresentationErrorCode.QUESTION_CANCELLED,
        }:
            self._chat_status.setText(PRESENTATION_MESSAGES[state.error_code])
        else:
            self._chat_status.setText({
                QuestionDisplayState.IDLE: _NO_QUESTION,
                QuestionDisplayState.PREPARING: "Preparing question…",
                QuestionDisplayState.ASKING: "Asking…",
                QuestionDisplayState.CANCELLING: "Cancelling…",
                QuestionDisplayState.GROUNDED: "Grounded answer",
                QuestionDisplayState.RELATED_NON_ANSWER: (
                    "Related evidence; insufficient support."
                ),
                QuestionDisplayState.INSUFFICIENT_NON_ANSWER: (
                    "Insufficient evidence."
                ),
                QuestionDisplayState.FAILED: "Failed",
                QuestionDisplayState.CANCELLED: "Cancelled",
            }[state.question])

        self._answer.clear()
        self._citations.clear()
        self._citation_status.clear()
        self._citation_mapping_available = False
        self._open_citation.setEnabled(False)
        self._close_citation_dialog()
        if state.chat_result is None:
            return
        graph = state.chat_result.graph
        self._answer.setPlainText(graph.answer.content)
        if not graph.citations:
            if state.question in (
                QuestionDisplayState.GROUNDED,
                QuestionDisplayState.RELATED_NON_ANSWER,
            ):
                self._citation_status.setText(
                    PRESENTATION_MESSAGES[PresentationErrorCode.CITATION_UNAVAILABLE]
                )
            return
        try:
            details = tuple(
                resolve_citation_detail(graph, citation)
                for citation in graph.citations
            )
            if len({detail.evidence_rank for detail in details}) != len(details):
                raise CitationUnavailable("citation is unavailable")
        except CitationUnavailable:
            self._citations.clear()
            self._citation_status.setText(
                PRESENTATION_MESSAGES[PresentationErrorCode.CITATION_UNAVAILABLE]
            )
            return
        for detail in details:
            self._citations.addItem(detail.evidence_label)
        self._citation_mapping_available = True
        self._update_citation_action(self._citations.currentRow())

    def _render_document(self, state: PresentationState) -> None:
        result = state.active_document
        if result is None:
            self._document_name.setText(_NO_DOCUMENT)
        else:
            page_label = "page" if result.page_count == 1 else "pages"
            self._document_name.setText(
                f"{result.logical_filename} — {result.page_count} {page_label}"
            )

        if state.error_code in {
            PresentationErrorCode.PDF_UNREADABLE,
            PresentationErrorCode.PDF_DUPLICATE,
            PresentationErrorCode.NATIVE_TEXT_UNAVAILABLE,
            PresentationErrorCode.DOCUMENT_FAILED,
            PresentationErrorCode.DOCUMENT_REGISTERED_INCOMPLETE,
        }:
            self._document_status.setText(PRESENTATION_MESSAGES[state.error_code])
            return
        if state.document_notice is DocumentNotice.CANCELLED:
            self._document_status.setText(
                "Cancelled; the registered document is incomplete and is not ready."
                if state.registered_incomplete_document
                else "Cancelled."
            )
            return
        self._document_status.setText({
            DocumentDisplayState.EMPTY: _NO_DOCUMENT,
            DocumentDisplayState.IMPORTING: "Importing…",
            DocumentDisplayState.EXTRACTING: "Extracting text…",
            DocumentDisplayState.INDEXING: "Building index…",
            DocumentDisplayState.EMBEDDING: "Generating embeddings…",
            DocumentDisplayState.READY: "Ready",
            DocumentDisplayState.READY_WITH_WARNINGS: "Ready with warnings",
            DocumentDisplayState.CANCELLING: "Cancelling…",
            DocumentDisplayState.CANCELLED: "Cancelled",
            DocumentDisplayState.FAILED: "Failed",
        }[state.document])

    def _sync_workspace_list(self, state: PresentationState) -> None:
        current = self._workspace_list.currentData()
        current_id = current.id if isinstance(current, Workspace) else None
        expected = tuple(
            self._workspace_list.itemData(index)
            for index in range(self._workspace_list.count())
        )
        if expected == state.workspaces:
            return
        self._workspace_list.blockSignals(True)
        self._workspace_list.clear()
        selected_index = -1
        for index, workspace in enumerate(state.workspaces):
            self._workspace_list.addItem(workspace.display_name, workspace)
            if workspace.id == current_id:
                selected_index = index
        self._workspace_list.setCurrentIndex(selected_index)
        self._workspace_list.blockSignals(False)

    def _workspace_status_text(self, state: PresentationState) -> str:
        if state.error_code in {
            PresentationErrorCode.WORKSPACE_UNAVAILABLE,
            PresentationErrorCode.WORKSPACE_OPERATION_FAILED,
        }:
            return PRESENTATION_MESSAGES[state.error_code]
        return {
            WorkspaceNotice.LISTED: "Workspaces loaded.",
            WorkspaceNotice.CREATED: "Workspace created. Select it to continue.",
            WorkspaceNotice.SELECTED: "Workspace selected.",
            None: "",
        }[state.workspace_notice]

    @Slot()
    def _request_create_workspace(self) -> None:
        if self._workspace_commands is None or not self._workspace_name.text().strip():
            return
        token = self._controller.begin(WorkerOperation.CREATE_WORKSPACE)
        self._workspace_commands.create_workspace(
            CreateWorkspaceCommand(token, self._workspace_name.text())
        )

    @Slot()
    def _request_select_workspace(self) -> None:
        workspace = self._workspace_list.currentData()
        if self._workspace_commands is None or not isinstance(workspace, Workspace):
            return
        token = self._controller.begin(WorkerOperation.SELECT_WORKSPACE)
        self._workspace_commands.select_workspace(
            SelectWorkspaceCommand(token, workspace.id)
        )

    @Slot()
    def _request_import_pdf(self) -> None:
        if self._document_commands is None or not self._controller.state.actions.import_pdf:
            return
        selected_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select one anonymous synthetic PDF",
            "",
            "PDF files (*.pdf)",
        )
        if not selected_path:
            return
        token = self._controller.begin(WorkerOperation.DOCUMENT)
        self._document_commands.run_document(
            DocumentCommand(token, SelectedPdfReference(selected_path))
        )

    @Slot()
    def _request_document_cancellation(self) -> None:
        if self._document_commands is None:
            return
        token = self._controller.request_cancellation()
        if token is not None:
            self._document_commands.request_cancellation(token)

    @Slot()
    def _request_question(self) -> None:
        state = self._controller.state
        question = self._question_input.toPlainText()
        if (
            self._question_commands is None
            or not state.actions.ask
            or state.active_document is None
            or not question.strip()
        ):
            return
        token = self._controller.begin(WorkerOperation.QUESTION)
        self._question_commands.run_question(
            QuestionCommand(token, state.active_document, question)
        )

    @Slot()
    def _request_question_retry(self) -> None:
        state = self._controller.state
        if (
            self._question_commands is None
            or not state.actions.retry_question
            or state.qa_request_id is None
        ):
            return
        token = self._controller.begin(WorkerOperation.QUESTION)
        self._question_commands.retry_question(
            RetryQuestionCommand(token, state.qa_request_id)
        )

    @Slot()
    def _request_question_cancellation(self) -> None:
        if self._question_commands is None:
            return
        token = self._controller.request_cancellation()
        if token is not None:
            self._question_commands.request_cancellation(token)

    @Slot(int)
    def _update_citation_action(self, row: int) -> None:
        state = self._controller.state
        self._open_citation.setEnabled(
            self._citation_mapping_available
            and state.actions.open_citation
            and 0 <= row < self._citations.count()
        )

    @Slot()
    def _open_selected_citation(self) -> None:
        result = self._controller.state.chat_result
        row = self._citations.currentRow()
        if (
            result is None
            or not self._citation_mapping_available
            or row < 0
            or row >= len(result.graph.citations)
        ):
            self._citation_unavailable()
            return
        try:
            detail = resolve_citation_detail(
                result.graph,
                result.graph.citations[row],
            )
            if self._citations.item(row).text() != detail.evidence_label:
                raise CitationUnavailable("citation is unavailable")
        except CitationUnavailable:
            self._citation_unavailable()
            return
        self._close_citation_dialog()
        dialog = CitationDialog(detail, self)
        dialog.finished.connect(self._citation_dialog_finished)
        self._citation_dialog = dialog
        dialog.open()

    def _citation_unavailable(self) -> None:
        self._close_citation_dialog()
        self._citation_mapping_available = False
        self._citations.clear()
        self._open_citation.setEnabled(False)
        self._citation_status.setText(
            PRESENTATION_MESSAGES[PresentationErrorCode.CITATION_UNAVAILABLE]
        )

    @Slot(int)
    def _citation_dialog_finished(self, _result: int) -> None:
        self._citation_dialog = None

    def _close_citation_dialog(self) -> None:
        if self._citation_dialog is not None:
            self._citation_dialog.close()
            self._citation_dialog = None
