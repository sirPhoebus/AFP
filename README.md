# AFP

Agent-factory orchestration platform prototype.

This repository now contains a tested vertical slice of the platform described in [plan.md](/home/phoebus/repo/AFP/docs/plan.md) and [technical-plan.md](/home/phoebus/repo/AFP/docs/technical-plan.md). It is still not a finished production system, but it is no longer just a bootstrap scaffold. The current codebase supports planning, dependency-aware task execution, approvals, persistence, audit trails, operator APIs, and infrastructure-backed runtime paths.

## What Exists Today

- persistence-backed run, task, approval, artefact, execution, log, event, evidence, PR, and CI data models;
- SQLite and Postgres repository backends;
- in-memory and Redis queue backends;
- migration registration and schema/index bootstrap under [db/migrations](/home/phoebus/repo/AFP/db/migrations/001_core_schema.sql#L1);
- dependency-aware task scheduling with DAG generation and dependent-task promotion;
- approval-gated tasks plus run-level and task-level approval records;
- artefact registration with approval invalidation on artefact changes;
- restart recovery for persisted `ready` tasks;
- persisted workflow events, outbox events, executions, logs, and unit evidence;
- explicit dequeue, start, complete, retry-ready, and cancel execution surfaces;
- containerized unit execution and evidence ingestion;
- merge-policy evaluation using approvals, unit evidence, CI checks, and PR presence;
- operator-facing dashboard/detail/approval-queue/control APIs;
- agent registry and structured provider/fallback invocation path;
- auth, trace headers, metrics, config inspection, and backup-posture endpoints.

## Module Layout

- `src/orchestrator_api`
  Flask API entrypoint, runtime assembly, route registration, orchestration services, agent registry, and config handling.
- `src/persistence`
  Schema bootstrap, migration registration, shared records, reset facade, and SQLite/Postgres repository backends.
- `src/workflow_engine`
  Lifecycle model, state transition validation, queue envelope and workflow event contracts, and queue backends.
- `src/planning`
  Planning/DAG rendering helpers for master-plan task creation.
- `src/execution`
  Container execution adapter used for unit evidence ingestion.
- `src/policy_engine`
  Execution-policy checks around skills and folder-scoped agent selection.
- `src/ui`
  Static UI shell plus JSON endpoints used by the operator experience.

## Implemented API Surface

Core workflow:
- `GET /health`
- `GET /runs`
- `POST /runs`
- `GET /runs/{run_id}`
- `POST /runs/{run_id}/tasks`
- `GET /runs/{run_id}/tasks`
- `GET /runs/{run_id}/dag`
- `POST /runs/{run_id}/plan`
- `POST /runs/{run_id}/tasks/{task_id}/transition`

Approvals and artefacts:
- `POST /runs/{run_id}/approvals`
- `GET /runs/{run_id}/approvals`
- `POST /runs/{run_id}/approvals/{approval_id}/decision`
- `POST /runs/{run_id}/artefacts`
- `GET /runs/{run_id}/artefacts`

Execution and audit:
- `POST /workers/drain-once`
- `POST /workers/dequeue-once`
- `POST /workers/executions/{execution_id}/start`
- `POST /workers/executions/{execution_id}/complete`
- `POST /workers/tasks/{task_id}/cancel`
- `POST /runs/{run_id}/tasks/{task_id}/execute-unit`
- `GET /workflow-events`
- `POST /workflow-events/replay`
- `GET /outbox-events`
- `GET /runs/{run_id}/executions`
- `GET /runs/{run_id}/logs`
- `GET /runs/{run_id}/unit-evidence`

PR / CI / policy:
- `POST /runs/{run_id}/pull-requests`
- `GET /runs/{run_id}/pull-requests`
- `POST /runs/{run_id}/ci-checks`
- `GET /runs/{run_id}/ci-checks`
- `POST /runs/{run_id}/merge-policy/evaluate`
- `GET /runs/{run_id}/policy-decisions`

Operator and platform ops:
- `GET /ui`
- `GET /ui/styles.css`
- `GET /ui/app.js`
- `GET /ui/api/dashboard`
- `GET /ui/api/approvals/queue`
- `GET /ui/api/runs/{run_id}/detail`
- `POST /ui/api/runs/{run_id}/controls`
- `GET /agents`
- `POST /runs/{run_id}/tasks/{task_id}/invoke-agent`
- `GET /metrics`
- `GET /ops/config`
- `GET /ops/backup-posture`

## Workflow Behavior

- tasks can start as `ready`, `blocked`, or `awaiting_approval`;
- DAG planning persists task dependencies and promotes dependents when prerequisites reach acceptable completion states;
- task approvals and run approvals are stored separately and can influence advancement;
- approvals must start `pending` and be resolved through the dedicated decision endpoint;
- task claims are persisted to reduce multi-worker collision risk;
- dequeues emit persisted workflow events and outbox records;
- restart recovery rebuilds queue state from persisted `ready` tasks;
- container execution writes execution records, unit evidence, and audit events;
- merge policy remains blocked until approvals, evidence, CI checks, and PR records meet the rule set.

## Development

Requirements:
- Python 3.13+
- `pip`
- Docker for the Postgres/Redis integration path

Install:

```bash
python -m pip install -e .
```

Run tests:

```bash
pytest -q
```

Run the infrastructure-backed integration stack:

```bash
docker compose -f docker-compose.integration.yml up -d
```

## Repository Layout

- `agents/`
  Agent examples and placeholders.
- `db/`
  Migration and schema bootstrap assets.
- `docs/`
  Product plan, technical plan, UI mockup, work items, and gap analysis.
- `src/`
  Python packages for the current implementation.
- `tests/`
  Regression and integration coverage.

## Current Status

What is materially implemented:
- orchestration API and runtime assembly;
- Postgres/Redis-backed runtime path;
- planning and DAG creation;
- dependency-aware scheduling;
- approval gating and invalidation;
- execution lifecycle and event/outbox persistence;
- unit evidence ingestion;
- PR / CI / merge-policy slice;
- operator APIs and a UI shell;
- agent invocation with provider fallback;
- auth, tracing, metrics, and backup-posture surfaces.

What is still incomplete relative to a production platform:
- deeper transaction and locking guarantees across all workflow mutations;
- mature queue scheduling semantics for delays, priorities, and scale-out workers;
- richer real-world agent/provider integrations;
- a fully built operator application instead of a shell plus JSON APIs;
- stronger security, tenancy, secrets, and deployment posture;
- broader evidence, eval, and CI bridge integrations.

See [docs/long-term-gap-analysis.md](/home/phoebus/repo/AFP/docs/long-term-gap-analysis.md#L1) for the remaining long-term gaps.
