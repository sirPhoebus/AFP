"""Service layer for workflow orchestration behavior."""

from __future__ import annotations

from hashlib import sha256
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from execution import run_container_command
from persistence.repository import PostgresRepository, SQLiteRepository
from planning import PlannedTaskSpec, render_plan_document
from workflow_engine import InMemoryQueue, LifecycleState, QueueEnvelope, RedisQueue, apply_transition
from workflow_engine.events import WorkflowEvent
from workflow_engine.worker import drain_worker_once

from .models import Task
from .serializers import to_artefact, to_task

Repository = SQLiteRepository | PostgresRepository
Queue = InMemoryQueue | RedisQueue

RUN_STATE_BLOCKERS: tuple[LifecycleState, ...] = (
    LifecycleState.BLOCKED,
    LifecycleState.NEEDS_HUMAN,
    LifecycleState.FAILED,
    LifecycleState.IN_PROGRESS,
    LifecycleState.AWAITING_APPROVAL,
)
RUN_STATE_PROGRESS_ORDER: tuple[LifecycleState, ...] = (
    LifecycleState.READY,
    LifecycleState.UNIT_PASS,
    LifecycleState.PR_OPEN,
    LifecycleState.INTEGRATION_PASS,
    LifecycleState.MERGED,
)
COMPLETED_DEPENDENCY_STATES = {
    LifecycleState.UNIT_PASS,
    LifecycleState.PR_OPEN,
    LifecycleState.INTEGRATION_PASS,
    LifecycleState.MERGED,
}


class WorkflowService:
    def __init__(self, repository: Repository, queue: Queue, events: list[WorkflowEvent]) -> None:
        self.repository = repository
        self.queue = queue
        self.events = events
        self.metrics: dict[str, int] = {
            "runs_created_total": 0,
            "tasks_created_total": 0,
            "worker_dequeues_total": 0,
            "worker_duplicates_total": 0,
            "execution_started_total": 0,
            "execution_completed_total": 0,
            "execution_failed_total": 0,
            "approvals_invalidated_total": 0,
            "agent_invocations_total": 0,
        }

    def recover_ready_tasks(self) -> None:
        for task_record in self.repository.list_tasks_by_state(LifecycleState.READY):
            self.queue.enqueue(
                QueueEnvelope(
                    run_id=task_record.run_id,
                    task_id=task_record.id,
                    attempt=task_record.retry_count + 1,
                    max_retries=task_record.max_retries,
                )
            )

    def list_runs(self) -> list[dict[str, object]]:
        if hasattr(self.repository.connection, "execute"):
            rows = self.repository.connection.execute(
                "SELECT id, title, state, seeded_bootstrap_task FROM runs ORDER BY created_at ASC, id ASC"
            ).fetchall()
        else:
            with self.repository.connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, title, state, seeded_bootstrap_task FROM runs ORDER BY created_at ASC, id ASC"
                )
                rows = cursor.fetchall()
        return [
            {
                "id": str(row["id"]),
                "title": row["title"],
                "state": row["state"],
                "seeded_bootstrap_task": bool(row["seeded_bootstrap_task"]),
            }
            for row in rows
        ]

    def enqueue_task(self, task: Task) -> QueueEnvelope:
        envelope = QueueEnvelope(
            run_id=task.run_id,
            task_id=task.id,
            attempt=task.retry_count + 1,
            max_retries=task.max_retries,
        )
        self.queue.enqueue(envelope)
        return envelope

    def task_dependencies_satisfied(self, task_id: UUID) -> bool:
        dependencies = self.repository.list_dependencies_for_task(str(task_id))
        if not dependencies:
            return True
        for dependency in dependencies:
            dependency_task = self.repository.get_task(str(dependency.depends_on_task_id))
            if dependency_task is None or dependency_task.state not in COMPLETED_DEPENDENCY_STATES:
                return False
        return True

    def derive_run_state(self, run_id: UUID) -> LifecycleState:
        task_records = self.repository.list_tasks_for_run(str(run_id))
        if not task_records:
            run_record = self.repository.get_run(str(run_id))
            return LifecycleState.NEW if run_record is None else run_record.state

        task_states = {task.state for task in task_records}
        if task_states == {LifecycleState.CANCELLED}:
            return LifecycleState.CANCELLED
        for candidate in RUN_STATE_BLOCKERS:
            if candidate in task_states:
                return candidate
        for candidate in RUN_STATE_PROGRESS_ORDER:
            if candidate in task_states:
                return candidate
        return LifecycleState.NEW

    def sync_run_state(self, run_id: UUID, target_state: LifecycleState | None = None) -> None:
        run_record = self.repository.get_run(str(run_id))
        if run_record is None:
            return
        desired_state = self.derive_run_state(run_id) if target_state is None else target_state
        if run_record.state == desired_state:
            return
        transition = apply_transition(run_record.state, desired_state)
        if transition.valid:
            self.repository.update_run_state(run_id=run_id, state=desired_state)

    def resolve_optional_task_for_run(self, run_id: str, task_id: str | None):
        if task_id is None:
            return None, None
        try:
            parsed_task_id = UUID(task_id)
        except ValueError:
            return None, "invalid_task_id"
        task_record = self.repository.get_task(str(parsed_task_id))
        if task_record is None or str(task_record.run_id) != run_id:
            return None, "invalid_task_reference"
        return parsed_task_id, None

    def create_task(
        self,
        run_id: UUID,
        name: str,
        max_retries: int,
        *,
        require_approval: bool = False,
        requested_by: str = "system",
        depends_on_task_ids: list[UUID] | None = None,
    ) -> Task:
        depends_on_task_ids = depends_on_task_ids or []
        initial_state = (
            LifecycleState.AWAITING_APPROVAL
            if require_approval
            else (LifecycleState.BLOCKED if depends_on_task_ids else LifecycleState.READY)
        )
        record = self.repository.create_task(
            task_id=uuid4(),
            run_id=run_id,
            name=name,
            state=initial_state,
            max_retries=max_retries,
        )
        task = to_task(record)
        for dependency_task_id in depends_on_task_ids:
            self.repository.create_task_dependency(task_id=task.id, depends_on_task_id=dependency_task_id)
        if require_approval:
            self.repository.create_approval(
                approval_id=uuid4(),
                run_id=run_id,
                task_id=task.id,
                status="pending",
                requested_by=requested_by,
                decided_by=None,
                decision_note="task_requires_approval",
            )
        elif not depends_on_task_ids:
            self.enqueue_task(task)
        self.metrics["tasks_created_total"] += 1
        self.sync_run_state(run_id)
        return task

    def promote_dependents_if_ready(self, task_id: UUID) -> None:
        for dependent in self.repository.list_dependents_for_task(str(task_id)):
            dependent_task = self.repository.get_task(str(dependent.task_id))
            if dependent_task is None or dependent_task.state != LifecycleState.BLOCKED:
                continue
            if not self.task_dependencies_satisfied(dependent.task_id):
                continue
            updated = self.repository.update_task_state(task_id=dependent.task_id, state=LifecycleState.READY)
            if updated is None:
                continue
            self.enqueue_task(to_task(updated))
            self.sync_run_state(updated.run_id)

    def create_plan(self, run_id: str, title: str, raw_tasks: list[dict]) -> dict[str, object]:
        if not raw_tasks:
            raise ValueError("tasks_required")

        specs: list[PlannedTaskSpec] = []
        task_names = {item["name"] for item in raw_tasks}
        for item in raw_tasks:
            dependencies = tuple(item.get("depends_on", []))
            unknown_dependencies = [name for name in dependencies if name not in task_names]
            if unknown_dependencies:
                raise KeyError(",".join(unknown_dependencies))
            specs.append(
                PlannedTaskSpec(
                    name=item["name"],
                    depends_on=dependencies,
                    require_approval=bool(item.get("require_approval", False)),
                    requested_by=item.get("requested_by", "planner"),
                    max_retries=int(item.get("max_retries", 3)),
                )
            )

        created_tasks: dict[str, Task] = {}
        parsed_run_id = UUID(run_id)
        for spec in specs:
            dependency_ids = [created_tasks[name].id for name in spec.depends_on]
            created_tasks[spec.name] = self.create_task(
                parsed_run_id,
                spec.name,
                spec.max_retries,
                require_approval=spec.require_approval,
                requested_by=spec.requested_by,
                depends_on_task_ids=dependency_ids,
            )

        plan_document = render_plan_document(run_id, title, specs)
        plan_artefact = self.repository.create_artefact(
            artefact_id=uuid4(),
            run_id=parsed_run_id,
            task_id=None,
            path=f"plans/{run_id}.md",
            checksum=sha256(plan_document.encode("utf-8")).hexdigest(),
            version="v1",
            producer="planner",
        )

        dag = {
            "run_id": run_id,
            "nodes": [{"id": str(task.id), "name": task.name, "state": task.state.value} for task in created_tasks.values()],
            "edges": [
                {"task_id": str(created_tasks[spec.name].id), "depends_on_task_id": str(created_tasks[dependency].id)}
                for spec in specs
                for dependency in spec.depends_on
            ],
        }
        return {
            "dag": dag,
            "tasks": list(created_tasks.values()),
            "artefact": to_artefact(plan_artefact),
            "document": plan_document,
        }

    def approval_threshold_met(self, run_id: str, task_id: str | None, scope: str) -> bool:
        approvals = self.repository.list_approvals_for_run(run_id)
        relevant = [
            approval
            for approval in approvals
            if approval.scope == scope and (
                (scope == "run" and approval.task_id is None) or (scope == "task" and str(approval.task_id) == task_id)
            )
        ]
        if not relevant:
            return True
        required = max(approval.required_approvals for approval in relevant)
        approved = sum(1 for approval in relevant if approval.status == "approved")
        return approved >= required

    def dequeue_task_once(self, *, worker_id: str = "worker-1") -> dict[str, object]:
        event = drain_worker_once(self.queue, self.events.append)
        if event is None:
            return {"status": "idle"}
        claimed_task = self.repository.claim_task(task_id=event.task_id, worker_id=worker_id)
        if claimed_task is None:
            return {"status": "lost"}
        existing_event = None
        if event.idempotency_key is not None:
            existing_event = self.repository.get_workflow_event_by_idempotency_key(event.idempotency_key)
        if existing_event is not None:
            self.metrics["worker_duplicates_total"] += 1
            return {
                "status": "duplicate",
                "event": {
                    "event_id": existing_event.event_id,
                    "event_type": existing_event.event_type,
                    "run_id": str(existing_event.run_id) if existing_event.run_id is not None else None,
                    "task_id": str(existing_event.task_id) if existing_event.task_id is not None else None,
                    "payload": existing_event.payload,
                    "idempotency_key": existing_event.idempotency_key,
                    "correlation_id": existing_event.correlation_id,
                    "causation_id": existing_event.causation_id,
                    "created_at": existing_event.created_at,
                },
            }
        correlation_id = f"{event.run_id}:{event.task_id}:{event.payload['attempt']}"
        event = WorkflowEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            run_id=event.run_id,
            task_id=event.task_id,
            payload=event.payload,
            idempotency_key=event.idempotency_key,
            correlation_id=correlation_id,
            created_at=event.created_at,
        )
        self.repository.create_workflow_event(event)
        self.repository.update_task_state(
            task_id=event.task_id,
            state=LifecycleState.IN_PROGRESS,
            retry_count=event.payload["attempt"],
        )
        self.sync_run_state(event.run_id)
        execution = self.repository.create_execution(
            execution_id=uuid4(),
            run_id=event.run_id,
            task_id=event.task_id,
            status="dequeued",
            runner_kind="worker",
            attempt=event.payload["attempt"],
            phase="dequeued",
            correlation_id=correlation_id,
        )
        self.repository.create_log(
            log_id=uuid4(),
            run_id=event.run_id,
            task_id=event.task_id,
            execution_id=execution.id,
            level="info",
            message=event.event_type,
        )
        self.metrics["worker_dequeues_total"] += 1
        return {"status": "processed", "event": event, "execution": execution}

    def start_execution(self, *, execution_id: UUID, run_id: UUID, task_id: UUID, correlation_id: str | None = None) -> WorkflowEvent:
        event = WorkflowEvent(
            event_type="task.execution.started",
            run_id=run_id,
            task_id=task_id,
            correlation_id=correlation_id,
        )
        self.repository.create_workflow_event(event)
        self.repository.update_execution_status(execution_id=execution_id, status="started", phase="started")
        self.metrics["execution_started_total"] += 1
        return event

    def complete_execution(
        self,
        *,
        execution_id: UUID,
        run_id: UUID,
        task_id: UUID,
        success: bool,
        retryable: bool = False,
    ) -> WorkflowEvent:
        if success:
            event_type = "task.execution.succeeded"
            status = "succeeded"
            phase = "completed"
        elif retryable:
            event_type = "task.execution.retried"
            status = "retried"
            phase = "retry_wait"
        else:
            event_type = "task.execution.failed"
            status = "failed"
            phase = "completed"
        event = WorkflowEvent(event_type=event_type, run_id=run_id, task_id=task_id)
        self.repository.create_workflow_event(event)
        self.repository.update_execution_status(execution_id=execution_id, status=status, phase=phase, finished=True)
        self.repository.release_task_claim(task_id=task_id)
        if success:
            self.promote_dependents_if_ready(task_id)
            self.metrics["execution_completed_total"] += 1
        else:
            self.metrics["execution_failed_total"] += 1
        return event

    def cancel_task(self, *, run_id: UUID, task_id: UUID) -> WorkflowEvent:
        self.repository.update_task_state(task_id=task_id, state=LifecycleState.CANCELLED)
        self.repository.release_task_claim(task_id=task_id)
        event = WorkflowEvent(event_type="task.execution.cancelled", run_id=run_id, task_id=task_id)
        self.repository.create_workflow_event(event)
        self.sync_run_state(run_id)
        return event

    def worker_drain_once(self) -> dict[str, object]:
        dequeued = self.dequeue_task_once()
        if dequeued["status"] != "processed":
            return dequeued
        return {"status": "processed", "event": dequeued["event"]}

    def evaluate_merge_policy(self, run_id: str) -> tuple[str, str, str]:
        approvals = self.repository.list_approvals_for_run(run_id)
        unit_evidence = self.repository.list_unit_evidence_for_run(run_id)
        ci_checks = self.repository.list_ci_checks_for_run(run_id)
        pull_requests = self.repository.list_pull_requests_for_run(run_id)

        if not pull_requests:
            return ("blocked", "missing_pull_request", "No pull request is registered.")
        if any(approval.scope == "run" and approval.status != "approved" for approval in approvals):
            return ("blocked", "run_approvals_incomplete", "Run-level approvals are incomplete.")
        if any(approval.status != "approved" for approval in approvals if approval.task_id is not None):
            return ("blocked", "approvals_incomplete", "Not all task approvals are approved.")
        if not unit_evidence or any(item.status != "passed" for item in unit_evidence):
            return ("blocked", "unit_evidence_incomplete", "Unit evidence is missing or failed.")
        if not ci_checks or any(item.status != "passed" for item in ci_checks):
            return ("blocked", "ci_checks_incomplete", "CI checks are missing or failing.")
        return ("allowed", "merge_ready", "Approvals, unit evidence, CI checks, and PR state are satisfied.")

    def execute_task_unit(self, run_id: UUID, task_record, image: str, command: list[str], mount_repo: bool) -> tuple[object, object]:
        result = run_container_command(image, command, workdir=mount_repo and "/home/phoebus/repo/AFP" or None)
        correlation_id = f"{run_id}:{task_record.id}:container:{task_record.retry_count + 1}"
        execution = self.repository.create_execution(
            execution_id=uuid4(),
            run_id=run_id,
            task_id=task_record.id,
            status="started",
            runner_kind="container",
            attempt=task_record.retry_count + 1,
            phase="started",
            correlation_id=correlation_id,
        )
        self.start_execution(
            execution_id=execution.id,
            run_id=run_id,
            task_id=task_record.id,
            correlation_id=correlation_id,
        )
        evidence = self.repository.create_unit_evidence(
            evidence_id=uuid4(),
            run_id=run_id,
            task_id=task_record.id,
            execution_id=execution.id,
            status="passed" if result.exit_code == 0 else "failed",
            command=" ".join(command),
            output=result.output,
        )
        target_state = LifecycleState.UNIT_PASS if result.exit_code == 0 else LifecycleState.FAILED
        self.repository.update_task_state(
            task_id=task_record.id,
            state=target_state,
            retry_count=task_record.retry_count + 1,
        )
        self.complete_execution(
            execution_id=execution.id,
            run_id=run_id,
            task_id=task_record.id,
            success=result.exit_code == 0,
            retryable=result.exit_code != 0 and (task_record.retry_count + 1) < task_record.max_retries,
        )
        self.sync_run_state(run_id)
        return execution, evidence

    def schedule_retry(self, *, task_id: UUID, delay_seconds: int) -> Task:
        next_attempt_at = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat()
        if hasattr(self.repository.connection, "execute"):
            self.repository.connection.execute(
                "UPDATE tasks SET next_attempt_at = ?, state = ?, updated_at = ? WHERE id = ?",
                (next_attempt_at, LifecycleState.READY.value, datetime.now(timezone.utc).isoformat(), str(task_id)),
            )
            self.repository.connection.commit()
        else:
            with self.repository.connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE tasks SET next_attempt_at = %s, state = %s, updated_at = %s WHERE id = %s",
                    (next_attempt_at, LifecycleState.READY.value, datetime.now(timezone.utc).isoformat(), str(task_id)),
                )
            self.repository.connection.commit()
        updated = self.repository.get_task(str(task_id))
        assert updated is not None
        self.enqueue_task(to_task(updated))
        return to_task(updated)
