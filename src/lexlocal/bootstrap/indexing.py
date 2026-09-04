"""Compose the synthetic processing-to-index handoff at Bootstrap."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from lexlocal.application.indexing import PrepareIndexing
from lexlocal.application.ports.indexing import (
    ChunkConfiguration,
    IndexingCancellationCheck,
    IndexPreparationResult,
    InvalidIndexingInput,
)
from lexlocal.application.ports.local_models import (
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
)
from lexlocal.application.ports.processing import ProcessingResult
from lexlocal.application.ports.security import SensitivePayloadCodec
from lexlocal.application.ports.unit_of_work import UnitOfWork
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.bootstrap.security import create_security_providers
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import ChunkId, IndexGenerationId
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.persistence.sqlite_unit_of_work import SQLiteUnitOfWork
from lexlocal.infrastructure.security.insecure_development_indexing import (
    InsecureDevelopmentOnlyChunkEqualityToken,
)
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
)


@dataclass(frozen=True, slots=True)
class IndexingApplicationComposition:
    """Expose configured indexing through an Application-owned result boundary."""

    prepare_index: Callable[[ProcessingResult], IndexPreparationResult]
    configuration: ChunkConfiguration
    unit_of_work_factory: Callable[[], UnitOfWork]


class _NeverCancelled:
    def raise_if_cancelled(self) -> None:
        return None


def compose_indexing_application(
    settings: AppSettings,
    connection_factory: SQLiteConnectionFactory,
    active_scope: ActiveWorkspaceScope,
    embedding_status: LocalModelStatus,
    *,
    sensitive_payload_codec: SensitivePayloadCodec | None = None,
    cancellation: IndexingCancellationCheck | None = None,
    chunk_id_factory: Callable[[], ChunkId] | None = None,
    index_generation_id_factory: Callable[[], IndexGenerationId] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> IndexingApplicationComposition:
    """Wire validated development/test indexing dependencies without running them."""

    security = create_security_providers(settings)
    if (
        not isinstance(embedding_status, LocalModelStatus)
        or embedding_status.readiness is not ModelReadiness.READY
        or embedding_status.model.capability is not ModelCapability.EMBEDDING
        or embedding_status.model.dimensions is None
    ):
        raise InvalidIndexingInput("embedding model status is unavailable")
    configuration = ChunkConfiguration(
        settings.index_chunk_size,
        settings.index_chunk_overlap,
    )
    payload_codec = (
        security.payload_codec if sensitive_payload_codec is None else sensitive_payload_codec
    )
    name_persistence = InsecureDevelopmentOnlyWorkspaceNamePersistence()

    def unit_of_work_factory() -> UnitOfWork:
        return SQLiteUnitOfWork(
            connection_factory,
            name_persistence,
            payload_codec,
        )

    use_case = PrepareIndexing(
        active_scope,
        embedding_status.model,
        _NeverCancelled() if cancellation is None else cancellation,
        InsecureDevelopmentOnlyChunkEqualityToken(),
        unit_of_work_factory,
        chunk_id_factory or _new_chunk_id,
        index_generation_id_factory or _new_index_generation_id,
        clock or _utc_millisecond_clock,
    )

    def prepare_index(processing: ProcessingResult) -> IndexPreparationResult:
        return use_case(processing, configuration)

    return IndexingApplicationComposition(
        prepare_index,
        configuration,
        unit_of_work_factory,
    )


def _new_chunk_id() -> ChunkId:
    return ChunkId(str(uuid4()))


def _new_index_generation_id() -> IndexGenerationId:
    return IndexGenerationId(str(uuid4()))


def _utc_millisecond_clock() -> datetime:
    now = datetime.now(UTC)
    return now.replace(microsecond=(now.microsecond // 1_000) * 1_000)
