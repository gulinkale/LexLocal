"""End-to-end tests for the anonymous synthetic QA retrieval slice."""

import sqlite3
import struct
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.application.embeddings import EmbedQuery
from lexlocal.application.ports.embeddings import EmbeddingCompatibility
from lexlocal.application.ports.local_models import (
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
    ResolvedModelRecord,
)
from lexlocal.application.ports.retrieval import (
    IncompatibleRetrievalScope,
    NoEligibleIndex,
    RetrievalError,
    RetrievalIntegrityError,
)
from lexlocal.application.ports.security import (
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.bootstrap.embeddings import EmbeddingApplicationComposition
from lexlocal.bootstrap.retrieval import (
    RetrievalApplicationComposition,
    compose_retrieval_application,
)
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import (
    ChunkId,
    DocumentId,
    EvidenceItemId,
    IndexGenerationId,
    LocalModelId,
    QaRequestId,
    RetrievalRunId,
    WorkspaceId,
)
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

NOW = datetime(2026, 9, 8, 8, 30, 45, 678000, tzinfo=UTC)
TIMESTAMP = "2026-09-08T08:30:45.678Z"
WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
OTHER_WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000002")
QA_REQUEST_ID = QaRequestId("20000000-0000-4000-8000-000000000001")
MODEL_ID = LocalModelId("40000000-0000-4000-8000-000000000001")
ADDITIONAL_QA_IDS = tuple(
    QaRequestId(f"20000000-0000-4000-8000-{number:012d}")
    for number in range(2, 5)
)


class _Provider:
    def __init__(self, vector: tuple[float, float] = (1.0, 0.0)) -> None:
        self._vector = vector
        self.calls: list[tuple[str, ...]] = []
        self._status = LocalModelStatus(
            ResolvedModelRecord(
                MODEL_ID,
                "qwen3-embedding-0.6b",
                "synthetic-model",
                "1",
                ModelCapability.EMBEDDING,
                "synthetic-local",
                2,
            ),
            ModelReadiness.READY,
            "synthetic-execution",
        )

    @property
    def status(self) -> LocalModelStatus:
        return self._status

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        exact = tuple(texts)
        self.calls.append(exact)
        return tuple(self._vector for _ in exact)


class _RunIdFactory:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> RetrievalRunId:
        self.calls += 1
        return RetrievalRunId(
            f"d0000000-0000-4000-8000-{self.calls:012d}"
        )


class _EvidenceIdFactory:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> EvidenceItemId:
        self.calls += 1
        return EvidenceItemId(
            f"e0000000-0000-4000-8000-{self.calls:012d}"
        )


def _settings(
    tmp_path: Path,
    *,
    top_k: int = 5,
    min_similarity: float = 0.0,
) -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment="test",
        log_level="INFO",
        data_dir=tmp_path,
        security_provider="insecure-development-only",
        retrieval_top_k=top_k,
        retrieval_min_similarity=min_similarity,
    )


def _document_id(number: int) -> str:
    return f"50000000-0000-4000-8000-{number:012d}"


def _version_id(number: int) -> str:
    return f"60000000-0000-4000-8000-{number:012d}"


def _generation_id(number: int) -> str:
    return f"80000000-0000-4000-8000-{number:012d}"


def _chunk_id(number: int) -> str:
    return f"b0000000-0000-4000-8000-{number:012d}"


def _encode_text(value: str, owner_id: str, purpose: str) -> bytes:
    codec = InsecureDevelopmentOnlyPayloadCodec()
    context = SensitivePayloadContext(WORKSPACE_ID, owner_id, purpose, 1)
    return codec.encode(
        value.encode("utf-8"),
        context=context,
        key_reference=WorkspaceKeyReference(WORKSPACE_ID, 1),
    ).payload


def _encode_vector(chunk_id: str, values: tuple[float, float]) -> bytes:
    compatibility = EmbeddingCompatibility(
        WORKSPACE_ID,
        IndexGenerationId(_generation_id(int(chunk_id[-12:]))),
        MODEL_ID,
        "chunk-v1",
        "normalize-v1",
        2,
    )
    context, key_reference = SQLiteEmbeddingRepository._security_values(
        ChunkId(chunk_id),
        compatibility,
    )
    return InsecureDevelopmentOnlyPayloadCodec().encode(
        struct.pack("<2f", *values),
        context=context,
        key_reference=key_reference,
    ).payload


def _insert_retrieval_source_graph(
    connection: sqlite3.Connection,
    *,
    document_count: int,
) -> None:
    connection.execute("BEGIN")
    connection.execute(
        """
        INSERT INTO workspaces (
            id, name_ciphertext, name_lookup_fingerprint,
            state, created_at, updated_at
        ) VALUES (?, x'01', x'02', 'ACTIVE', ?, ?)
        """,
        (str(WORKSPACE_ID), TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO local_models (
            id, purpose, provider, requested_alias,
            resolved_model_id, dimensions, created_at
        ) VALUES (?, 'EMBEDDING', 'synthetic', 'fixture',
                  'synthetic-model', 2, ?)
        """,
        (str(MODEL_ID), TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO chats (id, workspace_id, state, created_at, updated_at)
        VALUES ('synthetic-chat', ?, 'ACTIVE', ?, ?)
        """,
        (str(WORKSPACE_ID), TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO chat_messages (
            id, workspace_id, chat_id, role,
            sequence_number, content_ciphertext, created_at
        ) VALUES ('synthetic-question', ?, 'synthetic-chat',
                  'USER', 1, x'01', ?)
        """,
        (str(WORKSPACE_ID), TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO qa_requests (
            id, workspace_id, chat_id, question_message_id,
            state, created_at
        ) VALUES (?, ?, 'synthetic-chat', 'synthetic-question',
                  'SEARCHING', ?)
        """,
        (str(QA_REQUEST_ID), str(WORKSPACE_ID), TIMESTAMP),
    )
    for number in range(1, document_count + 1):
        _insert_document_graph(connection, number)
        connection.execute(
            """
            INSERT INTO qa_scope_versions (
                qa_request_id, workspace_id, document_id,
                document_version_id, included_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(QA_REQUEST_ID),
                str(WORKSPACE_ID),
                _document_id(number),
                _version_id(number),
                TIMESTAMP,
            ),
        )
    connection.commit()


def _insert_document_graph(connection: sqlite3.Connection, number: int) -> None:
    document_id = _document_id(number)
    version_id = _version_id(number)
    job_id = f"70000000-0000-4000-8000-{number:012d}"
    generation_id = _generation_id(number)
    page_id = f"90000000-0000-4000-8000-{number:012d}"
    locator_id = f"a0000000-0000-4000-8000-{number:012d}"
    chunk_id = _chunk_id(number)
    display_name = f"Anonymous document {number}"
    passage = f"Synthetic passage {number}"
    connection.execute(
        """
        INSERT INTO documents (
            id, workspace_id, display_name_ciphertext,
            state, created_at, updated_at
        ) VALUES (?, ?, ?, 'ACTIVE', ?, ?)
        """,
        (
            document_id,
            str(WORKSPACE_ID),
            _encode_text(display_name, document_id, "document-display-name"),
            TIMESTAMP,
            TIMESTAMP,
        ),
    )
    connection.execute(
        """
        INSERT INTO document_versions (
            id, workspace_id, document_id, version_number,
            historical_filename_ciphertext, page_count, state,
            created_at, activated_at
        ) VALUES (?, ?, ?, ?, x'01', 1, 'ACTIVE', ?, ?)
        """,
        (version_id, str(WORKSPACE_ID), document_id, number, TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO document_processing_jobs (
            id, workspace_id, document_version_id, attempt_number,
            state, stage, created_at, completed_at
        ) VALUES (?, ?, ?, 1, 'READY', 'CHUNKING', ?, ?)
        """,
        (job_id, str(WORKSPACE_ID), version_id, TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO document_pages (
            id, workspace_id, document_version_id, page_number,
            state, extraction_method, text_ciphertext, character_count,
            created_at, updated_at
        ) VALUES (?, ?, ?, 1, 'READY', 'NATIVE', ?, ?, ?, ?)
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
        INSERT INTO source_locators (
            id, workspace_id, document_version_id, page_id,
            locator_kind, page_number, locator_version, created_at
        ) VALUES (?, ?, ?, ?, 'PAGE', 1, 1, ?)
        """,
        (locator_id, str(WORKSPACE_ID), version_id, page_id, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO index_generations (
            id, workspace_id, document_version_id, processing_job_id,
            state, embedding_model_id, chunking_profile_version,
            normalization_profile_version, embedding_dimensions,
            vector_dtype, chunk_count, created_at, activated_at
        ) VALUES (?, ?, ?, ?, 'ACTIVE', ?, 'chunk-v1',
                  'normalize-v1', 2, 'float32', 1, ?, ?)
        """,
        (
            generation_id,
            str(WORKSPACE_ID),
            version_id,
            job_id,
            str(MODEL_ID),
            TIMESTAMP,
            TIMESTAMP,
        ),
    )
    connection.execute(
        """
        INSERT INTO chunks (
            id, workspace_id, index_generation_id, document_version_id,
            page_id, source_locator_id, document_order, page_order,
            text_ciphertext, normalized_text_fingerprint, character_count,
            token_count_estimate, extraction_method, created_at,
            source_start_offset, source_end_offset
        ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, x'01', ?, NULL,
                  'NATIVE', ?, 0, ?)
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
    vector = (1.0, 0.0) if number == 1 else (0.6, 0.8)
    connection.execute(
        """
        INSERT INTO embeddings (
            chunk_id, workspace_id, index_generation_id,
            embedding_model_id, dimensions, dtype,
            is_unit_normalized, vector_ciphertext, created_at
        ) VALUES (?, ?, ?, ?, 2, 'float32', 1, ?, ?)
        """,
        (
            chunk_id,
            str(WORKSPACE_ID),
            generation_id,
            str(MODEL_ID),
            _encode_vector(chunk_id, vector),
            TIMESTAMP,
        ),
    )


def _database(tmp_path: Path) -> tuple[SQLiteConnectionFactory, ActiveWorkspaceScope]:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    connection = factory.create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
    _insert_retrieval_source_graph(connection, document_count=2)
    connection.close()
    scope = ActiveWorkspaceScope()
    scope.select(WORKSPACE_ID)
    return factory, scope


def _add_qa_request(
    factory: SQLiteConnectionFactory,
    qa_request_id: QaRequestId,
    sequence_number: int,
) -> None:
    connection = factory.create()
    try:
        connection.execute("BEGIN")
        question_id = f"synthetic-question-{sequence_number}"
        connection.execute(
            """
            INSERT INTO chat_messages (
                id, workspace_id, chat_id, role,
                sequence_number, content_ciphertext, created_at
            ) VALUES (?, ?, 'synthetic-chat', 'USER', ?, x'01', ?)
            """,
            (question_id, str(WORKSPACE_ID), sequence_number, TIMESTAMP),
        )
        connection.execute(
            """
            INSERT INTO qa_requests (
                id, workspace_id, chat_id, question_message_id,
                state, created_at
            ) VALUES (?, ?, 'synthetic-chat', ?, 'SEARCHING', ?)
            """,
            (str(qa_request_id), str(WORKSPACE_ID), question_id, TIMESTAMP),
        )
        for number in (1, 2):
            connection.execute(
                """
                INSERT INTO qa_scope_versions (
                    qa_request_id, workspace_id, document_id,
                    document_version_id, included_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(qa_request_id),
                    str(WORKSPACE_ID),
                    _document_id(number),
                    _version_id(number),
                    TIMESTAMP,
                ),
            )
        connection.commit()
    finally:
        connection.close()


def _embedding_composition(
    scope: ActiveWorkspaceScope,
    provider: _Provider,
) -> EmbeddingApplicationComposition:
    return EmbeddingApplicationComposition(
        object(),  # type: ignore[arg-type]
        EmbedQuery(scope, provider),
    )


def _compose(
    tmp_path: Path,
    factory: SQLiteConnectionFactory,
    scope: ActiveWorkspaceScope,
    provider: _Provider,
    run_ids: _RunIdFactory,
    evidence_ids: _EvidenceIdFactory,
    *,
    top_k: int = 5,
    min_similarity: float = 0.0,
) -> RetrievalApplicationComposition:
    return compose_retrieval_application(
        _settings(tmp_path, top_k=top_k, min_similarity=min_similarity),
        factory,
        scope,
        _embedding_composition(scope, provider),
        retrieval_run_id_factory=run_ids,
        evidence_item_id_factory=evidence_ids,
        clock=lambda: NOW,
    )


def test_workspace_scope_persists_ranked_evidence_and_retry_reuses_it(
    tmp_path: Path,
) -> None:
    factory, scope = _database(tmp_path)
    provider = _Provider()
    run_ids = _RunIdFactory()
    evidence_ids = _EvidenceIdFactory()
    composition = _compose(
        tmp_path,
        factory,
        scope,
        provider,
        run_ids,
        evidence_ids,
    )
    query = " Exact anonymous query Ω\n"

    prepared = composition.prepare_retrieval(
        QA_REQUEST_ID,
        query,
        composition.configuration,
    )

    assert provider.calls == [(query,)]
    assert prepared.candidate_count == 2
    assert tuple(item.evidence.rank.value for item in prepared.evidence) == (1, 2)
    assert tuple(item.evidence.document_id for item in prepared.evidence) == (
        DocumentId(_document_id(1)),
        DocumentId(_document_id(2)),
    )
    assert tuple(item.excerpt for item in prepared.evidence) == (
        "Synthetic passage 1",
        "Synthetic passage 2",
    )
    assert tuple(item.source_locator.id for item in prepared.evidence) == tuple(
        item.evidence.source_locator_id for item in prepared.evidence
    )

    with composition.unit_of_work_factory() as unit_of_work:
        staged = composition.stage_retrieval(prepared, unit_of_work.retrieval)
        assert staged.reused is False
        unit_of_work.commit()

    connection = factory.create()
    try:
        run = connection.execute("SELECT * FROM retrieval_runs").fetchone()
        assert run["top_k"] == 5
        assert run["min_similarity"] == 0.0
        assert run["candidate_count"] == 2
        generations = connection.execute(
            "SELECT index_generation_id FROM retrieval_run_generations "
            "ORDER BY index_generation_id"
        ).fetchall()
        assert tuple(row["index_generation_id"] for row in generations) == (
            _generation_id(1),
            _generation_id(2),
        )
        assert connection.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 2
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(retrieval_runs)")
        }
        assert "query_vector" not in columns
        assert "query_embedding" not in columns
    finally:
        connection.close()

    retried = composition.prepare_retrieval(
        QA_REQUEST_ID,
        query,
        composition.configuration,
    )
    with composition.unit_of_work_factory() as unit_of_work:
        reused = composition.stage_retrieval(retried, unit_of_work.retrieval)
        unit_of_work.commit()

    assert provider.calls == [(query,)]
    assert retried.retrieval_run_id == prepared.retrieval_run_id
    assert tuple(item.evidence.id for item in retried.evidence) == tuple(
        item.evidence.id for item in prepared.evidence
    )
    assert reused.reused is True
    assert run_ids.calls == 1
    assert evidence_ids.calls == 2


def test_narrowed_scope_and_threshold_empty_runs_persist_exact_intent(
    tmp_path: Path,
) -> None:
    factory, scope = _database(tmp_path)
    narrowed_qa, empty_qa = ADDITIONAL_QA_IDS[:2]
    _add_qa_request(factory, narrowed_qa, 2)
    _add_qa_request(factory, empty_qa, 3)
    run_ids = _RunIdFactory()
    evidence_ids = _EvidenceIdFactory()
    narrowed_provider = _Provider()
    narrowed = _compose(
        tmp_path,
        factory,
        scope,
        narrowed_provider,
        run_ids,
        evidence_ids,
        top_k=1,
    )

    narrowed_registration = narrowed.prepare_retrieval(
        narrowed_qa,
        "narrowed synthetic query",
        narrowed.configuration,
        (DocumentId(_document_id(2)),),
    )
    with narrowed.unit_of_work_factory() as unit_of_work:
        narrowed.stage_retrieval(
            narrowed_registration,
            unit_of_work.retrieval,
        )
        unit_of_work.commit()

    assert narrowed_provider.calls == [("narrowed synthetic query",)]
    assert narrowed_registration.scope.generation_ids[0] == IndexGenerationId(
        _generation_id(2)
    )
    assert len(narrowed_registration.evidence) == 1
    assert narrowed_registration.evidence[0].evidence.document_id == DocumentId(
        _document_id(2)
    )

    empty_provider = _Provider((0.0, 1.0))
    empty = _compose(
        tmp_path,
        factory,
        scope,
        empty_provider,
        run_ids,
        evidence_ids,
        min_similarity=0.9,
    )
    empty_registration = empty.prepare_retrieval(
        empty_qa,
        "threshold empty synthetic query",
        empty.configuration,
    )
    with empty.unit_of_work_factory() as unit_of_work:
        empty.stage_retrieval(empty_registration, unit_of_work.retrieval)
        unit_of_work.commit()

    assert empty_registration.retrieval_run_id != narrowed_registration.retrieval_run_id
    assert empty_registration.candidate_count == 2
    assert empty_registration.evidence == ()
    connection = factory.create()
    try:
        row = connection.execute(
            "SELECT top_k, min_similarity, candidate_count FROM retrieval_runs "
            "WHERE qa_request_id = ?",
            (str(empty_qa),),
        ).fetchone()
        assert tuple(row) == (5, 0.9, 2)
        assert connection.execute(
            "SELECT COUNT(*) FROM retrieval_run_generations "
            "WHERE retrieval_run_id = ?",
            (str(empty_registration.retrieval_run_id),),
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM evidence_items WHERE retrieval_run_id = ?",
            (str(empty_registration.retrieval_run_id),),
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_caller_rollback_leaves_no_graph_and_retry_can_use_fresh_ids(
    tmp_path: Path,
) -> None:
    factory, scope = _database(tmp_path)
    rollback_qa = ADDITIONAL_QA_IDS[2]
    _add_qa_request(factory, rollback_qa, 4)
    provider = _Provider()
    run_ids = _RunIdFactory()
    evidence_ids = _EvidenceIdFactory()
    composition = _compose(
        tmp_path,
        factory,
        scope,
        provider,
        run_ids,
        evidence_ids,
    )

    rolled_back = composition.prepare_retrieval(
        rollback_qa,
        "rollback synthetic query",
        composition.configuration,
    )
    with composition.unit_of_work_factory() as unit_of_work:
        composition.stage_retrieval(rolled_back, unit_of_work.retrieval)

    connection = factory.create()
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM retrieval_runs WHERE qa_request_id = ?",
            (str(rollback_qa),),
        ).fetchone()[0] == 0
    finally:
        connection.close()

    retried = composition.prepare_retrieval(
        rollback_qa,
        "rollback synthetic query",
        composition.configuration,
    )
    with composition.unit_of_work_factory() as unit_of_work:
        composition.stage_retrieval(retried, unit_of_work.retrieval)
        unit_of_work.commit()

    assert retried.retrieval_run_id != rolled_back.retrieval_run_id
    assert run_ids.calls == 2
    assert provider.calls == [
        ("rollback synthetic query",),
        ("rollback synthetic query",),
    ]


@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [
        ("workspace", RetrievalIntegrityError),
        ("no-index", NoEligibleIndex),
        ("incompatible", IncompatibleRetrievalScope),
        ("corrupt-vector", RetrievalIntegrityError),
    ],
)
def test_scope_substitution_or_integrity_failure_precedes_query_and_persistence(
    tmp_path: Path,
    failure: str,
    expected_error: type[RetrievalError],
) -> None:
    factory, scope = _database(tmp_path)
    if failure == "workspace":
        scope.select(OTHER_WORKSPACE_ID)
    else:
        connection = factory.create()
        try:
            if failure == "no-index":
                connection.execute("UPDATE index_generations SET state = 'ARCHIVED'")
            elif failure == "incompatible":
                connection.execute(
                    "UPDATE index_generations SET chunking_profile_version = "
                    "'different-profile' WHERE id = ?",
                    (_generation_id(2),),
                )
            else:
                connection.execute(
                    "UPDATE embeddings SET vector_ciphertext = x'00' WHERE chunk_id = ?",
                    (_chunk_id(1),),
                )
            connection.commit()
        finally:
            connection.close()
    provider = _Provider()
    composition = _compose(
        tmp_path,
        factory,
        scope,
        provider,
        _RunIdFactory(),
        _EvidenceIdFactory(),
    )
    query = "private synthetic failure query"

    with pytest.raises(expected_error) as raised:
        composition.prepare_retrieval(
            QA_REQUEST_ID,
            query,
            composition.configuration,
        )

    message = str(raised.value)
    assert query not in message
    assert "Synthetic passage" not in message
    assert _chunk_id(1) not in message
    assert provider.calls == []
    connection = factory.create()
    try:
        assert connection.execute("SELECT COUNT(*) FROM retrieval_runs").fetchone()[0] == 0
    finally:
        connection.close()
