"""Unit tests for Bootstrap-owned processing composition."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtGui import QGuiApplication

from lexlocal.application.processing import ProcessNativePdfText
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.bootstrap.ingestion import compose_ingestion_application
from lexlocal.bootstrap.processing import compose_processing_application
from lexlocal.bootstrap.security import SecurityProviderConfigurationError
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory


@pytest.fixture(scope="module", autouse=True)
def gui_application() -> Iterator[QGuiApplication]:
    existing = QGuiApplication.instance()
    application = existing if isinstance(existing, QGuiApplication) else QGuiApplication([])
    yield application


def _settings(tmp_path: Path, *, environment: str = "test") -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment=environment,
        log_level="INFO",
        data_dir=tmp_path,
        security_provider="insecure-development-only",
    )


def test_composition_exposes_only_application_owned_processing_boundaries(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    factory = SQLiteConnectionFactory(tmp_path / "unused.db")
    scope = ActiveWorkspaceScope()
    ingestion = compose_ingestion_application(settings, factory, scope)

    processing = compose_processing_application(settings, factory, scope, ingestion)

    assert isinstance(processing.process_pdf, ProcessNativePdfText)
    with pytest.raises(RuntimeError, match="transaction is not active"):
        _repository = processing.unit_of_work_factory().processing


def test_processing_reuses_ingestion_controlled_storage_instance(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    factory = SQLiteConnectionFactory(tmp_path / "unused.db")
    scope = ActiveWorkspaceScope()
    ingestion = compose_ingestion_application(settings, factory, scope)

    processing = compose_processing_application(settings, factory, scope, ingestion)

    assert processing.process_pdf._controlled_storage is (  # noqa: SLF001
        ingestion.controlled_source_storage
    )


def test_production_fails_closed_before_processing_composition(tmp_path: Path) -> None:
    test_settings = _settings(tmp_path)
    factory = SQLiteConnectionFactory(tmp_path / "unused.db")
    scope = ActiveWorkspaceScope()
    ingestion = compose_ingestion_application(test_settings, factory, scope)

    with pytest.raises(SecurityProviderConfigurationError):
        compose_processing_application(
            _settings(tmp_path, environment="production"),
            factory,
            scope,
            ingestion,
        )
