"""Core schema bootstrap and migrations."""

from sqlite3 import Connection
from pathlib import Path


CORE_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        state TEXT NOT NULL,
        seeded_bootstrap_task INTEGER NOT NULL DEFAULT 0,
        lock_version INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        name TEXT NOT NULL,
        state TEXT NOT NULL,
        retry_count INTEGER NOT NULL DEFAULT 0,
        max_retries INTEGER NOT NULL DEFAULT 3,
        lock_version INTEGER NOT NULL DEFAULT 0,
        claimed_by TEXT,
        claimed_at TEXT,
        next_attempt_at TEXT,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK (retry_count >= 0),
        CHECK (max_retries >= 0),
        FOREIGN KEY (run_id) REFERENCES runs(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS task_dependencies (
        task_id TEXT NOT NULL,
        depends_on_task_id TEXT NOT NULL,
        PRIMARY KEY (task_id, depends_on_task_id),
        FOREIGN KEY (task_id) REFERENCES tasks(id),
        FOREIGN KEY (depends_on_task_id) REFERENCES tasks(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS approvals (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        task_id TEXT,
        status TEXT NOT NULL,
        requested_by TEXT NOT NULL,
        decided_by TEXT,
        decision_note TEXT,
        scope TEXT NOT NULL DEFAULT 'task',
        role TEXT NOT NULL DEFAULT 'reviewer',
        required_approvals INTEGER NOT NULL DEFAULT 1,
        invalidated_at TEXT,
        invalidation_reason TEXT,
        created_at TEXT NOT NULL,
        decided_at TEXT,
        CHECK (required_approvals >= 1),
        FOREIGN KEY (run_id) REFERENCES runs(id),
        FOREIGN KEY (task_id) REFERENCES tasks(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS artefacts (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        task_id TEXT,
        path TEXT NOT NULL,
        checksum TEXT NOT NULL,
        version TEXT NOT NULL,
        producer TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES runs(id),
        FOREIGN KEY (task_id) REFERENCES tasks(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS executions (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        status TEXT NOT NULL,
        runner_kind TEXT NOT NULL,
        attempt INTEGER NOT NULL,
        phase TEXT NOT NULL DEFAULT 'queued',
        correlation_id TEXT,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        FOREIGN KEY (run_id) REFERENCES runs(id),
        FOREIGN KEY (task_id) REFERENCES tasks(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS logs (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        task_id TEXT,
        execution_id TEXT,
        level TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES runs(id),
        FOREIGN KEY (task_id) REFERENCES tasks(id),
        FOREIGN KEY (execution_id) REFERENCES executions(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS eval_runs (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        task_id TEXT,
        status TEXT NOT NULL,
        evaluator TEXT NOT NULL,
        summary TEXT,
        created_at TEXT NOT NULL,
        finished_at TEXT,
        FOREIGN KEY (run_id) REFERENCES runs(id),
        FOREIGN KEY (task_id) REFERENCES tasks(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS policy_decisions (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        task_id TEXT,
        eval_run_id TEXT,
        decision TEXT NOT NULL,
        reason_code TEXT NOT NULL,
        rationale TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES runs(id),
        FOREIGN KEY (task_id) REFERENCES tasks(id),
        FOREIGN KEY (eval_run_id) REFERENCES eval_runs(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_events (
        event_id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        run_id TEXT,
        task_id TEXT,
        payload_json TEXT NOT NULL,
        idempotency_key TEXT,
        correlation_id TEXT,
        causation_id TEXT,
        schema_version INTEGER NOT NULL DEFAULT 1,
        replayed_from_event_id TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES runs(id),
        FOREIGN KEY (task_id) REFERENCES tasks(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS unit_evidence (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        execution_id TEXT NOT NULL,
        status TEXT NOT NULL,
        command TEXT NOT NULL,
        output TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES runs(id),
        FOREIGN KEY (task_id) REFERENCES tasks(id),
        FOREIGN KEY (execution_id) REFERENCES executions(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pull_requests (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        title TEXT NOT NULL,
        branch TEXT NOT NULL,
        status TEXT NOT NULL,
        url TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES runs(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ci_checks (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL,
        details TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES runs(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS outbox_events (
        id TEXT PRIMARY KEY,
        event_id TEXT NOT NULL,
        topic TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        published_at TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (event_id) REFERENCES workflow_events(event_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL
    )
    """,
)

INDEX_STATEMENTS: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_tasks_run_state ON tasks(run_id, state)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_claimed_by ON tasks(claimed_by, state)",
    "CREATE INDEX IF NOT EXISTS idx_approvals_run_status ON approvals(run_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_workflow_events_run_created ON workflow_events(run_id, created_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_workflow_events_idempotency ON workflow_events(idempotency_key) WHERE idempotency_key IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_outbox_published ON outbox_events(published_at, created_at)",
)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"


def init_db(connection: Connection) -> None:
    """Create the core schema on an open SQLite connection."""
    connection.execute("PRAGMA foreign_keys = ON")
    for statement in CORE_SCHEMA_STATEMENTS:
        connection.execute(statement)
    for statement in INDEX_STATEMENTS:
        connection.execute(statement)
    if MIGRATIONS_DIR.exists():
        for migration_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
                (migration_path.name,),
            )
    connection.commit()
