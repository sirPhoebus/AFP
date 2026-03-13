# Long-Term Gap Analysis

This document compares the current repository state to the intended system described in `docs/plan.md` and `docs/technical-plan.md`.

It is intentionally blunt. The repo now proves a useful workflow core, but it is still far from the full agent-factory platform.

## 1. Current Baseline

The current codebase has working slices in four areas.

### Platform Core

- persisted `runs`, `tasks`, `approvals`, `artefacts`, `executions`, `logs`, `workflow_events`, `eval_runs`, and `policy_decisions` schema bootstrap in SQLite;
- lifecycle enum and legal transition validation;
- run/task creation and retrieval APIs;
- task approval gating and approval decision flow;
- aggregate run-state derivation across multiple tasks;
- worker drain path that persists workflow events, execution records, and logs.

### Recovery and Auditability

- `ready` tasks are reconstructed into the in-memory queue after restart;
- workflow events survive restart;
- execution and log records survive restart;
- duplicate recovered drains are idempotent for the same task attempt.

### Policy

- required-skill checks for coding tasks;
- folder-scoped agent selection checks;
- machine-readable rejection reason codes for policy failures.

### Test Coverage

- state machine behavior;
- API flow for runs/tasks;
- approval and artefact APIs;
- persistence schema creation;
- restart recovery;
- event/audit persistence;
- duplicate-drain idempotency.

## 2. What Is Still Missing

These gaps are ordered by product significance, not by implementation ease.

## 2.1 Planning and Orchestration Gaps

The product vision starts with enrichment, architecture, master planning, delegated task plans, and human review of those artefacts. None of that exists in the code yet.

Missing:
- requirements enrichment artefact generation;
- architecture artefact generation;
- master plan DAG generation;
- delegated task-plan templating and storage;
- dependency-aware workflow scheduling from a DAG;
- explicit blocker/open-question modelling from planning stages.

Impact:
- the current system can execute a task workflow shell, but it cannot yet turn a vague request into a structured, approval-ready work graph.

## 2.2 Dependency and Scheduling Gaps

The code now handles multiple tasks, but not true orchestration dependencies.

Missing:
- enforcement of `task_dependencies` before a task becomes `ready`;
- automatic promotion of dependent tasks once prerequisites complete;
- scheduling strategy for breadth, depth, retries, and priority;
- detection of dependency cycles and invalid DAGs;
- run-level completion logic that considers dependency closure, not just task states.

Impact:
- a task can still be marked `ready` even when another task should logically block it.

## 2.3 Execution Runtime Gaps

The current worker path is deliberately synthetic.

Missing:
- real task execution adapters;
- isolated pod or job execution;
- manifest generation for executor jobs;
- containerized unit-test execution;
- stdout/stderr capture beyond the current synthetic audit log;
- timeout, cancel, retry delay, and backoff policy;
- distinction between queue dequeue, execution start, execution completion, and execution failure.

Impact:
- the system proves orchestration mechanics, not real code execution.

## 2.4 Evidence and Quality-Gate Gaps

The long-term plan requires deterministic evidence-backed promotion between stages.

Missing:
- unit-test evidence ingestion tied to task completion;
- integration-test evidence ingestion;
- eval run ingestion tied to acceptance criteria;
- coverage thresholds and quality bars;
- policy decisions that consume evidence records rather than just workflow state;
- block reasons tied to missing or invalid evidence.

Impact:
- the platform cannot yet enforce “no merge without evidence.”

## 2.5 Merge and PR Workflow Gaps

The planned product culminates in PR validation and merge recommendation. That does not exist yet.

Missing:
- branch and PR creation workflow;
- CI provider bridge;
- synchronization of external check state;
- merge recommendation policy endpoint;
- PR risk classification;
- generated PR description and reviewer checklist;
- merge gating based on approvals + evidence + CI state.

Impact:
- the current system stops well before the actual prove-to-merge loop.

## 2.6 Data and Persistence Gaps

SQLite bootstrap was the right local proving ground, but it is not the intended production persistence layer.

Missing:
- actual migrations under `db/migrations/`;
- Postgres-first schema management;
- indexes and constraints for production query patterns;
- transactional boundaries around multi-record workflow operations;
- optimistic locking or revision tracking for concurrent workers;
- retention and archival strategy for events/logs/executions;
- schema versioning policy.

Impact:
- persistence is good enough for local proof, not for multi-actor production operation.

## 2.7 Event Model Gaps

Events are now persisted, which closes an important audit gap, but the event model is still narrow.

Missing:
- richer event taxonomy across planning, approval, execution, retry, and merge phases;
- correlation and causation chains across events;
- event replay semantics;
- event deduplication strategy beyond drain idempotency;
- outbox or event-bus integration if the system becomes multi-service;
- versioned event payload contracts.

Impact:
- auditability is present, but event-driven coordination is still immature.

## 2.8 Approval Model Gaps

Approvals now matter for task progression, but the model is still minimal.

Missing:
- run-level approvals distinct from task-level approvals;
- approval policies by role, stage, or risk;
- multiple required approvers;
- approval expiration or invalidation when artefacts change;
- approval visibility and audit enrichment;
- enforcement that certain stages cannot advance without specific approval types.

Impact:
- approval gating works, but only as a basic yes/no mechanism.

## 2.9 UI and Operator Experience Gaps

The intended UI is almost entirely absent.

Missing:
- dashboard for runs;
- run detail page;
- task graph visualization;
- approval queue;
- log and evidence viewer;
- artefact diff viewer;
- operator controls for retry, pause, resume, cancel, and stop.

Impact:
- the platform is currently API/test driven only.

## 2.10 Agent-System Gaps

The end vision centers on orchestrating specialized agents. The current codebase only contains config files and policy checks.

Missing:
- agent registry loading and validation;
- prompt/template management;
- agent selection logic from task type;
- memory/context model for agents;
- actual invocation of external model providers;
- structured response validation from agents;
- failure and fallback strategy across agent classes.

Impact:
- the “agent-factory” part is still mostly aspirational.

## 2.11 Operational Gaps

The current code is not yet production-operable.

Missing:
- metrics for queue depth, retries, failures, and throughput;
- tracing and correlation IDs;
- health beyond basic process liveness;
- concurrency safety across multiple workers;
- configuration system and environment handling;
- authentication and authorization;
- secret management;
- backup and restore posture.

Impact:
- the system is not ready for real multi-user or multi-worker deployment.

## 3. Architectural Risks If Left Unaddressed

These are the highest-value long-term risks.

### 3.1 State Drift Between Run and Task Aggregation

Risk:
- run state can become misleading if aggregation rules, legal transitions, and future dependency logic evolve independently.

Mitigation:
- extract a dedicated run-state derivation policy module with explicit tests and ADR coverage.

### 3.2 Queue Semantics Diverging From Persisted State

Risk:
- in-memory queue behavior can drift from persisted task truth as retries, time delays, and dependency release logic become more complex.

Mitigation:
- move toward a persisted queue contract or external queue with strong reconciliation rules.

### 3.3 Synthetic Worker Semantics Hardening Into the Wrong Abstraction

Risk:
- the current drain model is intentionally simple and may become a constraint if real executions require richer lifecycles.

Mitigation:
- introduce explicit execution phases before layering in real runners.

### 3.4 Approval Semantics Remaining Too Weak

Risk:
- future stages may appear governed while still allowing incomplete or stale approvals.

Mitigation:
- design approval types, role rules, and invalidation semantics before UI/merge work.

## 4. Recommended Long-Term Sequence

If this project continues, the next sequence should be:

1. Task dependency enforcement and scheduler readiness rules.
2. Explicit execution lifecycle model: dequeued, started, succeeded, failed, retried.
3. Unit-evidence ingestion and gating for task completion.
4. Postgres migrations and migration tooling.
5. Planning pipeline artefacts and DAG generation.
6. UI shell for run detail, approvals, logs, and DAG visibility.
7. CI bridge, PR validation, and merge policy.

This order keeps the system honest: dependency correctness and execution truth should come before UI polish or merge automation.

## 5. Near-Term “Definition of Real”

The platform crosses from bootstrap to meaningfully real when all of the following are true:

- dependencies determine task readiness;
- tasks execute in an isolated runtime, not a synthetic drain;
- unit evidence is required to advance execution stages;
- approvals are policy-driven, not just stored and manually decided;
- run state is fully derived from dependency-aware task truth;
- audit records survive restart and support operator investigation;
- operators can inspect and control runs through a UI.

Until then, this repo should be treated as a strong workflow-core prototype, not a finished orchestrator.
