"""Minimal in-memory queue + worker loop for Milestone A bootstrap."""

from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterable

from .events import QueueEnvelope, WorkflowEvent


@dataclass
class InMemoryQueue:
    _items: deque[QueueEnvelope]

    def __init__(self) -> None:
        self._items = deque()

    def enqueue(self, envelope: QueueEnvelope) -> None:
        self._items.append(envelope)

    def dequeue(self) -> QueueEnvelope | None:
        if not self._items:
            return None

        return self._items.popleft()

    def size(self) -> int:
        return len(self._items)


def drain_worker_once(
    queue: InMemoryQueue,
    emit_event: Callable[[WorkflowEvent], None],
) -> WorkflowEvent | None:
    """Consume one queue message and emit a workflow transition event."""
    envelope = queue.dequeue()
    if envelope is None:
        return None

    event = WorkflowEvent(
        event_type="task.execution.dequeued",
        run_id=envelope.run_id,
        task_id=envelope.task_id,
        payload={
            "attempt": envelope.attempt,
            "max_retries": envelope.max_retries,
            "not_before_epoch_ms": envelope.not_before_epoch_ms,
        },
        idempotency_key=f"{envelope.task_id}:{envelope.attempt}",
    )
    emit_event(event)
    return event


def recover_inflight_tasks(
    queue: InMemoryQueue,
    inflight_envelopes: Iterable[QueueEnvelope],
) -> list[QueueEnvelope]:
    """Requeue unique retryable envelopes after a worker restart."""
    recovered: list[QueueEnvelope] = []
    seen_task_ids: set[str] = set()

    for envelope in inflight_envelopes:
        task_id = str(envelope.task_id)
        if task_id in seen_task_ids or not envelope.can_retry():
            continue

        next_envelope = envelope.next_attempt()
        queue.enqueue(next_envelope)
        recovered.append(next_envelope)
        seen_task_ids.add(task_id)

    return recovered
