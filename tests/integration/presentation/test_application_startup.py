from PySide6.QtWidgets import QApplication, QGroupBox, QLabel

from lexlocal.bootstrap.application import create_application


def test_application_can_be_created() -> None:
    application, main_window = create_application(["lexlocal-test"])

    assert isinstance(application, QApplication)
    assert application.applicationName() == "LexLocal"
    assert main_window.windowTitle() == "LexLocal"
    assert main_window.centralWidget() is not None
    warning = main_window.findChild(QLabel, "developmentWarning")
    workspace = main_window.findChild(QGroupBox, "workspaceSection")
    document = main_window.findChild(QGroupBox, "documentSection")
    chat = main_window.findChild(QGroupBox, "chatSection")
    assert warning is not None
    assert "Not for real user documents" in warning.text()
    assert workspace is not None
    assert workspace.isEnabled() is False
    assert document is not None
    assert document.isEnabled() is False
    assert chat is not None
    assert chat.isEnabled() is False

    main_window.close()
