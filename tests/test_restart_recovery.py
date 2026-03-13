import tempfile
import unittest
from pathlib import Path

from orchestrator_api.app import create_runtime


class RestartRecoveryTests(unittest.TestCase):
    def test_ready_tasks_are_recovered_into_queue_after_restart(self) -> None:
        db_path = Path(tempfile.mkdtemp()) / "restart-recovery.db"

        first_runtime = create_runtime(str(db_path))
        first_client = first_runtime.app.test_client()

        run_response = first_client.post("/runs", json={"title": "restart-demo"})
        run_id = run_response.get_json()["id"]
        task_response = first_client.post(
            f"/runs/{run_id}/tasks",
            json={"name": "recover-me", "max_retries": 2},
        )

        self.assertEqual(first_runtime.queue.size(), 1)
        task_id = task_response.get_json()["id"]

        restarted_runtime = create_runtime(str(db_path))
        restarted_client = restarted_runtime.app.test_client()

        self.assertEqual(restarted_runtime.queue.size(), 1)
        task_list = restarted_client.get(f"/runs/{run_id}/tasks")
        self.assertEqual(task_list.status_code, 200)
        self.assertEqual(task_list.get_json()[0]["id"], task_id)

        drain_response = restarted_client.post("/workers/drain-once")
        self.assertEqual(drain_response.status_code, 200)
        self.assertEqual(drain_response.get_json()["status"], "processed")
        self.assertEqual(restarted_runtime.queue.size(), 0)

    def test_workflow_events_and_audit_survive_restart(self) -> None:
        db_path = Path(tempfile.mkdtemp()) / "event-recovery.db"

        first_runtime = create_runtime(str(db_path))
        first_client = first_runtime.app.test_client()

        run_response = first_client.post("/runs", json={"title": "event-demo"})
        run_id = run_response.get_json()["id"]
        first_client.post(f"/runs/{run_id}/tasks", json={"name": "emit-event", "max_retries": 2})
        drain_response = first_client.post("/workers/drain-once")

        self.assertEqual(drain_response.status_code, 200)
        self.assertEqual(len(first_client.get("/workflow-events").get_json()), 1)
        self.assertEqual(len(first_client.get(f"/runs/{run_id}/executions").get_json()), 1)
        self.assertEqual(len(first_client.get(f"/runs/{run_id}/logs").get_json()), 1)

        restarted_runtime = create_runtime(str(db_path))
        restarted_client = restarted_runtime.app.test_client()

        persisted_events = restarted_client.get("/workflow-events")
        persisted_executions = restarted_client.get(f"/runs/{run_id}/executions")
        persisted_logs = restarted_client.get(f"/runs/{run_id}/logs")

        self.assertEqual(persisted_events.status_code, 200)
        self.assertEqual(len(persisted_events.get_json()), 1)
        self.assertEqual(persisted_events.get_json()[0]["event_type"], "task.execution.dequeued")
        self.assertEqual(persisted_executions.status_code, 200)
        self.assertEqual(persisted_executions.get_json()[0]["status"], "dequeued")
        self.assertEqual(persisted_logs.status_code, 200)
        self.assertEqual(persisted_logs.get_json()[0]["message"], "task.execution.dequeued")

    def test_duplicate_recovered_drain_is_idempotent(self) -> None:
        db_path = Path(tempfile.mkdtemp()) / "idempotency-recovery.db"

        first_runtime = create_runtime(str(db_path))
        first_client = first_runtime.app.test_client()
        run_id = first_client.post("/runs", json={"title": "idempotency-demo"}).get_json()["id"]
        first_client.post(f"/runs/{run_id}/tasks", json={"name": "dup-risk", "max_retries": 2})

        second_runtime = create_runtime(str(db_path))
        third_runtime = create_runtime(str(db_path))
        second_client = second_runtime.app.test_client()
        third_client = third_runtime.app.test_client()

        first_drain = second_client.post("/workers/drain-once")
        duplicate_drain = third_client.post("/workers/drain-once")

        self.assertEqual(first_drain.status_code, 200)
        self.assertEqual(first_drain.get_json()["status"], "processed")
        self.assertEqual(duplicate_drain.status_code, 200)
        self.assertEqual(duplicate_drain.get_json()["status"], "duplicate")

        executions = third_client.get(f"/runs/{run_id}/executions").get_json()
        events = third_client.get("/workflow-events").get_json()
        logs = third_client.get(f"/runs/{run_id}/logs").get_json()
        tasks = third_client.get(f"/runs/{run_id}/tasks").get_json()

        self.assertEqual(len(executions), 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(len(logs), 1)
        self.assertEqual(tasks[0]["state"], "in_progress")
        self.assertEqual(tasks[0]["retry_count"], 1)


if __name__ == "__main__":
    unittest.main()
