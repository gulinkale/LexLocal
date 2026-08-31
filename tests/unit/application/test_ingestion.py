"""Unit tests for synthetic PDF Application orchestration."""

from datetime import UTC, datetime
from hashlib import sha256
from types import TracebackType
from typing import Self

import pytest

from lexlocal.application.ingestion import ImportSyntheticPdf
from lexlocal.application.ports.ingestion import (
    DuplicateDocument,
    IngestionError,
    IngestionPersistenceError,
    IngestionRegistration,
    IngestionStorageError,
    InvalidPdfInput,
    PdfInspectionResult,
    StoredBlobId,
    UnsupportedPdf,
)
from lexlocal.application.ports.security import ControlledSourceRef
from lexlocal.application.workspaces import ActiveWorkspaceScope
from lexlocal.domain.documents import DocumentVersionState, LogicalDocumentState
from lexlocal.domain.identifiers import (
    DocumentId,
    DocumentVersionId,
    ProcessingJobId,
    WorkspaceId,
)
from lexlocal.domain.processing import ProcessingJobState

WORKSPACE_ID = WorkspaceId("550e8400-e29b-41d4-a716-446655440000")
OTHER_WORKSPACE_ID = WorkspaceId("123e4567-e89b-12d3-a456-426614174000")
DOCUMENT_ID = DocumentId("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
VERSION_ID = DocumentVersionId("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
JOB_ID = ProcessingJobId("cccccccc-cccc-cccc-cccc-cccccccccccc")
BLOB_ID = StoredBlobId("dddddddd-dddd-dddd-dddd-dddddddddddd")
NOW = datetime(2026, 8, 29, 10, 15, tzinfo=UTC)
SOURCE = b"%PDF-1.7 anonymous synthetic bytes"
REFERENCE = ControlledSourceRef(WORKSPACE_ID, "opaque-source-reference")


class _FakePdfInspector:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.sources: list[bytes] = []
        self.error: Exception | None = None

    def inspect(self, source: bytes) -> PdfInspectionResult:
        self.events.append("inspect")
        self.sources.append(source)
        if self.error is not None:
            raise self.error
        return PdfInspectionResult("application/pdf", 2)


class _FakeFingerprint:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls: list[tuple[WorkspaceId, bytes]] = []
        self.error: Exception | None = None

    def fingerprint(self, workspace_id: WorkspaceId, digest: bytes) -> bytes:
        self.events.append("fingerprint")
        self.calls.append((workspace_id, digest))
        if self.error is not None:
            raise self.error
        return b"d" * 32


class _FakeStorage:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.store_calls: list[tuple[WorkspaceId, bytes]] = []
        self.delete_calls: list[tuple[WorkspaceId, ControlledSourceRef]] = []
        self.store_error: Exception | None = None
        self.delete_error: Exception | None = None

    def store(self, workspace_id: WorkspaceId, source: bytes) -> ControlledSourceRef:
        self.events.append("store")
        self.store_calls.append((workspace_id, source))
        if self.store_error is not None:
            raise self.store_error
        return REFERENCE

    def read(self, workspace_id: WorkspaceId, reference: ControlledSourceRef) -> bytes:
        raise AssertionError("read is not part of Step 1 orchestration")

    def delete(self, workspace_id: WorkspaceId, reference: ControlledSourceRef) -> None:
        self.events.append("delete")
        self.delete_calls.append((workspace_id, reference))
        if self.delete_error is not None:
            raise self.delete_error


class _FakeRepository:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.registrations: list[IngestionRegistration] = []
        self.error: Exception | None = None

    def register(self, registration: IngestionRegistration) -> None:
        self.events.append("register")
        self.registrations.append(registration)
        if self.error is not None:
            raise self.error


class _FakeUnitOfWork:
    def __init__(self, repository: _FakeRepository, events: list[str]) -> None:
        self.ingestion = repository
        self.events = events
        self.commit_error: Exception | None = None
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self) -> Self:
        self.events.append("enter_uow")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.events.append("exit_uow")
        if exc_type is not None:
            self.rollbacks += 1

    def commit(self) -> None:
        self.events.append("commit")
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        self.rollbacks += 1


class _UowFactory:
    def __init__(self, unit_of_work: _FakeUnitOfWork, events: list[str]) -> None:
        self.unit_of_work = unit_of_work
        self.events = events
        self.calls = 0

    def __call__(self) -> _FakeUnitOfWork:
        self.events.append("create_uow")
        self.calls += 1
        return self.unit_of_work


def _subject() -> tuple[
    ImportSyntheticPdf,
    _FakePdfInspector,
    _FakeFingerprint,
    _FakeStorage,
    _FakeRepository,
    _FakeUnitOfWork,
    _UowFactory,
    list[str],
]:
    events: list[str] = []
    inspector = _FakePdfInspector(events)
    fingerprint = _FakeFingerprint(events)
    storage = _FakeStorage(events)
    repository = _FakeRepository(events)
    unit_of_work = _FakeUnitOfWork(repository, events)
    unit_of_work_factory = _UowFactory(unit_of_work, events)
    active_scope = ActiveWorkspaceScope()
    active_scope.select(WORKSPACE_ID)
    subject = ImportSyntheticPdf(
        active_scope,
        inspector,
        fingerprint,
        storage,
        unit_of_work_factory,
        lambda: DOCUMENT_ID,
        lambda: VERSION_ID,
        lambda: JOB_ID,
        lambda: BLOB_ID,
        lambda: NOW,
    )
    return (
        subject,
        inspector,
        fingerprint,
        storage,
        repository,
        unit_of_work,
        unit_of_work_factory,
        events,
    )


def test_success_uses_exact_order_scope_values_and_domain_graph() -> None:
    subject, inspector, fingerprint, storage, repository, uow, _, events = _subject()

    result = subject(SOURCE, "anonymous.pdf")

    assert events == [
        "inspect",
        "fingerprint",
        "store",
        "create_uow",
        "enter_uow",
        "register",
        "commit",
        "exit_uow",
    ]
    assert inspector.sources == [SOURCE]
    assert fingerprint.calls == [(WORKSPACE_ID, sha256(SOURCE).digest())]
    assert storage.store_calls == [(WORKSPACE_ID, SOURCE)]
    registration = repository.registrations[0]
    assert registration.stored_blob_id == BLOB_ID
    assert registration.controlled_source == REFERENCE
    assert str(registration.stored_blob_id) != registration.controlled_source.value
    assert registration.document.state is LogicalDocumentState.ACTIVE
    assert registration.version.state is DocumentVersionState.CANDIDATE_PROCESSING
    assert registration.version.version_number.value == 1
    assert registration.job.state is ProcessingJobState.QUEUED
    assert registration.job.attempt_number.value == 1
    assert registration.job_stage == "VALIDATING"
    assert registration.logical_filename == "anonymous.pdf"
    assert registration.byte_size == len(SOURCE)
    assert registration.duplicate_fingerprint == b"d" * 32
    assert registration.created_at == NOW
    registration.version.validate_document(registration.document)
    registration.job.validate_document_version(registration.version)
    assert uow.commits == 1
    assert uow.rollbacks == 0
    assert result.document_id == DOCUMENT_ID
    assert result.document_version_id == VERSION_ID
    assert result.processing_job_id == JOB_ID
    assert result.controlled_source == REFERENCE
    assert result.pdf == PdfInspectionResult("application/pdf", 2)
    assert not hasattr(result, "stored_blob_id")


@pytest.mark.parametrize(
    ("source", "filename"),
    [(b"", "anonymous.pdf"), (bytearray(SOURCE), "anonymous.pdf"), (SOURCE, "")],
)
def test_invalid_input_stops_before_inspection_storage_and_uow(
    source: object,
    filename: str,
) -> None:
    subject, inspector, _, storage, repository, _, factory, events = _subject()

    with pytest.raises(InvalidPdfInput):
        subject.__call__(source, filename)

    assert inspector.sources == []
    assert storage.store_calls == []
    assert repository.registrations == []
    assert factory.calls == 0
    assert events == []


@pytest.mark.parametrize(
    ("failure_owner", "error"),
    [
        ("inspector", UnsupportedPdf("unsupported PDF")),
        ("fingerprint", RuntimeError("private digest detail")),
    ],
)
def test_pre_storage_failure_creates_no_storage_or_uow(
    failure_owner: str,
    error: Exception,
) -> None:
    subject, inspector, fingerprint, storage, repository, _, factory, _ = _subject()
    if failure_owner == "inspector":
        inspector.error = error
        expected: type[Exception] = UnsupportedPdf
    else:
        fingerprint.error = error
        expected = IngestionPersistenceError

    with pytest.raises(expected):
        subject(SOURCE, "anonymous.pdf")

    assert storage.store_calls == []
    assert repository.registrations == []
    assert factory.calls == 0


def test_storage_failure_creates_no_database_scope_and_is_sanitized() -> None:
    subject, _, _, storage, repository, _, factory, _ = _subject()
    storage.store_error = RuntimeError("native provider source detail")

    with pytest.raises(
        IngestionStorageError,
        match="controlled source storage failed",
    ) as captured:
        subject(SOURCE, "anonymous.pdf")

    assert captured.value.__cause__ is None
    assert repository.registrations == []
    assert factory.calls == 0


@pytest.mark.parametrize(
    ("failure_point", "primary_error", "expected_type"),
    [
        ("register", DuplicateDocument("duplicate"), DuplicateDocument),
        (
            "register",
            RuntimeError("SQL and database path"),
            IngestionPersistenceError,
        ),
        ("commit", RuntimeError("commit SQL detail"), IngestionPersistenceError),
    ],
)
def test_database_failure_rolls_back_and_compensates(
    failure_point: str,
    primary_error: Exception,
    expected_type: type[IngestionError],
) -> None:
    subject, _, _, storage, repository, uow, _, events = _subject()
    if failure_point == "register":
        repository.error = primary_error
    else:
        uow.commit_error = primary_error

    with pytest.raises(expected_type) as captured:
        subject(SOURCE, "anonymous.pdf")

    assert uow.rollbacks == 1
    assert storage.delete_calls == [(WORKSPACE_ID, REFERENCE)]
    assert events[-2:] == ["exit_uow", "delete"]
    assert captured.value.__cause__ is None
    assert "SQL" not in str(captured.value)
    assert "database path" not in str(captured.value)


def test_compensation_failure_is_sanitized_and_retains_safe_primary_type() -> None:
    subject, _, _, storage, repository, uow, _, _ = _subject()
    repository.error = DuplicateDocument("duplicate")
    storage.delete_error = RuntimeError("opaque-source-reference and native bytes")

    with pytest.raises(
        IngestionStorageError,
        match="controlled source compensation failed",
    ) as captured:
        subject(SOURCE, "anonymous.pdf")

    assert uow.rollbacks == 1
    assert type(captured.value.primary_failure) is DuplicateDocument
    assert captured.value.__cause__ is None
    assert REFERENCE.value not in str(captured.value)
    assert SOURCE.decode() not in str(captured.value)
