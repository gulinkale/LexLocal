"""Define Application-owned contracts for deterministic page-aware indexing."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from lexlocal.application.ports.processing import PageExtractionMethod
from lexlocal.domain.documents import DocumentVersion, DocumentVersionState
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
from lexlocal.domain.processing import (
    IndexGeneration,
    IndexGenerationState,
    ProcessingJob,
    ProcessingJobState,
)
from lexlocal.domain.retrieval import PageNumber

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200
_ALGORITHM_VERSION = "page-codepoint-window-v1"
_BOUNDARY_POLICY = "page-source"
_WARNING_POLICY = "skip"
_TEXT_POLICY = "exact-text"
_EQUALITY_VERSION = "chunk-equality-v1"


class IndexingError(Exception):
    """Base exception for sanitized indexing failures."""


class InvalidChunkConfiguration(IndexingError):
    """Report invalid deterministic chunk configuration."""


class InvalidIndexingInput(IndexingError):
    """Report malformed or inconsistent page/provenance input."""


class NoEligibleChunks(IndexingError):
    """Report that the supplied processing handoff cannot produce a chunk."""


class IndexingCancelled(IndexingError):
    """Report cooperative cancellation before a complete chunk result exists."""


class IndexingPersistenceError(IndexingError):
    """Report a sanitized candidate/index persistence contract failure."""


class AmbiguousIndexGeneration(IndexingError):
    """Report that persisted generation state cannot be selected uniquely."""


class IndexingCancellationCheck(Protocol):
    """Raise when cooperative indexing cancellation has been requested."""

    def raise_if_cancelled(self) -> None:
        """Raise IndexingCancelled when cancellation is requested."""

        ...


@dataclass(frozen=True, slots=True)
class ChunkConfiguration:
    """Configure deterministic Unicode-code-point sliding windows."""

    chunk_size: int = DEFAULT_CHUNK_SIZE
    overlap: int = DEFAULT_CHUNK_OVERLAP

    def __post_init__(self) -> None:
        if (
            isinstance(self.chunk_size, bool)
            or not isinstance(self.chunk_size, int)
            or self.chunk_size <= 0
        ):
            raise InvalidChunkConfiguration("chunk size must be a positive integer")
        if (
            isinstance(self.overlap, bool)
            or not isinstance(self.overlap, int)
            or self.overlap < 0
            or self.overlap >= self.chunk_size
        ):
            raise InvalidChunkConfiguration(
                "chunk overlap must be a non-negative integer smaller than chunk size"
            )

    @property
    def profile(self) -> "ChunkProfile":
        """Return the canonical identity of this complete chunking contract."""

        return ChunkProfile(
            f"{_ALGORITHM_VERSION};unit=unicode-code-point;size={self.chunk_size};"
            f"overlap={self.overlap};boundary={_BOUNDARY_POLICY};"
            f"warning={_WARNING_POLICY};text={_TEXT_POLICY};"
            f"equality={_EQUALITY_VERSION}"
        )


@dataclass(frozen=True, slots=True)
class ChunkProfile:
    """Carry one canonical persisted chunk-profile identity."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise InvalidChunkConfiguration("chunk profile is invalid")


@dataclass(frozen=True, slots=True)
class LogicalChunk:
    """Represent deterministic content and provenance without technical identity."""

    workspace_id: WorkspaceId
    document_version_id: DocumentVersionId
    page_id: DocumentPageId
    page_number: PageNumber
    source_locator_id: SourceLocatorId
    document_order: int
    page_order: int
    source_start_offset: int
    source_end_offset: int
    text: str = field(repr=False)
    extraction_method: PageExtractionMethod
    profile: ChunkProfile

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_id, WorkspaceId):
            raise InvalidIndexingInput("chunk ownership is invalid")
        if not isinstance(self.document_version_id, DocumentVersionId):
            raise InvalidIndexingInput("chunk ownership is invalid")
        if not isinstance(self.page_id, DocumentPageId):
            raise InvalidIndexingInput("chunk provenance is invalid")
        if not isinstance(self.page_number, PageNumber):
            raise InvalidIndexingInput("chunk provenance is invalid")
        if not isinstance(self.source_locator_id, SourceLocatorId):
            raise InvalidIndexingInput("chunk provenance is invalid")
        _require_non_negative_integer(self.document_order, "chunk order")
        _require_non_negative_integer(self.page_order, "chunk order")
        _require_non_negative_integer(self.source_start_offset, "chunk offset")
        if (
            isinstance(self.source_end_offset, bool)
            or not isinstance(self.source_end_offset, int)
            or self.source_end_offset <= self.source_start_offset
        ):
            raise InvalidIndexingInput("chunk offset is invalid")
        if not isinstance(self.text, str) or not self.text:
            raise InvalidIndexingInput("chunk text is invalid")
        if len(self.text) != self.source_end_offset - self.source_start_offset:
            raise InvalidIndexingInput("chunk offset is invalid")
        if not isinstance(self.extraction_method, PageExtractionMethod):
            raise InvalidIndexingInput("chunk extraction method is invalid")
        if not isinstance(self.profile, ChunkProfile):
            raise InvalidIndexingInput("chunk profile is invalid")


class ChunkEqualityToken(Protocol):
    """Derive deterministic opaque equality material from one logical chunk."""

    def fingerprint(self, chunk: LogicalChunk) -> bytes:
        """Return deterministic equality material without using a random ChunkId."""

        ...


@dataclass(frozen=True, slots=True)
class IndexChunk:
    """Add injected persistence identity to one deterministic logical chunk."""

    id: ChunkId
    logical: LogicalChunk
    equality_token: bytes = field(repr=False)
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.id, ChunkId):
            raise InvalidIndexingInput("chunk identity is invalid")
        if not isinstance(self.logical, LogicalChunk):
            raise InvalidIndexingInput("logical chunk is invalid")
        if not isinstance(self.equality_token, bytes) or not self.equality_token:
            raise InvalidIndexingInput("chunk equality token is invalid")
        _require_utc(self.created_at)


@dataclass(frozen=True, slots=True)
class ChunkingResult:
    """Return a complete ordered logical and persistence-ready chunk set."""

    profile: ChunkProfile
    chunks: tuple[IndexChunk, ...]
    candidate_created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.profile, ChunkProfile):
            raise InvalidIndexingInput("chunking result profile is invalid")
        if not isinstance(self.chunks, tuple) or not self.chunks:
            raise NoEligibleChunks("processing handoff contains no eligible chunks")
        if not all(isinstance(chunk, IndexChunk) for chunk in self.chunks):
            raise InvalidIndexingInput("chunking result is invalid")
        if tuple(chunk.logical.document_order for chunk in self.chunks) != tuple(
            range(len(self.chunks))
        ):
            raise InvalidIndexingInput("chunking result order is invalid")
        if any(chunk.logical.profile != self.profile for chunk in self.chunks):
            raise InvalidIndexingInput("chunking result profile is inconsistent")
        _require_utc(self.candidate_created_at)

    @property
    def logical_chunks(self) -> tuple[LogicalChunk, ...]:
        """Expose deterministic output independently from IDs and timestamps."""

        return tuple(chunk.logical for chunk in self.chunks)

    def for_generation(self, generation: IndexGeneration) -> "CandidateChunkSet":
        """Bind the complete result to one candidate using its own timestamp."""

        return CandidateChunkSet(
            generation=generation,
            chunks=self.chunks,
            created_at=self.candidate_created_at,
        )


@dataclass(frozen=True, slots=True)
class CandidateChunkSet:
    """Carry one staging generation and its complete ordered chunks."""

    generation: IndexGeneration
    chunks: tuple[IndexChunk, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.generation, IndexGeneration):
            raise IndexingPersistenceError("candidate generation is invalid")
        if self.generation.state is not IndexGenerationState.STAGING:
            raise IndexingPersistenceError("candidate generation state is invalid")
        if (
            not isinstance(self.chunks, tuple)
            or not self.chunks
            or not all(isinstance(chunk, IndexChunk) for chunk in self.chunks)
        ):
            raise IndexingPersistenceError("candidate chunk set is invalid")
        if any(
            chunk.logical.workspace_id != self.generation.workspace_id
            or chunk.logical.document_version_id != self.generation.document_version_id
            for chunk in self.chunks
        ):
            raise IndexingPersistenceError("candidate chunk relationships are invalid")
        if tuple(chunk.logical.document_order for chunk in self.chunks) != tuple(
            range(len(self.chunks))
        ):
            raise IndexingPersistenceError("candidate chunk order is invalid")
        if any(
            chunk.logical.profile.value != self.generation.chunking_profile_version
            for chunk in self.chunks
        ):
            raise IndexingPersistenceError("candidate chunk profile is invalid")
        try:
            _require_utc(self.created_at)
        except InvalidIndexingInput:
            raise IndexingPersistenceError("candidate generation timestamp is invalid") from None


@dataclass(frozen=True, slots=True)
class PersistedIndexGeneration:
    """Expose persisted generation metadata without storage representations."""

    generation: IndexGeneration
    created_at: datetime
    activated_at: datetime | None = None
    archived_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.generation, IndexGeneration):
            raise IndexingPersistenceError("persisted generation is invalid")
        try:
            _require_utc(self.created_at)
            if self.activated_at is not None:
                _require_utc(self.activated_at)
            if self.archived_at is not None:
                _require_utc(self.archived_at)
        except InvalidIndexingInput:
            raise IndexingPersistenceError("persisted generation timestamp is invalid") from None
        state = self.generation.state
        if (
            (
                state is IndexGenerationState.STAGING
                and (self.activated_at is not None or self.archived_at is not None)
            )
            or (
                state is IndexGenerationState.ACTIVE
                and (self.activated_at is None or self.archived_at is not None)
            )
            or (
                state is IndexGenerationState.ARCHIVED
                and (self.activated_at is None or self.archived_at is None)
            )
        ):
            raise IndexingPersistenceError("persisted generation lifecycle is invalid")


@dataclass(frozen=True, slots=True)
class IndexCompatibility:
    """Describe requested generation compatibility without creating an identity."""

    workspace_id: WorkspaceId
    document_version_id: DocumentVersionId
    processing_job_id: ProcessingJobId
    embedding_model_id: LocalModelId
    chunking_profile_version: str
    normalization_profile_version: str
    embedding_dimensions: int

    def __post_init__(self) -> None:
        try:
            IndexGeneration(
                IndexGenerationId("00000000-0000-0000-0000-000000000000"),
                self.workspace_id,
                self.document_version_id,
                self.processing_job_id,
                self.embedding_model_id,
                self.chunking_profile_version,
                self.normalization_profile_version,
                self.embedding_dimensions,
            )
        except Exception:
            raise InvalidIndexingInput("index compatibility is invalid") from None


@dataclass(frozen=True, slots=True)
class StagingEmbeddingHandoff:
    """Expose one exact persisted STAGING chunk set to EMBEDDING-001."""

    candidate: CandidateChunkSet

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, CandidateChunkSet):
            raise IndexingPersistenceError("staging embedding handoff is invalid")


@dataclass(frozen=True, slots=True)
class ReusedActiveIndex:
    """Report a compatible ACTIVE generation requiring no embedding handoff."""

    persisted: PersistedIndexGeneration

    def __post_init__(self) -> None:
        if (
            not isinstance(self.persisted, PersistedIndexGeneration)
            or self.persisted.generation.state is not IndexGenerationState.ACTIVE
        ):
            raise IndexingPersistenceError("active index result is invalid")


IndexPreparationResult = StagingEmbeddingHandoff | ReusedActiveIndex


@dataclass(frozen=True, slots=True)
class EmbeddingMetadata:
    """Expose non-sensitive persisted embedding compatibility metadata."""

    chunk_id: ChunkId
    workspace_id: WorkspaceId
    index_generation_id: IndexGenerationId
    embedding_model_id: LocalModelId
    dimensions: int
    dtype: str
    is_unit_normalized: bool
    has_payload: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.chunk_id, ChunkId)
            or not isinstance(self.workspace_id, WorkspaceId)
            or not isinstance(self.index_generation_id, IndexGenerationId)
            or not isinstance(self.embedding_model_id, LocalModelId)
            or isinstance(self.dimensions, bool)
            or not isinstance(self.dimensions, int)
            or self.dimensions < 1
            or not isinstance(self.dtype, str)
            or not isinstance(self.is_unit_normalized, bool)
            or not isinstance(self.has_payload, bool)
        ):
            raise IndexingPersistenceError("embedding metadata is invalid")


@dataclass(frozen=True, slots=True)
class IndexActivationSnapshot:
    """Carry the exact persisted graph needed for an activation decision."""

    candidate: CandidateChunkSet
    version: DocumentVersion
    job: ProcessingJob
    job_stage: str
    embeddings: tuple[EmbeddingMetadata, ...]
    has_warnings: bool
    previous_version: DocumentVersion | None = None
    previous_generation: PersistedIndexGeneration | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.candidate, CandidateChunkSet)
            or not isinstance(self.version, DocumentVersion)
            or not isinstance(self.job, ProcessingJob)
            or not isinstance(self.job_stage, str)
            or not isinstance(self.embeddings, tuple)
            or not all(isinstance(item, EmbeddingMetadata) for item in self.embeddings)
            or not isinstance(self.has_warnings, bool)
            or (
                self.previous_version is not None
                and not isinstance(self.previous_version, DocumentVersion)
            )
            or (
                self.previous_generation is not None
                and not isinstance(self.previous_generation, PersistedIndexGeneration)
            )
        ):
            raise IndexingPersistenceError("activation snapshot is invalid")


@dataclass(frozen=True, slots=True)
class IndexActivationUpdate:
    """Describe one fully validated atomic activation transition."""

    candidate: CandidateChunkSet
    version: DocumentVersion
    job: ProcessingJob
    generation: IndexGeneration
    completed_at: datetime
    has_warnings: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.candidate, CandidateChunkSet)
            or not isinstance(self.version, DocumentVersion)
            or not isinstance(self.job, ProcessingJob)
            or not isinstance(self.generation, IndexGeneration)
            or not isinstance(self.has_warnings, bool)
        ):
            raise IndexingPersistenceError("activation update is invalid")
        expected_job_state = (
            ProcessingJobState.READY_WITH_WARNINGS
            if self.has_warnings
            else ProcessingJobState.READY
        )
        candidate_generation = self.candidate.generation
        try:
            expected_generation = candidate_generation.activate(self.job)
        except Exception:
            raise IndexingPersistenceError("activation update relationships are invalid") from None
        if (
            self.version.state is not DocumentVersionState.ACTIVE
            or self.job.state is not expected_job_state
            or self.generation.state is not IndexGenerationState.ACTIVE
            or self.version.workspace_id != candidate_generation.workspace_id
            or self.version.id != candidate_generation.document_version_id
            or self.job.workspace_id != candidate_generation.workspace_id
            or self.job.id != candidate_generation.processing_job_id
            or self.job.document_version_id != candidate_generation.document_version_id
            or self.generation != expected_generation
        ):
            raise IndexingPersistenceError("activation update relationships are invalid")
        try:
            _require_utc(self.completed_at)
        except InvalidIndexingInput:
            raise IndexingPersistenceError("activation timestamp is invalid") from None


@dataclass(frozen=True, slots=True)
class ActivatedIndex:
    """Report the successfully committed terminal index lifecycle values."""

    version: DocumentVersion
    job: ProcessingJob
    generation: IndexGeneration

    def __post_init__(self) -> None:
        if (
            not isinstance(self.version, DocumentVersion)
            or not isinstance(self.job, ProcessingJob)
            or not isinstance(self.generation, IndexGeneration)
            or self.version.state is not DocumentVersionState.ACTIVE
            or self.job.state
            not in (ProcessingJobState.READY, ProcessingJobState.READY_WITH_WARNINGS)
            or self.generation.state is not IndexGenerationState.ACTIVE
        ):
            raise IndexingPersistenceError("activated index result is invalid")


class IndexRepository(Protocol):
    """Persist and read candidate chunks in the active transaction."""

    def stage_candidate(self, candidate: CandidateChunkSet) -> None:
        """Stage one complete candidate generation and deterministic chunk set."""

        ...

    def list_generations(
        self,
        workspace_id: WorkspaceId,
        document_version_id: DocumentVersionId,
        processing_job_id: ProcessingJobId,
    ) -> tuple[PersistedIndexGeneration, ...]:
        """Return scoped persisted generations in deterministic order."""

        ...

    def replace_staging_candidate(self, candidate: CandidateChunkSet) -> None:
        """Replace one existing STAGING generation's complete chunk set."""

        ...

    def get_candidate(
        self,
        workspace_id: WorkspaceId,
        document_version_id: DocumentVersionId,
        index_generation_id: IndexGenerationId,
    ) -> CandidateChunkSet | None:
        """Return one exact workspace/version/generation candidate or None."""

        ...

    def get_activation_snapshot(
        self,
        workspace_id: WorkspaceId,
        document_version_id: DocumentVersionId,
        processing_job_id: ProcessingJobId,
        index_generation_id: IndexGenerationId,
    ) -> IndexActivationSnapshot:
        """Return the exact persisted lifecycle and embedding metadata."""

        ...

    def activate_candidate(self, update: IndexActivationUpdate) -> None:
        """Apply one guarded activation without committing or rolling back."""

        ...


def _require_non_negative_integer(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidIndexingInput(f"{name} is invalid")


def _require_utc(value: object) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise InvalidIndexingInput("chunk timestamp is invalid")
