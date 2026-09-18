"""Synthetic SQLite/RAG/verifier/CHAT vertical-slice tests."""

import json
import sqlite3
import struct
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.application.embeddings import EmbedQuery
from lexlocal.application.ports.chat import ChatCancelled, ChatError
from lexlocal.application.ports.embeddings import EmbeddingCompatibility
from lexlocal.application.ports.local_models import (
    ChatInferenceProfile,
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
    ResolvedModelRecord,
)
from lexlocal.application.ports.security import (
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.bootstrap.chat import compose_chat_application
from lexlocal.bootstrap.embeddings import EmbeddingApplicationComposition
from lexlocal.bootstrap.evidence_sufficiency import (
    compose_evidence_sufficiency_application,
)
from lexlocal.bootstrap.foundry import LocalModelComposition
from lexlocal.bootstrap.retrieval import compose_retrieval_application
from lexlocal.bootstrap.settings import AppSettings
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
from lexlocal.domain.retrieval import EvidenceSufficiency
from lexlocal.infrastructure.persistence.migration_runner import run_migrations
from lexlocal.infrastructure.persistence.migrations import (
    default_migrations_dir,
    discover_migrations,
)
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.persistence.sqlite_embedding_repository import (
    SQLiteEmbeddingRepository,
)
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyPayloadCodec,
)

NOW = datetime(2026, 9, 17, 11, 0, tzinfo=UTC)
TIMESTAMP = "2026-09-17T11:00:00.000Z"
WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
OTHER_WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000002")
CHAT_ID = ChatId("11000000-0000-4000-8000-000000000001")
QUESTION_ID = ChatMessageId("12000000-0000-4000-8000-000000000001")
QA_REQUEST_ID = QaRequestId("20000000-0000-4000-8000-000000000001")
EMBEDDING_MODEL_ID = LocalModelId("40000000-0000-4000-8000-000000000001")
CHAT_MODEL_ID = LocalModelId("41000000-0000-4000-8000-000000000001")
DOCUMENT_ID = DocumentId("50000000-0000-4000-8000-000000000001")
QUESTION = " Exact anonymous question Ω\n"


class _EmbeddingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._status = LocalModelStatus(
            ResolvedModelRecord(
                EMBEDDING_MODEL_ID,
                "synthetic-embedding",
                "synthetic-embedding-id",
                "1",
                ModelCapability.EMBEDDING,
                "synthetic",
                2,
            ),
            ModelReadiness.READY,
            "synthetic-cpu",
        )

    @property
    def status(self) -> LocalModelStatus:
        return self._status

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        exact = tuple(texts)
        self.calls.append(exact)
        return tuple((0.6, 0.8) for _ in exact)


class _ChatProvider:
    def __init__(
        self,
        relation: str,
        *,
        fail_generation: bool = False,
    ) -> None:
        self.relation = relation
        self.fail_generation = fail_generation
        self.prompts: list[str] = []
        self.profiles: list[ChatInferenceProfile | None] = []
        self._status = LocalModelStatus(
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

    @property
    def status(self) -> LocalModelStatus:
        return self._status

    def generate(
        self,
        prompt: str,
        *,
        profile: ChatInferenceProfile | None = None,
    ) -> str:
        self.prompts.append(prompt)
        self.profiles.append(profile)
        task = json.loads(prompt)["task"]
        if task == "classify-evidence-relations":
            return json.dumps({"assessments": [{"evidence": "E1", "relation": self.relation}]})
        if self.fail_generation:
            raise RuntimeError("private synthetic provider detail")
        return json.dumps(
            {
                "answer": "Exact anonymous grounded answer Ω",
                "citations": ["E1"],
            }
        )


class _IdFactory:
    def __init__(self, prefix: str, identifier_type: type) -> None:
        self.prefix = prefix
        self.identifier_type = identifier_type
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.identifier_type(f"{self.prefix}000000-0000-4000-8000-{self.calls:012d}")


class _Cancellation:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise ChatCancelled("private cancellation detail")


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment="test",
        log_level="INFO",
        data_dir=tmp_path,
        security_provider="insecure-development-only",
    )


def _encode_text(value: str, owner_id: str, purpose: str) -> bytes:
    codec = InsecureDevelopmentOnlyPayloadCodec()
    context = SensitivePayloadContext(WORKSPACE_ID, owner_id, purpose, 1)
    return codec.encode(
        value.encode("utf-8"),
        context=context,
        key_reference=WorkspaceKeyReference(WORKSPACE_ID, 1),
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
    vector_context, vector_key = SQLiteEmbeddingRepository._security_values(
        ChunkId(chunk_id),
        compatibility,
    )
    vector_payload = (
        InsecureDevelopmentOnlyPayloadCodec()
        .encode(
            struct.pack("<2f", 0.6, 0.8),
            context=vector_context,
            key_reference=vector_key,
        )
        .payload
    )
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
    connection.execute(
        """
        INSERT INTO chat_messages
          (id, workspace_id, chat_id, role, sequence_number,
           content_ciphertext, created_at)
        VALUES (?, ?, ?, 'USER', 1, ?, ?)
        """,
        (
            str(QUESTION_ID),
            str(WORKSPACE_ID),
            str(CHAT_ID),
            _encode_text(QUESTION, str(QUESTION_ID), "chat-message-content"),
            TIMESTAMP,
        ),
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
                str(DOCUMENT_ID),
                "document-display-name",
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
    connection.execute(
        """
        INSERT INTO document_pages
          (id, workspace_id, document_version_id, page_number, state,
           extraction_method, text_ciphertext, character_count, created_at, updated_at)
        VALUES (?, ?, ?, 1, 'READY', 'NATIVE', ?, ?, ?, ?)
        """,
        (
            page_id,
            str(WORKSPACE_ID),
            version_id,
            _encode_text(passage, page_id, "document-page-text"),
            len(passage),
            TIMESTAMP,
            TIMESTAMP,
        ),
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
            _encode_text(passage, chunk_id, "index-chunk-text"),
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


def _database(tmp_path: Path) -> tuple[SQLiteConnectionFactory, ActiveWorkspaceScope]:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    connection = factory.create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
    _insert_source_graph(connection)
    connection.close()
    scope = ActiveWorkspaceScope()
    scope.select(WORKSPACE_ID)
    return factory, scope


def _compose(
    tmp_path: Path,
    relation: str,
    *,
    cancellation: _Cancellation | None = None,
    fail_generation: bool = False,
    substitute_workspace: bool = False,
):
    factory, scope = _database(tmp_path)
    if substitute_workspace:
        scope.select(OTHER_WORKSPACE_ID)
    embedding = _EmbeddingProvider()
    chat = _ChatProvider(relation, fail_generation=fail_generation)
    local_models = LocalModelComposition(
        chat,
        embedding,
        chat.status,
        embedding.status,
        lambda: None,
    )
    embeddings = EmbeddingApplicationComposition(
        object(),  # type: ignore[arg-type]
        EmbedQuery(scope, embedding),
    )
    retrieval_ids = _IdFactory("d0", RetrievalRunId)
    evidence_ids = _IdFactory("e0", EvidenceItemId)
    retrieval = compose_retrieval_application(
        _settings(tmp_path),
        factory,
        scope,
        embeddings,
        retrieval_run_id_factory=retrieval_ids,
        evidence_item_id_factory=evidence_ids,
        clock=lambda: NOW,
    )
    sufficiency = compose_evidence_sufficiency_application(local_models)
    answer_ids = _IdFactory("f0", ChatMessageId)
    citation_ids = _IdFactory("f1", CitationId)
    activity_ids = _IdFactory("f2", ActivityEventId)
    composition = compose_chat_application(
        _settings(tmp_path),
        factory,
        scope,
        local_models,
        retrieval,
        sufficiency,
        cancellation=_Cancellation() if cancellation is None else cancellation,
        answer_message_id_factory=answer_ids,
        citation_id_factory=citation_ids,
        activity_event_id_factory=activity_ids,
        clock=lambda: NOW,
    )
    return (
        factory,
        composition,
        chat,
        embedding,
        retrieval_ids,
        evidence_ids,
        answer_ids,
        citation_ids,
        activity_ids,
        scope,
    )


@pytest.mark.parametrize(
    ("relation", "expected_state", "provider_tasks", "citation_count"),
    [
        pytest.param(
            "SUPPORTS",
            EvidenceSufficiency.SUFFICIENT,
            ("classify-evidence-relations", "answer-from-supplied-evidence"),
            1,
            id="grounded",
        ),
        pytest.param(
            "RELATED_ONLY",
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
            ("classify-evidence-relations",),
            1,
            id="related",
        ),
        pytest.param(
            "IRRELEVANT",
            EvidenceSufficiency.INSUFFICIENT,
            ("classify-evidence-relations",),
            0,
            id="insufficient",
        ),
    ],
)
def test_real_synthetic_vertical_slice_persists_each_terminal_outcome(
    tmp_path: Path,
    relation: str,
    expected_state: EvidenceSufficiency,
    provider_tasks: tuple[str, ...],
    citation_count: int,
) -> None:
    factory, composition, chat, embedding, *_ = _compose(tmp_path, relation)

    result = composition.complete_chat(QA_REQUEST_ID)

    assert result.reused is False
    assert result.graph.evidence_state is expected_state
    assert len(result.graph.citations) == citation_count
    assert embedding.calls == [(QUESTION,)]
    assert tuple(json.loads(prompt)["task"] for prompt in chat.prompts) == provider_tasks
    assert all(prompt is not result.graph.answer.content for prompt in chat.prompts)
    if expected_state is EvidenceSufficiency.SUFFICIENT:
        assert result.graph.answer.content == "Exact anonymous grounded answer Ω"
        assert result.graph.citations[0].evidence_item_id == (
            result.graph.retrieval.evidence[0].evidence.id
        )
    connection = factory.create()
    try:
        qa_row = connection.execute(
            "SELECT state, answer_message_id FROM qa_requests WHERE id = ?",
            (str(QA_REQUEST_ID),),
        ).fetchone()
        assert qa_row["state"] in ("COMPLETED", "COMPLETED_INSUFFICIENT")
        assert qa_row["answer_message_id"] == str(result.graph.answer.id)
        assert connection.execute("SELECT COUNT(*) FROM qa_verifier_snapshots").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM citations").fetchone()[0] == citation_count
        raw_answer = connection.execute(
            "SELECT content_ciphertext FROM chat_messages WHERE id = ?",
            (str(result.graph.answer.id),),
        ).fetchone()[0]
        assert b'"citations"' not in raw_answer
        assert b'"task"' not in raw_answer
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(retrieval_runs)")}
        assert "query_vector" not in columns
        assert "query_embedding" not in columns
    finally:
        connection.close()


def test_compatible_repeat_reuses_terminal_graph_without_work_or_new_ids(
    tmp_path: Path,
) -> None:
    (
        _,
        composition,
        chat,
        embedding,
        retrieval_ids,
        evidence_ids,
        answer_ids,
        citation_ids,
        activity_ids,
        _,
    ) = _compose(tmp_path, "SUPPORTS")
    first = composition.complete_chat(QA_REQUEST_ID)
    calls = (
        len(chat.prompts),
        len(embedding.calls),
        retrieval_ids.calls,
        evidence_ids.calls,
        answer_ids.calls,
        citation_ids.calls,
        activity_ids.calls,
    )

    second = composition.complete_chat(QA_REQUEST_ID)

    assert second.reused is True
    assert second.graph == first.graph
    assert (
        len(chat.prompts),
        len(embedding.calls),
        retrieval_ids.calls,
        evidence_ids.calls,
        answer_ids.calls,
        citation_ids.calls,
        activity_ids.calls,
    ) == calls


@pytest.mark.parametrize("failure", ["provider", "vector", "write", "cancel"])
def test_failures_leave_no_partial_completed_assistant_graph(
    tmp_path: Path,
    failure: str,
) -> None:
    cancellation = _Cancellation(failure == "cancel")
    factory, composition, chat, _, *_ = _compose(
        tmp_path,
        "SUPPORTS",
        cancellation=cancellation,
        fail_generation=failure == "provider",
    )
    connection = factory.create()
    try:
        if failure == "vector":
            connection.execute("UPDATE embeddings SET vector_ciphertext = x'00'")
            connection.commit()
        elif failure == "write":
            connection.execute(
                """
                CREATE TRIGGER reject_synthetic_answer
                BEFORE INSERT ON chat_messages
                WHEN NEW.role = 'ASSISTANT'
                BEGIN
                  SELECT RAISE(ABORT, 'synthetic write failure');
                END
                """
            )
            connection.commit()
    finally:
        connection.close()

    with pytest.raises((ChatError, ChatCancelled)) as captured:
        composition.complete_chat(QA_REQUEST_ID)

    assert captured.value.__cause__ is None
    assert QUESTION not in str(captured.value)
    connection = factory.create()
    try:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE role = 'ASSISTANT'"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM citations").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM qa_verifier_snapshots").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM activity_events WHERE event_type = 'QA_COMPLETED'"
            ).fetchone()[0]
            == 0
        )
    finally:
        connection.close()
    if failure == "cancel":
        assert chat.prompts == []


def test_workspace_substitution_fails_before_model_or_persistence(tmp_path: Path) -> None:
    factory, composition, chat, embedding, *_ = _compose(
        tmp_path,
        "SUPPORTS",
        substitute_workspace=True,
    )

    with pytest.raises(ChatError):
        composition.complete_chat(QA_REQUEST_ID)

    assert chat.prompts == []
    assert embedding.calls == []
    connection = factory.create()
    try:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE role = 'ASSISTANT'"
            ).fetchone()[0]
            == 0
        )
    finally:
        connection.close()
