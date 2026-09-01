"""Compose the synthetic native-PDF processing vertical slice at Bootstrap."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from lexlocal.application.ports.processing import CancellationCheck
from lexlocal.application.ports.unit_of_work import UnitOfWork
from lexlocal.application.processing import ProcessNativePdfText
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.bootstrap.ingestion import IngestionApplicationComposition
from lexlocal.bootstrap.security import (
    SecurityProviderConfigurationError,
    create_security_providers,
)
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import DocumentPageId, SourceLocatorId
from lexlocal.infrastructure.pdf.qt_text_extractor import QtNativePdfTextExtractor
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.persistence.sqlite_unit_of_work import SQLiteUnitOfWork
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
)

_INSECURE_DEVELOPMENT_PROVIDER = "insecure-development-only"


@dataclass(frozen=True, slots=True)
class ProcessingApplicationComposition:
    """Expose processing and its Application-owned persistence handoff."""

    process_pdf: ProcessNativePdfText
    unit_of_work_factory: Callable[[], UnitOfWork]


class _NeverCancelled:
    def raise_if_cancelled(self) -> None:
        return None


def compose_processing_application(
    settings: AppSettings,
    connection_factory: SQLiteConnectionFactory,
    active_scope: ActiveWorkspaceScope,
    ingestion: IngestionApplicationComposition,
    *,
    cancellation: CancellationCheck | None = None,
    page_id_factory: Callable[[], DocumentPageId] | None = None,
    source_locator_id_factory: Callable[[], SourceLocatorId] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ProcessingApplicationComposition:
    """Wire processing to the security lifetime already selected for ingestion."""

    if (
        settings.environment not in {"development", "test"}
        or settings.security_provider != _INSECURE_DEVELOPMENT_PROVIDER
    ):
        # Preserve the established sanitized fail-closed error and precedence.
        create_security_providers(settings)
        raise SecurityProviderConfigurationError(
            "security provider configuration is unsupported"
        )

    name_persistence = InsecureDevelopmentOnlyWorkspaceNamePersistence()

    def unit_of_work_factory() -> UnitOfWork:
        return SQLiteUnitOfWork(
            connection_factory,
            name_persistence,
            ingestion.sensitive_payload_codec,
        )

    process_pdf = ProcessNativePdfText(
        active_scope=active_scope,
        controlled_storage=ingestion.controlled_source_storage,
        extractor=QtNativePdfTextExtractor(),
        cancellation=_NeverCancelled() if cancellation is None else cancellation,
        unit_of_work_factory=unit_of_work_factory,
        page_id_factory=page_id_factory or _new_page_id,
        source_locator_id_factory=(
            source_locator_id_factory or _new_source_locator_id
        ),
        clock=clock or _utc_millisecond_clock,
    )
    return ProcessingApplicationComposition(process_pdf, unit_of_work_factory)


def _new_page_id() -> DocumentPageId:
    return DocumentPageId(str(uuid4()))


def _new_source_locator_id() -> SourceLocatorId:
    return SourceLocatorId(str(uuid4()))


def _utc_millisecond_clock() -> datetime:
    now = datetime.now(UTC)
    return now.replace(microsecond=(now.microsecond // 1_000) * 1_000)
