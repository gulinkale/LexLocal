from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication, QComboBox, QFileDialog, QLabel, QPushButton

from lexlocal.application.ports.document_workflow import (
    ActiveDocumentReadiness,
    ActiveDocumentResult,
    DocumentUnusableNativeText,
    DocumentWorkflowCancelled,
    DocumentWorkflowDisposition,
    DocumentWorkflowStage,
    SelectedPdfReference,
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
from lexlocal.domain.workspace import Workspace, WorkspaceProfile
from lexlocal.presentation.controller import PresentationController
from lexlocal.presentation.state import (
    CapabilityState,
    DocumentDisplayState,
    OperationToken,
    WorkerOperation,
    WorkspaceDisplayState,
)
from lexlocal.presentation.windows.main_window import (
    DocumentCommandBindings,
    MainWindow,
    WorkspaceCommandBindings,
)
from lexlocal.presentation.workflow_worker import (
    SerializedWorkflowHost,
    ThreadCancellationSource,
    WorkflowWorker,
)


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication(["lexlocal-document-ui-integration-test"])


def _id(identifier_type: type):
    return identifier_type(str(uuid4()))


def _workspace() -> Workspace:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Workspace(_id(WorkspaceId), "Synthetic Workspace", now, now)


def _active_document(workspace_id: WorkspaceId) -> ActiveDocumentResult:
    version_id = _id(DocumentVersionId)
    job_id = _id(ProcessingJobId)
    return ActiveDocumentResult(
        workspace_id,
        _id(DocumentId),
        version_id,
        job_id,
        "anonymous.pdf",
        1,
        ActiveDocumentReadiness.READY,
        IndexGeneration(
            _id(IndexGenerationId),
            workspace_id,
            version_id,
            job_id,
            _id(LocalModelId),
            "chunk-v1",
            "norm-v1",
            3,
            IndexGenerationState.ACTIVE,
        ),
    )


class _Session:
    def __init__(
        self,
        cancellation: ThreadCancellationSource,
        workspace: Workspace,
    ) -> None:
        self.cancellation = cancellation
        self.workspace = workspace
        self.result = _active_document(workspace.id)
        self.mode = "ready"
        self.disposition = DocumentWorkflowDisposition.NOT_REGISTERED
        self.started = Event()
        self.worker_thread: QThread | None = None
        self.selected: SelectedPdfReference | None = None
        self.closed = False

    def build_document(
        self,
        selected: SelectedPdfReference,
        stage_sink: Callable[[DocumentWorkflowStage], None],
    ) -> ActiveDocumentResult:
        self.worker_thread = QThread.currentThread()
        self.selected = selected
        stage_sink(DocumentWorkflowStage.IMPORTING)
        self.started.set()
        if self.mode == "cancel":
            while not self.cancellation.is_cancelled:
                sleep(0.002)
            raise DocumentWorkflowCancelled(
                "private cancellation detail",
                disposition=self.disposition,
            )
        if self.mode == "unusable":
            raise DocumentUnusableNativeText(
                "private native-text detail",
                disposition=DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            )
        stage_sink(DocumentWorkflowStage.EXTRACTING)
        stage_sink(DocumentWorkflowStage.INDEXING)
        stage_sink(DocumentWorkflowStage.EMBEDDING)
        return self.result

    def close(self) -> None:
        self.closed = True


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
        return (self.session.workspace,)

    def create_workspace(
        self,
        display_name: str,
        profile: WorkspaceProfile | None = None,
    ) -> Workspace:
        del display_name, profile
        raise AssertionError("workspace creation is outside this focused flow")

    def select_workspace(self, workspace_id: WorkspaceId) -> WorkspaceId:
        if workspace_id != self.session.workspace.id:
            raise RuntimeError
        return workspace_id

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
    WorkflowWorker,
    _Session,
]:
    workspace = _workspace()
    cancellation = ThreadCancellationSource()
    session = _Session(cancellation, workspace)
    worker = WorkflowWorker(_Builder(session), cancellation)
    host = SerializedWorkflowHost(worker, cancellation)
    controller = PresentationController()
    window = MainWindow(
        controller=controller,
        workspace_commands=WorkspaceCommandBindings(
            host.list_workspaces_requested.emit,
            host.create_workspace_requested.emit,
            host.select_workspace_requested.emit,
        ),
        document_commands=DocumentCommandBindings(
            host.document_requested.emit,
            host.request_cancellation,
        ),
    )
    worker.initialized.connect(window.accept_capability)
    worker.workspace_listed.connect(window.accept_workspace_listed)
    worker.workspace_created.connect(window.accept_workspace_created)
    worker.workspace_selected.connect(window.accept_workspace_selected)
    worker.document_phase_changed.connect(window.accept_document_phase)
    worker.document_ready.connect(window.accept_document_ready)
    worker.operation_cancelled.connect(window.accept_cancelled)
    worker.operation_failed.connect(window.accept_failed)
    host.start()
    host.initialize_requested.emit(controller.begin(WorkerOperation.STARTUP))
    _wait_until(
        application,
        lambda: (
            controller.state.capability is CapabilityState.READY
            and len(controller.state.workspaces) == 1
            and controller.state.active_operation is None
        ),
    )
    workspace_list = window.findChild(QComboBox, "workspaceList")
    select = window.findChild(QPushButton, "selectWorkspace")
    assert workspace_list is not None
    assert select is not None
    workspace_list.setCurrentIndex(0)
    select.click()
    _wait_until(
        application,
        lambda: controller.state.workspace is WorkspaceDisplayState.SELECTED,
    )
    window.show()
    application.processEvents()
    return window, controller, host, worker, session


def _choose_pdf(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args: (path, "PDF files (*.pdf)"),
    )


def test_serialized_worker_delivers_ordered_phases_and_ready_off_gui_thread(
    application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_path = "/private/PRIVATE-INTEGRATION-PATH.pdf"
    window, controller, host, _, session = _stack(application)
    observed: list[DocumentDisplayState] = []

    def observe(state: object) -> None:
        document = getattr(state, "document", None)
        if isinstance(document, DocumentDisplayState) and (
            not observed or observed[-1] is not document
        ):
            observed.append(document)

    controller.state_changed.connect(observe)
    _choose_pdf(monkeypatch, private_path)
    import_pdf = window.findChild(QPushButton, "importPdf")
    assert import_pdf is not None
    try:
        import_pdf.click()
        _wait_until(
            application,
            lambda: controller.state.document is DocumentDisplayState.READY,
        )

        assert observed == [
            DocumentDisplayState.IMPORTING,
            DocumentDisplayState.EXTRACTING,
            DocumentDisplayState.INDEXING,
            DocumentDisplayState.EMBEDDING,
            DocumentDisplayState.READY,
        ]
        assert session.worker_thread == host.worker_thread
        assert session.selected is not None
        assert session.selected.value == private_path
        assert private_path not in repr(session.selected)
        rendered = " ".join(label.text() for label in window.findChildren(QLabel))
        assert private_path not in rendered
        assert controller.state.active_document is session.result
    finally:
        window.close()
        assert host.shutdown(OperationToken(999, 1))
    assert session.closed is True


@pytest.mark.parametrize(
    ("disposition", "expected_state", "import_enabled"),
    [
        (
            DocumentWorkflowDisposition.NOT_REGISTERED,
            DocumentDisplayState.EMPTY,
            True,
        ),
        (
            DocumentWorkflowDisposition.REGISTERED_INCOMPLETE,
            DocumentDisplayState.CANCELLED,
            False,
        ),
    ],
)
def test_busy_worker_cancellation_uses_typed_disposition_and_keeps_gui_responsive(
    application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    disposition: DocumentWorkflowDisposition,
    expected_state: DocumentDisplayState,
    import_enabled: bool,
) -> None:
    window, controller, host, _, session = _stack(application)
    session.mode = "cancel"
    session.disposition = disposition
    _choose_pdf(monkeypatch, "/private/not-rendered.pdf")
    heartbeat = 0
    timer = QTimer()
    timer.setInterval(2)

    def tick() -> None:
        nonlocal heartbeat
        heartbeat += 1

    timer.timeout.connect(tick)
    import_pdf = window.findChild(QPushButton, "importPdf")
    cancel = window.findChild(QPushButton, "cancelDocument")
    assert import_pdf is not None
    assert cancel is not None
    try:
        timer.start()
        import_pdf.click()
        assert session.started.wait(2)
        _wait_until(application, lambda: heartbeat >= 3)
        assert session.worker_thread == host.worker_thread
        cancel.click()
        assert controller.state.document is DocumentDisplayState.CANCELLING
        _wait_until(
            application,
            lambda: controller.state.active_operation is None,
        )

        assert controller.state.document is expected_state
        assert import_pdf.isEnabled() is import_enabled
        assert controller.state.registered_incomplete_document is (
            disposition is DocumentWorkflowDisposition.REGISTERED_INCOMPLETE
        )
    finally:
        timer.stop()
        window.close()
        assert host.shutdown(OperationToken(999, 1))


def test_worker_maps_unusable_native_text_to_fixed_safe_ui_message(
    application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_path = "/private/PRIVATE-UNUSABLE-PATH.pdf"
    window, controller, host, _, session = _stack(application)
    session.mode = "unusable"
    _choose_pdf(monkeypatch, private_path)
    import_pdf = window.findChild(QPushButton, "importPdf")
    status = window.findChild(QLabel, "documentStatus")
    assert import_pdf is not None
    assert status is not None
    try:
        import_pdf.click()
        _wait_until(
            application,
            lambda: controller.state.active_operation is None,
        )

        assert controller.state.document is DocumentDisplayState.FAILED
        assert controller.state.registered_incomplete_document is True
        assert import_pdf.isEnabled() is False
        assert status.text() == (
            "This PDF has no usable native text in M1; OCR is unavailable."
        )
        assert private_path not in status.text()
    finally:
        window.close()
        assert host.shutdown(OperationToken(999, 1))
