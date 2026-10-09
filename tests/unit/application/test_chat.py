"""Tests for pure CHAT content and atomic completion orchestration."""

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from lexlocal.application.chat import (
    CompleteChat,
    PrepareChatContent,
    StartSingleDocumentQuestion,
)
from lexlocal.application.ports.chat import (
    ChatCancelled,
    ChatCompletionTarget,
    ChatIntakeRegistration,
    ChatIntegrityError,
    ChatPersistenceError,
    ChatResponseContractVersion,
    InvalidChatInput,
    QaRequestState,
    QaScopeVersionReference,
)
from lexlocal.application.ports.document_workflow import (
    ActiveDocumentReadiness,
    ActiveDocumentResult,
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
from lexlocal.application.prompts.chat_v1 import (
    CHAT_RESOURCE_VERSION,
    GROUNDED_CHAT_CONTRACT_VERSION,
    GROUNDED_REPAIR_PROMPT_VERSION,
    INSUFFICIENT_NON_ANSWER,
    INSUFFICIENT_NON_ANSWER_CONTRACT_VERSION,
    RELATED_NON_ANSWER,
    RELATED_NON_ANSWER_CONTRACT_VERSION,
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

NOW = datetime(2026, 9, 16, 12, 30, tzinfo=UTC)
WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
QA_REQUEST_ID = QaRequestId("20000000-0000-4000-8000-000000000001")
RETRIEVAL_RUN_ID = RetrievalRunId("30000000-0000-4000-8000-000000000001")
CHAT_MODEL_ID = LocalModelId("40000000-0000-4000-8000-000000000001")
EMBEDDING_MODEL_ID = LocalModelId("41000000-0000-4000-8000-000000000001")
ANSWER_MESSAGE_ID = ChatMessageId("50000000-0000-4000-8000-000000000001")
QUESTION = "  What is the synthetic marker state? Ω\n"
PASSAGES = (
    "The anonymous synthetic marker is active. Ω",
    "The same marker was reviewed on a synthetic date.",
)


def _generation() -> ResolvedRetrievalGeneration:
    generation = IndexGeneration(
        IndexGenerationId("60000000-0000-4000-8000-000000000001"),
        WORKSPACE_ID,
        DocumentVersionId("70000000-0000-4000-8000-000000000001"),
        ProcessingJobId("80000000-0000-4000-8000-000000000001"),
        EMBEDDING_MODEL_ID,
        "chunk-v1",
        "normalize-v1",
        2,
        IndexGenerationState.ACTIVE,
    )
    return ResolvedRetrievalGeneration(
        DocumentId("90000000-0000-4000-8000-000000000001"),
        VersionNumber(1),
        "Anonymous synthetic document",
        PersistedIndexGeneration(generation, NOW, NOW),
        ProcessingJobState.READY,
    )


def _evidence(
    generation: ResolvedRetrievalGeneration,
    rank: int,
) -> RetrievalEvidenceRegistration:
    locator = SourceLocator(
        SourceLocatorId(f"a0000000-0000-4000-8000-{rank:012d}"),
        WORKSPACE_ID,
        generation.document_version_id,
        DocumentPageId(f"b0000000-0000-4000-8000-{rank:012d}"),
        PageNumber(rank),
        SourceLocatorKind.PAGE,
    )
    evidence = Evidence(
        EvidenceItemId(f"c0000000-0000-4000-8000-{rank:012d}"),
        WORKSPACE_ID,
        RETRIEVAL_RUN_ID,
        generation.document_id,
        generation.document_version_id,
        locator.page_number,
        EvidenceRank(rank),
        SimilarityScore(1.0 - rank / 10),
        ChunkId(f"d0000000-0000-4000-8000-{rank:012d}"),
        locator.id,
    )
    return RetrievalEvidenceRegistration(
        evidence,
        generation.index_generation_id,
        rank - 1,
        locator,
        generation.document_display_name,
        generation.version_number,
        PASSAGES[rank - 1],
        NOW,
    )


def _retrieval(*, evidence_count: int = 2) -> RetrievalRegistration:
    generation = _generation()
    evidence = tuple(_evidence(generation, rank) for rank in range(1, evidence_count + 1))
    scope = ResolvedRetrievalScope(
        QaRetrievalRequest(QA_REQUEST_ID, WORKSPACE_ID, QUESTION),
        (generation,),
    )
    return RetrievalRegistration(
        RETRIEVAL_RUN_ID,
        scope,
        RetrievalConfiguration(),
        2,
        evidence,
        NOW,
    )


def _policy() -> EvidencePolicyIdentity:
    status = LocalModelStatus(
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
    return EvidencePolicyIdentity(
        "evidence-policy-v2",
        "evidence-relations-v2",
        status,
    )


def _result(
    state: EvidenceSufficiency,
    *,
    evidence_count: int = 2,
) -> EvidenceSufficiencyResult:
    retrieval = _retrieval(evidence_count=evidence_count)
    if state is EvidenceSufficiency.SUFFICIENT:
        relations = (EvidenceRelation.SUPPORTS,) * evidence_count
        related: tuple[RetrievalEvidenceRegistration, ...] = ()
    elif state is EvidenceSufficiency.RELATED_BUT_INSUFFICIENT:
        relations = (
            EvidenceRelation.IRRELEVANT,
            EvidenceRelation.RELATED_ONLY,
        )
        related = (retrieval.evidence[1],)
    else:
        relations = (EvidenceRelation.IRRELEVANT,) * evidence_count
        related = ()
    assessments = tuple(
        EvidenceAssessment(item.evidence.id, item.evidence.rank, relation)
        for item, relation in zip(retrieval.evidence, relations, strict=True)
    )
    counts = EvidenceRelationCounts(
        sum(item is EvidenceRelation.SUPPORTS for item in relations),
        sum(item is EvidenceRelation.RELATED_ONLY for item in relations),
        sum(item is EvidenceRelation.CONTRADICTS for item in relations),
        sum(item is EvidenceRelation.IRRELEVANT for item in relations),
    )
    return EvidenceSufficiencyResult(
        retrieval,
        state,
        _policy(),
        assessments,
        related,
        AggregateEvidenceCoverage.READY,
        counts,
        False,
    )


def _citation_ids(count: int) -> tuple[CitationId, ...]:
    return tuple(
        CitationId(f"e0000000-0000-4000-8000-{number:012d}")
        for number in range(1, count + 1)
    )


def test_grounded_prompt_preserves_exact_question_evidence_order_and_rules() -> None:
    prompt = PrepareChatContent().build_grounded_prompt(
        _result(EvidenceSufficiency.SUFFICIENT)
    )
    body = json.loads(prompt.text)

    assert prompt.contract_version.value == GROUNDED_CHAT_CONTRACT_VERSION
    assert prompt.repair is False
    assert body["resource_version"] == CHAT_RESOURCE_VERSION
    assert body["completion_contract_version"] == GROUNDED_CHAT_CONTRACT_VERSION
    assert body["question"] == QUESTION
    assert body["evidence"] == [
        {"label": "E1", "excerpt": PASSAGES[0]},
        {"label": "E2", "excerpt": PASSAGES[1]},
    ]
    rules = " ".join(body["rules"])
    assert "only the supplied question and evidence" in rules
    assert "unsupported claims" in rules
    assert "traceable" in rules
    assert "lacks information" in rules
    assert "authoritative legal advice" in rules
    assert str(WORKSPACE_ID) not in prompt.text
    assert "Anonymous synthetic document" not in prompt.text
    assert QUESTION not in repr(prompt)
    assert PASSAGES[0] not in repr(prompt)


def test_repair_prompt_is_versioned_and_confined_to_the_same_exact_context() -> None:
    preparer = PrepareChatContent()
    result = _result(EvidenceSufficiency.SUFFICIENT)
    initial = json.loads(preparer.build_grounded_prompt(result).text)
    repair = preparer.build_repair_prompt(result)
    repaired = json.loads(repair.text)

    assert repair.contract_version.value == GROUNDED_CHAT_CONTRACT_VERSION
    assert repair.repair is True
    assert repaired["repair_prompt_version"] == GROUNDED_REPAIR_PROMPT_VERSION
    assert repaired["attempt"] == "repair"
    assert repaired["question"] == initial["question"]
    assert repaired["evidence"] == initial["evidence"]
    assert "raw_output" not in repaired
    assert "previous_output" not in repaired


def test_valid_output_preserves_answer_and_citation_array_order_exactly() -> None:
    result = _result(EvidenceSufficiency.SUFFICIENT)
    answer = "  Exact answer Ω with E1 mentioned before E2.\n"
    prepared = PrepareChatContent().parse_grounded_output(
        json.dumps(
            {"answer": answer, "citations": ["E2", "E1"]},
            ensure_ascii=False,
        ),
        result,
        answer_message_id=ANSWER_MESSAGE_ID,
        citation_ids=_citation_ids(2),
        created_at=NOW,
    )

    assert prepared.content == answer
    assert prepared.response_contract_version.value == GROUNDED_CHAT_CONTRACT_VERSION
    assert tuple(item.ordinal for item in prepared.citations) == (1, 2)
    assert tuple(item.evidence_item_id for item in prepared.citations) == (
        result.retrieval.evidence[1].evidence.id,
        result.retrieval.evidence[0].evidence.id,
    )
    assert all(item.answer_message_id == ANSWER_MESSAGE_ID for item in prepared.citations)
    assert answer not in repr(prepared)


@pytest.mark.parametrize(
    "output",
    [
        "not-json",
        "[]",
        '{"answer":"ok","answer":"again","citations":["E1"]}',
        '{"answer":"ok"}',
        '{"answer":"ok","citations":["E1"],"extra":true}',
        '{"answer":"  ","citations":["E1"]}',
        '{"answer":1,"citations":["E1"]}',
        '{"answer":"ok","citations":"E1"}',
        '{"answer":"ok","citations":[]}',
        '{"answer":"ok","citations":[1]}',
        '{"answer":"ok","citations":["E01"]}',
        '{"answer":"ok","citations":["e1"]}',
        '{"answer":"ok","citations":["E1","E1"]}',
        '{"answer":"ok","citations":["E3"]}',
    ],
    ids=[
        "malformed-json",
        "non-object",
        "duplicate-top-level-key",
        "missing-key",
        "extra-key",
        "whitespace-answer",
        "wrong-answer-type",
        "wrong-citations-container",
        "empty-citations",
        "wrong-citation-item-type",
        "leading-zero-label",
        "lowercase-label",
        "duplicate-label",
        "unknown-label",
    ],
)
def test_strict_output_rejects_every_invalid_shape_without_leaking_values(
    output: str,
) -> None:
    with pytest.raises(InvalidChatInput) as raised:
        PrepareChatContent().parse_grounded_output(
            output,
            _result(EvidenceSufficiency.SUFFICIENT),
            answer_message_id=ANSWER_MESSAGE_ID,
            citation_ids=_citation_ids(1),
            created_at=NOW,
        )

    message = str(raised.value)
    assert output not in message
    assert QUESTION not in message
    assert PASSAGES[0] not in message


def test_citation_identity_inputs_must_match_the_validated_label_count() -> None:
    output = '{"answer":"Exact answer","citations":["E1","E2"]}'
    result = _result(EvidenceSufficiency.SUFFICIENT)

    with pytest.raises(ChatIntegrityError, match="citation identities are invalid"):
        PrepareChatContent().parse_grounded_output(
            output,
            result,
            answer_message_id=ANSWER_MESSAGE_ID,
            citation_ids=_citation_ids(1),
            created_at=NOW,
        )


def test_related_non_answer_uses_only_policy_approved_related_evidence() -> None:
    result = _result(EvidenceSufficiency.RELATED_BUT_INSUFFICIENT)
    prepared = PrepareChatContent().render_non_answer(
        result,
        answer_message_id=ANSWER_MESSAGE_ID,
        citation_ids=_citation_ids(1),
        created_at=NOW,
    )

    assert prepared.content == RELATED_NON_ANSWER
    assert (
        prepared.response_contract_version.value
        == RELATED_NON_ANSWER_CONTRACT_VERSION
    )
    assert tuple(item.evidence_item_id for item in prepared.citations) == (
        result.related_evidence[0].evidence.id,
    )
    assert tuple(item.ordinal for item in prepared.citations) == (1,)
    assert PASSAGES[0] not in prepared.content


def test_insufficient_non_answer_is_versioned_and_has_zero_citations() -> None:
    result = _result(EvidenceSufficiency.INSUFFICIENT)
    prepared = PrepareChatContent().render_non_answer(
        result,
        answer_message_id=ANSWER_MESSAGE_ID,
        citation_ids=(),
        created_at=NOW,
    )

    assert prepared.content == INSUFFICIENT_NON_ANSWER
    assert (
        prepared.response_contract_version.value
        == INSUFFICIENT_NON_ANSWER_CONTRACT_VERSION
    )
    assert prepared.citations == ()
    assert "similarity" not in prepared.content.lower()
    assert "model" not in prepared.content.lower()


def test_non_answer_rejects_citations_or_a_sufficient_state() -> None:
    preparer = PrepareChatContent()
    with pytest.raises(ChatIntegrityError, match="insufficient citations are invalid"):
        preparer.render_non_answer(
            _result(EvidenceSufficiency.INSUFFICIENT),
            answer_message_id=ANSWER_MESSAGE_ID,
            citation_ids=_citation_ids(1),
            created_at=NOW,
        )
    with pytest.raises(ChatIntegrityError, match="non-answer state is invalid"):
        preparer.render_non_answer(
            _result(EvidenceSufficiency.SUFFICIENT),
            answer_message_id=ANSWER_MESSAGE_ID,
            citation_ids=(),
            created_at=NOW,
        )


def test_grounded_prompt_rejects_non_sufficient_handoff_without_private_data() -> None:
    with pytest.raises(ChatIntegrityError) as raised:
        PrepareChatContent().build_grounded_prompt(
            _result(EvidenceSufficiency.RELATED_BUT_INSUFFICIENT)
        )

    assert QUESTION not in str(raised.value)
    assert PASSAGES[0] not in str(raised.value)


class _ChatRepositoryDouble:
    def __init__(self, target: ChatCompletionTarget) -> None:
        self.target = target
        self.completed = None
        self.added = []
        self.failures = []
        self.fail_add = False
        self.fail_failure = False

    def get_target(self, workspace_id: WorkspaceId, qa_request_id: QaRequestId):
        assert workspace_id == WORKSPACE_ID
        assert qa_request_id == QA_REQUEST_ID
        return self.target

    def get_completed(self, workspace_id: WorkspaceId, qa_request_id: QaRequestId):
        assert workspace_id == WORKSPACE_ID
        assert qa_request_id == QA_REQUEST_ID
        return self.completed

    def add(self, registration) -> None:
        if self.fail_add:
            raise RuntimeError("private staged write detail")
        self.added.append(registration)

    def record_failure(self, update) -> None:
        if self.fail_failure:
            raise RuntimeError("private failure write detail")
        self.failures.append(update)


class _RetrievalRepositoryDouble:
    def __init__(self, registration: RetrievalRegistration) -> None:
        self.registration = None
        self.prepared = registration
        self.added = []

    def get_for_qa_request(self, workspace_id, qa_request_id):
        assert workspace_id == WORKSPACE_ID
        assert qa_request_id == QA_REQUEST_ID
        return self.registration

    def add(self, registration: RetrievalRegistration) -> None:
        self.added.append(registration)
        self.registration = registration


class _UnitOfWorkDouble:
    def __init__(self, factory: "_UnitOfWorkFactory") -> None:
        self.factory = factory
        self.chat = factory.chat
        self.retrieval = factory.retrieval
        self.commits = 0
        self._committed = False
        self._snapshot = None

    def __enter__(self):
        self.factory.active += 1
        self.factory.events.append("uow-enter")
        self._snapshot = (
            len(self.chat.added),
            len(self.chat.failures),
            len(self.retrieval.added),
            self.retrieval.registration,
        )
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if not self._committed and self._snapshot is not None:
            chat_added, failures, retrieval_added, registration = self._snapshot
            del self.chat.added[chat_added:]
            del self.chat.failures[failures:]
            del self.retrieval.added[retrieval_added:]
            self.retrieval.registration = registration
        self.factory.active -= 1
        self.factory.events.append("uow-exit")

    def commit(self) -> None:
        self.factory.events.append("commit")
        if self.factory.fail_commit:
            raise RuntimeError("private commit detail")
        self.commits += 1
        self._committed = True

    def rollback(self) -> None:
        raise AssertionError("explicit rollback is not owned by CHAT")


class _UnitOfWorkFactory:
    def __init__(
        self,
        chat: _ChatRepositoryDouble,
        retrieval: _RetrievalRepositoryDouble,
    ) -> None:
        self.chat = chat
        self.retrieval = retrieval
        self.active = 0
        self.created = []
        self.events = []
        self.fail_commit = False

    def __call__(self):
        result = _UnitOfWorkDouble(self)
        self.created.append(result)
        return result


class _PrepareRetrievalDouble:
    def __init__(
        self,
        factory: _UnitOfWorkFactory,
        registration: RetrievalRegistration,
        events: list[str],
    ) -> None:
        self.factory = factory
        self.registration = registration
        self.events = events
        self.calls = 0

    def __call__(self, qa_request_id, query, configuration):
        assert self.factory.active == 0
        assert qa_request_id == QA_REQUEST_ID
        assert query == QUESTION
        assert configuration == RetrievalConfiguration()
        self.calls += 1
        self.events.append("rag")
        return self.registration


class _EvaluateDouble:
    def __init__(
        self,
        factory: _UnitOfWorkFactory,
        result: EvidenceSufficiencyResult,
        events: list[str],
    ) -> None:
        self.factory = factory
        self.result = result
        self.events = events
        self.calls = 0

    def __call__(self, retrieval):
        assert self.factory.active == 0
        assert retrieval == self.result.retrieval
        self.calls += 1
        self.events.append("rag-002")
        return self.result


class _ProviderDouble:
    def __init__(
        self,
        factory: _UnitOfWorkFactory,
        outputs: tuple[str, ...],
        events: list[str],
    ) -> None:
        self.factory = factory
        self.outputs = list(outputs)
        self.events = events
        self.calls = 0
        self._status = _policy().verifier_status

    @property
    def status(self) -> LocalModelStatus:
        return self._status

    def generate(self, prompt: str, *, profile=None) -> str:
        assert self.factory.active == 0
        assert json.loads(prompt)["question"] == QUESTION
        self.calls += 1
        self.events.append("provider")
        return self.outputs.pop(0)


class _CancellationDouble:
    def __init__(self, cancel_at: int | None = None) -> None:
        self.cancel_at = cancel_at
        self.calls = 0

    def raise_if_cancelled(self) -> None:
        self.calls += 1
        if self.calls == self.cancel_at:
            raise ChatCancelled("private cancellation detail")


def _target(state: QaRequestState = QaRequestState.DRAFT) -> ChatCompletionTarget:
    generation = _generation()
    return ChatCompletionTarget(
        WORKSPACE_ID,
        ChatId("11000000-0000-4000-8000-000000000001"),
        QA_REQUEST_ID,
        ChatMessageId("12000000-0000-4000-8000-000000000001"),
        1,
        QUESTION,
        (
            QaScopeVersionReference(
                WORKSPACE_ID,
                QA_REQUEST_ID,
                generation.document_id,
                generation.document_version_id,
                NOW,
            ),
        ),
        state,
    )


def _completion(
    state: EvidenceSufficiency,
    *,
    outputs: tuple[str, ...] = ('{"answer":"Exact answer","citations":["E1"]}',),
    cancellation: _CancellationDouble | None = None,
    target_state: QaRequestState = QaRequestState.DRAFT,
):
    result = _result(
        state,
        evidence_count=(
            0
            if state is EvidenceSufficiency.INSUFFICIENT
            else (2 if state is EvidenceSufficiency.RELATED_BUT_INSUFFICIENT else 1)
        ),
    )
    chat = _ChatRepositoryDouble(_target(target_state))
    retrieval = _RetrievalRepositoryDouble(result.retrieval)
    factory = _UnitOfWorkFactory(chat, retrieval)
    events: list[str] = []
    prepare = _PrepareRetrievalDouble(factory, result.retrieval, events)
    evaluate = _EvaluateDouble(factory, result, events)
    provider = _ProviderDouble(factory, outputs, events)
    scope = ActiveWorkspaceScope()
    scope.select(WORKSPACE_ID)
    answer_calls: list[int] = []
    citation_calls: list[int] = []
    activity_calls: list[int] = []
    clock_calls: list[int] = []

    def answer_id() -> ChatMessageId:
        answer_calls.append(1)
        return ANSWER_MESSAGE_ID

    def citation_id() -> CitationId:
        citation_calls.append(1)
        return CitationId(
            f"e0000000-0000-4000-8000-{len(citation_calls):012d}"
        )

    def activity_id() -> ActivityEventId:
        activity_calls.append(1)
        return ActivityEventId(
            f"f0000000-0000-4000-8000-{len(activity_calls):012d}"
        )

    def clock() -> datetime:
        clock_calls.append(1)
        return NOW

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
        _CancellationDouble() if cancellation is None else cancellation,
        answer_id,
        citation_id,
        activity_id,
        clock,
    )
    return (
        use_case,
        chat,
        retrieval,
        factory,
        prepare,
        evaluate,
        provider,
        events,
        answer_calls,
        citation_calls,
        activity_calls,
        clock_calls,
    )


@pytest.mark.parametrize(
    "state,provider_calls,citation_count,terminal_state",
    [
        (EvidenceSufficiency.SUFFICIENT, 1, 1, QaRequestState.COMPLETED),
        (
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
            0,
            1,
            QaRequestState.COMPLETED_INSUFFICIENT,
        ),
        (
            EvidenceSufficiency.INSUFFICIENT,
            0,
            0,
            QaRequestState.COMPLETED_INSUFFICIENT,
        ),
    ],
)
def test_completion_orders_existing_rag_policy_generation_and_atomic_write(
    state: EvidenceSufficiency,
    provider_calls: int,
    citation_count: int,
    terminal_state: QaRequestState,
) -> None:
    (
        use_case,
        chat,
        retrieval,
        factory,
        prepare,
        evaluate,
        provider,
        events,
        _,
        citation_calls,
        _,
        _,
    ) = _completion(state)

    completed = use_case(QA_REQUEST_ID)

    assert completed.reused is False
    assert completed.graph.target.state is terminal_state
    assert prepare.calls == 1
    assert evaluate.calls == 1
    assert provider.calls == provider_calls
    assert len(citation_calls) == citation_count
    assert len(retrieval.added) == 1
    assert len(chat.added) == 1
    assert sum(item.commits for item in factory.created) == 1
    assert events[:2] == ["rag", "rag-002"]
    if provider_calls:
        assert events[2] == "provider"


def test_invalid_initial_output_allows_one_repair_then_commits() -> None:
    values = _completion(
        EvidenceSufficiency.SUFFICIENT,
        outputs=(
            "malformed-private-output",
            '{"answer":"Repaired answer","citations":["E1"]}',
        ),
    )
    use_case, chat, _, _, _, _, provider, *_ = values

    completed = use_case(QA_REQUEST_ID)

    assert completed.graph.answer.content == "Repaired answer"
    assert provider.calls == 2
    assert len(chat.added) == 1


@pytest.mark.parametrize("state", [QaRequestState.FAILED, QaRequestState.CANCELLED])
def test_eligible_failed_or_cancelled_target_can_retry_to_completion(
    state: QaRequestState,
) -> None:
    values = _completion(EvidenceSufficiency.SUFFICIENT, target_state=state)

    completed = values[0](QA_REQUEST_ID)

    assert completed.graph.target.state is QaRequestState.COMPLETED
    assert len(values[1].added) == 1


def test_exhausted_repair_records_safe_failure_without_completed_graph() -> None:
    values = _completion(
        EvidenceSufficiency.SUFFICIENT,
        outputs=("private-invalid-initial", "private-invalid-repair"),
    )
    use_case, chat, _, factory, _, _, provider, *_ = values

    with pytest.raises(Exception, match="CHAT output validation failed") as raised:
        use_case(QA_REQUEST_ID)

    assert "private-invalid" not in str(raised.value)
    assert QUESTION not in str(raised.value)
    assert provider.calls == 2
    assert chat.added == []
    assert len(chat.failures) == 1
    assert chat.failures[0].error_code.value == "OUTPUT_VALIDATION_FAILED"
    assert sum(item.commits for item in factory.created) == 1


def test_cancellation_after_inference_discards_output_and_records_cancelled() -> None:
    cancellation = _CancellationDouble(cancel_at=3)
    values = _completion(
        EvidenceSufficiency.SUFFICIENT,
        cancellation=cancellation,
    )
    use_case, chat, _, _, _, _, provider, *_ = values

    with pytest.raises(ChatCancelled, match="CHAT completion was cancelled"):
        use_case(QA_REQUEST_ID)

    assert provider.calls == 1
    assert chat.added == []
    assert len(chat.failures) == 1
    assert chat.failures[0].state is QaRequestState.CANCELLED


def test_sufficient_generation_rejects_provider_model_substitution() -> None:
    values = _completion(EvidenceSufficiency.SUFFICIENT)
    use_case, chat, _, _, _, _, provider, *_ = values
    provider._status = LocalModelStatus(
        replace(
            provider.status.model,
            id=LocalModelId("40000000-0000-4000-8000-000000000099"),
        ),
        ModelReadiness.READY,
        provider.status.execution_provider,
    )

    with pytest.raises(ChatIntegrityError, match="model binding is invalid"):
        use_case(QA_REQUEST_ID)

    assert provider.calls == 0
    assert chat.added == []
    assert len(chat.failures) == 1


def test_completed_compatible_result_is_reused_without_any_expensive_or_new_work() -> None:
    first = _completion(EvidenceSufficiency.SUFFICIENT)
    completed = first[0](QA_REQUEST_ID)
    second = _completion(EvidenceSufficiency.SUFFICIENT)
    (
        use_case,
        chat,
        retrieval,
        factory,
        prepare,
        evaluate,
        provider,
        _,
        answers,
        citations,
        activities,
        clock_calls,
    ) = second
    chat.target = completed.graph.target
    chat.completed = completed.graph
    retrieval.registration = completed.graph.retrieval

    reused = use_case(QA_REQUEST_ID)

    assert reused.reused is True
    assert reused.graph == completed.graph
    assert prepare.calls == evaluate.calls == provider.calls == 0
    assert answers == citations == activities == clock_calls == []
    assert chat.added == chat.failures == []
    assert all(item.commits == 0 for item in factory.created)


def test_incompatible_terminal_result_fails_closed_without_expensive_work() -> None:
    first = _completion(EvidenceSufficiency.SUFFICIENT)
    completed = first[0](QA_REQUEST_ID)
    second = _completion(EvidenceSufficiency.SUFFICIENT)
    (
        use_case,
        chat,
        _,
        _,
        prepare,
        evaluate,
        provider,
        _,
        answers,
        citations,
        _,
        clock_calls,
    ) = second
    graph = replace(
        completed.graph,
        response_contract_version=ChatResponseContractVersion("wrong-contract-v1"),
    )
    chat.target = graph.target
    chat.completed = graph

    with pytest.raises(ChatIntegrityError, match="terminal result is incompatible"):
        use_case(QA_REQUEST_ID)

    assert prepare.calls == evaluate.calls == provider.calls == 0
    assert answers == citations == clock_calls == []


def test_terminal_graph_must_match_the_separately_loaded_target() -> None:
    first = _completion(EvidenceSufficiency.SUFFICIENT)
    completed = first[0](QA_REQUEST_ID)
    second = _completion(EvidenceSufficiency.SUFFICIENT)
    (
        use_case,
        chat,
        _,
        _,
        prepare,
        evaluate,
        provider,
        _,
        answers,
        citations,
        activities,
        clock_calls,
    ) = second
    chat.completed = completed.graph

    with pytest.raises(ChatIntegrityError, match="terminal target is inconsistent"):
        use_case(QA_REQUEST_ID)

    assert prepare.calls == evaluate.calls == provider.calls == 0
    assert answers == citations == activities == clock_calls == []
    assert chat.added == chat.failures == []


def _ready_document() -> ActiveDocumentResult:
    resolved = _generation()
    generation = resolved.persisted.generation
    return ActiveDocumentResult(
        workspace_id=WORKSPACE_ID,
        document_id=resolved.document_id,
        document_version_id=generation.document_version_id,
        processing_job_id=generation.processing_job_id,
        logical_filename="anonymous.pdf",
        page_count=1,
        readiness=ActiveDocumentReadiness.READY,
        active_generation=generation,
    )


class _IntakeCancellation:
    def __init__(self, cancel_at: int | None = None) -> None:
        self.cancel_at = cancel_at
        self.calls = 0
        self.requested = False

    def cancel(self) -> None:
        self.requested = True

    def raise_if_cancelled(self) -> None:
        self.calls += 1
        if self.requested or self.calls == self.cancel_at:
            raise ChatCancelled("private cancellation detail")


class _IntakeRepository:
    def __init__(self) -> None:
        self.registration: ChatIntakeRegistration | None = None
        self.stage_calls = 0
        self.fail = False

    def add_intake(self, registration: ChatIntakeRegistration) -> bool:
        self.stage_calls += 1
        if self.fail:
            raise RuntimeError("private intake write detail")
        if self.registration is None:
            self.registration = registration
            return False
        if self.registration == registration:
            return True
        raise ChatPersistenceError("CHAT intake conflicts with existing state")


class _IntakeUnitOfWork:
    def __init__(self, factory: "_IntakeUnitOfWorkFactory") -> None:
        self.factory = factory
        self.chat = factory.chat
        self.commits = 0
        self.committed = False
        self.snapshot: ChatIntakeRegistration | None = None

    def __enter__(self):
        self.factory.active += 1
        self.snapshot = self.chat.registration
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if not self.committed:
            self.chat.registration = self.snapshot
        self.factory.active -= 1

    def commit(self) -> None:
        if self.factory.fail_commit:
            raise RuntimeError("private intake commit detail")
        self.commits += 1
        self.committed = True
        if self.factory.after_commit is not None:
            self.factory.after_commit()

    def rollback(self) -> None:
        raise AssertionError("CHAT intake must not explicitly roll back")


class _IntakeUnitOfWorkFactory:
    def __init__(self, chat: _IntakeRepository) -> None:
        self.chat = chat
        self.active = 0
        self.created: list[_IntakeUnitOfWork] = []
        self.fail_commit = False
        self.after_commit: Callable[[], None] | None = None

    def __call__(self):
        unit_of_work = _IntakeUnitOfWork(self)
        self.created.append(unit_of_work)
        return unit_of_work


def _intake_use_case(
    *,
    cancellation: _IntakeCancellation | None = None,
) -> tuple[
    StartSingleDocumentQuestion,
    _IntakeRepository,
    _IntakeUnitOfWorkFactory,
    _IntakeCancellation,
    list[str],
]:
    repository = _IntakeRepository()
    factory = _IntakeUnitOfWorkFactory(repository)
    current_cancellation = cancellation or _IntakeCancellation()
    scope = ActiveWorkspaceScope()
    scope.select(WORKSPACE_ID)
    calls: list[str] = []

    def identifier(name: str, value):
        def create():
            assert factory.active == 0
            calls.append(name)
            return value

        return create

    def clock() -> datetime:
        assert factory.active == 0
        calls.append("clock")
        return NOW

    use_case = StartSingleDocumentQuestion(
        scope,
        factory,  # type: ignore[arg-type]
        current_cancellation,
        identifier(
            "chat-id",
            ChatId("a0000000-0000-4000-8000-000000000001"),
        ),
        identifier(
            "message-id",
            ChatMessageId("a1000000-0000-4000-8000-000000000001"),
        ),
        identifier("qa-id", QA_REQUEST_ID),
        clock,
    )
    return use_case, repository, factory, current_cancellation, calls


def test_intake_materializes_before_uow_and_commits_exact_question_once() -> None:
    use_case, repository, factory, _, calls = _intake_use_case()

    registration = use_case.materialize(_ready_document(), QUESTION)
    result = use_case(registration)

    assert calls == ["clock", "chat-id", "message-id", "qa-id"]
    assert registration.question == QUESTION
    assert registration.active_generation == _ready_document().active_generation
    assert result.qa_request_id == QA_REQUEST_ID
    assert result.reused is False
    assert repository.registration is registration
    assert repository.stage_calls == 1
    assert len(factory.created) == 1
    assert factory.created[0].commits == 1


def test_same_intake_attempt_reconstructs_without_new_graph_or_commit() -> None:
    use_case, repository, factory, _, calls = _intake_use_case()
    registration = use_case.materialize(_ready_document(), QUESTION)
    first = use_case(registration)
    second = use_case(registration)

    assert first.reused is False
    assert second.reused is True
    assert second.qa_request_id == first.qa_request_id
    assert repository.registration is registration
    assert repository.stage_calls == 2
    assert calls == ["clock", "chat-id", "message-id", "qa-id"]
    assert sum(item.commits for item in factory.created) == 1


@pytest.mark.parametrize("cancel_at", [2, 3])
def test_intake_cancellation_before_staging_or_commit_leaves_no_graph(
    cancel_at: int,
) -> None:
    cancellation = _IntakeCancellation(cancel_at)
    use_case, repository, factory, _, _ = _intake_use_case(
        cancellation=cancellation
    )
    registration = use_case.materialize(_ready_document(), QUESTION)

    with pytest.raises(ChatCancelled, match="CHAT intake was cancelled") as raised:
        use_case(registration)

    assert "private" not in str(raised.value)
    assert repository.registration is None
    assert sum(item.commits for item in factory.created) == 0


def test_intake_returns_committed_identity_when_cancel_arrives_after_commit() -> None:
    use_case, repository, factory, cancellation, _ = _intake_use_case()
    registration = use_case.materialize(_ready_document(), QUESTION)
    factory.after_commit = cancellation.cancel

    result = use_case(registration)

    assert result.qa_request_id == QA_REQUEST_ID
    assert result.reused is False
    assert repository.registration is registration
    assert cancellation.requested is True
    assert cancellation.calls == 3


@pytest.mark.parametrize("failure", ["write", "commit"])
def test_intake_write_or_commit_failure_rolls_back_without_private_leak(
    failure: str,
) -> None:
    use_case, repository, factory, _, _ = _intake_use_case()
    registration = use_case.materialize(_ready_document(), QUESTION)
    repository.fail = failure == "write"
    factory.fail_commit = failure == "commit"

    with pytest.raises(ChatPersistenceError, match="persistence failed") as raised:
        use_case(registration)

    assert QUESTION not in str(raised.value)
    assert str(QA_REQUEST_ID) not in str(raised.value)
    assert "private" not in str(raised.value)
    assert repository.registration is None


def test_intake_fails_closed_on_conflict_or_active_workspace_substitution() -> None:
    use_case, repository, _, _, _ = _intake_use_case()
    registration = use_case.materialize(_ready_document(), QUESTION)
    use_case(registration)

    with pytest.raises(ChatPersistenceError, match="conflicts"):
        use_case(replace(registration, question="Different synthetic question"))

    other_scope = ActiveWorkspaceScope()
    other_scope.select(WorkspaceId("10000000-0000-4000-8000-000000000099"))
    substituted = StartSingleDocumentQuestion(
        other_scope,
        _IntakeUnitOfWorkFactory(repository),  # type: ignore[arg-type]
        _IntakeCancellation(),
        lambda: registration.chat_id,
        lambda: registration.question_message_id,
        lambda: registration.qa_request_id,
        lambda: NOW,
    )
    with pytest.raises(ChatIntegrityError, match="ownership is invalid"):
        substituted(registration)
