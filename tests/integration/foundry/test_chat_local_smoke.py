"""Opt-in cached/offline CHAT grounded-output smoke path."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from lexlocal.application.chat import PrepareChatContent
from lexlocal.application.ports.chat import InvalidChatInput
from lexlocal.application.ports.evidence_sufficiency import (
    AggregateEvidenceCoverage,
    EvidenceAssessment,
    EvidencePolicyIdentity,
    EvidenceRelation,
    EvidenceRelationCounts,
    EvidenceSufficiencyResult,
)
from lexlocal.application.ports.indexing import PersistedIndexGeneration
from lexlocal.application.ports.local_models import ModelCapability
from lexlocal.application.ports.retrieval import (
    QaRetrievalRequest,
    ResolvedRetrievalGeneration,
    ResolvedRetrievalScope,
    RetrievalConfiguration,
    RetrievalEvidenceRegistration,
    RetrievalRegistration,
)
from lexlocal.bootstrap.settings import load_settings
from lexlocal.domain.documents import VersionNumber
from lexlocal.domain.identifiers import (
    ChatMessageId,
    ChunkId,
    CitationId,
    DocumentId,
    DocumentPageId,
    DocumentVersionId,
    EvidenceItemId,
    IndexGenerationId,
    LocalModelId,
    ProcessingJobId,
    QaRequestId,
    RetrievalRunId,
    SourceLocatorId,
    WorkspaceId,
)
from lexlocal.domain.processing import (
    IndexGeneration,
    IndexGenerationState,
    ProcessingJobState,
)
from lexlocal.domain.retrieval import (
    Evidence,
    EvidenceRank,
    EvidenceSufficiency,
    PageNumber,
    SimilarityScore,
    SourceLocator,
    SourceLocatorKind,
)
from lexlocal.infrastructure.foundry.local_adapter import FoundryLocalRuntime

_OPT_IN_ENVIRONMENT_VARIABLE = "LEXLOCAL_RUN_CHAT001_SMOKE"

pytestmark = [
    pytest.mark.foundry_smoke,
    pytest.mark.skipif(
        os.environ.get(_OPT_IN_ENVIRONMENT_VARIABLE) != "1",
        reason=(f"set {_OPT_IN_ENVIRONMENT_VARIABLE}=1 to run cached/offline CHAT smoke"),
    ),
]

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _sufficient_result(status) -> EvidenceSufficiencyResult:
    workspace_id = WorkspaceId("10000000-0000-4000-8000-000000000001")
    qa_request_id = QaRequestId("20000000-0000-4000-8000-000000000001")
    retrieval_run_id = RetrievalRunId("30000000-0000-4000-8000-000000000001")
    generation = IndexGeneration(
        IndexGenerationId("40000000-0000-4000-8000-000000000001"),
        workspace_id,
        DocumentVersionId("50000000-0000-4000-8000-000000000001"),
        ProcessingJobId("60000000-0000-4000-8000-000000000001"),
        LocalModelId("70000000-0000-4000-8000-000000000001"),
        "chunk-v1",
        "normalize-v1",
        2,
        IndexGenerationState.ACTIVE,
    )
    resolved = ResolvedRetrievalGeneration(
        DocumentId("80000000-0000-4000-8000-000000000001"),
        VersionNumber(1),
        "Anonymous synthetic source",
        PersistedIndexGeneration(generation, NOW, NOW),
        ProcessingJobState.READY,
    )
    locator = SourceLocator(
        SourceLocatorId("90000000-0000-4000-8000-000000000001"),
        workspace_id,
        generation.document_version_id,
        DocumentPageId("a0000000-0000-4000-8000-000000000001"),
        PageNumber(1),
        SourceLocatorKind.PAGE,
    )
    evidence = Evidence(
        EvidenceItemId("b0000000-0000-4000-8000-000000000001"),
        workspace_id,
        retrieval_run_id,
        resolved.document_id,
        resolved.document_version_id,
        PageNumber(1),
        EvidenceRank(1),
        SimilarityScore(1.0),
        ChunkId("c0000000-0000-4000-8000-000000000001"),
        locator.id,
    )
    retrieval = RetrievalRegistration(
        retrieval_run_id,
        ResolvedRetrievalScope(
            QaRetrievalRequest(
                qa_request_id,
                workspace_id,
                "What state does the anonymous marker have?",
            ),
            (resolved,),
        ),
        RetrievalConfiguration(),
        1,
        (
            RetrievalEvidenceRegistration(
                evidence,
                resolved.index_generation_id,
                0,
                locator,
                resolved.document_display_name,
                resolved.version_number,
                "The anonymous marker is ready.",
                NOW,
            ),
        ),
        NOW,
    )
    return EvidenceSufficiencyResult(
        retrieval,
        EvidenceSufficiency.SUFFICIENT,
        EvidencePolicyIdentity(
            "evidence-policy-v2",
            "evidence-relations-v2",
            status,
        ),
        (
            EvidenceAssessment(
                evidence.id,
                evidence.rank,
                EvidenceRelation.SUPPORTS,
            ),
        ),
        (),
        AggregateEvidenceCoverage.READY,
        EvidenceRelationCounts(1, 0, 0, 0),
        False,
    )


def test_cached_configured_chat_model_returns_valid_grounded_contract() -> None:
    """Use only the configured cached model and the normal strict CHAT contract."""

    settings = load_settings()
    runtime = FoundryLocalRuntime.initialize(
        app_name="lexlocal-chat001-smoke",
        model_cache_dir=settings.foundry_model_cache_dir,
    )
    try:
        status = runtime.resolve_ready(
            model_id=LocalModelId(str(uuid4())),
            requested_alias=settings.chat_model_alias,
            capability=ModelCapability.CHAT,
        )
        provider = runtime.chat_provider(status)
        result = _sufficient_result(status)
        evidence = result.retrieval.evidence[0]
        content = PrepareChatContent()
        answer_id = ChatMessageId("f0000000-0000-4000-8000-000000000001")
        citation_id = CitationId("f1000000-0000-4000-8000-000000000001")
        output = provider.generate(content.build_grounded_prompt(result).text)
        try:
            prepared = content.parse_grounded_output(
                output,
                result,
                answer_message_id=answer_id,
                citation_ids=(citation_id,),
                created_at=NOW,
            )
        except InvalidChatInput:
            repaired = provider.generate(content.build_repair_prompt(result).text)
            prepared = content.parse_grounded_output(
                repaired,
                result,
                answer_message_id=answer_id,
                citation_ids=(citation_id,),
                created_at=NOW,
            )

        assert prepared.content.strip()
        assert tuple(item.evidence_item_id for item in prepared.citations) == (
            evidence.evidence.id,
        )
        assert provider.status == status
    finally:
        runtime.close()
