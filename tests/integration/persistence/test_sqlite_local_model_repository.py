"""Integration tests for exact SQLite local-model identity persistence."""

import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from lexlocal.application.ports.local_models import (
    LocalModelPersistenceError,
    ModelCapability,
    ResolvedModelRecord,
)
from lexlocal.domain.identifiers import LocalModelId
from lexlocal.infrastructure.persistence.migration_runner import run_migrations
from lexlocal.infrastructure.persistence.migrations import (
    default_migrations_dir,
    discover_migrations,
)
from lexlocal.infrastructure.persistence.sqlite_connection import (
    SQLiteConnectionFactory,
)
from lexlocal.infrastructure.persistence.sqlite_local_model_repository import (
    SQLiteResolvedModelRepository,
)

CHAT_ID = LocalModelId("550e8400-e29b-41d4-a716-446655440000")
OTHER_ID = LocalModelId("123e4567-e89b-12d3-a456-426614174000")
_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z"
)


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = SQLiteConnectionFactory(tmp_path / "lexlocal.db").create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
    connection.execute("BEGIN")
    try:
        yield connection
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


@pytest.fixture
def repository(
    connection: sqlite3.Connection,
) -> SQLiteResolvedModelRepository:
    return SQLiteResolvedModelRepository(connection)


def make_record(
    *,
    model_id: LocalModelId = CHAT_ID,
    capability: ModelCapability = ModelCapability.CHAT,
    requested_alias: str = "synthetic-chat",
    resolved_model_id: str = "synthetic-chat:7",
    dimensions: int | None = None,
) -> ResolvedModelRecord:
    return ResolvedModelRecord(
        id=model_id,
        requested_alias=requested_alias,
        resolved_model_id=resolved_model_id,
        model_version="7",
        capability=capability,
        provider="FoundryLocal",
        dimensions=dimensions,
    )


@pytest.mark.parametrize(
    "record",
    [
        make_record(),
        make_record(
            model_id=OTHER_ID,
            capability=ModelCapability.EMBEDDING,
            requested_alias="synthetic-embedding",
            resolved_model_id="synthetic-embedding:3",
            dimensions=384,
        ),
    ],
    ids=["chat", "embedding"],
)
def test_get_or_add_exact_maps_schema_and_round_trips(
    connection: sqlite3.Connection,
    repository: SQLiteResolvedModelRepository,
    record: ResolvedModelRecord,
) -> None:
    assert repository.get_or_add_exact(record) == record
    assert connection.in_transaction

    row = connection.execute(
        "SELECT * FROM local_models WHERE id = ?",
        (str(record.id),),
    ).fetchone()

    assert row is not None
    assert row["id"] == str(record.id)
    assert row["purpose"] == record.capability.value
    assert row["provider"] == record.provider
    assert row["requested_alias"] == record.requested_alias
    assert row["resolved_model_id"] == record.resolved_model_id
    assert row["model_version"] == record.model_version
    assert row["dimensions"] == record.dimensions
    assert row["manifest_fingerprint"] is None
    assert _TIMESTAMP_PATTERN.fullmatch(row["created_at"])


def test_exact_identity_reuses_existing_stable_id(
    connection: sqlite3.Connection,
    repository: SQLiteResolvedModelRepository,
) -> None:
    original = make_record()
    repository.get_or_add_exact(original)

    reused = repository.get_or_add_exact(make_record(model_id=OTHER_ID))

    assert reused == original
    count = connection.execute("SELECT COUNT(*) FROM local_models").fetchone()
    assert count is not None
    assert count[0] == 1


@pytest.mark.parametrize(
    "conflicting",
    [
        make_record(requested_alias="different-alias"),
        make_record(resolved_model_id="different-model:1"),
    ],
    ids=["same-identity-key", "same-stable-id"],
)
def test_conflicting_identity_fails_closed_without_overwrite(
    connection: sqlite3.Connection,
    repository: SQLiteResolvedModelRepository,
    conflicting: ResolvedModelRecord,
) -> None:
    original = make_record()
    repository.get_or_add_exact(original)

    with pytest.raises(LocalModelPersistenceError) as captured:
        repository.get_or_add_exact(conflicting)

    assert str(captured.value) == "local model identity conflicts"
    assert captured.value.__cause__ is None
    row = connection.execute(
        "SELECT requested_alias, resolved_model_id FROM local_models"
    ).fetchone()
    assert tuple(row) == (original.requested_alias, original.resolved_model_id)


@pytest.mark.parametrize(
    ("statement", "value"),
    [
        ("UPDATE local_models SET requested_alias = ? WHERE id = ?", ""),
        (
            "UPDATE local_models SET created_at = ? WHERE id = ?",
            "not-a-timestamp",
        ),
    ],
)
def test_corrupt_stored_mapping_is_sanitized(
    connection: sqlite3.Connection,
    repository: SQLiteResolvedModelRepository,
    statement: str,
    value: object,
) -> None:
    record = make_record()
    repository.get_or_add_exact(record)
    connection.execute(statement, (value, str(record.id)))

    with pytest.raises(LocalModelPersistenceError) as captured:
        repository.get_or_add_exact(record)

    assert str(captured.value) == "local model data is invalid"
    assert captured.value.__cause__ is None


def test_repository_requires_caller_owned_active_transaction(
    tmp_path: Path,
) -> None:
    connection = SQLiteConnectionFactory(tmp_path / "lexlocal.db").create()
    run_migrations(connection, discover_migrations(default_migrations_dir()))
    repository = SQLiteResolvedModelRepository(connection)
    try:
        with pytest.raises(
            LocalModelPersistenceError,
            match="requires an active transaction",
        ):
            repository.get_or_add_exact(make_record())
    finally:
        connection.close()
