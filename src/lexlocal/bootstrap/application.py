from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from lexlocal.bootstrap.logging_setup import configure_logging
from lexlocal.bootstrap.persistence import initialize_persistence
from lexlocal.bootstrap.security import create_security_providers
from lexlocal.bootstrap.settings import load_settings
from lexlocal.bootstrap.ui import compose_ui_application
from lexlocal.presentation.windows.main_window import MainWindow


def create_application(
    argv: Sequence[str] | None = None,
) -> tuple[QApplication, MainWindow]:
    """Create the Qt application and its main window."""

    application = _qt_application(argv)
    return application, MainWindow()


def _qt_application(argv: Sequence[str] | None = None) -> QApplication:
    existing_application = QApplication.instance()

    if isinstance(existing_application, QApplication):
        application = existing_application
    else:
        arguments = list(argv) if argv is not None else []
        application = QApplication(arguments)

    application.setApplicationName("LexLocal")
    application.setOrganizationName("LexLocal")

    return application


def run(argv: Sequence[str] | None = None) -> int:
    """Start the LexLocal desktop application."""

    settings = load_settings()
    logger = configure_logging(settings)

    logger.info("Application starting")

    connection_factory = initialize_persistence(settings)
    security = create_security_providers(settings)
    application = _qt_application(argv)
    ui = compose_ui_application(settings, connection_factory, security)

    try:
        ui.main_window.show()
        ui.start()
        exit_code = application.exec()
    except BaseException:
        try:
            ui.shutdown()
        except Exception:
            pass
        raise
    if not ui.shutdown():
        raise RuntimeError("application worker did not stop safely")

    logger.info("Application stopped; exit_code=%d", exit_code)

    return exit_code
