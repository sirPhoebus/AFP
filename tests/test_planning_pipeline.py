import unittest

from orchestrator_api.app import APPROVALS, ARTEFACTS, QUEUE, RUNS, TASKS, TASK_DEPENDENCIES, app


class PlanningPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        RUNS.clear()
        TASKS.clear()
        APPROVALS.clear()
        ARTEFACTS.clear()
        TASK_DEPENDENCIES.clear()
        while QUEUE.dequeue() is not None:
            pass
        self.client = app.test_client()

    def test_plan_endpoint_creates_dag_tasks_and_plan_artefact(self) -> None:
        run_id = self.client.post("/runs", json={"title": "plan-run"}).get_json()["id"]

        response = self.client.post(
            f"/runs/{run_id}/plan",
            json={
                "tasks": [
                    {"name": "requirements"},
                    {"name": "implementation", "depends_on": ["requirements"], "require_approval": True},
                ]
            },
        )

        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertEqual(len(body["tasks"]), 2)
        self.assertEqual(body["artefact"]["path"], f"plans/{run_id}.md")
        self.assertIn("implementation", body["document"])
        self.assertEqual(len(body["dag"]["edges"]), 1)

        dag_response = self.client.get(f"/runs/{run_id}/dag")
        self.assertEqual(dag_response.status_code, 200)
        dag = dag_response.get_json()
        self.assertEqual(len(dag["nodes"]), 2)
        self.assertEqual(len(dag["edges"]), 1)

    def test_plan_rejects_unknown_dependencies(self) -> None:
        run_id = self.client.post("/runs", json={"title": "plan-run"}).get_json()["id"]

        response = self.client.post(
            f"/runs/{run_id}/plan",
            json={"tasks": [{"name": "implementation", "depends_on": ["missing"]}]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "unknown_plan_dependency")


if __name__ == "__main__":
    unittest.main()
