CREATE TABLE stored_blobs_replacement (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    kind TEXT NOT NULL CHECK (kind IN ('SOURCE_DOCUMENT', 'SOURCE_IMAGE', 'THUMBNAIL', 'DERIVED_ARTIFACT')),
    relative_path TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('STAGING', 'ACTIVE', 'DELETING', 'DELETED')),
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    plaintext_sha256_ciphertext BLOB,
    duplicate_fingerprint BLOB,
    encryption_format_version INTEGER CHECK (encryption_format_version > 0),
    created_at TEXT NOT NULL,
    activated_at TEXT,
    deleted_at TEXT,
    UNIQUE(workspace_id, relative_path),
    UNIQUE(id, workspace_id)
);

INSERT INTO stored_blobs_replacement
SELECT * FROM stored_blobs;

CREATE TEMP TABLE stored_blob_relationships (
    document_version_id TEXT PRIMARY KEY,
    source_blob_id TEXT NOT NULL
);

INSERT INTO stored_blob_relationships
SELECT id, source_blob_id
FROM document_versions
WHERE source_blob_id IS NOT NULL;

UPDATE document_versions
SET source_blob_id = NULL
WHERE source_blob_id IS NOT NULL;

DROP TABLE stored_blobs;
ALTER TABLE stored_blobs_replacement RENAME TO stored_blobs;

UPDATE document_versions
SET source_blob_id = (
    SELECT source_blob_id
    FROM stored_blob_relationships
    WHERE document_version_id = document_versions.id
)
WHERE id IN (SELECT document_version_id FROM stored_blob_relationships);

DROP TABLE stored_blob_relationships;
