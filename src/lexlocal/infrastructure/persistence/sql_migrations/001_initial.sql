PRAGMA foreign_keys = ON;

CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY CHECK (version > 0),
    filename TEXT NOT NULL UNIQUE,
    checksum_sha256 TEXT NOT NULL CHECK (length(checksum_sha256) = 64),
    applied_at TEXT NOT NULL
);

CREATE TABLE application_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE user_preferences (
    id TEXT PRIMARY KEY,
    preference_key TEXT NOT NULL UNIQUE,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE security_profiles (
    id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('SETUP_REQUIRED', 'ACTIVE', 'RECOVERY_REQUIRED', 'RESETTING')),
    format_version INTEGER NOT NULL CHECK (format_version > 0),
    password_kdf_metadata_json TEXT,
    password_wrapped_master_key BLOB,
    recovery_wrapped_master_key BLOB,
    biometric_wrapped_master_key BLOB,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE local_models (
    id TEXT PRIMARY KEY,
    purpose TEXT NOT NULL CHECK (purpose IN ('EMBEDDING', 'CHAT')),
    provider TEXT NOT NULL,
    requested_alias TEXT NOT NULL,
    resolved_model_id TEXT NOT NULL,
    model_version TEXT,
    dimensions INTEGER CHECK (dimensions IS NULL OR dimensions > 0),
    manifest_fingerprint TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(provider, resolved_model_id, purpose)
);

CREATE TABLE workspaces (
    id TEXT PRIMARY KEY,
    name_ciphertext BLOB NOT NULL,
    name_lookup_fingerprint BLOB NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'ARCHIVED', 'DELETING', 'DELETION_RECOVERY')),
    profile TEXT CHECK (profile IS NULL OR profile IN ('LITIGATION', 'CONTRACT_REVIEW', 'GENERAL_LEGAL')),
    profile_source TEXT CHECK (profile_source IS NULL OR profile_source IN ('USER', 'AI_CONFIRMED')),
    suggested_profile TEXT,
    suggested_profile_model_id TEXT REFERENCES local_models(id) ON UPDATE RESTRICT ON DELETE SET NULL,
    profile_suggested_at TEXT,
    profile_confirmed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT,
    deletion_started_at TEXT
);

-- The workspace is its own ownership root. Root ownership uses workspaces(id);
-- every non-root parent exposes
-- UNIQUE(id, workspace_id) and every child-to-parent relation is composite.

CREATE TABLE workspace_key_records (
    workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'ROTATING', 'DESTROYED')),
    key_version INTEGER NOT NULL CHECK (key_version > 0),
    wrapped_key_ciphertext BLOB,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE stored_blobs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    kind TEXT NOT NULL CHECK (kind IN ('SOURCE_DOCUMENT', 'SOURCE_IMAGE', 'THUMBNAIL', 'DERIVED_ARTIFACT')),
    relative_path TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('STAGING', 'ACTIVE', 'DELETING', 'DELETED')),
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    plaintext_sha256_ciphertext BLOB,
    duplicate_fingerprint BLOB,
    encryption_format_version INTEGER NOT NULL CHECK (encryption_format_version > 0),
    created_at TEXT NOT NULL,
    activated_at TEXT,
    deleted_at TEXT,
    UNIQUE(workspace_id, relative_path),
    UNIQUE(id, workspace_id)
);

CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    display_name_ciphertext BLOB NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'DELETED')),
    confirmed_type TEXT,
    type_source TEXT CHECK (type_source IS NULL OR type_source IN ('USER', 'AI_CONFIRMED')),
    suggested_type TEXT,
    suggested_type_model_id TEXT REFERENCES local_models(id) ON UPDATE RESTRICT ON DELETE SET NULL,
    type_suggested_at TEXT,
    type_confirmed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    UNIQUE(id, workspace_id)
);

CREATE TABLE document_versions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    version_number INTEGER NOT NULL CHECK (version_number >= 1),
    historical_filename_ciphertext BLOB NOT NULL,
    mime_type TEXT,
    file_extension TEXT,
    byte_size INTEGER CHECK (byte_size IS NULL OR byte_size >= 0),
    page_count INTEGER CHECK (page_count IS NULL OR page_count >= 0),
    source_blob_id TEXT,
    content_sha256_ciphertext BLOB,
    duplicate_fingerprint BLOB,
    state TEXT NOT NULL CHECK (state IN (
        'CANDIDATE_PROCESSING', 'CANDIDATE_READY', 'CANDIDATE_WARNING',
        'CANDIDATE_FAILED', 'CANDIDATE_CANCELLED', 'ACTIVE', 'ARCHIVED', 'DELETED'
    )),
    warning_summary_ciphertext BLOB,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    archived_at TEXT,
    deleted_at TEXT,
    UNIQUE(document_id, version_number),
    UNIQUE(id, workspace_id),
    FOREIGN KEY(document_id, workspace_id)
        REFERENCES documents(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(source_blob_id, workspace_id)
        REFERENCES stored_blobs(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE UNIQUE INDEX ux_document_one_active_version
ON document_versions(document_id) WHERE state = 'ACTIVE';

CREATE UNIQUE INDEX ux_workspace_duplicate_live_source
ON document_versions(workspace_id, duplicate_fingerprint)
WHERE duplicate_fingerprint IS NOT NULL AND state <> 'DELETED';

CREATE TABLE document_processing_jobs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    document_version_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    state TEXT NOT NULL CHECK (state IN ('QUEUED', 'PROCESSING', 'READY', 'READY_WITH_WARNINGS', 'FAILED', 'CANCELLED')),
    stage TEXT NOT NULL,
    progress_current INTEGER CHECK (progress_current IS NULL OR progress_current >= 0),
    progress_total INTEGER CHECK (progress_total IS NULL OR progress_total >= 0),
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
    error_code TEXT,
    error_metadata_json TEXT,
    started_at TEXT,
    heartbeat_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(document_version_id, attempt_number),
    UNIQUE(id, workspace_id),
    FOREIGN KEY(document_version_id, workspace_id)
        REFERENCES document_versions(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE
);

CREATE TABLE document_pages (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    document_version_id TEXT NOT NULL,
    page_number INTEGER NOT NULL CHECK (page_number >= 1),
    state TEXT NOT NULL CHECK (state IN ('READY', 'WARNING', 'FAILED')),
    extraction_method TEXT NOT NULL CHECK (extraction_method IN ('NATIVE', 'OCR')),
    text_ciphertext BLOB,
    normalized_text_fingerprint BLOB,
    character_count INTEGER NOT NULL DEFAULT 0 CHECK (character_count >= 0),
    word_count INTEGER NOT NULL DEFAULT 0 CHECK (word_count >= 0),
    warning_codes_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(document_version_id, page_number),
    UNIQUE(id, workspace_id),
    FOREIGN KEY(document_version_id, workspace_id)
        REFERENCES document_versions(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE
);

CREATE TABLE source_locators (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    document_version_id TEXT NOT NULL,
    page_id TEXT NOT NULL,
    locator_kind TEXT NOT NULL CHECK (locator_kind IN ('PAGE', 'PDF_TEXT_BOUNDS', 'OCR_BOUNDS', 'IMAGE_REGION')),
    page_number INTEGER NOT NULL CHECK (page_number >= 1),
    geometry_json_ciphertext BLOB,
    locator_version INTEGER NOT NULL CHECK (locator_version > 0),
    created_at TEXT NOT NULL,
    UNIQUE(id, workspace_id),
    FOREIGN KEY(document_version_id, workspace_id)
        REFERENCES document_versions(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(page_id, workspace_id)
        REFERENCES document_pages(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE
);

CREATE TABLE index_generations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    document_version_id TEXT NOT NULL,
    processing_job_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('STAGING', 'ACTIVE', 'ARCHIVED', 'FAILED')),
    embedding_model_id TEXT NOT NULL REFERENCES local_models(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    chunking_profile_version TEXT NOT NULL,
    normalization_profile_version TEXT NOT NULL,
    embedding_dimensions INTEGER NOT NULL CHECK (embedding_dimensions > 0),
    vector_dtype TEXT NOT NULL CHECK (vector_dtype = 'float32'),
    chunk_count INTEGER NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    created_at TEXT NOT NULL,
    activated_at TEXT,
    archived_at TEXT,
    UNIQUE(id, workspace_id),
    FOREIGN KEY(document_version_id, workspace_id)
        REFERENCES document_versions(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(processing_job_id, workspace_id)
        REFERENCES document_processing_jobs(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE
);

CREATE UNIQUE INDEX ux_version_one_active_index
ON index_generations(document_version_id) WHERE state = 'ACTIVE';

CREATE TABLE chunks (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    index_generation_id TEXT NOT NULL,
    document_version_id TEXT NOT NULL,
    page_id TEXT NOT NULL,
    source_locator_id TEXT NOT NULL,
    document_order INTEGER NOT NULL CHECK (document_order >= 0),
    page_order INTEGER NOT NULL CHECK (page_order >= 0),
    text_ciphertext BLOB NOT NULL,
    normalized_text_fingerprint BLOB NOT NULL,
    character_count INTEGER NOT NULL CHECK (character_count >= 0),
    token_count_estimate INTEGER CHECK (token_count_estimate IS NULL OR token_count_estimate >= 0),
    extraction_method TEXT NOT NULL CHECK (extraction_method IN ('NATIVE', 'OCR')),
    created_at TEXT NOT NULL,
    UNIQUE(index_generation_id, document_order),
    UNIQUE(id, workspace_id),
    FOREIGN KEY(index_generation_id, workspace_id)
        REFERENCES index_generations(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(document_version_id, workspace_id)
        REFERENCES document_versions(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(page_id, workspace_id)
        REFERENCES document_pages(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(source_locator_id, workspace_id)
        REFERENCES source_locators(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE
);

CREATE TABLE embeddings (
    chunk_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    index_generation_id TEXT NOT NULL,
    embedding_model_id TEXT NOT NULL REFERENCES local_models(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    dtype TEXT NOT NULL CHECK (dtype = 'float32'),
    is_unit_normalized INTEGER NOT NULL CHECK (is_unit_normalized = 1),
    vector_ciphertext BLOB NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(chunk_id, workspace_id)
        REFERENCES chunks(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(index_generation_id, workspace_id)
        REFERENCES index_generations(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE
);

CREATE TABLE chats (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    title_ciphertext BLOB,
    title_source TEXT,
    state TEXT NOT NULL CHECK (state IN ('EMPTY_DRAFT', 'ACTIVE', 'DELETING')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(id, workspace_id)
);

CREATE TABLE chat_scope_documents (
    chat_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    included_at TEXT NOT NULL,
    PRIMARY KEY(chat_id, document_id),
    FOREIGN KEY(chat_id, workspace_id)
        REFERENCES chats(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(document_id, workspace_id)
        REFERENCES documents(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE
);

CREATE TABLE chat_messages (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('USER', 'ASSISTANT')),
    sequence_number INTEGER NOT NULL CHECK (sequence_number >= 1),
    content_ciphertext BLOB NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(chat_id, sequence_number),
    UNIQUE(id, workspace_id),
    FOREIGN KEY(chat_id, workspace_id)
        REFERENCES chats(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE
);

CREATE TABLE chat_context_summaries (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    through_sequence_number INTEGER NOT NULL CHECK (through_sequence_number >= 1),
    content_ciphertext BLOB NOT NULL,
    summary_schema_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(id, workspace_id),
    FOREIGN KEY(chat_id, workspace_id)
        REFERENCES chats(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE
);

CREATE TABLE qa_requests (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    question_message_id TEXT NOT NULL,
    answer_message_id TEXT,
    state TEXT NOT NULL CHECK (state IN ('DRAFT', 'SEARCHING', 'EVALUATING_EVIDENCE', 'GENERATING', 'VALIDATING_CITATIONS', 'COMPLETED', 'COMPLETED_INSUFFICIENT', 'FAILED', 'CANCELLED')),
    evidence_state TEXT CHECK (evidence_state IS NULL OR evidence_state IN ('SUFFICIENT', 'RELATED_BUT_INSUFFICIENT', 'INSUFFICIENT')),
    chat_model_id TEXT REFERENCES local_models(id) ON UPDATE RESTRICT ON DELETE SET NULL,
    prompt_contract_version TEXT,
    top_k INTEGER CHECK (top_k IS NULL OR top_k > 0),
    evidence_policy_version TEXT,
    error_code TEXT,
    error_metadata_json TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    UNIQUE(id, workspace_id),
    FOREIGN KEY(chat_id, workspace_id)
        REFERENCES chats(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(question_message_id, workspace_id)
        REFERENCES chat_messages(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(answer_message_id, workspace_id)
        REFERENCES chat_messages(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE qa_scope_versions (
    qa_request_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    document_version_id TEXT NOT NULL,
    included_at TEXT NOT NULL,
    PRIMARY KEY(qa_request_id, document_version_id),
    FOREIGN KEY(qa_request_id, workspace_id)
        REFERENCES qa_requests(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(document_id, workspace_id)
        REFERENCES documents(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(document_version_id, workspace_id)
        REFERENCES document_versions(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE analyses (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL UNIQUE REFERENCES workspaces(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK (state IN ('NOT_CREATED', 'CURRENT', 'STALE')),
    current_version_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(id, workspace_id),
    FOREIGN KEY(current_version_id, workspace_id)
        REFERENCES analysis_versions(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE analysis_generation_runs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    analysis_id TEXT NOT NULL,
    run_type TEXT NOT NULL CHECK (run_type IN ('INITIAL', 'FULL_REGENERATION', 'SECTION_REGENERATION')),
    target_section_key TEXT,
    state TEXT NOT NULL CHECK (state IN ('QUEUED', 'GENERATING', 'VALIDATING', 'COMPLETED', 'FAILED', 'CANCELLED')),
    profile TEXT NOT NULL,
    chat_model_id TEXT REFERENCES local_models(id) ON UPDATE RESTRICT ON DELETE SET NULL,
    prompt_schema_version TEXT NOT NULL,
    error_code TEXT,
    error_metadata_json TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    UNIQUE(id, workspace_id),
    FOREIGN KEY(analysis_id, workspace_id)
        REFERENCES analyses(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE
);

CREATE TABLE analysis_generation_sections (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    generation_run_id TEXT NOT NULL,
    section_key TEXT NOT NULL,
    section_order INTEGER NOT NULL CHECK (section_order >= 0),
    state TEXT NOT NULL CHECK (state IN ('PENDING', 'RETRIEVING', 'GENERATING', 'VALIDATING', 'COMPLETED', 'FAILED', 'CANCELLED')),
    error_code TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(generation_run_id, section_key),
    UNIQUE(id, workspace_id),
    FOREIGN KEY(generation_run_id, workspace_id)
        REFERENCES analysis_generation_runs(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE
);

CREATE TABLE retrieval_runs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    purpose TEXT NOT NULL CHECK (purpose IN ('QA', 'ANALYSIS_SECTION')),
    qa_request_id TEXT,
    analysis_generation_section_id TEXT,
    query_ciphertext BLOB NOT NULL,
    embedding_model_id TEXT NOT NULL REFERENCES local_models(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    top_k INTEGER NOT NULL CHECK (top_k > 0),
    candidate_count INTEGER NOT NULL CHECK (candidate_count >= 0),
    retrieval_policy_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(id, workspace_id),
    CHECK ((purpose = 'QA' AND qa_request_id IS NOT NULL AND analysis_generation_section_id IS NULL)
        OR (purpose = 'ANALYSIS_SECTION' AND qa_request_id IS NULL AND analysis_generation_section_id IS NOT NULL)),
    FOREIGN KEY(qa_request_id, workspace_id)
        REFERENCES qa_requests(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(analysis_generation_section_id, workspace_id)
        REFERENCES analysis_generation_sections(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE
);

CREATE TABLE evidence_items (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    retrieval_run_id TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank >= 1),
    chunk_id TEXT,
    source_locator_id TEXT,
    document_id TEXT NOT NULL,
    document_version_id TEXT NOT NULL,
    document_display_name_ciphertext BLOB NOT NULL,
    version_number INTEGER NOT NULL CHECK (version_number >= 1),
    page_number INTEGER NOT NULL CHECK (page_number >= 1),
    excerpt_ciphertext BLOB,
    similarity_score REAL NOT NULL CHECK (similarity_score >= -1.0 AND similarity_score <= 1.0),
    availability TEXT NOT NULL CHECK (availability IN ('AVAILABLE', 'SOURCE_DELETED')),
    created_at TEXT NOT NULL,
    UNIQUE(retrieval_run_id, rank),
    UNIQUE(id, workspace_id),
    FOREIGN KEY(retrieval_run_id, workspace_id)
        REFERENCES retrieval_runs(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(chunk_id, workspace_id)
        REFERENCES chunks(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(source_locator_id, workspace_id)
        REFERENCES source_locators(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(document_id, workspace_id)
        REFERENCES documents(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(document_version_id, workspace_id)
        REFERENCES document_versions(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE citations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    evidence_item_id TEXT NOT NULL,
    answer_message_id TEXT,
    analysis_version_id TEXT,
    analysis_section_key TEXT,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    status TEXT NOT NULL CHECK (status IN ('VALID', 'SOURCE_DELETED')),
    created_at TEXT NOT NULL,
    UNIQUE(id, workspace_id),
    CHECK (
        (answer_message_id IS NOT NULL AND analysis_version_id IS NULL AND analysis_section_key IS NULL)
        OR
        (answer_message_id IS NULL AND analysis_version_id IS NOT NULL AND analysis_section_key IS NOT NULL)
    ),
    FOREIGN KEY(evidence_item_id, workspace_id)
        REFERENCES evidence_items(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(answer_message_id, workspace_id)
        REFERENCES chat_messages(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(analysis_version_id, workspace_id)
        REFERENCES analysis_versions(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE
);

CREATE TABLE analysis_generation_sources (
    generation_run_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    document_version_id TEXT NOT NULL,
    included_at TEXT NOT NULL,
    PRIMARY KEY(generation_run_id, document_version_id),
    FOREIGN KEY(generation_run_id, workspace_id)
        REFERENCES analysis_generation_runs(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(document_id, workspace_id)
        REFERENCES documents(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(document_version_id, workspace_id)
        REFERENCES document_versions(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE analysis_versions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    analysis_id TEXT NOT NULL,
    version_number INTEGER NOT NULL CHECK (version_number >= 1),
    creation_reason TEXT NOT NULL CHECK (creation_reason IN ('INITIAL_GENERATION', 'FULL_REGENERATION', 'SECTION_REGENERATION', 'USER_EDIT_SAVE', 'RESTORE')),
    content_source TEXT NOT NULL CHECK (content_source IN ('AI', 'USER', 'RESTORE', 'MIXED')),
    profile TEXT NOT NULL,
    profile_schema_version TEXT NOT NULL,
    generation_run_id TEXT,
    based_on_version_id TEXT,
    restored_from_version_id TEXT,
    changed_sections_json TEXT NOT NULL,
    source_set_fingerprint BLOB NOT NULL CHECK (
        typeof(source_set_fingerprint) = 'blob'
        AND length(source_set_fingerprint) = 32
    ),
    change_summary_ciphertext BLOB,
    created_at TEXT NOT NULL,
    UNIQUE(analysis_id, version_number),
    UNIQUE(id, workspace_id),
    CHECK (
        (
            creation_reason = 'RESTORE'
            AND content_source = 'RESTORE'
            AND restored_from_version_id IS NOT NULL
            AND generation_run_id IS NULL
        )
        OR
        (
            creation_reason <> 'RESTORE'
            AND restored_from_version_id IS NULL
        )
    ),
    FOREIGN KEY(analysis_id, workspace_id)
        REFERENCES analyses(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(generation_run_id, workspace_id)
        REFERENCES analysis_generation_runs(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(based_on_version_id, workspace_id)
        REFERENCES analysis_versions(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(restored_from_version_id, workspace_id)
        REFERENCES analysis_versions(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE analysis_sections (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    analysis_version_id TEXT NOT NULL,
    section_key TEXT NOT NULL,
    section_order INTEGER NOT NULL CHECK (section_order >= 0),
    content_ciphertext BLOB NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(analysis_version_id, section_key),
    UNIQUE(id, workspace_id),
    FOREIGN KEY(analysis_version_id, workspace_id)
        REFERENCES analysis_versions(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE
);

CREATE TABLE analysis_version_sources (
    analysis_version_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    document_version_id TEXT NOT NULL,
    included_at TEXT NOT NULL,
    PRIMARY KEY(analysis_version_id, document_version_id),
    FOREIGN KEY(analysis_version_id, workspace_id)
        REFERENCES analysis_versions(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(document_id, workspace_id)
        REFERENCES documents(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(document_version_id, workspace_id)
        REFERENCES document_versions(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE analysis_drafts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    analysis_id TEXT NOT NULL,
    base_version_id TEXT,
    state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'SAVED', 'DISCARDED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    saved_at TEXT,
    discarded_at TEXT,
    UNIQUE(id, workspace_id),
    FOREIGN KEY(analysis_id, workspace_id)
        REFERENCES analyses(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(base_version_id, workspace_id)
        REFERENCES analysis_versions(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE UNIQUE INDEX ux_analysis_one_active_draft
ON analysis_drafts(analysis_id) WHERE state = 'ACTIVE';

CREATE TABLE analysis_draft_sections (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    draft_id TEXT NOT NULL,
    section_key TEXT NOT NULL,
    section_order INTEGER NOT NULL CHECK (section_order >= 0),
    content_ciphertext BLOB NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(draft_id, section_key),
    FOREIGN KEY(draft_id, workspace_id)
        REFERENCES analysis_drafts(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE
);

CREATE TABLE analysis_stale_reasons (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    analysis_id TEXT NOT NULL,
    reason_type TEXT NOT NULL,
    summary_ciphertext BLOB,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY(analysis_id, workspace_id)
        REFERENCES analyses(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE
);

CREATE TABLE activity_events (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    category TEXT NOT NULL CHECK (category IN ('WORKSPACE', 'DOCUMENT', 'CHAT', 'ANALYSIS', 'SECURITY', 'ERROR')),
    event_type TEXT NOT NULL,
    result_status TEXT NOT NULL CHECK (result_status IN ('STARTED', 'SUCCESS', 'WARNING', 'FAILED', 'CANCELLED')),
    subject_type TEXT,
    subject_id TEXT,
    summary_key TEXT NOT NULL,
    safe_metadata_json TEXT,
    correlation_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE deletion_tasks (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    target_type TEXT NOT NULL CHECK (target_type IN ('DOCUMENT', 'WORKSPACE')),
    target_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('PLANNED', 'IN_PROGRESS', 'FAILED', 'COMPLETED')),
    plan_metadata_json TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_error_code TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE recovery_actions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT REFERENCES workspaces(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    operation_type TEXT NOT NULL CHECK (operation_type IN ('DOCUMENT_PROCESSING', 'DELETION', 'DATABASE_REPAIR', 'KEY_ACCESS', 'APPLICATION_RESET')),
    operation_id TEXT,
    detected_at TEXT NOT NULL,
    selected_action TEXT,
    resolved_at TEXT,
    result_status TEXT,
    safe_metadata_json TEXT,
    CHECK (
        workspace_id IS NOT NULL
        OR operation_type IN ('DATABASE_REPAIR', 'KEY_ACCESS', 'APPLICATION_RESET')
    )
);

CREATE INDEX ix_workspaces_state_updated ON workspaces(state, updated_at DESC);
CREATE INDEX ix_documents_workspace_state ON documents(workspace_id, state, updated_at DESC);
CREATE INDEX ix_versions_workspace_document ON document_versions(workspace_id, document_id, version_number DESC);
CREATE INDEX ix_pages_version_number ON document_pages(document_version_id, page_number);
CREATE INDEX ix_processing_jobs_recovery ON document_processing_jobs(state, heartbeat_at);
CREATE INDEX ix_chunks_generation ON chunks(index_generation_id, document_order);
CREATE INDEX ix_embeddings_generation ON embeddings(index_generation_id);
CREATE INDEX ix_chats_workspace_updated ON chats(workspace_id, updated_at DESC);
CREATE INDEX ix_messages_chat_sequence ON chat_messages(chat_id, sequence_number);
CREATE INDEX ix_qa_chat_created ON qa_requests(chat_id, created_at DESC);
CREATE INDEX ix_evidence_retrieval_rank ON evidence_items(retrieval_run_id, rank);
CREATE INDEX ix_analysis_versions_analysis_number ON analysis_versions(analysis_id, version_number DESC);
CREATE INDEX ix_activity_workspace_time ON activity_events(workspace_id, created_at DESC);
