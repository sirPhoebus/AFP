"""Public Flask app entrypoint."""

from .runtime import create_runtime


_DEFAULT_RUNTIME = create_runtime()
app = _DEFAULT_RUNTIME.app
REPOSITORY = _DEFAULT_RUNTIME.repository
EVENTS = _DEFAULT_RUNTIME.events
QUEUE = _DEFAULT_RUNTIME.queue
RUNS = _DEFAULT_RUNTIME.runs
TASKS = _DEFAULT_RUNTIME.tasks
APPROVALS = _DEFAULT_RUNTIME.approvals
ARTEFACTS = _DEFAULT_RUNTIME.artefacts
LOGS = _DEFAULT_RUNTIME.logs
EXECUTIONS = _DEFAULT_RUNTIME.executions
TASK_DEPENDENCIES = _DEFAULT_RUNTIME.task_dependencies
UNIT_EVIDENCE = _DEFAULT_RUNTIME.unit_evidence

__all__ = [
    "APPROVALS",
    "ARTEFACTS",
    "EVENTS",
    "EXECUTIONS",
    "LOGS",
    "QUEUE",
    "REPOSITORY",
    "RUNS",
    "TASKS",
    "TASK_DEPENDENCIES",
    "UNIT_EVIDENCE",
    "app",
    "create_runtime",
]
