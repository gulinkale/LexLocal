"""Unit tests for Bootstrap-owned ingestion composition."""

from pathlib import Path

import pytest

from lexlocal.application.ingestion import ImportSyntheticPdf
from lexlocal.application.ports.ingestion import PdfInspectionResult
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.bootstrap.ingestion import compose_ingestion_application
from lexlocal.bootstrap.security import SecurityProviderConfigurationError
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyControlledSourceStorage,
)
from lexlocal.infrastructure.security.insecure_development_ingestion import (
    InsecureDevelopmentOnlyDuplicateFingerprint,
)


class _Inspector:
    def inspect(self, _source: bytes) -> PdfInspectionResult:
        return PdfInspectionResult("application/pdf", 1)


def _settings(tmp_path: Path, *, environment: str = "test") -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment=environment,
        log_level="INFO",
        data_dir=tmp_path,
        security_provider="insecure-development-only",
    )


def test_composition_exposes_application_use_case_and_storage_port(
    tmp_path: Path,
) -> None:
    scope = ActiveWorkspaceScope()
    storage = InsecureDevelopmentOnlyControlledSourceStorage()
    fingerprint = InsecureDevelopmentOnlyDuplicateFingerprint()
    composition = compose_ingestion_application(
        _settings(tmp_path),
        SQLiteConnectionFactory(tmp_path / "unused.db"),
        scope,
        pdf_inspector=_Inspector(),
        duplicate_fingerprint=fingerprint,
        controlled_source_storage=storage,
    )

    assert isinstance(composition.import_pdf, ImportSyntheticPdf)
    assert composition.controlled_source_storage is storage


def test_production_rejects_insecure_composition_before_dependency_selection(
    tmp_path: Path,
) -> None:
    with pytest.raises(SecurityProviderConfigurationError):
        compose_ingestion_application(
            _settings(tmp_path, environment="production"),
            SQLiteConnectionFactory(tmp_path / "unused.db"),
            ActiveWorkspaceScope(),
            pdf_inspector=_Inspector(),
            controlled_source_storage=(
                InsecureDevelopmentOnlyControlledSourceStorage()
            ),
        )
