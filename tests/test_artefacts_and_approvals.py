import unittest
from uuid import uuid4

from orchestrator_api.app import APPROVALS, ARTEFACTS, QUEUE, RUNS, TASKS, TASK_DEPENDENCIES, app


class ArtefactAndApprovalApiTests(unittest.TestCase):
    def setUp(self) -> None:
        RUNS.clear()
        TASKS.clear()
        APPROVALS.clear()
        ARTEFACTS.clear()
        TASK_DEPENDENCIES.clear()
        while QUEUE.dequeue() is not None:
            pass
        self.client = app.test_client()

    def test_register_and_list_approval_for_run(self) -> None:
        run_response = self.client.post("/runs", json={"title": "approval-demo"})
        run_id = run_response.get_json()["id"]

        create_response = self.client.post(
            f"/runs/{run_id}/approvals",
            json={"status": "pending", "requested_by": "operator"},
        )
        self.assertEqual(create_response.status_code, 201)
        approval_body = create_response.get_json()
        self.assertEqual(approval_body["status"], "pending")
        self.assertEqual(approval_body["requested_by"], "operator")

        list_response = self.client.get(f"/runs/{run_id}/approvals")
        self.assertEqual(list_response.status_code, 200)
        approvals = list_response.get_json()
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0]["id"], approval_body["id"])

    def test_register_and_filter_artefacts_by_task(self) -> None:
        run_response = self.client.post("/runs")
        run_body = run_response.get_json()
        run_id = run_body["run"]["id"]
        task_id = run_body["tasks"][0]["id"]

        create_response = self.client.post(
            f"/runs/{run_id}/artefacts",
            json={
                "task_id": task_id,
                "path": "docs/plan.md",
                "checksum": "abc123",
                "version": "v1",
                "producer": "planner",
            },
        )
        self.assertEqual(create_response.status_code, 201)

        list_response = self.client.get(f"/runs/{run_id}/artefacts", query_string={"task_id": task_id})
        self.assertEqual(list_response.status_code, 200)
        artefacts = list_response.get_json()
        self.assertEqual(len(artefacts), 1)
        self.assertEqual(artefacts[0]["path"], "docs/plan.md")

    def test_rejects_approval_for_unknown_task(self) -> None:
        run_response = self.client.post("/runs", json={"title": "approval-demo"})
        run_id = run_response.get_json()["id"]

        create_response = self.client.post(
            f"/runs/{run_id}/approvals",
            json={"task_id": str(uuid4()), "status": "pending", "requested_by": "operator"},
        )

        self.assertEqual(create_response.status_code, 400)
        self.assertEqual(create_response.get_json(), {"error": "invalid_task_reference"})

    def test_rejects_artefact_for_malformed_task_id(self) -> None:
        run_response = self.client.post("/runs", json={"title": "artefact-demo"})
        run_id = run_response.get_json()["id"]

        create_response = self.client.post(
            f"/runs/{run_id}/artefacts",
            json={
                "task_id": "not-a-uuid",
                "path": "docs/plan.md",
                "checksum": "abc123",
                "version": "v1",
                "producer": "planner",
            },
        )

        self.assertEqual(create_response.status_code, 400)
        self.assertEqual(create_response.get_json(), {"error": "invalid_task_id"})

    def test_approval_decision_advances_task_to_ready_and_enqueues(self) -> None:
        run_response = self.client.post("/runs", json={"title": "approval-gated"})
        run_id = run_response.get_json()["id"]

        task_response = self.client.post(
            f"/runs/{run_id}/tasks",
            json={"name": "gated", "max_retries": 2, "require_approval": True, "requested_by": "planner"},
        )
        self.assertEqual(task_response.status_code, 201)
        self.assertEqual(task_response.get_json()["state"], "awaiting_approval")

        approval_id = self.client.get(f"/runs/{run_id}/approvals").get_json()[0]["id"]
        decision_response = self.client.post(
            f"/runs/{run_id}/approvals/{approval_id}/decision",
            json={"status": "approved", "decided_by": "operator"},
        )

        self.assertEqual(decision_response.status_code, 200)
        decision_body = decision_response.get_json()
        self.assertEqual(decision_body["approval"]["status"], "approved")
        self.assertEqual(decision_body["task"]["state"], "ready")
        self.assertEqual(QUEUE.size(), 1)
        self.assertEqual(self.client.get(f"/runs/{run_id}").get_json()["state"], "ready")

    def test_rejection_moves_task_to_needs_human_without_queueing(self) -> None:
        run_response = self.client.post("/runs", json={"title": "approval-gated"})
        run_id = run_response.get_json()["id"]

        self.client.post(
            f"/runs/{run_id}/tasks",
            json={"name": "gated", "max_retries": 2, "require_approval": True},
        )
        approval_id = self.client.get(f"/runs/{run_id}/approvals").get_json()[0]["id"]
        decision_response = self.client.post(
            f"/runs/{run_id}/approvals/{approval_id}/decision",
            json={"status": "rejected", "decided_by": "operator"},
        )

        self.assertEqual(decision_response.status_code, 200)
        decision_body = decision_response.get_json()
        self.assertEqual(decision_body["approval"]["status"], "rejected")
        self.assertEqual(decision_body["task"]["state"], "needs_human")
        self.assertEqual(QUEUE.size(), 0)
        self.assertEqual(self.client.get(f"/runs/{run_id}").get_json()["state"], "needs_human")

    def test_multi_task_run_state_uses_aggregate_priority(self) -> None:
        run_id = self.client.post("/runs", json={"title": "multi-task"}).get_json()["id"]

        self.client.post(f"/runs/{run_id}/tasks", json={"name": "ready-task"})
        self.client.post(f"/runs/{run_id}/tasks", json={"name": "gated-task", "require_approval": True})
        self.assertEqual(self.client.get(f"/runs/{run_id}").get_json()["state"], "awaiting_approval")

        approval_id = self.client.get(f"/runs/{run_id}/approvals").get_json()[0]["id"]
        self.client.post(
            f"/runs/{run_id}/approvals/{approval_id}/decision",
            json={"status": "approved", "decided_by": "operator"},
        )
        self.assertEqual(self.client.get(f"/runs/{run_id}").get_json()["state"], "ready")

        self.client.post("/workers/drain-once")
        self.assertEqual(self.client.get(f"/runs/{run_id}").get_json()["state"], "in_progress")

    def test_needs_human_dominates_ready_tasks_in_run_state(self) -> None:
        run_id = self.client.post("/runs", json={"title": "multi-task"}).get_json()["id"]

        self.client.post(f"/runs/{run_id}/tasks", json={"name": "ready-task"})
        self.client.post(f"/runs/{run_id}/tasks", json={"name": "gated-task", "require_approval": True})
        approval_id = self.client.get(f"/runs/{run_id}/approvals").get_json()[0]["id"]

        self.client.post(
            f"/runs/{run_id}/approvals/{approval_id}/decision",
            json={"status": "rejected", "decided_by": "operator"},
        )
        self.assertEqual(self.client.get(f"/runs/{run_id}").get_json()["state"], "needs_human")

    def test_run_state_stays_at_earliest_incomplete_success_stage(self) -> None:
        run_id = self.client.post("/runs", json={"title": "completion-aggregate"}).get_json()["id"]

        task_one = self.client.post(f"/runs/{run_id}/tasks", json={"name": "task-one"}).get_json()["id"]
        task_two = self.client.post(f"/runs/{run_id}/tasks", json={"name": "task-two"}).get_json()["id"]

        for target in ("in_progress", "unit_pass"):
            self.client.post(f"/runs/{run_id}/tasks/{task_one}/transition", json={"to_state": target})
        for target in ("in_progress", "unit_pass", "pr_open", "integration_pass", "merged"):
            self.client.post(f"/runs/{run_id}/tasks/{task_two}/transition", json={"to_state": target})

        self.assertEqual(self.client.get(f"/runs/{run_id}").get_json()["state"], "unit_pass")

    def test_run_state_advances_to_integration_pass_when_all_tasks_clear_pr_open(self) -> None:
        run_id = self.client.post("/runs", json={"title": "completion-aggregate"}).get_json()["id"]

        task_one = self.client.post(f"/runs/{run_id}/tasks", json={"name": "task-one"}).get_json()["id"]
        task_two = self.client.post(f"/runs/{run_id}/tasks", json={"name": "task-two"}).get_json()["id"]

        for task_id in (task_one, task_two):
            for target in ("in_progress", "unit_pass", "pr_open", "integration_pass"):
                self.client.post(f"/runs/{run_id}/tasks/{task_id}/transition", json={"to_state": target})
        self.client.post(f"/runs/{run_id}/tasks/{task_two}/transition", json={"to_state": "merged"})

        self.assertEqual(self.client.get(f"/runs/{run_id}").get_json()["state"], "integration_pass")

    def test_dependency_blocked_task_promotes_when_prerequisite_reaches_unit_pass(self) -> None:
        run_id = self.client.post("/runs", json={"title": "deps"}).get_json()["id"]
        first_task = self.client.post(f"/runs/{run_id}/tasks", json={"name": "first"}).get_json()
        second_task = self.client.post(
            f"/runs/{run_id}/tasks",
            json={"name": "second", "depends_on_task_ids": [first_task["id"]]},
        ).get_json()

        self.assertEqual(second_task["state"], "blocked")

        self.client.post(f"/runs/{run_id}/tasks/{first_task['id']}/transition", json={"to_state": "in_progress"})
        self.client.post(f"/runs/{run_id}/tasks/{first_task['id']}/transition", json={"to_state": "unit_pass"})

        tasks = {task["name"]: task for task in self.client.get(f"/runs/{run_id}/tasks").get_json()}
        self.assertEqual(tasks["second"]["state"], "ready")
        self.assertEqual(QUEUE.size(), 2)

    def test_dag_endpoint_returns_nodes_and_edges(self) -> None:
        run_id = self.client.post("/runs", json={"title": "deps"}).get_json()["id"]
        first_task = self.client.post(f"/runs/{run_id}/tasks", json={"name": "first"}).get_json()
        second_task = self.client.post(
            f"/runs/{run_id}/tasks",
            json={"name": "second", "depends_on_task_ids": [first_task["id"]]},
        ).get_json()

        dag = self.client.get(f"/runs/{run_id}/dag")
        self.assertEqual(dag.status_code, 200)
        body = dag.get_json()
        self.assertEqual(len(body["nodes"]), 2)
        self.assertEqual(body["edges"], [{"task_id": second_task["id"], "depends_on_task_id": first_task["id"]}])


if __name__ == "__main__":
    unittest.main()
