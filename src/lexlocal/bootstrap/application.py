from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from lexlocal.presentation.windows.main_window import MainWindow


def create_application(
    argv: Sequence[str] | None = None,
) -> tuple[QApplication, MainWindow]:
    """Create the Qt application and its main window."""

    existing_application = QApplication.instance()

    if isinstance(existing_application, QApplication):
        application = existing_application
    else:
        arguments = list(argv) if argv is not None else []
        application = QApplication(arguments)

    application.setApplicationName("LexLocal")
    application.setOrganizationName("LexLocal")

    main_window = MainWindow()

    return application, main_window


def run(argv: Sequence[str] | None = None) -> int:
    """Start the LexLocal desktop application."""

    application, main_window = create_application(argv)
    main_window.show()

    return application.exec()