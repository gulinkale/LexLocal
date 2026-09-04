"""DEVELOPMENT ONLY.

SYNTHETIC FIXTURES ONLY.
NOT RELEASE SAFE.
NOT FOR REAL USER DOCUMENTS.

Provide deterministic chunk equality tokens for anonymous development fixtures.
"""

from hashlib import sha256

from lexlocal.application.ports.indexing import (
    IndexingPersistenceError,
    LogicalChunk,
)

_TOKEN_PREFIX = b"lexlocal/insecure-development-only/chunk-equality/v1\x00"


class InsecureDevelopmentOnlyChunkEqualityToken:
    """DEVELOPMENT ONLY.

    SYNTHETIC FIXTURES ONLY.
    NOT RELEASE SAFE.
    NOT FOR REAL USER DOCUMENTS.

    Derive deterministic equality tokens for anonymous fixture chunks.
    """

    def fingerprint(self, chunk: LogicalChunk) -> bytes:
        """Return a versioned token over the exact canonical logical identity."""

        if not isinstance(chunk, LogicalChunk):
            raise IndexingPersistenceError("chunk equality input is invalid")
        fields = (
            str(chunk.workspace_id),
            str(chunk.document_version_id),
            str(chunk.page_id),
            str(chunk.source_locator_id),
            chunk.profile.value,
            str(chunk.source_start_offset),
            str(chunk.source_end_offset),
            str(chunk.document_order),
            str(chunk.page_order),
        )
        canonical = b"\x00".join(field.encode("utf-8") for field in fields)
        return sha256(_TOKEN_PREFIX + canonical + b"\x00" + chunk.text.encode("utf-8")).digest()
