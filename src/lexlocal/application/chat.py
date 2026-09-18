"""Prepare, validate, and atomically complete one existing QA request."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

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
    ChatIntegrityError,
    ChatPersistenceError,
    ChatResponseContractVersion,
    ChatTerminalGraph,
    InvalidChatInput,
    QaRequestState,
)
from lexlocal.application.ports.evidence_sufficiency import (
    EvidenceSufficiencyCancelled,
    EvidenceSufficiencyError,
    EvidenceSufficiencyResult,
)
from lexlocal.application.ports.local_models import (
    ChatInferenceProvider,
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
)
from lexlocal.application.ports.retrieval import (
    RetrievalConfiguration,
    RetrievalError,
    RetrievalEvidenceRegistration,
    RetrievalRegistration,
)
from lexlocal.application.ports.unit_of_work import UnitOfWork
from lexlocal.application.prompts.chat_v1 import (
    GROUNDED_CHAT_CONTRACT_VERSION,
    INSUFFICIENT_NON_ANSWER,
    INSUFFICIENT_NON_ANSWER_CONTRACT_VERSION,
    RELATED_NON_ANSWER,
    RELATED_NON_ANSWER_CONTRACT_VERSION,
    render_grounded_prompt,
)
from lexlocal.application.retrieval import PrepareRetrieval, StageRetrieval
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.domain.identifiers import (
    ActivityEventId,
    ChatMessageId,
    CitationId,
    QaRequestId,
    WorkspaceId,
)
from lexlocal.domain.retrieval import EvidenceSufficiency

_EVIDENCE_LABEL = re.compile(r"E[1-9][0-9]*")


class _InvalidStructuredOutput(Exception):
    """Mark untrusted output invalid without retaining its value."""


class _ChatOutputFailure(ChatError):
    """Classify exhausted structured-output validation without private content."""


@dataclass(frozen=True, slots=True)
class ChatPrompt:
    """Carry one private versioned prompt ready for the existing provider boundary."""

    contract_version: ChatResponseContractVersion
    text: str = field(repr=False)
    repair: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.contract_version, ChatResponseContractVersion)
            or not isinstance(self.text, str)
            or not self.text
            or not isinstance(self.repair, bool)
        ):
            raise InvalidChatInput("CHAT prompt is invalid")


@dataclass(frozen=True, slots=True)
class PreparedChatContent:
    """Carry validated private content and Application-derived citation identities."""

    content: str = field(repr=False)
    response_contract_version: ChatResponseContractVersion
    citations: tuple[ChatCitationRegistration, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.content, str)
            or not self.content.strip()
            or not isinstance(
                self.response_contract_version,
                ChatResponseContractVersion,
            )
            or not isinstance(self.citations, tuple)
            or not all(
                isinstance(item, ChatCitationRegistration) for item in self.citations
            )
        ):
            raise InvalidChatInput("prepared CHAT content is invalid")


class PrepareChatContent:
    """Build prompts and validate content without invoking models or persistence."""

    def build_grounded_prompt(
        self,
        result: EvidenceSufficiencyResult,
    ) -> ChatPrompt:
        """Build the exact context-only sufficient-evidence prompt."""

        self._require_state(result, EvidenceSufficiency.SUFFICIENT)
        return self._prompt(result, repair=False)

    def build_repair_prompt(
        self,
        result: EvidenceSufficiencyResult,
    ) -> ChatPrompt:
        """Build the sole constrained repair input over the unchanged evidence."""

        self._require_state(result, EvidenceSufficiency.SUFFICIENT)
        return self._prompt(result, repair=True)

    def parse_grounded_output(
        self,
        output: object,
        result: EvidenceSufficiencyResult,
        *,
        answer_message_id: ChatMessageId,
        citation_ids: tuple[CitationId, ...],
        created_at: datetime,
    ) -> PreparedChatContent:
        """Validate strict output and resolve labels only through exact RAG evidence."""

        self._require_state(result, EvidenceSufficiency.SUFFICIENT)
        try:
            answer, labels = self._parse(output)
            citations = self._citations_for_labels(
                labels,
                result,
                answer_message_id,
                citation_ids,
                created_at,
            )
            return PreparedChatContent(
                answer,
                ChatResponseContractVersion(GROUNDED_CHAT_CONTRACT_VERSION),
                citations,
            )
        except _InvalidStructuredOutput:
            raise InvalidChatInput("CHAT model output is invalid") from None
        except (InvalidChatInput, ChatIntegrityError):
            raise
        except Exception:
            raise InvalidChatInput("CHAT model output is invalid") from None

    def parse_grounded_output_with_factory(
        self,
        output: object,
        result: EvidenceSufficiencyResult,
        *,
        answer_message_id: ChatMessageId,
        citation_id_factory: Callable[[], CitationId],
        created_at: datetime,
    ) -> PreparedChatContent:
        """Validate output before allocating exactly its required citation identities."""

        self._require_state(result, EvidenceSufficiency.SUFFICIENT)
        try:
            answer, labels = self._parse(output)
            citation_ids = tuple(citation_id_factory() for _ in labels)
            citations = self._citations_for_labels(
                labels,
                result,
                answer_message_id,
                citation_ids,
                created_at,
            )
            return PreparedChatContent(
                answer,
                ChatResponseContractVersion(GROUNDED_CHAT_CONTRACT_VERSION),
                citations,
            )
        except _InvalidStructuredOutput:
            raise InvalidChatInput("CHAT model output is invalid") from None
        except (InvalidChatInput, ChatIntegrityError):
            raise
        except Exception:
            raise ChatIntegrityError("CHAT citation identities are invalid") from None

    def render_non_answer(
        self,
        result: EvidenceSufficiencyResult,
        *,
        answer_message_id: ChatMessageId,
        citation_ids: tuple[CitationId, ...],
        created_at: datetime,
    ) -> PreparedChatContent:
        """Render one deterministic non-model outcome from the RAG-002 decision."""

        if not isinstance(result, EvidenceSufficiencyResult):
            raise ChatIntegrityError("CHAT evidence handoff is invalid")
        if result.state is EvidenceSufficiency.RELATED_BUT_INSUFFICIENT:
            citations = self._citations_for_evidence(
                result,
                answer_message_id,
                citation_ids,
                created_at,
            )
            return PreparedChatContent(
                RELATED_NON_ANSWER,
                ChatResponseContractVersion(
                    RELATED_NON_ANSWER_CONTRACT_VERSION
                ),
                citations,
            )
        if result.state is EvidenceSufficiency.INSUFFICIENT:
            if citation_ids:
                raise ChatIntegrityError("CHAT insufficient citations are invalid")
            return PreparedChatContent(
                INSUFFICIENT_NON_ANSWER,
                ChatResponseContractVersion(
                    INSUFFICIENT_NON_ANSWER_CONTRACT_VERSION
                ),
                (),
            )
        raise ChatIntegrityError("CHAT non-answer state is invalid")

    @staticmethod
    def _prompt(result: EvidenceSufficiencyResult, *, repair: bool) -> ChatPrompt:
        retrieval = result.retrieval
        evidence = tuple(
            (f"E{item.evidence.rank.value}", item.excerpt)
            for item in retrieval.evidence
        )
        if not evidence:
            raise ChatIntegrityError("CHAT grounded evidence is invalid")
        return ChatPrompt(
            ChatResponseContractVersion(GROUNDED_CHAT_CONTRACT_VERSION),
            render_grounded_prompt(
                retrieval.scope.request.query,
                evidence,
                repair=repair,
            ),
            repair,
        )

    @staticmethod
    def _parse(output: object) -> tuple[str, tuple[str, ...]]:
        if type(output) is not str:
            raise _InvalidStructuredOutput
        try:
            decoded = json.loads(output, object_pairs_hook=_unique_object)
        except Exception:
            raise _InvalidStructuredOutput from None
        if not isinstance(decoded, dict) or set(decoded) != {"answer", "citations"}:
            raise _InvalidStructuredOutput
        answer = decoded["answer"]
        citation_values = decoded["citations"]
        if (
            type(answer) is not str
            or not answer.strip()
            or not isinstance(citation_values, list)
            or not citation_values
            or any(type(item) is not str for item in citation_values)
        ):
            raise _InvalidStructuredOutput
        labels = tuple(citation_values)
        if (
            any(_EVIDENCE_LABEL.fullmatch(label) is None for label in labels)
            or len(set(labels)) != len(labels)
        ):
            raise _InvalidStructuredOutput
        return answer, labels

    @staticmethod
    def _citations_for_labels(
        labels: tuple[str, ...],
        result: EvidenceSufficiencyResult,
        answer_message_id: ChatMessageId,
        citation_ids: tuple[CitationId, ...],
        created_at: datetime,
    ) -> tuple[ChatCitationRegistration, ...]:
        evidence = {
            f"E{item.evidence.rank.value}": item for item in result.retrieval.evidence
        }
        if any(label not in evidence for label in labels):
            raise _InvalidStructuredOutput
        return PrepareChatContent._build_citations(
            tuple(evidence[label] for label in labels),
            result,
            answer_message_id,
            citation_ids,
            created_at,
        )

    @staticmethod
    def _citations_for_evidence(
        result: EvidenceSufficiencyResult,
        answer_message_id: ChatMessageId,
        citation_ids: tuple[CitationId, ...],
        created_at: datetime,
    ) -> tuple[ChatCitationRegistration, ...]:
        return PrepareChatContent._build_citations(
            result.related_evidence,
            result,
            answer_message_id,
            citation_ids,
            created_at,
        )

    @staticmethod
    def _build_citations(
        evidence: tuple[RetrievalEvidenceRegistration, ...],
        result: EvidenceSufficiencyResult,
        answer_message_id: ChatMessageId,
        citation_ids: tuple[CitationId, ...],
        created_at: datetime,
    ) -> tuple[ChatCitationRegistration, ...]:
        if (
            not isinstance(answer_message_id, ChatMessageId)
            or not isinstance(citation_ids, tuple)
            or not all(isinstance(item, CitationId) for item in citation_ids)
            or len(set(citation_ids)) != len(citation_ids)
            or len(citation_ids) != len(evidence)
            or not all(
                isinstance(item, RetrievalEvidenceRegistration) for item in evidence
            )
        ):
            raise ChatIntegrityError("CHAT citation identities are invalid")
        return tuple(
            ChatCitationRegistration(
                citation_id,
                result.retrieval.workspace_id,
                item.evidence.id,
                answer_message_id,
                ordinal,
                created_at,
            )
            for ordinal, (citation_id, item) in enumerate(
                zip(citation_ids, evidence, strict=True),
                start=1,
            )
        )

    @staticmethod
    def _require_state(
        result: EvidenceSufficiencyResult,
        state: EvidenceSufficiency,
    ) -> None:
        if not isinstance(result, EvidenceSufficiencyResult) or result.state is not state:
            raise ChatIntegrityError("CHAT evidence handoff is invalid")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidStructuredOutput
        result[key] = value
    return result


class CompleteChat:
    """Complete one existing QA request without owning upstream policy or data."""

    def __init__(
        self,
        active_scope: ActiveWorkspaceScope,
        unit_of_work_factory: Callable[[], UnitOfWork],
        prepare_retrieval: PrepareRetrieval,
        stage_retrieval: StageRetrieval,
        evaluate_sufficiency: Callable[
            [RetrievalRegistration], EvidenceSufficiencyResult
        ],
        provider: ChatInferenceProvider,
        expected_chat_status: LocalModelStatus,
        evidence_policy_version: str,
        retrieval_configuration: RetrievalConfiguration,
        cancellation: ChatCancellationCheck,
        answer_message_id_factory: Callable[[], ChatMessageId],
        citation_id_factory: Callable[[], CitationId],
        activity_event_id_factory: Callable[[], ActivityEventId],
        clock: Callable[[], datetime],
        content: PrepareChatContent | None = None,
    ) -> None:
        if (
            not _is_ready_chat_status(expected_chat_status)
            or not isinstance(evidence_policy_version, str)
            or not evidence_policy_version.strip()
            or not isinstance(retrieval_configuration, RetrievalConfiguration)
        ):
            raise InvalidChatInput("CHAT completion configuration is invalid")
        self._active_scope = active_scope
        self._unit_of_work_factory = unit_of_work_factory
        self._prepare_retrieval = prepare_retrieval
        self._stage_retrieval = stage_retrieval
        self._evaluate_sufficiency = evaluate_sufficiency
        self._provider = provider
        self._expected_chat_status = expected_chat_status
        self._evidence_policy_version = evidence_policy_version
        self._retrieval_configuration = retrieval_configuration
        self._cancellation = cancellation
        self._answer_message_id_factory = answer_message_id_factory
        self._citation_id_factory = citation_id_factory
        self._activity_event_id_factory = activity_event_id_factory
        self._clock = clock
        self._content = PrepareChatContent() if content is None else content

    def __call__(self, qa_request_id: QaRequestId) -> ChatCompletionResult:
        """Return a compatible completion or create exactly one atomic terminal graph."""

        workspace_id = self._workspace_id()
        target: ChatCompletionTarget | None = None
        may_record_failure = False
        failure_code = ChatFailureCode.UNEXPECTED_FAILURE
        try:
            target, completed = self._load_state(workspace_id, qa_request_id)
            if completed is not None:
                if target is None or completed.target != target:
                    raise ChatIntegrityError("CHAT terminal target is inconsistent")
                self._require_reusable(completed)
                return ChatCompletionResult(completed, reused=True)
            if target is None:
                raise ChatIntegrityError("CHAT completion target is unavailable")
            self._require_eligible(target)
            may_record_failure = True

            failure_code = ChatFailureCode.CANCELLED
            self._checkpoint()
            failure_code = ChatFailureCode.RETRIEVAL_FAILED
            retrieval = self._prepare(target)
            failure_code = ChatFailureCode.EVIDENCE_EVALUATION_FAILED
            sufficiency = self._evaluate(retrieval)

            failure_code = ChatFailureCode.GENERATION_FAILED
            registration = self._registration(target, sufficiency)
            failure_code = ChatFailureCode.PERSISTENCE_FAILED
            return self._persist(target, registration)
        except Exception as error:
            if isinstance(error, _ChatOutputFailure):
                failure_code = ChatFailureCode.OUTPUT_VALIDATION_FAILED
            safe_error = self._safe_error(error, failure_code)
            if target is not None and may_record_failure:
                self._record_failure(target, safe_error, failure_code)
            raise safe_error from None

    def _workspace_id(self) -> WorkspaceId:
        try:
            workspace_id = self._active_scope.require_workspace_id()
        except Exception:
            raise ChatPersistenceError("active workspace is unavailable") from None
        if not isinstance(workspace_id, WorkspaceId):
            raise ChatPersistenceError("active workspace is unavailable")
        return workspace_id

    def _load_state(
        self,
        workspace_id: WorkspaceId,
        qa_request_id: QaRequestId,
    ) -> tuple[ChatCompletionTarget | None, ChatTerminalGraph | None]:
        if not isinstance(qa_request_id, QaRequestId):
            raise InvalidChatInput("CHAT QA request is invalid")
        try:
            with self._unit_of_work_factory() as unit_of_work:
                target = unit_of_work.chat.get_target(workspace_id, qa_request_id)
                completed = unit_of_work.chat.get_completed(workspace_id, qa_request_id)
            return target, completed
        except ChatError:
            raise
        except Exception:
            raise ChatPersistenceError("CHAT target loading failed") from None

    @staticmethod
    def _require_eligible(target: ChatCompletionTarget) -> None:
        if target.state not in (
            QaRequestState.DRAFT,
            QaRequestState.FAILED,
            QaRequestState.CANCELLED,
        ):
            raise ChatIntegrityError("CHAT completion target is not eligible")

    def _prepare(self, target: ChatCompletionTarget) -> RetrievalRegistration:
        try:
            retrieval = self._prepare_retrieval(
                target.qa_request_id,
                target.question,
                self._retrieval_configuration,
            )
        except RetrievalError:
            raise ChatError("CHAT retrieval failed") from None
        except Exception:
            raise ChatError("CHAT retrieval failed") from None
        if (
            not isinstance(retrieval, RetrievalRegistration)
            or retrieval.workspace_id != target.workspace_id
            or retrieval.qa_request_id != target.qa_request_id
            or retrieval.scope.request.query != target.question
        ):
            raise ChatIntegrityError("CHAT retrieval handoff is invalid")
        return retrieval

    def _evaluate(
        self,
        retrieval: RetrievalRegistration,
    ) -> EvidenceSufficiencyResult:
        try:
            result = self._evaluate_sufficiency(retrieval)
        except EvidenceSufficiencyCancelled:
            raise ChatCancelled("CHAT completion was cancelled") from None
        except EvidenceSufficiencyError:
            raise ChatError("CHAT evidence evaluation failed") from None
        except Exception:
            raise ChatError("CHAT evidence evaluation failed") from None
        if (
            not isinstance(result, EvidenceSufficiencyResult)
            or result.retrieval != retrieval
            or result.policy.evidence_policy_version
            != self._evidence_policy_version
        ):
            raise ChatIntegrityError("CHAT evidence handoff is invalid")
        return result

    def _registration(
        self,
        target: ChatCompletionTarget,
        sufficiency: EvidenceSufficiencyResult,
    ) -> ChatCompletionRegistration:
        created_at = self._utc_now()
        answer_message_id = self._answer_id()
        if sufficiency.state is EvidenceSufficiency.SUFFICIENT:
            prepared = self._grounded_content(
                sufficiency,
                answer_message_id,
                created_at,
            )
            chat_model_id = self._expected_chat_status.model.id
        else:
            citation_count = (
                len(sufficiency.related_evidence)
                if sufficiency.state
                is EvidenceSufficiency.RELATED_BUT_INSUFFICIENT
                else 0
            )
            prepared = self._content.render_non_answer(
                sufficiency,
                answer_message_id=answer_message_id,
                citation_ids=self._citation_ids(citation_count),
                created_at=created_at,
            )
            chat_model_id = None
        activity = ChatActivityEvent(
            self._activity_id(),
            target.workspace_id,
            target.qa_request_id,
            ChatActivityType.QA_COMPLETED,
            (
                ChatActivityResult.SUCCESS
                if sufficiency.state is EvidenceSufficiency.SUFFICIENT
                else ChatActivityResult.WARNING
            ),
            created_at,
        )
        return ChatCompletionRegistration(
            target,
            sufficiency,
            ChatAssistantMessage(
                answer_message_id,
                target.workspace_id,
                target.chat_id,
                target.question_sequence_number + 1,
                prepared.content,
                created_at,
            ),
            prepared.response_contract_version,
            chat_model_id,
            prepared.citations,
            created_at,
            activity,
        )

    def _grounded_content(
        self,
        sufficiency: EvidenceSufficiencyResult,
        answer_message_id: ChatMessageId,
        created_at: datetime,
    ) -> PreparedChatContent:
        prompt = self._content.build_grounded_prompt(sufficiency)
        output = self._infer(prompt)
        try:
            return self._content.parse_grounded_output_with_factory(
                output,
                sufficiency,
                answer_message_id=answer_message_id,
                citation_id_factory=self._citation_id_factory,
                created_at=created_at,
            )
        except InvalidChatInput:
            repair_prompt = self._content.build_repair_prompt(sufficiency)
            repaired = self._infer(repair_prompt)
            try:
                return self._content.parse_grounded_output_with_factory(
                    repaired,
                    sufficiency,
                    answer_message_id=answer_message_id,
                    citation_id_factory=self._citation_id_factory,
                    created_at=created_at,
                )
            except InvalidChatInput:
                raise _ChatOutputFailure("CHAT output validation failed") from None

    def _infer(self, prompt: ChatPrompt) -> str:
        self._checkpoint()
        self._require_provider_binding()
        try:
            output = self._provider.generate(prompt.text)
        except Exception:
            raise ChatError("CHAT generation failed") from None
        self._checkpoint()
        self._require_provider_binding()
        return output

    def _require_provider_binding(self) -> None:
        try:
            status = self._provider.status
        except Exception:
            raise ChatError("CHAT generation failed") from None
        if status != self._expected_chat_status:
            raise ChatIntegrityError("CHAT model binding is invalid")

    def _persist(
        self,
        target: ChatCompletionTarget,
        registration: ChatCompletionRegistration,
    ) -> ChatCompletionResult:
        self._checkpoint()
        try:
            with self._unit_of_work_factory() as unit_of_work:
                current = unit_of_work.chat.get_target(
                    target.workspace_id,
                    target.qa_request_id,
                )
                if current != target:
                    raise ChatPersistenceError("CHAT completion target is stale")
                if unit_of_work.chat.get_completed(
                    target.workspace_id,
                    target.qa_request_id,
                ) is not None:
                    raise ChatPersistenceError("CHAT completion already exists")
                staged = self._stage_retrieval(
                    registration.sufficiency.retrieval,
                    unit_of_work.retrieval,
                )
                if staged.registration != registration.sufficiency.retrieval:
                    raise ChatPersistenceError("CHAT retrieval staging is invalid")
                unit_of_work.chat.add(registration)
                self._checkpoint()
                unit_of_work.commit()
        except ChatCancelled:
            raise
        except ChatError:
            raise
        except RetrievalError:
            raise ChatPersistenceError("CHAT final persistence failed") from None
        except Exception:
            raise ChatPersistenceError("CHAT final persistence failed") from None
        return ChatCompletionResult(self._terminal_graph(registration), reused=False)

    @staticmethod
    def _terminal_graph(
        registration: ChatCompletionRegistration,
    ) -> ChatTerminalGraph:
        target = registration.target
        terminal_target = ChatCompletionTarget(
            target.workspace_id,
            target.chat_id,
            target.qa_request_id,
            target.question_message_id,
            target.question_sequence_number,
            target.question,
            target.scope_versions,
            registration.terminal_state,
            registration.answer.id,
        )
        return ChatTerminalGraph(
            terminal_target,
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

    def _require_reusable(self, graph: ChatTerminalGraph) -> None:
        state = graph.evidence_state
        expected_contract = {
            EvidenceSufficiency.SUFFICIENT: GROUNDED_CHAT_CONTRACT_VERSION,
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT:
                RELATED_NON_ANSWER_CONTRACT_VERSION,
            EvidenceSufficiency.INSUFFICIENT: INSUFFICIENT_NON_ANSWER_CONTRACT_VERSION,
        }[state]
        expected_content = {
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT: RELATED_NON_ANSWER,
            EvidenceSufficiency.INSUFFICIENT: INSUFFICIENT_NON_ANSWER,
        }
        if (
            graph.snapshot.evidence_policy_version
            != self._evidence_policy_version
            or graph.response_contract_version.value != expected_contract
            or graph.retrieval.configuration != self._retrieval_configuration
            or graph.retrieval.scope.request.document_ids is not None
            or (
                state is EvidenceSufficiency.SUFFICIENT
                and graph.chat_model_id != self._expected_chat_status.model.id
            )
            or (
                state is not EvidenceSufficiency.SUFFICIENT
                and (
                    graph.chat_model_id is not None
                    or graph.answer.content != expected_content[state]
                )
            )
        ):
            raise ChatIntegrityError("CHAT terminal result is incompatible")

    def _record_failure(
        self,
        target: ChatCompletionTarget,
        error: ChatError,
        failure_code: ChatFailureCode,
    ) -> None:
        cancelled = isinstance(error, ChatCancelled)
        state = QaRequestState.CANCELLED if cancelled else QaRequestState.FAILED
        code = ChatFailureCode.CANCELLED if cancelled else failure_code
        try:
            updated_at = self._utc_now()
            activity = ChatActivityEvent(
                self._activity_id(),
                target.workspace_id,
                target.qa_request_id,
                ChatActivityType.QA_CANCELLED if cancelled else ChatActivityType.QA_FAILED,
                ChatActivityResult.CANCELLED if cancelled else ChatActivityResult.FAILED,
                updated_at,
            )
            with self._unit_of_work_factory() as unit_of_work:
                current = unit_of_work.chat.get_target(
                    target.workspace_id,
                    target.qa_request_id,
                )
                if current is None:
                    return
                unit_of_work.chat.record_failure(
                    ChatFailureUpdate(current, state, code, updated_at, activity)
                )
                unit_of_work.commit()
        except Exception:
            return

    def _checkpoint(self) -> None:
        try:
            self._cancellation.raise_if_cancelled()
        except ChatCancelled:
            raise ChatCancelled("CHAT completion was cancelled") from None
        except Exception:
            raise ChatPersistenceError("CHAT cancellation check failed") from None

    def _utc_now(self) -> datetime:
        try:
            value = self._clock()
        except Exception:
            raise ChatPersistenceError("CHAT clock failed") from None
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() != timedelta(0)
            or value.microsecond % 1000 != 0
        ):
            raise ChatPersistenceError("CHAT clock returned invalid data")
        return value

    def _answer_id(self) -> ChatMessageId:
        try:
            value = self._answer_message_id_factory()
        except Exception:
            raise ChatPersistenceError("CHAT identifier generation failed") from None
        if not isinstance(value, ChatMessageId):
            raise ChatPersistenceError("CHAT identifier generation failed")
        return value

    def _citation_ids(self, count: int) -> tuple[CitationId, ...]:
        try:
            values = tuple(self._citation_id_factory() for _ in range(count))
        except Exception:
            raise ChatPersistenceError("CHAT identifier generation failed") from None
        if (
            not all(isinstance(item, CitationId) for item in values)
            or len(set(values)) != len(values)
        ):
            raise ChatPersistenceError("CHAT identifier generation failed")
        return values

    def _activity_id(self) -> ActivityEventId:
        try:
            value = self._activity_event_id_factory()
        except Exception:
            raise ChatPersistenceError("CHAT identifier generation failed") from None
        if not isinstance(value, ActivityEventId):
            raise ChatPersistenceError("CHAT identifier generation failed")
        return value

    @staticmethod
    def _safe_error(error: Exception, failure_code: ChatFailureCode) -> ChatError:
        if isinstance(error, ChatCancelled):
            return error
        if isinstance(error, ChatError):
            return error
        return ChatError(
            {
                ChatFailureCode.RETRIEVAL_FAILED: "CHAT retrieval failed",
                ChatFailureCode.EVIDENCE_EVALUATION_FAILED:
                    "CHAT evidence evaluation failed",
                ChatFailureCode.GENERATION_FAILED: "CHAT generation failed",
                ChatFailureCode.OUTPUT_VALIDATION_FAILED:
                    "CHAT output validation failed",
                ChatFailureCode.CITATION_VALIDATION_FAILED:
                    "CHAT citation validation failed",
                ChatFailureCode.PERSISTENCE_FAILED: "CHAT persistence failed",
                ChatFailureCode.UNEXPECTED_FAILURE: "CHAT completion failed",
                ChatFailureCode.CANCELLED: "CHAT completion was cancelled",
            }[failure_code]
        )


def _is_ready_chat_status(value: object) -> bool:
    return (
        isinstance(value, LocalModelStatus)
        and value.readiness is ModelReadiness.READY
        and value.model.capability is ModelCapability.CHAT
    )
