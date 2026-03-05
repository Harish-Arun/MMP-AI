<!--
Sync Impact Report
===================
Version change: N/A → 1.0.0
Modified principles: N/A (initial creation)
Added sections:
  - Core Principles (10 principles)
  - Technology Stack
  - Development Workflow
  - Governance
Removed sections: N/A
Templates requiring updates:
  - .specify/templates/plan-template.md ✅ no changes needed
    (uses dynamic "Constitution Check" gate)
  - .specify/templates/spec-template.md ✅ no changes needed
    (generic placeholder-driven)
  - .specify/templates/tasks-template.md ✅ no changes needed
    (generic placeholder-driven)
  - .specify/templates/checklist-template.md ✅ no changes needed
  - .specify/templates/agent-file-template.md ✅ no changes needed
  - .specify/templates/commands/ — no command files present
Follow-up TODOs: None
-->

# MMP-AI Constitution

## Core Principles

### I. Containerized Microservice Architecture

All system components MUST follow a containerized microservice
architecture. Every service MUST be deployable as an independent
Docker container. Services MUST communicate through secure
service-to-service networking. The entire system MUST be
orchestratable via Docker Compose (or equivalent container
orchestration). No service may assume co-location with another
service at runtime.

**Rationale:** Containerization enforces clear service boundaries,
enables independent scaling, and ensures consistent deployment
across environments.

### II. SDK-Free LLM Integration

All LLM interactions MUST be executed through HTTP REST endpoints
using standard HTTP requests (e.g., curl or language-native HTTP
clients). No provider SDKs or client libraries may be used for
LLM invocation. Model providers MUST remain abstracted behind a
common interface to allow vendor flexibility without code changes.

**Rationale:** Avoiding SDK lock-in ensures the system can switch
LLM providers without rewriting integration code and eliminates
transitive dependency risks from third-party client libraries.

### III. Configuration-Driven Agentic Workflows

All agent orchestration MUST follow a deterministic graph-based
workflow implemented using LangGraph. Workflows MUST NOT be
hardcoded in application code. A dedicated configuration layer
MUST define:

- Workflow nodes and agent definitions
- Execution edges and conditional routing
- Execution mode (parallel or sequential)
- Human-in-the-loop checkpoints and interrupt points
- Retry policies and escalation rules

A Supervisor Agent MUST dynamically construct workflows from this
configuration. The Supervisor Agent MUST NOT contain hardcoded
agents or workflow definitions. All orchestration logic MUST be
derived from configuration to allow workflow modifications without
application code changes.

**Rationale:** Configuration-driven workflows enable business
users and operators to modify processing logic without developer
intervention, reducing change risk and deployment cycles.

### IV. Single-Responsibility Sub-Agents

Each agent MUST perform exactly one well-defined responsibility
(e.g., fraud analysis, signature verification, payee validation).
Agents MUST:

- Remain modular and loosely coupled
- Access tools only through the MCP server (fast-mcp)
- Remain independently testable
- Support observability and distributed tracing

No agent may combine multiple validation concerns into a single
execution unit.

**Rationale:** Single-responsibility agents are easier to test,
replace, and scale independently. MCP-only tool access enforces
a uniform integration contract.

### V. Segregation of Duties & Access Control

The system MUST support Single Sign-On (SSO) authentication
integrated with enterprise Active Directory. Authorization MUST
be enforced using AD group-based role assignments. Segregation of
Duties (SoD) MUST be strictly enforced at the application logic
level and MUST be auditable.

The following roles MUST remain logically separated per payment
transaction:

- **Keyer** — payment entry
- **Authenticator** — validation confirmation
- **Verifier** — final authorization

The same user MUST NOT act as more than one role within the
lifecycle of a single payment instruction, even if that user holds
permissions for multiple roles.

**Rationale:** Segregation of duties is a regulatory and fraud
prevention requirement for payment processing. Application-level
enforcement ensures compliance independent of infrastructure
configuration.

### VI. Event-Driven External Ingestion

The architecture MUST support external ingestion mechanisms:

- A **File Intake Service** MUST monitor a network drive and
  automatically copy newly detected payment instruction files
  into an Amazon S3 bucket.
- A **Processing Trigger** (e.g., AWS Lambda) MUST detect new
  files in S3 and invoke the MMP processing engine.

These components may exist outside the main processing engine but
MUST follow the same engineering and security standards defined in
this constitution.

**Rationale:** Event-driven ingestion decouples file arrival from
processing, enabling reliable asynchronous handling and
integration with enterprise file transfer infrastructure.

### VII. Full-Stack Observability

The system MUST implement full observability using:

- **OpenTelemetry** for instrumentation
- **Prometheus** for metrics collection
- **Grafana** for visualization and alerting

All services MUST expose:

- Structured logs (JSON format)
- Distributed traces with cross-service propagation
- Operational metrics
- Health check endpoints (liveness and readiness)

Trace propagation MUST be supported across services and agent
workflows to enable end-to-end request tracing.

**Rationale:** Payment processing systems require comprehensive
observability for incident response, performance analysis, and
regulatory audit trails.

### VIII. Behavior-Driven Testing

The project MUST follow Behavior-Driven Development (BDD).
Testing MUST follow the Testing Pyramid model including:

- Unit tests
- Integration tests
- API tests
- Agent workflow tests
- End-to-end tests

Backend testing MUST use **Pytest**. Frontend testing MUST use
**Vitest**. All tests MUST be automated within CI pipelines. No
feature may be considered complete without passing automated tests
at the appropriate pyramid level.

**Rationale:** BDD ensures specifications are executable and
verifiable. The testing pyramid prevents over-reliance on slow
end-to-end tests while maintaining confidence through layered
coverage.

### IX. Security by Design

All container-to-container communication MUST be secure and
authenticated. Secrets MUST NOT be stored in source code and MUST
be retrieved from secure secret management systems. Services MUST
validate all external inputs. Audit logs MUST be maintained for
all critical payment processing operations.

**Rationale:** Financial payment systems are high-value targets.
Security controls must be architectural requirements, not
afterthoughts applied during review.

### X. Code Quality & API Governance

The system MUST enforce modular architecture, clear service
boundaries, strong error handling, and consistent API design.
All APIs MUST be versioned and documented. Critical payment
processing actions MUST be traceable and auditable. Code changes
MUST maintain existing service contracts unless explicitly
versioned through a breaking-change process.

**Rationale:** Consistent API governance prevents integration
failures across microservices and ensures backward compatibility
for downstream payment systems.

## Technology Stack

The following technology choices are non-negotiable for this
project:

| Layer | Technology |
|---|---|
| Backend API | FastAPI (Python) |
| Frontend | React + Vite.js with Bootstrap CSS |
| Agent Framework | LangGraph |
| MCP Server | fast-mcp |
| Database | MongoDB |
| Checkpoint Persistence | MongoDB (LangGraph checkpoints) |
| Backend Language | Python (all backend and supporting services) |
| Container Orchestration | Docker / Docker Compose |
| Observability | OpenTelemetry + Prometheus + Grafana |
| Backend Testing | Pytest |
| Frontend Testing | Vitest |

Any deviation from this stack MUST be formally proposed and
approved through the governance amendment process before
implementation.

## Development Workflow

All development MUST follow these workflow requirements:

- **Specifications first**: Every feature MUST begin with a
  specification (spec.md) and implementation plan (plan.md)
  before coding begins.
- **Constitution compliance gate**: Every plan MUST pass a
  Constitution Check verifying alignment with all ten
  principles before implementation proceeds.
- **BDD cycle**: Acceptance scenarios MUST be defined before
  implementation. Tests MUST be written and verified to fail
  before feature code is written.
- **CI automation**: All tests, linting, and security scans
  MUST execute in CI pipelines. No merge to main without
  passing CI.
- **Code review**: All changes MUST be reviewed for compliance
  with this constitution, security requirements, and SoD
  constraints.
- **Audit trail**: All payment-critical code changes MUST
  include traceability to the originating specification and
  approval chain.

## Governance

This constitution supersedes all other development practices and
guidelines for the MMP-AI project. All specifications,
implementation tasks, and code changes MUST comply with this
constitution.

**Amendment procedure:**

1. Any team member may propose an amendment by submitting a
   documented change request referencing specific principle
   numbers.
2. Amendments MUST include rationale, impact analysis, and a
   migration plan for existing code.
3. Amendments MUST be reviewed and approved by the project lead
   and at least one additional senior engineer.
4. Approved amendments MUST be reflected in an updated version
   of this constitution before implementation begins.

**Versioning policy:**

- MAJOR version: Removal or backward-incompatible redefinition
  of a principle.
- MINOR version: New principle or materially expanded guidance.
- PATCH version: Clarifications, wording fixes, non-semantic
  refinements.

**Compliance review:**

- All pull requests MUST include a self-attestation of
  constitution compliance.
- Quarterly compliance reviews SHOULD be conducted to verify
  adherence across the codebase.
- Violations discovered in review MUST be tracked as
  remediation tasks with assigned owners and deadlines.

Use `.specify/memory/constitution.md` as the authoritative source
for all governance decisions.

**Version**: 1.0.0 | **Ratified**: 2026-03-05 | **Last Amended**: 2026-03-05
