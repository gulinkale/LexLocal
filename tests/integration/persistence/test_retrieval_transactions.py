"""Transaction-boundary tests for SQLite retrieval persistence."""

from pathlib import Path

import pytest

from lexlocal.application.ports.retrieval import RetrievalPersistenceError
from lexlocal.domain.identifiers import QaRequestId, WorkspaceId
from lexlocal.infrastructure.persistence.migration_runner import run_migrations
from lexlocal.infrastructure.persistence.migrations import (
    default_migrations_dir,
    discover_migrations,
)
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.persistence.sqlite_retrieval_repository import (
    SQLiteRetrievalRepository,
)
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyPayloadCodec,
)

WORKSPACE_ID = WorkspaceId("10000000-0000-4000-8000-000000000001")
QA_REQUEST_ID = QaRequestId("20000000-0000-4000-8000-000000000001")


def test_lookup_uses_and_leaves_the_caller_transaction_active(tmp_path: Path) -> None:
    connection = SQLiteConnectionFactory(tmp_path / "lexlocal.db").create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
    repository = SQLiteRetrievalRepository(
        connection,
        InsecureDevelopmentOnlyPayloadCodec(),
    )
    connection.execute("BEGIN")

    assert repository.get_for_qa_request(WORKSPACE_ID, QA_REQUEST_ID) is None
    assert connection.in_transaction is True

    connection.rollback()
    connection.close()


def test_repository_never_opens_an_implicit_transaction(tmp_path: Path) -> None:
    connection = SQLiteConnectionFactory(tmp_path / "lexlocal.db").create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
    repository = SQLiteRetrievalRepository(
        connection,
        InsecureDevelopmentOnlyPayloadCodec(),
    )

    with pytest.raises(RetrievalPersistenceError, match="transaction is not active"):
        repository.get_for_qa_request(WORKSPACE_ID, QA_REQUEST_ID)

    assert connection.in_transaction is False
    connection.close()
