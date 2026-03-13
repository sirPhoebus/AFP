"""Serialization helpers for API payloads."""

from __future__ import annotations

from dataclasses import asdict

from persistence.records import (
    ArtefactRecord,
    ApprovalRecord,
    CiCheckRecord,
    ExecutionRecord,
    LogRecord,
    PullRequestRecord,
    RunRecord,
    TaskRecord,
    UnitEvidenceRecord,
)
from workflow_engine.events import WorkflowEvent

from .models import Approval, Artefact, Run, Task


def serialize_run(run: Run) -> dict[str, str | bool]:
    payload = asdict(run)
    payload["id"] = str(run.id)
    payload["state"] = run.state.value
    return payload


def serialize_task(task: Task) -> dict[str, str | int]:
    payload = asdict(task)
    payload["id"] = str(task.id)
    payload["run_id"] = str(task.run_id)
    payload["state"] = task.state.value
    return payload


def serialize_event(event: WorkflowEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "run_id": str(event.run_id) if event.run_id is not None else None,
        "task_id": str(event.task_id) if event.task_id is not None else None,
        "payload": event.payload,
        "idempotency_key": event.idempotency_key,
        "correlation_id": event.correlation_id,
        "causation_id": event.causation_id,
        "schema_version": event.schema_version,
        "replayed_from_event_id": event.replayed_from_event_id,
        "created_at": event.created_at.isoformat(),
    }


def serialize_execution(record: ExecutionRecord) -> dict[str, object]:
    return {
        "id": str(record.id),
        "run_id": str(record.run_id),
        "task_id": str(record.task_id),
        "status": record.status,
        "runner_kind": record.runner_kind,
        "attempt": record.attempt,
        "phase": record.phase,
        "correlation_id": record.correlation_id,
    }


def serialize_log(record: LogRecord) -> dict[str, object]:
    return {
        "id": str(record.id),
        "run_id": str(record.run_id),
        "task_id": str(record.task_id) if record.task_id is not None else None,
        "execution_id": str(record.execution_id) if record.execution_id is not None else None,
        "level": record.level,
        "message": record.message,
    }


def serialize_unit_evidence(record: UnitEvidenceRecord) -> dict[str, object]:
    return {
        "id": str(record.id),
        "run_id": str(record.run_id),
        "task_id": str(record.task_id),
        "execution_id": str(record.execution_id),
        "status": record.status,
        "command": record.command,
        "output": record.output,
    }


def serialize_pull_request(record: PullRequestRecord) -> dict[str, object]:
    return {
        "id": str(record.id),
        "run_id": str(record.run_id),
        "title": record.title,
        "branch": record.branch,
        "status": record.status,
        "url": record.url,
    }


def serialize_ci_check(record: CiCheckRecord) -> dict[str, object]:
    return {
        "id": str(record.id),
        "run_id": str(record.run_id),
        "name": record.name,
        "status": record.status,
        "details": record.details,
    }


def serialize_approval(approval: Approval) -> dict[str, str | None]:
    payload = asdict(approval)
    payload["id"] = str(approval.id)
    payload["run_id"] = str(approval.run_id)
    payload["task_id"] = str(approval.task_id) if approval.task_id is not None else None
    return payload


def serialize_artefact(artefact: Artefact) -> dict[str, str | None]:
    payload = asdict(artefact)
    payload["id"] = str(artefact.id)
    payload["run_id"] = str(artefact.run_id)
    payload["task_id"] = str(artefact.task_id) if artefact.task_id is not None else None
    return payload


def to_run(record: RunRecord) -> Run:
    return Run(
        id=record.id,
        title=record.title,
        state=record.state,
        seeded_bootstrap_task=record.seeded_bootstrap_task,
    )


def to_task(record: TaskRecord) -> Task:
    return Task(
        id=record.id,
        run_id=record.run_id,
        name=record.name,
        state=record.state,
        retry_count=record.retry_count,
        max_retries=record.max_retries,
    )


def to_approval(record: ApprovalRecord) -> Approval:
    return Approval(
        id=record.id,
        run_id=record.run_id,
        task_id=record.task_id,
        status=record.status,
        requested_by=record.requested_by,
        decided_by=record.decided_by,
        decision_note=record.decision_note,
        scope=record.scope,
        role=record.role,
        required_approvals=record.required_approvals,
        invalidated_at=record.invalidated_at,
        invalidation_reason=record.invalidation_reason,
    )


def to_artefact(record: ArtefactRecord) -> Artefact:
    return Artefact(
        id=record.id,
        run_id=record.run_id,
        task_id=record.task_id,
        path=record.path,
        checksum=record.checksum,
        version=record.version,
        producer=record.producer,
    )
