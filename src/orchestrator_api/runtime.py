"""Runtime construction for the orchestrator API."""

from __future__ import annotations

from uuid import uuid4

from flask import Flask
from flask import g, jsonify, request

from persistence import PostgresRepository, SQLiteRepository, TableResetView
from workflow_engine import InMemoryQueue, RedisQueue

from .config import AppConfig
from .models import AppRuntime
from .routes import register_routes
from .services import WorkflowService


def create_runtime(db_dsn: str = ":memory:", queue_url: str | None = None) -> AppRuntime:
    app = Flask(__name__)
    config = AppConfig.from_env()
    if db_dsn.startswith("postgresql://") or db_dsn.startswith("postgres://"):
        repository = PostgresRepository(db_dsn)
    else:
        repository = SQLiteRepository(db_dsn)

    events = []
    queue = RedisQueue(queue_url) if queue_url else InMemoryQueue()
    service = WorkflowService(repository, queue, events)

    @app.before_request
    def attach_request_context():
        g.request_id = request.headers.get("X-Request-ID", str(uuid4()))
        g.correlation_id = request.headers.get("X-Correlation-ID", g.request_id)
        if config.api_token and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            header = request.headers.get("Authorization", "")
            if header != f"Bearer {config.api_token}":
                return jsonify({"error": "unauthorized"}), 401
        if request.path.endswith("/decision") and request.method == "POST":
            role = request.headers.get("X-AFP-Role", "reviewer")
            if role not in config.approval_roles:
                return jsonify({"error": "forbidden"}), 403
        return None

    @app.after_request
    def add_trace_headers(response):
        response.headers["X-Request-ID"] = g.request_id
        response.headers["X-Correlation-ID"] = g.correlation_id
        return response

    runs = TableResetView(
        repository,
        "workflow_events",
        "policy_decisions",
        "eval_runs",
        "pull_requests",
        "ci_checks",
        "unit_evidence",
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
        "pull_requests",
        "ci_checks",
        "unit_evidence",
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
    executions = TableResetView(repository, "unit_evidence", "logs", "executions")
    task_dependencies = TableResetView(repository, "task_dependencies")
    unit_evidence = TableResetView(repository, "unit_evidence")

    service.recover_ready_tasks()
    register_routes(app, service, config=config)

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
        task_dependencies=task_dependencies,
        unit_evidence=unit_evidence,
    )
