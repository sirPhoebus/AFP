-- Core schema baseline with indexes and operational metadata.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outbox_events (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    published_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_run_state ON tasks(run_id, state);
CREATE INDEX IF NOT EXISTS idx_tasks_claimed_by ON tasks(claimed_by, state);
CREATE INDEX IF NOT EXISTS idx_approvals_run_status ON approvals(run_id, status);
CREATE INDEX IF NOT EXISTS idx_workflow_events_run_created ON workflow_events(run_id, created_at);
