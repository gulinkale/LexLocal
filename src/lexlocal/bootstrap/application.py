from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from lexlocal.bootstrap.foundry import compose_local_models
from lexlocal.bootstrap.logging_setup import configure_logging
from lexlocal.bootstrap.persistence import (
    compose_workspace_application,
    initialize_persistence,
)
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

    connection_factory = initialize_persistence(settings)
    _workspace_application = compose_workspace_application(
        settings,
        connection_factory,
    )
    local_models = compose_local_models(settings, connection_factory)

    try:
        application, main_window = create_application(argv)
        main_window.show()

        exit_code = application.exec()
    except BaseException:
        try:
            local_models.close()
        except Exception:
            pass
        raise
    else:
        local_models.close()

    logger.info("Application stopped; exit_code=%d", exit_code)

    return exit_code
