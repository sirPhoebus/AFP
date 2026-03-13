"""SQLite-backed repository for orchestrator bootstrap entities."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from json import dumps, loads
from uuid import UUID

from workflow_engine import LifecycleState
from workflow_engine.events import WorkflowEvent

from .schema import init_db


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RunRecord:
    id: UUID
    title: str
    state: LifecycleState
    seeded_bootstrap_task: bool


@dataclass(frozen=True)
class TaskRecord:
    id: UUID
    run_id: UUID
    name: str
    state: LifecycleState
    retry_count: int
    max_retries: int


@dataclass(frozen=True)
class ApprovalRecord:
    id: UUID
    run_id: UUID
    task_id: UUID | None
    status: str
    requested_by: str
    decided_by: str | None
    decision_note: str | None


@dataclass(frozen=True)
class ArtefactRecord:
    id: UUID
    run_id: UUID
    task_id: UUID | None
    path: str
    checksum: str
    version: str
    producer: str


@dataclass(frozen=True)
class ExecutionRecord:
    id: UUID
    run_id: UUID
    task_id: UUID
    status: str
    runner_kind: str
    attempt: int


@dataclass(frozen=True)
class LogRecord:
    id: UUID
    run_id: UUID
    task_id: UUID | None
    execution_id: UUID | None
    level: str
    message: str


@dataclass(frozen=True)
class WorkflowEventRecord:
    event_id: str
    event_type: str
    run_id: UUID | None
    task_id: UUID | None
    payload: dict
    idempotency_key: str | None
    created_at: str


class SQLiteRepository:
    """Simple repository around a single SQLite connection."""

    def __init__(self, dsn: str = ":memory:") -> None:
        self.connection = sqlite3.connect(dsn, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        init_db(self.connection)

    def reset_tables(self, table_names: Iterable[str]) -> None:
        for table_name in table_names:
            self.connection.execute(f"DELETE FROM {table_name}")
        self.connection.commit()

    def create_run(self, *, run_id: UUID, title: str, state: LifecycleState, seeded_bootstrap_task: bool) -> RunRecord:
        now = _utc_now()
        self.connection.execute(
            """
            INSERT INTO runs (id, title, state, seeded_bootstrap_task, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(run_id), title, state.value, int(seeded_bootstrap_task), now, now),
        )
        self.connection.commit()
        return self.get_run(str(run_id))

    def get_run(self, run_id: str) -> RunRecord | None:
        row = self.connection.execute(
            "SELECT id, title, state, seeded_bootstrap_task FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return RunRecord(
            id=UUID(row["id"]),
            title=row["title"],
            state=LifecycleState(row["state"]),
            seeded_bootstrap_task=bool(row["seeded_bootstrap_task"]),
        )

    def update_run_state(self, *, run_id: UUID, state: LifecycleState) -> RunRecord | None:
        now = _utc_now()
        self.connection.execute(
            """
            UPDATE runs
            SET state = ?, updated_at = ?
            WHERE id = ?
            """,
            (state.value, now, str(run_id)),
        )
        self.connection.commit()
        return self.get_run(str(run_id))

    def create_task(self, *, task_id: UUID, run_id: UUID, name: str, state: LifecycleState, max_retries: int) -> TaskRecord:
        now = _utc_now()
        self.connection.execute(
            """
            INSERT INTO tasks (id, run_id, name, state, retry_count, max_retries, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (str(task_id), str(run_id), name, state.value, max_retries, now, now),
        )
        self.connection.commit()
        return self.get_task(str(task_id))

    def get_task(self, task_id: str) -> TaskRecord | None:
        row = self.connection.execute(
            "SELECT id, run_id, name, state, retry_count, max_retries FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return TaskRecord(
            id=UUID(row["id"]),
            run_id=UUID(row["run_id"]),
            name=row["name"],
            state=LifecycleState(row["state"]),
            retry_count=row["retry_count"],
            max_retries=row["max_retries"],
        )

    def update_task_state(
        self,
        *,
        task_id: UUID,
        state: LifecycleState,
        retry_count: int | None = None,
    ) -> TaskRecord | None:
        now = _utc_now()
        if retry_count is None:
            self.connection.execute(
                """
                UPDATE tasks
                SET state = ?, updated_at = ?
                WHERE id = ?
                """,
                (state.value, now, str(task_id)),
            )
        else:
            self.connection.execute(
                """
                UPDATE tasks
                SET state = ?, retry_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (state.value, retry_count, now, str(task_id)),
            )
        self.connection.commit()
        return self.get_task(str(task_id))

    def list_tasks_for_run(self, run_id: str) -> list[TaskRecord]:
        rows = self.connection.execute(
            """
            SELECT id, run_id, name, state, retry_count, max_retries
            FROM tasks
            WHERE run_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
        return [
            TaskRecord(
                id=UUID(row["id"]),
                run_id=UUID(row["run_id"]),
                name=row["name"],
                state=LifecycleState(row["state"]),
                retry_count=row["retry_count"],
                max_retries=row["max_retries"],
            )
            for row in rows
        ]

    def list_tasks_by_state(self, state: LifecycleState) -> list[TaskRecord]:
        rows = self.connection.execute(
            """
            SELECT id, run_id, name, state, retry_count, max_retries
            FROM tasks
            WHERE state = ?
            ORDER BY created_at ASC, id ASC
            """,
            (state.value,),
        ).fetchall()
        return [
            TaskRecord(
                id=UUID(row["id"]),
                run_id=UUID(row["run_id"]),
                name=row["name"],
                state=LifecycleState(row["state"]),
                retry_count=row["retry_count"],
                max_retries=row["max_retries"],
            )
            for row in rows
        ]

    def create_approval(
        self,
        *,
        approval_id: UUID,
        run_id: UUID,
        task_id: UUID | None,
        status: str,
        requested_by: str,
        decided_by: str | None,
        decision_note: str | None,
    ) -> ApprovalRecord:
        now = _utc_now()
        self.connection.execute(
            """
            INSERT INTO approvals (id, run_id, task_id, status, requested_by, decided_by, decision_note, created_at, decided_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                str(approval_id),
                str(run_id),
                str(task_id) if task_id is not None else None,
                status,
                requested_by,
                decided_by,
                decision_note,
                now,
            ),
        )
        self.connection.commit()
        return self.get_approval(str(approval_id))

    def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        row = self.connection.execute(
            """
            SELECT id, run_id, task_id, status, requested_by, decided_by, decision_note
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()
        if row is None:
            return None
        return ApprovalRecord(
            id=UUID(row["id"]),
            run_id=UUID(row["run_id"]),
            task_id=UUID(row["task_id"]) if row["task_id"] is not None else None,
            status=row["status"],
            requested_by=row["requested_by"],
            decided_by=row["decided_by"],
            decision_note=row["decision_note"],
        )

    def list_approvals_for_run(self, run_id: str) -> list[ApprovalRecord]:
        rows = self.connection.execute(
            """
            SELECT id, run_id, task_id, status, requested_by, decided_by, decision_note
            FROM approvals
            WHERE run_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
        return [
            ApprovalRecord(
                id=UUID(row["id"]),
                run_id=UUID(row["run_id"]),
                task_id=UUID(row["task_id"]) if row["task_id"] is not None else None,
                status=row["status"],
                requested_by=row["requested_by"],
                decided_by=row["decided_by"],
                decision_note=row["decision_note"],
            )
            for row in rows
        ]

    def update_approval(
        self,
        *,
        approval_id: UUID,
        status: str,
        decided_by: str | None,
        decision_note: str | None,
    ) -> ApprovalRecord | None:
        now = _utc_now()
        self.connection.execute(
            """
            UPDATE approvals
            SET status = ?, decided_by = ?, decision_note = ?, decided_at = ?
            WHERE id = ?
            """,
            (status, decided_by, decision_note, now, str(approval_id)),
        )
        self.connection.commit()
        return self.get_approval(str(approval_id))

    def list_approvals_for_task(self, task_id: str) -> list[ApprovalRecord]:
        rows = self.connection.execute(
            """
            SELECT id, run_id, task_id, status, requested_by, decided_by, decision_note
            FROM approvals
            WHERE task_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (task_id,),
        ).fetchall()
        return [
            ApprovalRecord(
                id=UUID(row["id"]),
                run_id=UUID(row["run_id"]),
                task_id=UUID(row["task_id"]) if row["task_id"] is not None else None,
                status=row["status"],
                requested_by=row["requested_by"],
                decided_by=row["decided_by"],
                decision_note=row["decision_note"],
            )
            for row in rows
        ]

    def create_artefact(
        self,
        *,
        artefact_id: UUID,
        run_id: UUID,
        task_id: UUID | None,
        path: str,
        checksum: str,
        version: str,
        producer: str,
    ) -> ArtefactRecord:
        now = _utc_now()
        self.connection.execute(
            """
            INSERT INTO artefacts (id, run_id, task_id, path, checksum, version, producer, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(artefact_id),
                str(run_id),
                str(task_id) if task_id is not None else None,
                path,
                checksum,
                version,
                producer,
                now,
            ),
        )
        self.connection.commit()
        return self.get_artefact(str(artefact_id))

    def get_artefact(self, artefact_id: str) -> ArtefactRecord | None:
        row = self.connection.execute(
            """
            SELECT id, run_id, task_id, path, checksum, version, producer
            FROM artefacts
            WHERE id = ?
            """,
            (artefact_id,),
        ).fetchone()
        if row is None:
            return None
        return ArtefactRecord(
            id=UUID(row["id"]),
            run_id=UUID(row["run_id"]),
            task_id=UUID(row["task_id"]) if row["task_id"] is not None else None,
            path=row["path"],
            checksum=row["checksum"],
            version=row["version"],
            producer=row["producer"],
        )

    def list_artefacts_for_run(self, run_id: str, *, task_id: str | None = None) -> list[ArtefactRecord]:
        if task_id is None:
            rows = self.connection.execute(
                """
                SELECT id, run_id, task_id, path, checksum, version, producer
                FROM artefacts
                WHERE run_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (run_id,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT id, run_id, task_id, path, checksum, version, producer
                FROM artefacts
                WHERE run_id = ? AND task_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (run_id, task_id),
            ).fetchall()
        return [
            ArtefactRecord(
                id=UUID(row["id"]),
                run_id=UUID(row["run_id"]),
                task_id=UUID(row["task_id"]) if row["task_id"] is not None else None,
                path=row["path"],
                checksum=row["checksum"],
                version=row["version"],
                producer=row["producer"],
            )
            for row in rows
        ]

    def create_execution(
        self,
        *,
        execution_id: UUID,
        run_id: UUID,
        task_id: UUID,
        status: str,
        runner_kind: str,
        attempt: int,
    ) -> ExecutionRecord:
        now = _utc_now()
        self.connection.execute(
            """
            INSERT INTO executions (id, run_id, task_id, status, runner_kind, attempt, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (str(execution_id), str(run_id), str(task_id), status, runner_kind, attempt, now, now),
        )
        self.connection.commit()
        return ExecutionRecord(
            id=execution_id,
            run_id=run_id,
            task_id=task_id,
            status=status,
            runner_kind=runner_kind,
            attempt=attempt,
        )

    def list_executions_for_run(self, run_id: str) -> list[ExecutionRecord]:
        rows = self.connection.execute(
            """
            SELECT id, run_id, task_id, status, runner_kind, attempt
            FROM executions
            WHERE run_id = ?
            ORDER BY started_at ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
        return [
            ExecutionRecord(
                id=UUID(row["id"]),
                run_id=UUID(row["run_id"]),
                task_id=UUID(row["task_id"]),
                status=row["status"],
                runner_kind=row["runner_kind"],
                attempt=row["attempt"],
            )
            for row in rows
        ]

    def create_log(
        self,
        *,
        log_id: UUID,
        run_id: UUID,
        task_id: UUID | None,
        execution_id: UUID | None,
        level: str,
        message: str,
    ) -> LogRecord:
        now = _utc_now()
        self.connection.execute(
            """
            INSERT INTO logs (id, run_id, task_id, execution_id, level, message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(log_id),
                str(run_id),
                str(task_id) if task_id is not None else None,
                str(execution_id) if execution_id is not None else None,
                level,
                message,
                now,
            ),
        )
        self.connection.commit()
        return LogRecord(
            id=log_id,
            run_id=run_id,
            task_id=task_id,
            execution_id=execution_id,
            level=level,
            message=message,
        )

    def list_logs_for_run(self, run_id: str) -> list[LogRecord]:
        rows = self.connection.execute(
            """
            SELECT id, run_id, task_id, execution_id, level, message
            FROM logs
            WHERE run_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
        return [
            LogRecord(
                id=UUID(row["id"]),
                run_id=UUID(row["run_id"]),
                task_id=UUID(row["task_id"]) if row["task_id"] is not None else None,
                execution_id=UUID(row["execution_id"]) if row["execution_id"] is not None else None,
                level=row["level"],
                message=row["message"],
            )
            for row in rows
        ]

    def create_workflow_event(self, event: WorkflowEvent) -> WorkflowEventRecord:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO workflow_events
            (event_id, event_type, run_id, task_id, payload_json, idempotency_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.event_type,
                str(event.run_id) if event.run_id is not None else None,
                str(event.task_id) if event.task_id is not None else None,
                dumps(event.payload, sort_keys=True),
                event.idempotency_key,
                event.created_at.isoformat(),
            ),
        )
        self.connection.commit()
        return WorkflowEventRecord(
            event_id=event.event_id,
            event_type=event.event_type,
            run_id=event.run_id,
            task_id=event.task_id,
            payload=event.payload,
            idempotency_key=event.idempotency_key,
            created_at=event.created_at.isoformat(),
        )

    def get_workflow_event_by_idempotency_key(self, idempotency_key: str) -> WorkflowEventRecord | None:
        row = self.connection.execute(
            """
            SELECT event_id, event_type, run_id, task_id, payload_json, idempotency_key, created_at
            FROM workflow_events
            WHERE idempotency_key = ?
            ORDER BY created_at ASC, event_id ASC
            LIMIT 1
            """,
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        return WorkflowEventRecord(
            event_id=row["event_id"],
            event_type=row["event_type"],
            run_id=UUID(row["run_id"]) if row["run_id"] is not None else None,
            task_id=UUID(row["task_id"]) if row["task_id"] is not None else None,
            payload=loads(row["payload_json"]),
            idempotency_key=row["idempotency_key"],
            created_at=row["created_at"],
        )

    def list_workflow_events(self, *, run_id: str | None = None) -> list[WorkflowEventRecord]:
        if run_id is None:
            rows = self.connection.execute(
                """
                SELECT event_id, event_type, run_id, task_id, payload_json, idempotency_key, created_at
                FROM workflow_events
                ORDER BY created_at ASC, event_id ASC
                """
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT event_id, event_type, run_id, task_id, payload_json, idempotency_key, created_at
                FROM workflow_events
                WHERE run_id = ?
                ORDER BY created_at ASC, event_id ASC
                """,
                (run_id,),
            ).fetchall()
        return [
            WorkflowEventRecord(
                event_id=row["event_id"],
                event_type=row["event_type"],
                run_id=UUID(row["run_id"]) if row["run_id"] is not None else None,
                task_id=UUID(row["task_id"]) if row["task_id"] is not None else None,
                payload=loads(row["payload_json"]),
                idempotency_key=row["idempotency_key"],
                created_at=row["created_at"],
            )
            for row in rows
        ]


class TableResetView:
    """Small compatibility facade used by tests that call `.clear()`."""

    def __init__(self, repository: SQLiteRepository, *table_names: str) -> None:
        self.repository = repository
        self.table_names = table_names

    def clear(self) -> None:
        self.repository.reset_tables(self.table_names)
