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


class ContainerExecutionTests(unittest.TestCase):
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

    def test_container_execution_ingests_unit_evidence_and_advances_task(self) -> None:
        run_id = self.client.post("/runs", json={"title": "container"}).get_json()["id"]
        task_id = self.client.post(f"/runs/{run_id}/tasks", json={"name": "unit-task"}).get_json()["id"]

        response = self.client.post(
            f"/runs/{run_id}/tasks/{task_id}/execute-unit",
            json={"image": "python:3.13-slim", "command": ["python", "-c", "print('unit pass')"]},
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["execution"]["status"], "unit_pass")
        self.assertEqual(body["evidence"]["status"], "passed")

        evidence = self.client.get(f"/runs/{run_id}/unit-evidence")
        self.assertEqual(evidence.status_code, 200)
        self.assertEqual(len(evidence.get_json()), 1)

        tasks = self.client.get(f"/runs/{run_id}/tasks").get_json()
        self.assertEqual(tasks[0]["state"], "unit_pass")


if __name__ == "__main__":
    unittest.main()
