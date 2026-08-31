"""Integration tests for atomic SQLite ingestion registration."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from lexlocal.application.ports.ingestion import (
    DuplicateDocument,
    IngestionPersistenceError,
    IngestionRegistration,
    PdfInspectionResult,
    StoredBlobId,
)
from lexlocal.application.ports.security import ControlledSourceRef
from lexlocal.domain.documents import DocumentVersion, LogicalDocument, VersionNumber
from lexlocal.domain.identifiers import (
    DocumentId,
    DocumentVersionId,
    ProcessingJobId,
    WorkspaceId,
)
from lexlocal.domain.processing import AttemptNumber, ProcessingJob
from lexlocal.infrastructure.persistence.migration_runner import run_migrations
from lexlocal.infrastructure.persistence.migrations import (
    default_migrations_dir,
    discover_migrations,
)
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.persistence.sqlite_ingestion_repository import (
    SQLiteIngestionRepository,
)


def _id(identifier_type: type, value: str | None = None):  # type: ignore[no-untyped-def]
    return identifier_type(value or str(uuid4()))


def _registration(
    workspace_id: WorkspaceId,
    *,
    fingerprint: bytes = b"f" * 32,
) -> IngestionRegistration:
    document = LogicalDocument(_id(DocumentId), workspace_id)
    version = DocumentVersion(
        _id(DocumentVersionId), workspace_id, document.id, VersionNumber(1)
    )
    job = ProcessingJob(
        _id(ProcessingJobId), workspace_id, version.id, AttemptNumber(1)
    )
    return IngestionRegistration(
        stored_blob_id=StoredBlobId(str(uuid4())),
        controlled_source=ControlledSourceRef(workspace_id, f"opaque-{uuid4()}"),
        document=document,
        version=version,
        job=job,
        logical_filename="synthetic-ç.pdf",
        pdf=PdfInspectionResult("application/pdf", 3),
        byte_size=42,
        duplicate_fingerprint=fingerprint,
        created_at=datetime(2026, 1, 2, 3, 4, 5, 678900, tzinfo=UTC),
    )


@pytest.fixture
def database(tmp_path: Path):  # type: ignore[no-untyped-def]
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    connection = factory.create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
    yield connection
    connection.close()


def _insert_workspace(connection, workspace_id: WorkspaceId) -> None:  # type: ignore[no-untyped-def]
    connection.execute("BEGIN")
    connection.execute(
        """
        INSERT INTO workspaces (
            id, name_ciphertext, name_lookup_fingerprint, state, profile,
            profile_source, suggested_profile, suggested_profile_model_id,
            profile_suggested_at, profile_confirmed_at, created_at, updated_at,
            archived_at, deletion_started_at
        ) VALUES (?, x'01', x'02', 'ACTIVE', NULL, NULL, NULL, NULL, NULL, NULL,
                  '2026-01-01T00:00:00.000Z', '2026-01-01T00:00:00.000Z', NULL, NULL)
        """,
        (str(workspace_id),),
    )


def test_register_maps_exact_four_row_graph_without_committing(database) -> None:  # type: ignore[no-untyped-def]
    workspace_id = _id(WorkspaceId)
    _insert_workspace(database, workspace_id)
    registration = _registration(workspace_id)

    SQLiteIngestionRepository(database).register(registration)

    assert database.in_transaction
    blob = database.execute("SELECT * FROM stored_blobs").fetchone()
    document = database.execute("SELECT * FROM documents").fetchone()
    version = database.execute("SELECT * FROM document_versions").fetchone()
    job = database.execute("SELECT * FROM document_processing_jobs").fetchone()
    assert blob["id"] == str(registration.stored_blob_id)
    assert blob["relative_path"] == registration.controlled_source.value
    assert blob["encryption_format_version"] is None
    assert blob["plaintext_sha256_ciphertext"] is None
    assert blob["duplicate_fingerprint"] == registration.duplicate_fingerprint
    assert document["id"] == str(registration.document.id)
    assert document["display_name_ciphertext"] == "synthetic-ç.pdf".encode()
    assert version["document_id"] == document["id"]
    assert version["source_blob_id"] == blob["id"]
    assert version["historical_filename_ciphertext"] == "synthetic-ç.pdf".encode()
    assert version["state"] == "CANDIDATE_PROCESSING"
    assert version["created_at"] == "2026-01-02T03:04:05.678Z"
    assert job["document_version_id"] == version["id"]
    assert job["state"] == "QUEUED"
    assert job["stage"] == "VALIDATING"


def test_same_workspace_duplicate_is_rejected_and_sanitized(database) -> None:  # type: ignore[no-untyped-def]
    workspace_id = _id(WorkspaceId)
    _insert_workspace(database, workspace_id)
    repository = SQLiteIngestionRepository(database)
    repository.register(_registration(workspace_id))

    with pytest.raises(DuplicateDocument) as captured:
        repository.register(_registration(workspace_id))

    assert str(captured.value) == "document already exists"
    assert captured.value.__cause__ is None


def test_same_fingerprint_in_different_workspaces_can_be_committed(database) -> None:  # type: ignore[no-untyped-def]
    workspace_id_1 = _id(WorkspaceId)
    workspace_id_2 = _id(WorkspaceId)
    _insert_workspace(database, workspace_id_1)
    database.commit()
    _insert_workspace(database, workspace_id_2)
    database.commit()
    repository = SQLiteIngestionRepository(database)

    fingerprint = b"f" * 32
    registration_1 = _registration(workspace_id_1, fingerprint=fingerprint)
    registration_2 = _registration(workspace_id_2, fingerprint=fingerprint)

    database.execute("BEGIN")
    repository.register(registration_1)
    repository.register(registration_2)

    database.commit()

    rows = database.execute(
        """
        SELECT workspace_id, duplicate_fingerprint
        FROM stored_blobs
        WHERE duplicate_fingerprint = ?
        """,
        (fingerprint,),
    ).fetchall()
    assert len(rows) == 2
    assert {row["workspace_id"] for row in rows} == {
    str(workspace_id_1),
    str(workspace_id_2),
}


def test_repository_requires_active_transaction(database) -> None:  # type: ignore[no-untyped-def]
    database.commit()
    with pytest.raises(IngestionPersistenceError, match="transaction is not active"):
        SQLiteIngestionRepository(database).register(_registration(_id(WorkspaceId)))


def test_cross_workspace_relationship_fails_without_leaking_values(database) -> None:  # type: ignore[no-untyped-def]
    workspace_id = _id(WorkspaceId)
    _insert_workspace(database, workspace_id)
    registration = _registration(workspace_id)
    foreign_workspace = _id(WorkspaceId)
    object.__setattr__(registration.controlled_source, "workspace_id", foreign_workspace)

    with pytest.raises(IngestionPersistenceError) as captured:
        SQLiteIngestionRepository(database).register(registration)

    assert str(workspace_id) not in str(captured.value)
    assert str(foreign_workspace) not in str(captured.value)


def test_version_workspace_mismatch_fails_without_leaking_values(database) -> None:
    workspace_id = _id(WorkspaceId)
    _insert_workspace(database, workspace_id)

    registration = _registration(workspace_id)
    foreign_workspace = _id(WorkspaceId)

    object.__setattr__(
        registration.version,
        "workspace_id",
        foreign_workspace,
    )

    with pytest.raises(IngestionPersistenceError) as captured:
        SQLiteIngestionRepository(database).register(registration)

    assert str(workspace_id) not in str(captured.value)
    assert str(foreign_workspace) not in str(captured.value)


def test_job_workspace_mismatch_fails_without_leaking_values(database) -> None:
    workspace_id = _id(WorkspaceId)
    _insert_workspace(database, workspace_id)

    registration = _registration(workspace_id)
    foreign_workspace = _id(WorkspaceId)

    object.__setattr__(
        registration.job,
        "workspace_id",
        foreign_workspace,
    )

    with pytest.raises(IngestionPersistenceError) as captured:
        SQLiteIngestionRepository(database).register(registration)

    assert str(workspace_id) not in str(captured.value)
    assert str(foreign_workspace) not in str(captured.value)
