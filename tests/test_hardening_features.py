import os
import tempfile
import unittest
from pathlib import Path

from orchestrator_api.app import create_runtime


class HardeningFeatureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = Path(tempfile.mkdtemp()) / "hardening.db"
        self.runtime = create_runtime(str(self.db_path))
        self.client = self.runtime.app.test_client()

    def test_execution_lifecycle_outbox_and_replay(self) -> None:
        run_id = self.client.post("/runs", json={"title": "lifecycle"}).get_json()["id"]
        task_id = self.client.post(f"/runs/{run_id}/tasks", json={"name": "task"}).get_json()["id"]

        dequeued = self.client.post("/workers/dequeue-once")
        self.assertEqual(dequeued.status_code, 200)
        self.assertEqual(dequeued.get_json()["status"], "processed")
        execution_id = dequeued.get_json()["execution"]["id"]

        started = self.client.post(
            f"/workers/executions/{execution_id}/start",
            json={"run_id": run_id, "task_id": task_id},
        )
        completed = self.client.post(
            f"/workers/executions/{execution_id}/complete",
            json={"run_id": run_id, "task_id": task_id, "success": True},
        )
        replay = self.client.post("/workflow-events/replay")
        outbox = self.client.get("/outbox-events")

        self.assertEqual(started.status_code, 200)
        self.assertEqual(completed.status_code, 200)
        self.assertGreaterEqual(replay.get_json()["count"], 3)
        self.assertGreaterEqual(len(outbox.get_json()), 3)

    def test_run_level_approval_and_invalidation(self) -> None:
        run_id = self.client.post("/runs", json={"title": "approvals"}).get_json()["id"]
        approval = self.client.post(
            f"/runs/{run_id}/approvals",
            json={"scope": "run", "status": "pending", "requested_by": "lead", "required_approvals": 1},
        ).get_json()
        decision = self.client.post(
            f"/runs/{run_id}/approvals/{approval['id']}/decision",
            json={"status": "approved", "decided_by": "operator"},
        )
        artefact = self.client.post(
            f"/runs/{run_id}/artefacts",
            json={"path": "docs/plan.md", "checksum": "abc", "version": "v1", "producer": "planner"},
        )
        approvals = self.client.get(f"/runs/{run_id}/approvals").get_json()

        self.assertEqual(decision.status_code, 200)
        self.assertEqual(artefact.status_code, 201)
        self.assertIn("invalidated", {item["status"] for item in approvals})

    def test_task_scoped_artefact_only_invalidates_matching_task_approval(self) -> None:
        run_id = self.client.post("/runs", json={"title": "task-approvals"}).get_json()["id"]
        task_a = self.client.post(f"/runs/{run_id}/tasks", json={"name": "a"}).get_json()["id"]
        task_b = self.client.post(f"/runs/{run_id}/tasks", json={"name": "b"}).get_json()["id"]

        approval_a = self.client.post(
            f"/runs/{run_id}/approvals",
            json={"task_id": task_a, "scope": "task", "requested_by": "lead"},
        ).get_json()
        approval_b = self.client.post(
            f"/runs/{run_id}/approvals",
            json={"task_id": task_b, "scope": "task", "requested_by": "lead"},
        ).get_json()
        self.client.post(
            f"/runs/{run_id}/approvals/{approval_a['id']}/decision",
            json={"status": "approved", "decided_by": "operator"},
        )
        self.client.post(
            f"/runs/{run_id}/approvals/{approval_b['id']}/decision",
            json={"status": "approved", "decided_by": "operator"},
        )

        self.client.post(
            f"/runs/{run_id}/artefacts",
            json={"task_id": task_a, "path": "a.txt", "checksum": "1", "version": "v1", "producer": "tester"},
        )
        approvals = {item["id"]: item["status"] for item in self.client.get(f"/runs/{run_id}/approvals").get_json()}

        self.assertEqual(approvals[approval_a["id"]], "invalidated")
        self.assertEqual(approvals[approval_b["id"]], "approved")

    def test_create_approval_rejects_pre_decided_records(self) -> None:
        run_id = self.client.post("/runs", json={"title": "approval-guard"}).get_json()["id"]
        response = self.client.post(
            f"/runs/{run_id}/approvals",
            json={"status": "approved", "decided_by": "operator"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "approval_must_start_pending")

    def test_ui_agent_and_ops_surfaces(self) -> None:
        run_id = self.client.post("/runs", json={"title": "ui"}).get_json()["id"]
        task_id = self.client.post(f"/runs/{run_id}/tasks", json={"name": "agent"}).get_json()["id"]

        dashboard = self.client.get("/ui/api/dashboard")
        approvals_queue = self.client.get("/ui/api/approvals/queue")
        detail = self.client.get(f"/ui/api/runs/{run_id}/detail")
        agents = self.client.get("/agents")
        invoke = self.client.post(
            f"/runs/{run_id}/tasks/{task_id}/invoke-agent",
            json={"agent_name": "coder", "prompt": "write code", "fail_primary": True},
        )
        metrics = self.client.get("/metrics")
        ops_config = self.client.get("/ops/config")
        backup = self.client.get("/ops/backup-posture")

        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(approvals_queue.status_code, 200)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(agents.status_code, 200)
        self.assertEqual(invoke.status_code, 200)
        self.assertEqual(invoke.get_json()["provider"], "fallback")
        self.assertEqual(metrics.status_code, 200)
        self.assertIn("afp_queue_depth", metrics.get_data(as_text=True))
        self.assertEqual(ops_config.status_code, 200)
        self.assertEqual(backup.status_code, 200)

    def test_dashboard_counts_pending_approvals_across_runs(self) -> None:
        run_a = self.client.post("/runs", json={"title": "a"}).get_json()["id"]
        run_b = self.client.post("/runs", json={"title": "b"}).get_json()["id"]
        self.client.post(f"/runs/{run_a}/approvals", json={"scope": "run", "requested_by": "lead"})
        self.client.post(f"/runs/{run_b}/approvals", json={"scope": "run", "requested_by": "lead"})

        dashboard = self.client.get("/ui/api/dashboard")

        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.get_json()["pending_approvals"], 2)

    def test_second_worker_cannot_claim_same_task(self) -> None:
        run_id = self.client.post("/runs", json={"title": "claims"}).get_json()["id"]
        self.client.post(f"/runs/{run_id}/tasks", json={"name": "claimed"})

        first = self.client.post("/workers/dequeue-once", headers={"X-Worker-ID": "worker-a"})
        second = self.client.post("/workers/dequeue-once", headers={"X-Worker-ID": "worker-b"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["status"], "processed")
        self.assertEqual(second.status_code, 200)
        self.assertIn(second.get_json()["status"], {"idle", "duplicate", "lost"})

    def test_auth_and_trace_headers_when_enabled(self) -> None:
        original_token = os.environ.get("AFP_API_TOKEN")
        original_roles = os.environ.get("AFP_APPROVAL_ROLES")
        os.environ["AFP_API_TOKEN"] = "secret-token"
        os.environ["AFP_APPROVAL_ROLES"] = "operator"
        try:
            runtime = create_runtime(str(Path(tempfile.mkdtemp()) / "secure.db"))
            client = runtime.app.test_client()
            unauthorized = client.post("/runs", json={"title": "secure"})
            self.assertEqual(unauthorized.status_code, 401)

            authorized = client.post(
                "/runs",
                json={"title": "secure"},
                headers={"Authorization": "Bearer secret-token", "X-Request-ID": "req-1"},
            )
            self.assertEqual(authorized.status_code, 201)
            self.assertEqual(authorized.headers["X-Request-ID"], "req-1")
        finally:
            if original_token is None:
                os.environ.pop("AFP_API_TOKEN", None)
            else:
                os.environ["AFP_API_TOKEN"] = original_token
            if original_roles is None:
                os.environ.pop("AFP_APPROVAL_ROLES", None)
            else:
                os.environ["AFP_APPROVAL_ROLES"] = original_roles


if __name__ == "__main__":
    unittest.main()
