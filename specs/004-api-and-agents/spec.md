# Feature Specification: API and Agents Service

**Feature Branch**: `004-api-and-agents`
**Created**: 2026-03-09
**Status**: Draft
**Input**: User description: "api-and-agents container: all APIs for frontend communication covering workflow execution, stop, resume, status queries; external microservice integrations (signature fetching, fraud check, confirmation of payee, account info); payment instruction search with pagination; workflow creation from config; operation persistence; stats generation; audit log creation. Primary workflow trigger is an S3 event when a file is uploaded; fallback is operator manual upload and start."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Automatic Workflow Start from S3 Notification (Priority: P1)

A payment instruction file lands in the S3 bucket (uploaded by the ingestion component from feature 001). S3 sends a notification to the API-and-agents service. The service receives the notification, registers the payment instruction, and automatically starts the processing workflow — no human action is required. The operator can then observe the workflow progressing in real time via the frontend. This is the primary and expected path for all payment instruction processing.

**Why this priority**: The S3-triggered path is the primary production flow. Every minute a file sits unprocessed after arriving in S3 is a delay to payment execution. Automating the trigger end-to-end without human intervention is the highest-value outcome of this feature.

**Independent Test**: Can be tested by posting a synthetic S3 notification event directly to the API's notification endpoint with a valid S3 file reference, and confirming a workflow is created, execution begins, and a workflow ID is recorded — without any manual operator action.

**Acceptance Scenarios**:

1. **Given** the API service is running and a workflow config exists, **When** an S3 notification is received indicating a new file has been uploaded, **Then** the service registers the payment instruction, creates a workflow, starts execution, and records the workflow ID — all without operator intervention
2. **Given** an S3 notification arrives for a file that has already triggered a workflow, **When** the duplicate notification is received, **Then** no second workflow is started and the duplicate is logged as a warning
3. **Given** an S3 notification arrives but the referenced file is not accessible, **When** the service attempts to retrieve the file reference, **Then** the notification is rejected with a structured error, an audit log entry is written, and no workflow is started
4. **Given** a workflow is auto-started from S3, **When** execution begins, **Then** the trigger source (S3 event) and the S3 file reference are recorded on the workflow record for traceability

---

### User Story 2 - Operator Manual Upload and Workflow Start (Fallback Path) (Priority: P1)

An operator needs to submit a payment instruction for processing outside the automated S3 path — for example, during an ingestion outage, for a re-submission, or for an ad-hoc test. They upload the document directly via the API and request a workflow to start. The resulting workflow is identical in execution to an S3-triggered workflow; only the trigger source differs.

**Why this priority**: The manual path is an essential fallback. If the S3 ingestion pipeline (feature 001) is unavailable, the engine must still be operable by human intervention. Equally important for re-processing failed or corrected documents.

**Independent Test**: Can be tested by uploading a payment instruction file directly via the API, starting a workflow for it, and confirming the workflow proceeds through all steps identically to an S3-triggered run.

**Acceptance Scenarios**:

1. **Given** the API service is running, **When** an operator uploads a payment instruction file and submits a start-workflow request, **Then** the file is stored, the payment instruction is registered, the workflow starts, and a workflow ID is returned within 2 seconds
2. **Given** a manually uploaded file, **When** the workflow starts, **Then** the trigger source (manual / operator) and the uploading operator identity are recorded on the workflow record
3. **Given** the same file has already been processed (matched by content or reference), **When** the operator attempts to upload and start, **Then** the system warns of a potential duplicate and requires explicit confirmation before proceeding

---

### User Story 3 - Frontend Monitors and Controls In-Flight Workflows (Priority: P1)

Whether a workflow was started automatically from S3 or manually by an operator, the frontend operator can monitor its real-time progress and take actions — pausing, resuming, stopping, or submitting feedback at a human-in-the-loop step. The operator can request the current state at any time without needing to refresh the entire page.

**Why this priority**: This is the primary interactive surface of the entire engine. Without it, operators have no visibility or control once a workflow is in progress.

**Independent Test**: Can be tested end-to-end by starting a workflow (via either trigger path), polling the status endpoint, submitting a stop and then a resume command, submitting feedback at a feedback-required step, and confirming the workflow completes — all without requiring the frontend UI to be running.

**Acceptance Scenarios**:

1. **Given** the API service is running and a valid workflow config exists, **When** a start-workflow request is submitted with a payment instruction reference, **Then** the workflow is created, execution begins, and a workflow ID is returned within 2 seconds
2. **Given** a workflow is running, **When** the status endpoint is queried with the workflow ID, **Then** the response contains the current workflow state, the list of completed steps with their outputs, and any pending action
3. **Given** a running workflow, **When** a stop request is submitted, **Then** the workflow halts cleanly, state is persisted, and status reflects stopped
4. **Given** a stopped workflow, **When** a resume request is submitted, **Then** the workflow continues from the last persisted step without re-executing completed steps
5. **Given** a workflow that is paused awaiting human feedback, **When** a feedback payload is submitted via the API, **Then** the workflow resumes and the feedback is incorporated into the next step
6. **Given** any workflow state transition (started, step completed, paused, stopped, completed, failed), **When** the transition occurs, **Then** a corresponding step-level event is written to the project-level collection and is immediately queryable via the API

---

### User Story 4 - Payment Instruction Search (Priority: P2)

An operator or back-office user needs to find a specific payment instruction or browse a list of recently submitted instructions. They use a search endpoint with optional filters (e.g., payee name, account number, date range, workflow status) and receive paginated results. Each result includes the payment instruction's key fields and its current workflow status.

**Why this priority**: Operators need to locate and review instructions across sessions, especially for in-flight or failed workflows. Without search, the system is a black box after submission.

**Independent Test**: Can be tested by inserting a set of seeded payment instruction records and querying the search endpoint with different filter combinations, confirming correct filtered results are returned in paginated form — without requiring a workflow to be running.

**Acceptance Scenarios**:

1. **Given** payment instructions exist in the system, **When** a search request is submitted with no filters, **Then** all instructions are returned in reverse-chronological order, paginated with a configurable page size
2. **Given** payment instructions exist, **When** a search request is submitted with a filter (e.g., payee name), **Then** only matching records are returned
3. **Given** a search result set exceeds one page, **When** the caller requests the next page using a cursor or page number, **Then** the next set of results is returned without duplicates or omissions
4. **Given** no results match the search filters, **When** the search is executed, **Then** an empty result set is returned with a clear indication that no records matched
5. **Given** a search request includes a workflow status filter (e.g., "failed"), **When** executed, **Then** only instructions whose current workflow status matches are returned

---

### User Story 5 - External Microservice Integration (Priority: P2)

During workflow execution, the agents require data from external systems — fetching reference signature data, running fraud checks, confirming payee details, and retrieving account information. The API-and-agents service acts as the integration point for these external calls: it holds the client logic for each external microservice, normalises responses, handles errors gracefully, and feeds results back into the workflow as tool inputs.

**Why this priority**: Without external integrations, the authentication toolset (003-mcp-tools) cannot function — it depends on live data from external systems. This is co-equal in priority with search because both unblock downstream workflow steps and are independently testable.

**Independent Test**: Can be tested by calling each external integration endpoint in isolation (with the external service mocked) and confirming that requests are correctly formed, responses are correctly normalised, and error scenarios (timeout, 4xx, 5xx) return a structured error to the caller.

**Acceptance Scenarios**:

1. **Given** the signature fetching integration is configured, **When** a signature fetch is requested with a customer reference, **Then** the reference signature data is retrieved and returned in the normalised format expected by the authentication toolset
2. **Given** the fraud check integration is configured, **When** a fraud check is invoked with payment data, **Then** the fraud risk result is returned in a consistent structured format regardless of the external service's native response shape
3. **Given** the confirmation of payee integration is configured, **When** a payee confirmation is requested, **Then** a match result (full match / close match / no match) is returned in normalised form
4. **Given** the account info integration is configured, **When** an account info lookup is requested, **Then** account details are returned or a structured not-found response is given
5. **Given** any external integration call fails (timeout, error response), **When** the failure occurs, **Then** a structured error is returned to the workflow with sufficient detail for the agent to decide on retry or escalation — the API service does not swallow errors silently

---

### User Story 6 - Stats, Audit Log, and Operational Observability (Priority: P3)

An operations manager reviews the health and throughput of the payment processing pipeline. They query a stats endpoint for aggregate metrics (e.g., workflows started today, pass rate, average processing time, failure breakdown by check type). All significant system events — workflow state changes, external integration calls, errors — are also written to an audit log that is queryable and provides a full, tamper-evident trail of what happened and when.

**Why this priority**: Operational visibility and auditability are compliance and governance requirements for payment processing. They are lower priority only because they do not block core workflow execution — but they are non-negotiable for production readiness.

**Independent Test**: Can be tested by running a set of synthetic workflows, then querying the stats endpoint and auditing the audit log records to confirm that all expected entries are present, accurately reflect the synthetic run data, and the stats calculations are correct.

**Acceptance Scenarios**:

1. **Given** workflows have been processed, **When** the stats endpoint is queried, **Then** aggregate counts and rates are returned (e.g., total started, total completed, total failed, average duration, check pass/fail rates)
2. **Given** any significant system event occurs (workflow start/stop/resume/complete/fail, feedback submitted, external integration called, error raised), **When** the event occurs, **Then** an audit log entry is written containing: event type, timestamp, workflow ID, actor (system or user identifier), and relevant payload summary
3. **Given** audit log entries exist, **When** the audit log is queried with a workflow ID, **Then** the full chronological event trail for that workflow is returned
4. **Given** stats are requested for a specific date range, **When** the query is submitted with date parameters, **Then** metrics are correctly scoped to that range only
5. **Given** an audit log write fails, **When** the failure occurs, **Then** the triggering operation is NOT rolled back — audit log failures are logged separately and do not disrupt workflow execution

---

### Edge Cases

- What happens if an S3 notification arrives but the service is temporarily unavailable — is the notification lost, or does S3 retry delivery?
- What happens if an S3 notification arrives for a file reference that resolves to an unsupported document format?
- What happens if an operator manually uploads the exact same file that was already processed via S3 — how is the duplicate detected and who is warned?
- What happens if a start-workflow request is submitted for a payment instruction that already has a running workflow?
- What happens if a resume request is submitted for a workflow that is not in a stopped or paused state?
- What happens if the search index is temporarily inconsistent (e.g., a record exists but hasn't been indexed yet) and a search misses a recently submitted instruction?
- What happens if an external integration is unreachable during a workflow step — does the workflow wait, fail the step, or allow the agent to decide?
- What happens if the stats calculation becomes expensive as record volume grows — is there a staleness trade-off?
- What happens if a feedback payload is submitted for a workflow that has already completed or failed?
- What happens if the project-level collection write (step event / audit log) fails — does the service retry, and how are missed entries detected?
- How does pagination behave if records are inserted between page requests, causing results to shift?

## Requirements *(mandatory)*

### Functional Requirements

**Workflow Trigger Paths**

- **FR-001**: The service MUST accept S3 event notifications and automatically start a workflow for the referenced payment instruction file — this is the primary trigger path; no operator action is required
- **FR-001a**: The service MUST expose an operator-facing upload endpoint that accepts a payment instruction file and a start-workflow command as a fallback trigger path when the S3 route is unavailable or for re-submissions
- **FR-001b**: Both trigger paths MUST produce an identical workflow execution; the trigger source (S3 event or manual operator) and the actor identity MUST be recorded on the workflow record for traceability
- **FR-001c**: The service MUST detect duplicate triggers for the same payment instruction (by file reference or content match) and MUST NOT start a second workflow if one is already running or completed for that instruction; duplicates from S3 are silently discarded with a warning log; duplicates from a manual operator upload MUST surface a confirmation prompt before proceeding

**Workflow Execution API**

- **FR-002-exec**: The service MUST expose endpoints to stop and resume a workflow by workflow ID; workflows are constructed at runtime from the workflow definition config (no hardcoded topology)
- **FR-002**: The service MUST expose a status endpoint that returns the current workflow state, the trigger source, the full ordered list of step events so far, and any pending action for a given workflow ID
- **FR-003**: The service MUST expose a feedback submission endpoint that accepts a feedback payload for a workflow paused at a feedback-required step and triggers resumption
- **FR-004**: The service MUST write a step-level event record to the project-level collection at the completion of every workflow step, enabling real-time status polling from the frontend
- **FR-005**: The service MUST persist all workflow operation state in the checkpointer so that workflows survive service restarts and can be reliably resumed

**Payment Instruction Search**

- **FR-006**: The service MUST expose a search endpoint that accepts optional filters (at minimum: payee name, account reference, date range, workflow status) and returns matching payment instructions
- **FR-007**: Search results MUST be paginated; the caller MUST be able to navigate pages sequentially and the API MUST return total result count alongside each page
- **FR-008**: Each search result MUST include the payment instruction's key identifying fields and the current workflow status for that instruction

**External Microservice Integrations**

- **FR-009**: The service MUST provide an integration for each of the following external microservices: signature fetching, fraud check, confirmation of payee, and account information lookup
- **FR-010**: Each external integration MUST normalise the external service's response into a consistent internal format before returning it to the calling agent or tool
- **FR-011**: Each external integration MUST handle error conditions (timeout, 4xx, 5xx) gracefully and return a structured error response — errors MUST NOT be silently swallowed
- **FR-012**: External integration endpoints (base URLs, credentials references, timeout values) MUST be externally configurable and MUST NOT be hardcoded [NEEDS CLARIFICATION: should retry logic for external integration calls (max retries, back-off) be handled in this service, or delegated entirely to the MCP tools service / calling agent? Defining responsibility here avoids duplicate or conflicting retry logic]

**Stats and Audit Log**

- **FR-013**: The service MUST expose a stats endpoint returning aggregate workflow metrics; at minimum: total started, total completed, total failed, average processing duration, and check-level pass/fail breakdown
- **FR-014**: Stats MUST be filterable by date range
- **FR-015**: The service MUST write an audit log entry for every significant event: workflow state transitions, feedback submissions, external integration calls and their outcomes, and all errors
- **FR-016**: Audit log entries MUST be queryable by workflow ID and by date range via a dedicated API endpoint
- **FR-017**: Audit log write failures MUST NOT cause the triggering operation to fail or roll back; failures MUST be captured in a secondary error log

**General**

- **FR-018**: All API responses MUST follow a consistent envelope structure (data payload, status code, error detail where applicable)
- **FR-019**: All endpoints MUST be documented such that a frontend developer can integrate without additional verbal explanation

### Key Entities

- **WorkflowTrigger**: Records how and by whom a workflow was initiated. Attributes: trigger type (s3-event / manual-operator), actor identity (system or operator ID), S3 file reference or uploaded file reference, trigger timestamp
- **WorkflowInstance**: A running or completed workflow. Attributes: workflow ID, payment instruction reference, current state (running / paused / awaiting-feedback / stopped / complete / failed), trigger source (WorkflowTrigger reference), created timestamp, last updated timestamp, config profile used
- **StepEvent**: A verbose record of a single completed workflow step. Attributes: workflow ID, step name, step index, inputs, outputs, status, timestamp. Written to the project-level collection incrementally
- **FeedbackSubmission**: A human-provided input to a paused workflow. Attributes: workflow ID, step name, feedback payload, submitted by, timestamp
- **PaymentInstructionRecord**: A persisted record of a submitted payment instruction, used as the basis for search. Attributes: instruction ID, payee name, account reference, amount, submission timestamp, current workflow status
- **ExternalIntegrationCall**: A record of a call made to an external microservice. Attributes: service name, request summary, response summary, status (success / error), duration, timestamp — written to the audit log
- **AuditLogEntry**: A tamper-evident record of a significant system event. Attributes: event type, timestamp, workflow ID, actor, payload summary
- **StatsSnapshot**: A computed aggregate view. Attributes: time range, total started, total completed, total failed, average duration, per-check pass/fail counts

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: When an S3 notification is received, a workflow is started and its first step event appears in the status response within 10 seconds of the notification arriving — no operator action required
- **SC-001a**: When an operator manually uploads a file and starts a workflow, the workflow starts and its first step event appears within 5 seconds of the start request completing
- **SC-002**: A stopped workflow can be resumed and completes successfully from its last checkpoint, with zero steps re-executed
- **SC-003**: Payment instruction search returns correctly filtered, paginated results within 2 seconds for datasets up to 10,000 records
- **SC-004**: All four external integrations (signature fetch, fraud check, confirmation of payee, account info) return normalised responses within their configured timeout; errors are surfaced as structured responses rather than unhandled exceptions
- **SC-005**: Stats for a given date range are returned within 3 seconds for up to 30 days of data
- **SC-006**: Every workflow state transition and external integration call produces a queryable audit log entry within 5 seconds of the event occurring
- **SC-007**: An audit log write failure does not cause any workflow step, API response, or external integration call to fail — the operation completes normally and only the audit record is missed
- **SC-008**: All external integration base URLs and credentials references can be changed via configuration alone, taking effect on the next service restart with no code change

## Assumptions

- The checkpointer and project-level collection are external persistence stores provisioned separately; this service defines the interface and write contracts but does not own the storage infrastructure
- External microservices (fraud check, confirmation of payee, account info, signature fetch) are pre-existing services with known API contracts; this feature implements client integration adapters for them, not the services themselves
- Authentication and authorisation for the API endpoints (who may call start/stop/resume, who may read audit logs) follows the organisation's standard API security practices and is a separate concern not in scope for this spec
- S3 notification delivery reliability (retry behaviour when the API service is temporarily unavailable) is governed by the S3/notification infrastructure configuration established in feature 001; this service assumes notifications are delivered at least once and handles duplicates via the deduplication logic in FR-001c
- Payment instruction records are written to the searchable store at the point of workflow creation (either triggered by S3 notification or operator upload); the initial record write is owned by this service at the moment of workflow start
- The workflow definition config consumed by this service is the same config established in feature 002 (engine boilerplate); workflow topology is never hardcoded here
- Stats are computed on read from persisted records (not from a maintained counter) unless performance testing reveals this is insufficient, in which case a pre-aggregated approach is adopted
