"""Compose deterministic QA retrieval at the Bootstrap boundary."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from lexlocal.application.ports.retrieval import RetrievalConfiguration
from lexlocal.application.ports.unit_of_work import UnitOfWork
from lexlocal.application.retrieval import PrepareRetrieval, StageRetrieval
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.bootstrap.embeddings import EmbeddingApplicationComposition
from lexlocal.bootstrap.security import create_security_providers
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import EvidenceItemId, RetrievalRunId
from lexlocal.domain.retrieval import SimilarityScore
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.persistence.sqlite_unit_of_work import SQLiteUnitOfWork
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
)


@dataclass(frozen=True, slots=True)
class RetrievalApplicationComposition:
    """Expose configured retrieval preparation and caller-owned staging."""

    prepare_retrieval: PrepareRetrieval
    stage_retrieval: StageRetrieval
    configuration: RetrievalConfiguration
    unit_of_work_factory: Callable[[], UnitOfWork]


def compose_retrieval_application(
    settings: AppSettings,
    connection_factory: SQLiteConnectionFactory,
    active_scope: ActiveWorkspaceScope,
    embeddings: EmbeddingApplicationComposition,
    *,
    retrieval_run_id_factory: Callable[[], RetrievalRunId] | None = None,
    evidence_item_id_factory: Callable[[], EvidenceItemId] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> RetrievalApplicationComposition:
    """Wire existing embedding, retrieval, security, and SQLite boundaries."""

    security = create_security_providers(settings)
    configuration = RetrievalConfiguration(
        settings.retrieval_top_k,
        SimilarityScore(settings.retrieval_min_similarity),
    )
    name_persistence = InsecureDevelopmentOnlyWorkspaceNamePersistence()

    def unit_of_work_factory() -> UnitOfWork:
        return SQLiteUnitOfWork(
            connection_factory,
            name_persistence,
            security.payload_codec,
        )

    return RetrievalApplicationComposition(
        PrepareRetrieval(
            active_scope,
            unit_of_work_factory,
            embeddings.embed_query,
            retrieval_run_id_factory or _new_retrieval_run_id,
            evidence_item_id_factory or _new_evidence_item_id,
            clock or _utc_millisecond_clock,
        ),
        StageRetrieval(active_scope),
        configuration,
        unit_of_work_factory,
    )


def _new_retrieval_run_id() -> RetrievalRunId:
    return RetrievalRunId(str(uuid4()))


def _new_evidence_item_id() -> EvidenceItemId:
    return EvidenceItemId(str(uuid4()))


def _utc_millisecond_clock() -> datetime:
    now = datetime.now(UTC)
    return now.replace(microsecond=(now.microsecond // 1_000) * 1_000)
