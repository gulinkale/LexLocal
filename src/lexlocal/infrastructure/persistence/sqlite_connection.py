"""Create SQLite connections with consistent application settings."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SQLiteConnectionFactory:
    """Create configured SQLite connections for a database file."""

    database_path: Path
    busy_timeout_ms: int = 5_000

    def __post_init__(self) -> None:
        """Validate connection configuration."""

        if self.busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms must be non-negative")

    def create(self) -> sqlite3.Connection:
        """Open and configure a new SQLite connection."""

        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        connection = sqlite3.connect(
            self.database_path,
            timeout=self.busy_timeout_ms / 1_000,
            isolation_level=None,
        )

        try:
            connection.row_factory = sqlite3.Row

            journal_mode_row = connection.execute("PRAGMA journal_mode = WAL").fetchone()

            if journal_mode_row is None or str(journal_mode_row[0]).lower() != "wal":
                raise RuntimeError("SQLite WAL mode could not be enabled")

            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        except Exception:
            connection.close()
            raise

        return connection
