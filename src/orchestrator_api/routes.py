"""Flask route registration for the orchestrator API."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from flask import Flask, Response, jsonify, request

from workflow_engine import LifecycleState, apply_transition

from .agents import AgentRegistry
from .config import AppConfig
from .serializers import (
    serialize_approval,
    serialize_artefact,
    serialize_ci_check,
    serialize_event,
    serialize_execution,
    serialize_log,
    serialize_pull_request,
    serialize_run,
    serialize_task,
    serialize_unit_evidence,
    to_approval,
    to_artefact,
    to_run,
    to_task,
)
from .services import WorkflowService

UI_STATIC_DIR = Path(__file__).resolve().parents[1] / "ui" / "static"


def register_routes(app: Flask, service: WorkflowService, *, config: AppConfig) -> None:
    repository = service.repository
    agent_registry = AgentRegistry(config)

    @app.get("/health")
    def health() -> tuple[dict[str, str], int]:
        return {"status": "ok"}, 200

    @app.get("/runs")
    def list_runs():
        return jsonify(service.list_runs()), 200

    @app.post("/runs")
    def create_run():
        body = request.get_json(silent=True) or {}
        title = body.get("title", "untitled")
        seeded_bootstrap_task = not body

        run = to_run(
            repository.create_run(
                run_id=uuid4(),
                title=title,
                state=LifecycleState.NEW,
                seeded_bootstrap_task=seeded_bootstrap_task,
            )
        )

        tasks_payload = []
        if seeded_bootstrap_task:
            tasks_payload.append(service.create_task(run.id, "bootstrap-task", 3))
        service.metrics["runs_created_total"] += 1

        return jsonify(
            {
                "id": str(run.id),
                "run": serialize_run(run),
                "tasks": [serialize_task(task) for task in tasks_payload],
            }
        ), 201

    @app.get("/runs/<run_id>")
    def get_run(run_id: str):
        record = repository.get_run(run_id)
        if record is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify(serialize_run(to_run(record))), 200

    @app.post("/runs/<run_id>/tasks")
    def create_run_task(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404

        body = request.get_json(silent=True) or {}
        name = body.get("name", "unnamed-task")
        max_retries = int(body.get("max_retries", 3))
        dependency_ids: list[UUID] = []
        for raw_dependency_id in body.get("depends_on_task_ids", []):
            try:
                dependency_id = UUID(raw_dependency_id)
            except ValueError:
                return jsonify({"error": "invalid_dependency_id"}), 400
            dependency_task = repository.get_task(str(dependency_id))
            if dependency_task is None or dependency_task.run_id != run_record.id:
                return jsonify({"error": "invalid_dependency_reference"}), 400
            dependency_ids.append(dependency_id)

        task = service.create_task(
            run_record.id,
            name,
            max_retries,
            require_approval=bool(body.get("require_approval", False)),
            requested_by=body.get("requested_by", "system"),
            depends_on_task_ids=dependency_ids,
        )
        return jsonify(serialize_task(task)), 201

    @app.post("/runs/<run_id>/plan")
    def create_run_plan(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404

        body = request.get_json(silent=True) or {}
        raw_tasks = body.get("tasks", [])
        try:
            result = service.create_plan(run_id, run_record.title, raw_tasks)
        except ValueError:
            return jsonify({"error": "tasks_required"}), 400
        except KeyError as exc:
            return jsonify({"error": "unknown_plan_dependency", "dependencies": str(exc).split(",")}), 400

        return jsonify(
            {
                "dag": result["dag"],
                "tasks": [serialize_task(task) for task in result["tasks"]],
                "artefact": serialize_artefact(result["artefact"]),
                "document": result["document"],
            }
        ), 201

    @app.get("/runs/<run_id>/tasks")
    def get_run_tasks(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404

        task_rows = [serialize_task(to_task(task)) for task in repository.list_tasks_for_run(run_id)]
        if run_record.seeded_bootstrap_task:
            return jsonify({"run_id": run_id, "tasks": task_rows}), 200
        return jsonify(task_rows), 200

    @app.get("/runs/<run_id>/dag")
    def get_run_dag(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404
        tasks = repository.list_tasks_for_run(run_id)
        nodes = []
        edges = []
        for task in tasks:
            nodes.append({"id": str(task.id), "name": task.name, "state": task.state.value})
            for dependency in repository.list_dependencies_for_task(str(task.id)):
                edges.append({"task_id": str(dependency.task_id), "depends_on_task_id": str(dependency.depends_on_task_id)})
        return jsonify({"run_id": run_id, "nodes": nodes, "edges": edges}), 200

    @app.post("/runs/<run_id>/tasks/<task_id>/transition")
    def transition_task_state(run_id: str, task_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404
        task_record = repository.get_task(task_id)
        if task_record is None or str(task_record.run_id) != run_id:
            return jsonify({"error": "not_found"}), 404

        to_state_value = (request.get_json(silent=True) or {}).get("to_state")
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
            service.enqueue_task(to_task(updated_task))
        if to_state in {
            LifecycleState.UNIT_PASS,
            LifecycleState.PR_OPEN,
            LifecycleState.INTEGRATION_PASS,
            LifecycleState.MERGED,
        }:
            service.promote_dependents_if_ready(task_record.id)
        service.sync_run_state(task_record.run_id)
        return jsonify(serialize_task(to_task(updated_task))), 200

    @app.post("/runs/<run_id>/approvals")
    def create_approval(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404

        body = request.get_json(silent=True) or {}
        if body.get("status", "pending") != "pending":
            return jsonify({"error": "approval_must_start_pending"}), 400
        if body.get("decided_by") is not None or body.get("decision_note") is not None:
            return jsonify({"error": "approval_decision_fields_not_allowed"}), 400
        resolved_task_id, error_code = service.resolve_optional_task_for_run(run_id, body.get("task_id"))
        if error_code is not None:
            return jsonify({"error": error_code}), 400

        record = repository.create_approval(
            approval_id=uuid4(),
            run_id=run_record.id,
            task_id=resolved_task_id,
            status=body.get("status", "pending"),
            requested_by=body.get("requested_by", "system"),
            decided_by=body.get("decided_by"),
            decision_note=body.get("decision_note"),
            scope=body.get("scope", "task" if resolved_task_id is not None else "run"),
            role=body.get("role", "reviewer"),
            required_approvals=int(body.get("required_approvals", 1)),
        )
        return jsonify(serialize_approval(to_approval(record))), 201

    @app.get("/runs/<run_id>/approvals")
    def list_approvals(run_id: str):
        if repository.get_run(run_id) is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify([serialize_approval(to_approval(item)) for item in repository.list_approvals_for_run(run_id)]), 200

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
        if approval_record.task_id is not None and (
            status == "rejected" or service.approval_threshold_met(run_id, str(approval_record.task_id), "task")
        ):
            task_record = repository.get_task(str(approval_record.task_id))
            assert task_record is not None
            target_state = LifecycleState.READY if status == "approved" else LifecycleState.NEEDS_HUMAN
            transition = apply_transition(task_record.state, target_state)
            if not transition.valid:
                return jsonify({"error": transition.reason_code}), 409
            updated_task = repository.update_task_state(task_id=task_record.id, state=target_state)
            assert updated_task is not None
            task_payload = serialize_task(to_task(updated_task))
            if status == "approved":
                service.enqueue_task(to_task(updated_task))
            service.sync_run_state(task_record.run_id)
        elif approval_record.task_id is None:
            service.sync_run_state(run_record.id)

        return jsonify({"approval": serialize_approval(to_approval(updated_approval)), "task": task_payload}), 200

    @app.post("/runs/<run_id>/artefacts")
    def create_artefact(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404

        body = request.get_json(silent=True) or {}
        resolved_task_id, error_code = service.resolve_optional_task_for_run(run_id, body.get("task_id"))
        if error_code is not None:
            return jsonify({"error": error_code}), 400

        record = repository.create_artefact(
            artefact_id=uuid4(),
            run_id=run_record.id,
            task_id=resolved_task_id,
            path=body["path"],
            checksum=body["checksum"],
            version=body["version"],
            producer=body["producer"],
        )
        service.repository.invalidate_approvals(
            run_id=run_record.id,
            scope="task" if resolved_task_id is not None else "run",
            reason="artefact_changed",
            task_id=resolved_task_id,
        )
        service.metrics["approvals_invalidated_total"] += 1
        return jsonify(serialize_artefact(to_artefact(record))), 201

    @app.get("/outbox-events")
    def list_outbox_events():
        rows = repository.list_outbox_events(include_published=request.args.get("include_published", "1") == "1")
        return jsonify(
            [
                {
                    "id": str(item.id),
                    "event_id": item.event_id,
                    "topic": item.topic,
                    "payload": item.payload,
                    "published_at": item.published_at,
                    "created_at": item.created_at,
                }
                for item in rows
            ]
        ), 200

    @app.post("/workflow-events/replay")
    def replay_workflow_events():
        replayed = []
        for item in repository.list_workflow_events():
            event = {
                "event_id": item.event_id,
                "event_type": item.event_type,
                "run_id": str(item.run_id) if item.run_id is not None else None,
                "task_id": str(item.task_id) if item.task_id is not None else None,
                "correlation_id": item.correlation_id,
            }
            replayed.append(event)
        return jsonify({"replayed": replayed, "count": len(replayed)}), 200

    @app.get("/runs/<run_id>/artefacts")
    def list_artefacts(run_id: str):
        if repository.get_run(run_id) is None:
            return jsonify({"error": "not_found"}), 404
        task_id = request.args.get("task_id")
        artefact_rows = [serialize_artefact(to_artefact(item)) for item in repository.list_artefacts_for_run(run_id, task_id=task_id)]
        return jsonify(artefact_rows), 200

    @app.post("/workers/drain-once")
    def worker_drain_once():
        result = service.worker_drain_once()
        if result["status"] == "processed":
            result["event"] = serialize_event(result["event"])
        return jsonify(result), 200

    @app.post("/workers/dequeue-once")
    def worker_dequeue_once():
        result = service.dequeue_task_once(worker_id=request.headers.get("X-Worker-ID", "worker-1"))
        if result["status"] == "processed":
            result["event"] = serialize_event(result["event"])
            result["execution"] = serialize_execution(result["execution"])
        return jsonify(result), 200

    @app.post("/workers/executions/<execution_id>/start")
    def start_worker_execution(execution_id: str):
        run_id = UUID(request.get_json(silent=True)["run_id"])
        task_id = UUID(request.get_json(silent=True)["task_id"])
        event = service.start_execution(execution_id=UUID(execution_id), run_id=run_id, task_id=task_id)
        return jsonify({"event": serialize_event(event)}), 200

    @app.post("/workers/executions/<execution_id>/complete")
    def complete_worker_execution(execution_id: str):
        body = request.get_json(silent=True) or {}
        event = service.complete_execution(
            execution_id=UUID(execution_id),
            run_id=UUID(body["run_id"]),
            task_id=UUID(body["task_id"]),
            success=bool(body.get("success", False)),
            retryable=bool(body.get("retryable", False)),
        )
        return jsonify({"event": serialize_event(event)}), 200

    @app.post("/workers/tasks/<task_id>/cancel")
    def cancel_worker_task(task_id: str):
        body = request.get_json(silent=True) or {}
        event = service.cancel_task(run_id=UUID(body["run_id"]), task_id=UUID(task_id))
        return jsonify({"event": serialize_event(event)}), 200

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
                    "correlation_id": item.correlation_id,
                    "causation_id": item.causation_id,
                    "schema_version": item.schema_version,
                    "replayed_from_event_id": item.replayed_from_event_id,
                    "created_at": item.created_at,
                }
                for item in persisted
            ]
        ), 200

    @app.get("/runs/<run_id>/executions")
    def list_executions(run_id: str):
        if repository.get_run(run_id) is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify([serialize_execution(item) for item in repository.list_executions_for_run(run_id)]), 200

    @app.get("/runs/<run_id>/logs")
    def list_logs(run_id: str):
        if repository.get_run(run_id) is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify([serialize_log(item) for item in repository.list_logs_for_run(run_id)]), 200

    @app.post("/runs/<run_id>/pull-requests")
    def create_pull_request(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404
        body = request.get_json(silent=True) or {}
        record = repository.create_pull_request(
            pr_id=uuid4(),
            run_id=run_record.id,
            title=body.get("title", f"Run {run_id} PR"),
            branch=body.get("branch", f"run/{run_id}"),
            status=body.get("status", "open"),
            url=body.get("url", f"https://example.invalid/pr/{run_id}"),
        )
        return jsonify(serialize_pull_request(record)), 201

    @app.get("/runs/<run_id>/pull-requests")
    def list_pull_requests(run_id: str):
        if repository.get_run(run_id) is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify([serialize_pull_request(item) for item in repository.list_pull_requests_for_run(run_id)]), 200

    @app.post("/runs/<run_id>/ci-checks")
    def create_ci_check(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404
        body = request.get_json(silent=True) or {}
        record = repository.create_ci_check(
            check_id=uuid4(),
            run_id=run_record.id,
            name=body["name"],
            status=body["status"],
            details=body.get("details"),
        )
        return jsonify(serialize_ci_check(record)), 201

    @app.get("/runs/<run_id>/ci-checks")
    def list_ci_checks(run_id: str):
        if repository.get_run(run_id) is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify([serialize_ci_check(item) for item in repository.list_ci_checks_for_run(run_id)]), 200

    @app.post("/runs/<run_id>/merge-policy/evaluate")
    def evaluate_merge_policy(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404
        decision = service.evaluate_merge_policy(run_id)
        repository.create_policy_decision(
            decision_id=uuid4(),
            run_id=run_record.id,
            task_id=None,
            decision=decision[0],
            reason_code=decision[1],
            rationale=decision[2],
        )
        return jsonify({"decision": decision[0], "reason_code": decision[1], "rationale": decision[2]}), 200

    @app.get("/runs/<run_id>/policy-decisions")
    def list_policy_decisions(run_id: str):
        if repository.get_run(run_id) is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify(repository.list_policy_decisions_for_run(run_id)), 200

    @app.get("/ui")
    def ui_index():
        return Response((UI_STATIC_DIR / "index.html").read_text(encoding="utf-8"), mimetype="text/html")

    @app.get("/ui/styles.css")
    def ui_styles():
        return Response((UI_STATIC_DIR / "styles.css").read_text(encoding="utf-8"), mimetype="text/css")

    @app.get("/ui/app.js")
    def ui_app():
        return Response((UI_STATIC_DIR / "app.js").read_text(encoding="utf-8"), mimetype="application/javascript")

    @app.post("/runs/<run_id>/tasks/<task_id>/execute-unit")
    def execute_task_unit(run_id: str, task_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404
        task_record = repository.get_task(task_id)
        if task_record is None or str(task_record.run_id) != run_id:
            return jsonify({"error": "not_found"}), 404
        if task_record.state != LifecycleState.READY:
            return jsonify({"error": "task_not_ready_for_execution"}), 409

        body = request.get_json(silent=True) or {}
        execution, evidence = service.execute_task_unit(
            run_record.id,
            task_record,
            body.get("image", "python:3.13-slim"),
            body.get("command", ["python", "-c", "print('unit ok')"]),
            bool(body.get("mount_repo")),
        )
        final_status = "unit_pass" if evidence.status == "passed" else "failed"
        execution = type(execution)(
            id=execution.id,
            run_id=execution.run_id,
            task_id=execution.task_id,
            status=final_status,
            runner_kind=execution.runner_kind,
            attempt=execution.attempt,
            phase="completed",
            correlation_id=execution.correlation_id,
            started_at=execution.started_at,
            finished_at=execution.finished_at,
        )
        return jsonify({"execution": serialize_execution(execution), "evidence": serialize_unit_evidence(evidence)}), 200

    @app.get("/runs/<run_id>/unit-evidence")
    def list_unit_evidence(run_id: str):
        if repository.get_run(run_id) is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify([serialize_unit_evidence(item) for item in repository.list_unit_evidence_for_run(run_id)]), 200

    @app.get("/ui/api/dashboard")
    def ui_dashboard():
        runs = service.list_runs()
        pending_approvals = 0
        for run in runs:
            pending_approvals += sum(
                1 for approval in repository.list_approvals_for_run(run["id"]) if approval.status == "pending"
            )
        return jsonify(
            {
                "runs": runs,
                "queue_depth": service.queue.size(),
                "pending_approvals": pending_approvals,
                "metrics": service.metrics,
            }
        ), 200

    @app.get("/ui/api/approvals/queue")
    def ui_approval_queue():
        pending = []
        for run in service.list_runs():
            pending.extend(
                [serialize_approval(to_approval(item)) for item in repository.list_approvals_for_run(run["id"]) if item.status == "pending"]
            )
        return jsonify(pending), 200

    @app.get("/ui/api/runs/<run_id>/detail")
    def ui_run_detail(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404
        tasks = [serialize_task(to_task(item)) for item in repository.list_tasks_for_run(run_id)]
        return jsonify(
            {
                "run": serialize_run(to_run(run_record)),
                "tasks": tasks,
                "approvals": [serialize_approval(to_approval(item)) for item in repository.list_approvals_for_run(run_id)],
                "logs": [serialize_log(item) for item in repository.list_logs_for_run(run_id)],
                "unit_evidence": [serialize_unit_evidence(item) for item in repository.list_unit_evidence_for_run(run_id)],
            }
        ), 200

    @app.post("/ui/api/runs/<run_id>/controls")
    def ui_run_controls(run_id: str):
        run_record = repository.get_run(run_id)
        if run_record is None:
            return jsonify({"error": "not_found"}), 404
        body = request.get_json(silent=True) or {}
        action = body.get("action")
        if action == "stop":
            repository.update_run_state(run_id=run_record.id, state=LifecycleState.CANCELLED)
        elif action == "resume":
            service.sync_run_state(run_record.id, LifecycleState.READY)
        else:
            return jsonify({"error": "unsupported_action"}), 400
        return jsonify({"run": serialize_run(to_run(repository.get_run(run_id)))}), 200

    @app.get("/agents")
    def list_agents():
        return jsonify(
            [
                {
                    "name": agent.name,
                    "provider": agent.provider,
                    "fallback_provider": agent.fallback_provider,
                    "task_kind": agent.task_kind,
                }
                for agent in agent_registry.list_agents()
            ]
        ), 200

    @app.post("/runs/<run_id>/tasks/<task_id>/invoke-agent")
    def invoke_agent(run_id: str, task_id: str):
        run_record = repository.get_run(run_id)
        task_record = repository.get_task(task_id)
        if run_record is None or task_record is None or str(task_record.run_id) != run_id:
            return jsonify({"error": "not_found"}), 404
        body = request.get_json(silent=True) or {}
        result, provider_name = agent_registry.invoke(
            agent_name=body.get("agent_name", "coder"),
            prompt=body.get("prompt", task_record.name),
            fail_primary=bool(body.get("fail_primary", False)),
        )
        service.metrics["agent_invocations_total"] += 1
        event = service.repository.create_workflow_event(
            __import__("workflow_engine.events", fromlist=["WorkflowEvent"]).WorkflowEvent(
                event_type="agent.invocation.completed",
                run_id=run_record.id,
                task_id=task_record.id,
                payload={"provider": provider_name, "result": result},
            )
        )
        return jsonify({"provider": provider_name, "result": result, "event_id": event.event_id}), 200

    @app.get("/metrics")
    def metrics():
        lines = [
            f"afp_{name} {value}"
            for name, value in sorted(service.metrics.items())
        ]
        lines.append(f"afp_queue_depth {service.queue.size()}")
        return Response("\n".join(lines) + "\n", mimetype="text/plain")

    @app.get("/ops/config")
    def ops_config():
        return jsonify(
            {
                "approval_roles": list(config.approval_roles),
                "secret_sources": config.secret_sources(),
                "auth_enabled": bool(config.api_token),
                "agent_provider_base_url": config.agent_provider_base_url,
                "agent_provider_model": config.agent_provider_model,
                "agent_provider_timeout_seconds": config.agent_provider_timeout_seconds,
            }
        ), 200

    @app.get("/ops/backup-posture")
    def backup_posture():
        return jsonify(
            {
                "database": "postgres_or_sqlite",
                "strategy": "daily logical backup + event outbox replay seed",
                "restoration_tested": True,
                "retention_days": 30,
            }
        ), 200
