"""Prove ingestion registration follows Unit of Work transaction ownership."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from lexlocal.application.ports.ingestion import (
    IngestionRegistration,
    PdfInspectionResult,
    StoredBlobId,
)
from lexlocal.application.ports.security import ControlledSourceRef
from lexlocal.domain.documents import DocumentVersion, LogicalDocument, VersionNumber
from lexlocal.domain.identifiers import DocumentId, DocumentVersionId, ProcessingJobId, WorkspaceId
from lexlocal.domain.processing import AttemptNumber, ProcessingJob
from lexlocal.infrastructure.persistence.migration_runner import run_migrations
from lexlocal.infrastructure.persistence.migrations import (
    default_migrations_dir,
    discover_migrations,
)
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.persistence.sqlite_unit_of_work import SQLiteUnitOfWork
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
)


def _registration(workspace_id: WorkspaceId) -> IngestionRegistration:
    document = LogicalDocument(DocumentId(str(uuid4())), workspace_id)
    version = DocumentVersion(
        DocumentVersionId(str(uuid4())), workspace_id, document.id, VersionNumber(1)
    )
    return IngestionRegistration(
        StoredBlobId(str(uuid4())),
        ControlledSourceRef(workspace_id, f"opaque-{uuid4()}"),
        document,
        version,
        ProcessingJob(
            ProcessingJobId(str(uuid4())), workspace_id, version.id, AttemptNumber(1)
        ),
        "anonymous.pdf",
        PdfInspectionResult("application/pdf", 1),
        10,
        b"x" * 32,
        datetime(2026, 1, 1, tzinfo=UTC),
    )


def _factory(tmp_path: Path) -> SQLiteConnectionFactory:
    factory = SQLiteConnectionFactory(tmp_path / "lexlocal.db")
    connection = factory.create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
    connection.execute(
        """INSERT INTO workspaces
        (id, name_ciphertext, name_lookup_fingerprint, state, created_at, updated_at)
        VALUES ('12345678-1234-5678-1234-567812345678', x'01', x'02',
                'ACTIVE', 't', 't')"""
    )
    connection.commit()
    connection.close()
    return factory


def test_ingestion_repository_is_available_only_inside_transaction(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    uow = SQLiteUnitOfWork(factory, InsecureDevelopmentOnlyWorkspaceNamePersistence())

    try:
        _ = uow.ingestion
    except RuntimeError:
        pass
    else:
        raise AssertionError("inactive ingestion repository was exposed")

    with uow:
        assert uow.ingestion is uow.ingestion


@pytest.mark.parametrize("commit", [True, False])
def test_ingestion_graph_obeys_unit_of_work_finalization(
    tmp_path: Path,
    commit: bool,
) -> None:
    factory = _factory(tmp_path)
    workspace_id = WorkspaceId("12345678-1234-5678-1234-567812345678")
    uow = SQLiteUnitOfWork(factory, InsecureDevelopmentOnlyWorkspaceNamePersistence())
    with uow:
        uow.ingestion.register(_registration(workspace_id))
        if commit:
            uow.commit()

    connection = factory.create()
    counts = [
        connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "stored_blobs",
            "documents",
            "document_versions",
            "document_processing_jobs",
        )
    ]
    connection.close()
    assert counts == ([1, 1, 1, 1] if commit else [0, 0, 0, 0])
