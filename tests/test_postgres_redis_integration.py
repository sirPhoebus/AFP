import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from orchestrator_api.app import create_runtime


COMPOSE_FILE = "/home/phoebus/repo/AFP/docker-compose.integration.yml"
POSTGRES_DSN = "postgresql://afp:afp@127.0.0.1:54329/afp"
REDIS_URL = "redis://127.0.0.1:6389/0"


def _compose(*args: str) -> None:
    subprocess.run(["docker", "compose", "-f", COMPOSE_FILE, *args], check=True)


class PostgresRedisIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _compose("up", "-d")
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                runtime = create_runtime(POSTGRES_DSN, REDIS_URL)
                runtime.runs.clear()
                while runtime.queue.dequeue() is not None:
                    pass
                return
            except Exception:
                time.sleep(1)
        raise RuntimeError("postgres/redis services did not become ready")

    @classmethod
    def tearDownClass(cls) -> None:
        _compose("down", "-v")

    def setUp(self) -> None:
        runtime = create_runtime(POSTGRES_DSN, REDIS_URL)
        runtime.runs.clear()
        while runtime.queue.dequeue() is not None:
            pass

    def test_runtime_uses_postgres_and_redis_for_end_to_end_flow(self) -> None:
        runtime = create_runtime(POSTGRES_DSN, REDIS_URL)
        client = runtime.app.test_client()

        run_id = client.post("/runs", json={"title": "pg-redis"}).get_json()["id"]
        task_id = client.post(
            f"/runs/{run_id}/tasks",
            json={"name": "dep-target", "max_retries": 2},
        ).get_json()["id"]

        self.assertEqual(runtime.queue.size(), 1)

        drained = client.post("/workers/drain-once")
        self.assertEqual(drained.status_code, 200)
        self.assertEqual(drained.get_json()["status"], "processed")

        run = client.get(f"/runs/{run_id}").get_json()
        events = client.get("/workflow-events").get_json()
        executions = client.get(f"/runs/{run_id}/executions").get_json()
        logs = client.get(f"/runs/{run_id}/logs").get_json()

        self.assertEqual(run["state"], "in_progress")
        self.assertEqual(events[0]["task_id"], task_id)
        self.assertEqual(len(executions), 1)
        self.assertEqual(len(logs), 1)
