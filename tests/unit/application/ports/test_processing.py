"""Tests for Application-owned native processing contracts."""

from collections.abc import Iterable
from datetime import UTC, datetime

import pytest

from lexlocal.application.ports.processing import (
    CancellationCheck,
    NativePdfPage,
    NativePdfTextExtractor,
    PageExtractionMethod,
    ProcessedPage,
    ProcessedPageState,
    ProcessingCancelled,
    ProcessingPageBatch,
    ProcessingPersistenceError,
    ProcessingTarget,
)
from lexlocal.domain.identifiers import (
    DocumentId,
    DocumentPageId,
    DocumentVersionId,
    ProcessingJobId,
    SourceLocatorId,
    WorkspaceId,
)
from lexlocal.domain.retrieval import PageNumber, SourceLocator, SourceLocatorKind

_WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
_VERSION_ID = DocumentVersionId("10000000-0000-4000-8000-000000000003")
_TARGET = ProcessingTarget(
    workspace_id=_WORKSPACE_ID,
    document_id=DocumentId("10000000-0000-4000-8000-000000000002"),
    document_version_id=_VERSION_ID,
    processing_job_id=ProcessingJobId("10000000-0000-4000-8000-000000000004"),
    expected_page_count=1,
)


def _page(text: str = "exact synthetic text") -> ProcessedPage:
    page_id = DocumentPageId("10000000-0000-4000-8000-000000000005")
    number = PageNumber(1)
    return ProcessedPage(
        id=page_id,
        workspace_id=_WORKSPACE_ID,
        document_version_id=_VERSION_ID,
        page_number=number,
        text=text,
        state=ProcessedPageState.READY,
        extraction_method=PageExtractionMethod.NATIVE,
        source_locator=SourceLocator(
            id=SourceLocatorId("10000000-0000-4000-8000-000000000006"),
            workspace_id=_WORKSPACE_ID,
            document_version_id=_VERSION_ID,
            page_id=page_id,
            page_number=number,
            kind=SourceLocatorKind.PAGE,
        ),
    )


def test_native_page_preserves_exact_text_without_normalization() -> None:
    exact = "  İlk satır\nİkinci satır\t "

    page = NativePdfPage(PageNumber(1), exact)

    assert page.text == exact


def test_processed_page_rejects_mismatched_locator_relationship() -> None:
    page = _page()
    wrong_locator = SourceLocator(
        id=page.source_locator.id,
        workspace_id=page.workspace_id,
        document_version_id=page.document_version_id,
        page_id=DocumentPageId("20000000-0000-4000-8000-000000000005"),
        page_number=page.page_number,
        kind=SourceLocatorKind.PAGE,
    )

    with pytest.raises(
        ProcessingPersistenceError,
        match="processed page relationships are invalid",
    ):
        ProcessedPage(
            id=page.id,
            workspace_id=page.workspace_id,
            document_version_id=page.document_version_id,
            page_number=page.page_number,
            text=page.text,
            state=page.state,
            extraction_method=page.extraction_method,
            source_locator=wrong_locator,
        )


def test_processed_page_state_matches_exact_text_usability() -> None:
    page = _page()

    with pytest.raises(
        ProcessingPersistenceError,
        match="processed page state is invalid",
    ):
        ProcessedPage(
            id=page.id,
            workspace_id=page.workspace_id,
            document_version_id=page.document_version_id,
            page_number=page.page_number,
            text=" \n\t",
            state=ProcessedPageState.READY,
            extraction_method=page.extraction_method,
            source_locator=page.source_locator,
        )


def test_page_batch_requires_complete_contiguous_order() -> None:
    target = ProcessingTarget(
        workspace_id=_TARGET.workspace_id,
        document_id=_TARGET.document_id,
        document_version_id=_TARGET.document_version_id,
        processing_job_id=_TARGET.processing_job_id,
        expected_page_count=2,
    )

    with pytest.raises(ProcessingPersistenceError, match="batch is incomplete"):
        ProcessingPageBatch(
            target,
            (_page(),),
            datetime(2026, 1, 2, tzinfo=UTC),
        )


class _Extractor:
    def extract(self, source: bytes) -> Iterable[NativePdfPage]:
        return (NativePdfPage(PageNumber(1), source.decode()),)


class _Cancellation:
    def raise_if_cancelled(self) -> None:
        return None


_extractor_contract: NativePdfTextExtractor = _Extractor()
_cancellation_contract: CancellationCheck = _Cancellation()


def test_protocol_doubles_are_available_without_sdk_types() -> None:
    assert tuple(_extractor_contract.extract(b"synthetic"))[0].text == "synthetic"
    _cancellation_contract.raise_if_cancelled()
    assert ProcessingCancelled.__module__.startswith("lexlocal.application")
