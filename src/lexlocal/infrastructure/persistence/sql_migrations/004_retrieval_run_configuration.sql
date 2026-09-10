ALTER TABLE retrieval_runs
ADD COLUMN min_similarity REAL NOT NULL DEFAULT 0.0
CHECK (min_similarity >= -1.0 AND min_similarity <= 1.0);

CREATE TABLE retrieval_run_generations (
    retrieval_run_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    index_generation_id TEXT NOT NULL,
    PRIMARY KEY(retrieval_run_id, index_generation_id),
    FOREIGN KEY(retrieval_run_id, workspace_id)
        REFERENCES retrieval_runs(id, workspace_id) ON UPDATE RESTRICT ON DELETE CASCADE,
    FOREIGN KEY(index_generation_id, workspace_id)
        REFERENCES index_generations(id, workspace_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);
