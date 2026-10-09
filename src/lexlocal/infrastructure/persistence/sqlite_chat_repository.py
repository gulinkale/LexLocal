"""Persist and reconstruct CHAT completion graphs in an active transaction."""

import sqlite3
from datetime import datetime, timedelta

from lexlocal.application.ports.chat import (
    ChatActivityEvent,
    ChatActivityResult,
    ChatActivityType,
    ChatAssistantMessage,
    ChatCitationRegistration,
    ChatCompletionRegistration,
    ChatCompletionTarget,
    ChatFailureUpdate,
    ChatIntakeRegistration,
    ChatPersistenceError,
    ChatRepository,
    ChatResponseContractVersion,
    ChatTerminalGraph,
    ChatVerifierSnapshot,
    ChatVerifierSnapshotRelation,
    QaRequestState,
    QaScopeVersionReference,
)
from lexlocal.application.ports.evidence_sufficiency import (
    AggregateEvidenceCoverage,
    EvidenceRelation,
    EvidenceRelationCounts,
)
from lexlocal.application.ports.security import (
    EncodedSensitivePayload,
    SensitivePayloadCodec,
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
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
from lexlocal.domain.retrieval import EvidenceRank, EvidenceSufficiency
from lexlocal.infrastructure.persistence.sqlite_retrieval_repository import (
    SQLiteRetrievalRepository,
)

_CODEC_FORMAT_VERSION = 1
_PAYLOAD_SCHEMA_VERSION = 1
_MESSAGE_CONTENT_PURPOSE = "chat-message-content"


class SQLiteChatRepository(ChatRepository):
    """Map CHAT terminal state without owning transaction finalization."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        payload_codec: SensitivePayloadCodec,
    ) -> None:
        self._connection = connection
        self._payload_codec = payload_codec
        self._retrieval_repository = SQLiteRetrievalRepository(
            connection,
            payload_codec,
        )

    def get_target(
        self,
        workspace_id: WorkspaceId,
        qa_request_id: QaRequestId,
    ) -> ChatCompletionTarget | None:
        """Load one exact committed question and immutable QA scope."""

        self._require_transaction()
        self._require_lookup_types(workspace_id, qa_request_id)
        try:
            row = self._qa_row(qa_request_id)
            if row is None:
                return None
            self._validate_target_row(row, workspace_id, qa_request_id)
            scope = self._scope_rows(workspace_id, qa_request_id)
            question_message_id = ChatMessageId(row["question_message_id"])
            question = self._decode_text(
                row["question_ciphertext"],
                workspace_id=workspace_id,
                message_id=question_message_id,
            )
            return ChatCompletionTarget(
                workspace_id=workspace_id,
                chat_id=ChatId(row["chat_id"]),
                qa_request_id=qa_request_id,
                question_message_id=question_message_id,
                question_sequence_number=row["question_sequence_number"],
                question=question,
                scope_versions=scope,
                state=QaRequestState(row["state"]),
                answer_message_id=(
                    ChatMessageId(row["answer_message_id"])
                    if row["answer_message_id"] is not None
                    else None
                ),
            )
        except ChatPersistenceError:
            raise
        except Exception:
            raise ChatPersistenceError("CHAT target reconstruction failed") from None

    def get_completed(
        self,
        workspace_id: WorkspaceId,
        qa_request_id: QaRequestId,
    ) -> ChatTerminalGraph | None:
        """Reconstruct the sole complete terminal graph or fail closed."""

        self._require_transaction()
        self._require_lookup_types(workspace_id, qa_request_id)
        try:
            target = self.get_target(workspace_id, qa_request_id)
            if target is None:
                return None
            row = self._qa_row(qa_request_id)
            if row is None:
                raise ChatPersistenceError("CHAT terminal owner is invalid")
            if target.state not in (
                QaRequestState.COMPLETED,
                QaRequestState.COMPLETED_INSUFFICIENT,
            ):
                self._require_no_completion_artifacts(target)
                return None

            retrieval = self._retrieval_repository.get_for_qa_request(
                workspace_id,
                qa_request_id,
            )
            if retrieval is None:
                raise ChatPersistenceError("CHAT terminal retrieval is missing")
            snapshot = self._map_snapshot(workspace_id, qa_request_id, retrieval.retrieval_run_id)
            answer = self._map_answer(target)
            citations = self._map_citations(target, retrieval.retrieval_run_id)
            activity = self._map_completion_activity(workspace_id, qa_request_id)
            evidence_state = self._map_evidence_state(row["evidence_state"])
            completed_at = self._parse_timestamp(row["completed_at"])
            response_version = ChatResponseContractVersion(row["prompt_contract_version"])
            chat_model_id = (
                LocalModelId(row["chat_model_id"])
                if row["chat_model_id"] is not None
                else None
            )
            if (
                row["top_k"] != retrieval.configuration.top_k
                or row["evidence_policy_version"]
                != snapshot.evidence_policy_version
                or row["error_code"] is not None
                or row["error_metadata_json"] is not None
            ):
                raise ChatPersistenceError("CHAT terminal metadata is inconsistent")
            return ChatTerminalGraph(
                target=target,
                retrieval=retrieval,
                snapshot=snapshot,
                answer=answer,
                evidence_state=evidence_state,
                response_contract_version=response_version,
                chat_model_id=chat_model_id,
                citations=citations,
                completed_at=completed_at,
                activity=activity,
            )
        except ChatPersistenceError:
            raise
        except Exception:
            raise ChatPersistenceError("CHAT terminal reconstruction failed") from None

    def add_intake(self, registration: ChatIntakeRegistration) -> bool:
        """Stage one exact intake or reconstruct its compatible committed graph."""

        self._require_transaction()
        if not isinstance(registration, ChatIntakeRegistration):
            raise ChatPersistenceError("CHAT intake registration is invalid")
        try:
            self._require_intake_source(registration)
            existing_row = self._qa_row(registration.qa_request_id)
            if existing_row is not None:
                target = self.get_target(
                    registration.workspace_id,
                    registration.qa_request_id,
                )
                if target != registration.target:
                    raise ChatPersistenceError("CHAT intake conflicts with existing state")
                self._require_compatible_intake(registration)
                return True

            self._require_intake_ids_absent(registration)
            payload = self._encode_text(
                registration.question,
                workspace_id=registration.workspace_id,
                message_id=registration.question_message_id,
            )
            timestamp = self._timestamp(registration.created_at)
            self._insert_intake(registration, payload, timestamp)
            return False
        except ChatPersistenceError:
            raise
        except Exception:
            raise ChatPersistenceError("CHAT intake persistence failed") from None

    def add(self, registration: ChatCompletionRegistration) -> None:
        """Stage one complete terminal graph on the caller's transaction."""

        self._require_transaction()
        if not isinstance(registration, ChatCompletionRegistration):
            raise ChatPersistenceError("CHAT registration is invalid")
        try:
            target = self.get_target(
                registration.target.workspace_id,
                registration.target.qa_request_id,
            )
            if target != registration.target:
                raise ChatPersistenceError("CHAT registration target is stale")
            self._require_clean_registration_target(registration.target)
            retrieval = self._retrieval_repository.get_for_qa_request(
                registration.target.workspace_id,
                registration.target.qa_request_id,
            )
            if retrieval is None or retrieval != registration.sufficiency.retrieval:
                raise ChatPersistenceError("CHAT registration retrieval is inconsistent")

            answer_payload = self._encode_text(
                registration.answer.content,
                workspace_id=registration.answer.workspace_id,
                message_id=registration.answer.id,
            )
            self._insert_answer(registration.answer, answer_payload)
            self._insert_snapshot(registration.snapshot)
            self._insert_citations(registration.citations)
            self._update_terminal_request(registration)
            self._update_chat(
                registration.target.workspace_id,
                registration.target.chat_id,
                registration.completed_at,
            )
            self._insert_activity(registration.activity)
        except ChatPersistenceError:
            raise
        except Exception:
            raise ChatPersistenceError("CHAT persistence failed") from None

    def record_failure(self, update: ChatFailureUpdate) -> None:
        """Stage one sanitized non-completed terminal state update."""

        self._require_transaction()
        if not isinstance(update, ChatFailureUpdate):
            raise ChatPersistenceError("CHAT failure update is invalid")
        try:
            target = self.get_target(update.target.workspace_id, update.target.qa_request_id)
            if target != update.target or target is None:
                raise ChatPersistenceError("CHAT failure target is stale")
            if target.state not in (
                QaRequestState.DRAFT,
                QaRequestState.SEARCHING,
                QaRequestState.EVALUATING_EVIDENCE,
                QaRequestState.GENERATING,
                QaRequestState.VALIDATING_CITATIONS,
                QaRequestState.FAILED,
                QaRequestState.CANCELLED,
            ):
                raise ChatPersistenceError("CHAT failure target state is invalid")
            self._require_no_completion_artifacts(target)
            cursor = self._connection.execute(
                """
                UPDATE qa_requests
                SET state = ?, evidence_state = NULL, chat_model_id = NULL,
                    prompt_contract_version = NULL, top_k = NULL,
                    evidence_policy_version = NULL, error_code = ?,
                    error_metadata_json = NULL, completed_at = ?
                WHERE id = ? AND workspace_id = ? AND state = ?
                  AND answer_message_id IS NULL
                """,
                (
                    update.state.value,
                    update.error_code.value,
                    self._timestamp(update.updated_at),
                    str(target.qa_request_id),
                    str(target.workspace_id),
                    target.state.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ChatPersistenceError("CHAT failure update conflicted")
            self._update_chat(target.workspace_id, target.chat_id, update.updated_at)
            self._insert_activity(update.activity)
        except ChatPersistenceError:
            raise
        except Exception:
            raise ChatPersistenceError("CHAT failure persistence failed") from None

    def _require_intake_source(self, registration: ChatIntakeRegistration) -> None:
        generation = registration.active_generation
        row = self._connection.execute(
            """
            SELECT w.state AS workspace_state,
                   d.workspace_id AS document_workspace_id,
                   d.state AS document_state,
                   v.workspace_id AS version_workspace_id,
                   v.document_id AS version_document_id,
                   v.state AS version_state,
                   j.workspace_id AS job_workspace_id,
                   j.document_version_id AS job_version_id,
                   j.state AS job_state,
                   g.workspace_id AS generation_workspace_id,
                   g.document_version_id AS generation_version_id,
                   g.processing_job_id AS generation_job_id,
                   g.state AS generation_state,
                   g.embedding_model_id,
                   g.chunking_profile_version,
                   g.normalization_profile_version,
                   g.embedding_dimensions,
                   g.vector_dtype,
                   g.activated_at AS generation_activated_at,
                   g.archived_at AS generation_archived_at
            FROM workspaces AS w
            LEFT JOIN documents AS d
              ON d.id = ? AND d.workspace_id = w.id
            LEFT JOIN document_versions AS v
              ON v.id = ? AND v.workspace_id = w.id
            LEFT JOIN document_processing_jobs AS j
              ON j.id = ? AND j.workspace_id = w.id
            LEFT JOIN index_generations AS g
              ON g.id = ? AND g.workspace_id = w.id
            WHERE w.id = ?
            """,
            (
                str(registration.document_id),
                str(registration.document_version_id),
                str(generation.processing_job_id),
                str(generation.id),
                str(registration.workspace_id),
            ),
        ).fetchone()
        if (
            row is None
            or row["workspace_state"] != "ACTIVE"
            or row["document_workspace_id"] != str(registration.workspace_id)
            or row["document_state"] != "ACTIVE"
            or row["version_workspace_id"] != str(registration.workspace_id)
            or row["version_document_id"] != str(registration.document_id)
            or row["version_state"] != "ACTIVE"
            or row["job_workspace_id"] != str(registration.workspace_id)
            or row["job_version_id"] != str(registration.document_version_id)
            or row["job_state"] not in ("READY", "READY_WITH_WARNINGS")
            or row["generation_workspace_id"] != str(registration.workspace_id)
            or row["generation_version_id"] != str(registration.document_version_id)
            or row["generation_job_id"] != str(generation.processing_job_id)
            or row["generation_state"] != "ACTIVE"
            or row["embedding_model_id"] != str(generation.embedding_model_id)
            or row["chunking_profile_version"]
            != generation.chunking_profile_version
            or row["normalization_profile_version"]
            != generation.normalization_profile_version
            or row["embedding_dimensions"] != generation.embedding_dimensions
            or row["vector_dtype"] != "float32"
            or row["generation_activated_at"] is None
            or row["generation_archived_at"] is not None
        ):
            raise ChatPersistenceError("CHAT intake source is unavailable")

    def _require_intake_ids_absent(self, registration: ChatIntakeRegistration) -> None:
        row = self._connection.execute(
            """
            SELECT
              EXISTS(SELECT 1 FROM chats WHERE id = ?) AS chat_exists,
              EXISTS(SELECT 1 FROM chat_scope_documents WHERE chat_id = ?)
                AS chat_scope_exists,
              EXISTS(SELECT 1 FROM chat_messages WHERE id = ?) AS message_exists,
              EXISTS(SELECT 1 FROM qa_requests WHERE id = ?) AS qa_exists,
              EXISTS(SELECT 1 FROM qa_scope_versions WHERE qa_request_id = ?)
                AS qa_scope_exists
            """,
            (
                str(registration.chat_id),
                str(registration.chat_id),
                str(registration.question_message_id),
                str(registration.qa_request_id),
                str(registration.qa_request_id),
            ),
        ).fetchone()
        if row is None or any(row):
            raise ChatPersistenceError("CHAT intake state is partial or conflicting")

    def _require_compatible_intake(
        self,
        registration: ChatIntakeRegistration,
    ) -> None:
        timestamp = self._timestamp(registration.created_at)
        row = self._connection.execute(
            """
            SELECT c.title_ciphertext, c.title_source,
                   c.created_at AS chat_created_at,
                   c.updated_at AS chat_updated_at,
                   m.created_at AS message_created_at,
                   q.created_at AS request_created_at,
                   q.answer_message_id, q.started_at, q.completed_at,
                   q.evidence_state, q.chat_model_id,
                   q.prompt_contract_version, q.top_k,
                   q.evidence_policy_version, q.error_code,
                   q.error_metadata_json,
                   cs.included_at AS chat_scope_included_at,
                   qs.included_at AS qa_scope_included_at,
                   (SELECT COUNT(*) FROM chat_messages WHERE chat_id = c.id)
                     AS message_count,
                   (SELECT COUNT(*) FROM qa_requests WHERE chat_id = c.id)
                     AS request_count,
                   (SELECT COUNT(*) FROM chat_scope_documents WHERE chat_id = c.id)
                     AS chat_scope_count,
                   (SELECT COUNT(*) FROM qa_scope_versions
                    WHERE qa_request_id = q.id) AS qa_scope_count
            FROM qa_requests AS q
            JOIN chats AS c
              ON c.id = q.chat_id AND c.workspace_id = q.workspace_id
            JOIN chat_messages AS m
              ON m.id = q.question_message_id AND m.workspace_id = q.workspace_id
            JOIN chat_scope_documents AS cs
              ON cs.chat_id = c.id AND cs.workspace_id = c.workspace_id
             AND cs.document_id = ?
            JOIN qa_scope_versions AS qs
              ON qs.qa_request_id = q.id AND qs.workspace_id = q.workspace_id
             AND qs.document_id = ? AND qs.document_version_id = ?
            WHERE q.id = ? AND q.workspace_id = ?
            """,
            (
                str(registration.document_id),
                str(registration.document_id),
                str(registration.document_version_id),
                str(registration.qa_request_id),
                str(registration.workspace_id),
            ),
        ).fetchone()
        nullable_request_fields = (
            "answer_message_id",
            "started_at",
            "completed_at",
            "evidence_state",
            "chat_model_id",
            "prompt_contract_version",
            "top_k",
            "evidence_policy_version",
            "error_code",
            "error_metadata_json",
        )
        if (
            row is None
            or row["title_ciphertext"] is not None
            or row["title_source"] is not None
            or any(row[name] is not None for name in nullable_request_fields)
            or any(
                row[name] != timestamp
                for name in (
                    "chat_created_at",
                    "chat_updated_at",
                    "message_created_at",
                    "request_created_at",
                    "chat_scope_included_at",
                    "qa_scope_included_at",
                )
            )
            or row["message_count"] != 1
            or row["request_count"] != 1
            or row["chat_scope_count"] != 1
            or row["qa_scope_count"] != 1
        ):
            raise ChatPersistenceError("CHAT intake state is partial or conflicting")

    def _insert_intake(
        self,
        registration: ChatIntakeRegistration,
        question_payload: bytes,
        timestamp: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO chats (
                id, workspace_id, title_ciphertext, title_source,
                state, created_at, updated_at
            ) VALUES (?, ?, NULL, NULL, 'ACTIVE', ?, ?)
            """,
            (
                str(registration.chat_id),
                str(registration.workspace_id),
                timestamp,
                timestamp,
            ),
        )
        self._connection.execute(
            """
            INSERT INTO chat_scope_documents (
                chat_id, workspace_id, document_id, included_at
            ) VALUES (?, ?, ?, ?)
            """,
            (
                str(registration.chat_id),
                str(registration.workspace_id),
                str(registration.document_id),
                timestamp,
            ),
        )
        self._connection.execute(
            """
            INSERT INTO chat_messages (
                id, workspace_id, chat_id, role, sequence_number,
                content_ciphertext, created_at
            ) VALUES (?, ?, ?, 'USER', 1, ?, ?)
            """,
            (
                str(registration.question_message_id),
                str(registration.workspace_id),
                str(registration.chat_id),
                question_payload,
                timestamp,
            ),
        )
        self._connection.execute(
            """
            INSERT INTO qa_requests (
                id, workspace_id, chat_id, question_message_id,
                state, created_at
            ) VALUES (?, ?, ?, ?, 'DRAFT', ?)
            """,
            (
                str(registration.qa_request_id),
                str(registration.workspace_id),
                str(registration.chat_id),
                str(registration.question_message_id),
                timestamp,
            ),
        )
        self._connection.execute(
            """
            INSERT INTO qa_scope_versions (
                qa_request_id, workspace_id, document_id,
                document_version_id, included_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(registration.qa_request_id),
                str(registration.workspace_id),
                str(registration.document_id),
                str(registration.document_version_id),
                timestamp,
            ),
        )

    def _qa_row(self, qa_request_id: QaRequestId) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self._connection.execute(
            """
            SELECT q.*, w.state AS workspace_state,
                   c.workspace_id AS chat_workspace_id,
                   c.state AS chat_state,
                   m.workspace_id AS question_workspace_id,
                   m.chat_id AS question_chat_id,
                   m.role AS question_role,
                   m.sequence_number AS question_sequence_number,
                   m.content_ciphertext AS question_ciphertext
            FROM qa_requests AS q
            LEFT JOIN workspaces AS w ON w.id = q.workspace_id
            LEFT JOIN chats AS c ON c.id = q.chat_id
            LEFT JOIN chat_messages AS m ON m.id = q.question_message_id
            WHERE q.id = ?
            """,
            (str(qa_request_id),),
        ).fetchone()
        return row

    @staticmethod
    def _validate_target_row(
        row: sqlite3.Row,
        workspace_id: WorkspaceId,
        qa_request_id: QaRequestId,
    ) -> None:
        if (
            row["id"] != str(qa_request_id)
            or row["workspace_id"] != str(workspace_id)
            or row["workspace_state"] != "ACTIVE"
            or row["chat_workspace_id"] != str(workspace_id)
            or row["chat_state"] != "ACTIVE"
            or row["question_workspace_id"] != str(workspace_id)
            or row["question_chat_id"] != row["chat_id"]
            or row["question_role"] != "USER"
            or not isinstance(row["question_sequence_number"], int)
            or row["question_sequence_number"] < 1
            or not isinstance(row["question_ciphertext"], bytes)
        ):
            raise ChatPersistenceError("CHAT target ownership is invalid")

    def _scope_rows(
        self,
        workspace_id: WorkspaceId,
        qa_request_id: QaRequestId,
    ) -> tuple[QaScopeVersionReference, ...]:
        rows = self._connection.execute(
            """
            SELECT s.*, d.workspace_id AS document_workspace_id,
                   v.workspace_id AS version_workspace_id,
                   v.document_id AS version_document_id
            FROM qa_scope_versions AS s
            LEFT JOIN documents AS d ON d.id = s.document_id
            LEFT JOIN document_versions AS v ON v.id = s.document_version_id
            WHERE s.qa_request_id = ?
            ORDER BY s.document_id, s.document_version_id
            """,
            (str(qa_request_id),),
        ).fetchall()
        if not rows or any(
            row["workspace_id"] != str(workspace_id)
            or row["document_workspace_id"] != str(workspace_id)
            or row["version_workspace_id"] != str(workspace_id)
            or row["version_document_id"] != row["document_id"]
            for row in rows
        ):
            raise ChatPersistenceError("CHAT QA scope is invalid")
        return tuple(
            QaScopeVersionReference(
                workspace_id,
                qa_request_id,
                DocumentId(row["document_id"]),
                DocumentVersionId(row["document_version_id"]),
                self._parse_timestamp(row["included_at"]),
            )
            for row in rows
        )

    def _require_clean_registration_target(self, target: ChatCompletionTarget) -> None:
        row = self._qa_row(target.qa_request_id)
        retry = target.state in (QaRequestState.FAILED, QaRequestState.CANCELLED)
        if row is None or any(
            row[name] is not None
            for name in (
                "answer_message_id",
                "evidence_state",
                "chat_model_id",
                "prompt_contract_version",
                "top_k",
                "evidence_policy_version",
                "error_metadata_json",
            )
        ) or (
            not retry
            and (row["error_code"] is not None or row["completed_at"] is not None)
        ) or (
            retry
            and (row["error_code"] is None or row["completed_at"] is None)
        ):
            raise ChatPersistenceError("CHAT registration target is not clean")
        self._require_no_completion_artifacts(target)

    def _require_no_completion_artifacts(self, target: ChatCompletionTarget) -> None:
        answer_count = self._connection.execute(
            """
            SELECT COUNT(*) FROM chat_messages
            WHERE chat_id = ? AND sequence_number = ? AND role = 'ASSISTANT'
            """,
            (str(target.chat_id), target.question_sequence_number + 1),
        ).fetchone()[0]
        snapshot_count = self._connection.execute(
            "SELECT COUNT(*) FROM qa_verifier_snapshots WHERE qa_request_id = ?",
            (str(target.qa_request_id),),
        ).fetchone()[0]
        activity_count = self._connection.execute(
            """
            SELECT COUNT(*) FROM activity_events
            WHERE subject_type = 'QA_REQUEST' AND subject_id = ?
              AND event_type = 'QA_COMPLETED'
            """,
            (str(target.qa_request_id),),
        ).fetchone()[0]
        if answer_count or snapshot_count or activity_count:
            raise ChatPersistenceError("CHAT completion state is partial")

    def _map_answer(self, target: ChatCompletionTarget) -> ChatAssistantMessage:
        if target.answer_message_id is None:
            raise ChatPersistenceError("CHAT answer is missing")
        row = self._connection.execute(
            "SELECT * FROM chat_messages WHERE id = ?",
            (str(target.answer_message_id),),
        ).fetchone()
        if (
            row is None
            or row["workspace_id"] != str(target.workspace_id)
            or row["chat_id"] != str(target.chat_id)
            or row["role"] != "ASSISTANT"
            or row["sequence_number"] != target.question_sequence_number + 1
            or not isinstance(row["content_ciphertext"], bytes)
        ):
            raise ChatPersistenceError("CHAT answer mapping is invalid")
        return ChatAssistantMessage(
            target.answer_message_id,
            target.workspace_id,
            target.chat_id,
            row["sequence_number"],
            self._decode_text(
                row["content_ciphertext"],
                workspace_id=target.workspace_id,
                message_id=target.answer_message_id,
            ),
            self._parse_timestamp(row["created_at"]),
        )

    def _map_snapshot(
        self,
        workspace_id: WorkspaceId,
        qa_request_id: QaRequestId,
        retrieval_run_id: RetrievalRunId,
    ) -> ChatVerifierSnapshot:
        rows = self._connection.execute(
            "SELECT * FROM qa_verifier_snapshots WHERE qa_request_id = ?",
            (str(qa_request_id),),
        ).fetchall()
        if len(rows) != 1:
            raise ChatPersistenceError("CHAT verifier snapshot is missing or ambiguous")
        row = rows[0]
        if (
            row["workspace_id"] != str(workspace_id)
            or row["retrieval_run_id"] != str(retrieval_run_id)
        ):
            raise ChatPersistenceError("CHAT verifier snapshot ownership is invalid")
        relation_rows = self._connection.execute(
            """
            SELECT r.*, e.rank, e.retrieval_run_id AS evidence_retrieval_run_id,
                   e.workspace_id AS evidence_workspace_id
            FROM qa_verifier_snapshot_relations AS r
            LEFT JOIN evidence_items AS e ON e.id = r.evidence_item_id
            WHERE r.qa_request_id = ?
            ORDER BY e.rank, e.id
            """,
            (str(qa_request_id),),
        ).fetchall()
        relations: list[ChatVerifierSnapshotRelation] = []
        for relation_row in relation_rows:
            if (
                relation_row["workspace_id"] != str(workspace_id)
                or relation_row["retrieval_run_id"] != str(retrieval_run_id)
                or relation_row["evidence_workspace_id"] != str(workspace_id)
                or relation_row["evidence_retrieval_run_id"] != str(retrieval_run_id)
                or not isinstance(relation_row["rank"], int)
            ):
                raise ChatPersistenceError("CHAT verifier relation ownership is invalid")
            relations.append(
                ChatVerifierSnapshotRelation(
                    workspace_id,
                    qa_request_id,
                    retrieval_run_id,
                    EvidenceItemId(relation_row["evidence_item_id"]),
                    EvidenceRank(relation_row["rank"]),
                    EvidenceRelation(relation_row["relation"]),
                )
            )
        return ChatVerifierSnapshot(
            workspace_id,
            qa_request_id,
            retrieval_run_id,
            row["evidence_policy_version"],
            AggregateEvidenceCoverage(row["aggregate_coverage"]),
            EvidenceRelationCounts(
                row["supports_count"],
                row["related_only_count"],
                row["contradicts_count"],
                row["irrelevant_count"],
            ),
            self._map_bool(row["repair_used"]),
            tuple(relations),
        )

    def _map_citations(
        self,
        target: ChatCompletionTarget,
        retrieval_run_id: RetrievalRunId,
    ) -> tuple[ChatCitationRegistration, ...]:
        if target.answer_message_id is None:
            raise ChatPersistenceError("CHAT citation owner is missing")
        rows = self._connection.execute(
            """
            SELECT c.*, e.retrieval_run_id, e.workspace_id AS evidence_workspace_id
            FROM citations AS c
            LEFT JOIN evidence_items AS e ON e.id = c.evidence_item_id
            WHERE c.answer_message_id = ?
            ORDER BY c.ordinal, c.id
            """,
            (str(target.answer_message_id),),
        ).fetchall()
        result: list[ChatCitationRegistration] = []
        for row in rows:
            if (
                row["workspace_id"] != str(target.workspace_id)
                or row["evidence_workspace_id"] != str(target.workspace_id)
                or row["retrieval_run_id"] != str(retrieval_run_id)
                or row["analysis_version_id"] is not None
                or row["analysis_section_key"] is not None
                or row["status"] != "VALID"
            ):
                raise ChatPersistenceError("CHAT citation mapping is invalid")
            result.append(
                ChatCitationRegistration(
                    CitationId(row["id"]),
                    target.workspace_id,
                    EvidenceItemId(row["evidence_item_id"]),
                    target.answer_message_id,
                    row["ordinal"],
                    self._parse_timestamp(row["created_at"]),
                )
            )
        return tuple(result)

    def _map_completion_activity(
        self,
        workspace_id: WorkspaceId,
        qa_request_id: QaRequestId,
    ) -> ChatActivityEvent:
        rows = self._connection.execute(
            """
            SELECT * FROM activity_events
            WHERE subject_type = 'QA_REQUEST' AND subject_id = ?
              AND event_type = 'QA_COMPLETED'
            ORDER BY id
            """,
            (str(qa_request_id),),
        ).fetchall()
        if len(rows) != 1:
            raise ChatPersistenceError("CHAT completion activity is missing or ambiguous")
        row = rows[0]
        if (
            row["workspace_id"] != str(workspace_id)
            or row["category"] != "CHAT"
            or row["summary_key"] != "chat.qa.completed"
            or row["safe_metadata_json"] is not None
            or row["correlation_id"] is not None
        ):
            raise ChatPersistenceError("CHAT completion activity is invalid")
        return ChatActivityEvent(
            ActivityEventId(row["id"]),
            workspace_id,
            qa_request_id,
            ChatActivityType(row["event_type"]),
            ChatActivityResult(row["result_status"]),
            self._parse_timestamp(row["created_at"]),
        )

    def _insert_answer(self, message: ChatAssistantMessage, payload: bytes) -> None:
        self._connection.execute(
            """
            INSERT INTO chat_messages (
                id, workspace_id, chat_id, role, sequence_number,
                content_ciphertext, created_at
            ) VALUES (?, ?, ?, 'ASSISTANT', ?, ?, ?)
            """,
            (
                str(message.id),
                str(message.workspace_id),
                str(message.chat_id),
                message.sequence_number,
                payload,
                self._timestamp(message.created_at),
            ),
        )

    def _insert_snapshot(self, snapshot: ChatVerifierSnapshot) -> None:
        counts = snapshot.relation_counts
        self._connection.execute(
            """
            INSERT INTO qa_verifier_snapshots (
                qa_request_id, workspace_id, retrieval_run_id,
                evidence_policy_version, aggregate_coverage,
                supports_count, related_only_count, contradicts_count,
                irrelevant_count, repair_used
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(snapshot.qa_request_id),
                str(snapshot.workspace_id),
                str(snapshot.retrieval_run_id),
                snapshot.evidence_policy_version,
                snapshot.aggregate_coverage.value,
                counts.supports,
                counts.related_only,
                counts.contradicts,
                counts.irrelevant,
                int(snapshot.repair_used),
            ),
        )
        self._connection.executemany(
            """
            INSERT INTO qa_verifier_snapshot_relations (
                qa_request_id, workspace_id, retrieval_run_id,
                evidence_item_id, relation
            ) VALUES (?, ?, ?, ?, ?)
            """,
            tuple(
                (
                    str(snapshot.qa_request_id),
                    str(snapshot.workspace_id),
                    str(snapshot.retrieval_run_id),
                    str(item.evidence_item_id),
                    item.relation.value,
                )
                for item in snapshot.relations
            ),
        )

    def _insert_citations(
        self,
        citations: tuple[ChatCitationRegistration, ...],
    ) -> None:
        self._connection.executemany(
            """
            INSERT INTO citations (
                id, workspace_id, evidence_item_id, answer_message_id,
                analysis_version_id, analysis_section_key,
                ordinal, status, created_at
            ) VALUES (?, ?, ?, ?, NULL, NULL, ?, 'VALID', ?)
            """,
            tuple(
                (
                    str(item.id),
                    str(item.workspace_id),
                    str(item.evidence_item_id),
                    str(item.answer_message_id),
                    item.ordinal,
                    self._timestamp(item.created_at),
                )
                for item in citations
            ),
        )

    def _update_terminal_request(self, registration: ChatCompletionRegistration) -> None:
        target = registration.target
        cursor = self._connection.execute(
            """
            UPDATE qa_requests
            SET answer_message_id = ?, state = ?, evidence_state = ?,
                chat_model_id = ?, prompt_contract_version = ?, top_k = ?,
                evidence_policy_version = ?, error_code = NULL,
                error_metadata_json = NULL, completed_at = ?
            WHERE id = ? AND workspace_id = ? AND state = ?
              AND answer_message_id IS NULL
            """,
            (
                str(registration.answer.id),
                registration.terminal_state.value,
                registration.sufficiency.state.value,
                (
                    str(registration.chat_model_id)
                    if registration.chat_model_id is not None
                    else None
                ),
                registration.response_contract_version.value,
                registration.sufficiency.retrieval.configuration.top_k,
                registration.snapshot.evidence_policy_version,
                self._timestamp(registration.completed_at),
                str(target.qa_request_id),
                str(target.workspace_id),
                target.state.value,
            ),
        )
        if cursor.rowcount != 1:
            raise ChatPersistenceError("CHAT terminal update conflicted")

    def _update_chat(
        self,
        workspace_id: WorkspaceId,
        chat_id: ChatId,
        updated_at: datetime,
    ) -> None:
        cursor = self._connection.execute(
            """
            UPDATE chats SET updated_at = ?
            WHERE id = ? AND workspace_id = ? AND state = 'ACTIVE'
            """,
            (self._timestamp(updated_at), str(chat_id), str(workspace_id)),
        )
        if cursor.rowcount != 1:
            raise ChatPersistenceError("CHAT owner update conflicted")

    def _insert_activity(self, activity: ChatActivityEvent) -> None:
        self._connection.execute(
            """
            INSERT INTO activity_events (
                id, workspace_id, category, event_type, result_status,
                subject_type, subject_id, summary_key, safe_metadata_json,
                correlation_id, created_at
            ) VALUES (?, ?, 'CHAT', ?, ?, 'QA_REQUEST', ?, ?, NULL, NULL, ?)
            """,
            (
                str(activity.id),
                str(activity.workspace_id),
                activity.event_type.value,
                activity.result.value,
                str(activity.qa_request_id),
                activity.summary_key,
                self._timestamp(activity.created_at),
            ),
        )

    def _encode_text(
        self,
        value: str,
        *,
        workspace_id: WorkspaceId,
        message_id: ChatMessageId,
    ) -> bytes:
        context, key = self._security_values(workspace_id, message_id)
        encoded = self._payload_codec.encode(
            value.encode("utf-8"),
            context=context,
            key_reference=key,
        )
        if (
            not isinstance(encoded, EncodedSensitivePayload)
            or encoded.context != context
            or encoded.key_reference != key
            or encoded.format_version != _CODEC_FORMAT_VERSION
        ):
            raise ChatPersistenceError("CHAT payload is invalid")
        return encoded.payload

    def _decode_text(
        self,
        payload: object,
        *,
        workspace_id: WorkspaceId,
        message_id: ChatMessageId,
    ) -> str:
        if not isinstance(payload, bytes):
            raise ChatPersistenceError("CHAT payload is invalid")
        context, key = self._security_values(workspace_id, message_id)
        plaintext = self._payload_codec.decode(
            EncodedSensitivePayload(payload, context, key, _CODEC_FORMAT_VERSION),
            context=context,
            key_reference=key,
        )
        if not isinstance(plaintext, bytes):
            raise ChatPersistenceError("CHAT payload is invalid")
        try:
            return plaintext.decode("utf-8")
        except UnicodeDecodeError:
            raise ChatPersistenceError("CHAT payload is invalid") from None

    @staticmethod
    def _security_values(
        workspace_id: WorkspaceId,
        message_id: ChatMessageId,
    ) -> tuple[SensitivePayloadContext, WorkspaceKeyReference]:
        return (
            SensitivePayloadContext(
                workspace_id,
                str(message_id),
                _MESSAGE_CONTENT_PURPOSE,
                _PAYLOAD_SCHEMA_VERSION,
            ),
            WorkspaceKeyReference(workspace_id, 1),
        )

    def _require_transaction(self) -> None:
        if not self._connection.in_transaction:
            raise ChatPersistenceError("CHAT transaction is not active")

    @staticmethod
    def _require_lookup_types(
        workspace_id: WorkspaceId,
        qa_request_id: QaRequestId,
    ) -> None:
        if not isinstance(workspace_id, WorkspaceId) or not isinstance(
            qa_request_id, QaRequestId
        ):
            raise ChatPersistenceError("CHAT lookup is invalid")

    @staticmethod
    def _map_evidence_state(value: object) -> EvidenceSufficiency:
        if not isinstance(value, str):
            raise ChatPersistenceError("CHAT evidence state is invalid")
        try:
            return EvidenceSufficiency(value)
        except ValueError:
            raise ChatPersistenceError("CHAT evidence state is invalid") from None

    @staticmethod
    def _map_bool(value: object) -> bool:
        if value not in (0, 1) or isinstance(value, bool):
            raise ChatPersistenceError("CHAT boolean mapping is invalid")
        return bool(value)

    @staticmethod
    def _timestamp(value: datetime) -> str:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ChatPersistenceError("CHAT timestamp is invalid")
        canonical = value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if SQLiteChatRepository._parse_timestamp(canonical) != value:
            raise ChatPersistenceError("CHAT timestamp is invalid")
        return canonical

    @staticmethod
    def _parse_timestamp(value: object) -> datetime:
        if not isinstance(value, str) or not value.endswith("Z"):
            raise ChatPersistenceError("CHAT timestamp is invalid")
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError:
            raise ChatPersistenceError("CHAT timestamp is invalid") from None
        canonical = parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if parsed.utcoffset() != timedelta(0) or value != canonical:
            raise ChatPersistenceError("CHAT timestamp is invalid")
        return parsed
