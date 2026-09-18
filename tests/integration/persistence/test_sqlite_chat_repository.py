"""Integration tests for exact SQLite CHAT completion persistence."""

import sqlite3
import struct
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.application.ports.chat import (
    ChatActivityEvent,
    ChatActivityResult,
    ChatActivityType,
    ChatAssistantMessage,
    ChatCitationRegistration,
    ChatCompletionRegistration,
    ChatFailureCode,
    ChatFailureUpdate,
    ChatPersistenceError,
    ChatResponseContractVersion,
    QaRequestState,
)
from lexlocal.application.ports.embeddings import (
    ChunkEmbedding,
    EmbeddingCompatibility,
    NormalizedEmbeddingVector,
)
from lexlocal.application.ports.evidence_sufficiency import (
    AggregateEvidenceCoverage,
    EvidenceAssessment,
    EvidencePolicyIdentity,
    EvidenceRelation,
    EvidenceRelationCounts,
    EvidenceSufficiencyResult,
)
from lexlocal.application.ports.local_models import (
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
    ResolvedModelRecord,
)
from lexlocal.application.ports.retrieval import (
    QaRetrievalRequest,
    RetrievalConfiguration,
    RetrievalEvidenceRegistration,
    RetrievalRegistration,
)
from lexlocal.application.ports.security import (
    EncodedSensitivePayload,
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
from lexlocal.domain.identifiers import (
    ActivityEventId,
    ChatId,
    ChatMessageId,
    ChunkId,
    CitationId,
    DocumentId,
    EvidenceItemId,
    IndexGenerationId,
    LocalModelId,
    QaRequestId,
    RetrievalRunId,
    WorkspaceId,
)
from lexlocal.domain.retrieval import Evidence, EvidenceRank, EvidenceSufficiency, SimilarityScore
from lexlocal.infrastructure.persistence.migration_runner import run_migrations
from lexlocal.infrastructure.persistence.migrations import (
    default_migrations_dir,
    discover_migrations,
)
from lexlocal.infrastructure.persistence.sqlite_chat_repository import (
    SQLiteChatRepository,
)
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.persistence.sqlite_embedding_repository import (
    SQLiteEmbeddingRepository,
)
from lexlocal.infrastructure.persistence.sqlite_retrieval_repository import (
    SQLiteRetrievalRepository,
)
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyPayloadCodec,
)

NOW = datetime(2026, 9, 16, 10, 20, 30, 456000, tzinfo=UTC)
TIMESTAMP = "2026-09-16T10:20:30.456Z"
WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
OTHER_WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000002")
CHAT_ID = ChatId("11000000-0000-4000-8000-000000000001")
QUESTION_ID = ChatMessageId("12000000-0000-4000-8000-000000000001")
QA_REQUEST_ID = QaRequestId("20000000-0000-4000-8000-000000000001")
RETRIEVAL_RUN_ID = RetrievalRunId("30000000-0000-4000-8000-000000000001")
EMBEDDING_MODEL_ID = LocalModelId("40000000-0000-4000-8000-000000000001")
CHAT_MODEL_ID = LocalModelId("41000000-0000-4000-8000-000000000001")
DOCUMENT_ID = DocumentId("50000000-0000-4000-8000-000000000001")
ANSWER_ID = ChatMessageId("d0000000-0000-4000-8000-000000000001")
EVIDENCE_ID = EvidenceItemId("c0000000-0000-4000-8000-000000000001")
QUESTION = " Exact anonymous question Ω\n"
ANSWER = " Exact synthetic grounded answer Ω\n"


class _RecordingCodec:
    def __init__(self) -> None:
        self._delegate = InsecureDevelopmentOnlyPayloadCodec()
        self.encoded: list[SensitivePayloadContext] = []
        self.decoded: list[SensitivePayloadContext] = []

    def encode(
        self,
        plaintext: bytes,
        *,
        context: SensitivePayloadContext,
        key_reference: WorkspaceKeyReference,
    ) -> EncodedSensitivePayload:
        self.encoded.append(context)
        return self._delegate.encode(
            plaintext,
            context=context,
            key_reference=key_reference,
        )

    def decode(
        self,
        encoded: EncodedSensitivePayload,
        *,
        context: SensitivePayloadContext,
        key_reference: WorkspaceKeyReference,
    ) -> bytes:
        self.decoded.append(context)
        return self._delegate.decode(
            encoded,
            context=context,
            key_reference=key_reference,
        )


@pytest.fixture
def database(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = SQLiteConnectionFactory(tmp_path / "lexlocal.db").create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
    _insert_source_graph(connection)
    connection.execute("BEGIN")
    yield connection
    if connection.in_transaction:
        connection.rollback()
    connection.close()


def _encode_text(
    value: str,
    *,
    workspace_id: WorkspaceId,
    owner_id: str,
    purpose: str,
) -> bytes:
    codec = InsecureDevelopmentOnlyPayloadCodec()
    context = SensitivePayloadContext(workspace_id, owner_id, purpose, 1)
    return codec.encode(
        value.encode("utf-8"),
        context=context,
        key_reference=WorkspaceKeyReference(workspace_id, 1),
    ).payload


def _insert_source_graph(connection: sqlite3.Connection) -> None:
    version_id = "60000000-0000-4000-8000-000000000001"
    job_id = "70000000-0000-4000-8000-000000000001"
    generation_id = "80000000-0000-4000-8000-000000000001"
    page_id = "90000000-0000-4000-8000-000000000001"
    locator_id = "a0000000-0000-4000-8000-000000000001"
    chunk_id = "b0000000-0000-4000-8000-000000000001"
    passage = "Synthetic supporting passage"
    compatibility = EmbeddingCompatibility(
        WORKSPACE_ID,
        IndexGenerationId(generation_id),
        EMBEDDING_MODEL_ID,
        "chunk-v1",
        "normalize-v1",
        2,
    )
    embedding = ChunkEmbedding(
        ChunkId(chunk_id),
        compatibility,
        NormalizedEmbeddingVector((0.6, 0.8)),
        NOW,
    )
    vector_context, vector_key = SQLiteEmbeddingRepository._security_values(
        embedding.chunk_id,
        compatibility,
    )
    vector_payload = InsecureDevelopmentOnlyPayloadCodec().encode(
        struct.pack("<2f", *embedding.vector.values),
        context=vector_context,
        key_reference=vector_key,
    ).payload
    connection.execute("BEGIN")
    connection.execute(
        """
        INSERT INTO workspaces
          (id, name_ciphertext, name_lookup_fingerprint, state, created_at, updated_at)
        VALUES (?, x'01', x'02', 'ACTIVE', ?, ?)
        """,
        (str(WORKSPACE_ID), TIMESTAMP, TIMESTAMP),
    )
    connection.executemany(
        """
        INSERT INTO local_models
          (id, purpose, provider, requested_alias, resolved_model_id,
           model_version, dimensions, created_at)
        VALUES (?, ?, 'synthetic', ?, ?, '1', ?, ?)
        """,
        (
            (
                str(EMBEDDING_MODEL_ID),
                "EMBEDDING",
                "synthetic-embedding",
                "synthetic-embedding-id",
                2,
                TIMESTAMP,
            ),
            (
                str(CHAT_MODEL_ID),
                "CHAT",
                "synthetic-chat",
                "synthetic-chat-id",
                None,
                TIMESTAMP,
            ),
        ),
    )
    connection.execute(
        """
        INSERT INTO chats (id, workspace_id, state, created_at, updated_at)
        VALUES (?, ?, 'ACTIVE', ?, ?)
        """,
        (str(CHAT_ID), str(WORKSPACE_ID), TIMESTAMP, TIMESTAMP),
    )
    question_payload = _encode_text(
        QUESTION,
        workspace_id=WORKSPACE_ID,
        owner_id=str(QUESTION_ID),
        purpose="chat-message-content",
    )
    connection.execute(
        """
        INSERT INTO chat_messages
          (id, workspace_id, chat_id, role, sequence_number, content_ciphertext, created_at)
        VALUES (?, ?, ?, 'USER', 1, ?, ?)
        """,
        (str(QUESTION_ID), str(WORKSPACE_ID), str(CHAT_ID), question_payload, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO qa_requests
          (id, workspace_id, chat_id, question_message_id, state, created_at)
        VALUES (?, ?, ?, ?, 'DRAFT', ?)
        """,
        (str(QA_REQUEST_ID), str(WORKSPACE_ID), str(CHAT_ID), str(QUESTION_ID), TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO documents
          (id, workspace_id, display_name_ciphertext, state, created_at, updated_at)
        VALUES (?, ?, ?, 'ACTIVE', ?, ?)
        """,
        (
            str(DOCUMENT_ID),
            str(WORKSPACE_ID),
            _encode_text(
                "Anonymous document",
                workspace_id=WORKSPACE_ID,
                owner_id=str(DOCUMENT_ID),
                purpose="document-display-name",
            ),
            TIMESTAMP,
            TIMESTAMP,
        ),
    )
    connection.execute(
        """
        INSERT INTO document_versions
          (id, workspace_id, document_id, version_number,
           historical_filename_ciphertext, page_count, state, created_at, activated_at)
        VALUES (?, ?, ?, 1, x'01', 1, 'ACTIVE', ?, ?)
        """,
        (version_id, str(WORKSPACE_ID), str(DOCUMENT_ID), TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO document_processing_jobs
          (id, workspace_id, document_version_id, attempt_number,
           state, stage, created_at, completed_at)
        VALUES (?, ?, ?, 1, 'READY', 'CHUNKING', ?, ?)
        """,
        (job_id, str(WORKSPACE_ID), version_id, TIMESTAMP, TIMESTAMP),
    )
    page_payload = _encode_text(
        passage,
        workspace_id=WORKSPACE_ID,
        owner_id=page_id,
        purpose="document-page-text",
    )
    connection.execute(
        """
        INSERT INTO document_pages
          (id, workspace_id, document_version_id, page_number, state,
           extraction_method, text_ciphertext, character_count, created_at, updated_at)
        VALUES (?, ?, ?, 1, 'READY', 'NATIVE', ?, ?, ?, ?)
        """,
        (page_id, str(WORKSPACE_ID), version_id, page_payload, len(passage), TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO source_locators
          (id, workspace_id, document_version_id, page_id,
           locator_kind, page_number, locator_version, created_at)
        VALUES (?, ?, ?, ?, 'PAGE', 1, 1, ?)
        """,
        (locator_id, str(WORKSPACE_ID), version_id, page_id, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO index_generations
          (id, workspace_id, document_version_id, processing_job_id, state,
           embedding_model_id, chunking_profile_version,
           normalization_profile_version, embedding_dimensions,
           vector_dtype, chunk_count, created_at, activated_at)
        VALUES (?, ?, ?, ?, 'ACTIVE', ?, 'chunk-v1', 'normalize-v1',
                2, 'float32', 1, ?, ?)
        """,
        (
            generation_id,
            str(WORKSPACE_ID),
            version_id,
            job_id,
            str(EMBEDDING_MODEL_ID),
            TIMESTAMP,
            TIMESTAMP,
        ),
    )
    chunk_payload = _encode_text(
        passage,
        workspace_id=WORKSPACE_ID,
        owner_id=chunk_id,
        purpose="index-chunk-text",
    )
    connection.execute(
        """
        INSERT INTO chunks
          (id, workspace_id, index_generation_id, document_version_id, page_id,
           source_locator_id, document_order, page_order, text_ciphertext,
           normalized_text_fingerprint, character_count, token_count_estimate,
           extraction_method, created_at, source_start_offset, source_end_offset)
        VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, x'01', ?, NULL, 'NATIVE', ?, 0, ?)
        """,
        (
            chunk_id,
            str(WORKSPACE_ID),
            generation_id,
            version_id,
            page_id,
            locator_id,
            chunk_payload,
            len(passage),
            TIMESTAMP,
            len(passage),
        ),
    )
    connection.execute(
        """
        INSERT INTO embeddings
          (chunk_id, workspace_id, index_generation_id, embedding_model_id,
           dimensions, dtype, is_unit_normalized, vector_ciphertext, created_at)
        VALUES (?, ?, ?, ?, 2, 'float32', 1, ?, ?)
        """,
        (
            chunk_id,
            str(WORKSPACE_ID),
            generation_id,
            str(EMBEDDING_MODEL_ID),
            vector_payload,
            TIMESTAMP,
        ),
    )
    connection.execute(
        """
        INSERT INTO qa_scope_versions
          (qa_request_id, workspace_id, document_id, document_version_id, included_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(QA_REQUEST_ID), str(WORKSPACE_ID), str(DOCUMENT_ID), version_id, TIMESTAMP),
    )
    connection.commit()


def _persist_retrieval(
    connection: sqlite3.Connection,
    *,
    evidence_count: int,
) -> RetrievalRegistration:
    repository = SQLiteRetrievalRepository(
        connection,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    scope = repository.resolve_scope(
        QaRetrievalRequest(QA_REQUEST_ID, WORKSPACE_ID, QUESTION)
    )
    candidates = repository.load_candidates(scope)
    evidence: tuple[RetrievalEvidenceRegistration, ...] = ()
    if evidence_count:
        candidate = candidates.candidates[0]
        item = Evidence(
            EVIDENCE_ID,
            WORKSPACE_ID,
            RETRIEVAL_RUN_ID,
            candidate.generation.document_id,
            candidate.generation.document_version_id,
            candidate.source_locator.page_number,
            EvidenceRank(1),
            SimilarityScore(0.8),
            candidate.chunk_id,
            candidate.source_locator.id,
        )
        evidence = (
            RetrievalEvidenceRegistration(
                item,
                candidate.generation.index_generation_id,
                candidate.document_order,
                candidate.source_locator,
                candidate.generation.document_display_name,
                candidate.generation.version_number,
                candidate.passage,
                NOW,
            ),
        )
    registration = RetrievalRegistration(
        RETRIEVAL_RUN_ID,
        scope,
        RetrievalConfiguration(5, SimilarityScore(0.0)),
        len(candidates.candidates),
        evidence,
        NOW,
    )
    repository.add(registration)
    return registration


def _policy() -> EvidencePolicyIdentity:
    record = ResolvedModelRecord(
        CHAT_MODEL_ID,
        "synthetic-chat",
        "synthetic-chat-id",
        "1",
        ModelCapability.CHAT,
        "synthetic",
    )
    return EvidencePolicyIdentity(
        "evidence-policy-v2",
        "evidence-relations-v2",
        LocalModelStatus(record, ModelReadiness.READY, "synthetic-cpu"),
    )


def _completion(
    connection: sqlite3.Connection,
    state: EvidenceSufficiency,
) -> ChatCompletionRegistration:
    evidence_count = 0 if state is EvidenceSufficiency.INSUFFICIENT else 1
    retrieval = _persist_retrieval(connection, evidence_count=evidence_count)
    assessments: tuple[EvidenceAssessment, ...] = ()
    related: tuple[RetrievalEvidenceRegistration, ...] = ()
    counts = EvidenceRelationCounts(0, 0, 0, 0)
    if state is EvidenceSufficiency.SUFFICIENT:
        assessments = (EvidenceAssessment(EVIDENCE_ID, EvidenceRank(1), EvidenceRelation.SUPPORTS),)
        counts = EvidenceRelationCounts(1, 0, 0, 0)
    elif state is EvidenceSufficiency.RELATED_BUT_INSUFFICIENT:
        assessments = (
            EvidenceAssessment(EVIDENCE_ID, EvidenceRank(1), EvidenceRelation.RELATED_ONLY),
        )
        related = retrieval.evidence
        counts = EvidenceRelationCounts(0, 1, 0, 0)
    sufficiency = EvidenceSufficiencyResult(
        retrieval,
        state,
        _policy(),
        assessments,
        related,
        AggregateEvidenceCoverage.READY,
        counts,
        False,
    )
    repository = SQLiteChatRepository(
        connection,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    target = repository.get_target(WORKSPACE_ID, QA_REQUEST_ID)
    assert target is not None
    citations: tuple[ChatCitationRegistration, ...] = ()
    if state is not EvidenceSufficiency.INSUFFICIENT:
        citations = (
            ChatCitationRegistration(
                CitationId("e0000000-0000-4000-8000-000000000001"),
                WORKSPACE_ID,
                EVIDENCE_ID,
                ANSWER_ID,
                1,
                NOW,
            ),
        )
    return ChatCompletionRegistration(
        target,
        sufficiency,
        ChatAssistantMessage(ANSWER_ID, WORKSPACE_ID, CHAT_ID, 2, ANSWER, NOW),
        ChatResponseContractVersion("chat-answer-v1"),
        CHAT_MODEL_ID if state is EvidenceSufficiency.SUFFICIENT else None,
        citations,
        NOW,
        ChatActivityEvent(
            ActivityEventId("f0000000-0000-4000-8000-000000000001"),
            WORKSPACE_ID,
            QA_REQUEST_ID,
            ChatActivityType.QA_COMPLETED,
            (
                ChatActivityResult.SUCCESS
                if state is EvidenceSufficiency.SUFFICIENT
                else ChatActivityResult.WARNING
            ),
            NOW,
        ),
    )


def test_target_reconstructs_exact_question_scope_and_codec_context(
    database: sqlite3.Connection,
) -> None:
    codec = _RecordingCodec()
    repository = SQLiteChatRepository(database, codec)

    target = repository.get_target(WORKSPACE_ID, QA_REQUEST_ID)

    assert target is not None
    assert target.question == QUESTION
    assert target.chat_id == CHAT_ID
    assert target.state is QaRequestState.DRAFT
    assert tuple(item.document_id for item in target.scope_versions) == (DOCUMENT_ID,)
    assert codec.decoded == [
        SensitivePayloadContext(
            WORKSPACE_ID,
            str(QUESTION_ID),
            "chat-message-content",
            1,
        )
    ]


@pytest.mark.parametrize(
    "state",
    [
        EvidenceSufficiency.SUFFICIENT,
        EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
        EvidenceSufficiency.INSUFFICIENT,
    ],
)
def test_all_terminal_completion_graphs_round_trip_exactly(
    database: sqlite3.Connection,
    state: EvidenceSufficiency,
) -> None:
    registration = _completion(database, state)
    codec = _RecordingCodec()
    repository = SQLiteChatRepository(database, codec)

    repository.add(registration)
    restored = repository.get_completed(WORKSPACE_ID, QA_REQUEST_ID)

    assert restored is not None
    assert restored.evidence_state is state
    assert restored.answer.content == ANSWER
    assert restored.snapshot == registration.snapshot
    assert restored.retrieval == registration.sufficiency.retrieval
    assert restored.response_contract_version == registration.response_contract_version
    assert restored.chat_model_id == registration.chat_model_id
    assert restored.citations == registration.citations
    assert restored.completed_at == NOW
    assert {
        (item.owner_id, item.purpose) for item in codec.encoded + codec.decoded
    } >= {(str(ANSWER_ID), "chat-message-content")}
    assert database.in_transaction is True
    assert "Exact synthetic" not in repr(restored)


def test_snapshot_relations_use_existing_evidence_rank_without_second_order(
    database: sqlite3.Connection,
) -> None:
    registration = _completion(database, EvidenceSufficiency.SUFFICIENT)
    repository = SQLiteChatRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    repository.add(registration)

    row = database.execute(
        """
        SELECT r.evidence_item_id, r.relation, e.rank
        FROM qa_verifier_snapshot_relations AS r
        JOIN evidence_items AS e ON e.id = r.evidence_item_id
        """
    ).fetchone()

    assert tuple(row) == (str(EVIDENCE_ID), "SUPPORTS", 1)


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM qa_verifier_snapshot_relations",
        "UPDATE qa_verifier_snapshots SET supports_count = 0",
        "UPDATE qa_verifier_snapshot_relations SET relation = 'IRRELEVANT'",
        "UPDATE citations SET ordinal = 2",
        "UPDATE chat_messages SET content_ciphertext = x'ff' WHERE role = 'ASSISTANT'",
    ],
    ids=[
        "missing-relation",
        "count-mismatch",
        "relation-mismatch",
        "citation-gap",
        "corrupt-answer",
    ],
)
def test_corrupt_or_partial_terminal_graph_fails_closed_without_sensitive_values(
    database: sqlite3.Connection,
    statement: str,
) -> None:
    registration = _completion(database, EvidenceSufficiency.SUFFICIENT)
    repository = SQLiteChatRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    repository.add(registration)
    database.execute(statement)

    with pytest.raises(ChatPersistenceError) as raised:
        repository.get_completed(WORKSPACE_ID, QA_REQUEST_ID)

    message = str(raised.value)
    assert "Exact synthetic" not in message
    assert str(EVIDENCE_ID) not in message
    assert "ff" not in message


def test_cross_workspace_lookup_fails_before_protected_decode(
    database: sqlite3.Connection,
) -> None:
    codec = _RecordingCodec()
    repository = SQLiteChatRepository(database, codec)

    with pytest.raises(ChatPersistenceError, match="ownership is invalid"):
        repository.get_target(OTHER_WORKSPACE_ID, QA_REQUEST_ID)

    assert codec.decoded == []


def test_duplicate_completion_is_rejected_without_replacement(
    database: sqlite3.Connection,
) -> None:
    registration = _completion(database, EvidenceSufficiency.SUFFICIENT)
    repository = SQLiteChatRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    repository.add(registration)

    with pytest.raises(ChatPersistenceError):
        repository.add(registration)

    assert database.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE role = 'ASSISTANT'"
    ).fetchone()[0] == 1
    assert database.execute("SELECT COUNT(*) FROM citations").fetchone()[0] == 1


def test_compatible_completed_graph_reconstruction_is_idempotent_and_read_only(
    database: sqlite3.Connection,
) -> None:
    registration = _completion(database, EvidenceSufficiency.SUFFICIENT)
    repository = SQLiteChatRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    repository.add(registration)
    before = database.total_changes

    first = repository.get_completed(WORKSPACE_ID, QA_REQUEST_ID)
    second = repository.get_completed(WORKSPACE_ID, QA_REQUEST_ID)

    assert first == second
    assert database.total_changes == before
    assert database.in_transaction is True


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("workspace_id", str(OTHER_WORKSPACE_ID)),
        ("retrieval_run_id", "30000000-0000-4000-8000-000000000099"),
    ],
    ids=["cross-workspace-relation", "cross-retrieval-relation"],
)
def test_snapshot_relation_owner_substitution_fails_closed(
    database: sqlite3.Connection,
    column: str,
    value: str,
) -> None:
    registration = _completion(database, EvidenceSufficiency.SUFFICIENT)
    repository = SQLiteChatRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    repository.add(registration)
    database.commit()
    database.execute("PRAGMA foreign_keys = OFF")
    database.execute("BEGIN")
    database.execute(
        f"UPDATE qa_verifier_snapshot_relations SET {column} = ?",
        (value,),
    )

    with pytest.raises(ChatPersistenceError) as raised:
        repository.get_completed(WORKSPACE_ID, QA_REQUEST_ID)

    assert value not in str(raised.value)


def test_failure_state_is_staged_only_without_completion_artifacts(
    database: sqlite3.Connection,
) -> None:
    repository = SQLiteChatRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    target = repository.get_target(WORKSPACE_ID, QA_REQUEST_ID)
    assert target is not None
    update = ChatFailureUpdate(
        target,
        QaRequestState.FAILED,
        ChatFailureCode.GENERATION_FAILED,
        NOW,
        ChatActivityEvent(
            ActivityEventId("f0000000-0000-4000-8000-000000000002"),
            WORKSPACE_ID,
            QA_REQUEST_ID,
            ChatActivityType.QA_FAILED,
            ChatActivityResult.FAILED,
            NOW,
        ),
    )

    repository.record_failure(update)

    row = database.execute(
        "SELECT state, error_code, error_metadata_json FROM qa_requests"
    ).fetchone()
    assert tuple(row) == ("FAILED", "GENERATION_FAILED", None)
    assert repository.get_completed(WORKSPACE_ID, QA_REQUEST_ID) is None


def test_stale_target_and_conflicting_retrieval_are_rejected(
    database: sqlite3.Connection,
) -> None:
    registration = _completion(database, EvidenceSufficiency.SUFFICIENT)
    repository = SQLiteChatRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    database.execute("UPDATE qa_requests SET state = 'SEARCHING'")

    with pytest.raises(ChatPersistenceError, match="target is stale"):
        repository.add(registration)

    database.execute("UPDATE qa_requests SET state = 'DRAFT'")
    database.execute("UPDATE retrieval_runs SET top_k = 4")
    with pytest.raises(ChatPersistenceError) as raised:
        repository.add(registration)
    assert ANSWER not in str(raised.value)


def test_failed_add_leaves_partial_rows_for_caller_rollback(
    database: sqlite3.Connection,
) -> None:
    registration = _completion(database, EvidenceSufficiency.SUFFICIENT)
    repository = SQLiteChatRepository(database, InsecureDevelopmentOnlyPayloadCodec())
    database.execute(
        """
        INSERT INTO activity_events
          (id, workspace_id, category, event_type, result_status,
           summary_key, created_at)
        VALUES (?, ?, 'CHAT', 'SYNTHETIC', 'SUCCESS', 'synthetic', ?)
        """,
        (str(registration.activity.id), str(WORKSPACE_ID), TIMESTAMP),
    )

    with pytest.raises(ChatPersistenceError):
        repository.add(registration)

    assert database.in_transaction is True
    database.rollback()
    assert database.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE role = 'ASSISTANT'"
    ).fetchone()[0] == 0


@pytest.mark.parametrize(
    "retry_state,error_code",
    [
        ("FAILED", "GENERATION_FAILED"),
        ("CANCELLED", "CANCELLED"),
    ],
)
def test_failed_or_cancelled_request_can_stage_a_clean_retry_completion(
    database: sqlite3.Connection,
    retry_state: str,
    error_code: str,
) -> None:
    database.execute(
        """
        UPDATE qa_requests
        SET state = ?, error_code = ?, completed_at = ?
        WHERE id = ?
        """,
        (retry_state, error_code, TIMESTAMP, str(QA_REQUEST_ID)),
    )
    registration = _completion(database, EvidenceSufficiency.SUFFICIENT)
    repository = SQLiteChatRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )

    repository.add(registration)

    row = database.execute(
        """
        SELECT state, answer_message_id, error_code
        FROM qa_requests WHERE id = ?
        """,
        (str(QA_REQUEST_ID),),
    ).fetchone()
    assert tuple(row) == ("COMPLETED", str(ANSWER_ID), None)


def test_retry_state_without_failure_metadata_fails_closed(
    database: sqlite3.Connection,
) -> None:
    database.execute(
        "UPDATE qa_requests SET state = 'FAILED' WHERE id = ?",
        (str(QA_REQUEST_ID),),
    )
    registration = _completion(database, EvidenceSufficiency.SUFFICIENT)
    repository = SQLiteChatRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )

    with pytest.raises(ChatPersistenceError, match="target is not clean"):
        repository.add(registration)
