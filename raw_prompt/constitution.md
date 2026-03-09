Project: MMP-AI (Manual Payment Processing AI System)

Purpose:
The system processes manual payment instructions received as PDF documents. The system extracts relevant payment data and performs multiple validation processes (fraud check, signature verification, payee validation, rule validation, etc.) through agent-based execution. After validations complete, the payment instruction undergoes verification before being marked ready for downstream payment systems.

Architecture Principles:

The system must follow a containerized microservice architecture. All components must be deployable via Docker containers and communicate through secure service-to-service networking.

Primary stack:

* Backend: FastAPI (Python)
* Frontend: React + Vite.js with Bootstrap CSS
* Agent Framework: LangGraph
* MCP Server: fast-mcp
* Database: MongoDB
* LangGraph checkpoint persistence: MongoDB
* Programming language: Python for backend and supporting services

LLM Invocation Constraint:
All LLM interactions must be executed through HTTP REST endpoints using curl or standard HTTP requests. No provider SDKs or client libraries may be used. Model providers must remain abstracted to allow vendor flexibility.

Agentic Workflow Architecture:

All agent orchestration must follow a deterministic graph-based workflow implemented using LangGraph.

Workflows must NOT be hardcoded in the application.

Instead, a dedicated configuration layer must define:

* workflow nodes
* agent definitions
* execution edges
* conditional routing
* execution mode (parallel or sequential)
* human-in-the-loop checkpoints
* interrupt points
* retry policies
* escalation rules

A Supervisor Agent must dynamically construct workflows using this configuration.

The Supervisor Agent must not contain any hardcoded agents or workflow definitions. All orchestration logic must be derived from the configuration layer to allow workflow modifications without modifying application code.

Sub Agents:

Each agent must perform a single well-defined responsibility such as fraud analysis, signature verification, or payee validation.

Agents must:

* remain modular and loosely coupled
* access tools only through the MCP server
* remain independently testable
* support observability and tracing

Identity and Access Control:

The system must support Single Sign-On authentication integrated with enterprise Active Directory.

Authorization must be enforced using AD group-based role assignments.

Segregation of Duties (SoD) must be strictly enforced.

Even if a user has permissions for multiple roles, the system must prevent the same user from performing multiple approval stages on the same payment instruction.

The following roles must remain logically separated per payment transaction:

* Keyer (payment entry)
* Authenticator (validation confirmation)
* Verifier (final authorization)

The same user must never be allowed to act as more than one role within the lifecycle of a single payment instruction.

This enforcement must occur at the application logic level and must be auditable.

External Event Triggers:

The architecture must support external ingestion mechanisms.

File Intake Service:
A component must monitor a network drive and automatically copy newly detected payment instruction files into an Amazon S3 bucket.

Processing Trigger:
An event-driven trigger (e.g., AWS Lambda) must detect new files in S3 and invoke the MMP processing engine.

These components may exist outside the main processing engine but must follow the same engineering and security standards.

Observability:

The system must implement full observability using:

* OpenTelemetry
* Prometheus
* Grafana

Services must expose:

* structured logs
* distributed traces
* operational metrics
* health check endpoints

Trace propagation must be supported across services and agent workflows.

Testing Strategy:

The project must follow Behavior Driven Development (BDD).

Testing must follow the Testing Pyramid model including:

* unit tests
* integration tests
* API tests
* agent workflow tests
* end-to-end tests

Backend testing must use Pytest.

Frontend testing must use Vitest.

Tests must be automated within CI pipelines.

Security and Container Communication:

All container communication must be secure and authenticated.

Secrets must never be stored in source code and must be retrieved from secure secret management systems.

Services must validate all external inputs and maintain audit logs for critical payment operations.

Code Quality Principles:

The system must enforce modular architecture, clear service boundaries, strong error handling, and consistent API design.

APIs must be versioned and documented.

Critical payment processing actions must be traceable and auditable.

Governance:

All specifications, implementation tasks, and code changes must comply with this constitution. Any new architecture or workflow proposal must adhere to these principles unless formally amended through repository governance.
