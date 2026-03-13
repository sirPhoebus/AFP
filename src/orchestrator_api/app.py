"""Minimal API scaffold for Milestone A."""

from dataclasses import asdict, dataclass
from uuid import UUID, uuid4

from flask import Flask, jsonify, request

from workflow_engine import LifecycleState
from workflow_engine.events import QueueEnvelope, WorkflowEvent
from workflow_engine.worker import InMemoryQueue, drain_worker_once


@dataclass
class Run:
    id: UUID
    title: str
    state: LifecycleState


@dataclass
class Task:
    id: UUID
    run_id: UUID
    name: str
    state: LifecycleState
    retry_count: int
    max_retries: int


app = Flask(__name__)
RUNS: dict[str, Run] = {}
TASKS: dict[str, Task] = {}
QUEUE = InMemoryQueue()
EVENTS: list[WorkflowEvent] = []


@app.get("/health")
def health() -> tuple[dict[str, str], int]:
    return {"status": "ok"}, 200


@app.post("/runs")
def create_run() -> tuple[dict[str, str], int]:
    body = request.get_json(silent=True) or {}
    title = body.get("title", "seed-run")

    run_id = uuid4()
    run = Run(id=run_id, title=title, state=LifecycleState.NEW)
    RUNS[str(run_id)] = run

    payload = asdict(run)
    payload["id"] = str(payload["id"])
    payload["state"] = payload["state"].value
    return payload, 201


@app.get("/runs/<run_id>")
def get_run(run_id: str):
    run = RUNS.get(run_id)
    if run is None:
        return jsonify({"error": "not_found"}), 404

    payload = asdict(run)
    payload["id"] = str(payload["id"])
    payload["state"] = payload["state"].value
    return jsonify(payload), 200


@app.post("/runs/<run_id>/tasks")
def create_task(run_id: str):
    run = RUNS.get(run_id)
    if run is None:
        return jsonify({"error": "run_not_found"}), 404

    body = request.get_json(silent=True) or {}
    task_name = body.get("name", "seed-task")
    max_retries = int(body.get("max_retries", 3))

    task_id = uuid4()
    task = Task(
        id=task_id,
        run_id=run.id,
        name=task_name,
        state=LifecycleState.NEW,
        retry_count=0,
        max_retries=max_retries,
    )
    TASKS[str(task_id)] = task

    QUEUE.enqueue(QueueEnvelope(run_id=run.id, task_id=task.id, max_retries=task.max_retries))

    payload = asdict(task)
    payload["id"] = str(payload["id"])
    payload["run_id"] = str(payload["run_id"])
    payload["state"] = payload["state"].value
    return jsonify(payload), 201


@app.get("/runs/<run_id>/tasks")
def list_tasks(run_id: str):
    tasks = [task for task in TASKS.values() if str(task.run_id) == run_id]
    payload = []
    for task in tasks:
        task_payload = asdict(task)
        task_payload["id"] = str(task_payload["id"])
        task_payload["run_id"] = str(task_payload["run_id"])
        task_payload["state"] = task_payload["state"].value
        payload.append(task_payload)

    return jsonify(payload), 200


@app.post("/workers/drain-once")
def worker_drain_once():
    event = drain_worker_once(QUEUE, EVENTS.append)
    if event is None:
        return jsonify({"status": "empty"}), 200

    return (
        jsonify(
            {
                "status": "processed",
                "event_id": event.event_id,
                "event_type": event.event_type,
                "idempotency_key": event.idempotency_key,
            }
        ),
        200,
    )


@app.get("/workflow-events")
def list_workflow_events():
    return (
        jsonify(
            [
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "run_id": str(event.run_id) if event.run_id else None,
                    "task_id": str(event.task_id) if event.task_id else None,
                    "idempotency_key": event.idempotency_key,
                    "payload": event.payload,
                }
                for event in EVENTS
            ]
        ),
        200,
    )
