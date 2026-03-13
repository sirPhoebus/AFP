"""SQLite-backed persistence backend."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from json import dumps, loads
from uuid import UUID

from workflow_engine import LifecycleState
from workflow_engine.events import WorkflowEvent

from .records import (
    ApprovalRecord,
    ArtefactRecord,
    CiCheckRecord,
    ExecutionRecord,
    LogRecord,
    OutboxEventRecord,
    PullRequestRecord,
    RunRecord,
    TaskDependencyRecord,
    TaskRecord,
    UnitEvidenceRecord,
    WorkflowEventRecord,
    utc_now,
)
from .schema import init_db


class SQLiteRepository:
    """Simple repository around a single SQLite connection."""

    def __init__(self, dsn: str = ":memory:") -> None:
        self.connection = sqlite3.connect(dsn, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        init_db(self.connection)

    def reset_tables(self, table_names: Iterable[str]) -> None:
        self.connection.execute("PRAGMA foreign_keys = OFF")
        try:
            for table_name in table_names:
                self.connection.execute(f"DELETE FROM {table_name}")
            self.connection.commit()
        finally:
            self.connection.execute("PRAGMA foreign_keys = ON")

    def create_run(self, *, run_id: UUID, title: str, state: LifecycleState, seeded_bootstrap_task: bool) -> RunRecord:
        now = utc_now()
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
        now = utc_now()
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
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO tasks (id, run_id, name, state, retry_count, max_retries, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (str(task_id), str(run_id), name, state.value, max_retries, now, now),
        )
        self.connection.commit()
        return self.get_task(str(task_id))

    def create_task_dependency(self, *, task_id: UUID, depends_on_task_id: UUID) -> TaskDependencyRecord:
        self.connection.execute(
            """
            INSERT INTO task_dependencies (task_id, depends_on_task_id)
            VALUES (?, ?)
            """,
            (str(task_id), str(depends_on_task_id)),
        )
        self.connection.commit()
        return TaskDependencyRecord(task_id=task_id, depends_on_task_id=depends_on_task_id)

    def list_dependencies_for_task(self, task_id: str) -> list[TaskDependencyRecord]:
        rows = self.connection.execute(
            """
            SELECT task_id, depends_on_task_id
            FROM task_dependencies
            WHERE task_id = ?
            ORDER BY depends_on_task_id ASC
            """,
            (task_id,),
        ).fetchall()
        return [
            TaskDependencyRecord(task_id=UUID(row["task_id"]), depends_on_task_id=UUID(row["depends_on_task_id"]))
            for row in rows
        ]

    def list_dependents_for_task(self, task_id: str) -> list[TaskDependencyRecord]:
        rows = self.connection.execute(
            """
            SELECT task_id, depends_on_task_id
            FROM task_dependencies
            WHERE depends_on_task_id = ?
            ORDER BY task_id ASC
            """,
            (task_id,),
        ).fetchall()
        return [
            TaskDependencyRecord(task_id=UUID(row["task_id"]), depends_on_task_id=UUID(row["depends_on_task_id"]))
            for row in rows
        ]

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
        now = utc_now()
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
        scope: str = "task",
        role: str = "reviewer",
        required_approvals: int = 1,
    ) -> ApprovalRecord:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO approvals (id, run_id, task_id, status, requested_by, decided_by, decision_note, scope, role, required_approvals, created_at, decided_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                str(approval_id),
                str(run_id),
                str(task_id) if task_id is not None else None,
                status,
                requested_by,
                decided_by,
                decision_note,
                scope,
                role,
                required_approvals,
                now,
            ),
        )
        self.connection.commit()
        return self.get_approval(str(approval_id))

    def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        row = self.connection.execute(
            """
            SELECT id, run_id, task_id, status, requested_by, decided_by, decision_note, scope, role, required_approvals, invalidated_at, invalidation_reason
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
            scope=row["scope"],
            role=row["role"],
            required_approvals=row["required_approvals"],
            invalidated_at=row["invalidated_at"],
            invalidation_reason=row["invalidation_reason"],
        )

    def list_approvals_for_run(self, run_id: str) -> list[ApprovalRecord]:
        rows = self.connection.execute(
            """
            SELECT id, run_id, task_id, status, requested_by, decided_by, decision_note, scope, role, required_approvals, invalidated_at, invalidation_reason
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
                scope=row["scope"],
                role=row["role"],
                required_approvals=row["required_approvals"],
                invalidated_at=row["invalidated_at"],
                invalidation_reason=row["invalidation_reason"],
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
        now = utc_now()
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
            SELECT id, run_id, task_id, status, requested_by, decided_by, decision_note, scope, role, required_approvals, invalidated_at, invalidation_reason
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
                scope=row["scope"],
                role=row["role"],
                required_approvals=row["required_approvals"],
                invalidated_at=row["invalidated_at"],
                invalidation_reason=row["invalidation_reason"],
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
        now = utc_now()
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
        phase: str = "queued",
        correlation_id: str | None = None,
    ) -> ExecutionRecord:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO executions (id, run_id, task_id, status, runner_kind, attempt, phase, correlation_id, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (str(execution_id), str(run_id), str(task_id), status, runner_kind, attempt, phase, correlation_id, now, now),
        )
        self.connection.commit()
        return ExecutionRecord(
            id=execution_id,
            run_id=run_id,
            task_id=task_id,
            status=status,
            runner_kind=runner_kind,
            attempt=attempt,
            phase=phase,
            correlation_id=correlation_id,
            started_at=now,
            finished_at=now,
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
        now = utc_now()
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
            (event_id, event_type, run_id, task_id, payload_json, idempotency_key, correlation_id, causation_id, schema_version, replayed_from_event_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.event_type,
                str(event.run_id) if event.run_id is not None else None,
                str(event.task_id) if event.task_id is not None else None,
                dumps(event.payload, sort_keys=True),
                event.idempotency_key,
                event.correlation_id,
                event.causation_id,
                event.schema_version,
                event.replayed_from_event_id,
                event.created_at.isoformat(),
            ),
        )
        self.connection.commit()
        self.create_outbox_event(event)
        return WorkflowEventRecord(
            event_id=event.event_id,
            event_type=event.event_type,
            run_id=event.run_id,
            task_id=event.task_id,
            payload=event.payload,
            idempotency_key=event.idempotency_key,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            schema_version=event.schema_version,
            replayed_from_event_id=event.replayed_from_event_id,
            created_at=event.created_at.isoformat(),
        )

    def get_workflow_event_by_idempotency_key(self, idempotency_key: str) -> WorkflowEventRecord | None:
        row = self.connection.execute(
            """
            SELECT event_id, event_type, run_id, task_id, payload_json, idempotency_key, correlation_id, causation_id, schema_version, replayed_from_event_id, created_at
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
            correlation_id=row["correlation_id"],
            causation_id=row["causation_id"],
            schema_version=row["schema_version"],
            replayed_from_event_id=row["replayed_from_event_id"],
            created_at=row["created_at"],
        )

    def list_workflow_events(self, *, run_id: str | None = None) -> list[WorkflowEventRecord]:
        if run_id is None:
            rows = self.connection.execute(
                """
                SELECT event_id, event_type, run_id, task_id, payload_json, idempotency_key, correlation_id, causation_id, schema_version, replayed_from_event_id, created_at
                FROM workflow_events
                ORDER BY created_at ASC, event_id ASC
                """
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT event_id, event_type, run_id, task_id, payload_json, idempotency_key, correlation_id, causation_id, schema_version, replayed_from_event_id, created_at
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
                correlation_id=row["correlation_id"],
                causation_id=row["causation_id"],
                schema_version=row["schema_version"],
                replayed_from_event_id=row["replayed_from_event_id"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def create_unit_evidence(
        self,
        *,
        evidence_id: UUID,
        run_id: UUID,
        task_id: UUID,
        execution_id: UUID,
        status: str,
        command: str,
        output: str,
    ) -> UnitEvidenceRecord:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO unit_evidence (id, run_id, task_id, execution_id, status, command, output, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (str(evidence_id), str(run_id), str(task_id), str(execution_id), status, command, output, now),
        )
        self.connection.commit()
        return UnitEvidenceRecord(
            id=evidence_id,
            run_id=run_id,
            task_id=task_id,
            execution_id=execution_id,
            status=status,
            command=command,
            output=output,
        )

    def list_unit_evidence_for_run(self, run_id: str) -> list[UnitEvidenceRecord]:
        rows = self.connection.execute(
            """
            SELECT id, run_id, task_id, execution_id, status, command, output
            FROM unit_evidence
            WHERE run_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
        return [
            UnitEvidenceRecord(
                id=UUID(row["id"]),
                run_id=UUID(row["run_id"]),
                task_id=UUID(row["task_id"]),
                execution_id=UUID(row["execution_id"]),
                status=row["status"],
                command=row["command"],
                output=row["output"],
            )
            for row in rows
        ]

    def create_pull_request(self, *, pr_id: UUID, run_id: UUID, title: str, branch: str, status: str, url: str) -> PullRequestRecord:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO pull_requests (id, run_id, title, branch, status, url, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (str(pr_id), str(run_id), title, branch, status, url, now),
        )
        self.connection.commit()
        return PullRequestRecord(id=pr_id, run_id=run_id, title=title, branch=branch, status=status, url=url)

    def list_pull_requests_for_run(self, run_id: str) -> list[PullRequestRecord]:
        rows = self.connection.execute(
            """
            SELECT id, run_id, title, branch, status, url
            FROM pull_requests
            WHERE run_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
        return [
            PullRequestRecord(
                id=UUID(row["id"]),
                run_id=UUID(row["run_id"]),
                title=row["title"],
                branch=row["branch"],
                status=row["status"],
                url=row["url"],
            )
            for row in rows
        ]

    def create_ci_check(self, *, check_id: UUID, run_id: UUID, name: str, status: str, details: str | None) -> CiCheckRecord:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO ci_checks (id, run_id, name, status, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(check_id), str(run_id), name, status, details, now),
        )
        self.connection.commit()
        return CiCheckRecord(id=check_id, run_id=run_id, name=name, status=status, details=details)

    def list_ci_checks_for_run(self, run_id: str) -> list[CiCheckRecord]:
        rows = self.connection.execute(
            """
            SELECT id, run_id, name, status, details
            FROM ci_checks
            WHERE run_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
        return [
            CiCheckRecord(
                id=UUID(row["id"]),
                run_id=UUID(row["run_id"]),
                name=row["name"],
                status=row["status"],
                details=row["details"],
            )
            for row in rows
        ]

    def create_policy_decision(
        self,
        *,
        decision_id: UUID,
        run_id: UUID,
        task_id: UUID | None,
        decision: str,
        reason_code: str,
        rationale: str | None,
    ) -> None:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO policy_decisions (id, run_id, task_id, eval_run_id, decision, reason_code, rationale, created_at)
            VALUES (?, ?, ?, NULL, ?, ?, ?, ?)
            """,
            (str(decision_id), str(run_id), str(task_id) if task_id else None, decision, reason_code, rationale, now),
        )
        self.connection.commit()

    def list_policy_decisions_for_run(self, run_id: str) -> list[dict[str, str | None]]:
        rows = self.connection.execute(
            """
            SELECT id, run_id, task_id, decision, reason_code, rationale, created_at
            FROM policy_decisions
            WHERE run_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "task_id": row["task_id"],
                "decision": row["decision"],
                "reason_code": row["reason_code"],
                "rationale": row["rationale"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def transaction(self, fn):
        try:
            self.connection.execute("BEGIN")
            result = fn()
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise

    def claim_task(self, *, task_id: UUID, worker_id: str) -> TaskRecord | None:
        now = utc_now()
        cursor = self.connection.execute(
            """
            UPDATE tasks
            SET claimed_by = ?, claimed_at = ?, lock_version = lock_version + 1
            WHERE id = ? AND (claimed_by IS NULL OR claimed_by = ?)
            """,
            (worker_id, now, str(task_id), worker_id),
        )
        self.connection.commit()
        if cursor.rowcount == 0:
            return None
        return self.get_task(str(task_id))

    def release_task_claim(self, *, task_id: UUID) -> TaskRecord | None:
        self.connection.execute(
            "UPDATE tasks SET claimed_by = NULL, claimed_at = NULL WHERE id = ?",
            (str(task_id),),
        )
        self.connection.commit()
        return self.get_task(str(task_id))

    def update_execution_status(
        self,
        *,
        execution_id: UUID,
        status: str,
        phase: str,
        finished: bool = False,
    ) -> None:
        now = utc_now()
        self.connection.execute(
            """
            UPDATE executions
            SET status = ?, phase = ?, finished_at = CASE WHEN ? THEN ? ELSE finished_at END
            WHERE id = ?
            """,
            (status, phase, int(finished), now, str(execution_id)),
        )
        self.connection.commit()

    def create_outbox_event(self, event: WorkflowEvent) -> OutboxEventRecord:
        outbox_id = UUID(event.event_id)
        created_at = event.created_at.isoformat()
        self.connection.execute(
            """
            INSERT OR IGNORE INTO outbox_events (id, event_id, topic, payload_json, published_at, created_at)
            VALUES (?, ?, ?, ?, NULL, ?)
            """,
            (str(outbox_id), event.event_id, event.event_type, dumps(event.payload, sort_keys=True), created_at),
        )
        self.connection.commit()
        return OutboxEventRecord(
            id=outbox_id,
            event_id=event.event_id,
            topic=event.event_type,
            payload=event.payload,
            published_at=None,
            created_at=created_at,
        )

    def list_outbox_events(self, *, include_published: bool = True) -> list[OutboxEventRecord]:
        query = "SELECT id, event_id, topic, payload_json, published_at, created_at FROM outbox_events"
        if not include_published:
            query += " WHERE published_at IS NULL"
        query += " ORDER BY created_at ASC, id ASC"
        rows = self.connection.execute(query).fetchall()
        return [
            OutboxEventRecord(
                id=UUID(row["id"]),
                event_id=row["event_id"],
                topic=row["topic"],
                payload=loads(row["payload_json"]),
                published_at=row["published_at"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def mark_outbox_published(self, outbox_id: UUID) -> None:
        self.connection.execute(
            "UPDATE outbox_events SET published_at = ? WHERE id = ?",
            (utc_now(), str(outbox_id)),
        )
        self.connection.commit()

    def invalidate_approvals(self, *, run_id: UUID, scope: str, reason: str, task_id: UUID | None = None) -> None:
        if scope == "task" and task_id is not None:
            self.connection.execute(
                """
                UPDATE approvals
                SET status = 'invalidated', invalidated_at = ?, invalidation_reason = ?
                WHERE run_id = ? AND scope = ? AND task_id = ? AND status = 'approved'
                """,
                (utc_now(), reason, str(run_id), scope, str(task_id)),
            )
        else:
            self.connection.execute(
                """
                UPDATE approvals
                SET status = 'invalidated', invalidated_at = ?, invalidation_reason = ?
                WHERE run_id = ? AND scope = ? AND status = 'approved'
                """,
                (utc_now(), reason, str(run_id), scope),
            )
        self.connection.commit()
