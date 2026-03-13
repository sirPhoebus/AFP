# AFP Business Partner Overview

## Executive Summary

AFP is an orchestration platform for turning software delivery work into a governed, traceable, evidence-backed execution flow. It is designed for organizations that want more than task automation: they want a system that can plan work, coordinate execution, enforce approvals, collect evidence, and explain why a change is or is not ready to ship.

The current repository represents a working prototype with real workflow depth. It already demonstrates planning, dependency-aware task execution, approval controls, audit trails, unit evidence capture, PR/CI policy evaluation, operator APIs, and infrastructure-backed runtime paths.

## The Business Problem

Engineering organizations lose time and control in the gaps between planning, execution, approval, and release:

- planning artefacts live separately from delivery execution;
- handoffs between people, agents, and systems are hard to audit;
- approvals often exist outside the workflow they are meant to govern;
- evidence for quality gates is fragmented across tools;
- release decisions can be difficult to explain after the fact.

AFP is built to close those gaps by creating a single operating layer for governed delivery work.

## What AFP Does

AFP coordinates work across the full operational loop:

1. Turn work into structured runs, tasks, and dependency graphs.
2. Route tasks through approvals and policy gates.
3. Track execution lifecycle and collect evidence.
4. Record workflow events, logs, and decisions for auditability.
5. Evaluate whether a run is ready to advance toward merge or release.

This creates a system of record for software delivery orchestration rather than a set of disconnected scripts and dashboards.

## Demonstrated Capabilities in the Current Prototype

The current platform slice already shows:

- planning and DAG generation for structured task execution;
- dependency-aware scheduling so blocked tasks wait for prerequisites;
- persistence-backed workflow state in SQLite and Postgres;
- Redis-backed queue integration for infrastructure-backed runtime flows;
- approval-gated work with run-level and task-level approval records;
- artefact tracking and approval invalidation when governed artefacts change;
- execution lifecycle tracking with queue, start, completion, cancellation, and retry-related metadata;
- persisted workflow events and outbox events for audit and integration patterns;
- containerized unit execution with evidence capture;
- PR, CI, and merge-policy evaluation;
- operator APIs for dashboard, approval queue, run detail, and control surfaces;
- metrics, trace headers, auth hooks, config inspection, and backup-posture reporting;
- agent invocation with structured outputs and provider fallback.

## Why This Matters

For business stakeholders, AFP creates value in four areas:

### 1. Control

Critical workflow decisions become explicit. Approvals, evidence, and release decisions are attached to the work itself instead of being scattered across chat, CI logs, and spreadsheets.

### 2. Auditability

Runs, tasks, events, executions, logs, and policy decisions are recorded as durable system artifacts. This improves post-incident review, governance, and compliance reporting.

### 3. Speed With Guardrails

Teams can automate more of the delivery path without giving up oversight. AFP is intended to accelerate execution while making quality and approval gates more consistent.

### 4. Platform Leverage

Rather than adding one-off automation for each team, AFP is structured as a reusable orchestration layer that can support multiple workflows, agents, and release policies over time.

## Target Users

AFP is relevant to:

- engineering leadership looking for more predictable and governable delivery;
- platform and DevOps teams building internal developer workflow systems;
- regulated or high-assurance delivery environments that need traceability;
- organizations experimenting with agent-assisted engineering but requiring stronger controls than ad hoc tooling provides.

## Current Maturity

AFP should be understood as a serious prototype, not a production-ready commercial platform.

What that means:

- the current system proves the core operating model end to end;
- key controls and audit behaviors are real and tested;
- several product and operational surfaces are still early-stage;
- the UI is currently a shell plus JSON-backed operator APIs rather than a finished product experience.

## Roadmap Themes

The most important next-stage investments are:

- stronger production data and concurrency guarantees;
- deeper real-world agent and provider integrations;
- richer evidence ingestion and CI bridge coverage;
- a fuller operator experience;
- hardened security, tenancy, and deployment posture.

## Positioning

AFP is best positioned as:

- a governed orchestration layer for software delivery;
- a control plane for agent-assisted engineering workflows;
- a bridge between planning, execution, evidence, and release policy;
- a foundation for organizations that want automation with accountability.

## Partner Narrative

AFP helps organizations move from “automation scattered across tools” to “a governed delivery system with evidence, approvals, and traceability built in.”

That is the core story for partners:

- better operational control,
- clearer auditability,
- faster delivery with stronger guardrails,
- and a practical path toward managed agent-assisted execution.
