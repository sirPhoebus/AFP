import sqlite3
import unittest

from persistence import init_db


class PersistenceSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")

    def tearDown(self) -> None:
        self.connection.close()

    def test_init_db_creates_all_core_tables(self) -> None:
        init_db(self.connection)

        table_names = {
            row[0]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

        self.assertTrue(
            {
                "runs",
                "tasks",
                "task_dependencies",
                "approvals",
                "artefacts",
                "executions",
                "logs",
                "eval_runs",
                "policy_decisions",
                "workflow_events",
                "unit_evidence",
                "outbox_events",
                "schema_migrations",
            }.issubset(table_names)
        )

    def test_init_db_registers_migrations_and_indexes(self) -> None:
        init_db(self.connection)
        migrations = self.connection.execute("SELECT version FROM schema_migrations").fetchall()
        indexes = self.connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()

        self.assertTrue(any(row[0] == "001_core_schema.sql" for row in migrations))
        self.assertTrue(any(row[0] == "idx_tasks_run_state" for row in indexes))

    def test_tasks_and_policy_decisions_have_expected_foreign_keys(self) -> None:
        init_db(self.connection)

        task_foreign_keys = self.connection.execute("PRAGMA foreign_key_list(tasks)").fetchall()
        policy_foreign_keys = self.connection.execute("PRAGMA foreign_key_list(policy_decisions)").fetchall()

        self.assertEqual(task_foreign_keys[0][2], "runs")
        self.assertEqual({row[2] for row in policy_foreign_keys}, {"runs", "tasks", "eval_runs"})


if __name__ == "__main__":
    unittest.main()
