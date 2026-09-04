from datetime import UTC, datetime

import pytest

from lexlocal.application.ports.indexing import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    CandidateChunkSet,
    ChunkConfiguration,
    ChunkEqualityToken,
    ChunkProfile,
    IndexChunk,
    IndexingCancellationCheck,
    IndexingPersistenceError,
    IndexRepository,
    InvalidChunkConfiguration,
    InvalidIndexingInput,
    LogicalChunk,
    PersistedIndexGeneration,
    ReusedActiveIndex,
    StagingEmbeddingHandoff,
)
from lexlocal.application.ports.processing import PageExtractionMethod
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
    AttemptNumber,
    IndexGeneration,
    IndexGenerationState,
    ProcessingJob,
    ProcessingJobState,
)
from lexlocal.domain.retrieval import PageNumber

WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
VERSION_ID = DocumentVersionId("20000000-0000-4000-8000-000000000001")
PAGE_ID = DocumentPageId("30000000-0000-4000-8000-000000000001")
LOCATOR_ID = SourceLocatorId("40000000-0000-4000-8000-000000000001")
CHUNK_ID = ChunkId("50000000-0000-4000-8000-000000000001")
GENERATION_ID = IndexGenerationId("60000000-0000-4000-8000-000000000001")
JOB_ID = ProcessingJobId("70000000-0000-4000-8000-000000000001")
MODEL_ID = LocalModelId("80000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


class _Token:
    def fingerprint(self, chunk: LogicalChunk) -> bytes:
        return f"{chunk.document_order}:{chunk.text}".encode()


class _Cancellation:
    def raise_if_cancelled(self) -> None:
        return None


class _Repository:
    def stage_candidate(self, candidate: CandidateChunkSet) -> None:
        self.candidate = candidate

    def get_candidate(
        self,
        workspace_id: WorkspaceId,
        document_version_id: DocumentVersionId,
        index_generation_id: IndexGenerationId,
    ) -> CandidateChunkSet | None:
        return None

    def list_generations(
        self,
        workspace_id: WorkspaceId,
        document_version_id: DocumentVersionId,
        processing_job_id: ProcessingJobId,
    ) -> tuple[PersistedIndexGeneration, ...]:
        return ()

    def replace_staging_candidate(self, candidate: CandidateChunkSet) -> None:
        self.candidate = candidate


_TOKEN_CONFORMANCE: ChunkEqualityToken = _Token()
_CANCELLATION_CONFORMANCE: IndexingCancellationCheck = _Cancellation()
_REPOSITORY_CONFORMANCE: IndexRepository = _Repository()


def _logical(**overrides: object) -> LogicalChunk:
    values: dict[str, object] = {
        "workspace_id": WORKSPACE_ID,
        "document_version_id": VERSION_ID,
        "page_id": PAGE_ID,
        "page_number": PageNumber(1),
        "source_locator_id": LOCATOR_ID,
        "document_order": 0,
        "page_order": 0,
        "source_start_offset": 0,
        "source_end_offset": 4,
        "text": "text",
        "extraction_method": PageExtractionMethod.NATIVE,
        "profile": ChunkConfiguration(4, 1).profile,
    }
    values.update(overrides)
    return LogicalChunk(**values)  # type: ignore[arg-type]


def test_chunk_configuration_defaults_and_canonical_profile() -> None:
    configuration = ChunkConfiguration()

    assert configuration.chunk_size == DEFAULT_CHUNK_SIZE == 1000
    assert configuration.overlap == DEFAULT_CHUNK_OVERLAP == 200
    assert configuration.profile.value == (
        "page-codepoint-window-v1;unit=unicode-code-point;size=1000;overlap=200;"
        "boundary=page-source;warning=skip;text=exact-text;"
        "equality=chunk-equality-v1"
    )
    assert ChunkConfiguration(4, 1).profile == ChunkConfiguration(4, 1).profile
    assert ChunkConfiguration(5, 1).profile != ChunkConfiguration(4, 1).profile


@pytest.mark.parametrize(
    ("chunk_size", "overlap"),
    [(0, 0), (-1, 0), (True, 0), (1.0, 0), (4, -1), (4, 4), (4, 5), (4, True)],
)
def test_chunk_configuration_rejects_invalid_values(
    chunk_size: object,
    overlap: object,
) -> None:
    with pytest.raises(InvalidChunkConfiguration):
        ChunkConfiguration(chunk_size, overlap)  # type: ignore[arg-type]


def test_logical_chunk_preserves_exact_offsets_and_hides_text_from_repr() -> None:
    chunk = _logical(text="\nA ", source_end_offset=3)

    assert chunk.text == "\nA "
    assert chunk.source_start_offset == 0
    assert chunk.source_end_offset == 3
    assert "\nA " not in repr(chunk)


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_start_offset": -1},
        {"source_end_offset": 0},
        {"source_end_offset": 3},
        {"text": ""},
        {"document_order": True},
        {"page_order": -1},
    ],
)
def test_logical_chunk_rejects_invalid_contract_values(
    overrides: dict[str, object],
) -> None:
    with pytest.raises((InvalidIndexingInput, InvalidChunkConfiguration)):
        _logical(**overrides)


def test_chunk_profile_rejects_an_empty_identity() -> None:
    with pytest.raises(InvalidChunkConfiguration):
        ChunkProfile("")


def test_index_chunk_requires_injected_identity_token_and_utc_time() -> None:
    logical = _logical()
    chunk = IndexChunk(CHUNK_ID, logical, b"opaque", NOW)

    assert chunk.logical is logical
    assert "opaque" not in repr(chunk)
    with pytest.raises(InvalidIndexingInput):
        IndexChunk(CHUNK_ID, logical, b"", NOW)
    with pytest.raises(InvalidIndexingInput):
        IndexChunk(CHUNK_ID, logical, b"opaque", datetime(2026, 1, 2))


def test_candidate_chunk_set_requires_matching_generation_ownership() -> None:
    generation = IndexGeneration(
        id=GENERATION_ID,
        workspace_id=WORKSPACE_ID,
        document_version_id=VERSION_ID,
        processing_job_id=JOB_ID,
        embedding_model_id=MODEL_ID,
        chunking_profile_version=ChunkConfiguration(4, 1).profile.value,
        normalization_profile_version="exact-text-v1",
        embedding_dimensions=8,
    )
    chunk = IndexChunk(CHUNK_ID, _logical(), b"opaque", NOW)

    candidate = CandidateChunkSet(generation, (chunk,), NOW)
    assert candidate.chunks == (chunk,)
    assert candidate.created_at is NOW
    with pytest.raises(
        IndexingPersistenceError,
        match="candidate chunk relationships are invalid",
    ):
        CandidateChunkSet(
            generation,
            (
                IndexChunk(
                    CHUNK_ID,
                    _logical(workspace_id=WorkspaceId("10000000-0000-4000-8000-000000000002")),
                    b"opaque",
                    NOW,
                ),
            ),
            NOW,
        )

    with pytest.raises(
        IndexingPersistenceError,
        match="candidate generation state is invalid",
    ):
        CandidateChunkSet(
            IndexGeneration(
                id=GENERATION_ID,
                workspace_id=WORKSPACE_ID,
                document_version_id=VERSION_ID,
                processing_job_id=JOB_ID,
                embedding_model_id=MODEL_ID,
                chunking_profile_version=ChunkConfiguration(4, 1).profile.value,
                normalization_profile_version="exact-text-v1",
                embedding_dimensions=8,
                state=IndexGenerationState.ACTIVE,
            ),
            (chunk,),
            NOW,
        )

    with pytest.raises(
        IndexingPersistenceError,
        match="candidate generation timestamp is invalid",
    ):
        CandidateChunkSet(generation, (chunk,), datetime(2026, 1, 2))


def test_staging_and_active_results_are_explicitly_distinct() -> None:
    generation = IndexGeneration(
        GENERATION_ID,
        WORKSPACE_ID,
        VERSION_ID,
        JOB_ID,
        MODEL_ID,
        ChunkConfiguration(4, 1).profile.value,
        "exact-text-v1",
        8,
    )
    chunk = IndexChunk(CHUNK_ID, _logical(), b"opaque", NOW)
    candidate = CandidateChunkSet(generation, (chunk,), NOW)
    active = generation.activate(
        ProcessingJob(JOB_ID, WORKSPACE_ID, VERSION_ID, AttemptNumber(1), ProcessingJobState.READY)
    )

    staging_result = StagingEmbeddingHandoff(candidate)
    active_result = ReusedActiveIndex(PersistedIndexGeneration(active, NOW, NOW))

    assert staging_result.candidate.chunks == (chunk,)
    assert active_result.persisted.generation.id == GENERATION_ID
    assert not hasattr(active_result, "candidate")

    staging_result = StagingEmbeddingHandoff(candidate)
    active_result = ReusedActiveIndex(PersistedIndexGeneration(active, NOW, NOW))

    assert staging_result.candidate.chunks == (chunk,)
    assert active_result.persisted.generation.id == GENERATION_ID
    assert not hasattr(active_result, "candidate")
