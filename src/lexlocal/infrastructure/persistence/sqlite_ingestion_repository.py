"""Register synthetic ingestion metadata in an existing SQLite transaction."""

import sqlite3

from lexlocal.application.ports.ingestion import (
    DuplicateDocument,
    IngestionPersistenceError,
    IngestionRegistration,
    IngestionRepository,
)
from lexlocal.application.ports.security import (
    SecurityContractError,
    SensitivePayloadContext,
    WorkspaceKeyReference,
)
from lexlocal.domain.identifiers import WorkspaceId
from lexlocal.infrastructure.security.insecure_development import (
    InsecureDevelopmentOnlyPayloadCodec,
)


class SQLiteIngestionRepository(IngestionRepository):
    """Stage one complete synthetic ingestion graph without finalizing it."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._codec = InsecureDevelopmentOnlyPayloadCodec()

    def register(self, registration: IngestionRegistration) -> None:
        """Insert the blob, document, version, and job in caller transaction."""

        if not self._connection.in_transaction:
            raise IngestionPersistenceError("ingestion transaction is not active")
        if not isinstance(registration, IngestionRegistration):
            raise IngestionPersistenceError("ingestion registration is invalid")

        workspace_id = registration.document.workspace_id
        if registration.controlled_source.workspace_id != workspace_id:
            raise IngestionPersistenceError("ingestion workspace relationships are invalid")
        timestamp = registration.created_at.isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )
        try:
            document_name = self._encode_name(
                registration.logical_filename,
                workspace_id=workspace_id,
                owner_id=str(registration.document.id),
                purpose="document-display-name",
            )
            version_name = self._encode_name(
                registration.logical_filename,
                workspace_id=registration.version.workspace_id,
                owner_id=str(registration.version.id),
                purpose="document-version-historical-filename",
            )
            self._connection.execute(
                """
                INSERT INTO stored_blobs (
                    id, workspace_id, kind, relative_path, state, size_bytes,
                    plaintext_sha256_ciphertext, duplicate_fingerprint,
                    encryption_format_version, created_at, activated_at, deleted_at
                ) VALUES (?, ?, 'SOURCE_DOCUMENT', ?, 'ACTIVE', ?, NULL, ?, NULL, ?, ?, NULL)
                """,
                (
                    str(registration.stored_blob_id),
                    str(registration.controlled_source.workspace_id),
                    registration.controlled_source.value,
                    registration.byte_size,
                    registration.duplicate_fingerprint,
                    timestamp,
                    timestamp,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO documents (
                    id, workspace_id, display_name_ciphertext, state,
                    confirmed_type, type_source, suggested_type,
                    suggested_type_model_id, type_suggested_at, type_confirmed_at,
                    created_at, updated_at, deleted_at
                ) VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?, NULL)
                """,
                (
                    str(registration.document.id),
                    str(workspace_id),
                    document_name,
                    registration.document.state.value,
                    timestamp,
                    timestamp,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO document_versions (
                    id, workspace_id, document_id, version_number,
                    historical_filename_ciphertext, mime_type, file_extension,
                    byte_size, page_count, source_blob_id,
                    content_sha256_ciphertext, duplicate_fingerprint, state,
                    warning_summary_ciphertext, created_at, activated_at,
                    archived_at, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, '.pdf', ?, ?, ?, NULL, ?, ?, NULL, ?, NULL, NULL, NULL)
                """,
                (
                    str(registration.version.id),
                    str(registration.version.workspace_id),
                    str(registration.document.id),
                    registration.version.version_number.value,
                    version_name,
                    registration.pdf.mime_type,
                    registration.byte_size,
                    registration.pdf.page_count,
                    str(registration.stored_blob_id),
                    registration.duplicate_fingerprint,
                    registration.version.state.value,
                    timestamp,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO document_processing_jobs (
                    id, workspace_id, document_version_id, attempt_number,
                    state, stage, progress_current, progress_total,
                    cancel_requested, error_code, error_metadata_json,
                    started_at, heartbeat_at, completed_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 0, NULL, NULL, NULL, NULL, NULL, ?)
                """,
                (
                    str(registration.job.id),
                    str(registration.job.workspace_id),
                    str(registration.version.id),
                    registration.job.attempt_number.value,
                    registration.job.state.value,
                    registration.job_stage,
                    timestamp,
                ),
            )
        except sqlite3.IntegrityError as error:
            if "ux_workspace_duplicate_live_source" in str(error) or (
                "document_versions.workspace_id" in str(error)
                and "document_versions.duplicate_fingerprint" in str(error)
            ):
                raise DuplicateDocument("document already exists") from None
            raise IngestionPersistenceError("ingestion persistence failed") from None
        except (SecurityContractError, UnicodeError, ValueError, TypeError):
            raise IngestionPersistenceError("ingestion registration is invalid") from None
        except sqlite3.DatabaseError:
            raise IngestionPersistenceError("ingestion persistence failed") from None

    def _encode_name(
        self,
        value: str,
        *,
        workspace_id: WorkspaceId,
        owner_id: str,
        purpose: str,
    ) -> bytes:
        context = SensitivePayloadContext(workspace_id, owner_id, purpose, 1)
        key_reference = WorkspaceKeyReference(workspace_id, 1)
        return self._codec.encode(
            value.encode("utf-8"), context=context, key_reference=key_reference
        ).payload
