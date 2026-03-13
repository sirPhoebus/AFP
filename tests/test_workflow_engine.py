import unittest
from uuid import uuid4

from workflow_engine import (
    InMemoryQueue,
    LifecycleState,
    QueueEnvelope,
    apply_transition,
    drain_worker_once,
    recover_inflight_tasks,
)


class WorkflowEngineTests(unittest.TestCase):
    def test_valid_and_invalid_transitions(self):
        ok = apply_transition(LifecycleState.NEW, LifecycleState.ENRICHED)
        bad = apply_transition(LifecycleState.NEW, LifecycleState.MERGED)
        self.assertTrue(ok.valid)
        self.assertEqual(ok.reason_code, "ok")
        self.assertFalse(bad.valid)
        self.assertEqual(bad.reason_code, "illegal_transition")

    def test_queue_drain_emits_event(self):
        queue = InMemoryQueue()
        events = []
        envelope = QueueEnvelope(run_id=uuid4(), task_id=uuid4(), max_retries=4)
        queue.enqueue(envelope)

        event = drain_worker_once(queue, events.append)
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "task.execution.dequeued")
        self.assertEqual(event.payload["attempt"], 1)
        self.assertEqual(queue.size(), 0)
        self.assertEqual(len(events), 1)

    def test_nominal_transition_chain_reaches_merged(self):
        path = [
            LifecycleState.ENRICHED,
            LifecycleState.PLANNED,
            LifecycleState.AWAITING_APPROVAL,
            LifecycleState.READY,
            LifecycleState.IN_PROGRESS,
            LifecycleState.UNIT_PASS,
            LifecycleState.PR_OPEN,
            LifecycleState.INTEGRATION_PASS,
            LifecycleState.MERGED,
        ]
        state = LifecycleState.NEW

        for next_state in path:
            result = apply_transition(state, next_state)
            self.assertTrue(result.valid, f"{state} -> {next_state} should be valid")
            state = next_state

        self.assertEqual(state, LifecycleState.MERGED)

    def test_no_op_and_terminal_state_reason_codes(self):
        no_op = apply_transition(LifecycleState.READY, LifecycleState.READY)
        terminal = apply_transition(LifecycleState.MERGED, LifecycleState.FAILED)

        self.assertFalse(no_op.valid)
        self.assertEqual(no_op.reason_code, "no_op_transition_forbidden")
        self.assertFalse(terminal.valid)
        self.assertEqual(terminal.reason_code, "terminal_state")

    def test_restart_recovery_requeues_retryable_unique_tasks(self):
        queue = InMemoryQueue()
        task_id = uuid4()
        recoverable = QueueEnvelope(run_id=uuid4(), task_id=task_id, attempt=1, max_retries=3)
        duplicate = QueueEnvelope(run_id=recoverable.run_id, task_id=task_id, attempt=1, max_retries=3)
        exhausted = QueueEnvelope(run_id=uuid4(), task_id=uuid4(), attempt=3, max_retries=3)

        recovered = recover_inflight_tasks(queue, [recoverable, duplicate, exhausted])

        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].attempt, 2)
        self.assertEqual(queue.size(), 1)


if __name__ == "__main__":
    unittest.main()
