"""Persist deterministic float32 embeddings in an active SQLite transaction."""

import sqlite3
import struct
from datetime import datetime, timedelta
from math import hypot, isclose, isfinite

from lexlocal.application.ports.embeddings import (
    EMBEDDING_DTYPE,
    ChunkEmbedding,
    EmbeddingCompatibility,
    EmbeddingPersistenceError,
    EmbeddingRepository,
    NormalizedEmbeddingVector,
    PersistedEmbeddingSet,
)
from lexlocal.application.ports.indexing import (
    CandidateChunkSet,
    IndexChunk,
    StagingEmbeddingHandoff,
)
from lexlocal.application.ports.security import (
    EncodedSensitivePayload,
    SensitivePayloadCodec,
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
from lexlocal.domain.identifiers import ChunkId
from lexlocal.domain.processing import IndexGenerationState

_VECTOR_FORMAT = "lexlocal-f32-le-v1"
_PAYLOAD_PURPOSE = "chunk-embedding-vector"
_PAYLOAD_SCHEMA_VERSION = 1
_CODEC_FORMAT_VERSION = 1


class SQLiteEmbeddingRepository(EmbeddingRepository):
    """Map exact staging chunk embeddings without finalizing transactions."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        payload_codec: SensitivePayloadCodec,
    ) -> None:
        self._connection = connection
        self._payload_codec = payload_codec

    def get_for_candidate(
        self,
        handoff: StagingEmbeddingHandoff,
    ) -> PersistedEmbeddingSet:
        """Return compatible rows in exact candidate chunk order."""

        self._require_transaction()
        try:
            candidate = self._candidate(handoff)
            self._validate_candidate_graph(candidate)
            compatibility = self._compatibility(candidate)
            expected_chunks = candidate.chunks
            expected_by_id = {chunk.id: chunk for chunk in expected_chunks}
            rows = self._embedding_rows(candidate)
            embeddings: list[ChunkEmbedding] = []
            for row in rows:
                chunk_id = ChunkId(row["chunk_id"])
                expected_chunk = expected_by_id.get(chunk_id)
                if expected_chunk is None:
                    raise EmbeddingPersistenceError(
                        "persisted embedding ownership is invalid"
                    )
                embeddings.append(
                    self._map_embedding(row, expected_chunk, compatibility)
                )
            return PersistedEmbeddingSet(
                compatibility,
                tuple(chunk.id for chunk in expected_chunks),
                tuple(embeddings),
            )
        except EmbeddingPersistenceError:
            raise
        except Exception:
            raise EmbeddingPersistenceError(
                "persisted embedding reconstruction failed"
            ) from None

    def add_batch(
        self,
        handoff: StagingEmbeddingHandoff,
        embeddings: tuple[ChunkEmbedding, ...],
    ) -> None:
        """Insert one fully validated batch in the caller-owned transaction."""

        self._require_transaction()
        try:
            candidate = self._candidate(handoff)
            self._validate_candidate_graph(candidate)
            compatibility = self._compatibility(candidate)
            batch = self._validate_batch(candidate, compatibility, embeddings)
            persisted = self.get_for_candidate(handoff)
            persisted_ids = {item.chunk_id for item in persisted.embeddings}
            if any(item.chunk_id in persisted_ids for item in batch):
                raise EmbeddingPersistenceError("embedding batch conflicts")

            parameters: list[object] = []
            for item in batch:
                parameters.extend(
                    (
                        str(item.chunk_id),
                        str(compatibility.workspace_id),
                        str(compatibility.index_generation_id),
                        str(compatibility.embedding_model_id),
                        compatibility.dimensions,
                        compatibility.dtype,
                        1,
                        self._encode_vector(item),
                        self._timestamp(item.created_at),
                    )
                )
            placeholders = ", ".join("(?, ?, ?, ?, ?, ?, ?, ?, ?)" for _ in batch)
            self._connection.execute(
                """
                INSERT INTO embeddings (
                    chunk_id, workspace_id, index_generation_id,
                    embedding_model_id, dimensions, dtype,
                    is_unit_normalized, vector_ciphertext, created_at
                ) VALUES
                """
                + placeholders,
                tuple(parameters),
            )
        except EmbeddingPersistenceError:
            raise
        except Exception:
            raise EmbeddingPersistenceError("embedding batch persistence failed") from None

    @staticmethod
    def _candidate(handoff: StagingEmbeddingHandoff) -> CandidateChunkSet:
        if not isinstance(handoff, StagingEmbeddingHandoff):
            raise EmbeddingPersistenceError("embedding handoff is invalid")
        candidate = handoff.candidate
        if candidate.generation.state is not IndexGenerationState.STAGING:
            raise EmbeddingPersistenceError("embedding candidate state is invalid")
        return candidate

    def _validate_candidate_graph(self, candidate: CandidateChunkSet) -> None:
        generation = candidate.generation
        row = self._connection.execute(
            """
            SELECT g.*, v.state AS version_state, j.state AS job_state,
                   j.stage AS job_stage, j.document_version_id AS job_version_id,
                   m.purpose AS model_purpose, m.dimensions AS model_dimensions
            FROM index_generations AS g
            JOIN document_versions AS v
              ON v.id = g.document_version_id AND v.workspace_id = g.workspace_id
            JOIN document_processing_jobs AS j
              ON j.id = g.processing_job_id AND j.workspace_id = g.workspace_id
            JOIN local_models AS m ON m.id = g.embedding_model_id
            WHERE g.id = ?
            """,
            (str(generation.id),),
        ).fetchone()
        if (
            row is None
            or row["workspace_id"] != str(generation.workspace_id)
            or row["document_version_id"] != str(generation.document_version_id)
            or row["processing_job_id"] != str(generation.processing_job_id)
            or row["state"] != IndexGenerationState.STAGING.value
            or row["embedding_model_id"] != str(generation.embedding_model_id)
            or row["chunking_profile_version"]
            != generation.chunking_profile_version
            or row["normalization_profile_version"]
            != generation.normalization_profile_version
            or row["embedding_dimensions"] != generation.embedding_dimensions
            or row["vector_dtype"] != EMBEDDING_DTYPE
            or row["chunk_count"] != len(candidate.chunks)
            or self._parse_timestamp(row["created_at"]) != candidate.created_at
            or row["activated_at"] is not None
            or row["archived_at"] is not None
            or row["version_state"] != "CANDIDATE_PROCESSING"
            or row["job_state"] != "PROCESSING"
            or row["job_stage"] != "CHUNKING"
            or row["job_version_id"] != str(generation.document_version_id)
            or row["model_purpose"] != "EMBEDDING"
            or row["model_dimensions"] != generation.embedding_dimensions
        ):
            raise EmbeddingPersistenceError("embedding candidate ownership is invalid")

        chunk_ids = tuple(chunk.id for chunk in candidate.chunks)
        placeholders = ", ".join("?" for _ in chunk_ids)
        rows = self._connection.execute(
            f"""
            SELECT id, workspace_id, index_generation_id,
                   document_version_id, document_order
            FROM chunks
            WHERE index_generation_id = ? OR id IN ({placeholders})
            ORDER BY document_order
            """,
            (str(generation.id), *(str(chunk_id) for chunk_id in chunk_ids)),
        ).fetchall()
        if len(rows) != len(candidate.chunks):
            raise EmbeddingPersistenceError("embedding candidate chunks are invalid")
        for row, chunk in zip(rows, candidate.chunks, strict=True):
            if (
                row["id"] != str(chunk.id)
                or row["workspace_id"] != str(generation.workspace_id)
                or row["index_generation_id"] != str(generation.id)
                or row["document_version_id"] != str(generation.document_version_id)
                or row["document_order"] != chunk.logical.document_order
            ):
                raise EmbeddingPersistenceError("embedding candidate chunks are invalid")

    @staticmethod
    def _compatibility(candidate: CandidateChunkSet) -> EmbeddingCompatibility:
        generation = candidate.generation
        return EmbeddingCompatibility(
            generation.workspace_id,
            generation.id,
            generation.embedding_model_id,
            generation.chunking_profile_version,
            generation.normalization_profile_version,
            generation.embedding_dimensions,
            EMBEDDING_DTYPE,
            True,
        )

    @staticmethod
    def _validate_batch(
        candidate: CandidateChunkSet,
        compatibility: EmbeddingCompatibility,
        embeddings: object,
    ) -> tuple[ChunkEmbedding, ...]:
        if (
            not isinstance(embeddings, tuple)
            or not embeddings
            or not all(isinstance(item, ChunkEmbedding) for item in embeddings)
        ):
            raise EmbeddingPersistenceError("embedding batch is invalid")
        batch = embeddings
        batch_ids = tuple(item.chunk_id for item in batch)
        batch_id_set = set(batch_ids)
        expected_order = tuple(
            chunk.id for chunk in candidate.chunks if chunk.id in batch_id_set
        )
        if (
            len(batch_id_set) != len(batch_ids)
            or batch_ids != expected_order
            or any(item.compatibility != compatibility for item in batch)
        ):
            raise EmbeddingPersistenceError("embedding batch is invalid")
        return batch

    def _embedding_rows(self, candidate: CandidateChunkSet) -> tuple[sqlite3.Row, ...]:
        generation = candidate.generation
        chunk_ids = tuple(chunk.id for chunk in candidate.chunks)
        placeholders = ", ".join("?" for _ in chunk_ids)
        rows = self._connection.execute(
            f"""
            SELECT e.*, c.workspace_id AS chunk_workspace_id,
                   c.index_generation_id AS chunk_generation_id,
                   c.document_version_id AS chunk_version_id,
                   c.document_order AS chunk_document_order
            FROM embeddings AS e
            JOIN chunks AS c ON c.id = e.chunk_id
            WHERE e.index_generation_id = ? OR e.chunk_id IN ({placeholders})
            ORDER BY c.document_order
            """,
            (str(generation.id), *(str(chunk_id) for chunk_id in chunk_ids)),
        ).fetchall()
        return tuple(rows)

    def _map_embedding(
        self,
        row: sqlite3.Row,
        expected_chunk: IndexChunk,
        compatibility: EmbeddingCompatibility,
    ) -> ChunkEmbedding:
        chunk_id = ChunkId(row["chunk_id"])
        if (
            chunk_id != expected_chunk.id
            or row["workspace_id"] != str(compatibility.workspace_id)
            or row["index_generation_id"] != str(compatibility.index_generation_id)
            or row["embedding_model_id"] != str(compatibility.embedding_model_id)
            or row["dimensions"] != compatibility.dimensions
            or row["dtype"] != compatibility.dtype
            or row["is_unit_normalized"] != 1
            or row["chunk_workspace_id"] != str(compatibility.workspace_id)
            or row["chunk_generation_id"] != str(compatibility.index_generation_id)
            or row["chunk_version_id"]
            != str(expected_chunk.logical.document_version_id)
            or row["chunk_document_order"] != expected_chunk.logical.document_order
        ):
            raise EmbeddingPersistenceError("persisted embedding mapping is invalid")
        return ChunkEmbedding(
            chunk_id,
            compatibility,
            self._decode_vector(row["vector_ciphertext"], chunk_id, compatibility),
            self._parse_timestamp(row["created_at"]),
        )

    def _encode_vector(self, embedding: ChunkEmbedding) -> bytes:
        compatibility = embedding.compatibility
        vector = struct.pack(
            f"<{compatibility.dimensions}f",
            *embedding.vector.values,
        )
        context, key_reference = self._security_values(
            embedding.chunk_id,
            compatibility,
        )
        encoded = self._payload_codec.encode(
            vector,
            context=context,
            key_reference=key_reference,
        )
        if (
            not isinstance(encoded, EncodedSensitivePayload)
            or encoded.context != context
            or encoded.key_reference != key_reference
            or encoded.format_version != _CODEC_FORMAT_VERSION
        ):
            raise EmbeddingPersistenceError("embedding payload is invalid")
        return encoded.payload

    def _decode_vector(
        self,
        payload: object,
        chunk_id: ChunkId,
        compatibility: EmbeddingCompatibility,
    ) -> NormalizedEmbeddingVector:
        if not isinstance(payload, bytes):
            raise EmbeddingPersistenceError("embedding payload is invalid")
        context, key_reference = self._security_values(chunk_id, compatibility)
        plaintext = self._payload_codec.decode(
            EncodedSensitivePayload(
                payload,
                context,
                key_reference,
                _CODEC_FORMAT_VERSION,
            ),
            context=context,
            key_reference=key_reference,
        )
        expected_length = 4 * compatibility.dimensions
        if not isinstance(plaintext, bytes) or len(plaintext) != expected_length:
            raise EmbeddingPersistenceError("embedding payload is invalid")
        values = struct.unpack(f"<{compatibility.dimensions}f", plaintext)
        norm = hypot(*values)
        if (
            not all(isfinite(value) for value in values)
            or not isfinite(norm)
            or norm <= 0.0
            or not isclose(norm, 1.0, rel_tol=1e-6, abs_tol=1e-6)
            or struct.pack(f"<{compatibility.dimensions}f", *values) != plaintext
        ):
            raise EmbeddingPersistenceError("embedding payload is invalid")
        return NormalizedEmbeddingVector(values)

    @staticmethod
    def _security_values(
        chunk_id: ChunkId,
        compatibility: EmbeddingCompatibility,
    ) -> tuple[SensitivePayloadContext, WorkspaceKeyReference]:
        owner_id = (
            f"{_VECTOR_FORMAT}:{chunk_id}:{compatibility.embedding_model_id}:"
            f"{compatibility.dimensions}:{compatibility.dtype}"
        )
        workspace_id = compatibility.workspace_id
        return (
            SensitivePayloadContext(
                workspace_id,
                owner_id,
                _PAYLOAD_PURPOSE,
                _PAYLOAD_SCHEMA_VERSION,
            ),
            WorkspaceKeyReference(workspace_id, 1),
        )

    def _require_transaction(self) -> None:
        if not self._connection.in_transaction:
            raise EmbeddingPersistenceError("embedding transaction is not active")

    @staticmethod
    def _timestamp(value: datetime) -> str:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise EmbeddingPersistenceError("embedding timestamp is invalid")
        canonical = value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if SQLiteEmbeddingRepository._parse_timestamp(canonical) != value:
            raise EmbeddingPersistenceError("embedding timestamp is invalid")
        return canonical

    @staticmethod
    def _parse_timestamp(value: object) -> datetime:
        if not isinstance(value, str) or not value.endswith("Z"):
            raise EmbeddingPersistenceError("embedding timestamp is invalid")
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        canonical = parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if parsed.utcoffset() != timedelta(0) or value != canonical:
            raise EmbeddingPersistenceError("embedding timestamp is invalid")
        return parsed
