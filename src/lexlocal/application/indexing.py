"""Build deterministic page-aware chunks from the processing handoff."""

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from lexlocal.application.ports.indexing import (
    ActivatedIndex,
    AmbiguousIndexGeneration,
    CandidateChunkSet,
    ChunkConfiguration,
    ChunkEqualityToken,
    ChunkingResult,
    IndexActivationSnapshot,
    IndexActivationUpdate,
    IndexChunk,
    IndexCompatibility,
    IndexingCancellationCheck,
    IndexingCancelled,
    IndexingError,
    IndexingPersistenceError,
    InvalidIndexingInput,
    LogicalChunk,
    NoEligibleChunks,
    PersistedIndexGeneration,
    ReusedActiveIndex,
    StagingEmbeddingHandoff,
)
from lexlocal.application.ports.local_models import ModelCapability, ResolvedModelRecord
from lexlocal.application.ports.processing import (
    ProcessedPage,
    ProcessedPageState,
    ProcessingResult,
)
from lexlocal.application.ports.unit_of_work import UnitOfWork
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.domain.documents import DocumentVersionState
from lexlocal.domain.identifiers import ChunkId, IndexGenerationId, WorkspaceId
from lexlocal.domain.processing import (
    IndexGeneration,
    IndexGenerationState,
    ProcessingJobState,
)


class BuildPageAwareChunks:
    """Build one complete deterministic chunk set without persistence."""

    def __init__(
        self,
        cancellation: IndexingCancellationCheck,
        equality_token: ChunkEqualityToken,
        chunk_id_factory: Callable[[], ChunkId],
        clock: Callable[[], datetime],
    ) -> None:
        self._cancellation = cancellation
        self._equality_token = equality_token
        self._chunk_id_factory = chunk_id_factory
        self._clock = clock

    def __call__(
        self,
        pages: Sequence[ProcessedPage],
        configuration: ChunkConfiguration | None = None,
        *,
        existing_candidate: CandidateChunkSet | None = None,
    ) -> ChunkingResult:
        config = ChunkConfiguration() if configuration is None else configuration
        if not isinstance(config, ChunkConfiguration):
            raise InvalidIndexingInput("chunk configuration is invalid")
        ordered_pages = self._validate_pages(pages)
        profile = config.profile
        chunks: list[IndexChunk] = []

        self._checkpoint()
        for page in ordered_pages:
            self._checkpoint()
            if page.state is ProcessedPageState.WARNING:
                continue
            page_order = 0
            start = 0
            while start < len(page.text):
                self._checkpoint()
                end = min(start + config.chunk_size, len(page.text))
                logical = LogicalChunk(
                    workspace_id=page.workspace_id,
                    document_version_id=page.document_version_id,
                    page_id=page.id,
                    page_number=page.page_number,
                    source_locator_id=page.source_locator.id,
                    document_order=len(chunks),
                    page_order=page_order,
                    source_start_offset=start,
                    source_end_offset=end,
                    text=page.text[start:end],
                    extraction_method=page.extraction_method,
                    profile=profile,
                )
                existing_chunk = (
                    existing_candidate.chunks[len(chunks)]
                    if existing_candidate is not None
                    and len(chunks) < len(existing_candidate.chunks)
                    else None
                )
                chunks.append(self._materialize(logical, existing_chunk))
                if end == len(page.text):
                    break
                start = end - config.overlap
                page_order += 1

        if not chunks:
            raise NoEligibleChunks("processing handoff contains no eligible chunks")
        self._checkpoint()
        candidate_created_at = (
            existing_candidate.created_at if existing_candidate is not None else self._utc_now()
        )
        return ChunkingResult(profile, tuple(chunks), candidate_created_at)

    @staticmethod
    def _validate_pages(pages: Sequence[ProcessedPage]) -> tuple[ProcessedPage, ...]:
        if isinstance(pages, (str, bytes)):
            raise InvalidIndexingInput("processing page handoff is invalid")
        try:
            result = tuple(pages)
        except Exception:
            raise InvalidIndexingInput("processing page handoff is invalid") from None
        if not result or not all(isinstance(page, ProcessedPage) for page in result):
            raise InvalidIndexingInput("processing page handoff is invalid")
        if tuple(page.page_number.value for page in result) != tuple(range(1, len(result) + 1)):
            raise InvalidIndexingInput("processing page order is invalid")
        first = result[0]
        if any(
            page.workspace_id != first.workspace_id
            or page.document_version_id != first.document_version_id
            for page in result
        ):
            raise InvalidIndexingInput("processing page ownership is invalid")
        if len({page.id for page in result}) != len(result) or len(
            {page.source_locator.id for page in result}
        ) != len(result):
            raise InvalidIndexingInput("processing page identity is invalid")
        return result

    def _materialize(
        self,
        logical: LogicalChunk,
        existing_chunk: IndexChunk | None,
    ) -> IndexChunk:
        try:
            token = self._equality_token.fingerprint(logical)
        except Exception:
            raise InvalidIndexingInput("chunk dependency returned invalid data") from None
        if existing_chunk is not None and existing_chunk.logical == logical:
            return IndexChunk(
                existing_chunk.id,
                logical,
                token,
                existing_chunk.created_at,
            )
        try:
            chunk_id = self._chunk_id_factory()
        except Exception:
            raise InvalidIndexingInput("chunk dependency returned invalid data") from None
        if not isinstance(chunk_id, ChunkId):
            raise InvalidIndexingInput("chunk identity factory returned invalid data")
        created_at = self._utc_now()
        return IndexChunk(chunk_id, logical, token, created_at)

    def _utc_now(self) -> datetime:
        try:
            value = self._clock()
        except Exception:
            raise InvalidIndexingInput("chunk clock failed") from None
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() != timedelta(0)
        ):
            raise InvalidIndexingInput("chunk clock returned invalid data")
        return value

    def _checkpoint(self) -> None:
        try:
            self._cancellation.raise_if_cancelled()
        except IndexingCancelled:
            raise IndexingCancelled("indexing was cancelled") from None
        except Exception:
            raise InvalidIndexingInput("cancellation check failed") from None


def select_compatible_generation(
    generations: tuple[PersistedIndexGeneration, ...],
    requested: IndexCompatibility,
) -> PersistedIndexGeneration | None:
    """Select one compatible ACTIVE/STAGING generation or fail on ambiguity."""

    if not isinstance(generations, tuple) or not all(
        isinstance(item, PersistedIndexGeneration) for item in generations
    ):
        raise InvalidIndexingInput("persisted generation discovery is invalid")
    if not isinstance(requested, IndexCompatibility):
        raise InvalidIndexingInput("requested generation metadata is invalid")
    compatible = tuple(
        item
        for item in generations
        if item.generation.state in (IndexGenerationState.STAGING, IndexGenerationState.ACTIVE)
        and _same_compatibility(item.generation, requested)
    )
    if len(compatible) > 1:
        raise AmbiguousIndexGeneration("compatible index generation is ambiguous")
    return compatible[0] if compatible else None


def _same_compatibility(left: IndexGeneration, right: IndexCompatibility) -> bool:
    return (
        left.workspace_id == right.workspace_id
        and left.document_version_id == right.document_version_id
        and left.processing_job_id == right.processing_job_id
        and left.embedding_model_id == right.embedding_model_id
        and left.chunking_profile_version == right.chunking_profile_version
        and left.normalization_profile_version == right.normalization_profile_version
        and left.embedding_dimensions == right.embedding_dimensions
    )


class PrepareIndexing:
    """Prepare or reuse one index generation for the active workspace."""

    def __init__(
        self,
        active_scope: ActiveWorkspaceScope,
        model: ResolvedModelRecord,
        cancellation: IndexingCancellationCheck,
        equality_token: ChunkEqualityToken,
        unit_of_work_factory: Callable[[], UnitOfWork],
        chunk_id_factory: Callable[[], ChunkId],
        index_generation_id_factory: Callable[[], IndexGenerationId],
        clock: Callable[[], datetime],
    ) -> None:
        self._active_scope = active_scope
        self._model = model
        self._cancellation = cancellation
        self._unit_of_work_factory = unit_of_work_factory
        self._index_generation_id_factory = index_generation_id_factory
        self._chunker = BuildPageAwareChunks(
            cancellation,
            equality_token,
            chunk_id_factory,
            clock,
        )

    def __call__(
        self,
        processing: ProcessingResult,
        configuration: ChunkConfiguration | None = None,
    ) -> StagingEmbeddingHandoff | ReusedActiveIndex:
        """Return an exact persisted staging handoff or reuse a compatible active index."""

        workspace_id = self._workspace_id()
        compatibility = self._compatibility(workspace_id, processing, configuration)
        self._checkpoint()
        try:
            with self._unit_of_work_factory() as read_uow:
                discovered = read_uow.indexing.list_generations(
                    workspace_id,
                    processing.document_version_id,
                    processing.processing_job_id,
                )
                selected = select_compatible_generation(discovered, compatibility)
                existing_candidate = self._existing_staging_candidate(
                    read_uow,
                    workspace_id,
                    processing,
                    selected,
                )
        except IndexingError:
            raise
        except Exception:
            raise IndexingPersistenceError("index generation discovery failed") from None

        self._checkpoint()
        if selected is not None and selected.generation.state is IndexGenerationState.ACTIVE:
            self._checkpoint()
            return ReusedActiveIndex(selected)

        result = self._chunker(
            processing.pages,
            configuration,
            existing_candidate=existing_candidate,
        )
        self._checkpoint()
        try:
            with self._unit_of_work_factory() as write_uow:
                current = write_uow.indexing.list_generations(
                    workspace_id,
                    processing.document_version_id,
                    processing.processing_job_id,
                )
                selected = select_compatible_generation(current, compatibility)
                if (
                    selected is not None
                    and selected.generation.state is IndexGenerationState.ACTIVE
                ):
                    self._checkpoint()
                    return ReusedActiveIndex(selected)
                if not self._same_staging_selection(selected, existing_candidate):
                    raise IndexingPersistenceError("index generation changed during preparation")
                candidate = self._candidate(result, compatibility, selected)
                if selected is None:
                    write_uow.indexing.stage_candidate(candidate)
                else:
                    write_uow.indexing.replace_staging_candidate(candidate)
                persisted = write_uow.indexing.get_candidate(
                    workspace_id,
                    processing.document_version_id,
                    candidate.generation.id,
                )
                if persisted is None:
                    raise IndexingPersistenceError("persisted candidate is unavailable")
                self._checkpoint()
                write_uow.commit()
        except IndexingCancelled:
            raise
        except AmbiguousIndexGeneration:
            raise
        except Exception:
            raise IndexingPersistenceError("index candidate persistence failed") from None

        self._checkpoint()
        return StagingEmbeddingHandoff(persisted)

    @staticmethod
    def _existing_staging_candidate(
        read_uow: UnitOfWork,
        workspace_id: WorkspaceId,
        processing: ProcessingResult,
        selected: PersistedIndexGeneration | None,
    ) -> CandidateChunkSet | None:
        if selected is None or selected.generation.state is IndexGenerationState.ACTIVE:
            return None
        candidate = read_uow.indexing.get_candidate(
            workspace_id,
            processing.document_version_id,
            selected.generation.id,
        )
        if candidate is None:
            raise IndexingPersistenceError("persisted staging candidate is unavailable")
        return candidate

    @staticmethod
    def _same_staging_selection(
        selected: PersistedIndexGeneration | None,
        existing_candidate: CandidateChunkSet | None,
    ) -> bool:
        if existing_candidate is None:
            return selected is None
        return (
            selected is not None
            and selected.generation.state is IndexGenerationState.STAGING
            and selected.generation.id == existing_candidate.generation.id
        )

    def _workspace_id(self) -> WorkspaceId:
        try:
            return self._active_scope.require_workspace_id()
        except Exception:
            raise IndexingPersistenceError("active workspace is unavailable") from None

    def _compatibility(
        self,
        workspace_id: WorkspaceId,
        processing: ProcessingResult,
        configuration: ChunkConfiguration | None,
    ) -> IndexCompatibility:
        if not isinstance(processing, ProcessingResult):
            raise InvalidIndexingInput("processing handoff is invalid")
        if any(page.workspace_id != workspace_id for page in processing.pages):
            raise InvalidIndexingInput("processing handoff ownership is invalid")
        if (
            not isinstance(self._model, ResolvedModelRecord)
            or self._model.capability is not ModelCapability.EMBEDDING
            or self._model.dimensions is None
        ):
            raise InvalidIndexingInput("embedding model identity is invalid")
        config = ChunkConfiguration() if configuration is None else configuration
        if not isinstance(config, ChunkConfiguration):
            raise InvalidIndexingInput("chunk configuration is invalid")
        return IndexCompatibility(
            workspace_id,
            processing.document_version_id,
            processing.processing_job_id,
            self._model.id,
            config.profile.value,
            "exact-text-v1",
            self._model.dimensions,
        )

    def _candidate(
        self,
        result: ChunkingResult,
        compatibility: IndexCompatibility,
        selected: PersistedIndexGeneration | None,
    ) -> CandidateChunkSet:
        if selected is not None:
            if selected.generation.state is not IndexGenerationState.STAGING:
                raise IndexingPersistenceError("selected generation state is invalid")
            return CandidateChunkSet(
                selected.generation,
                result.chunks,
                selected.created_at,
            )
        try:
            generation_id = self._index_generation_id_factory()
        except Exception:
            raise IndexingPersistenceError("generation identity factory failed") from None
        if not isinstance(generation_id, IndexGenerationId):
            raise IndexingPersistenceError("generation identity factory returned invalid data")
        return result.for_generation(
            IndexGeneration(
                generation_id,
                compatibility.workspace_id,
                compatibility.document_version_id,
                compatibility.processing_job_id,
                compatibility.embedding_model_id,
                compatibility.chunking_profile_version,
                compatibility.normalization_profile_version,
                compatibility.embedding_dimensions,
            )
        )

    def _checkpoint(self) -> None:
        try:
            self._cancellation.raise_if_cancelled()
        except IndexingCancelled:
            raise IndexingCancelled("indexing was cancelled") from None
        except Exception:
            raise IndexingPersistenceError("cancellation check failed") from None


class FinalizeIndexing:
    """Atomically activate one exact, completely embedded staging candidate."""

    def __init__(
        self,
        active_scope: ActiveWorkspaceScope,
        cancellation: IndexingCancellationCheck,
        unit_of_work_factory: Callable[[], UnitOfWork],
        clock: Callable[[], datetime],
    ) -> None:
        self._active_scope = active_scope
        self._cancellation = cancellation
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock

    def __call__(self, handoff: StagingEmbeddingHandoff) -> ActivatedIndex:
        """Finalize only a complete compatible persisted embedding set."""

        workspace_id = self._workspace_id()
        if not isinstance(handoff, StagingEmbeddingHandoff):
            raise InvalidIndexingInput("staging embedding handoff is invalid")
        candidate = handoff.candidate
        generation = candidate.generation
        if generation.workspace_id != workspace_id:
            raise InvalidIndexingInput("staging embedding handoff ownership is invalid")
        self._checkpoint()
        try:
            with self._unit_of_work_factory() as unit_of_work:
                snapshot = unit_of_work.indexing.get_activation_snapshot(
                    workspace_id,
                    generation.document_version_id,
                    generation.processing_job_id,
                    generation.id,
                )
                update = self._activation_update(handoff, snapshot)
                unit_of_work.indexing.activate_candidate(update)
                unit_of_work.commit()
        except IndexingCancelled:
            raise
        except IndexingError:
            raise
        except Exception:
            raise IndexingPersistenceError("index activation failed") from None
        return ActivatedIndex(update.version, update.job, update.generation)

    def _activation_update(
        self,
        handoff: StagingEmbeddingHandoff,
        snapshot: IndexActivationSnapshot,
    ) -> IndexActivationUpdate:
        candidate = handoff.candidate
        if snapshot.candidate != candidate:
            raise IndexingPersistenceError("activation candidate is stale")
        generation = candidate.generation
        expected_chunk_ids = tuple(chunk.id for chunk in candidate.chunks)
        embedded_chunk_ids = tuple(item.chunk_id for item in snapshot.embeddings)
        if (
            len(embedded_chunk_ids) != len(expected_chunk_ids)
            or len(set(embedded_chunk_ids)) != len(embedded_chunk_ids)
            or set(embedded_chunk_ids) != set(expected_chunk_ids)
            or any(
                item.workspace_id != generation.workspace_id
                or item.index_generation_id != generation.id
                or item.embedding_model_id != generation.embedding_model_id
                or item.dimensions != generation.embedding_dimensions
                or item.dtype != "float32"
                or not item.is_unit_normalized
                or not item.has_payload
                for item in snapshot.embeddings
            )
        ):
            raise IndexingPersistenceError("candidate embeddings are incomplete or incompatible")
        if (
            snapshot.version.workspace_id != generation.workspace_id
            or snapshot.version.id != generation.document_version_id
            or snapshot.version.state is not DocumentVersionState.CANDIDATE_PROCESSING
            or snapshot.job.workspace_id != generation.workspace_id
            or snapshot.job.id != generation.processing_job_id
            or snapshot.job.document_version_id != generation.document_version_id
            or snapshot.job.state is not ProcessingJobState.PROCESSING
            or snapshot.job_stage != "CHUNKING"
        ):
            raise IndexingPersistenceError("activation lifecycle is stale")
        if (snapshot.previous_version is None) != (snapshot.previous_generation is None):
            raise IndexingPersistenceError("previous active index lifecycle is invalid")
        if snapshot.previous_version is not None and snapshot.previous_generation is not None:
            if (
                snapshot.previous_version.workspace_id != generation.workspace_id
                or snapshot.previous_version.document_id != snapshot.version.document_id
                or snapshot.previous_version.state is not DocumentVersionState.ACTIVE
                or snapshot.previous_generation.generation.workspace_id != generation.workspace_id
                or snapshot.previous_generation.generation.document_version_id
                != snapshot.previous_version.id
                or snapshot.previous_generation.generation.state is not IndexGenerationState.ACTIVE
            ):
                raise IndexingPersistenceError("previous active index lifecycle is invalid")
        try:
            terminal_job = snapshot.job.transition_to(
                ProcessingJobState.READY_WITH_WARNINGS
                if snapshot.has_warnings
                else ProcessingJobState.READY
            )
            ready_version = snapshot.version.transition_to(
                DocumentVersionState.CANDIDATE_WARNING
                if snapshot.has_warnings
                else DocumentVersionState.CANDIDATE_READY
            )
            active_version = ready_version.transition_to(DocumentVersionState.ACTIVE)
            active_generation = generation.activate(terminal_job)
        except Exception:
            raise IndexingPersistenceError("activation lifecycle is invalid") from None
        return IndexActivationUpdate(
            candidate,
            active_version,
            terminal_job,
            active_generation,
            self._utc_now(),
            snapshot.has_warnings,
        )

    def _workspace_id(self) -> WorkspaceId:
        try:
            return self._active_scope.require_workspace_id()
        except Exception:
            raise IndexingPersistenceError("active workspace is unavailable") from None

    def _checkpoint(self) -> None:
        try:
            self._cancellation.raise_if_cancelled()
        except IndexingCancelled:
            raise IndexingCancelled("indexing was cancelled") from None
        except Exception:
            raise IndexingPersistenceError("cancellation check failed") from None

    def _utc_now(self) -> datetime:
        try:
            value = self._clock()
        except Exception:
            raise IndexingPersistenceError("index activation clock failed") from None
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() != timedelta(0)
        ):
            raise IndexingPersistenceError("index activation clock returned invalid data")
        return value
