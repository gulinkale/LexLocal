"""DEVELOPMENT ONLY.

SYNTHETIC FIXTURES ONLY.
NOT RELEASE SAFE.
NOT FOR REAL USER DOCUMENTS.

Provide deterministic duplicate tokens for anonymous development fixtures.
"""

from hashlib import sha256

from lexlocal.application.ports.ingestion import IngestionPersistenceError
from lexlocal.domain.identifiers import WorkspaceId

_TOKEN_PREFIX = b"lexlocal/insecure-development-only/document-duplicate/v1\x00"


class InsecureDevelopmentOnlyDuplicateFingerprint:
    """DEVELOPMENT ONLY.

    SYNTHETIC FIXTURES ONLY.
    NOT RELEASE SAFE.
    NOT FOR REAL USER DOCUMENTS.

    Derive workspace-scoped equality tokens for anonymous fixtures.
    """

    def fingerprint(
        self,
        workspace_id: WorkspaceId,
        source_sha256: bytes,
    ) -> bytes:
        """Return the exact versioned development token."""

        if not isinstance(workspace_id, WorkspaceId):
            raise IngestionPersistenceError("workspace identity is invalid")
        if not isinstance(source_sha256, bytes) or len(source_sha256) != 32:
            raise IngestionPersistenceError("source digest is invalid")
        return sha256(
            _TOKEN_PREFIX
            + str(workspace_id).encode("utf-8")
            + b"\x00"
            + source_sha256
        ).digest()
