"""Integration tests for CHAT completion transaction and cancellation boundaries."""

from datetime import UTC, datetime

import pytest

from lexlocal.application.chat import CompleteChat
from lexlocal.application.ports.chat import (
    ChatCancelled,
    ChatCompletionTarget,
    ChatError,
    ChatPersistenceError,
    QaRequestState,
    QaScopeVersionReference,
)
from lexlocal.application.ports.evidence_sufficiency import (
    AggregateEvidenceCoverage,
    EvidenceAssessment,
    EvidencePolicyIdentity,
    EvidenceRelation,
    EvidenceRelationCounts,
    EvidenceSufficiencyResult,
)
from lexlocal.application.ports.indexing import PersistedIndexGeneration
from lexlocal.application.ports.local_models import (
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
    ResolvedModelRecord,
)
from lexlocal.application.ports.retrieval import (
    QaRetrievalRequest,
    ResolvedRetrievalGeneration,
    ResolvedRetrievalScope,
    RetrievalConfiguration,
    RetrievalEvidenceRegistration,
    RetrievalRegistration,
)
from lexlocal.application.retrieval import StageRetrieval
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.domain.documents import VersionNumber
from lexlocal.domain.identifiers import (
    ActivityEventId,
    ChatId,
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

NOW = datetime(2026, 9, 16, 14, 0, tzinfo=UTC)
WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000021")
QA_REQUEST_ID = QaRequestId("20000000-0000-4000-8000-000000000021")
CHAT_MODEL_ID = LocalModelId("30000000-0000-4000-8000-000000000021")
QUESTION = "What is the anonymous synthetic state?"


def _retrieval() -> RetrievalRegistration:
    generation = IndexGeneration(
        IndexGenerationId("40000000-0000-4000-8000-000000000021"),
        WORKSPACE_ID,
        DocumentVersionId("50000000-0000-4000-8000-000000000021"),
        ProcessingJobId("60000000-0000-4000-8000-000000000021"),
        LocalModelId("70000000-0000-4000-8000-000000000021"),
        "chunk-v1",
        "normalize-v1",
        2,
        IndexGenerationState.ACTIVE,
    )
    resolved = ResolvedRetrievalGeneration(
        DocumentId("80000000-0000-4000-8000-000000000021"),
        VersionNumber(1),
        "Anonymous synthetic document",
        PersistedIndexGeneration(generation, NOW, NOW),
        ProcessingJobState.READY,
    )
    locator = SourceLocator(
        SourceLocatorId("90000000-0000-4000-8000-000000000021"),
        WORKSPACE_ID,
        generation.document_version_id,
        DocumentPageId("a0000000-0000-4000-8000-000000000021"),
        PageNumber(1),
        SourceLocatorKind.PAGE,
    )
    evidence = Evidence(
        EvidenceItemId("b0000000-0000-4000-8000-000000000021"),
        WORKSPACE_ID,
        RetrievalRunId("c0000000-0000-4000-8000-000000000021"),
        resolved.document_id,
        resolved.document_version_id,
        PageNumber(1),
        EvidenceRank(1),
        SimilarityScore(0.8),
        ChunkId("d0000000-0000-4000-8000-000000000021"),
        locator.id,
    )
    scope = ResolvedRetrievalScope(
        QaRetrievalRequest(QA_REQUEST_ID, WORKSPACE_ID, QUESTION),
        (resolved,),
    )
    return RetrievalRegistration(
        evidence.retrieval_run_id,
        scope,
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
                "Anonymous synthetic support",
                NOW,
            ),
        ),
        NOW,
    )


def _status() -> LocalModelStatus:
    return LocalModelStatus(
        ResolvedModelRecord(
            CHAT_MODEL_ID,
            "synthetic-chat",
            "synthetic-chat-id",
            "1",
            ModelCapability.CHAT,
            "synthetic",
        ),
        ModelReadiness.READY,
        "synthetic-cpu",
    )


def _sufficiency(retrieval: RetrievalRegistration) -> EvidenceSufficiencyResult:
    item = retrieval.evidence[0]
    return EvidenceSufficiencyResult(
        retrieval,
        EvidenceSufficiency.SUFFICIENT,
        EvidencePolicyIdentity(
            "evidence-policy-v2",
            "evidence-relations-v2",
            _status(),
        ),
        (
            EvidenceAssessment(
                item.evidence.id,
                item.evidence.rank,
                EvidenceRelation.SUPPORTS,
            ),
        ),
        (),
        AggregateEvidenceCoverage.READY,
        EvidenceRelationCounts(1, 0, 0, 0),
        False,
    )


class _ChatRepository:
    def __init__(self, target: ChatCompletionTarget) -> None:
        self.target = target
        self.added = []
        self.failures = []
        self.fail_add = False
        self.fail_failure = False

    def get_target(self, workspace_id, qa_request_id):
        return self.target

    def get_completed(self, workspace_id, qa_request_id):
        return None

    def add(self, registration) -> None:
        if self.fail_add:
            raise RuntimeError("private write detail")
        self.added.append(registration)

    def record_failure(self, update) -> None:
        if self.fail_failure:
            raise RuntimeError("private failure detail")
        self.failures.append(update)


class _RetrievalRepository:
    def __init__(self) -> None:
        self.registration = None
        self.added = []
        self.fail_add = False

    def get_for_qa_request(self, workspace_id, qa_request_id):
        return self.registration

    def add(self, registration) -> None:
        if self.fail_add:
            raise RuntimeError("private retrieval write detail")
        self.registration = registration
        self.added.append(registration)


class _UnitOfWork:
    def __init__(self, factory: "_Factory") -> None:
        self.factory = factory
        self.chat = factory.chat
        self.retrieval = factory.retrieval
        self.commits = 0
        self.committed = False
        self.snapshot = None

    def __enter__(self):
        self.factory.active += 1
        self.snapshot = (
            len(self.chat.added),
            len(self.chat.failures),
            len(self.retrieval.added),
            self.retrieval.registration,
        )
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if not self.committed and self.snapshot is not None:
            chat_added, failures, retrieval_added, registration = self.snapshot
            del self.chat.added[chat_added:]
            del self.chat.failures[failures:]
            del self.retrieval.added[retrieval_added:]
            self.retrieval.registration = registration
        self.factory.active -= 1

    def commit(self) -> None:
        if self.factory.fail_commit:
            raise RuntimeError("private commit detail")
        self.commits += 1
        self.committed = True

    def rollback(self) -> None:
        raise AssertionError("CHAT must not explicitly roll back")


class _Factory:
    def __init__(self, chat: _ChatRepository, retrieval: _RetrievalRepository) -> None:
        self.chat = chat
        self.retrieval = retrieval
        self.active = 0
        self.fail_commit = False
        self.created = []

    def __call__(self):
        result = _UnitOfWork(self)
        self.created.append(result)
        return result


class _Cancellation:
    def __init__(self, cancel_at: int | None = None) -> None:
        self.cancel_at = cancel_at
        self.calls = 0

    def raise_if_cancelled(self) -> None:
        self.calls += 1
        if self.calls == self.cancel_at:
            raise ChatCancelled("private cancellation detail")


class _Provider:
    def __init__(self, factory: _Factory, outputs: tuple[str, ...]) -> None:
        self.factory = factory
        self.outputs = list(outputs)
        self.calls = 0

    @property
    def status(self) -> LocalModelStatus:
        return _status()

    def generate(self, prompt: str, *, profile=None) -> str:
        assert self.factory.active == 0
        self.calls += 1
        return self.outputs.pop(0)


def _use_case(
    *,
    outputs: tuple[str, ...] = ('{"answer":"Exact answer","citations":["E1"]}',),
    cancellation: _Cancellation | None = None,
):
    retrieval = _retrieval()
    resolved = retrieval.scope.generations[0]
    target = ChatCompletionTarget(
        WORKSPACE_ID,
        ChatId("e0000000-0000-4000-8000-000000000021"),
        QA_REQUEST_ID,
        ChatMessageId("e1000000-0000-4000-8000-000000000021"),
        1,
        QUESTION,
        (
            QaScopeVersionReference(
                WORKSPACE_ID,
                QA_REQUEST_ID,
                resolved.document_id,
                resolved.document_version_id,
                NOW,
            ),
        ),
        QaRequestState.DRAFT,
    )
    chat = _ChatRepository(target)
    retrieval_repository = _RetrievalRepository()
    factory = _Factory(chat, retrieval_repository)
    provider = _Provider(factory, outputs)
    scope = ActiveWorkspaceScope()
    scope.select(WORKSPACE_ID)

    def prepare(qa_request_id, query, configuration):
        assert factory.active == 0
        return retrieval

    def evaluate(value):
        assert factory.active == 0
        return _sufficiency(value)

    use_case = CompleteChat(
        scope,
        factory,  # type: ignore[arg-type]
        prepare,  # type: ignore[arg-type]
        StageRetrieval(scope),
        evaluate,
        provider,
        provider.status,
        "evidence-policy-v2",
        RetrievalConfiguration(),
        _Cancellation() if cancellation is None else cancellation,
        lambda: ChatMessageId("f0000000-0000-4000-8000-000000000021"),
        lambda: CitationId("f1000000-0000-4000-8000-000000000021"),
        lambda: ActivityEventId("f2000000-0000-4000-8000-000000000021"),
        lambda: NOW,
    )
    return use_case, chat, retrieval_repository, factory, provider


def test_retrieval_and_chat_graph_commit_in_one_final_unit_of_work() -> None:
    use_case, chat, retrieval, factory, _ = _use_case()

    result = use_case(QA_REQUEST_ID)

    assert result.reused is False
    assert len(factory.created) == 2
    assert factory.created[0].commits == 0
    assert factory.created[1].commits == 1
    assert retrieval.added == [chat.added[0].sufficiency.retrieval]


@pytest.mark.parametrize("failure", ["retrieval-write", "chat-write", "commit"])
def test_final_write_or_commit_failure_rolls_back_complete_graph(failure: str) -> None:
    use_case, chat, retrieval, factory, _ = _use_case()
    if failure == "retrieval-write":
        retrieval.fail_add = True
    elif failure == "chat-write":
        chat.fail_add = True
    else:
        factory.fail_commit = True

    with pytest.raises(ChatPersistenceError) as raised:
        use_case(QA_REQUEST_ID)

    assert QUESTION not in str(raised.value)
    assert chat.added == []
    assert retrieval.added == []
    assert retrieval.registration is None
    assert len(chat.failures) == (0 if failure == "commit" else 1)


@pytest.mark.parametrize(
    "checkpoint,provider_calls",
    [(1, 0), (2, 0), (3, 1), (4, 1), (5, 1)],
)
def test_every_completion_cancellation_checkpoint_leaves_no_partial_graph(
    checkpoint: int,
    provider_calls: int,
) -> None:
    cancellation = _Cancellation(cancel_at=checkpoint)
    use_case, chat, retrieval, _, provider = _use_case(cancellation=cancellation)

    with pytest.raises(ChatCancelled, match="CHAT completion was cancelled"):
        use_case(QA_REQUEST_ID)

    assert provider.calls == provider_calls
    assert chat.added == []
    assert retrieval.added == []
    assert len(chat.failures) == 1


def test_failure_state_recording_failure_never_masks_original_generation_error() -> None:
    use_case, chat, _, _, _ = _use_case(outputs=())
    chat.fail_failure = True

    with pytest.raises(ChatError, match="CHAT generation failed") as raised:
        use_case(QA_REQUEST_ID)

    assert "private" not in str(raised.value)
    assert chat.added == []
    assert chat.failures == []
