"""Orchestrator API data models."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from flask import Flask

from persistence import TableResetView
from workflow_engine import InMemoryQueue, LifecycleState, RedisQueue
from workflow_engine.events import WorkflowEvent

from persistence.repository import PostgresRepository, SQLiteRepository


@dataclass
class Run:
    id: UUID
    title: str
    state: LifecycleState
    seeded_bootstrap_task: bool = False


@dataclass
class Task:
    id: UUID
    run_id: UUID
    name: str
    state: LifecycleState
    retry_count: int = 0
    max_retries: int = 3


@dataclass
class Approval:
    id: UUID
    run_id: UUID
    task_id: UUID | None
    status: str
    requested_by: str
    decided_by: str | None = None
    decision_note: str | None = None
    scope: str = "task"
    role: str = "reviewer"
    required_approvals: int = 1
    invalidated_at: str | None = None
    invalidation_reason: str | None = None


@dataclass
class Artefact:
    id: UUID
    run_id: UUID
    task_id: UUID | None
    path: str
    checksum: str
    version: str
    producer: str


@dataclass
class AppRuntime:
    app: Flask
    repository: SQLiteRepository | PostgresRepository
    queue: InMemoryQueue | RedisQueue
    events: list[WorkflowEvent]
    runs: TableResetView
    tasks: TableResetView
    approvals: TableResetView
    artefacts: TableResetView
    logs: TableResetView
    executions: TableResetView
    task_dependencies: TableResetView
    unit_evidence: TableResetView
