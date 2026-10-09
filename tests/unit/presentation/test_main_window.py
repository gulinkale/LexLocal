from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from lexlocal.domain.identifiers import WorkspaceId
from lexlocal.domain.workspace import Workspace
from lexlocal.presentation.controller import PresentationController
from lexlocal.presentation.state import (
    CapabilityEvent,
    CapabilityState,
    OperationFailedEvent,
    PresentationErrorCode,
    WorkerOperation,
    WorkspaceEvent,
    WorkspaceListEvent,
    WorkspaceSelectedEvent,
)
from lexlocal.presentation.windows.main_window import (
    MainWindow,
    WorkspaceCommandBindings,
)
from lexlocal.presentation.workflow_worker import (
    CreateWorkspaceCommand,
    SelectWorkspaceCommand,
)


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication(["lexlocal-main-window-test"])


@dataclass
class _Commands:
    list_tokens: list[object] = field(default_factory=list)
    create_commands: list[CreateWorkspaceCommand] = field(default_factory=list)
    select_commands: list[SelectWorkspaceCommand] = field(default_factory=list)

    @property
    def bindings(self) -> WorkspaceCommandBindings:
        return WorkspaceCommandBindings(
            self.list_tokens.append,
            self.create_commands.append,
            self.select_commands.append,
        )


def _workspace(name: str) -> Workspace:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Workspace(WorkspaceId(str(uuid4())), name, now, now)


def _widget(window: MainWindow, widget_type: type[QWidget], name: str):
    widget = window.findChild(widget_type, name)
    assert widget is not None
    return widget


def _initialized_window(
    application: QApplication,
    capability: CapabilityState = CapabilityState.READY,
    workspaces: tuple[Workspace, ...] = (),
) -> tuple[MainWindow, PresentationController, _Commands]:
    controller = PresentationController()
    commands = _Commands()
    window = MainWindow(controller=controller, workspace_commands=commands.bindings)
    startup_token = controller.begin(WorkerOperation.STARTUP)
    window.accept_capability(CapabilityEvent(startup_token, capability))
    assert len(commands.list_tokens) == 1
    window.accept_workspace_listed(
        WorkspaceListEvent(commands.list_tokens[0], workspaces)
    )
    window.show()
    application.processEvents()
    return window, controller, commands


def test_shell_has_persistent_warning_and_three_ordered_sections(
    application: QApplication,
) -> None:
    window, _, _ = _initialized_window(application)

    warning = _widget(window, QLabel, "developmentWarning")
    workspace = _widget(window, QGroupBox, "workspaceSection")
    document = _widget(window, QGroupBox, "documentSection")
    chat = _widget(window, QGroupBox, "chatSection")

    assert "synthetic" in warning.text()
    assert "Not for real user documents" in warning.text()
    assert workspace.geometry().top() < document.geometry().top() < chat.geometry().top()
    assert document.isEnabled() is False
    assert chat.isEnabled() is False
    assert _widget(window, QLabel, "documentStatus").text() == "No document selected."
    assert _widget(window, QLabel, "chatStatus").text() == "No question submitted."
    window.close()


def test_create_preserves_name_and_does_not_implicitly_select(
    application: QApplication,
) -> None:
    window, controller, commands = _initialized_window(application)
    name = _widget(window, QLineEdit, "workspaceName")
    create = _widget(window, QPushButton, "createWorkspace")
    workspace_list = _widget(window, QComboBox, "workspaceList")
    active = _widget(window, QLabel, "activeWorkspace")

    assert create.isEnabled() is False
    name.setText("  Synthetic Appeal  ")
    assert create.isEnabled() is True
    create.click()

    assert len(commands.create_commands) == 1
    assert commands.create_commands[0].display_name == "  Synthetic Appeal  "
    assert create.isEnabled() is False

    created = _workspace("Synthetic Appeal")
    window.accept_workspace_created(
        WorkspaceEvent(commands.create_commands[0].token, created)
    )

    assert workspace_list.count() == 1
    assert workspace_list.currentIndex() == -1
    assert active.text() == "No workspace selected."
    assert controller.state.selected_workspace_id is None
    assert "Select it to continue" in _widget(
        window, QLabel, "workspaceStatus"
    ).text()
    window.close()


def test_list_and_explicit_selection_render_only_safe_name_and_clear_downstream(
    application: QApplication,
) -> None:
    first = _workspace("Synthetic Alpha")
    second = _workspace("Synthetic Beta")
    window, controller, commands = _initialized_window(
        application, workspaces=(first, second)
    )
    workspace_list = _widget(window, QComboBox, "workspaceList")
    select = _widget(window, QPushButton, "selectWorkspace")
    active = _widget(window, QLabel, "activeWorkspace")
    document_status = _widget(window, QLabel, "documentStatus")
    chat_status = _widget(window, QLabel, "chatStatus")

    assert workspace_list.count() == 2
    assert workspace_list.currentIndex() == -1
    assert controller.state.selected_workspace_id is None
    assert select.isEnabled() is False

    workspace_list.setCurrentIndex(1)
    assert select.isEnabled() is True
    document_status.setText("stale document")
    chat_status.setText("stale question")
    select.click()

    assert len(commands.select_commands) == 1
    command = commands.select_commands[0]
    assert command.workspace_id == second.id
    window.accept_workspace_selected(
        WorkspaceSelectedEvent(command.token, second.id)
    )

    assert active.text() == "Synthetic Beta"
    assert str(second.id) not in active.text()
    assert controller.state.active_workspace == second
    assert document_status.text() == "No document selected."
    assert chat_status.text() == "No question submitted."
    window.close()


def test_workspace_failure_uses_only_fixed_safe_copy(
    application: QApplication,
) -> None:
    window, _, commands = _initialized_window(application)
    name = _widget(window, QLineEdit, "workspaceName")
    name.setText("Synthetic Workspace")
    _widget(window, QPushButton, "createWorkspace").click()
    command = commands.create_commands[0]

    window.accept_failed(
        OperationFailedEvent(
            command.token,
            WorkerOperation.CREATE_WORKSPACE,
            PresentationErrorCode.WORKSPACE_OPERATION_FAILED,
        )
    )

    status = _widget(window, QLabel, "workspaceStatus").text()
    assert status == "The workspace operation could not be completed."
    assert "Synthetic Workspace" not in status
    window.close()


def test_model_unavailable_keeps_only_workspace_controls_usable(
    application: QApplication,
) -> None:
    window, _, _ = _initialized_window(
        application, capability=CapabilityState.MODEL_UNAVAILABLE
    )
    name = _widget(window, QLineEdit, "workspaceName")
    name.setText("Synthetic Workspace")

    assert _widget(window, QGroupBox, "workspaceSection").isEnabled() is True
    assert _widget(window, QPushButton, "createWorkspace").isEnabled() is True
    assert _widget(window, QGroupBox, "documentSection").isEnabled() is False
    assert _widget(window, QGroupBox, "chatSection").isEnabled() is False
    assert "No cloud fallback" in _widget(
        window, QLabel, "capabilityStatus"
    ).text()
    window.close()


def test_fatal_startup_hides_normal_workflow(
    application: QApplication,
) -> None:
    controller = PresentationController()
    commands = _Commands()
    window = MainWindow(controller=controller, workspace_commands=commands.bindings)
    token = controller.begin(WorkerOperation.STARTUP)
    window.show()
    window.accept_capability(CapabilityEvent(token, CapabilityState.FATAL_STARTUP))
    application.processEvents()

    assert _widget(window, QWidget, "fatalStartupPage").isVisible() is True
    assert _widget(window, QWidget, "workflowPage").isVisible() is False
    assert _widget(window, QLabel, "fatalStartupStatus").text() == (
        "LexLocal could not start safely."
    )
    assert commands.list_tokens == []
    window.close()


def test_workspace_controls_have_accessible_names_and_fixed_tab_order(
    application: QApplication,
) -> None:
    workspace = _workspace("Synthetic Workspace")
    window, _, _ = _initialized_window(application, workspaces=(workspace,))
    name = _widget(window, QLineEdit, "workspaceName")
    create = _widget(window, QPushButton, "createWorkspace")
    workspace_list = _widget(window, QComboBox, "workspaceList")
    select = _widget(window, QPushButton, "selectWorkspace")

    assert name.accessibleName() == "Workspace name"
    assert create.accessibleName() == "Create workspace"
    assert workspace_list.accessibleName() == "Existing workspaces"
    assert select.accessibleName() == "Select workspace"
    name.setText("Synthetic New Workspace")
    workspace_list.setCurrentIndex(0)
    name.setFocus()
    application.processEvents()
    assert application.focusWidget() is name
    assert window.focusNextChild() is True
    assert application.focusWidget() is create
    assert window.focusNextChild() is True
    assert application.focusWidget() is workspace_list
    assert window.focusNextChild() is True
    assert application.focusWidget() is select
    window.close()
