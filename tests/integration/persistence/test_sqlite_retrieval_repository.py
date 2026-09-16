"""Integration tests for exact SQLite QA retrieval persistence."""

import sqlite3
import struct
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.application.ports.embeddings import (
    ChunkEmbedding,
    EmbeddingCompatibility,
    NormalizedEmbeddingVector,
)
from lexlocal.application.ports.retrieval import (
    IncompatibleRetrievalScope,
    NoEligibleIndex,
    QaRetrievalRequest,
    RetrievalConfiguration,
    RetrievalEvidenceRegistration,
    RetrievalIntegrityError,
    RetrievalPersistenceError,
    RetrievalRegistration,
)
from lexlocal.application.ports.security import (
    EncodedSensitivePayload,
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
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
from lexlocal.domain.processing import ProcessingJobState
from lexlocal.domain.retrieval import Evidence, EvidenceRank, SimilarityScore
from lexlocal.infrastructure.persistence.migration_runner import run_migrations
from lexlocal.infrastructure.persistence.migrations import (
    default_migrations_dir,
    discover_migrations,
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

NOW = datetime(2026, 9, 8, 8, 30, 45, 678000, tzinfo=UTC)
TIMESTAMP = "2026-09-08T08:30:45.678Z"
WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
OTHER_WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000002")
QA_REQUEST_ID = QaRequestId("20000000-0000-4000-8000-000000000001")
RETRIEVAL_RUN_ID = RetrievalRunId("30000000-0000-4000-8000-000000000001")
MODEL_ID = LocalModelId("40000000-0000-4000-8000-000000000001")


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


class _FailingSecondEvidenceCodec(_RecordingCodec):
    def encode(
        self,
        plaintext: bytes,
        *,
        context: SensitivePayloadContext,
        key_reference: WorkspaceKeyReference,
    ) -> EncodedSensitivePayload:
        if (
            context.owner_id == "c0000000-0000-4000-8000-000000000002"
            and context.purpose == "retrieval-evidence-excerpt"
        ):
            raise RuntimeError("Synthetic passage 2")
        return super().encode(
            plaintext,
            context=context,
            key_reference=key_reference,
        )


@pytest.fixture
def database(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = SQLiteConnectionFactory(tmp_path / "lexlocal.db").create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
    _insert_retrieval_source_graph(connection, document_count=2)
    connection.execute("BEGIN")
    yield connection
    if connection.in_transaction:
        connection.rollback()
    connection.close()


def _document_id(number: int) -> str:
    return f"50000000-0000-4000-8000-{number:012d}"


def _version_id(number: int) -> str:
    return f"60000000-0000-4000-8000-{number:012d}"


def _generation_id(number: int) -> str:
    return f"80000000-0000-4000-8000-{number:012d}"


def _chunk_id(number: int) -> str:
    return f"b0000000-0000-4000-8000-{number:012d}"


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
    document_payload = _encode_text(
        display_name,
        workspace_id=WORKSPACE_ID,
        owner_id=document_id,
        purpose="document-display-name",
    )
    page_payload = _encode_text(
        passage,
        workspace_id=WORKSPACE_ID,
        owner_id=page_id,
        purpose="document-page-text",
    )
    chunk_payload = _encode_text(
        passage,
        workspace_id=WORKSPACE_ID,
        owner_id=chunk_id,
        purpose="index-chunk-text",
    )
    compatibility = EmbeddingCompatibility(
        WORKSPACE_ID,
        IndexGenerationId(generation_id),
        MODEL_ID,
        "chunk-v1",
        "normalize-v1",
        2,
    )
    vector = NormalizedEmbeddingVector((0.6, 0.8))
    embedding = ChunkEmbedding(ChunkId(chunk_id), compatibility, vector, NOW)
    vector_context, vector_key = SQLiteEmbeddingRepository._security_values(
        embedding.chunk_id,
        compatibility,
    )
    vector_payload = InsecureDevelopmentOnlyPayloadCodec().encode(
        struct.pack("<2f", *vector.values),
        context=vector_context,
        key_reference=vector_key,
    ).payload
    connection.execute(
        """
        INSERT INTO documents (
            id, workspace_id, display_name_ciphertext,
            state, created_at, updated_at
        ) VALUES (?, ?, ?, 'ACTIVE', ?, ?)
        """,
        (document_id, str(WORKSPACE_ID), document_payload, TIMESTAMP, TIMESTAMP),
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
            page_payload,
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
            chunk_payload,
            len(passage),
            TIMESTAMP,
            len(passage),
        ),
    )
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
            vector_payload,
            TIMESTAMP,
        ),
    )
    connection.execute(
        """
        INSERT INTO qa_scope_versions (
            qa_request_id, workspace_id, document_id,
            document_version_id, included_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (str(QA_REQUEST_ID), str(WORKSPACE_ID), document_id, version_id, TIMESTAMP),
    )


def _request(*document_numbers: int) -> QaRetrievalRequest:
    document_ids = (
        tuple(DocumentId(_document_id(number)) for number in document_numbers)
        if document_numbers
        else None
    )
    return QaRetrievalRequest(
        QA_REQUEST_ID,
        WORKSPACE_ID,
        " Exact anonymous query Ω\n",
        document_ids,
    )


def _registration(
    repository: SQLiteRetrievalRepository,
    request: QaRetrievalRequest,
    *,
    evidence_count: int = 1,
) -> RetrievalRegistration:
    scope = repository.resolve_scope(request)
    candidates = repository.load_candidates(scope)
    snapshots: list[RetrievalEvidenceRegistration] = []
    for rank, candidate in enumerate(candidates.candidates[:evidence_count], start=1):
        evidence = Evidence(
            EvidenceItemId(f"c0000000-0000-4000-8000-{rank:012d}"),
            WORKSPACE_ID,
            RETRIEVAL_RUN_ID,
            candidate.generation.document_id,
            candidate.generation.document_version_id,
            candidate.source_locator.page_number,
            EvidenceRank(rank),
            SimilarityScore(0.9 - (rank - 1) * 0.1),
            candidate.chunk_id,
            candidate.source_locator.id,
        )
        snapshots.append(
            RetrievalEvidenceRegistration(
                evidence,
                candidate.generation.index_generation_id,
                candidate.document_order,
                candidate.source_locator,
                candidate.generation.document_display_name,
                candidate.generation.version_number,
                candidate.passage,
                NOW,
            )
        )
    return RetrievalRegistration(
        RETRIEVAL_RUN_ID,
        scope,
        RetrievalConfiguration(5, SimilarityScore(0.25)),
        len(candidates.candidates),
        tuple(snapshots),
        NOW,
    )


def test_resolves_authoritative_full_and_narrowed_active_scope(
    database: sqlite3.Connection,
) -> None:
    repository = SQLiteRetrievalRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )

    full = repository.resolve_scope(_request())
    narrowed = repository.resolve_scope(_request(2))

    assert tuple(item.document_id for item in full.generations) == (
        DocumentId(_document_id(1)),
        DocumentId(_document_id(2)),
    )
    assert narrowed.generation_ids == (IndexGenerationId(_generation_id(2)),)
    assert narrowed.representative.document_display_name == "Anonymous document 2"
    assert all(
        item.coverage_state is ProcessingJobState.READY for item in full.generations
    )


def test_scope_reconstructs_exact_ready_and_warning_coverage(
    database: sqlite3.Connection,
) -> None:
    repository = SQLiteRetrievalRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    database.execute(
        "UPDATE document_processing_jobs SET state = 'READY_WITH_WARNINGS' WHERE id = ?",
        ("70000000-0000-4000-8000-000000000002",),
    )

    scope = repository.resolve_scope(_request())

    assert tuple(item.coverage_state for item in scope.generations) == (
        ProcessingJobState.READY,
        ProcessingJobState.READY_WITH_WARNINGS,
    )


def test_scope_rejects_unknown_narrowing_and_cross_workspace_owner(
    database: sqlite3.Connection,
) -> None:
    repository = SQLiteRetrievalRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )

    with pytest.raises(RetrievalIntegrityError, match="narrowing is invalid"):
        repository.resolve_scope(
            QaRetrievalRequest(
                QA_REQUEST_ID,
                WORKSPACE_ID,
                "query",
                (DocumentId("50000000-0000-4000-8000-000000000099"),),
            )
        )
    with pytest.raises(RetrievalIntegrityError, match="owner is invalid"):
        repository.resolve_scope(
            QaRetrievalRequest(QA_REQUEST_ID, OTHER_WORKSPACE_ID, "query")
        )


def test_scope_distinguishes_no_active_index_from_partial_or_incompatible_state(
    database: sqlite3.Connection,
) -> None:
    repository = SQLiteRetrievalRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    database.execute("UPDATE index_generations SET state = 'ARCHIVED'")
    with pytest.raises(NoEligibleIndex, match="no eligible ACTIVE index"):
        repository.resolve_scope(_request())

    database.execute("UPDATE index_generations SET state = 'ACTIVE' WHERE id = ?", (_generation_id(1),))
    with pytest.raises(RetrievalIntegrityError, match="generation state is invalid"):
        repository.resolve_scope(_request())


@pytest.mark.parametrize(
    ("statement", "error_type"),
    [
        (
            "UPDATE document_processing_jobs SET state = 'FAILED' "
            "WHERE id = '70000000-0000-4000-8000-000000000001'",
            RetrievalIntegrityError,
        ),
        (
            "UPDATE index_generations SET chunking_profile_version = 'chunk-v2' "
            "WHERE id = '80000000-0000-4000-8000-000000000002'",
            IncompatibleRetrievalScope,
        ),
    ],
    ids=["invalid-processing-owner-state", "incompatible-cohort"],
)
def test_scope_fails_closed_for_invalid_generation_graphs(
    database: sqlite3.Connection,
    statement: str,
    error_type: type[Exception],
) -> None:
    repository = SQLiteRetrievalRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    database.execute(statement)

    with pytest.raises(error_type):
        repository.resolve_scope(_request())


@pytest.mark.parametrize(
    ("statement", "requires_corruption_mode"),
    [
        (
            "DELETE FROM document_processing_jobs "
            "WHERE id = '70000000-0000-4000-8000-000000000001'",
            True,
        ),
        (
            "UPDATE document_processing_jobs "
            "SET workspace_id = '10000000-0000-4000-8000-000000000002' "
            "WHERE id = '70000000-0000-4000-8000-000000000001'",
            True,
        ),
        (
            "UPDATE index_generations "
            "SET processing_job_id = '70000000-0000-4000-8000-000000000002' "
            "WHERE id = '80000000-0000-4000-8000-000000000001'",
            False,
        ),
        (
            "UPDATE document_processing_jobs SET state = 'PROCESSING' "
            "WHERE id = '70000000-0000-4000-8000-000000000001'",
            False,
        ),
        (
            "UPDATE document_processing_jobs SET stage = 'EXTRACTION' "
            "WHERE id = '70000000-0000-4000-8000-000000000001'",
            False,
        ),
    ],
    ids=[
        "missing-job",
        "cross-workspace-job",
        "cross-version-job",
        "nonterminal-job",
        "wrong-job-stage",
    ],
)
def test_scope_rejects_invalid_coverage_relationship_before_handoff(
    database: sqlite3.Connection,
    statement: str,
    requires_corruption_mode: bool,
) -> None:
    repository = SQLiteRetrievalRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    if requires_corruption_mode:
        database.rollback()
        database.execute("PRAGMA foreign_keys = OFF")
        database.execute("BEGIN")
    database.execute(statement)

    with pytest.raises(RetrievalIntegrityError) as raised:
        repository.resolve_scope(_request())

    message = str(raised.value)
    assert "70000000" not in message
    assert "80000000" not in message
    assert "10000000" not in message


def test_load_candidates_decodes_exact_ordered_vectors_text_and_provenance(
    database: sqlite3.Connection,
) -> None:
    codec = _RecordingCodec()
    repository = SQLiteRetrievalRepository(database, codec)
    scope = repository.resolve_scope(_request())

    candidates = repository.load_candidates(scope)

    assert tuple(item.passage for item in candidates.candidates) == (
        "Synthetic passage 1",
        "Synthetic passage 2",
    )
    assert candidates.candidates[0].embedding.vector.values == pytest.approx((0.6, 0.8))
    assert candidates.candidates[1].embedding.vector.values == pytest.approx((0.6, 0.8))
    assert tuple(item.source_locator.page_number.value for item in candidates.candidates) == (
        1,
        1,
    )
    assert {context.purpose for context in codec.decoded} >= {
        "document-display-name",
        "document-page-text",
        "index-chunk-text",
        "chunk-embedding-vector",
    }


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM embeddings WHERE chunk_id = 'b0000000-0000-4000-8000-000000000001'",
        "UPDATE embeddings SET vector_ciphertext = x'00' WHERE chunk_id = 'b0000000-0000-4000-8000-000000000001'",
        "UPDATE embeddings SET dimensions = 3 WHERE chunk_id = 'b0000000-0000-4000-8000-000000000001'",
        "UPDATE embeddings SET created_at = 'invalid' WHERE chunk_id = 'b0000000-0000-4000-8000-000000000001'",
        "UPDATE chunks SET created_at = 'invalid' WHERE id = 'b0000000-0000-4000-8000-000000000001'",
        "UPDATE document_pages SET text_ciphertext = x'ff' WHERE id = '90000000-0000-4000-8000-000000000001'",
        "UPDATE document_pages SET character_count = 999 WHERE id = '90000000-0000-4000-8000-000000000001'",
        "UPDATE chunks SET normalized_text_fingerprint = x'' WHERE id = 'b0000000-0000-4000-8000-000000000001'",
        "UPDATE embeddings SET index_generation_id = '80000000-0000-4000-8000-000000000001' WHERE chunk_id = 'b0000000-0000-4000-8000-000000000002'",
        "UPDATE chunks SET source_locator_id = 'a0000000-0000-4000-8000-000000000002' WHERE id = 'b0000000-0000-4000-8000-000000000001'",
    ],
    ids=[
        "missing-vector",
        "corrupt-vector",
        "dimension-mismatch",
        "invalid-timestamp",
        "invalid-chunk-timestamp",
        "corrupt-page-text",
        "page-character-count",
        "empty-chunk-fingerprint",
        "extra-cross-generation-vector",
        "locator-substitution",
    ],
)
def test_candidate_integrity_failures_are_sanitized(
    database: sqlite3.Connection,
    statement: str,
) -> None:
    repository = SQLiteRetrievalRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    scope = repository.resolve_scope(_request())
    database.execute(statement)

    with pytest.raises(RetrievalIntegrityError) as raised:
        repository.load_candidates(scope)

    message = str(raised.value)
    assert "Synthetic passage" not in message
    assert _chunk_id(1) not in message
    assert _generation_id(1) not in message


def test_new_run_generation_and_evidence_round_trip_exactly(
    database: sqlite3.Connection,
) -> None:
    codec = _RecordingCodec()
    repository = SQLiteRetrievalRepository(database, codec)
    registration = _registration(repository, _request(1))

    repository.add(registration)
    restored = repository.get_for_qa_request(WORKSPACE_ID, QA_REQUEST_ID)

    assert restored == registration
    run = database.execute("SELECT * FROM retrieval_runs").fetchone()
    assert run["purpose"] == "QA"
    assert run["analysis_generation_section_id"] is None
    assert run["top_k"] == 5
    assert run["min_similarity"] == 0.25
    assert run["candidate_count"] == 1
    assert database.execute(
        "SELECT index_generation_id FROM retrieval_run_generations"
    ).fetchone()["index_generation_id"] == _generation_id(1)
    assert {context.purpose for context in codec.encoded} == {
        "retrieval-query",
        "retrieval-evidence-document-name",
        "retrieval-evidence-excerpt",
    }
    assert "Exact anonymous query" not in repr(restored)
    assert "Synthetic passage" not in repr(restored)


def test_generation_snapshot_constraints_reject_duplicate_or_cross_scope_rows(
    database: sqlite3.Connection,
) -> None:
    repository = SQLiteRetrievalRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    registration = _registration(repository, _request(1))
    repository.add(registration)
    parameters = (
        str(RETRIEVAL_RUN_ID),
        str(WORKSPACE_ID),
        _generation_id(1),
    )

    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            "INSERT INTO retrieval_run_generations VALUES (?, ?, ?)",
            parameters,
        )
    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            "UPDATE retrieval_run_generations SET workspace_id = ?",
            (str(OTHER_WORKSPACE_ID),),
        )


def test_successful_zero_evidence_run_still_snapshots_every_generation(
    database: sqlite3.Connection,
) -> None:
    repository = SQLiteRetrievalRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    registration = _registration(repository, _request(1, 2), evidence_count=0)

    repository.add(registration)
    restored = repository.get_for_qa_request(WORKSPACE_ID, QA_REQUEST_ID)

    assert restored is not None
    assert restored.evidence == ()
    assert restored.candidate_count == 2
    assert database.execute(
        "SELECT COUNT(*) FROM retrieval_run_generations"
    ).fetchone()[0] == 2
    assert database.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0] == 0


def test_same_qa_second_run_is_rejected_without_replacement(
    database: sqlite3.Connection,
) -> None:
    repository = SQLiteRetrievalRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    registration = _registration(repository, _request(1))
    repository.add(registration)

    with pytest.raises(RetrievalPersistenceError, match="already exists"):
        repository.add(registration)

    assert database.execute("SELECT COUNT(*) FROM retrieval_runs").fetchone()[0] == 1


def test_cross_workspace_run_lookup_fails_before_sensitive_payload_decode(
    database: sqlite3.Connection,
) -> None:
    codec = _RecordingCodec()
    repository = SQLiteRetrievalRepository(database, codec)
    repository.add(_registration(repository, _request(1)))
    codec.decoded.clear()

    with pytest.raises(RetrievalPersistenceError, match="owner mapping is invalid"):
        repository.get_for_qa_request(OTHER_WORKSPACE_ID, QA_REQUEST_ID)

    assert codec.decoded == []


def test_ambiguous_same_qa_runs_fail_closed(database: sqlite3.Connection) -> None:
    repository = SQLiteRetrievalRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    registration = _registration(repository, _request(1))
    repository.add(registration)
    database.execute(
        """
        INSERT INTO retrieval_runs (
            id, workspace_id, purpose, qa_request_id, query_ciphertext,
            embedding_model_id, top_k, candidate_count,
            retrieval_policy_version, created_at, min_similarity
        ) SELECT '30000000-0000-4000-8000-000000000002', workspace_id,
                 purpose, qa_request_id, query_ciphertext, embedding_model_id,
                 top_k, candidate_count, retrieval_policy_version,
                 created_at, min_similarity
          FROM retrieval_runs WHERE id = ?
        """,
        (str(RETRIEVAL_RUN_ID),),
    )

    with pytest.raises(RetrievalPersistenceError, match="state is ambiguous"):
        repository.get_for_qa_request(WORKSPACE_ID, QA_REQUEST_ID)


def test_corrupt_persisted_configuration_or_evidence_fails_closed(
    database: sqlite3.Connection,
) -> None:
    repository = SQLiteRetrievalRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    repository.add(_registration(repository, _request(1)))
    database.execute("UPDATE evidence_items SET excerpt_ciphertext = x'ff'")

    with pytest.raises(RetrievalPersistenceError) as raised:
        repository.get_for_qa_request(WORKSPACE_ID, QA_REQUEST_ID)

    assert "Synthetic passage" not in str(raised.value)
    assert "ff" not in str(raised.value)


def test_full_scope_registration_round_trips_without_inventing_a_narrowing(
    database: sqlite3.Connection,
) -> None:
    repository = SQLiteRetrievalRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    registration = _registration(repository, _request(), evidence_count=2)

    repository.add(registration)

    assert repository.get_for_qa_request(WORKSPACE_ID, QA_REQUEST_ID) == registration


@pytest.mark.parametrize(
    "mutation",
    ["candidate-count", "evidence-excerpt"],
)
def test_add_revalidates_registration_against_the_current_candidate_graph(
    database: sqlite3.Connection,
    mutation: str,
) -> None:
    repository = SQLiteRetrievalRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    registration = _registration(repository, _request(1))
    if mutation == "candidate-count":
        invalid = replace(registration, candidate_count=2)
    else:
        evidence = replace(
            registration.evidence[0],
            excerpt="Different anonymous synthetic passage",
        )
        invalid = replace(registration, evidence=(evidence,))

    with pytest.raises(RetrievalPersistenceError) as raised:
        repository.add(invalid)

    assert "Synthetic passage" not in str(raised.value)
    assert database.execute("SELECT COUNT(*) FROM retrieval_runs").fetchone()[0] == 0


def test_add_rejects_duplicate_evidence_identity_before_staging(
    database: sqlite3.Connection,
) -> None:
    repository = SQLiteRetrievalRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    registration = _registration(repository, _request(), evidence_count=2)
    duplicate = replace(
        registration.evidence[1],
        evidence=replace(
            registration.evidence[1].evidence,
            id=registration.evidence[0].evidence.id,
        ),
    )
    invalid = replace(
        registration,
        evidence=(registration.evidence[0], duplicate),
    )

    with pytest.raises(RetrievalPersistenceError, match="evidence set is inconsistent"):
        repository.add(invalid)

    assert database.execute("SELECT COUNT(*) FROM retrieval_runs").fetchone()[0] == 0


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE retrieval_runs SET candidate_count = 2",
        "UPDATE retrieval_runs SET retrieval_policy_version = 'wrong-policy'",
        "UPDATE retrieval_runs SET query_ciphertext = x''",
        "UPDATE evidence_items SET rank = 2",
        "UPDATE evidence_items SET similarity_score = 0.1",
        "UPDATE evidence_items SET excerpt_ciphertext = x''",
        "UPDATE evidence_items SET created_at = 'invalid'",
    ],
    ids=[
        "candidate-count",
        "policy",
        "query",
        "rank",
        "score",
        "excerpt",
        "timestamp",
    ],
)
def test_persisted_run_corruption_fails_closed_and_sanitized(
    database: sqlite3.Connection,
    statement: str,
) -> None:
    repository = SQLiteRetrievalRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    repository.add(_registration(repository, _request(1)))
    database.execute(statement)

    with pytest.raises(RetrievalPersistenceError) as raised:
        repository.get_for_qa_request(WORKSPACE_ID, QA_REQUEST_ID)

    message = str(raised.value)
    assert "Synthetic passage" not in message
    assert "Exact anonymous query" not in message


def test_repository_requires_but_never_finalizes_caller_transaction(
    database: sqlite3.Connection,
) -> None:
    repository = SQLiteRetrievalRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    registration = _registration(repository, _request(1))

    repository.add(registration)

    assert database.in_transaction is True
    database.rollback()
    assert database.execute("SELECT COUNT(*) FROM retrieval_runs").fetchone()[0] == 0
    with pytest.raises(RetrievalPersistenceError, match="transaction is not active"):
        repository.resolve_scope(_request())

    database.execute("BEGIN")
    assert repository.get_for_qa_request(WORKSPACE_ID, QA_REQUEST_ID) is None
    repository.add(registration)
    assert database.in_transaction is True


def test_caller_commit_makes_the_complete_graph_reconstructable(
    database: sqlite3.Connection,
) -> None:
    repository = SQLiteRetrievalRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    registration = _registration(repository, _request(1))
    repository.add(registration)

    database.commit()
    database.execute("BEGIN")

    assert repository.get_for_qa_request(WORKSPACE_ID, QA_REQUEST_ID) == registration


def test_mid_graph_failure_is_sanitized_and_caller_can_roll_back_every_write(
    database: sqlite3.Connection,
) -> None:
    repository = SQLiteRetrievalRepository(database, _FailingSecondEvidenceCodec())
    registration = _registration(repository, _request(), evidence_count=2)

    with pytest.raises(RetrievalPersistenceError) as raised:
        repository.add(registration)

    assert "Synthetic passage" not in str(raised.value)
    assert database.in_transaction is True
    database.rollback()
    assert database.execute("SELECT COUNT(*) FROM retrieval_runs").fetchone()[0] == 0
    assert database.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0] == 0


def test_concurrent_same_qa_snapshot_cannot_create_a_second_run(
    tmp_path: Path,
) -> None:
    factory = SQLiteConnectionFactory(tmp_path / "concurrent.db")
    setup = factory.create()
    run_migrations(setup, discover_migrations(default_migrations_dir()))
    _insert_retrieval_source_graph(setup, document_count=1)
    setup.close()
    first = factory.create()
    second = factory.create()
    first.execute("BEGIN")
    second.execute("BEGIN")
    first_repository = SQLiteRetrievalRepository(
        first,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    second_repository = SQLiteRetrievalRepository(
        second,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    first_registration = _registration(first_repository, _request(1))
    second_registration = _registration(second_repository, _request(1))

    first_repository.add(first_registration)
    first.commit()
    with pytest.raises(RetrievalPersistenceError):
        second_repository.add(second_registration)

    second.rollback()
    second.close()
    assert first.execute("SELECT COUNT(*) FROM retrieval_runs").fetchone()[0] == 1
    first.close()
