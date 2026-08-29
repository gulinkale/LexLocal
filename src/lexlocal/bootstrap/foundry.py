"""Compose the process-lifetime local-model boundary at Bootstrap."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from lexlocal.application.ports.local_models import (
    ChatInferenceProvider,
    EmbeddingProvider,
    LocalModelStatus,
    ModelCapability,
    ResolvedModelRecord,
)
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import LocalModelId
from lexlocal.infrastructure.foundry.local_adapter import FoundryLocalRuntime
from lexlocal.infrastructure.persistence.sqlite_connection import (
    SQLiteConnectionFactory,
)
from lexlocal.infrastructure.persistence.sqlite_unit_of_work import SQLiteUnitOfWork
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
)


class _Runtime(Protocol):
    def resolve_ready(
        self,
        *,
        model_id: LocalModelId,
        requested_alias: str,
        capability: ModelCapability,
    ) -> LocalModelStatus: ...

    def adopt_persisted_record(
        self,
        status: LocalModelStatus,
        persisted: ResolvedModelRecord,
    ) -> LocalModelStatus: ...

    def chat_provider(self, status: LocalModelStatus) -> ChatInferenceProvider: ...

    def embedding_provider(self, status: LocalModelStatus) -> EmbeddingProvider: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class LocalModelComposition:
    """Expose two ready SDK-free capabilities and their safe statuses."""

    chat: ChatInferenceProvider
    embedding: EmbeddingProvider
    chat_status: LocalModelStatus
    embedding_status: LocalModelStatus
    _close: Callable[[], None]

    def close(self) -> None:
        """Release the process-owned runtime after application shutdown."""

        self._close()


def compose_local_models(
    settings: AppSettings,
    connection_factory: SQLiteConnectionFactory,
    *,
    runtime_factory: Callable[[], _Runtime] = FoundryLocalRuntime.initialize,
    model_id_factory: Callable[[], LocalModelId] | None = None,
) -> LocalModelComposition:
    """Resolve, persist, and expose both exact local capabilities atomically."""

    runtime = runtime_factory()
    create_model_id = model_id_factory or _new_model_id
    try:
        chat_status = runtime.resolve_ready(
            model_id=create_model_id(),
            requested_alias=settings.chat_model_alias,
            capability=ModelCapability.CHAT,
        )
        embedding_status = runtime.resolve_ready(
            model_id=create_model_id(),
            requested_alias=settings.embedding_model_alias,
            capability=ModelCapability.EMBEDDING,
        )

        unit_of_work = SQLiteUnitOfWork(
            connection_factory,
            InsecureDevelopmentOnlyWorkspaceNamePersistence(),
        )
        with unit_of_work:
            persisted_chat = unit_of_work.local_models.get_or_add_exact(
                chat_status.model
            )
            persisted_embedding = unit_of_work.local_models.get_or_add_exact(
                embedding_status.model
            )
            chat_status = runtime.adopt_persisted_record(
                chat_status,
                persisted_chat,
            )
            embedding_status = runtime.adopt_persisted_record(
                embedding_status,
                persisted_embedding,
            )
            chat = runtime.chat_provider(chat_status)
            embedding = runtime.embedding_provider(embedding_status)
            unit_of_work.commit()

        return LocalModelComposition(
            chat=chat,
            embedding=embedding,
            chat_status=chat_status,
            embedding_status=embedding_status,
            _close=runtime.close,
        )
    except BaseException:
        try:
            runtime.close()
        except Exception:
            pass
        raise


def _new_model_id() -> LocalModelId:
    return LocalModelId(str(uuid4()))
