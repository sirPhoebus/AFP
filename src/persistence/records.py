"""Persistence record types shared by repository backends."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from workflow_engine import LifecycleState


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RunRecord:
    id: UUID
    title: str
    state: LifecycleState
    seeded_bootstrap_task: bool


@dataclass(frozen=True)
class TaskRecord:
    id: UUID
    run_id: UUID
    name: str
    state: LifecycleState
    retry_count: int
    max_retries: int
    lock_version: int = 0
    claimed_by: str | None = None
    claimed_at: str | None = None
    next_attempt_at: str | None = None
    last_error: str | None = None


@dataclass(frozen=True)
class TaskDependencyRecord:
    task_id: UUID
    depends_on_task_id: UUID


@dataclass(frozen=True)
class ApprovalRecord:
    id: UUID
    run_id: UUID
    task_id: UUID | None
    status: str
    requested_by: str
    decided_by: str | None
    decision_note: str | None
    scope: str = "task"
    role: str = "reviewer"
    required_approvals: int = 1
    invalidated_at: str | None = None
    invalidation_reason: str | None = None


@dataclass(frozen=True)
class ArtefactRecord:
    id: UUID
    run_id: UUID
    task_id: UUID | None
    path: str
    checksum: str
    version: str
    producer: str


@dataclass(frozen=True)
class ExecutionRecord:
    id: UUID
    run_id: UUID
    task_id: UUID
    status: str
    runner_kind: str
    attempt: int
    phase: str = "queued"
    correlation_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass(frozen=True)
class LogRecord:
    id: UUID
    run_id: UUID
    task_id: UUID | None
    execution_id: UUID | None
    level: str
    message: str


@dataclass(frozen=True)
class WorkflowEventRecord:
    event_id: str
    event_type: str
    run_id: UUID | None
    task_id: UUID | None
    payload: dict
    idempotency_key: str | None
    created_at: str
    correlation_id: str | None = None
    causation_id: str | None = None
    schema_version: int = 1
    replayed_from_event_id: str | None = None


@dataclass(frozen=True)
class OutboxEventRecord:
    id: UUID
    event_id: str
    topic: str
    payload: dict
    published_at: str | None
    created_at: str


@dataclass(frozen=True)
class UnitEvidenceRecord:
    id: UUID
    run_id: UUID
    task_id: UUID
    execution_id: UUID
    status: str
    command: str
    output: str


@dataclass(frozen=True)
class PullRequestRecord:
    id: UUID
    run_id: UUID
    title: str
    branch: str
    status: str
    url: str


@dataclass(frozen=True)
class CiCheckRecord:
    id: UUID
    run_id: UUID
    name: str
    status: str
    details: str | None
