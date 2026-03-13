"""Minimal API scaffold for Milestone A bootstrap work."""

from dataclasses import asdict, dataclass
from uuid import UUID, uuid4

from flask import Flask, jsonify, request

from persistence import SQLiteRepository, TableResetView
from workflow_engine import LifecycleState, QueueEnvelope, apply_transition
from workflow_engine.events import WorkflowEvent
from workflow_engine.worker import InMemoryQueue, drain_worker_once


@dataclass
class Run:
    id: UUID
    title: str
    state: LifecycleState
    seeded_bootstrap_task: bool = False


@dataclass
class Task:
    id: UUID
    run_id: UUID
    name: str
    state: LifecycleState
    retry_count: int = 0
    max_retries: int = 3


@dataclass
class Approval:
    id: UUID
    run_id: UUID
    task_id: UUID | None
    status: str
    requested_by: str
    decided_by: str | None = None
    decision_note: str | None = None


@dataclass
class Artefact:
    id: UUID
    run_id: UUID
    task_id: UUID | None
    path: str
    checksum: str
    version: str
    producer: str


@dataclass
class AppRuntime:
    app: Flask
    repository: SQLiteRepository
    queue: InMemoryQueue
    events: list[WorkflowEvent]
    runs: TableResetView
    tasks: TableResetView
    approvals: TableResetView
    artefacts: TableResetView
    logs: TableResetView
    executions: TableResetView


def _serialize_run(run: Run) -> dict[str, str | bool]:
    payload = asdict(run)
    payload["id"] = str(run.id)
    payload["state"] = run.state.value
    return payload


def _serialize_task(task: Task) -> dict[str, str | int]:
    payload = asdict(task)
    payload["id"] = str(task.id)
    payload["run_id"] = str(task.run_id)
    payload["state"] = task.state.value
    return payload


def _serialize_event(event: WorkflowEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "run_id": str(event.run_id) if event.run_id is not None else None,
        "task_id": str(event.task_id) if event.task_id is not None else None,
        "payload": event.payload,
        "idempotency_key": event.idempotency_key,
        "created_at": event.created_at.isoformat(),
    }


def _serialize_execution(record) -> dict[str, object]:
    return {
        "id": str(record.id),
        "run_id": str(record.run_id),
        "task_id": str(record.task_id),
        "status": record.status,
        "runner_kind": record.runner_kind,
        "attempt": record.attempt,
    }


def _serialize_log(record) -> dict[str, object]:
    return {
        "id": str(record.id),
        "run_id": str(record.run_id),
        "task_id": str(record.task_id) if record.task_id is not None else None,
        "execution_id": str(record.execution_id) if record.execution_id is not None else None,
        "level": record.level,
        "message": record.message,
    }


def _serialize_approval(approval: Approval) -> dict[str, str | None]:
    payload = asdict(approval)
    payload["id"] = str(approval.id)
    payload["run_id"] = str(approval.run_id)
    payload["task_id"] = str(approval.task_id) if approval.task_id is not None else None
    return payload


def _serialize_artefact(artefact: Artefact) -> dict[str, str | None]:
    payload = asdict(artefact)
    payload["id"] = str(artefact.id)
    payload["run_id"] = str(artefact.run_id)
    payload["task_id"] = str(artefact.task_id) if artefact.task_id is not None else None
    return payload


def _to_run(record) -> Run:
    return Run(
        id=record.id,
        title=record.title,
        state=record.state,
        seeded_bootstrap_task=record.seeded_bootstrap_task,
    )


def _to_task(record) -> Task:
    return Task(
        id=record.id,
        run_id=record.run_id,
        name=record.name,
        state=record.state,
        retry_count=record.retry_count,
        max_retries=record.max_retries,
    )


def _to_approval(record) -> Approval:
    return Approval(
        id=record.id,
        run_id=record.run_id,
        task_id=record.task_id,
        status=record.status,
        requested_by=record.requested_by,
        decided_by=record.decided_by,
        decision_note=record.decision_note,
    )


def _to_artefact(record) -> Artefact:
    return Artefact(
        id=record.id,
        run_id=record.run_id,
        task_id=record.task_id,
        path=record.path,
        checksum=record.checksum,
        version=record.version,
        producer=record.producer,
    )


def _recover_ready_tasks(repository: SQLiteRepository, queue: InMemoryQueue) -> None:
    for task_record in repository.list_tasks_by_state(LifecycleState.READY):
        queue.enqueue(
            QueueEnvelope(
                run_id=task_record.run_id,
                task_id=task_record.id,
                attempt=task_record.retry_count + 1,
                max_retries=task_record.max_retries,
            )
        )


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


def create_runtime(db_dsn: str = ":memory:") -> AppRuntime:
    app = Flask(__name__)
    repository = SQLiteRepository(db_dsn)
    events: list[WorkflowEvent] = []
    queue = InMemoryQueue()
    runs = TableResetView(
        repository,
        "workflow_events",
        "policy_decisions",
        "eval_runs",
        "logs",
        "executions",
        "artefacts",
        "approvals",
        "task_dependencies",
        "tasks",
        "runs",
    )
    tasks = TableResetView(
        repository,
        "workflow_events",
        "policy_decisions",
        "eval_runs",
        "logs",
        "executions",
        "artefacts",
        "approvals",
        "task_dependencies",
        "tasks",
    )
    approvals = TableResetView(repository, "approvals")
    artefacts = TableResetView(repository, "artefacts")
    logs = TableResetView(repository, "logs")
    executions = TableResetView(repository, "logs", "executions")

    _recover_ready_tasks(repository, queue)

    def _enqueue_task(task: Task) -> QueueEnvelope:
        envelope = QueueEnvelope(
            run_id=task.run_id,
            task_id=task.id,
            attempt=task.retry_count + 1,
            max_retries=task.max_retries,
        )
        queue.enqueue(envelope)
        return envelope

    def _derive_run_state(run_id: UUID) -> LifecycleState:
        task_records = repository.list_tasks_for_run(str(run_id))
        if not task_records:
            run_record = repository.get_run(str(run_id))
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

    def _sync_run_state(run_id: UUID, target_state: LifecycleState | None = None) -> None:
        run_record = repository.get_run(str(run_id))
        if run_record is None:
            return
        desired_state = _derive_run_state(run_id) if target_state is None else target_state
        if run_record.state == desired_state:
            return
        transition = apply_transition(run_record.state, desired_state)
        if transition.valid:
            repository.update_run_state(run_id=run_id, state=desired_state)

    def _resolve_optional_task_for_run(run_id: str, task_id: str | None):
        if task_id is None:
            return None, None

        try:
            parsed_task_id = UUID(task_id)
        except ValueError:
            return None, (jsonify({"error": "invalid_task_id"}), 400)

        task_record = repository.get_task(str(parsed_task_id))
        if task_record is None or str(task_record.run_id) != run_id:
            return None, (jsonify({"error": "invalid_task_reference"}), 400)

        return parsed_task_id, None

    def _create_task(
        run_id: UUID,
        name: str,
        max_retries: int,
        *,
        require_approval: bool = False,
        requested_by: str = "system",
    ) -> Task:
        initial_state = LifecycleState.AWAITING_APPROVAL if require_approval else LifecycleState.READY
        record = repository.create_task(
            task_id=uuid4(),
            run_id=run_id,
            name=name,
            state=initial_state,
            max_retries=max_retries,
        )
        task = _to_task(record)
        if require_approval:
            repository.create_approval(
                approval_id=uuid4(),
                run_id=run_id,
                task_id=task.id,
                status="pending",
                requested_by=requested_by,
                decided_by=None,
                decision_note="task_requires_approval",
            )
            _sync_run_state(run_id)
        else:
            _enqueue_task(task)
            _sync_run_state(run_id)
        return task

    @app.get("/health")
    def health() -> tuple[dict[str, str], int]:
        return {"status": "ok"}, 200

    @app.post("/runs")
    def create_run():
        body = request.get_json(silent=True) or {}
        title = body.get("title", "untitled")
        seeded_bootstrap_task = not body

        run = _to_run(
            repository.create_run(
                run_id=uuid4(),
                title=title,
                state=LifecycleState.NEW,
                seeded_bootstrap_task=seeded_bootstrap_task,
            )
        )

        tasks_payload: list[Task] = []
        if seeded_bootstrap_task:
            tasks_payload.append(_create_task(run.id, "bootstrap-task", 3))

        run_payload = _serialize_run(run)
        response = {
            "id": str(run.id),
            "run": run_payload,
            "tasks": [_serialize_task(task) for task in tasks_payload],
        }
        return jsonify(response), 201

    @app.get("/runs/<run_id>")
    def get_run(run_id: str):
        record = repository.get_run(run_id)
        if record is None:
            return jsonify({"error": "not_found"}), 404

        return jsonify(_serialize_run(_to_run(record))), 200

    @app.post("/runs/<run_id>/tasks")
    def create_run_task(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404

        body = request.get_json(silent=True) or {}
        name = body.get("name", "unnamed-task")
        max_retries = int(body.get("max_retries", 3))
        task = _create_task(
            run_record.id,
            name,
            max_retries,
            require_approval=bool(body.get("require_approval", False)),
            requested_by=body.get("requested_by", "system"),
        )
        return jsonify(_serialize_task(task)), 201

    @app.get("/runs/<run_id>/tasks")
    def get_run_tasks(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404

        task_rows = [_serialize_task(_to_task(task)) for task in repository.list_tasks_for_run(run_id)]
        if run_record.seeded_bootstrap_task:
            return jsonify({"run_id": run_id, "tasks": task_rows}), 200
        return jsonify(task_rows), 200

    @app.post("/runs/<run_id>/tasks/<task_id>/transition")
    def transition_task_state(run_id: str, task_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404

        task_record = repository.get_task(task_id)
        if task_record is None or str(task_record.run_id) != run_id:
            return jsonify({"error": "not_found"}), 404

        body = request.get_json(silent=True) or {}
        to_state_value = body.get("to_state")
        try:
            to_state = LifecycleState(to_state_value)
        except ValueError:
            return jsonify({"error": "invalid_target_state"}), 400

        transition = apply_transition(task_record.state, to_state)
        if not transition.valid:
            return jsonify({"error": transition.reason_code}), 409

        updated_task = repository.update_task_state(task_id=task_record.id, state=to_state)
        assert updated_task is not None
        if to_state == LifecycleState.READY:
            _enqueue_task(_to_task(updated_task))
        _sync_run_state(task_record.run_id)
        return jsonify(_serialize_task(_to_task(updated_task))), 200

    @app.post("/runs/<run_id>/approvals")
    def create_approval(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404

        body = request.get_json(silent=True) or {}
        resolved_task_id, error_response = _resolve_optional_task_for_run(run_id, body.get("task_id"))
        if error_response is not None:
            return error_response

        record = repository.create_approval(
            approval_id=uuid4(),
            run_id=run_record.id,
            task_id=resolved_task_id,
            status=body.get("status", "pending"),
            requested_by=body.get("requested_by", "system"),
            decided_by=body.get("decided_by"),
            decision_note=body.get("decision_note"),
        )
        return jsonify(_serialize_approval(_to_approval(record))), 201

    @app.get("/runs/<run_id>/approvals")
    def list_approvals(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404

        approval_rows = [_serialize_approval(_to_approval(item)) for item in repository.list_approvals_for_run(run_id)]
        return jsonify(approval_rows), 200

    @app.post("/runs/<run_id>/approvals/<approval_id>/decision")
    def decide_approval(run_id: str, approval_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404

        approval_record = repository.get_approval(approval_id)
        if approval_record is None or str(approval_record.run_id) != run_id:
            return jsonify({"error": "not_found"}), 404

        body = request.get_json(silent=True) or {}
        status = body.get("status")
        if status not in {"approved", "rejected"}:
            return jsonify({"error": "invalid_approval_status"}), 400
        if approval_record.status != "pending":
            return jsonify({"error": "approval_already_decided"}), 409

        updated_approval = repository.update_approval(
            approval_id=approval_record.id,
            status=status,
            decided_by=body.get("decided_by", "operator"),
            decision_note=body.get("decision_note"),
        )
        assert updated_approval is not None

        task_payload = None
        if approval_record.task_id is not None:
            task_record = repository.get_task(str(approval_record.task_id))
            assert task_record is not None
            target_state = LifecycleState.READY if status == "approved" else LifecycleState.NEEDS_HUMAN
            transition = apply_transition(task_record.state, target_state)
            if not transition.valid:
                return jsonify({"error": transition.reason_code}), 409
            updated_task = repository.update_task_state(task_id=task_record.id, state=target_state)
            assert updated_task is not None
            task_payload = _serialize_task(_to_task(updated_task))
            if status == "approved":
                _enqueue_task(_to_task(updated_task))
            _sync_run_state(task_record.run_id)

        return jsonify({"approval": _serialize_approval(_to_approval(updated_approval)), "task": task_payload}), 200

    @app.post("/runs/<run_id>/artefacts")
    def create_artefact(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404

        body = request.get_json(silent=True) or {}
        resolved_task_id, error_response = _resolve_optional_task_for_run(run_id, body.get("task_id"))
        if error_response is not None:
            return error_response

        record = repository.create_artefact(
            artefact_id=uuid4(),
            run_id=run_record.id,
            task_id=resolved_task_id,
            path=body["path"],
            checksum=body["checksum"],
            version=body["version"],
            producer=body["producer"],
        )
        return jsonify(_serialize_artefact(_to_artefact(record))), 201

    @app.get("/runs/<run_id>/artefacts")
    def list_artefacts(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404

        task_id = request.args.get("task_id")
        artefact_rows = [
            _serialize_artefact(_to_artefact(item))
            for item in repository.list_artefacts_for_run(run_id, task_id=task_id)
        ]
        return jsonify(artefact_rows), 200

    @app.post("/workers/drain-once")
    def worker_drain_once():
        event = drain_worker_once(queue, events.append)
        if event is None:
            return jsonify({"status": "idle"}), 200
        existing_event = None
        if event.idempotency_key is not None:
            existing_event = repository.get_workflow_event_by_idempotency_key(event.idempotency_key)
        if existing_event is not None:
            return (
                jsonify(
                    {
                        "status": "duplicate",
                        "event": {
                            "event_id": existing_event.event_id,
                            "event_type": existing_event.event_type,
                            "run_id": str(existing_event.run_id) if existing_event.run_id is not None else None,
                            "task_id": str(existing_event.task_id) if existing_event.task_id is not None else None,
                            "payload": existing_event.payload,
                            "idempotency_key": existing_event.idempotency_key,
                            "created_at": existing_event.created_at,
                        },
                    }
                ),
                200,
            )
        repository.create_workflow_event(event)
        repository.update_task_state(
            task_id=event.task_id,
            state=LifecycleState.IN_PROGRESS,
            retry_count=event.payload["attempt"],
        )
        _sync_run_state(event.run_id)
        execution = repository.create_execution(
            execution_id=uuid4(),
            run_id=event.run_id,
            task_id=event.task_id,
            status="dequeued",
            runner_kind="worker",
            attempt=event.payload["attempt"],
        )
        repository.create_log(
            log_id=uuid4(),
            run_id=event.run_id,
            task_id=event.task_id,
            execution_id=execution.id,
            level="info",
            message=event.event_type,
        )
        return jsonify({"status": "processed", "event": _serialize_event(event)}), 200

    @app.get("/workflow-events")
    def list_workflow_events():
        persisted = repository.list_workflow_events()
        return jsonify(
            [
                {
                    "event_id": item.event_id,
                    "event_type": item.event_type,
                    "run_id": str(item.run_id) if item.run_id is not None else None,
                    "task_id": str(item.task_id) if item.task_id is not None else None,
                    "payload": item.payload,
                    "idempotency_key": item.idempotency_key,
                    "created_at": item.created_at,
                }
                for item in persisted
            ]
        ), 200

    @app.get("/runs/<run_id>/executions")
    def list_executions(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify([_serialize_execution(item) for item in repository.list_executions_for_run(run_id)]), 200

    @app.get("/runs/<run_id>/logs")
    def list_logs(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify([_serialize_log(item) for item in repository.list_logs_for_run(run_id)]), 200

    return AppRuntime(
        app=app,
        repository=repository,
        queue=queue,
        events=events,
        runs=runs,
        tasks=tasks,
        approvals=approvals,
        artefacts=artefacts,
        logs=logs,
        executions=executions,
    )


_DEFAULT_RUNTIME = create_runtime()
app = _DEFAULT_RUNTIME.app
REPOSITORY = _DEFAULT_RUNTIME.repository
EVENTS = _DEFAULT_RUNTIME.events
QUEUE = _DEFAULT_RUNTIME.queue
RUNS = _DEFAULT_RUNTIME.runs
TASKS = _DEFAULT_RUNTIME.tasks
APPROVALS = _DEFAULT_RUNTIME.approvals
ARTEFACTS = _DEFAULT_RUNTIME.artefacts
LOGS = _DEFAULT_RUNTIME.logs
EXECUTIONS = _DEFAULT_RUNTIME.executions
