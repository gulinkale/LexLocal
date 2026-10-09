"""Tests for the Application-owned CHAT completion contracts."""

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from lexlocal.application.ports.chat import (
    ChatActivityEvent,
    ChatActivityResult,
    ChatActivityType,
    ChatAssistantMessage,
    ChatCancellationCheck,
    ChatCancelled,
    ChatCitationRegistration,
    ChatCompletionRegistration,
    ChatCompletionResult,
    ChatCompletionTarget,
    ChatError,
    ChatFailureCode,
    ChatFailureUpdate,
    ChatIntakeRegistration,
    ChatIntakeResult,
    ChatIntegrityError,
    ChatPersistenceError,
    ChatRepository,
    ChatResponseContractVersion,
    ChatTerminalGraph,
    ChatVerifierSnapshot,
    InvalidChatInput,
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

NOW = datetime(2026, 9, 16, 14, 30, tzinfo=UTC)
WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
OTHER_WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000002")
CHAT_ID = ChatId("20000000-0000-4000-8000-000000000001")
QA_REQUEST_ID = QaRequestId("30000000-0000-4000-8000-000000000001")
QUESTION_MESSAGE_ID = ChatMessageId("40000000-0000-4000-8000-000000000001")
ANSWER_MESSAGE_ID = ChatMessageId("40000000-0000-4000-8000-000000000002")
RETRIEVAL_RUN_ID = RetrievalRunId("50000000-0000-4000-8000-000000000001")
EMBEDDING_MODEL_ID = LocalModelId("60000000-0000-4000-8000-000000000001")
CHAT_MODEL_ID = LocalModelId("60000000-0000-4000-8000-000000000002")
DOCUMENT_ID = DocumentId("70000000-0000-4000-8000-000000000001")
VERSION_ID = DocumentVersionId("80000000-0000-4000-8000-000000000001")
QUESTION = " Private synthetic question Ω? "
ANSWER = " Private synthetic grounded answer Ω. "


def _scope_reference(
    *,
    workspace_id: WorkspaceId = WORKSPACE_ID,
    qa_request_id: QaRequestId = QA_REQUEST_ID,
) -> QaScopeVersionReference:
    return QaScopeVersionReference(
        workspace_id,
        qa_request_id,
        DOCUMENT_ID,
        VERSION_ID,
        NOW,
    )


def _target(
    *,
    state: QaRequestState = QaRequestState.DRAFT,
    answer_message_id: ChatMessageId | None = None,
    workspace_id: WorkspaceId = WORKSPACE_ID,
    scope_versions: tuple[QaScopeVersionReference, ...] | None = None,
) -> ChatCompletionTarget:
    return ChatCompletionTarget(
        workspace_id,
        CHAT_ID,
        QA_REQUEST_ID,
        QUESTION_MESSAGE_ID,
        3,
        QUESTION,
        (_scope_reference(workspace_id=workspace_id),)
        if scope_versions is None
        else scope_versions,
        state,
        answer_message_id,
    )


def _intake() -> ChatIntakeRegistration:
    generation = _retrieval().scope.generations[0].persisted.generation
    return ChatIntakeRegistration(
        WORKSPACE_ID,
        CHAT_ID,
        QUESTION_MESSAGE_ID,
        QA_REQUEST_ID,
        DOCUMENT_ID,
        VERSION_ID,
        generation,
        QUESTION,
        NOW,
    )


def _status() -> LocalModelStatus:
    return LocalModelStatus(
        ResolvedModelRecord(
            CHAT_MODEL_ID,
            "synthetic-chat",
            "synthetic-chat:1",
            "1",
            ModelCapability.CHAT,
            "local",
        ),
        ModelReadiness.READY,
        "SyntheticExecutionProvider",
    )


def _retrieval(evidence_count: int = 2) -> RetrievalRegistration:
    generation = IndexGeneration(
        IndexGenerationId("90000000-0000-4000-8000-000000000001"),
        WORKSPACE_ID,
        VERSION_ID,
        ProcessingJobId("a0000000-0000-4000-8000-000000000001"),
        EMBEDDING_MODEL_ID,
        "chunk-v1",
        "normalization-v1",
        2,
        IndexGenerationState.ACTIVE,
    )
    resolved = ResolvedRetrievalGeneration(
        DOCUMENT_ID,
        VersionNumber(1),
        "Synthetic document",
        PersistedIndexGeneration(generation, NOW, activated_at=NOW),
        ProcessingJobState.READY,
    )
    scope = ResolvedRetrievalScope(
        QaRetrievalRequest(QA_REQUEST_ID, WORKSPACE_ID, QUESTION),
        (resolved,),
    )
    evidence = tuple(
        _evidence(resolved, number) for number in range(1, evidence_count + 1)
    )
    return RetrievalRegistration(
        RETRIEVAL_RUN_ID,
        scope,
        RetrievalConfiguration(),
        2,
        evidence,
        NOW,
    )


def _evidence(
    generation: ResolvedRetrievalGeneration,
    number: int,
) -> RetrievalEvidenceRegistration:
    locator = SourceLocator(
        SourceLocatorId(f"b0000000-0000-4000-8000-{number:012d}"),
        WORKSPACE_ID,
        VERSION_ID,
        DocumentPageId(f"c0000000-0000-4000-8000-{number:012d}"),
        PageNumber(number),
        SourceLocatorKind.PAGE,
    )
    evidence = Evidence(
        EvidenceItemId(f"d0000000-0000-4000-8000-{number:012d}"),
        WORKSPACE_ID,
        RETRIEVAL_RUN_ID,
        DOCUMENT_ID,
        VERSION_ID,
        PageNumber(number),
        EvidenceRank(number),
        SimilarityScore(1.0 - number / 10),
        ChunkId(f"e0000000-0000-4000-8000-{number:012d}"),
        locator.id,
    )
    return RetrievalEvidenceRegistration(
        evidence,
        generation.index_generation_id,
        number - 1,
        locator,
        generation.document_display_name,
        generation.version_number,
        f"Private synthetic excerpt {number} Ω",
        NOW,
    )


def _sufficiency(
    state: EvidenceSufficiency = EvidenceSufficiency.SUFFICIENT,
    *,
    evidence_count: int = 2,
    repair_used: bool = False,
) -> EvidenceSufficiencyResult:
    retrieval = _retrieval(evidence_count)
    if not retrieval.evidence:
        relations: tuple[EvidenceRelation, ...] = ()
    elif state is EvidenceSufficiency.SUFFICIENT:
        relations = tuple(EvidenceRelation.SUPPORTS for _ in retrieval.evidence)
    elif state is EvidenceSufficiency.RELATED_BUT_INSUFFICIENT:
        relations = tuple(
            EvidenceRelation.RELATED_ONLY if index == 0 else EvidenceRelation.IRRELEVANT
            for index, _ in enumerate(retrieval.evidence)
        )
    else:
        relations = tuple(EvidenceRelation.IRRELEVANT for _ in retrieval.evidence)
    assessments = tuple(
        EvidenceAssessment(item.evidence.id, item.evidence.rank, relation)
        for item, relation in zip(retrieval.evidence, relations, strict=True)
    )
    counts = EvidenceRelationCounts(
        relations.count(EvidenceRelation.SUPPORTS),
        relations.count(EvidenceRelation.RELATED_ONLY),
        relations.count(EvidenceRelation.CONTRADICTS),
        relations.count(EvidenceRelation.IRRELEVANT),
    )
    related = (
        tuple(
            item
            for item, relation in zip(retrieval.evidence, relations, strict=True)
            if relation is not EvidenceRelation.IRRELEVANT
        )
        if state is EvidenceSufficiency.RELATED_BUT_INSUFFICIENT
        else ()
    )
    return EvidenceSufficiencyResult(
        retrieval,
        state,
        EvidencePolicyIdentity("evidence-policy-v2", "evidence-relations-v2", _status()),
        assessments,
        related,
        AggregateEvidenceCoverage.READY,
        counts,
        repair_used,
    )


def _answer() -> ChatAssistantMessage:
    return ChatAssistantMessage(
        ANSWER_MESSAGE_ID,
        WORKSPACE_ID,
        CHAT_ID,
        4,
        ANSWER,
        NOW,
    )


def _activity(
    result: ChatActivityResult = ChatActivityResult.SUCCESS,
) -> ChatActivityEvent:
    event_type = {
        ChatActivityResult.SUCCESS: ChatActivityType.QA_COMPLETED,
        ChatActivityResult.WARNING: ChatActivityType.QA_COMPLETED,
        ChatActivityResult.FAILED: ChatActivityType.QA_FAILED,
        ChatActivityResult.CANCELLED: ChatActivityType.QA_CANCELLED,
    }[result]
    return ChatActivityEvent(
        ActivityEventId("f0000000-0000-4000-8000-000000000001"),
        WORKSPACE_ID,
        QA_REQUEST_ID,
        event_type,
        result,
        NOW,
    )


def _citations(
    sufficiency: EvidenceSufficiencyResult,
) -> tuple[ChatCitationRegistration, ...]:
    evidence: tuple[RetrievalEvidenceRegistration, ...]
    if sufficiency.state is EvidenceSufficiency.INSUFFICIENT:
        evidence = ()
    elif sufficiency.state is EvidenceSufficiency.RELATED_BUT_INSUFFICIENT:
        evidence = sufficiency.related_evidence
    else:
        evidence = sufficiency.retrieval.evidence[:1]
    return tuple(
        ChatCitationRegistration(
            CitationId(f"11000000-0000-4000-8000-{ordinal:012d}"),
            WORKSPACE_ID,
            item.evidence.id,
            ANSWER_MESSAGE_ID,
            ordinal,
            NOW,
        )
        for ordinal, item in enumerate(evidence, start=1)
    )


def _completion(
    state: EvidenceSufficiency = EvidenceSufficiency.SUFFICIENT,
    *,
    evidence_count: int = 2,
) -> ChatCompletionRegistration:
    sufficiency = _sufficiency(state, evidence_count=evidence_count)
    return ChatCompletionRegistration(
        _target(),
        sufficiency,
        _answer(),
        ChatResponseContractVersion("chat-answer-v1"),
        CHAT_MODEL_ID if state is EvidenceSufficiency.SUFFICIENT else None,
        _citations(sufficiency),
        NOW,
        _activity(
            ChatActivityResult.SUCCESS
            if state is EvidenceSufficiency.SUFFICIENT
            else ChatActivityResult.WARNING
        ),
    )


def _terminal_graph(
    registration: ChatCompletionRegistration,
) -> ChatTerminalGraph:
    target = replace(
        registration.target,
        state=registration.terminal_state,
        answer_message_id=registration.answer.id,
    )
    return ChatTerminalGraph(
        target,
        registration.sufficiency.retrieval,
        registration.snapshot,
        registration.answer,
        registration.sufficiency.state,
        registration.response_contract_version,
        registration.chat_model_id,
        registration.citations,
        registration.completed_at,
        registration.activity,
    )


class _RepositoryDouble:
    def get_target(
        self,
        workspace_id: WorkspaceId,
        qa_request_id: QaRequestId,
    ) -> ChatCompletionTarget | None:
        return _target() if (workspace_id, qa_request_id) == (WORKSPACE_ID, QA_REQUEST_ID) else None

    def get_completed(
        self,
        workspace_id: WorkspaceId,
        qa_request_id: QaRequestId,
    ) -> ChatTerminalGraph | None:
        return None

    def add_intake(self, registration: ChatIntakeRegistration) -> bool:
        self.intake = registration
        return False

    def add(self, registration: ChatCompletionRegistration) -> None:
        self.registration = registration

    def record_failure(self, update: ChatFailureUpdate) -> None:
        self.failure = update


class _CancellationDouble:
    def raise_if_cancelled(self) -> None:
        return None


_REPOSITORY_CONFORMANCE: ChatRepository = _RepositoryDouble()
_CANCELLATION_CONFORMANCE: ChatCancellationCheck = _CancellationDouble()


def test_intake_contract_preserves_exact_private_question_and_scope() -> None:
    registration = _intake()
    target = registration.target
    result = ChatIntakeResult(registration.qa_request_id, reused=False)

    assert target.question == QUESTION
    assert target.question_sequence_number == 1
    assert target.state is QaRequestState.DRAFT
    assert target.scope_versions == (
        QaScopeVersionReference(
            WORKSPACE_ID,
            QA_REQUEST_ID,
            DOCUMENT_ID,
            VERSION_ID,
            NOW,
        ),
    )
    assert result.qa_request_id == QA_REQUEST_ID
    assert QUESTION.strip() not in repr(registration)
    for protected in (
        WORKSPACE_ID,
        CHAT_ID,
        QUESTION_MESSAGE_ID,
        QA_REQUEST_ID,
        DOCUMENT_ID,
        VERSION_ID,
        registration.active_generation.id,
    ):
        assert str(protected) not in repr(registration)
        assert str(protected) not in repr(result)


def test_intake_contract_rejects_invalid_question_and_generation_safely() -> None:
    registration = _intake()
    with pytest.raises(InvalidChatInput, match="registration is invalid"):
        replace(registration, question=" \t\n")
    with pytest.raises(ChatIntegrityError, match="ownership is invalid"):
        replace(
            registration,
            active_generation=replace(
                registration.active_generation,
                state=IndexGenerationState.ARCHIVED,
            ),
        )


def test_target_preserves_private_question_and_exact_authoritative_scope() -> None:
    target = _target()

    assert target.question == QUESTION
    assert target.scope_versions == (_scope_reference(),)
    assert target.answer_message_id is None
    assert QUESTION.strip() not in repr(target)
    with pytest.raises(FrozenInstanceError):
        target.question = "changed"  # type: ignore[misc]


def test_target_rejects_owner_scope_substitution_before_private_content() -> None:
    private_question = "private-value-that-must-not-leak"
    substituted_scope = (_scope_reference(workspace_id=OTHER_WORKSPACE_ID),)

    with pytest.raises(ChatIntegrityError, match="scope is invalid") as captured:
        replace(
            _target(),
            question=private_question,
            scope_versions=substituted_scope,
        )

    assert private_question not in str(captured.value)
    assert captured.value.__cause__ is None


def test_target_requires_terminal_answer_link_and_canonical_unique_scope() -> None:
    with pytest.raises(ChatIntegrityError, match="state is inconsistent"):
        _target(state=QaRequestState.COMPLETED)
    with pytest.raises(ChatIntegrityError, match="state is inconsistent"):
        _target(answer_message_id=ANSWER_MESSAGE_ID)
    with pytest.raises(ChatIntegrityError, match="scope is inconsistent"):
        _target(scope_versions=(_scope_reference(), _scope_reference()))


def test_snapshot_projects_exact_rag002_result_without_sensitive_content() -> None:
    result = _sufficiency(
        EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
        repair_used=True,
    )
    snapshot = ChatVerifierSnapshot.from_result(result)

    assert snapshot.workspace_id == WORKSPACE_ID
    assert snapshot.qa_request_id == QA_REQUEST_ID
    assert snapshot.retrieval_run_id == RETRIEVAL_RUN_ID
    assert snapshot.evidence_policy_version == "evidence-policy-v2"
    assert tuple(item.rank.value for item in snapshot.relations) == (1, 2)
    assert tuple(item.relation for item in snapshot.relations) == (
        EvidenceRelation.RELATED_ONLY,
        EvidenceRelation.IRRELEVANT,
    )
    assert snapshot.relation_counts == EvidenceRelationCounts(0, 1, 0, 1)
    assert "Private synthetic" not in repr(snapshot)


def test_zero_evidence_snapshot_has_frozen_empty_shape() -> None:
    snapshot = ChatVerifierSnapshot.from_result(
        _sufficiency(EvidenceSufficiency.INSUFFICIENT, evidence_count=0)
    )

    assert snapshot.relations == ()
    assert snapshot.relation_counts.total == 0
    assert snapshot.repair_used is False

    with pytest.raises(ChatIntegrityError, match="snapshot is inconsistent"):
        replace(snapshot, repair_used=True)


def test_snapshot_rejects_duplicate_missing_or_cross_owner_relations() -> None:
    snapshot = ChatVerifierSnapshot.from_result(_sufficiency())
    first = snapshot.relations[0]

    with pytest.raises(ChatIntegrityError, match="snapshot is inconsistent"):
        replace(snapshot, relations=(first, first))
    with pytest.raises(ChatIntegrityError, match="snapshot is inconsistent"):
        replace(snapshot, relations=snapshot.relations[:1])
    with pytest.raises(ChatIntegrityError, match="ownership is invalid"):
        replace(
            snapshot,
            relations=(replace(first, workspace_id=OTHER_WORKSPACE_ID), snapshot.relations[1]),
        )


def test_grounded_registration_binds_exact_rag_result_and_citations() -> None:
    registration = _completion()

    assert registration.terminal_state is QaRequestState.COMPLETED
    assert registration.snapshot == ChatVerifierSnapshot.from_result(
        registration.sufficiency
    )
    assert registration.chat_model_id == CHAT_MODEL_ID
    assert tuple(item.ordinal for item in registration.citations) == (1,)
    rendered = repr(registration)
    assert QUESTION.strip() not in rendered
    assert ANSWER.strip() not in rendered


@pytest.mark.parametrize(
    ("state", "terminal_state", "citation_count"),
    [
        (
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
            QaRequestState.COMPLETED_INSUFFICIENT,
            1,
        ),
        (
            EvidenceSufficiency.INSUFFICIENT,
            QaRequestState.COMPLETED_INSUFFICIENT,
            0,
        ),
    ],
)
def test_non_sufficient_registration_has_no_model_and_exact_citation_shape(
    state: EvidenceSufficiency,
    terminal_state: QaRequestState,
    citation_count: int,
) -> None:
    registration = _completion(state)

    assert registration.terminal_state is terminal_state
    assert registration.chat_model_id is None
    assert len(registration.citations) == citation_count


def test_registration_rejects_model_and_citation_shape_for_each_outcome() -> None:
    grounded = _completion()
    related = _completion(EvidenceSufficiency.RELATED_BUT_INSUFFICIENT)
    insufficient = _completion(EvidenceSufficiency.INSUFFICIENT)

    with pytest.raises(ChatIntegrityError, match="grounded CHAT completion"):
        replace(grounded, chat_model_id=None)
    with pytest.raises(ChatIntegrityError, match="related evidence citations"):
        replace(related, citations=())
    with pytest.raises(ChatIntegrityError, match="insufficient CHAT completion"):
        replace(insufficient, chat_model_id=CHAT_MODEL_ID)


def test_registration_rejects_citation_gaps_duplicates_and_substitution() -> None:
    registration = _completion()
    citation = registration.citations[0]

    with pytest.raises(ChatIntegrityError, match="citation set is inconsistent"):
        replace(registration, citations=(replace(citation, ordinal=2),))
    with pytest.raises(ChatIntegrityError, match="citation set is inconsistent"):
        replace(registration, citations=(citation, replace(citation, ordinal=2)))
    with pytest.raises(ChatIntegrityError, match="evidence ownership is invalid"):
        replace(
            registration,
            citations=(
                replace(
                    citation,
                    evidence_item_id=EvidenceItemId(
                        "d0000000-0000-4000-8000-000000000099"
                    ),
                ),
            ),
        )


def test_registration_rejects_workspace_question_scope_and_message_substitution() -> None:
    registration = _completion()

    with pytest.raises(ChatIntegrityError, match="ownership is inconsistent"):
        replace(
            registration,
            answer=replace(registration.answer, workspace_id=OTHER_WORKSPACE_ID),
        )
    wrong_query = replace(
        registration.sufficiency.retrieval.scope.request,
        query="Different private synthetic question",
    )
    wrong_scope = replace(
        registration.sufficiency.retrieval.scope,
        request=wrong_query,
    )
    wrong_retrieval = replace(
        registration.sufficiency.retrieval,
        scope=wrong_scope,
    )
    with pytest.raises(ChatIntegrityError, match="ownership is inconsistent"):
        replace(
            registration,
            sufficiency=replace(
                registration.sufficiency,
                retrieval=wrong_retrieval,
            ),
        )


def test_registration_rejects_silent_reduction_of_full_qa_scope() -> None:
    registration = _completion()
    second_scope = QaScopeVersionReference(
        WORKSPACE_ID,
        QA_REQUEST_ID,
        DocumentId("70000000-0000-4000-8000-000000000002"),
        DocumentVersionId("80000000-0000-4000-8000-000000000002"),
        NOW,
    )

    with pytest.raises(ChatIntegrityError, match="scope is inconsistent"):
        replace(
            registration,
            target=replace(
                registration.target,
                scope_versions=(_scope_reference(), second_scope),
            ),
        )


def test_terminal_graph_and_result_preserve_complete_retry_identity() -> None:
    registration = _completion(EvidenceSufficiency.RELATED_BUT_INSUFFICIENT)
    graph = _terminal_graph(registration)
    result = ChatCompletionResult(graph, reused=True)

    assert result.graph.target.answer_message_id == ANSWER_MESSAGE_ID
    assert result.graph.target.state is QaRequestState.COMPLETED_INSUFFICIENT
    assert result.graph.snapshot == registration.snapshot
    assert result.graph.citations == registration.citations
    assert result.reused is True
    assert QUESTION.strip() not in repr(result)


def test_terminal_graph_rejects_partial_or_conflicting_historical_state() -> None:
    graph = _terminal_graph(_completion())

    with pytest.raises(ChatIntegrityError, match="terminal state is inconsistent"):
        replace(
            graph,
            target=replace(
                graph.target,
                state=QaRequestState.COMPLETED_INSUFFICIENT,
            ),
        )
    with pytest.raises(ChatIntegrityError, match="snapshot binding is inconsistent"):
        replace(
            graph,
            snapshot=replace(
                graph.snapshot,
                retrieval_run_id=RetrievalRunId(
                    "50000000-0000-4000-8000-000000000099"
                ),
                relations=tuple(
                    replace(
                        item,
                        retrieval_run_id=RetrievalRunId(
                            "50000000-0000-4000-8000-000000000099"
                        ),
                    )
                    for item in graph.snapshot.relations
                ),
            ),
        )


@pytest.mark.parametrize(
    ("state", "activity_result"),
    [
        (QaRequestState.FAILED, ChatActivityResult.FAILED),
        (QaRequestState.CANCELLED, ChatActivityResult.CANCELLED),
    ],
)
def test_failure_update_is_sanitized_and_bound_to_exact_target(
    state: QaRequestState,
    activity_result: ChatActivityResult,
) -> None:
    error_code = (
        ChatFailureCode.PERSISTENCE_FAILED
        if state is QaRequestState.FAILED
        else ChatFailureCode.CANCELLED
    )
    update = ChatFailureUpdate(
        _target(),
        state,
        error_code,
        NOW,
        _activity(activity_result),
    )

    assert update.error_code is error_code
    assert update.activity.summary_key == (
        "chat.qa.failed"
        if state is QaRequestState.FAILED
        else "chat.qa.cancelled"
    )
    assert QUESTION.strip() not in repr(update)

    with pytest.raises(ChatIntegrityError, match="ownership is invalid"):
        replace(
            update,
            activity=replace(update.activity, workspace_id=OTHER_WORKSPACE_ID),
        )

    with pytest.raises(InvalidChatInput, match="failure update is invalid") as captured:
        replace(update, error_code="private-synthetic-error")  # type: ignore[arg-type]
    assert "private-synthetic-error" not in str(captured.value)


def test_contracts_reject_non_utc_timestamps() -> None:
    non_utc = NOW.astimezone(timezone(timedelta(hours=3)))

    with pytest.raises(InvalidChatInput, match="timestamp is invalid"):
        replace(_scope_reference(), included_at=non_utc)
    with pytest.raises(InvalidChatInput, match="timestamp is invalid"):
        replace(_answer(), created_at=non_utc)


def test_errors_and_protocols_are_minimal_and_transaction_neutral() -> None:
    assert all(
        issubclass(error_type, ChatError)
        for error_type in (
            InvalidChatInput,
            ChatIntegrityError,
            ChatPersistenceError,
            ChatCancelled,
        )
    )
    assert _REPOSITORY_CONFORMANCE.get_target(WORKSPACE_ID, QA_REQUEST_ID) == _target()
    _CANCELLATION_CONFORMANCE.raise_if_cancelled()
    assert {
        name
        for name, value in vars(ChatRepository).items()
        if callable(value) and not name.startswith("_")
    } == {"get_target", "get_completed", "add_intake", "add", "record_failure"}
    assert not hasattr(ChatRepository, "commit")
    assert not hasattr(ChatRepository, "rollback")
    assert {
        name
        for name, value in vars(ChatCancellationCheck).items()
        if callable(value) and not name.startswith("_")
    } == {"raise_if_cancelled"}


def test_contract_errors_do_not_expose_protected_values() -> None:
    private_value = "private-synthetic-answer-that-must-not-leak"

    with pytest.raises(InvalidChatInput) as captured:
        replace(_answer(), content=private_value, sequence_number=0)

    assert private_value not in str(captured.value)
    assert captured.value.__cause__ is None


def test_application_contract_has_no_infrastructure_or_sdk_imports() -> None:
    contract_path = (
        Path(__file__).resolve().parents[4]
        / "src"
        / "lexlocal"
        / "application"
        / "ports"
        / "chat.py"
    )
    tree = ast.parse(contract_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert all(
        not module.startswith(
            (
                "foundry_local_sdk",
                "openai",
                "sqlite3",
                "lexlocal.infrastructure",
                "lexlocal.bootstrap",
                "lexlocal.presentation",
            )
        )
        for module in imported_modules
    )
