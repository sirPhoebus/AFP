# AFP

Bootstrap implementation of an agent-factory orchestrator.

The repository currently contains a persistence-backed workflow skeleton with:
- run and task lifecycle state management;
- approval-gated task execution;
- artefact registration;
- queue recovery across restart;
- workflow event, execution, and log audit persistence;
- execution-policy checks for required skills and folder-scoped agent selection.

This is not the full product described in [docs/plan.md](/home/phoebus/repo/AFP/docs/plan.md). It is the early platform core and persistence slice that proves the workflow model and restart/idempotency behavior.

## Current Modules

- `src/orchestrator_api`
  Minimal Flask API for runs, tasks, approvals, artefacts, worker drain, and audit retrieval.
- `src/workflow_engine`
  Lifecycle enum, transition validation, queue envelope contract, worker queue, and recovery helpers.
- `src/persistence`
  SQLite schema bootstrap and repository layer for runs, tasks, approvals, artefacts, executions, logs, and workflow events.
- `src/policy_engine`
  Coding-task policy checks for required skills and folder-scoped agent selection.
- `src/agent_runner`
  Earlier worker-loop bootstrap primitives used by part of the test suite.

## Implemented API Surface

- `GET /health`
- `POST /runs`
- `GET /runs/{run_id}`
- `POST /runs/{run_id}/tasks`
- `GET /runs/{run_id}/tasks`
- `POST /runs/{run_id}/tasks/{task_id}/transition`
- `POST /runs/{run_id}/approvals`
- `GET /runs/{run_id}/approvals`
- `POST /runs/{run_id}/approvals/{approval_id}/decision`
- `POST /runs/{run_id}/artefacts`
- `GET /runs/{run_id}/artefacts`
- `POST /workers/drain-once`
- `GET /workflow-events`
- `GET /runs/{run_id}/executions`
- `GET /runs/{run_id}/logs`

## Workflow Behavior Today

- normal tasks start in `ready` and are enqueued immediately;
- approval-gated tasks start in `awaiting_approval` and are not enqueued until approved;
- approval decisions move tasks to `ready` or `needs_human`;
- worker drain moves a task to `in_progress`;
- run state is derived from the aggregate state of its tasks, not from last-writer wins;
- queue recovery reconstructs `ready` work after restart from persisted task state;
- workflow events, executions, and logs survive restart;
- duplicate recovered drains for the same attempt are idempotent.

## Development

Requirements:
- Python 3.13+
- `pip`

Install in editable mode:

```bash
python -m pip install -e .
```

Run tests:

```bash
pytest -q
```

## Repository Layout

- `agents/`
  Agent config examples and placeholders.
- `db/`
  Migration placeholder directory.
- `docs/`
  Product plan, technical plan, ADRs, and gap analysis.
- `skills/`
  Local skill inventory.
- `src/`
  Python packages for the current implementation.
- `tests/`
  Unit and workflow regression coverage.

## Current Status

What is real:
- persistence-backed workflow skeleton;
- restart recovery and idempotency coverage;
- task approval gating and aggregate run-state derivation;
- audit persistence for workflow drains.

What is still missing:
- dependency-aware task scheduling;
- real external queue and Postgres integration;
- planning pipeline and DAG generation;
- containerized execution and unit evidence ingestion;
- CI, PR validation, merge policy, and UI.

See [docs/long-term-gap-analysis.md](/home/phoebus/repo/AFP/docs/long-term-gap-analysis.md) for the longer-term gap breakdown.
