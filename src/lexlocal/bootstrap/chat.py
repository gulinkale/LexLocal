"""Compose one existing QA request through the grounded CHAT boundary."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from lexlocal.application.chat import CompleteChat
from lexlocal.application.ports.chat import ChatCancellationCheck
from lexlocal.application.ports.unit_of_work import UnitOfWork
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.bootstrap.evidence_sufficiency import (
    EvidenceSufficiencyApplicationComposition,
)
from lexlocal.bootstrap.foundry import LocalModelComposition
from lexlocal.bootstrap.retrieval import RetrievalApplicationComposition
from lexlocal.bootstrap.security import SecurityProviders, create_security_providers
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import (
    ActivityEventId,
    ChatMessageId,
    CitationId,
)
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.persistence.sqlite_unit_of_work import SQLiteUnitOfWork
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
)


class ChatBootstrapConfigurationError(Exception):
    """Report a sanitized CHAT composition mismatch."""


@dataclass(frozen=True, slots=True)
class ChatApplicationComposition:
    """Expose the configured existing-QA completion use case."""

    complete_chat: CompleteChat
    unit_of_work_factory: Callable[[], UnitOfWork]


class _NeverCancelled:
    def raise_if_cancelled(self) -> None:
        return None


def compose_chat_application(
    settings: AppSettings,
    connection_factory: SQLiteConnectionFactory,
    active_scope: ActiveWorkspaceScope,
    local_models: LocalModelComposition,
    retrieval: RetrievalApplicationComposition,
    sufficiency: EvidenceSufficiencyApplicationComposition,
    *,
    cancellation: ChatCancellationCheck | None = None,
    answer_message_id_factory: Callable[[], ChatMessageId] | None = None,
    citation_id_factory: Callable[[], CitationId] | None = None,
    activity_event_id_factory: Callable[[], ActivityEventId] | None = None,
    clock: Callable[[], datetime] | None = None,
    security_providers: SecurityProviders | None = None,
) -> ChatApplicationComposition:
    """Wire existing RAG, verifier, model, security, and SQLite components."""

    security = security_providers or create_security_providers(settings)
    if sufficiency.policy.verifier_status != local_models.chat_status:
        raise ChatBootstrapConfigurationError("CHAT evidence verifier model binding is invalid")
    try:
        provider_status = local_models.chat.status
    except Exception:
        raise ChatBootstrapConfigurationError("CHAT provider binding is unavailable") from None
    if provider_status != local_models.chat_status:
        raise ChatBootstrapConfigurationError("CHAT provider binding is invalid")

    name_persistence = InsecureDevelopmentOnlyWorkspaceNamePersistence()

    def unit_of_work_factory() -> UnitOfWork:
        return SQLiteUnitOfWork(
            connection_factory,
            name_persistence,
            security.payload_codec,
        )

    current_clock = _utc_millisecond_clock if clock is None else clock
    completion = CompleteChat(
        active_scope,
        unit_of_work_factory,
        retrieval.prepare_retrieval,
        retrieval.stage_retrieval,
        sufficiency.evaluate_evidence_sufficiency,
        local_models.chat,
        local_models.chat_status,
        sufficiency.policy.evidence_policy_version,
        retrieval.configuration,
        _NeverCancelled() if cancellation is None else cancellation,
        answer_message_id_factory or _new_answer_message_id,
        citation_id_factory or _new_citation_id,
        activity_event_id_factory or _new_activity_event_id,
        current_clock,
    )
    return ChatApplicationComposition(completion, unit_of_work_factory)


def _new_answer_message_id() -> ChatMessageId:
    return ChatMessageId(str(uuid4()))


def _new_citation_id() -> CitationId:
    return CitationId(str(uuid4()))


def _new_activity_event_id() -> ActivityEventId:
    return ActivityEventId(str(uuid4()))


def _utc_millisecond_clock() -> datetime:
    now = datetime.now(UTC)
    return now.replace(microsecond=(now.microsecond // 1_000) * 1_000)
