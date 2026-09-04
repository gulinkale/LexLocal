from datetime import UTC, datetime, timedelta

import pytest

from lexlocal.application.indexing import (
    BuildPageAwareChunks,
    select_compatible_generation,
)
from lexlocal.application.ports.indexing import (
    AmbiguousIndexGeneration,
    ChunkConfiguration,
    IndexCompatibility,
    IndexingCancellationCheck,
    IndexingCancelled,
    InvalidIndexingInput,
    LogicalChunk,
    NoEligibleChunks,
    PersistedIndexGeneration,
)
from lexlocal.application.ports.processing import (
    PageExtractionMethod,
    ProcessedPage,
    ProcessedPageState,
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
from lexlocal.domain.processing import IndexGeneration, IndexGenerationState
from lexlocal.domain.retrieval import PageNumber, SourceLocator, SourceLocatorKind

WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
VERSION_ID = DocumentVersionId("20000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
GENERATION_ID = IndexGenerationId("60000000-0000-4000-8000-000000000001")
JOB_ID = ProcessingJobId("70000000-0000-4000-8000-000000000001")
MODEL_ID = LocalModelId("80000000-0000-4000-8000-000000000001")


def _identifier(kind: type[ChunkId], number: int) -> ChunkId:
    return kind(f"50000000-0000-4000-8000-{number:012d}")


def _page(
    number: int,
    text: str,
    *,
    workspace_id: WorkspaceId = WORKSPACE_ID,
    version_id: DocumentVersionId = VERSION_ID,
) -> ProcessedPage:
    page_id = DocumentPageId(f"30000000-0000-4000-8000-{number:012d}")
    page_number = PageNumber(number)
    locator = SourceLocator(
        id=SourceLocatorId(f"40000000-0000-4000-8000-{number:012d}"),
        workspace_id=workspace_id,
        document_version_id=version_id,
        page_id=page_id,
        page_number=page_number,
        kind=SourceLocatorKind.PAGE,
    )
    return ProcessedPage(
        id=page_id,
        workspace_id=workspace_id,
        document_version_id=version_id,
        page_number=page_number,
        text=text,
        state=(
            ProcessedPageState.READY
            if any(not character.isspace() for character in text)
            else ProcessedPageState.WARNING
        ),
        extraction_method=PageExtractionMethod.NATIVE,
        source_locator=locator,
    )


def _generation(
    *,
    generation_id: IndexGenerationId = GENERATION_ID,
    state: IndexGenerationState = IndexGenerationState.STAGING,
    profile: str | None = None,
) -> IndexGeneration:
    return IndexGeneration(
        generation_id,
        WORKSPACE_ID,
        VERSION_ID,
        JOB_ID,
        MODEL_ID,
        profile or ChunkConfiguration(4, 1).profile.value,
        "exact-text-v1",
        8,
        state,
    )


def _compatibility(*, profile: str | None = None) -> IndexCompatibility:
    return IndexCompatibility(
        WORKSPACE_ID,
        VERSION_ID,
        JOB_ID,
        MODEL_ID,
        profile or ChunkConfiguration(4, 1).profile.value,
        "exact-text-v1",
        8,
    )


class _NeverCancelled:
    def raise_if_cancelled(self) -> None:
        return None


class _CancelAt:
    def __init__(self, call: int) -> None:
        self._call = call
        self.calls = 0

    def raise_if_cancelled(self) -> None:
        self.calls += 1
        if self.calls == self._call:
            raise IndexingCancelled("fixture detail")


class _Token:
    def fingerprint(self, chunk: LogicalChunk) -> bytes:
        return (
            f"{chunk.workspace_id}:{chunk.document_version_id}:{chunk.page_id}:"
            f"{chunk.source_locator_id}:{chunk.profile.value}:"
            f"{chunk.source_start_offset}:{chunk.source_end_offset}:"
            f"{chunk.document_order}:{chunk.page_order}:{chunk.text}"
        ).encode()


class _Ids:
    def __init__(self, start: int = 1) -> None:
        self.next = start
        self.calls = 0

    def __call__(self) -> ChunkId:
        result = _identifier(ChunkId, self.next)
        self.next += 1
        self.calls += 1
        return result


class _Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        return self.value


class _SequenceClock:
    def __init__(self, *values: datetime) -> None:
        self._values = iter(values)
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        return next(self._values)


def _build(
    *,
    cancellation: IndexingCancellationCheck | None = None,
    ids: _Ids | None = None,
    clock: _Clock | None = None,
) -> tuple[BuildPageAwareChunks, _Ids, _Clock]:
    id_factory = _Ids() if ids is None else ids
    clock_factory = _Clock() if clock is None else clock
    return (
        BuildPageAwareChunks(
            cancellation=_NeverCancelled() if cancellation is None else cancellation,
            equality_token=_Token(),
            chunk_id_factory=id_factory,
            clock=clock_factory,
        ),
        id_factory,
        clock_factory,
    )


@pytest.mark.parametrize(
    ("text", "expected_texts", "expected_offsets"),
    [
        ("abc", ["abc"], [(0, 3)]),
        ("abcd", ["abcd"], [(0, 4)]),
        ("abcde", ["abcd", "de"], [(0, 4), (3, 5)]),
        ("abcdefghij", ["abcd", "defg", "ghij"], [(0, 4), (3, 7), (6, 10)]),
    ],
)
def test_sliding_windows_preserve_exact_text_and_offsets(
    text: str,
    expected_texts: list[str],
    expected_offsets: list[tuple[int, int]],
) -> None:
    build, _, _ = _build()

    result = build((_page(1, text),), ChunkConfiguration(4, 1))

    assert [chunk.text for chunk in result.logical_chunks] == expected_texts
    assert [
        (chunk.source_start_offset, chunk.source_end_offset) for chunk in result.logical_chunks
    ] == expected_offsets
    assert all(
        chunk.text == text[chunk.source_start_offset : chunk.source_end_offset]
        for chunk in result.logical_chunks
    )
    assert [chunk.page_order for chunk in result.logical_chunks] == list(range(len(expected_texts)))


def test_unicode_positions_and_whitespace_are_preserved_exactly() -> None:
    text = " é\nA 𐍈 "
    build, _, _ = _build()

    chunks = build((_page(1, text),), ChunkConfiguration(4, 1)).logical_chunks

    assert [chunk.text for chunk in chunks] == [text[0:4], text[3:7]]
    assert "".join(chunk.text for chunk in chunks) != text
    assert chunks[0].text.startswith(" ")
    assert chunks[-1].text.endswith(" ")
    assert "\n" in chunks[0].text


def test_pages_and_locators_remain_separate_with_explicit_document_order() -> None:
    pages = (_page(1, "abcde"), _page(2, "vwxyz"))
    build, _, _ = _build()

    chunks = build(pages, ChunkConfiguration(4, 1)).logical_chunks

    assert [chunk.document_order for chunk in chunks] == [0, 1, 2, 3]
    assert [chunk.page_order for chunk in chunks] == [0, 1, 0, 1]
    assert [chunk.page_number.value for chunk in chunks] == [1, 1, 2, 2]
    assert [chunk.page_id for chunk in chunks] == [
        pages[0].id,
        pages[0].id,
        pages[1].id,
        pages[1].id,
    ]
    assert [chunk.source_locator_id for chunk in chunks] == [
        pages[0].source_locator.id,
        pages[0].source_locator.id,
        pages[1].source_locator.id,
        pages[1].source_locator.id,
    ]


def test_warning_pages_produce_zero_chunks_in_a_mixed_handoff() -> None:
    pages = (_page(1, "ready"), _page(2, " \n\t"), _page(3, "also ready"))
    build, ids, clock = _build()

    chunks = build(pages, ChunkConfiguration(20, 0)).logical_chunks

    assert [chunk.page_number.value for chunk in chunks] == [1, 3]
    assert [chunk.document_order for chunk in chunks] == [0, 1]
    assert ids.calls == 2
    assert clock.calls == 3


def test_no_eligible_chunks_is_sanitized_and_creates_no_identified_chunk() -> None:
    build, ids, clock = _build()

    with pytest.raises(NoEligibleChunks, match="no eligible chunks") as captured:
        build((_page(1, " \n"),), ChunkConfiguration(4, 1))

    assert ids.calls == clock.calls == 0
    assert "\n" not in str(captured.value)


def test_logical_output_is_independent_from_injected_ids_and_time() -> None:
    first, first_ids, first_clock = _build(ids=_Ids(1), clock=_Clock(NOW))
    second, second_ids, second_clock = _build(
        ids=_Ids(50),
        clock=_Clock(NOW + timedelta(days=1)),
    )
    pages = (_page(1, "abcdefgh"),)
    config = ChunkConfiguration(3, 1)

    first_result = first(pages, config)
    second_result = second(pages, config)

    assert first_result.logical_chunks == second_result.logical_chunks
    assert [chunk.id for chunk in first_result.chunks] != [
        chunk.id for chunk in second_result.chunks
    ]
    assert first_ids.calls == second_ids.calls == 4
    assert first_clock.calls == second_clock.calls == 5
    assert first_result.candidate_created_at == NOW
    assert second_result.candidate_created_at == NOW + timedelta(days=1)


def test_candidate_uses_the_separate_injected_generation_timestamp() -> None:
    chunk_time = NOW
    candidate_time = NOW + timedelta(seconds=1)
    clock = _SequenceClock(chunk_time, candidate_time)
    build = BuildPageAwareChunks(
        cancellation=_NeverCancelled(),
        equality_token=_Token(),
        chunk_id_factory=_Ids(),
        clock=clock,
    )
    result = build((_page(1, "abc"),), ChunkConfiguration(4, 1))
    generation = IndexGeneration(
        id=IndexGenerationId("60000000-0000-4000-8000-000000000001"),
        workspace_id=WORKSPACE_ID,
        document_version_id=VERSION_ID,
        processing_job_id=ProcessingJobId("70000000-0000-4000-8000-000000000001"),
        embedding_model_id=LocalModelId("80000000-0000-4000-8000-000000000001"),
        chunking_profile_version=result.profile.value,
        normalization_profile_version="exact-text-v1",
        embedding_dimensions=8,
    )
    candidate = result.for_generation(generation)

    assert result.chunks[0].created_at == chunk_time
    assert result.candidate_created_at == candidate_time
    assert candidate.created_at == candidate_time
    assert clock.calls == 2


def test_non_utc_candidate_clock_value_is_rejected() -> None:
    build, _, _ = _build(clock=_Clock(datetime(2026, 1, 2)))

    with pytest.raises(InvalidIndexingInput, match="clock returned invalid data"):
        build((_page(1, "abc"),), ChunkConfiguration(4, 1))


@pytest.mark.parametrize("cancel_call", [1, 2, 3, 4])
def test_cancellation_never_returns_a_successful_result(cancel_call: int) -> None:
    cancellation = _CancelAt(cancel_call)
    build, _, _ = _build(cancellation=cancellation)

    with pytest.raises(IndexingCancelled, match="indexing was cancelled") as captured:
        build((_page(1, "abcdefgh"),), ChunkConfiguration(3, 1))

    assert "fixture detail" not in str(captured.value)


def test_page_order_or_ownership_mismatch_is_rejected_without_values() -> None:
    build, _, _ = _build()
    other_workspace = WorkspaceId("10000000-0000-4000-8000-000000000002")

    with pytest.raises(InvalidIndexingInput, match="page order is invalid"):
        build((_page(2, "second"), _page(1, "first")))
    with pytest.raises(InvalidIndexingInput, match="page ownership is invalid") as error:
        build((_page(1, "first"), _page(2, "second", workspace_id=other_workspace)))

    assert str(other_workspace) not in str(error.value)


def test_invalid_dependencies_are_sanitized() -> None:
    class BadToken:
        def fingerprint(self, chunk: LogicalChunk) -> bytes:
            raise RuntimeError(chunk.text)

    build = BuildPageAwareChunks(
        cancellation=_NeverCancelled(),
        equality_token=BadToken(),
        chunk_id_factory=_Ids(),
        clock=_Clock(),
    )

    with pytest.raises(InvalidIndexingInput, match="dependency returned invalid data") as error:
        build((_page(1, "sensitive fixture"),), ChunkConfiguration(20, 0))

    assert "sensitive fixture" not in str(error.value)


def test_generation_classification_selects_none_staging_or_active() -> None:
    requested = _compatibility()
    staging = PersistedIndexGeneration(_generation(), NOW)
    active = PersistedIndexGeneration(_generation(state=IndexGenerationState.ACTIVE), NOW, NOW)

    assert select_compatible_generation((), requested) is None
    assert select_compatible_generation((staging,), requested) is staging
    assert select_compatible_generation((active,), requested) is active


def test_incompatible_generation_is_visible_but_not_selected() -> None:
    requested = _compatibility()
    incompatible = PersistedIndexGeneration(
        _generation(profile=ChunkConfiguration(5, 1).profile.value), NOW
    )

    assert select_compatible_generation((incompatible,), requested) is None


@pytest.mark.parametrize(
    "states",
    [
        (IndexGenerationState.STAGING, IndexGenerationState.STAGING),
        (IndexGenerationState.ACTIVE, IndexGenerationState.ACTIVE),
        (IndexGenerationState.ACTIVE, IndexGenerationState.STAGING),
    ],
)
def test_multiple_compatible_generations_fail_closed(
    states: tuple[IndexGenerationState, IndexGenerationState],
) -> None:
    requested = _compatibility()
    persisted = tuple(
        PersistedIndexGeneration(
            _generation(
                generation_id=IndexGenerationId(f"60000000-0000-4000-8000-{index + 2:012d}"),
                state=state,
            ),
            NOW + timedelta(seconds=index),
            NOW if state is IndexGenerationState.ACTIVE else None,
        )
        for index, state in enumerate(states)
    )

    with pytest.raises(AmbiguousIndexGeneration, match="ambiguous"):
        select_compatible_generation(persisted, requested)
