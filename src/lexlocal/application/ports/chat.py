"""Define Application-owned contracts for one grounded QA completion."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from lexlocal.application.ports.evidence_sufficiency import (
    AggregateEvidenceCoverage,
    EvidenceRelation,
    EvidenceRelationCounts,
    EvidenceSufficiencyResult,
)
from lexlocal.application.ports.retrieval import RetrievalRegistration
from lexlocal.domain.identifiers import (
    ActivityEventId,
    ChatId,
    ChatMessageId,
    CitationId,
    DocumentId,
    DocumentVersionId,
    EvidenceItemId,
    LocalModelId,
    QaRequestId,
    RetrievalRunId,
    WorkspaceId,
)
from lexlocal.domain.processing import IndexGeneration, IndexGenerationState
from lexlocal.domain.retrieval import EvidenceRank, EvidenceSufficiency


class ChatError(Exception):
    """Base exception for sanitized CHAT completion failures."""


class InvalidChatInput(ChatError):
    """Report invalid CHAT-owned input or value construction."""


class ChatIntegrityError(ChatError):
    """Report inconsistent ownership or terminal graph relationships."""


class ChatPersistenceError(ChatError):
    """Report a sanitized CHAT persistence-boundary failure."""


class ChatCancelled(ChatError):
    """Report cooperative CHAT cancellation."""


class QaRequestState(StrEnum):
    """Represent the existing QA lifecycle states needed for strict reconstruction."""

    DRAFT = "DRAFT"
    SEARCHING = "SEARCHING"
    EVALUATING_EVIDENCE = "EVALUATING_EVIDENCE"
    GENERATING = "GENERATING"
    VALIDATING_CITATIONS = "VALIDATING_CITATIONS"
    COMPLETED = "COMPLETED"
    COMPLETED_INSUFFICIENT = "COMPLETED_INSUFFICIENT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ChatActivityResult(StrEnum):
    """Limit CHAT-owned activity registrations to existing safe result states."""

    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ChatActivityType(StrEnum):
    """Identify the fixed CHAT activity events emitted by this ticket."""

    QA_COMPLETED = "QA_COMPLETED"
    QA_FAILED = "QA_FAILED"
    QA_CANCELLED = "QA_CANCELLED"


class ChatFailureCode(StrEnum):
    """Provide fixed non-sensitive terminal failure classifications."""

    RETRIEVAL_FAILED = "RETRIEVAL_FAILED"
    EVIDENCE_EVALUATION_FAILED = "EVIDENCE_EVALUATION_FAILED"
    GENERATION_FAILED = "GENERATION_FAILED"
    OUTPUT_VALIDATION_FAILED = "OUTPUT_VALIDATION_FAILED"
    CITATION_VALIDATION_FAILED = "CITATION_VALIDATION_FAILED"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"
    UNEXPECTED_FAILURE = "UNEXPECTED_FAILURE"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class ChatIntakeRegistration:
    """Carry one immutable one-question intake attempt for atomic staging."""

    workspace_id: WorkspaceId = field(repr=False)
    chat_id: ChatId = field(repr=False)
    question_message_id: ChatMessageId = field(repr=False)
    qa_request_id: QaRequestId = field(repr=False)
    document_id: DocumentId = field(repr=False)
    document_version_id: DocumentVersionId = field(repr=False)
    active_generation: IndexGeneration = field(repr=False)
    question: str = field(repr=False)
    created_at: datetime = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.workspace_id, WorkspaceId)
            or not isinstance(self.chat_id, ChatId)
            or not isinstance(self.question_message_id, ChatMessageId)
            or not isinstance(self.qa_request_id, QaRequestId)
            or not isinstance(self.document_id, DocumentId)
            or not isinstance(self.document_version_id, DocumentVersionId)
            or not isinstance(self.active_generation, IndexGeneration)
            or not isinstance(self.question, str)
            or not self.question.strip()
        ):
            raise InvalidChatInput("CHAT intake registration is invalid")
        _require_utc(self.created_at)
        if (
            self.active_generation.state is not IndexGenerationState.ACTIVE
            or self.active_generation.workspace_id != self.workspace_id
            or self.active_generation.document_version_id != self.document_version_id
        ):
            raise ChatIntegrityError("CHAT intake ownership is invalid")

    @property
    def target(self) -> "ChatCompletionTarget":
        """Return the exact DRAFT target represented by this intake attempt."""

        return ChatCompletionTarget(
            workspace_id=self.workspace_id,
            chat_id=self.chat_id,
            qa_request_id=self.qa_request_id,
            question_message_id=self.question_message_id,
            question_sequence_number=1,
            question=self.question,
            scope_versions=(
                QaScopeVersionReference(
                    self.workspace_id,
                    self.qa_request_id,
                    self.document_id,
                    self.document_version_id,
                    self.created_at,
                ),
            ),
            state=QaRequestState.DRAFT,
        )


@dataclass(frozen=True, slots=True)
class ChatIntakeResult:
    """Return one durable QA identity without exposing it through repr."""

    qa_request_id: QaRequestId = field(repr=False)
    reused: bool

    def __post_init__(self) -> None:
        if not isinstance(self.qa_request_id, QaRequestId) or not isinstance(
            self.reused, bool
        ):
            raise InvalidChatInput("CHAT intake result is invalid")


@dataclass(frozen=True, slots=True)
class ChatResponseContractVersion:
    """Identify the exact grounded-output or Application non-answer contract."""

    value: str

    def __post_init__(self) -> None:
        if not _is_non_whitespace(self.value):
            raise InvalidChatInput("CHAT response contract version is invalid")


@dataclass(frozen=True, slots=True)
class QaScopeVersionReference:
    """Carry one row from the authoritative immutable QA version snapshot."""

    workspace_id: WorkspaceId
    qa_request_id: QaRequestId
    document_id: DocumentId
    document_version_id: DocumentVersionId
    included_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.workspace_id, WorkspaceId)
            or not isinstance(self.qa_request_id, QaRequestId)
            or not isinstance(self.document_id, DocumentId)
            or not isinstance(self.document_version_id, DocumentVersionId)
        ):
            raise ChatIntegrityError("QA scope version ownership is invalid")
        _require_utc(self.included_at)

    @property
    def canonical_key(self) -> tuple[str, str]:
        """Return the stable order used when reconstructing the scope snapshot."""

        return str(self.document_id), str(self.document_version_id)


@dataclass(frozen=True, slots=True)
class ChatCompletionTarget:
    """Expose one existing committed QA question and immutable version scope."""

    workspace_id: WorkspaceId
    chat_id: ChatId
    qa_request_id: QaRequestId
    question_message_id: ChatMessageId
    question_sequence_number: int
    question: str = field(repr=False)
    scope_versions: tuple[QaScopeVersionReference, ...]
    state: QaRequestState
    answer_message_id: ChatMessageId | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.workspace_id, WorkspaceId)
            or not isinstance(self.chat_id, ChatId)
            or not isinstance(self.qa_request_id, QaRequestId)
            or not isinstance(self.question_message_id, ChatMessageId)
        ):
            raise ChatIntegrityError("CHAT completion target ownership is invalid")
        if (
            isinstance(self.question_sequence_number, bool)
            or not isinstance(self.question_sequence_number, int)
            or self.question_sequence_number < 1
            or not isinstance(self.question, str)
            or not self.question.strip()
            or not isinstance(self.state, QaRequestState)
            or (
                self.answer_message_id is not None
                and not isinstance(self.answer_message_id, ChatMessageId)
            )
        ):
            raise InvalidChatInput("CHAT completion target is invalid")
        _require_scope(
            self.scope_versions,
            self.workspace_id,
            self.qa_request_id,
        )
        terminal = self.state in (
            QaRequestState.COMPLETED,
            QaRequestState.COMPLETED_INSUFFICIENT,
        )
        if terminal != (self.answer_message_id is not None):
            raise ChatIntegrityError("CHAT completion target state is inconsistent")


@dataclass(frozen=True, slots=True)
class ChatAssistantMessage:
    """Carry one immutable assistant message ready for final persistence."""

    id: ChatMessageId
    workspace_id: WorkspaceId
    chat_id: ChatId
    sequence_number: int
    content: str = field(repr=False)
    created_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, ChatMessageId)
            or not isinstance(self.workspace_id, WorkspaceId)
            or not isinstance(self.chat_id, ChatId)
            or isinstance(self.sequence_number, bool)
            or not isinstance(self.sequence_number, int)
            or self.sequence_number < 1
            or not isinstance(self.content, str)
            or not self.content.strip()
        ):
            raise InvalidChatInput("CHAT assistant message is invalid")
        _require_utc(self.created_at)


@dataclass(frozen=True, slots=True)
class ChatCitationRegistration:
    """Bind one answer-local ordinal to one persisted retrieval evidence item."""

    id: CitationId
    workspace_id: WorkspaceId
    evidence_item_id: EvidenceItemId
    answer_message_id: ChatMessageId
    ordinal: int
    created_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, CitationId)
            or not isinstance(self.workspace_id, WorkspaceId)
            or not isinstance(self.evidence_item_id, EvidenceItemId)
            or not isinstance(self.answer_message_id, ChatMessageId)
            or isinstance(self.ordinal, bool)
            or not isinstance(self.ordinal, int)
            or self.ordinal < 1
        ):
            raise InvalidChatInput("CHAT citation registration is invalid")
        _require_utc(self.created_at)


@dataclass(frozen=True, slots=True)
class ChatVerifierSnapshotRelation:
    """Snapshot one RAG-002 relation without creating another evidence order."""

    workspace_id: WorkspaceId
    qa_request_id: QaRequestId
    retrieval_run_id: RetrievalRunId
    evidence_item_id: EvidenceItemId
    rank: EvidenceRank
    relation: EvidenceRelation

    def __post_init__(self) -> None:
        if (
            not isinstance(self.workspace_id, WorkspaceId)
            or not isinstance(self.qa_request_id, QaRequestId)
            or not isinstance(self.retrieval_run_id, RetrievalRunId)
            or not isinstance(self.evidence_item_id, EvidenceItemId)
            or not isinstance(self.rank, EvidenceRank)
            or not isinstance(self.relation, EvidenceRelation)
        ):
            raise ChatIntegrityError("CHAT verifier snapshot relation is invalid")


@dataclass(frozen=True, slots=True)
class ChatVerifierSnapshot:
    """Carry the immutable CHAT-owned historical RAG-002 verifier snapshot."""

    workspace_id: WorkspaceId
    qa_request_id: QaRequestId
    retrieval_run_id: RetrievalRunId
    evidence_policy_version: str
    aggregate_coverage: AggregateEvidenceCoverage
    relation_counts: EvidenceRelationCounts
    repair_used: bool
    relations: tuple[ChatVerifierSnapshotRelation, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.workspace_id, WorkspaceId)
            or not isinstance(self.qa_request_id, QaRequestId)
            or not isinstance(self.retrieval_run_id, RetrievalRunId)
            or not _is_non_whitespace(self.evidence_policy_version)
            or not isinstance(self.aggregate_coverage, AggregateEvidenceCoverage)
            or not isinstance(self.relation_counts, EvidenceRelationCounts)
            or not isinstance(self.repair_used, bool)
            or not isinstance(self.relations, tuple)
            or not all(
                isinstance(item, ChatVerifierSnapshotRelation)
                for item in self.relations
            )
        ):
            raise ChatIntegrityError("CHAT verifier snapshot is invalid")
        if any(
            item.workspace_id != self.workspace_id
            or item.qa_request_id != self.qa_request_id
            or item.retrieval_run_id != self.retrieval_run_id
            for item in self.relations
        ):
            raise ChatIntegrityError("CHAT verifier snapshot ownership is invalid")
        evidence_ids = tuple(item.evidence_item_id for item in self.relations)
        ranks = tuple(item.rank.value for item in self.relations)
        counts = EvidenceRelationCounts(
            sum(item.relation is EvidenceRelation.SUPPORTS for item in self.relations),
            sum(
                item.relation is EvidenceRelation.RELATED_ONLY
                for item in self.relations
            ),
            sum(
                item.relation is EvidenceRelation.CONTRADICTS
                for item in self.relations
            ),
            sum(
                item.relation is EvidenceRelation.IRRELEVANT
                for item in self.relations
            ),
        )
        if (
            len(set(evidence_ids)) != len(evidence_ids)
            or ranks != tuple(range(1, len(self.relations) + 1))
            or counts != self.relation_counts
            or (
                not self.relations
                and (self.relation_counts.total != 0 or self.repair_used)
            )
        ):
            raise ChatIntegrityError("CHAT verifier snapshot is inconsistent")

    @classmethod
    def from_result(cls, result: EvidenceSufficiencyResult) -> "ChatVerifierSnapshot":
        """Project the implemented RAG-002 result without copying sensitive content."""

        if not isinstance(result, EvidenceSufficiencyResult):
            raise ChatIntegrityError("CHAT verifier snapshot source is invalid")
        retrieval = result.retrieval
        return cls(
            workspace_id=retrieval.workspace_id,
            qa_request_id=retrieval.qa_request_id,
            retrieval_run_id=retrieval.retrieval_run_id,
            evidence_policy_version=result.policy.evidence_policy_version,
            aggregate_coverage=result.aggregate_coverage,
            relation_counts=result.relation_counts,
            repair_used=result.repair_used,
            relations=tuple(
                ChatVerifierSnapshotRelation(
                    retrieval.workspace_id,
                    retrieval.qa_request_id,
                    retrieval.retrieval_run_id,
                    assessment.evidence_item_id,
                    assessment.rank,
                    assessment.relation,
                )
                for assessment in result.assessments
            ),
        )


@dataclass(frozen=True, slots=True)
class ChatActivityEvent:
    """Carry one CHAT-category event with no protected diagnostic payload."""

    id: ActivityEventId
    workspace_id: WorkspaceId
    qa_request_id: QaRequestId
    event_type: ChatActivityType
    result: ChatActivityResult
    created_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, ActivityEventId)
            or not isinstance(self.workspace_id, WorkspaceId)
            or not isinstance(self.qa_request_id, QaRequestId)
            or not isinstance(self.event_type, ChatActivityType)
            or not isinstance(self.result, ChatActivityResult)
        ):
            raise InvalidChatInput("CHAT activity event is invalid")
        _require_utc(self.created_at)

    @property
    def summary_key(self) -> str:
        """Return the fixed localization key without accepting caller text."""

        return {
            ChatActivityType.QA_COMPLETED: "chat.qa.completed",
            ChatActivityType.QA_FAILED: "chat.qa.failed",
            ChatActivityType.QA_CANCELLED: "chat.qa.cancelled",
        }[self.event_type]


@dataclass(frozen=True, slots=True)
class ChatCompletionRegistration:
    """Carry one fully validated completion graph for caller-owned staging."""

    target: ChatCompletionTarget
    sufficiency: EvidenceSufficiencyResult = field(repr=False)
    answer: ChatAssistantMessage = field(repr=False)
    response_contract_version: ChatResponseContractVersion
    chat_model_id: LocalModelId | None
    citations: tuple[ChatCitationRegistration, ...]
    completed_at: datetime
    activity: ChatActivityEvent

    def __post_init__(self) -> None:
        if (
            not isinstance(self.target, ChatCompletionTarget)
            or not isinstance(self.sufficiency, EvidenceSufficiencyResult)
            or not isinstance(self.answer, ChatAssistantMessage)
            or not isinstance(
                self.response_contract_version,
                ChatResponseContractVersion,
            )
            or (
                self.chat_model_id is not None
                and not isinstance(self.chat_model_id, LocalModelId)
            )
            or not isinstance(self.citations, tuple)
            or not all(
                isinstance(item, ChatCitationRegistration) for item in self.citations
            )
            or not isinstance(self.activity, ChatActivityEvent)
        ):
            raise InvalidChatInput("CHAT completion registration is invalid")
        _require_utc(self.completed_at)
        if self.target.state not in (
            QaRequestState.DRAFT,
            QaRequestState.FAILED,
            QaRequestState.CANCELLED,
        ):
            raise ChatIntegrityError("CHAT completion target state is not eligible")
        _require_completion_ownership(
            self.target,
            self.sufficiency.retrieval,
            self.answer,
            self.activity,
        )
        _require_citations(
            self.citations,
            self.target.workspace_id,
            self.answer.id,
            self.sufficiency,
        )
        _require_outcome_shape(
            self.sufficiency.state,
            self.chat_model_id,
            self.citations,
        )

    @property
    def snapshot(self) -> ChatVerifierSnapshot:
        """Return the exact historical representation of the RAG-002 handoff."""

        return ChatVerifierSnapshot.from_result(self.sufficiency)

    @property
    def terminal_state(self) -> QaRequestState:
        """Return the schema terminal state implied by the sufficiency outcome."""

        if self.sufficiency.state is EvidenceSufficiency.SUFFICIENT:
            return QaRequestState.COMPLETED
        return QaRequestState.COMPLETED_INSUFFICIENT


@dataclass(frozen=True, slots=True)
class ChatTerminalGraph:
    """Represent one strictly reconstructed immutable completed QA graph."""

    target: ChatCompletionTarget
    retrieval: RetrievalRegistration = field(repr=False)
    snapshot: ChatVerifierSnapshot
    answer: ChatAssistantMessage = field(repr=False)
    evidence_state: EvidenceSufficiency
    response_contract_version: ChatResponseContractVersion
    chat_model_id: LocalModelId | None
    citations: tuple[ChatCitationRegistration, ...]
    completed_at: datetime
    activity: ChatActivityEvent

    def __post_init__(self) -> None:
        if (
            not isinstance(self.target, ChatCompletionTarget)
            or not isinstance(self.retrieval, RetrievalRegistration)
            or not isinstance(self.snapshot, ChatVerifierSnapshot)
            or not isinstance(self.answer, ChatAssistantMessage)
            or not isinstance(self.evidence_state, EvidenceSufficiency)
            or not isinstance(
                self.response_contract_version,
                ChatResponseContractVersion,
            )
            or (
                self.chat_model_id is not None
                and not isinstance(self.chat_model_id, LocalModelId)
            )
            or not isinstance(self.citations, tuple)
            or not all(
                isinstance(item, ChatCitationRegistration) for item in self.citations
            )
            or not isinstance(self.activity, ChatActivityEvent)
        ):
            raise ChatIntegrityError("CHAT terminal graph is invalid")
        _require_utc(self.completed_at)
        expected_state = (
            QaRequestState.COMPLETED
            if self.evidence_state is EvidenceSufficiency.SUFFICIENT
            else QaRequestState.COMPLETED_INSUFFICIENT
        )
        if (
            self.target.state is not expected_state
            or self.target.answer_message_id != self.answer.id
        ):
            raise ChatIntegrityError("CHAT terminal state is inconsistent")
        _require_completion_ownership(
            self.target,
            self.retrieval,
            self.answer,
            self.activity,
        )
        _require_snapshot_binding(self.snapshot, self.retrieval)
        _require_historical_citations(
            self.citations,
            self.target.workspace_id,
            self.answer.id,
            self.retrieval,
            self.snapshot,
            self.evidence_state,
        )
        _require_outcome_shape(
            self.evidence_state,
            self.chat_model_id,
            self.citations,
        )


@dataclass(frozen=True, slots=True)
class ChatCompletionResult:
    """Return one complete terminal graph and whether it was reused."""

    graph: ChatTerminalGraph = field(repr=False)
    reused: bool

    def __post_init__(self) -> None:
        if not isinstance(self.graph, ChatTerminalGraph) or not isinstance(
            self.reused, bool
        ):
            raise ChatIntegrityError("CHAT completion result is invalid")


@dataclass(frozen=True, slots=True)
class ChatFailureUpdate:
    """Carry one sanitized FAILED or CANCELLED update for a separate short UoW."""

    target: ChatCompletionTarget
    state: QaRequestState
    error_code: ChatFailureCode
    updated_at: datetime
    activity: ChatActivityEvent

    def __post_init__(self) -> None:
        if (
            not isinstance(self.target, ChatCompletionTarget)
            or self.state not in (QaRequestState.FAILED, QaRequestState.CANCELLED)
            or not isinstance(self.error_code, ChatFailureCode)
            or not isinstance(self.activity, ChatActivityEvent)
        ):
            raise InvalidChatInput("CHAT failure update is invalid")
        _require_utc(self.updated_at)
        expected_activity = (
            ChatActivityResult.FAILED
            if self.state is QaRequestState.FAILED
            else ChatActivityResult.CANCELLED
        )
        expected_event = (
            ChatActivityType.QA_FAILED
            if self.state is QaRequestState.FAILED
            else ChatActivityType.QA_CANCELLED
        )
        if (
            self.target.answer_message_id is not None
            or self.activity.workspace_id != self.target.workspace_id
            or self.activity.qa_request_id != self.target.qa_request_id
            or self.activity.result is not expected_activity
            or self.activity.event_type is not expected_event
            or (
                self.state is QaRequestState.CANCELLED
                and self.error_code is not ChatFailureCode.CANCELLED
            )
            or (
                self.state is QaRequestState.FAILED
                and self.error_code is ChatFailureCode.CANCELLED
            )
        ):
            raise ChatIntegrityError("CHAT failure update ownership is invalid")


class ChatRepository(Protocol):
    """Load and stage one QA completion without owning transaction finalization."""

    def get_target(
        self,
        workspace_id: WorkspaceId,
        qa_request_id: QaRequestId,
    ) -> ChatCompletionTarget | None:
        """Load the existing same-workspace QA question and immutable scope."""

        ...

    def get_completed(
        self,
        workspace_id: WorkspaceId,
        qa_request_id: QaRequestId,
    ) -> ChatTerminalGraph | None:
        """Reconstruct the sole complete compatible terminal graph, when present."""

        ...

    def add_intake(self, registration: ChatIntakeRegistration) -> bool:
        """Stage one intake or return True for its exact compatible reconstruction."""

        ...

    def add(self, registration: ChatCompletionRegistration) -> None:
        """Stage one complete outcome without committing or rolling back."""

        ...

    def record_failure(self, update: ChatFailureUpdate) -> None:
        """Stage one sanitized FAILED or CANCELLED state update."""

        ...


class ChatCancellationCheck(Protocol):
    """Expose cooperative cancellation to the CHAT Application orchestration."""

    def raise_if_cancelled(self) -> None:
        """Raise ChatCancelled when cancellation has been requested."""

        ...


def _require_completion_ownership(
    target: ChatCompletionTarget,
    retrieval: RetrievalRegistration,
    answer: ChatAssistantMessage,
    activity: ChatActivityEvent,
) -> None:
    if (
        retrieval.workspace_id != target.workspace_id
        or retrieval.qa_request_id != target.qa_request_id
        or retrieval.scope.request.query != target.question
        or answer.workspace_id != target.workspace_id
        or answer.chat_id != target.chat_id
        or answer.sequence_number != target.question_sequence_number + 1
        or activity.workspace_id != target.workspace_id
        or activity.qa_request_id != target.qa_request_id
        or activity.event_type is not ChatActivityType.QA_COMPLETED
        or activity.result
        not in (ChatActivityResult.SUCCESS, ChatActivityResult.WARNING)
    ):
        raise ChatIntegrityError("CHAT completion ownership is inconsistent")
    versions = {
        item.document_version_id: item.document_id for item in target.scope_versions
    }
    resolved_versions = {
        generation.document_version_id: generation.document_id
        for generation in retrieval.scope.generations
    }
    if any(
        generation.document_version_id not in versions
        or versions[generation.document_version_id] != generation.document_id
        for generation in retrieval.scope.generations
    ) or (
        retrieval.scope.request.document_ids is None
        and resolved_versions != versions
    ):
        raise ChatIntegrityError("CHAT completion scope is inconsistent")


def _require_citations(
    citations: tuple[ChatCitationRegistration, ...],
    workspace_id: WorkspaceId,
    answer_message_id: ChatMessageId,
    sufficiency: EvidenceSufficiencyResult,
) -> None:
    _require_citation_shape(citations, workspace_id, answer_message_id)
    selected = {item.evidence.id for item in sufficiency.retrieval.evidence}
    cited = tuple(item.evidence_item_id for item in citations)
    if any(item not in selected for item in cited):
        raise ChatIntegrityError("CHAT citation evidence ownership is invalid")
    if sufficiency.state is EvidenceSufficiency.RELATED_BUT_INSUFFICIENT:
        expected = tuple(
            item.evidence.id for item in sufficiency.related_evidence
        )
        if cited != expected:
            raise ChatIntegrityError("CHAT related evidence citations are inconsistent")


def _require_historical_citations(
    citations: tuple[ChatCitationRegistration, ...],
    workspace_id: WorkspaceId,
    answer_message_id: ChatMessageId,
    retrieval: RetrievalRegistration,
    snapshot: ChatVerifierSnapshot,
    state: EvidenceSufficiency,
) -> None:
    _require_citation_shape(citations, workspace_id, answer_message_id)
    selected = {item.evidence.id for item in retrieval.evidence}
    cited = tuple(item.evidence_item_id for item in citations)
    if any(item not in selected for item in cited):
        raise ChatIntegrityError("CHAT citation evidence ownership is invalid")
    if state is EvidenceSufficiency.RELATED_BUT_INSUFFICIENT:
        expected = tuple(
            item.evidence_item_id
            for item in snapshot.relations
            if item.relation is not EvidenceRelation.IRRELEVANT
        )
        if cited != expected:
            raise ChatIntegrityError("CHAT related evidence citations are inconsistent")


def _require_citation_shape(
    citations: tuple[ChatCitationRegistration, ...],
    workspace_id: WorkspaceId,
    answer_message_id: ChatMessageId,
) -> None:
    ids = tuple(item.id for item in citations)
    evidence_ids = tuple(item.evidence_item_id for item in citations)
    if (
        tuple(item.ordinal for item in citations)
        != tuple(range(1, len(citations) + 1))
        or len(set(ids)) != len(ids)
        or len(set(evidence_ids)) != len(evidence_ids)
        or any(
            item.workspace_id != workspace_id
            or item.answer_message_id != answer_message_id
            for item in citations
        )
    ):
        raise ChatIntegrityError("CHAT citation set is inconsistent")


def _require_outcome_shape(
    state: EvidenceSufficiency,
    chat_model_id: LocalModelId | None,
    citations: tuple[ChatCitationRegistration, ...],
) -> None:
    if state is EvidenceSufficiency.SUFFICIENT:
        if not isinstance(chat_model_id, LocalModelId) or not citations:
            raise ChatIntegrityError("grounded CHAT completion is inconsistent")
    elif state is EvidenceSufficiency.RELATED_BUT_INSUFFICIENT:
        if chat_model_id is not None or not citations:
            raise ChatIntegrityError("related CHAT completion is inconsistent")
    elif state is EvidenceSufficiency.INSUFFICIENT:
        if chat_model_id is not None or citations:
            raise ChatIntegrityError("insufficient CHAT completion is inconsistent")
    else:
        raise ChatIntegrityError("CHAT evidence state is invalid")


def _require_snapshot_binding(
    snapshot: ChatVerifierSnapshot,
    retrieval: RetrievalRegistration,
) -> None:
    expected = tuple(
        (item.evidence.id, item.evidence.rank) for item in retrieval.evidence
    )
    actual = tuple(
        (item.evidence_item_id, item.rank) for item in snapshot.relations
    )
    if (
        snapshot.workspace_id != retrieval.workspace_id
        or snapshot.qa_request_id != retrieval.qa_request_id
        or snapshot.retrieval_run_id != retrieval.retrieval_run_id
        or actual != expected
    ):
        raise ChatIntegrityError("CHAT verifier snapshot binding is inconsistent")


def _require_scope(
    scope: object,
    workspace_id: WorkspaceId,
    qa_request_id: QaRequestId,
) -> None:
    if (
        not isinstance(scope, tuple)
        or not scope
        or not all(isinstance(item, QaScopeVersionReference) for item in scope)
        or any(
            item.workspace_id != workspace_id or item.qa_request_id != qa_request_id
            for item in scope
        )
    ):
        raise ChatIntegrityError("CHAT QA scope is invalid")
    document_ids = tuple(item.document_id for item in scope)
    version_ids = tuple(item.document_version_id for item in scope)
    if (
        len(set(document_ids)) != len(document_ids)
        or len(set(version_ids)) != len(version_ids)
        or tuple(item.canonical_key for item in scope)
        != tuple(sorted(item.canonical_key for item in scope))
    ):
        raise ChatIntegrityError("CHAT QA scope is inconsistent")


def _require_utc(value: object) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != timedelta(0)
    ):
        raise InvalidChatInput("CHAT timestamp is invalid")


def _is_non_whitespace(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
