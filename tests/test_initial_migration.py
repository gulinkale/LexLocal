import hashlib
import hmac
import json
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "001_initial.sql"
NOW = "2026-07-27T00:00:00.000Z"


def source_set_fingerprint(key: bytes, profile: str, schema: str, sources: list[dict]) -> bytes:
    payload = {
        "format_version": 1,
        "profile": profile,
        "profile_schema_version": schema,
        "sources": sorted(
            sources,
            key=lambda item: (item["document_id"], item["document_version_id"]),
        ),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(key, canonical, hashlib.sha256).digest()


def verify_recorded_migration_checksum(
    db: sqlite3.Connection, version: int, migration_bytes: bytes
) -> None:
    row = db.execute(
        "SELECT checksum_sha256 FROM schema_migrations WHERE version = ?",
        (version,),
    ).fetchone()
    if row is None or row[0] != hashlib.sha256(migration_bytes).hexdigest():
        raise RuntimeError("migration checksum mismatch")


class InitialMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(MIGRATION.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.db.close()

    def workspace(self, workspace_id: str) -> None:
        self.db.execute(
            """
            INSERT INTO workspaces(
                id, name_ciphertext, name_lookup_fingerprint, state,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'ACTIVE', ?, ?)
            """,
            (workspace_id, b"name", workspace_id.encode(), NOW, NOW),
        )

    def document(self, document_id: str, workspace_id: str) -> None:
        self.db.execute(
            """
            INSERT INTO documents(
                id, workspace_id, display_name_ciphertext, state,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'ACTIVE', ?, ?)
            """,
            (document_id, workspace_id, b"document", NOW, NOW),
        )

    def version(
        self,
        version_id: str,
        workspace_id: str,
        document_id: str,
        number: int,
        state: str = "ACTIVE",
        fingerprint: bytes | None = None,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO document_versions(
                id, workspace_id, document_id, version_number,
                historical_filename_ciphertext, duplicate_fingerprint,
                state, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                workspace_id,
                document_id,
                number,
                b"filename",
                fingerprint,
                state,
                NOW,
            ),
        )

    def test_empty_database_migration_and_foreign_key_check(self) -> None:
        violations = self.db.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual([], violations)
        self.assertIsNotNone(
            self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspaces'"
            ).fetchone()
        )

    def test_two_active_versions_for_one_document_are_rejected(self) -> None:
        self.workspace("w1")
        self.document("d1", "w1")
        self.version("v1", "w1", "d1", 1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.version("v2", "w1", "d1", 2)

    def test_two_active_indexes_for_one_version_are_rejected(self) -> None:
        self.workspace("w1")
        self.document("d1", "w1")
        self.version("v1", "w1", "d1", 1)
        self.db.execute(
            "INSERT INTO local_models VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("m1", "EMBEDDING", "foundry", "alias", "resolved", None, 3, None, NOW),
        )
        self.db.execute(
            """
            INSERT INTO document_processing_jobs(
                id, workspace_id, document_version_id, attempt_number,
                state, stage, created_at
            ) VALUES ('j1', 'w1', 'v1', 1, 'READY', 'ACTIVATING', ?)
            """,
            (NOW,),
        )
        values = (
            "w1",
            "v1",
            "j1",
            "ACTIVE",
            "m1",
            "chunk-v1",
            "norm-v1",
            3,
            "float32",
            NOW,
        )
        self.db.execute(
            """
            INSERT INTO index_generations(
                id, workspace_id, document_version_id, processing_job_id,
                state, embedding_model_id, chunking_profile_version,
                normalization_profile_version, embedding_dimensions,
                vector_dtype, created_at
            ) VALUES ('i1', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                """
                INSERT INTO index_generations(
                    id, workspace_id, document_version_id, processing_job_id,
                    state, embedding_model_id, chunking_profile_version,
                    normalization_profile_version, embedding_dimensions,
                    vector_dtype, created_at
                ) VALUES ('i2', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )

    def test_cross_workspace_child_relation_is_rejected(self) -> None:
        self.workspace("w1")
        self.workspace("w2")
        self.document("d1", "w1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.version("v1", "w2", "d1", 1)

    def test_same_fingerprint_in_same_workspace_is_rejected(self) -> None:
        self.workspace("w1")
        self.document("d1", "w1")
        self.document("d2", "w1")
        self.version("v1", "w1", "d1", 1, fingerprint=b"same")
        with self.assertRaises(sqlite3.IntegrityError):
            self.version("v2", "w1", "d2", 1, fingerprint=b"same")

    def test_same_fingerprint_in_different_workspaces_is_allowed(self) -> None:
        self.workspace("w1")
        self.workspace("w2")
        self.document("d1", "w1")
        self.document("d2", "w2")
        self.version("v1", "w1", "d1", 1, fingerprint=b"same")
        self.version("v2", "w2", "d2", 1, fingerprint=b"same")
        self.db.commit()

    def test_restore_is_rejected_as_generation_run_type(self) -> None:
        self.workspace("w1")
        self.db.execute(
            """
            INSERT INTO analyses(id, workspace_id, state, created_at, updated_at)
            VALUES ('a1', 'w1', 'NOT_CREATED', ?, ?)
            """,
            (NOW, NOW),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                """
                INSERT INTO analysis_generation_runs(
                    id, workspace_id, analysis_id, run_type, state, profile,
                    prompt_schema_version, created_at
                ) VALUES (
                    'r1', 'w1', 'a1', 'RESTORE', 'QUEUED', 'LITIGATION',
                    'prompt-v1', ?
                )
                """,
                (NOW,),
            )

    def test_restore_version_metadata_invariants(self) -> None:
        self.workspace("w1")
        self.db.execute(
            """
            INSERT INTO analyses(id, workspace_id, state, created_at, updated_at)
            VALUES ('a1', 'w1', 'CURRENT', ?, ?)
            """,
            (NOW, NOW),
        )
        common = (
            "w1", "a1", "LITIGATION", "schema-v1", "[]", b"x" * 32, NOW
        )
        self.db.execute(
            """
            INSERT INTO analysis_versions(
                id, workspace_id, analysis_id, version_number, creation_reason,
                content_source, profile, profile_schema_version,
                changed_sections_json, source_set_fingerprint, created_at
            ) VALUES ('av1', ?, ?, 1, 'INITIAL_GENERATION', 'AI', ?, ?, ?, ?, ?)
            """,
            common,
        )
        self.db.execute(
            """
            INSERT INTO analysis_versions(
                id, workspace_id, analysis_id, version_number, creation_reason,
                content_source, profile, profile_schema_version,
                based_on_version_id, restored_from_version_id,
                changed_sections_json, source_set_fingerprint, created_at
            ) VALUES (
                'av2', ?, ?, 2, 'RESTORE', 'RESTORE', ?, ?, 'av1', 'av1',
                ?, ?, ?
            )
            """,
            common,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                """
                INSERT INTO analysis_versions(
                    id, workspace_id, analysis_id, version_number,
                    creation_reason, content_source, profile,
                    profile_schema_version, changed_sections_json,
                    source_set_fingerprint, created_at
                ) VALUES (
                    'av3', 'w1', 'a1', 3, 'RESTORE', 'RESTORE', 'LITIGATION',
                    'schema-v1', '[]', ?, ?
                )
                """,
                (b"x" * 32, NOW),
            )

    def test_source_set_fingerprint_contract(self) -> None:
        sources = [
            {"document_id": "d2", "document_version_id": "v2", "coverage_state": "FULL"},
            {"document_id": "d1", "document_version_id": "v1", "coverage_state": "PARTIAL"},
        ]
        baseline = source_set_fingerprint(b"k1", "LITIGATION", "schema-v1", sources)
        self.assertEqual(32, len(baseline))
        self.assertEqual(
            baseline,
            source_set_fingerprint(b"k1", "LITIGATION", "schema-v1", list(reversed(sources))),
        )
        self.assertEqual(
            baseline,
            source_set_fingerprint(b"k1", "LITIGATION", "schema-v1", sources),
        )
        variants = [
            source_set_fingerprint(b"k2", "LITIGATION", "schema-v1", sources),
            source_set_fingerprint(b"k1", "CONTRACT_REVIEW", "schema-v1", sources),
            source_set_fingerprint(b"k1", "LITIGATION", "schema-v2", sources),
            source_set_fingerprint(
                b"k1", "LITIGATION", "schema-v1",
                [{**sources[0], "document_version_id": "v3"}, sources[1]],
            ),
            source_set_fingerprint(
                b"k1", "LITIGATION", "schema-v1",
                [{**sources[0], "coverage_state": "PARTIAL"}, sources[1]],
            ),
        ]
        self.assertTrue(all(value != baseline for value in variants))

    def test_source_set_fingerprint_requires_blob(self) -> None:
        self.workspace("w1")
        self.db.execute(
            """
            INSERT INTO analyses(id, workspace_id, state, created_at, updated_at)
            VALUES ('a1', 'w1', 'NOT_CREATED', ?, ?)
            """,
            (NOW, NOW),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                """
                INSERT INTO analysis_versions(
                    id, workspace_id, analysis_id, version_number,
                    creation_reason, content_source, profile,
                    profile_schema_version, changed_sections_json,
                    source_set_fingerprint, created_at
                ) VALUES (
                    'av1', 'w1', 'a1', 1, 'INITIAL_GENERATION', 'AI',
                    'LITIGATION', 'schema-v1', '[]', ?, ?
                )
                """,
                ("00" * 32, NOW),
            )

    def test_recorded_migration_checksum_mismatch_blocks_verification(self) -> None:
        migration_bytes = MIGRATION.read_bytes()
        checksum = hashlib.sha256(migration_bytes).hexdigest()
        self.db.execute(
            """
            INSERT INTO schema_migrations(version, filename, checksum_sha256, applied_at)
            VALUES (1, '001_initial.sql', ?, ?)
            """,
            (checksum, NOW),
        )
        verify_recorded_migration_checksum(self.db, 1, migration_bytes)
        with self.assertRaises(RuntimeError):
            verify_recorded_migration_checksum(
                self.db, 1, migration_bytes + b"\\n-- tampered"
            )


if __name__ == "__main__":
    unittest.main()
