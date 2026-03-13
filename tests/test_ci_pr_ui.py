import unittest

from orchestrator_api.app import (
    APPROVALS,
    ARTEFACTS,
    QUEUE,
    RUNS,
    TASKS,
    TASK_DEPENDENCIES,
    UNIT_EVIDENCE,
    app,
)


class CiPrUiTests(unittest.TestCase):
    def setUp(self) -> None:
        RUNS.clear()
        TASKS.clear()
        APPROVALS.clear()
        ARTEFACTS.clear()
        TASK_DEPENDENCIES.clear()
        UNIT_EVIDENCE.clear()
        while QUEUE.dequeue() is not None:
            pass
        self.client = app.test_client()

    def test_merge_policy_blocks_and_then_allows(self) -> None:
        run_id = self.client.post("/runs", json={"title": "merge"}).get_json()["id"]
        task_id = self.client.post(f"/runs/{run_id}/tasks", json={"name": "task"}).get_json()["id"]
        self.client.post(
            f"/runs/{run_id}/tasks/{task_id}/execute-unit",
            json={"image": "python:3.13-slim", "command": ["python", "-c", "print('unit pass')"]},
        )

        blocked = self.client.post(f"/runs/{run_id}/merge-policy/evaluate")
        self.assertEqual(blocked.status_code, 200)
        self.assertEqual(blocked.get_json()["decision"], "blocked")

        self.client.post(f"/runs/{run_id}/pull-requests", json={"title": "PR", "branch": "run/merge", "status": "open", "url": "https://example.invalid/pr/1"})
        self.client.post(f"/runs/{run_id}/ci-checks", json={"name": "integration", "status": "passed"})

        allowed = self.client.post(f"/runs/{run_id}/merge-policy/evaluate")
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.get_json()["decision"], "allowed")

    def test_ui_shell_routes_render(self) -> None:
        self.assertEqual(self.client.get("/ui").status_code, 200)
        self.assertIn("Workflow Console", self.client.get("/ui").get_data(as_text=True))
        self.assertEqual(self.client.get("/ui/styles.css").status_code, 200)
        self.assertEqual(self.client.get("/ui/app.js").status_code, 200)


if __name__ == "__main__":
    unittest.main()
