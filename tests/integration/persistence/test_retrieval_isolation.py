"""Focused workspace, version, and sensitive-payload retrieval isolation tests."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from test_sqlite_retrieval_repository import (
    OTHER_WORKSPACE_ID,
    WORKSPACE_ID,
    _insert_retrieval_source_graph,
    _RecordingCodec,
    _registration,
    _request,
)

from lexlocal.application.ports.retrieval import (
    RetrievalIntegrityError,
    RetrievalPersistenceError,
)
from lexlocal.infrastructure.persistence.migration_runner import run_migrations
from lexlocal.infrastructure.persistence.migrations import (
    default_migrations_dir,
    discover_migrations,
)
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.persistence.sqlite_retrieval_repository import (
    SQLiteRetrievalRepository,
)


@pytest.fixture
def database(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = SQLiteConnectionFactory(tmp_path / "retrieval-isolation.db").create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
    _insert_retrieval_source_graph(connection, document_count=2)
    yield connection
    if connection.in_transaction:
        connection.rollback()
    connection.close()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE documents SET state = 'DELETED' "
        "WHERE id = '50000000-0000-4000-8000-000000000002'",
        "UPDATE document_versions SET state = 'ARCHIVED' "
        "WHERE id = '60000000-0000-4000-8000-000000000002'",
    ],
    ids=["inactive-document", "inactive-version"],
)
def test_one_inactive_scope_member_fails_the_whole_scope_without_exclusion(
    database: sqlite3.Connection,
    statement: str,
) -> None:
    database.execute("BEGIN")
    database.execute(statement)
    repository = SQLiteRetrievalRepository(database, _RecordingCodec())

    with pytest.raises(RetrievalIntegrityError) as raised:
        repository.resolve_scope(_request())

    assert "50000000-0000-4000-8000-000000000002" not in str(raised.value)
    assert "60000000-0000-4000-8000-000000000002" not in str(raised.value)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE chunks SET document_version_id = "
        "'60000000-0000-4000-8000-000000000002' "
        "WHERE id = 'b0000000-0000-4000-8000-000000000001'",
        "UPDATE embeddings SET workspace_id = "
        "'10000000-0000-4000-8000-000000000002', vector_ciphertext = x'00' "
        "WHERE chunk_id = 'b0000000-0000-4000-8000-000000000001'",
        "UPDATE source_locators SET workspace_id = "
        "'10000000-0000-4000-8000-000000000002' "
        "WHERE id = 'a0000000-0000-4000-8000-000000000001'",
    ],
    ids=["version", "vector-workspace", "locator-workspace"],
)
def test_candidate_substitution_fails_before_sensitive_candidate_decode(
    database: sqlite3.Connection,
    statement: str,
) -> None:
    database.execute("PRAGMA foreign_keys = OFF")
    database.execute("BEGIN")
    codec = _RecordingCodec()
    repository = SQLiteRetrievalRepository(database, codec)
    scope = repository.resolve_scope(_request())
    codec.decoded.clear()
    database.execute(statement)

    with pytest.raises(RetrievalIntegrityError) as raised:
        repository.load_candidates(scope)

    decoded_purposes = {context.purpose for context in codec.decoded}
    assert "chunk-embedding-vector" not in decoded_purposes
    assert "index-chunk-text" not in decoded_purposes
    assert "Synthetic passage" not in str(raised.value)
    assert str(OTHER_WORKSPACE_ID) not in str(raised.value)


def test_evidence_workspace_substitution_fails_before_evidence_payload_decode(
    database: sqlite3.Connection,
) -> None:
    database.execute("PRAGMA foreign_keys = OFF")
    database.execute("BEGIN")
    codec = _RecordingCodec()
    repository = SQLiteRetrievalRepository(database, codec)
    repository.add(_registration(repository, _request(1)))
    database.execute(
        "UPDATE evidence_items SET workspace_id = ?, excerpt_ciphertext = x'ff'",
        (str(OTHER_WORKSPACE_ID),),
    )
    codec.decoded.clear()

    with pytest.raises(RetrievalPersistenceError) as raised:
        repository.get_for_qa_request(WORKSPACE_ID, _request(1).qa_request_id)

    decoded_purposes = {context.purpose for context in codec.decoded}
    assert "retrieval-evidence-excerpt" not in decoded_purposes
    assert "ff" not in str(raised.value)
    assert str(OTHER_WORKSPACE_ID) not in str(raised.value)
