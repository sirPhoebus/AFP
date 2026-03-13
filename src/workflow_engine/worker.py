"""Queue backends and worker loop primitives for bootstrap orchestration."""

from collections import deque
from dataclasses import dataclass
from json import dumps, loads
from typing import Callable, Iterable
from uuid import UUID

from redis import Redis

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


class RedisQueue:
    """Redis-backed queue with the same interface as the in-memory queue."""

    def __init__(self, url: str, key: str = "afp:queue") -> None:
        self._redis = Redis.from_url(url, decode_responses=True)
        self._key = key

    def enqueue(self, envelope: QueueEnvelope) -> None:
        self._redis.rpush(
            self._key,
            dumps(
                {
                    "run_id": str(envelope.run_id),
                    "task_id": str(envelope.task_id),
                    "attempt": envelope.attempt,
                    "max_retries": envelope.max_retries,
                    "not_before_epoch_ms": envelope.not_before_epoch_ms,
                },
                sort_keys=True,
            ),
        )

    def dequeue(self) -> QueueEnvelope | None:
        payload = self._redis.lpop(self._key)
        if payload is None:
            return None
        item = loads(payload)
        return QueueEnvelope(
            run_id=UUID(item["run_id"]),
            task_id=UUID(item["task_id"]),
            attempt=item["attempt"],
            max_retries=item["max_retries"],
            not_before_epoch_ms=item.get("not_before_epoch_ms"),
        )

    def size(self) -> int:
        return int(self._redis.llen(self._key))

    def clear(self) -> None:
        self._redis.delete(self._key)


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
