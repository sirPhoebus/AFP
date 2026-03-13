"""Execution policy checks for coding-task prerequisites."""

from dataclasses import dataclass


BASE_REQUIRED_SKILLS = {"test-driven-development", "verification-before-completion"}
BUGFIX_REQUIRED_SKILLS = {"systematic-debugging"}
FOLDER_AGENT_RULES: tuple[tuple[str, str], ...] = (
    ("src/", "system_operator"),
    ("tests/", "system_operator"),
    ("db/", "system_operator"),
    ("docs/", "file_manager"),
    ("agents/", "file_manager"),
    ("skills/", "file_manager"),
)


@dataclass(frozen=True)
class ExecutionPolicyDecision:
    allowed: bool
    reason_codes: tuple[str, ...]


def _required_skills(task_kind: str) -> set[str]:
    required = set(BASE_REQUIRED_SKILLS)
    if task_kind == "bugfix":
        required.update(BUGFIX_REQUIRED_SKILLS)
    return required


def _expected_agent_for_path(path: str) -> str | None:
    normalized_path = path.strip("./")
    for prefix, agent_name in FOLDER_AGENT_RULES:
        if normalized_path.startswith(prefix):
            return agent_name
    return None


def evaluate_coding_task_policy(
    *,
    task_kind: str,
    target_paths: list[str],
    selected_agent: str,
    loaded_skills: list[str],
) -> ExecutionPolicyDecision:
    """Validate skill prerequisites and folder-scoped agent selection."""
    reason_codes: list[str] = []

    missing_skills = sorted(_required_skills(task_kind) - set(loaded_skills))
    if missing_skills:
        reason_codes.append(f"missing_required_skills:{','.join(missing_skills)}")

    expected_agents = {
        expected_agent
        for path in target_paths
        if (expected_agent := _expected_agent_for_path(path)) is not None
    }
    if expected_agents and selected_agent not in expected_agents:
        reason_codes.append(f"incorrect_agent_for_scope:{','.join(sorted(expected_agents))}")

    if len(expected_agents) > 1:
        reason_codes.append("mixed_folder_scopes_require_split")

    return ExecutionPolicyDecision(allowed=not reason_codes, reason_codes=tuple(reason_codes))
