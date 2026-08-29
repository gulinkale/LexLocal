"""Integration tests for local-model repository transaction ownership."""

from pathlib import Path

import pytest

from lexlocal.application.ports.local_models import (
    LocalModelPersistenceError,
    ModelCapability,
    ResolvedModelRecord,
)
from lexlocal.bootstrap.persistence import initialize_persistence
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import LocalModelId
from lexlocal.infrastructure.persistence.sqlite_connection import (
    SQLiteConnectionFactory,
)
from lexlocal.infrastructure.persistence.sqlite_unit_of_work import SQLiteUnitOfWork
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
)

MODEL_ID = LocalModelId("550e8400-e29b-41d4-a716-446655440000")


def make_factory(tmp_path: Path) -> SQLiteConnectionFactory:
    return initialize_persistence(
        AppSettings(
            app_name="LexLocal",
            environment="test",
            log_level="INFO",
            data_dir=tmp_path,
            security_provider="insecure-development-only",
        )
    )


def make_unit_of_work(factory: SQLiteConnectionFactory) -> SQLiteUnitOfWork:
    return SQLiteUnitOfWork(
        factory,
        InsecureDevelopmentOnlyWorkspaceNamePersistence(),
    )


def make_record(*, requested_alias: str = "synthetic-chat") -> ResolvedModelRecord:
    return ResolvedModelRecord(
        id=MODEL_ID,
        requested_alias=requested_alias,
        resolved_model_id="synthetic-chat:1",
        model_version="1",
        capability=ModelCapability.CHAT,
        provider="FoundryLocal",
    )


def record_count(factory: SQLiteConnectionFactory) -> int:
    connection = factory.create()
    try:
        row = connection.execute("SELECT COUNT(*) FROM local_models").fetchone()
    finally:
        connection.close()
    assert row is not None
    return int(row[0])


def test_commit_makes_record_visible_from_fresh_connection(tmp_path: Path) -> None:
    factory = make_factory(tmp_path)
    unit_of_work = make_unit_of_work(factory)

    with unit_of_work:
        assert unit_of_work.local_models.get_or_add_exact(make_record()) == make_record()
        unit_of_work.commit()

    assert record_count(factory) == 1


def test_exception_rolls_back_record(tmp_path: Path) -> None:
    factory = make_factory(tmp_path)
    unit_of_work = make_unit_of_work(factory)

    with pytest.raises(RuntimeError, match="synthetic failure"):
        with unit_of_work:
            unit_of_work.local_models.get_or_add_exact(make_record())
            raise RuntimeError("synthetic failure")

    assert record_count(factory) == 0


def test_omitted_commit_rolls_back_record(tmp_path: Path) -> None:
    factory = make_factory(tmp_path)
    unit_of_work = make_unit_of_work(factory)

    with unit_of_work:
        unit_of_work.local_models.get_or_add_exact(make_record())

    assert record_count(factory) == 0


def test_failed_transaction_leaves_no_partial_record(tmp_path: Path) -> None:
    factory = make_factory(tmp_path)
    unit_of_work = make_unit_of_work(factory)

    with pytest.raises(LocalModelPersistenceError):
        with unit_of_work:
            unit_of_work.local_models.get_or_add_exact(make_record())
            unit_of_work.local_models.get_or_add_exact(
                make_record(requested_alias="conflicting-alias")
            )

    assert record_count(factory) == 0
