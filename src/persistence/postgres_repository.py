"""Postgres-backed persistence backend."""

from __future__ import annotations

from collections.abc import Iterable
from json import dumps, loads
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

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
from .schema import CORE_SCHEMA_STATEMENTS


class PostgresRepository:
    """Postgres-backed repository mirroring the SQLite repository contract."""

    def __init__(self, dsn: str) -> None:
        self.connection = psycopg.connect(dsn, row_factory=dict_row)
        with self.connection.cursor() as cursor:
            for statement in CORE_SCHEMA_STATEMENTS:
                cursor.execute(statement)
        self.connection.commit()

    def reset_tables(self, table_names: Iterable[str]) -> None:
        with self.connection.cursor() as cursor:
            for table_name in table_names:
                cursor.execute(f"TRUNCATE TABLE {table_name} CASCADE")
        self.connection.commit()

    def create_run(self, *, run_id: UUID, title: str, state: LifecycleState, seeded_bootstrap_task: bool) -> RunRecord:
        now = utc_now()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO runs (id, title, state, seeded_bootstrap_task, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (str(run_id), title, state.value, int(seeded_bootstrap_task), now, now),
            )
        self.connection.commit()
        return self.get_run(str(run_id))

    def get_run(self, run_id: str) -> RunRecord | None:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id, title, state, seeded_bootstrap_task FROM runs WHERE id = %s", (run_id,))
            row = cursor.fetchone()
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
        with self.connection.cursor() as cursor:
            cursor.execute(
                "UPDATE runs SET state = %s, updated_at = %s WHERE id = %s",
                (state.value, now, str(run_id)),
            )
        self.connection.commit()
        return self.get_run(str(run_id))

    def create_task(self, *, task_id: UUID, run_id: UUID, name: str, state: LifecycleState, max_retries: int) -> TaskRecord:
        now = utc_now()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tasks (id, run_id, name, state, retry_count, max_retries, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 0, %s, %s, %s)
                """,
                (str(task_id), str(run_id), name, state.value, max_retries, now, now),
            )
        self.connection.commit()
        return self.get_task(str(task_id))

    def create_task_dependency(self, *, task_id: UUID, depends_on_task_id: UUID) -> TaskDependencyRecord:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO task_dependencies (task_id, depends_on_task_id) VALUES (%s, %s)",
                (str(task_id), str(depends_on_task_id)),
            )
        self.connection.commit()
        return TaskDependencyRecord(task_id=task_id, depends_on_task_id=depends_on_task_id)

    def list_dependencies_for_task(self, task_id: str) -> list[TaskDependencyRecord]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT task_id, depends_on_task_id FROM task_dependencies WHERE task_id = %s ORDER BY depends_on_task_id ASC",
                (task_id,),
            )
            rows = cursor.fetchall()
        return [
            TaskDependencyRecord(task_id=UUID(row["task_id"]), depends_on_task_id=UUID(row["depends_on_task_id"]))
            for row in rows
        ]

    def list_dependents_for_task(self, task_id: str) -> list[TaskDependencyRecord]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT task_id, depends_on_task_id FROM task_dependencies WHERE depends_on_task_id = %s ORDER BY task_id ASC",
                (task_id,),
            )
            rows = cursor.fetchall()
        return [
            TaskDependencyRecord(task_id=UUID(row["task_id"]), depends_on_task_id=UUID(row["depends_on_task_id"]))
            for row in rows
        ]

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, run_id, name, state, retry_count, max_retries FROM tasks WHERE id = %s",
                (task_id,),
            )
            row = cursor.fetchone()
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

    def update_task_state(self, *, task_id: UUID, state: LifecycleState, retry_count: int | None = None) -> TaskRecord | None:
        now = utc_now()
        with self.connection.cursor() as cursor:
            if retry_count is None:
                cursor.execute(
                    "UPDATE tasks SET state = %s, updated_at = %s WHERE id = %s",
                    (state.value, now, str(task_id)),
                )
            else:
                cursor.execute(
                    "UPDATE tasks SET state = %s, retry_count = %s, updated_at = %s WHERE id = %s",
                    (state.value, retry_count, now, str(task_id)),
                )
        self.connection.commit()
        return self.get_task(str(task_id))

    def list_tasks_for_run(self, run_id: str) -> list[TaskRecord]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, run_id, name, state, retry_count, max_retries
                FROM tasks WHERE run_id = %s ORDER BY created_at ASC, id ASC
                """,
                (run_id,),
            )
            rows = cursor.fetchall()
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
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, run_id, name, state, retry_count, max_retries
                FROM tasks WHERE state = %s ORDER BY created_at ASC, id ASC
                """,
                (state.value,),
            )
            rows = cursor.fetchall()
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
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO approvals (id, run_id, task_id, status, requested_by, decided_by, decision_note, scope, role, required_approvals, created_at, decided_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
                """,
                (str(approval_id), str(run_id), str(task_id) if task_id else None, status, requested_by, decided_by, decision_note, scope, role, required_approvals, now),
            )
        self.connection.commit()
        return self.get_approval(str(approval_id))

    def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, run_id, task_id, status, requested_by, decided_by, decision_note, scope, role, required_approvals, invalidated_at, invalidation_reason FROM approvals WHERE id = %s",
                (approval_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ApprovalRecord(
            id=UUID(row["id"]),
            run_id=UUID(row["run_id"]),
            task_id=UUID(row["task_id"]) if row["task_id"] else None,
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
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, run_id, task_id, status, requested_by, decided_by, decision_note, scope, role, required_approvals, invalidated_at, invalidation_reason FROM approvals WHERE run_id = %s ORDER BY created_at ASC, id ASC",
                (run_id,),
            )
            rows = cursor.fetchall()
        return [
            ApprovalRecord(
                id=UUID(row["id"]),
                run_id=UUID(row["run_id"]),
                task_id=UUID(row["task_id"]) if row["task_id"] else None,
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

    def update_approval(self, *, approval_id: UUID, status: str, decided_by: str | None, decision_note: str | None) -> ApprovalRecord | None:
        now = utc_now()
        with self.connection.cursor() as cursor:
            cursor.execute(
                "UPDATE approvals SET status = %s, decided_by = %s, decision_note = %s, decided_at = %s WHERE id = %s",
                (status, decided_by, decision_note, now, str(approval_id)),
            )
        self.connection.commit()
        return self.get_approval(str(approval_id))

    def list_approvals_for_task(self, task_id: str) -> list[ApprovalRecord]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, run_id, task_id, status, requested_by, decided_by, decision_note, scope, role, required_approvals, invalidated_at, invalidation_reason FROM approvals WHERE task_id = %s ORDER BY created_at ASC, id ASC",
                (task_id,),
            )
            rows = cursor.fetchall()
        return [
            ApprovalRecord(
                id=UUID(row["id"]),
                run_id=UUID(row["run_id"]),
                task_id=UUID(row["task_id"]) if row["task_id"] else None,
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

    def create_artefact(self, *, artefact_id: UUID, run_id: UUID, task_id: UUID | None, path: str, checksum: str, version: str, producer: str) -> ArtefactRecord:
        now = utc_now()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO artefacts (id, run_id, task_id, path, checksum, version, producer, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (str(artefact_id), str(run_id), str(task_id) if task_id else None, path, checksum, version, producer, now),
            )
        self.connection.commit()
        return self.get_artefact(str(artefact_id))

    def get_artefact(self, artefact_id: str) -> ArtefactRecord | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, run_id, task_id, path, checksum, version, producer FROM artefacts WHERE id = %s",
                (artefact_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ArtefactRecord(
            id=UUID(row["id"]),
            run_id=UUID(row["run_id"]),
            task_id=UUID(row["task_id"]) if row["task_id"] else None,
            path=row["path"],
            checksum=row["checksum"],
            version=row["version"],
            producer=row["producer"],
        )

    def list_artefacts_for_run(self, run_id: str, *, task_id: str | None = None) -> list[ArtefactRecord]:
        with self.connection.cursor() as cursor:
            if task_id is None:
                cursor.execute(
                    "SELECT id, run_id, task_id, path, checksum, version, producer FROM artefacts WHERE run_id = %s ORDER BY created_at ASC, id ASC",
                    (run_id,),
                )
            else:
                cursor.execute(
                    "SELECT id, run_id, task_id, path, checksum, version, producer FROM artefacts WHERE run_id = %s AND task_id = %s ORDER BY created_at ASC, id ASC",
                    (run_id, task_id),
                )
            rows = cursor.fetchall()
        return [
            ArtefactRecord(
                id=UUID(row["id"]),
                run_id=UUID(row["run_id"]),
                task_id=UUID(row["task_id"]) if row["task_id"] else None,
                path=row["path"],
                checksum=row["checksum"],
                version=row["version"],
                producer=row["producer"],
            )
            for row in rows
        ]

    def create_execution(self, *, execution_id: UUID, run_id: UUID, task_id: UUID, status: str, runner_kind: str, attempt: int, phase: str = "queued", correlation_id: str | None = None) -> ExecutionRecord:
        now = utc_now()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO executions (id, run_id, task_id, status, runner_kind, attempt, phase, correlation_id, started_at, finished_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (str(execution_id), str(run_id), str(task_id), status, runner_kind, attempt, phase, correlation_id, now, now),
            )
        self.connection.commit()
        return ExecutionRecord(id=execution_id, run_id=run_id, task_id=task_id, status=status, runner_kind=runner_kind, attempt=attempt, phase=phase, correlation_id=correlation_id, started_at=now, finished_at=now)

    def list_executions_for_run(self, run_id: str) -> list[ExecutionRecord]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, run_id, task_id, status, runner_kind, attempt FROM executions WHERE run_id = %s ORDER BY started_at ASC, id ASC",
                (run_id,),
            )
            rows = cursor.fetchall()
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

    def create_log(self, *, log_id: UUID, run_id: UUID, task_id: UUID | None, execution_id: UUID | None, level: str, message: str) -> LogRecord:
        now = utc_now()
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO logs (id, run_id, task_id, execution_id, level, message, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (str(log_id), str(run_id), str(task_id) if task_id else None, str(execution_id) if execution_id else None, level, message, now),
            )
        self.connection.commit()
        return LogRecord(id=log_id, run_id=run_id, task_id=task_id, execution_id=execution_id, level=level, message=message)

    def list_logs_for_run(self, run_id: str) -> list[LogRecord]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, run_id, task_id, execution_id, level, message FROM logs WHERE run_id = %s ORDER BY created_at ASC, id ASC",
                (run_id,),
            )
            rows = cursor.fetchall()
        return [
            LogRecord(
                id=UUID(row["id"]),
                run_id=UUID(row["run_id"]),
                task_id=UUID(row["task_id"]) if row["task_id"] else None,
                execution_id=UUID(row["execution_id"]) if row["execution_id"] else None,
                level=row["level"],
                message=row["message"],
            )
            for row in rows
        ]

    def create_workflow_event(self, event: WorkflowEvent) -> WorkflowEventRecord:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO workflow_events (event_id, event_type, run_id, task_id, payload_json, idempotency_key, correlation_id, causation_id, schema_version, replayed_from_event_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO UPDATE SET
                  event_type = EXCLUDED.event_type,
                  run_id = EXCLUDED.run_id,
                  task_id = EXCLUDED.task_id,
                  payload_json = EXCLUDED.payload_json,
                  idempotency_key = EXCLUDED.idempotency_key,
                  correlation_id = EXCLUDED.correlation_id,
                  causation_id = EXCLUDED.causation_id,
                  schema_version = EXCLUDED.schema_version,
                  replayed_from_event_id = EXCLUDED.replayed_from_event_id,
                  created_at = EXCLUDED.created_at
                """,
                (
                    event.event_id,
                    event.event_type,
                    str(event.run_id) if event.run_id else None,
                    str(event.task_id) if event.task_id else None,
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
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT event_id, event_type, run_id, task_id, payload_json, idempotency_key, correlation_id, causation_id, schema_version, replayed_from_event_id, created_at
                FROM workflow_events WHERE idempotency_key = %s ORDER BY created_at ASC, event_id ASC LIMIT 1
                """,
                (idempotency_key,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return WorkflowEventRecord(
            event_id=row["event_id"],
            event_type=row["event_type"],
            run_id=UUID(row["run_id"]) if row["run_id"] else None,
            task_id=UUID(row["task_id"]) if row["task_id"] else None,
            payload=loads(row["payload_json"]),
            idempotency_key=row["idempotency_key"],
            correlation_id=row["correlation_id"],
            causation_id=row["causation_id"],
            schema_version=row["schema_version"],
            replayed_from_event_id=row["replayed_from_event_id"],
            created_at=row["created_at"],
        )

    def list_workflow_events(self, *, run_id: str | None = None) -> list[WorkflowEventRecord]:
        with self.connection.cursor() as cursor:
            if run_id is None:
                cursor.execute(
                    "SELECT event_id, event_type, run_id, task_id, payload_json, idempotency_key, correlation_id, causation_id, schema_version, replayed_from_event_id, created_at FROM workflow_events ORDER BY created_at ASC, event_id ASC"
                )
            else:
                cursor.execute(
                    "SELECT event_id, event_type, run_id, task_id, payload_json, idempotency_key, correlation_id, causation_id, schema_version, replayed_from_event_id, created_at FROM workflow_events WHERE run_id = %s ORDER BY created_at ASC, event_id ASC",
                    (run_id,),
                )
            rows = cursor.fetchall()
        return [
            WorkflowEventRecord(
                event_id=row["event_id"],
                event_type=row["event_type"],
                run_id=UUID(row["run_id"]) if row["run_id"] else None,
                task_id=UUID(row["task_id"]) if row["task_id"] else None,
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

    def create_unit_evidence(self, *, evidence_id: UUID, run_id: UUID, task_id: UUID, execution_id: UUID, status: str, command: str, output: str) -> UnitEvidenceRecord:
        now = utc_now()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO unit_evidence (id, run_id, task_id, execution_id, status, command, output, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (str(evidence_id), str(run_id), str(task_id), str(execution_id), status, command, output, now),
            )
        self.connection.commit()
        return UnitEvidenceRecord(id=evidence_id, run_id=run_id, task_id=task_id, execution_id=execution_id, status=status, command=command, output=output)

    def list_unit_evidence_for_run(self, run_id: str) -> list[UnitEvidenceRecord]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, run_id, task_id, execution_id, status, command, output FROM unit_evidence WHERE run_id = %s ORDER BY created_at ASC, id ASC",
                (run_id,),
            )
            rows = cursor.fetchall()
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
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO pull_requests (id, run_id, title, branch, status, url, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (str(pr_id), str(run_id), title, branch, status, url, now),
            )
        self.connection.commit()
        return PullRequestRecord(id=pr_id, run_id=run_id, title=title, branch=branch, status=status, url=url)

    def list_pull_requests_for_run(self, run_id: str) -> list[PullRequestRecord]:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id, run_id, title, branch, status, url FROM pull_requests WHERE run_id = %s ORDER BY created_at ASC, id ASC", (run_id,))
            rows = cursor.fetchall()
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
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO ci_checks (id, run_id, name, status, details, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (str(check_id), str(run_id), name, status, details, now),
            )
        self.connection.commit()
        return CiCheckRecord(id=check_id, run_id=run_id, name=name, status=status, details=details)

    def list_ci_checks_for_run(self, run_id: str) -> list[CiCheckRecord]:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id, run_id, name, status, details FROM ci_checks WHERE run_id = %s ORDER BY created_at ASC, id ASC", (run_id,))
            rows = cursor.fetchall()
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
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO policy_decisions (id, run_id, task_id, eval_run_id, decision, reason_code, rationale, created_at)
                VALUES (%s, %s, %s, NULL, %s, %s, %s, %s)
                """,
                (str(decision_id), str(run_id), str(task_id) if task_id else None, decision, reason_code, rationale, now),
            )
        self.connection.commit()

    def list_policy_decisions_for_run(self, run_id: str) -> list[dict[str, str | None]]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, run_id, task_id, decision, reason_code, rationale, created_at FROM policy_decisions WHERE run_id = %s ORDER BY created_at ASC, id ASC",
                (run_id,),
            )
            rows = cursor.fetchall()
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
            with self.connection.transaction():
                return fn()
        except Exception:
            raise

    def claim_task(self, *, task_id: UUID, worker_id: str) -> TaskRecord | None:
        now = utc_now()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE tasks
                SET claimed_by = %s, claimed_at = %s, lock_version = lock_version + 1
                WHERE id = %s AND (claimed_by IS NULL OR claimed_by = %s)
                """,
                (worker_id, now, str(task_id), worker_id),
            )
            updated_rows = cursor.rowcount
        self.connection.commit()
        if updated_rows == 0:
            return None
        return self.get_task(str(task_id))

    def release_task_claim(self, *, task_id: UUID) -> TaskRecord | None:
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE tasks SET claimed_by = NULL, claimed_at = NULL WHERE id = %s", (str(task_id),))
        self.connection.commit()
        return self.get_task(str(task_id))

    def update_execution_status(self, *, execution_id: UUID, status: str, phase: str, finished: bool = False) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE executions
                SET status = %s, phase = %s, finished_at = CASE WHEN %s THEN %s ELSE finished_at END
                WHERE id = %s
                """,
                (status, phase, finished, utc_now(), str(execution_id)),
            )
        self.connection.commit()

    def create_outbox_event(self, event: WorkflowEvent) -> OutboxEventRecord:
        outbox_id = UUID(event.event_id)
        created_at = event.created_at.isoformat()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO outbox_events (id, event_id, topic, payload_json, published_at, created_at)
                VALUES (%s, %s, %s, %s, NULL, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (str(outbox_id), event.event_id, event.event_type, dumps(event.payload, sort_keys=True), created_at),
            )
        self.connection.commit()
        return OutboxEventRecord(id=outbox_id, event_id=event.event_id, topic=event.event_type, payload=event.payload, published_at=None, created_at=created_at)

    def list_outbox_events(self, *, include_published: bool = True) -> list[OutboxEventRecord]:
        with self.connection.cursor() as cursor:
            if include_published:
                cursor.execute("SELECT id, event_id, topic, payload_json, published_at, created_at FROM outbox_events ORDER BY created_at ASC, id ASC")
            else:
                cursor.execute("SELECT id, event_id, topic, payload_json, published_at, created_at FROM outbox_events WHERE published_at IS NULL ORDER BY created_at ASC, id ASC")
            rows = cursor.fetchall()
        return [
            OutboxEventRecord(id=UUID(row["id"]), event_id=row["event_id"], topic=row["topic"], payload=loads(row["payload_json"]), published_at=row["published_at"], created_at=row["created_at"])
            for row in rows
        ]

    def mark_outbox_published(self, outbox_id: UUID) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE outbox_events SET published_at = %s WHERE id = %s", (utc_now(), str(outbox_id)))
        self.connection.commit()

    def invalidate_approvals(self, *, run_id: UUID, scope: str, reason: str, task_id: UUID | None = None) -> None:
        with self.connection.cursor() as cursor:
            if scope == "task" and task_id is not None:
                cursor.execute(
                    """
                    UPDATE approvals
                    SET status = 'invalidated', invalidated_at = %s, invalidation_reason = %s
                    WHERE run_id = %s AND scope = %s AND task_id = %s AND status = 'approved'
                    """,
                    (utc_now(), reason, str(run_id), scope, str(task_id)),
                )
            else:
                cursor.execute(
                    """
                    UPDATE approvals
                    SET status = 'invalidated', invalidated_at = %s, invalidation_reason = %s
                    WHERE run_id = %s AND scope = %s AND status = 'approved'
                    """,
                    (utc_now(), reason, str(run_id), scope),
                )
        self.connection.commit()
