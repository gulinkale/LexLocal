"""Persist exact resolved local-model identities in an existing transaction."""

import re
import sqlite3
from datetime import UTC, datetime

from lexlocal.application.ports.local_models import (
    LocalModelPersistenceError,
    ModelCapability,
    ResolvedModelRecord,
    ResolvedModelRepository,
)
from lexlocal.domain.errors import InvalidDomainValue
from lexlocal.domain.identifiers import LocalModelId

_UTC_MILLISECOND_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z"
)


class SQLiteResolvedModelRepository(ResolvedModelRepository):
    """Stage or reuse exact model identities on a caller-owned transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_or_add_exact(
        self,
        model: ResolvedModelRecord,
    ) -> ResolvedModelRecord:
        """Reuse an exact row, insert a new identity, or fail closed."""

        self._require_active_transaction()
        if not isinstance(model, ResolvedModelRecord):
            raise LocalModelPersistenceError("local model data is invalid")

        try:
            by_id = self._select_by_id(model.id)
            if by_id is not None:
                return self._require_exact(by_id, model)

            by_identity = self._select_by_identity(model)
            if by_identity is not None:
                return self._require_exact(by_identity, model, compare_id=False)

            self._connection.execute(
                """
                INSERT INTO local_models (
                    id,
                    purpose,
                    provider,
                    requested_alias,
                    resolved_model_id,
                    model_version,
                    dimensions,
                    manifest_fingerprint,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    str(model.id),
                    model.capability.value,
                    model.provider,
                    model.requested_alias,
                    model.resolved_model_id,
                    model.model_version,
                    model.dimensions,
                    self._serialize_timestamp(datetime.now(UTC)),
                ),
            )
            return model
        except LocalModelPersistenceError:
            raise
        except sqlite3.IntegrityError:
            raise LocalModelPersistenceError("local model identity conflicts") from None
        except (InvalidDomainValue, KeyError, TypeError, ValueError):
            raise LocalModelPersistenceError("local model data is invalid") from None
        except sqlite3.DatabaseError:
            raise LocalModelPersistenceError("local model persistence failed") from None

    def _select_by_id(self, model_id: LocalModelId) -> sqlite3.Row | None:
        row: object = self._connection.execute(
            """
            SELECT
                id,
                purpose,
                provider,
                requested_alias,
                resolved_model_id,
                model_version,
                dimensions,
                created_at
            FROM local_models
            WHERE id = ?
            """,
            (str(model_id),),
        ).fetchone()
        return self._require_row(row)

    def _select_by_identity(self, model: ResolvedModelRecord) -> sqlite3.Row | None:
        row: object = self._connection.execute(
            """
            SELECT
                id,
                purpose,
                provider,
                requested_alias,
                resolved_model_id,
                model_version,
                dimensions,
                created_at
            FROM local_models
            WHERE provider = ?
              AND resolved_model_id = ?
              AND purpose = ?
            """,
            (
                model.provider,
                model.resolved_model_id,
                model.capability.value,
            ),
        ).fetchone()
        return self._require_row(row)

    def _require_exact(
        self,
        row: sqlite3.Row,
        requested: ResolvedModelRecord,
        *,
        compare_id: bool = True,
    ) -> ResolvedModelRecord:
        try:
            stored = self._map_row(row)
        except LocalModelPersistenceError:
            raise LocalModelPersistenceError("local model data is invalid") from None
        comparable_stored = (
            stored.requested_alias,
            stored.resolved_model_id,
            stored.model_version,
            stored.capability,
            stored.provider,
            stored.dimensions,
        )
        comparable_requested = (
            requested.requested_alias,
            requested.resolved_model_id,
            requested.model_version,
            requested.capability,
            requested.provider,
            requested.dimensions,
        )
        if comparable_stored != comparable_requested or (
            compare_id and stored.id != requested.id
        ):
            raise LocalModelPersistenceError("local model identity conflicts")
        return stored

    def _map_row(self, row: sqlite3.Row) -> ResolvedModelRecord:
        self._parse_timestamp(row["created_at"])
        model_version = row["model_version"]
        dimensions = row["dimensions"]
        return ResolvedModelRecord(
            id=LocalModelId(self._require_string(row["id"])),
            requested_alias=self._require_string(row["requested_alias"]),
            resolved_model_id=self._require_string(row["resolved_model_id"]),
            model_version=(
                None
                if model_version is None
                else self._require_string(model_version)
            ),
            capability=ModelCapability(self._require_string(row["purpose"])),
            provider=self._require_string(row["provider"]),
            dimensions=(
                None if dimensions is None else self._require_integer(dimensions)
            ),
        )

    def _require_active_transaction(self) -> None:
        if not self._connection.in_transaction:
            raise LocalModelPersistenceError(
                "local model repository requires an active transaction"
            )

    @staticmethod
    def _serialize_timestamp(value: datetime) -> str:
        return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    @staticmethod
    def _parse_timestamp(value: object) -> datetime:
        timestamp = SQLiteResolvedModelRepository._require_string(value)
        if _UTC_MILLISECOND_PATTERN.fullmatch(timestamp) is None:
            raise ValueError("timestamp format is invalid")
        return datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=UTC
        )

    @staticmethod
    def _require_string(value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("stored value must be a string")
        return value

    @staticmethod
    def _require_integer(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("stored value must be an integer")
        return value

    @staticmethod
    def _require_row(value: object) -> sqlite3.Row | None:
        if value is None or isinstance(value, sqlite3.Row):
            return value
        raise LocalModelPersistenceError("local model data is invalid")
