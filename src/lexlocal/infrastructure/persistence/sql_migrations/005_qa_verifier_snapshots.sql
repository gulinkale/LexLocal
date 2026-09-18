CREATE TABLE qa_verifier_snapshots (
    qa_request_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    retrieval_run_id TEXT NOT NULL UNIQUE,
    evidence_policy_version TEXT NOT NULL CHECK (length(trim(evidence_policy_version)) > 0),
    aggregate_coverage TEXT NOT NULL CHECK (aggregate_coverage IN ('READY', 'READY_WITH_WARNINGS')),
    supports_count INTEGER NOT NULL CHECK (supports_count >= 0),
    related_only_count INTEGER NOT NULL CHECK (related_only_count >= 0),
    contradicts_count INTEGER NOT NULL CHECK (contradicts_count >= 0),
    irrelevant_count INTEGER NOT NULL CHECK (irrelevant_count >= 0),
    repair_used INTEGER NOT NULL CHECK (repair_used IN (0, 1)),
    UNIQUE(qa_request_id, workspace_id, retrieval_run_id),
    CHECK (
        supports_count + related_only_count + contradicts_count + irrelevant_count > 0
        OR repair_used = 0
    ),
    FOREIGN KEY(qa_request_id, workspace_id)
        REFERENCES qa_requests(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(retrieval_run_id, workspace_id)
        REFERENCES retrieval_runs(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE
);

CREATE TABLE qa_verifier_snapshot_relations (
    qa_request_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    retrieval_run_id TEXT NOT NULL,
    evidence_item_id TEXT NOT NULL,
    relation TEXT NOT NULL CHECK (relation IN ('SUPPORTS', 'RELATED_ONLY', 'CONTRADICTS', 'IRRELEVANT')),
    PRIMARY KEY(qa_request_id, evidence_item_id),
    UNIQUE(retrieval_run_id, evidence_item_id),
    FOREIGN KEY(qa_request_id, workspace_id, retrieval_run_id)
        REFERENCES qa_verifier_snapshots(qa_request_id, workspace_id, retrieval_run_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(evidence_item_id, workspace_id)
        REFERENCES evidence_items(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);
