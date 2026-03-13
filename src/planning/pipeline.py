"""Simple planning pipeline for generating a persisted task DAG."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PlannedTaskSpec:
    name: str
    depends_on: tuple[str, ...] = ()
    require_approval: bool = False
    requested_by: str = "planner"
    max_retries: int = 3


def render_plan_document(run_id: str, title: str, task_specs: list[PlannedTaskSpec]) -> str:
    lines = [f"# Plan for run {run_id}", "", f"Title: {title}", "", "## Tasks"]
    for task in task_specs:
        dependencies = ", ".join(task.depends_on) if task.depends_on else "none"
        approval = "yes" if task.require_approval else "no"
        lines.extend(
            [
                f"- name: {task.name}",
                f"  depends_on: {dependencies}",
                f"  require_approval: {approval}",
                f"  max_retries: {task.max_retries}",
            ]
        )
    return "\n".join(lines)
