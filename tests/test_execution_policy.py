import unittest

from policy_engine import evaluate_coding_task_policy


class ExecutionPolicyTests(unittest.TestCase):
    def test_allows_coding_task_with_required_skills_and_matching_agent(self) -> None:
        decision = evaluate_coding_task_policy(
            task_kind="feature",
            target_paths=["src/orchestrator_api/app.py", "tests/test_api_and_worker.py"],
            selected_agent="system_operator",
            loaded_skills=["test-driven-development", "verification-before-completion"],
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_codes, ())

    def test_blocks_bugfix_without_debugging_skill(self) -> None:
        decision = evaluate_coding_task_policy(
            task_kind="bugfix",
            target_paths=["src/workflow_engine/worker.py"],
            selected_agent="system_operator",
            loaded_skills=["test-driven-development", "verification-before-completion"],
        )

        self.assertFalse(decision.allowed)
        self.assertIn("missing_required_skills:systematic-debugging", decision.reason_codes)

    def test_blocks_agent_scope_mismatch(self) -> None:
        decision = evaluate_coding_task_policy(
            task_kind="feature",
            target_paths=["docs/technical-plan.md"],
            selected_agent="system_operator",
            loaded_skills=["test-driven-development", "verification-before-completion"],
        )

        self.assertFalse(decision.allowed)
        self.assertIn("incorrect_agent_for_scope:file_manager", decision.reason_codes)

    def test_flags_mixed_folder_scopes_for_split_execution(self) -> None:
        decision = evaluate_coding_task_policy(
            task_kind="feature",
            target_paths=["src/orchestrator_api/app.py", "docs/technical-plan.md"],
            selected_agent="system_operator",
            loaded_skills=["test-driven-development", "verification-before-completion"],
        )

        self.assertFalse(decision.allowed)
        self.assertIn("mixed_folder_scopes_require_split", decision.reason_codes)


if __name__ == "__main__":
    unittest.main()
