"""Integration tests for deterministic SQLite embedding persistence."""

import sqlite3
import struct
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lexlocal.application.ports.embeddings import (
    EMBEDDING_DTYPE,
    ChunkEmbedding,
    EmbeddingCompatibility,
    EmbeddingPersistenceError,
    NormalizedEmbeddingVector,
)
from lexlocal.application.ports.indexing import (
    CandidateChunkSet,
    ChunkConfiguration,
    IndexChunk,
    LogicalChunk,
    StagingEmbeddingHandoff,
)
from lexlocal.application.ports.processing import PageExtractionMethod
from lexlocal.application.ports.security import (
    EncodedSensitivePayload,
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
from lexlocal.domain.identifiers import (
    ChunkId,
    DocumentPageId,
    DocumentVersionId,
    IndexGenerationId,
    LocalModelId,
    ProcessingJobId,
    SourceLocatorId,
    WorkspaceId,
)
from lexlocal.domain.processing import IndexGeneration
from lexlocal.domain.retrieval import PageNumber
from lexlocal.infrastructure.persistence.migration_runner import run_migrations
from lexlocal.infrastructure.persistence.migrations import (
    default_migrations_dir,
    discover_migrations,
)
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.persistence.sqlite_embedding_repository import (
    SQLiteEmbeddingRepository,
)
from lexlocal.infrastructure.persistence.sqlite_index_repository import (
    SQLiteIndexRepository,
)
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyPayloadCodec,
)
from lexlocal.infrastructure.security.insecure_development_indexing import (
    InsecureDevelopmentOnlyChunkEqualityToken,
)

WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
VERSION_ID = DocumentVersionId("20000000-0000-4000-8000-000000000001")
JOB_ID = ProcessingJobId("30000000-0000-4000-8000-000000000001")
MODEL_ID = LocalModelId("40000000-0000-4000-8000-000000000001")
OTHER_MODEL_ID = LocalModelId("40000000-0000-4000-8000-000000000002")
GENERATION_ID = IndexGenerationId("50000000-0000-4000-8000-000000000001")
PAGE_ID = DocumentPageId("60000000-0000-4000-8000-000000000001")
LOCATOR_ID = SourceLocatorId("70000000-0000-4000-8000-000000000001")
CHUNK_A = ChunkId("80000000-0000-4000-8000-000000000001")
CHUNK_B = ChunkId("80000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 9, 7, 8, 30, 45, 678000, tzinfo=UTC)
PROFILE = ChunkConfiguration(4, 0).profile


class _RecordingCodec:
    def __init__(self) -> None:
        self._delegate = InsecureDevelopmentOnlyPayloadCodec()
        self.encoded_contexts: list[
            tuple[SensitivePayloadContext, WorkspaceKeyReference]
        ] = []
        self.decoded_contexts: list[
            tuple[SensitivePayloadContext, WorkspaceKeyReference]
        ] = []

    def encode(
        self,
        plaintext: bytes,
        *,
        context: SensitivePayloadContext,
        key_reference: WorkspaceKeyReference,
    ) -> EncodedSensitivePayload:
        self.encoded_contexts.append((context, key_reference))
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
        self.decoded_contexts.append((context, key_reference))
        return self._delegate.decode(
            encoded,
            context=context,
            key_reference=key_reference,
        )


@pytest.fixture
def database(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = SQLiteConnectionFactory(tmp_path / "lexlocal.db").create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
    _insert_graph(connection)
    candidate = _candidate()
    connection.execute("BEGIN")
    SQLiteIndexRepository(
        connection,
        InsecureDevelopmentOnlyPayloadCodec(),
    ).stage_candidate(candidate)
    connection.commit()
    yield connection
    connection.close()


def _insert_graph(connection: sqlite3.Connection) -> None:
    timestamp = "2026-09-07T08:30:45.678Z"
    connection.execute("BEGIN")
    connection.execute(
        "INSERT INTO workspaces (id, name_ciphertext, name_lookup_fingerprint, state, created_at, updated_at) VALUES (?, x'01', x'02', 'ACTIVE', ?, ?)",
        (str(WORKSPACE_ID), timestamp, timestamp),
    )
    connection.execute(
        "INSERT INTO documents (id, workspace_id, display_name_ciphertext, state, created_at, updated_at) VALUES ('synthetic-document', ?, x'03', 'ACTIVE', ?, ?)",
        (str(WORKSPACE_ID), timestamp, timestamp),
    )
    connection.execute(
        "INSERT INTO document_versions (id, workspace_id, document_id, version_number, historical_filename_ciphertext, page_count, state, created_at) VALUES (?, ?, 'synthetic-document', 1, x'04', 1, 'CANDIDATE_PROCESSING', ?)",
        (str(VERSION_ID), str(WORKSPACE_ID), timestamp),
    )
    connection.execute(
        "INSERT INTO document_processing_jobs (id, workspace_id, document_version_id, attempt_number, state, stage, created_at) VALUES (?, ?, ?, 1, 'PROCESSING', 'CHUNKING', ?)",
        (str(JOB_ID), str(WORKSPACE_ID), str(VERSION_ID), timestamp),
    )
    connection.execute(
        "INSERT INTO local_models (id, purpose, provider, requested_alias, resolved_model_id, dimensions, created_at) VALUES (?, 'EMBEDDING', 'synthetic', 'fixture', 'synthetic-model', 2, ?)",
        (str(MODEL_ID), timestamp),
    )
    page_context = SensitivePayloadContext(
        WORKSPACE_ID,
        str(PAGE_ID),
        "document-page-text",
        1,
    )
    page_payload = InsecureDevelopmentOnlyPayloadCodec().encode(
        b"abcdefgh",
        context=page_context,
        key_reference=WorkspaceKeyReference(WORKSPACE_ID, 1),
    ).payload
    connection.execute(
        "INSERT INTO document_pages (id, workspace_id, document_version_id, page_number, state, extraction_method, text_ciphertext, character_count, created_at, updated_at) VALUES (?, ?, ?, 1, 'READY', 'NATIVE', ?, 8, ?, ?)",
        (str(PAGE_ID), str(WORKSPACE_ID), str(VERSION_ID), page_payload, timestamp, timestamp),
    )
    connection.execute(
        "INSERT INTO source_locators (id, workspace_id, document_version_id, page_id, locator_kind, page_number, locator_version, created_at) VALUES (?, ?, ?, ?, 'PAGE', 1, 1, ?)",
        (str(LOCATOR_ID), str(WORKSPACE_ID), str(VERSION_ID), str(PAGE_ID), timestamp),
    )
    connection.commit()


def _candidate() -> CandidateChunkSet:
    generation = IndexGeneration(
        GENERATION_ID,
        WORKSPACE_ID,
        VERSION_ID,
        JOB_ID,
        MODEL_ID,
        PROFILE.value,
        "exact-text-v1",
        2,
    )
    token = InsecureDevelopmentOnlyChunkEqualityToken()
    chunks = []
    for order, (chunk_id, start, end, text) in enumerate(
        (
            (CHUNK_A, 0, 4, "abcd"),
            (CHUNK_B, 4, 8, "efgh"),
        )
    ):
        logical = LogicalChunk(
            WORKSPACE_ID,
            VERSION_ID,
            PAGE_ID,
            PageNumber(1),
            LOCATOR_ID,
            order,
            order,
            start,
            end,
            text,
            PageExtractionMethod.NATIVE,
            PROFILE,
        )
        chunks.append(IndexChunk(chunk_id, logical, token.fingerprint(logical), NOW))
    return CandidateChunkSet(generation, tuple(chunks), NOW)


def _handoff(candidate: CandidateChunkSet | None = None) -> StagingEmbeddingHandoff:
    return StagingEmbeddingHandoff(_candidate() if candidate is None else candidate)


def _compatibility(candidate: CandidateChunkSet | None = None) -> EmbeddingCompatibility:
    generation = (_candidate() if candidate is None else candidate).generation
    return EmbeddingCompatibility(
        generation.workspace_id,
        generation.id,
        generation.embedding_model_id,
        generation.chunking_profile_version,
        generation.normalization_profile_version,
        generation.embedding_dimensions,
    )


def _embedding(chunk_id: ChunkId) -> ChunkEmbedding:
    values = (0.6, 0.8) if chunk_id == CHUNK_A else (0.0, 1.0)
    return ChunkEmbedding(
        chunk_id,
        _compatibility(),
        NormalizedEmbeddingVector(values),
        NOW,
    )


def test_deterministic_float32_schema_mapping_and_exact_round_trip(
    database: sqlite3.Connection,
) -> None:
    database.execute("BEGIN")
    repository = SQLiteEmbeddingRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )

    repository.add_batch(_handoff(), (_embedding(CHUNK_A), _embedding(CHUNK_B)))

    rows = database.execute(
        "SELECT * FROM embeddings ORDER BY chunk_id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["chunk_id"] == str(CHUNK_A)
    assert rows[0]["workspace_id"] == str(WORKSPACE_ID)
    assert rows[0]["index_generation_id"] == str(GENERATION_ID)
    assert rows[0]["embedding_model_id"] == str(MODEL_ID)
    assert rows[0]["dimensions"] == 2
    assert rows[0]["dtype"] == EMBEDDING_DTYPE
    assert rows[0]["is_unit_normalized"] == 1
    assert rows[0]["vector_ciphertext"] == struct.pack("<2f", 0.6, 0.8)
    assert len(rows[0]["vector_ciphertext"]) == 8
    assert rows[0]["created_at"] == "2026-09-07T08:30:45.678Z"

    restored = repository.get_for_candidate(_handoff())

    assert restored.is_complete is True
    assert tuple(item.chunk_id for item in restored.embeddings) == (CHUNK_A, CHUNK_B)
    assert restored.embeddings[0].vector.values == struct.unpack(
        "<2f", struct.pack("<2f", 0.6, 0.8)
    )
    assert restored.embeddings[1].vector.values == (0.0, 1.0)
    assert all(item.created_at == NOW for item in restored.embeddings)


def test_vector_payload_uses_exact_deterministic_security_context(
    database: sqlite3.Connection,
) -> None:
    codec = _RecordingCodec()
    database.execute("BEGIN")
    repository = SQLiteEmbeddingRepository(database, codec)

    repository.add_batch(_handoff(), (_embedding(CHUNK_A),))
    repository.get_for_candidate(_handoff())

    expected_owner = f"lexlocal-f32-le-v1:{CHUNK_A}:{MODEL_ID}:2:float32"
    assert len(codec.encoded_contexts) == 1
    assert len(codec.decoded_contexts) == 1
    for context, key_reference in (
        codec.encoded_contexts + codec.decoded_contexts
    ):
        assert context.workspace_id == WORKSPACE_ID
        assert context.owner_id == expected_owner
        assert context.purpose == "chunk-embedding-vector"
        assert context.schema_version == 1
        assert key_reference == WorkspaceKeyReference(WORKSPACE_ID, 1)


def test_partial_rows_are_returned_in_candidate_order(
    database: sqlite3.Connection,
) -> None:
    database.execute("BEGIN")
    repository = SQLiteEmbeddingRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )

    repository.add_batch(_handoff(), (_embedding(CHUNK_B),))
    partial = repository.get_for_candidate(_handoff())
    repository.add_batch(_handoff(), (_embedding(CHUNK_A),))
    complete = repository.get_for_candidate(_handoff())

    assert tuple(item.chunk_id for item in partial.embeddings) == (CHUNK_B,)
    assert partial.is_complete is False
    assert tuple(item.chunk_id for item in complete.embeddings) == (CHUNK_A, CHUNK_B)
    assert complete.is_complete is True


def test_duplicate_and_conflicting_batches_fail_without_leaking_values(
    database: sqlite3.Connection,
) -> None:
    database.execute("BEGIN")
    repository = SQLiteEmbeddingRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    repository.add_batch(_handoff(), (_embedding(CHUNK_A),))

    with pytest.raises(EmbeddingPersistenceError) as duplicate:
        repository.add_batch(_handoff(), (_embedding(CHUNK_A),))

    incompatible = replace(
        _embedding(CHUNK_B),
        compatibility=replace(
            _compatibility(),
            normalization_profile_version="conflicting-synthetic-profile",
        ),
    )
    with pytest.raises(EmbeddingPersistenceError) as conflict:
        repository.add_batch(_handoff(), (incompatible,))

    assert str(CHUNK_A) not in str(duplicate.value)
    assert "conflicting-synthetic-profile" not in str(conflict.value)
    assert database.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 1


def test_cross_workspace_handoff_is_rejected_without_identity_leakage(
    database: sqlite3.Connection,
) -> None:
    candidate = _candidate()
    other_workspace = WorkspaceId("10000000-0000-4000-8000-000000000002")
    substituted = CandidateChunkSet(
        replace(candidate.generation, workspace_id=other_workspace),
        tuple(
            replace(
                chunk,
                logical=replace(chunk.logical, workspace_id=other_workspace),
            )
            for chunk in candidate.chunks
        ),
        candidate.created_at,
    )
    database.execute("BEGIN")
    repository = SQLiteEmbeddingRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )

    with pytest.raises(EmbeddingPersistenceError) as caught:
        repository.get_for_candidate(_handoff(substituted))

    assert str(other_workspace) not in str(caught.value)
    assert str(GENERATION_ID) not in str(caught.value)


def test_persisted_generation_must_remain_staging(
    database: sqlite3.Connection,
) -> None:
    database.execute("BEGIN")
    database.execute(
        "UPDATE index_generations SET state = 'ACTIVE', activated_at = ? WHERE id = ?",
        ("2026-09-07T08:30:46.678Z", str(GENERATION_ID)),
    )
    repository = SQLiteEmbeddingRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )

    with pytest.raises(EmbeddingPersistenceError, match="ownership is invalid"):
        repository.add_batch(_handoff(), (_embedding(CHUNK_A),))

    assert database.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("statement", "parameters"),
    [
        ("UPDATE embeddings SET dimensions = 3", ()),
        ("UPDATE embeddings SET dtype = 'float64'", ()),
        ("UPDATE embeddings SET is_unit_normalized = 0", ()),
        ("UPDATE embeddings SET vector_ciphertext = x'0000'", ()),
        ("UPDATE embeddings SET vector_ciphertext = ?", (struct.pack("<2f", float("nan"), 1.0),)),
        ("UPDATE embeddings SET vector_ciphertext = ?", (struct.pack("<2f", 0.0, 0.0),)),
        ("UPDATE embeddings SET vector_ciphertext = ?", (struct.pack("<2f", 0.5, 0.5),)),
        ("UPDATE embeddings SET created_at = 'not-a-timestamp'", ()),
    ],
)
def test_corrupt_metadata_payload_or_timestamp_fails_closed(
    database: sqlite3.Connection,
    statement: str,
    parameters: tuple[object, ...],
) -> None:
    database.execute("BEGIN")
    repository = SQLiteEmbeddingRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    repository.add_batch(_handoff(), (_embedding(CHUNK_A),))
    database.commit()
    database.execute("PRAGMA ignore_check_constraints = ON")
    database.execute("BEGIN")
    database.execute(statement, parameters)

    with pytest.raises(EmbeddingPersistenceError):
        repository.get_for_candidate(_handoff())


def test_corrupt_model_and_chunk_generation_ownership_fail_closed(
    database: sqlite3.Connection,
) -> None:
    timestamp = "2026-09-07T08:30:45.678Z"
    database.execute("BEGIN")
    repository = SQLiteEmbeddingRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    repository.add_batch(_handoff(), (_embedding(CHUNK_A),))
    database.execute(
        "INSERT INTO local_models (id, purpose, provider, requested_alias, resolved_model_id, dimensions, created_at) VALUES (?, 'EMBEDDING', 'synthetic', 'other', 'other-model', 2, ?)",
        (str(OTHER_MODEL_ID), timestamp),
    )
    database.execute(
        "UPDATE embeddings SET embedding_model_id = ?",
        (str(OTHER_MODEL_ID),),
    )

    with pytest.raises(EmbeddingPersistenceError):
        repository.get_for_candidate(_handoff())

    database.rollback()
    database.execute("PRAGMA foreign_keys = OFF")
    database.execute("BEGIN")
    repository.add_batch(_handoff(), (_embedding(CHUNK_A),))
    wrong_generation = "50000000-0000-4000-8000-000000000099"
    database.execute(
        "UPDATE embeddings SET index_generation_id = ?",
        (wrong_generation,),
    )

    with pytest.raises(EmbeddingPersistenceError) as caught:
        repository.get_for_candidate(_handoff())

    assert wrong_generation not in str(caught.value)


def test_batch_statement_is_atomic_and_caller_can_rollback(
    database: sqlite3.Connection,
) -> None:
    database.execute("BEGIN")
    database.execute(
        f"""
        CREATE TEMP TRIGGER reject_second_synthetic_embedding
        BEFORE INSERT ON embeddings
        WHEN NEW.chunk_id = '{CHUNK_B}'
        BEGIN
            SELECT RAISE(ABORT, 'synthetic batch failure');
        END
        """
    )
    repository = SQLiteEmbeddingRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )

    with pytest.raises(EmbeddingPersistenceError) as caught:
        repository.add_batch(_handoff(), (_embedding(CHUNK_A), _embedding(CHUNK_B)))

    assert "synthetic batch failure" not in str(caught.value)
    assert database.in_transaction is True
    assert database.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 0
    database.rollback()
    assert database.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 0


def test_repository_requires_and_never_finalizes_active_transaction(
    database: sqlite3.Connection,
) -> None:
    repository = SQLiteEmbeddingRepository(
        database,
        InsecureDevelopmentOnlyPayloadCodec(),
    )

    with pytest.raises(EmbeddingPersistenceError, match="transaction is not active"):
        repository.get_for_candidate(_handoff())

    database.execute("BEGIN")
    repository.add_batch(_handoff(), (_embedding(CHUNK_A),))

    assert database.in_transaction is True
    database.rollback()
    assert database.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 0
