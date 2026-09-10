"""Define Application-owned contracts for QA-scoped deterministic retrieval."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from lexlocal.application.ports.embeddings import (
    EMBEDDING_DTYPE,
    ChunkEmbedding,
    EmbeddingCompatibility,
)
from lexlocal.application.ports.indexing import PersistedIndexGeneration
from lexlocal.domain.documents import VersionNumber
from lexlocal.domain.identifiers import (
    ChunkId,
    DocumentId,
    DocumentVersionId,
    IndexGenerationId,
    LocalModelId,
    QaRequestId,
    RetrievalRunId,
    WorkspaceId,
)
from lexlocal.domain.processing import IndexGenerationState
from lexlocal.domain.retrieval import (
    Evidence,
    EvidenceAvailability,
    EvidenceRank,
    SimilarityScore,
    SourceLocator,
)

DEFAULT_RETRIEVAL_TOP_K = 5
MAX_RETRIEVAL_TOP_K = 20
DEFAULT_RETRIEVAL_MIN_SIMILARITY = SimilarityScore(0.0)
RETRIEVAL_POLICY_VERSION = "cosine-top-k-v1"


class RetrievalError(Exception):
    """Base exception for sanitized retrieval failures."""


class InvalidRetrievalInput(RetrievalError):
    """Report invalid QA retrieval input or configuration."""


class NoEligibleIndex(RetrievalError):
    """Report that the resolved QA scope has no eligible ACTIVE index."""


class IncompatibleRetrievalScope(RetrievalError):
    """Report that resolved ACTIVE generations do not form one cohort."""


class RetrievalIntegrityError(RetrievalError):
    """Report corrupt or inconsistent retrieval candidate data."""


class RetrievalPersistenceError(RetrievalError):
    """Report a sanitized retrieval persistence contract failure."""


@dataclass(frozen=True, slots=True)
class RetrievalConfiguration:
    """Carry the effective operational top-K and similarity threshold."""

    top_k: int = DEFAULT_RETRIEVAL_TOP_K
    min_similarity: SimilarityScore = DEFAULT_RETRIEVAL_MIN_SIMILARITY

    def __post_init__(self) -> None:
        if (
            isinstance(self.top_k, bool)
            or not isinstance(self.top_k, int)
            or not 1 <= self.top_k <= MAX_RETRIEVAL_TOP_K
            or not isinstance(self.min_similarity, SimilarityScore)
        ):
            raise InvalidRetrievalInput("retrieval configuration is invalid")


@dataclass(frozen=True, slots=True)
class QaRetrievalRequest:
    """Request retrieval for one existing QA owner and its exact query."""

    qa_request_id: QaRequestId
    workspace_id: WorkspaceId
    query: str = field(repr=False)
    document_ids: tuple[DocumentId, ...] | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.qa_request_id, QaRequestId)
            or not isinstance(self.workspace_id, WorkspaceId)
            or not isinstance(self.query, str)
            or not self.query.strip()
        ):
            raise InvalidRetrievalInput("QA retrieval request is invalid")
        if self.document_ids is not None and (
            not isinstance(self.document_ids, tuple)
            or not self.document_ids
            or not all(isinstance(item, DocumentId) for item in self.document_ids)
            or len(set(self.document_ids)) != len(self.document_ids)
        ):
            raise InvalidRetrievalInput("QA retrieval document scope is invalid")


@dataclass(frozen=True, slots=True)
class ResolvedRetrievalGeneration:
    """Bind one eligible ACTIVE generation to document snapshot metadata."""

    document_id: DocumentId
    version_number: VersionNumber
    document_display_name: str = field(repr=False)
    persisted: PersistedIndexGeneration

    def __post_init__(self) -> None:
        if (
            not isinstance(self.document_id, DocumentId)
            or not isinstance(self.version_number, VersionNumber)
            or not isinstance(self.document_display_name, str)
            or not self.document_display_name.strip()
            or not isinstance(self.persisted, PersistedIndexGeneration)
            or self.persisted.generation.state is not IndexGenerationState.ACTIVE
        ):
            raise NoEligibleIndex("resolved retrieval generation is not eligible")

    @property
    def workspace_id(self) -> WorkspaceId:
        return self.persisted.generation.workspace_id

    @property
    def document_version_id(self) -> DocumentVersionId:
        return self.persisted.generation.document_version_id

    @property
    def index_generation_id(self) -> IndexGenerationId:
        return self.persisted.generation.id

    @property
    def canonical_key(self) -> tuple[str, str, str]:
        return (
            str(self.document_id),
            str(self.document_version_id),
            str(self.index_generation_id),
        )


@dataclass(frozen=True, slots=True)
class ResolvedRetrievalScope:
    """Carry one exact QA scope whose ACTIVE generations form one cohort."""

    request: QaRetrievalRequest
    generations: tuple[ResolvedRetrievalGeneration, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.request, QaRetrievalRequest):
            raise InvalidRetrievalInput("resolved retrieval scope is invalid")
        if (
            not isinstance(self.generations, tuple)
            or not self.generations
            or not all(
                isinstance(item, ResolvedRetrievalGeneration) for item in self.generations
            )
        ):
            raise NoEligibleIndex("resolved retrieval scope has no eligible index")

        canonical = tuple(sorted(self.generations, key=lambda item: item.canonical_key))
        generation_ids = tuple(item.index_generation_id for item in canonical)
        version_ids = tuple(item.document_version_id for item in canonical)
        if len(set(generation_ids)) != len(generation_ids) or len(set(version_ids)) != len(
            version_ids
        ):
            raise RetrievalIntegrityError("resolved retrieval scope is inconsistent")
        if any(item.workspace_id != self.request.workspace_id for item in canonical):
            raise RetrievalIntegrityError("resolved retrieval ownership is inconsistent")
        if self.request.document_ids is not None and {
            item.document_id for item in canonical
        } != set(self.request.document_ids):
            raise RetrievalIntegrityError("resolved retrieval document scope is inconsistent")

        first = canonical[0].persisted.generation
        cohort = (
            first.embedding_model_id,
            first.chunking_profile_version,
            first.normalization_profile_version,
            first.embedding_dimensions,
        )
        if any(
            (
                item.persisted.generation.embedding_model_id,
                item.persisted.generation.chunking_profile_version,
                item.persisted.generation.normalization_profile_version,
                item.persisted.generation.embedding_dimensions,
            )
            != cohort
            for item in canonical[1:]
        ):
            raise IncompatibleRetrievalScope(
                "resolved retrieval generations are incompatible"
            )
        object.__setattr__(self, "generations", canonical)

    @property
    def representative(self) -> ResolvedRetrievalGeneration:
        """Return the canonical explicit target for one ephemeral query embedding."""

        return self.generations[0]

    @property
    def generation_ids(self) -> tuple[IndexGenerationId, ...]:
        return tuple(item.index_generation_id for item in self.generations)

    @property
    def embedding_model_id(self) -> LocalModelId:
        return self.representative.persisted.generation.embedding_model_id

    @property
    def query_compatibility(self) -> EmbeddingCompatibility:
        generation = self.representative.persisted.generation
        return EmbeddingCompatibility(
            workspace_id=generation.workspace_id,
            index_generation_id=generation.id,
            embedding_model_id=generation.embedding_model_id,
            chunking_profile_version=generation.chunking_profile_version,
            normalization_profile_version=generation.normalization_profile_version,
            dimensions=generation.embedding_dimensions,
        )


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    """Carry one fully validated chunk, vector, and source-provenance candidate."""

    generation: ResolvedRetrievalGeneration
    embedding: ChunkEmbedding = field(repr=False)
    document_order: int
    source_locator: SourceLocator
    passage: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.generation, ResolvedRetrievalGeneration)
            or not isinstance(self.embedding, ChunkEmbedding)
            or isinstance(self.document_order, bool)
            or not isinstance(self.document_order, int)
            or self.document_order < 0
            or not isinstance(self.source_locator, SourceLocator)
            or not isinstance(self.passage, str)
            or not self.passage
        ):
            raise RetrievalIntegrityError("retrieval candidate is invalid")

        expected = self.generation.persisted.generation
        compatibility = self.embedding.compatibility
        locator = self.source_locator
        if (
            compatibility.workspace_id != expected.workspace_id
            or compatibility.index_generation_id != expected.id
            or compatibility.embedding_model_id != expected.embedding_model_id
            or compatibility.chunking_profile_version
            != expected.chunking_profile_version
            or compatibility.normalization_profile_version
            != expected.normalization_profile_version
            or compatibility.dimensions != expected.embedding_dimensions
            or compatibility.dtype != EMBEDDING_DTYPE
            or compatibility.is_unit_normalized is not True
            or locator.workspace_id != expected.workspace_id
            or locator.document_version_id != expected.document_version_id
        ):
            raise RetrievalIntegrityError("retrieval candidate relationships are invalid")

    @property
    def chunk_id(self) -> ChunkId:
        return self.embedding.chunk_id


@dataclass(frozen=True, slots=True)
class RetrievalCandidateSet:
    """Carry the exact complete candidate set for the resolved generation scope."""

    scope: ResolvedRetrievalScope
    candidates: tuple[RetrievalCandidate, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.scope, ResolvedRetrievalScope)
            or not isinstance(self.candidates, tuple)
            or not self.candidates
            or not all(isinstance(item, RetrievalCandidate) for item in self.candidates)
        ):
            raise RetrievalIntegrityError("retrieval candidate set is incomplete")
        chunk_ids = tuple(item.chunk_id for item in self.candidates)
        positions = tuple(
            (item.generation.index_generation_id, item.document_order)
            for item in self.candidates
        )
        expected_generations = set(self.scope.generations)
        actual_generations = {item.generation for item in self.candidates}
        if (
            len(set(chunk_ids)) != len(chunk_ids)
            or len(set(positions)) != len(positions)
            or actual_generations != expected_generations
        ):
            raise RetrievalIntegrityError("retrieval candidate set is inconsistent")


@dataclass(frozen=True, slots=True)
class RankedRetrievalEvidence:
    """Carry one logical ranked passage before persistence identities exist."""

    rank: EvidenceRank
    similarity_score: SimilarityScore
    candidate: RetrievalCandidate

    def __post_init__(self) -> None:
        if (
            not isinstance(self.rank, EvidenceRank)
            or not isinstance(self.similarity_score, SimilarityScore)
            or not isinstance(self.candidate, RetrievalCandidate)
        ):
            raise RetrievalIntegrityError("ranked retrieval evidence is invalid")


@dataclass(frozen=True, slots=True)
class RetrievalRanking:
    """Return deterministic logical evidence and the exact pre-filter count."""

    scope: ResolvedRetrievalScope
    configuration: RetrievalConfiguration
    candidate_count: int
    evidence: tuple[RankedRetrievalEvidence, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.scope, ResolvedRetrievalScope)
            or not isinstance(self.configuration, RetrievalConfiguration)
            or isinstance(self.candidate_count, bool)
            or not isinstance(self.candidate_count, int)
            or self.candidate_count < 1
            or not isinstance(self.evidence, tuple)
            or not all(isinstance(item, RankedRetrievalEvidence) for item in self.evidence)
            or len(self.evidence) > self.configuration.top_k
            or tuple(item.rank.value for item in self.evidence)
            != tuple(range(1, len(self.evidence) + 1))
            or any(
                item.similarity_score.value
                < self.configuration.min_similarity.value
                for item in self.evidence
            )
        ):
            raise RetrievalIntegrityError("retrieval ranking is invalid")


@dataclass(frozen=True, slots=True)
class RetrievalEvidenceRegistration:
    """Carry one persistence-ready exact evidence and mutable-data snapshot."""

    evidence: Evidence
    index_generation_id: IndexGenerationId
    document_order: int
    source_locator: SourceLocator
    document_display_name: str = field(repr=False)
    version_number: VersionNumber
    excerpt: str = field(repr=False)
    created_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.evidence, Evidence)
            or not isinstance(self.index_generation_id, IndexGenerationId)
            or isinstance(self.document_order, bool)
            or not isinstance(self.document_order, int)
            or self.document_order < 0
            or not isinstance(self.source_locator, SourceLocator)
            or not isinstance(self.document_display_name, str)
            or not self.document_display_name.strip()
            or not isinstance(self.version_number, VersionNumber)
            or not isinstance(self.excerpt, str)
            or not self.excerpt
            or self.evidence.availability is not EvidenceAvailability.AVAILABLE
            or self.evidence.chunk_id is None
            or self.evidence.source_locator_id != self.source_locator.id
            or self.evidence.workspace_id != self.source_locator.workspace_id
            or self.evidence.document_version_id
            != self.source_locator.document_version_id
            or self.evidence.page_number != self.source_locator.page_number
        ):
            raise RetrievalPersistenceError("retrieval evidence registration is invalid")
        _require_utc(self.created_at)


@dataclass(frozen=True, slots=True)
class RetrievalRegistration:
    """Carry one complete immutable QA-owned retrieval persistence graph."""

    retrieval_run_id: RetrievalRunId
    scope: ResolvedRetrievalScope
    configuration: RetrievalConfiguration
    candidate_count: int
    evidence: tuple[RetrievalEvidenceRegistration, ...]
    created_at: datetime
    retrieval_policy_version: str = RETRIEVAL_POLICY_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.retrieval_run_id, RetrievalRunId)
            or not isinstance(self.scope, ResolvedRetrievalScope)
            or not isinstance(self.configuration, RetrievalConfiguration)
            or isinstance(self.candidate_count, bool)
            or not isinstance(self.candidate_count, int)
            or self.candidate_count < 1
            or not isinstance(self.evidence, tuple)
            or not all(
                isinstance(item, RetrievalEvidenceRegistration) for item in self.evidence
            )
            or len(self.evidence) > self.configuration.top_k
            or len(self.evidence) > self.candidate_count
            or self.retrieval_policy_version != RETRIEVAL_POLICY_VERSION
        ):
            raise RetrievalPersistenceError("retrieval registration is invalid")
        _require_utc(self.created_at)

        generations = {item.index_generation_id: item for item in self.scope.generations}
        if (
            tuple(item.evidence.rank.value for item in self.evidence)
            != tuple(range(1, len(self.evidence) + 1))
            or tuple(self.evidence) != tuple(sorted(self.evidence, key=_evidence_sort_key))
            or any(
            item.evidence.retrieval_run_id != self.retrieval_run_id
            or item.evidence.workspace_id != self.scope.request.workspace_id
            or item.index_generation_id not in generations
            or item.evidence.document_id
            != generations[item.index_generation_id].document_id
            or item.evidence.document_version_id
            != generations[item.index_generation_id].document_version_id
            or item.version_number != generations[item.index_generation_id].version_number
            or item.document_display_name
            != generations[item.index_generation_id].document_display_name
            or item.evidence.similarity_score.value
            < self.configuration.min_similarity.value
            for item in self.evidence
            )
        ):
            raise RetrievalPersistenceError("retrieval registration is inconsistent")

    @property
    def qa_request_id(self) -> QaRequestId:
        return self.scope.request.qa_request_id

    @property
    def workspace_id(self) -> WorkspaceId:
        return self.scope.request.workspace_id

    @property
    def embedding_model_id(self) -> LocalModelId:
        return self.scope.embedding_model_id


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Return one staged registration and whether a committed run was reused."""

    registration: RetrievalRegistration
    reused: bool

    def __post_init__(self) -> None:
        if not isinstance(self.registration, RetrievalRegistration) or not isinstance(
            self.reused, bool
        ):
            raise RetrievalPersistenceError("retrieval result is invalid")


class RetrievalRepository(Protocol):
    """Resolve and stage QA retrieval data in the caller-owned transaction."""

    def get_for_qa_request(
        self,
        workspace_id: WorkspaceId,
        qa_request_id: QaRequestId,
    ) -> RetrievalRegistration | None:
        """Return the complete committed run for one exact QA owner, when present."""

        ...

    def resolve_scope(self, request: QaRetrievalRequest) -> ResolvedRetrievalScope:
        """Resolve the authoritative narrowed QA scope and ACTIVE generations."""

        ...

    def load_candidates(self, scope: ResolvedRetrievalScope) -> RetrievalCandidateSet:
        """Load and validate the exact complete candidate vector graph."""

        ...

    def add(self, registration: RetrievalRegistration) -> None:
        """Stage one complete QA retrieval graph without transaction finalization."""

        ...


def _require_utc(value: object) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise RetrievalPersistenceError("retrieval timestamp is invalid")


def _evidence_sort_key(
    item: RetrievalEvidenceRegistration,
) -> tuple[float, str, str, str, int, str]:
    evidence = item.evidence
    return (
        -evidence.similarity_score.value,
        str(evidence.document_id),
        str(evidence.document_version_id),
        str(item.index_generation_id),
        item.document_order,
        str(evidence.chunk_id),
    )
