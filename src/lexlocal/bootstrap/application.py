from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from lexlocal.bootstrap.logging_setup import configure_logging
from lexlocal.bootstrap.persistence import initialize_persistence
from lexlocal.bootstrap.settings import load_settings
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

    settings = load_settings()
    logger = configure_logging(settings)

    logger.info("Application starting")

    # The composition root owns persistence dependencies for the lifetime of
    # the event loop. They can be passed to application services here as those
    # services are introduced.
    _connection_factory = initialize_persistence(settings)

    application, main_window = create_application(argv)
    main_window.show()

    exit_code = application.exec()

    logger.info("Application stopped; exit_code=%d", exit_code)

    return exit_code
