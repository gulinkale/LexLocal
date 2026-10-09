"""Transaction-boundary tests for SQLite CHAT persistence."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.application.ports.chat import (
    ChatActivityEvent,
    ChatActivityResult,
    ChatActivityType,
    ChatFailureCode,
    ChatFailureUpdate,
    ChatIntakeRegistration,
    ChatPersistenceError,
    QaRequestState,
)
from lexlocal.application.ports.security import (
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
from lexlocal.domain.identifiers import (
    ActivityEventId,
    ChatId,
    ChatMessageId,
    DocumentId,
    DocumentVersionId,
    IndexGenerationId,
    LocalModelId,
    ProcessingJobId,
    QaRequestId,
    WorkspaceId,
)
from lexlocal.domain.processing import IndexGeneration, IndexGenerationState
from lexlocal.infrastructure.persistence.migration_runner import run_migrations
from lexlocal.infrastructure.persistence.migrations import (
    default_migrations_dir,
    discover_migrations,
)
from lexlocal.infrastructure.persistence.sqlite_chat_repository import (
    SQLiteChatRepository,
)
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyPayloadCodec,
)

NOW = datetime(2026, 9, 16, 11, 0, 0, tzinfo=UTC)
TIMESTAMP = "2026-09-16T11:00:00.000Z"
WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000011")
CHAT_ID = ChatId("11000000-0000-4000-8000-000000000011")
QUESTION_ID = ChatMessageId("12000000-0000-4000-8000-000000000011")
QA_REQUEST_ID = QaRequestId("20000000-0000-4000-8000-000000000011")
INTAKE_CHAT_ID = ChatId("11000000-0000-4000-8000-000000000012")
INTAKE_QUESTION_ID = ChatMessageId("12000000-0000-4000-8000-000000000012")
INTAKE_QA_REQUEST_ID = QaRequestId("20000000-0000-4000-8000-000000000012")
DOCUMENT_ID = DocumentId("50000000-0000-4000-8000-000000000011")
VERSION_ID = DocumentVersionId("60000000-0000-4000-8000-000000000011")
JOB_ID = ProcessingJobId("70000000-0000-4000-8000-000000000011")
GENERATION_ID = IndexGenerationId("80000000-0000-4000-8000-000000000011")
MODEL_ID = LocalModelId("30000000-0000-4000-8000-000000000011")


def _database(tmp_path: Path) -> tuple[SQLiteConnectionFactory, SQLiteChatRepository]:
    factory = SQLiteConnectionFactory(tmp_path / "chat-transactions.db")
    connection = factory.create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
    codec = InsecureDevelopmentOnlyPayloadCodec()
    context = SensitivePayloadContext(
        WORKSPACE_ID,
        str(QUESTION_ID),
        "chat-message-content",
        1,
    )
    question_payload = codec.encode(
        b"Synthetic transaction question",
        context=context,
        key_reference=WorkspaceKeyReference(WORKSPACE_ID, 1),
    ).payload
    connection.executescript(
        f"""
        INSERT INTO workspaces
          (id, name_ciphertext, name_lookup_fingerprint, state, created_at, updated_at)
        VALUES ('{WORKSPACE_ID}', x'01', x'02', 'ACTIVE', '{TIMESTAMP}', '{TIMESTAMP}');
        INSERT INTO chats
          (id, workspace_id, state, created_at, updated_at)
        VALUES ('{CHAT_ID}', '{WORKSPACE_ID}', 'ACTIVE', '{TIMESTAMP}', '{TIMESTAMP}');
        INSERT INTO chat_messages
          (id, workspace_id, chat_id, role, sequence_number, content_ciphertext, created_at)
        VALUES ('{QUESTION_ID}', '{WORKSPACE_ID}', '{CHAT_ID}', 'USER', 1,
                x'{question_payload.hex()}', '{TIMESTAMP}');
        INSERT INTO qa_requests
          (id, workspace_id, chat_id, question_message_id, state, created_at)
        VALUES ('{QA_REQUEST_ID}', '{WORKSPACE_ID}', '{CHAT_ID}', '{QUESTION_ID}',
                'DRAFT', '{TIMESTAMP}');
        INSERT INTO documents
          (id, workspace_id, display_name_ciphertext, state, created_at, updated_at)
        VALUES ('50000000-0000-4000-8000-000000000011', '{WORKSPACE_ID}', x'03',
                'ACTIVE', '{TIMESTAMP}', '{TIMESTAMP}');
        INSERT INTO document_versions
          (id, workspace_id, document_id, version_number,
           historical_filename_ciphertext, state, created_at)
        VALUES ('60000000-0000-4000-8000-000000000011', '{WORKSPACE_ID}',
                '50000000-0000-4000-8000-000000000011', 1, x'04',
                'ACTIVE', '{TIMESTAMP}');
        INSERT INTO local_models
          (id, purpose, provider, requested_alias, resolved_model_id,
           model_version, dimensions, created_at)
        VALUES ('{MODEL_ID}', 'EMBEDDING', 'synthetic', 'synthetic-embedding',
                'synthetic-embedding-id', '1', 2, '{TIMESTAMP}');
        INSERT INTO document_processing_jobs
          (id, workspace_id, document_version_id, attempt_number,
           state, stage, created_at, completed_at)
        VALUES ('{JOB_ID}', '{WORKSPACE_ID}', '{VERSION_ID}', 1,
                'READY', 'CHUNKING', '{TIMESTAMP}', '{TIMESTAMP}');
        INSERT INTO index_generations
          (id, workspace_id, document_version_id, processing_job_id, state,
           embedding_model_id, chunking_profile_version,
           normalization_profile_version, embedding_dimensions,
           vector_dtype, chunk_count, created_at, activated_at)
        VALUES ('{GENERATION_ID}', '{WORKSPACE_ID}', '{VERSION_ID}', '{JOB_ID}',
                'ACTIVE', '{MODEL_ID}', 'chunk-v1', 'normalize-v1', 2,
                'float32', 0, '{TIMESTAMP}', '{TIMESTAMP}');
        INSERT INTO qa_scope_versions
          (qa_request_id, workspace_id, document_id, document_version_id, included_at)
        VALUES ('{QA_REQUEST_ID}', '{WORKSPACE_ID}',
                '50000000-0000-4000-8000-000000000011',
                '60000000-0000-4000-8000-000000000011', '{TIMESTAMP}');
        """
    )
    return factory, SQLiteChatRepository(connection, codec)


def _failure_update(repository: SQLiteChatRepository) -> ChatFailureUpdate:
    target = repository.get_target(WORKSPACE_ID, QA_REQUEST_ID)
    assert target is not None
    return ChatFailureUpdate(
        target,
        QaRequestState.FAILED,
        ChatFailureCode.GENERATION_FAILED,
        NOW,
        ChatActivityEvent(
            ActivityEventId("f0000000-0000-4000-8000-000000000011"),
            WORKSPACE_ID,
            QA_REQUEST_ID,
            ChatActivityType.QA_FAILED,
            ChatActivityResult.FAILED,
            NOW,
        ),
    )


def _intake() -> ChatIntakeRegistration:
    return ChatIntakeRegistration(
        WORKSPACE_ID,
        INTAKE_CHAT_ID,
        INTAKE_QUESTION_ID,
        INTAKE_QA_REQUEST_ID,
        DOCUMENT_ID,
        VERSION_ID,
        IndexGeneration(
            GENERATION_ID,
            WORKSPACE_ID,
            VERSION_ID,
            JOB_ID,
            MODEL_ID,
            "chunk-v1",
            "normalize-v1",
            2,
            IndexGenerationState.ACTIVE,
        ),
        " Exact synthetic intake question ",
        NOW,
    )


def test_repository_requires_and_leaves_caller_transaction_active(
    tmp_path: Path,
) -> None:
    _, repository = _database(tmp_path)
    connection = repository._connection

    with pytest.raises(ChatPersistenceError, match="transaction is not active"):
        repository.get_target(WORKSPACE_ID, QA_REQUEST_ID)

    connection.execute("BEGIN")
    assert repository.get_target(WORKSPACE_ID, QA_REQUEST_ID) is not None
    assert connection.in_transaction is True
    connection.rollback()
    connection.close()


def test_separate_failure_update_obeys_caller_commit_and_rollback(
    tmp_path: Path,
) -> None:
    factory, repository = _database(tmp_path)
    connection = repository._connection
    connection.execute("BEGIN")
    update = _failure_update(repository)
    repository.record_failure(update)
    assert connection.in_transaction is True
    connection.rollback()
    assert connection.execute("SELECT state FROM qa_requests").fetchone()[0] == "DRAFT"

    connection.execute("BEGIN")
    repository.record_failure(_failure_update(repository))
    connection.commit()
    connection.close()

    verification = factory.create()
    row = verification.execute(
        "SELECT state, error_code, error_metadata_json FROM qa_requests"
    ).fetchone()
    assert tuple(row) == ("FAILED", "GENERATION_FAILED", None)
    assert verification.execute("SELECT COUNT(*) FROM activity_events").fetchone()[0] == 1
    verification.close()


def test_intake_graph_obeys_caller_commit_and_rollback(tmp_path: Path) -> None:
    factory, repository = _database(tmp_path)
    connection = repository._connection

    connection.execute("BEGIN")
    assert repository.add_intake(_intake()) is False
    assert connection.in_transaction is True
    connection.rollback()
    assert connection.execute(
        "SELECT COUNT(*) FROM qa_requests WHERE id = ?",
        (str(INTAKE_QA_REQUEST_ID),),
    ).fetchone()[0] == 0

    connection.execute("BEGIN")
    assert repository.add_intake(_intake()) is False
    connection.commit()
    connection.close()

    verification = factory.create()
    assert verification.execute(
        "SELECT COUNT(*) FROM chats WHERE id = ?",
        (str(INTAKE_CHAT_ID),),
    ).fetchone()[0] == 1
    assert verification.execute(
        "SELECT COUNT(*) FROM qa_requests WHERE id = ?",
        (str(INTAKE_QA_REQUEST_ID),),
    ).fetchone()[0] == 1
    verification.close()
