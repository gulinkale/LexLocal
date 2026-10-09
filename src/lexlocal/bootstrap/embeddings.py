"""Compose the synthetic local embedding pipeline at Bootstrap."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from lexlocal.application.embeddings import EmbedQuery, EmbedStagingChunks
from lexlocal.application.indexing import FinalizeIndexing
from lexlocal.application.ports.embeddings import EmbeddingCancellationCheck
from lexlocal.application.ports.unit_of_work import UnitOfWork
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.bootstrap.foundry import LocalModelComposition
from lexlocal.bootstrap.security import SecurityProviders, create_security_providers
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.persistence.sqlite_unit_of_work import SQLiteUnitOfWork
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
)


@dataclass(frozen=True, slots=True)
class EmbeddingApplicationComposition:
    """Expose composed chunk and ephemeral query embedding use cases."""

    embed_staging_chunks: EmbedStagingChunks
    embed_query: EmbedQuery


class _NeverCancelled:
    def raise_if_cancelled(self) -> None:
        return None


def compose_embedding_application(
    settings: AppSettings,
    connection_factory: SQLiteConnectionFactory,
    active_scope: ActiveWorkspaceScope,
    local_models: LocalModelComposition,
    *,
    cancellation: EmbeddingCancellationCheck | None = None,
    clock: Callable[[], datetime] | None = None,
    security_providers: SecurityProviders | None = None,
) -> EmbeddingApplicationComposition:
    """Wire the existing local provider, persistence, and INDEX finalizer."""

    security = security_providers or create_security_providers(settings)
    cancellation_check = _NeverCancelled() if cancellation is None else cancellation
    current_clock = _utc_millisecond_clock if clock is None else clock
    name_persistence = InsecureDevelopmentOnlyWorkspaceNamePersistence()

    def unit_of_work_factory() -> UnitOfWork:
        return SQLiteUnitOfWork(
            connection_factory,
            name_persistence,
            security.payload_codec,
        )

    finalizer = FinalizeIndexing(
        active_scope,
        cancellation_check,
        unit_of_work_factory,
        current_clock,
    )
    return EmbeddingApplicationComposition(
        EmbedStagingChunks(
            active_scope,
            local_models.embedding,
            cancellation_check,
            unit_of_work_factory,
            finalizer,
            current_clock,
            settings.embedding_batch_size,
        ),
        EmbedQuery(active_scope, local_models.embedding),
    )


def _utc_millisecond_clock() -> datetime:
    now = datetime.now(UTC)
    return now.replace(microsecond=(now.microsecond // 1_000) * 1_000)
