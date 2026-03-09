# Feature Specification: MMP AI Engine Boilerplate

**Feature Branch**: `002-engine-boilerplate`
**Created**: 2026-03-09
**Status**: Draft
**Input**: User description: "mmp-ai-engine-boilerplate this project will be our entire engine that handles the workflow and invoke respective tools. we have planned to have two containers. 1. agents + api services: responsible for entire workflow lifecycle (start, stop, resume), handle feedback, persist in checkpointer and a project level collection. 2. mcp tools services: responsible for holding all AI-related and non-AI-related scripts which will assist the agents for its task. We need different config files like app, business level, model-config, etc."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Config-Driven Workflow Lifecycle Management (Priority: P1)

A developer or operator interacts with the engine through the API service to start, stop, or resume a document processing workflow. When a workflow is started, the agents service reads the workflow definition from configuration — there is no hardcoded step topology in the agents code. The engine dynamically assembles the workflow graph at runtime from that config, executes it, persists state in a checkpointer after every step, and records each step verbosely in the project-level collection so that progress can be tracked in real time.

**Why this priority**: This is the foundational capability of the engine — without reliable workflow lifecycle management, no document processing can occur. Every other capability builds on top of this.

**Independent Test**: Can be tested by starting a workflow via the API, interrupting it mid-run, then resuming it and confirming it completes from the correct step. Delivers a standalone viable engine capable of processing documents end-to-end.

**Acceptance Scenarios**:

1. **Given** the agents & API service container is running and a valid workflow definition exists in config, **When** a start-workflow request is submitted with a document reference, **Then** the engine reads the config, dynamically builds the workflow, begins execution, and returns a workflow ID
2. **Given** a workflow is in progress, **When** a stop request is submitted with the workflow ID, **Then** the workflow halts cleanly and its state is persisted in the checkpointer
3. **Given** a stopped or interrupted workflow exists in the checkpointer, **When** a resume request is submitted with the workflow ID, **Then** the workflow continues from the last persisted checkpoint without re-executing completed steps
4. **Given** a workflow completes successfully, **When** execution finishes, **Then** the result is persisted in the project-level collection and the workflow ID is marked complete

---

### User Story 2 - Human Feedback Handling within a Workflow (Priority: P2)

During a workflow run, the engine reaches a step that requires human review — for example, confirming an extracted field or approving a signature match. The workflow pauses, the operator provides feedback via the API, and the workflow resumes incorporating that feedback to continue processing.

**Why this priority**: Human-in-the-loop capability is a core design requirement of the engine. Without it, the system cannot handle cases where automated confidence is insufficient and human judgment is required.

**Independent Test**: Can be tested by triggering a workflow that reaches a feedback-required step, submitting a feedback payload via the API, and confirming the workflow resumes and reflects the feedback in subsequent steps and the final output.

**Acceptance Scenarios**:

1. **Given** a workflow reaches a step requiring human input, **When** the engine detects the feedback requirement, **Then** the workflow pauses and a pending-feedback status is returned via the API
2. **Given** a workflow is paused for feedback, **When** an operator submits a feedback response via the API, **Then** the workflow resumes from the feedback step with the operator's input incorporated
3. **Given** a feedback response is submitted, **When** the workflow resumes, **Then** the feedback payload is persisted alongside the workflow record in the project-level collection
4. **Given** no feedback is received within the defined timeout window, **When** the timeout elapses, **Then** the workflow is marked as awaiting-feedback and remains pausable until feedback arrives — it does not fail automatically

---

### User Story 3 - MCP Tools Service Provides AI and Non-AI Capabilities to Agents (Priority: P2)

An agent running in the agents service needs to perform a task — such as extracting data from a document, running OCR, detecting signatures, or fetching reference data. The agent calls the MCP tools service, which hosts the relevant tool scripts and returns the result. The agent uses this result to advance the workflow.

**Why this priority**: The tools service is the engine's capability layer. Without it, agents cannot perform any meaningful operations on documents. It is co-equal in priority with feedback handling because both are needed for a complete workflow.

**Independent Test**: Can be tested by running the MCP tools service container in isolation and invoking individual tool endpoints (e.g., extraction, OCR, signature detection) with sample inputs, confirming correct outputs without requiring the agents service to be running.

**Acceptance Scenarios**:

1. **Given** the MCP tools service container is running, **When** an agent invokes an AI-related tool (e.g., document extraction, signature detection), **Then** the tool executes the appropriate script and returns a structured result
2. **Given** the MCP tools service container is running, **When** an agent invokes a non-AI tool (e.g., file type validation, reference data lookup), **Then** the tool executes and returns the result
3. **Given** a tool script encounters an error (e.g., unreadable document), **When** the error occurs, **Then** the tools service returns a structured error response that the agent can handle gracefully
4. **Given** a new tool script is added to the tools service, **When** the container is restarted, **Then** the new tool is available for agents to invoke without changes to the agents service

---

### User Story 4 - Configuration-Driven Behaviour and Workflow Definition (Priority: P3)

A developer sets up the engine for a new environment — or defines a new document processing workflow — by editing configuration files alone. Config covers application settings, business rules, model parameters, and critically the workflow definition itself (steps, order, tool assignments, feedback gates). No code changes are required to change what the workflow does or add new steps.

**Why this priority**: Configuration-driven workflow construction is the differentiating design decision for this engine. It allows the workflow topology to be modified, extended, or replaced without developer involvement. Combined with environment-portable config, it also prevents hard-coded values from proliferating across services.

**Independent Test**: Can be tested by modifying the workflow definition config to add or remove a step, restarting the agents service, starting a workflow, and confirming the engine executes exactly the steps declared in the updated config — without any code changes.

**Acceptance Scenarios**:

1. **Given** app config, business config, model config, and workflow definition config files are present, **When** the agents service starts, **Then** it reads and applies all configuration values before accepting requests
2. **Given** a required config value is missing or malformed, **When** the container starts, **Then** it fails to start with a clear error message identifying the missing or invalid value
3. **Given** a workflow definition config is present, **When** a workflow is started, **Then** the engine constructs the workflow graph entirely from that config — no step name, step order, tool assignment, or feedback gate is hardcoded in the agents code
4. **Given** the workflow definition config is updated to add a new step that calls a registered MCP tool, **When** the agents service is restarted and a new workflow is started, **Then** the new step is included in execution
5. **Given** model configuration (e.g., confidence thresholds, model selection parameters) is changed, **When** the container is restarted, **Then** subsequent AI tool calls use the updated model configuration

---

### Edge Cases

- What happens if the checkpointer storage becomes unavailable mid-workflow?
- What happens if the MCP tools service is unreachable when an agent attempts a tool call?
- How does the engine behave if the same workflow ID is submitted twice for start?
- What happens if the workflow definition config references a tool name that does not exist in the MCP tools service — does the engine fail to start, fail at the step, or skip the unknown step?
- What happens if the workflow definition config is syntactically valid but defines zero steps?
- What happens if a config file is present but contains syntactically valid but semantically invalid values (e.g., negative confidence threshold)?
- How does the system handle a workflow that is submitted while an identical workflow is already running for the same document?
- What happens if a tool script takes significantly longer than expected (hung process)?
- How are secrets (credentials, API keys referenced by tools) handled — are they in config files or injected separately?
- What happens if writing a StepEvent to the project-level collection fails mid-workflow — does the workflow halt, continue without that record, or retry the write?
- If two frontend clients are polling the step-event API for the same workflow simultaneously, does the system guarantee consistent read ordering of step events?

## Requirements *(mandatory)*

### Functional Requirements

**Agents & API Service**

- **FR-001**: The agents service MUST expose an API that allows callers to start, stop, and resume workflows by workflow ID; the workflow graph executed MUST be assembled dynamically at runtime from the workflow definition config — no workflow topology (step names, step order, tool assignments, feedback gates) shall be hardcoded in the agents or workflow module code
- **FR-002**: The agents service MUST persist workflow execution state in a checkpointer after every significant step, enabling resume from the last checkpoint
- **FR-003**: The agents service MUST persist a verbose step-level event record to the project-level collection at the completion of every workflow step (not only at workflow completion), capturing the step name, inputs, outputs, status, and timestamp
- **FR-003a**: The API MUST expose an endpoint to query the step-level event stream for a given workflow ID, returning all recorded steps in chronological order, so that a frontend can poll or subscribe to display real-time workflow progress
- **FR-004**: The agents service MUST support human-in-the-loop feedback by pausing workflows at designated steps and accepting feedback payloads via the API
- **FR-005**: The agents service MUST incorporate submitted feedback into the workflow state before resuming, and persist the feedback alongside the workflow record
- **FR-006**: The agents service MUST return a structured status response for any workflow ID, including: current state (running, paused, awaiting-feedback, complete, failed), last checkpoint, and any pending actions
- **FR-007**: The agents service MUST delegate tool execution to the MCP tools service and must not embed tool logic directly

**MCP Tools Service**

- **FR-008**: The MCP tools service MUST host all AI-related tool scripts (e.g., document extraction, OCR, signature detection, verification) as independently invocable capabilities
- **FR-009**: The MCP tools service MUST host all non-AI tool scripts (e.g., file utilities, reference data lookups, validation helpers) as independently invocable capabilities
- **FR-010**: The MCP tools service MUST return structured, consistent response envelopes from all tools (result payload, status, error detail if applicable)
- **FR-011**: The MCP tools service MUST be extensible — new tool scripts can be added and made available without modifying the agents service or API contracts

**Configuration**

- **FR-012**: Both containers MUST load configuration at startup from separate, externally mounted config files covering at minimum: application settings, business-level rules, model configuration, and (for the agents service) a workflow definition config that declares the complete step topology
- **FR-013**: Both containers MUST validate all required configuration values at startup and refuse to start if required values are absent or invalid, emitting a clear error
- **FR-014**: Configuration MUST be environment-portable — the same container images run in dev, staging, and production by swapping config files only, with no code changes

**Project Structure**

- **FR-015**: The project MUST be structured as a single repository containing both service definitions, shared configuration schemas, and any shared libraries used by both containers
- **FR-016**: The two services (agents+API and MCP tools) MUST be independently deployable — either can be restarted or scaled without requiring the other to restart [NEEDS CLARIFICATION: should the two containers communicate directly (e.g., via HTTP/gRPC between containers) or through an intermediary such as a message queue or shared storage? This defines the coupling model and affects independent deployability guarantees]
- **FR-017**: The agents service MUST construct the workflow graph by parsing the workflow definition config at runtime; the config MUST be the single source of truth for step topology — any change to step structure requires only a config edit and container restart
- **FR-018**: The workflow definition config MUST allow specification of, at minimum: the ordered list of steps, the tool each step invokes, and which steps require human feedback before proceeding

### Key Entities

- **WorkflowDefinition**: The config-declared blueprint for a workflow. Attributes: workflow type name, ordered list of step definitions (each with: step name, tool reference, feedback-required flag, any routing conditions). Read from config at runtime; never hardcoded
- **Workflow**: A named, stateful execution instance created from a WorkflowDefinition. Attributes: workflow ID, workflow type name, document reference, current state (running / paused / awaiting-feedback / complete / failed), created timestamp, last updated timestamp
- **Checkpoint**: A persisted snapshot of workflow execution state. Attributes: workflow ID, step name, step index, state data, timestamp
- **FeedbackEvent**: A human-provided input to a paused workflow. Attributes: workflow ID, step name, feedback payload, submitted by, timestamp
- **StepEvent**: A verbose record written to the project-level collection at the end of every workflow step. Attributes: workflow ID, step name, step index, step inputs, step outputs, step status (success / failed / skipped), agent reasoning notes (if any), timestamp. Written incrementally as the workflow progresses — not only at completion
- **WorkflowRecord**: The project-level persistent record summarising a completed workflow. Attributes: workflow ID, document reference, final outcome, total steps executed, timestamps. References the associated StepEvents for full detail
- **ToolInvocation**: A record of a single tool call made by an agent. Attributes: tool name, input parameters, output result, status, duration, timestamp
- **ConfigProfile**: The set of config files loaded by a container. Attributes: app config, business config, model config, environment name

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A workflow can be started, interrupted, and successfully resumed from its last checkpoint within the same session, with zero data loss between steps
- **SC-002**: Human feedback submitted via the API is incorporated into workflow execution without requiring a workflow restart — the workflow continues from the paused step
- **SC-003**: Any individual MCP tool can be invoked and returns a valid response within 30 seconds for standard document inputs
- **SC-004**: A new tool script can be added to the MCP tools service and be available for agent use after a single container restart, with no changes to any other service
- **SC-005**: Both containers start successfully with valid config files within 30 seconds, and fail fast with a descriptive error message within 10 seconds if a required config value is missing
- **SC-006**: The entire engine (both containers) can be stood up in a new environment (dev/staging/prod) by supplying environment-specific config files only — no code modification required; this includes changing the workflow step topology by editing the workflow definition config alone
- **SC-007**: The agents service and MCP tools service can be restarted independently without causing the other service to fail or lose in-flight state
- **SC-008**: A frontend client querying the step-event API for a running workflow receives step records reflecting the actual current progress — the latest written step appears in the query response within 5 seconds of that step completing

## Clarifications

### Session 2026-03-09

- Q: Should the project-level collection capture only final workflow outcomes, or verbose data at every step for real-time frontend visibility? → A: Verbose step-level data MUST be written to the project-level collection at the end of every workflow step so that a frontend can tap the API and display real-time workflow progress.
- Q: Should workflow step topology be hardcoded in the agents/workflow code, or driven entirely from config? → A: The workflow MUST be constructed dynamically at runtime from a workflow definition config file. Nothing — no step names, step order, tool assignments, or feedback gates — shall be hardcoded in the agents or workflow module.

## Assumptions

- The checkpointer is an external persistence store (e.g., database or object storage) accessible to the agents service; the boilerplate will define the interface but not provision the storage itself
- The project-level collection is a separate store from the checkpointer — it holds finalised records, not transient execution state
- Both containers are defined as part of a single repository and deployed together via container orchestration (e.g., Docker Compose for local development, Kubernetes or equivalent for production)
- Tool scripts in the MCP tools service are written in a language consistent with the existing codebase (Python, based on the existing project structure)
- The boilerplate establishes the project structure, config schema, container definitions, and service interfaces — initial tool implementations will be migrated or added in subsequent feature work
- Security for inter-service communication (e.g., mTLS, API keys between containers) follows the organisation's standard practices and is not in scope for the initial boilerplate
