# Feature Specification: Frontend Portal

**Feature Branch**: `005-frontend-portal`
**Created**: 2026-03-09
**Status**: Draft
**Input**: User description: "Frontend portal for the MMP AI system. Three operator roles: keyer (data entry/extraction review), authenticator (authentication checks review), verifier (final verification). Superuser/admin for audit logs and stats. SSO Windows AD authentication with role-based access. Operators view documents, respond to HITL steps, give feedback on AI results, make corrections. Shared feedback/comments column appended by each user as the workflow progresses."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - SSO Login and Role-Based Workspace Access (Priority: P1)

A user opens the portal and is authenticated automatically via their Windows Active Directory credentials using SSO — no separate username or password to manage. Once authenticated, the portal determines their assigned role (Keyer, Authenticator, Verifier, or Admin) and presents only the workspace and actions relevant to that role. A user with multiple roles sees all applicable views.

**Why this priority**: Without authentication and role enforcement, no other capability is safely accessible. This is the gate through which all users enter and the foundation for every access control decision in the portal.

**Independent Test**: Can be tested by logging in with AD accounts assigned to each of the four roles separately and confirming that each user sees only their role-appropriate workspace, navigation items, and action controls — and cannot access views belonging to other roles.

**Acceptance Scenarios**:

1. **Given** a user with a valid Windows AD account visits the portal, **When** they open the portal URL, **Then** they are authenticated via SSO without being prompted for a separate password and are taken directly to their role workspace
2. **Given** a user is authenticated, **When** the portal loads, **Then** only navigation items, views, and action buttons appropriate to their assigned role are visible and accessible
3. **Given** a user attempts to directly access a URL belonging to another role's workspace, **When** the navigation is attempted, **Then** access is denied and the user is redirected to their own workspace with a clear message
4. **Given** a user's AD session expires or they are removed from their AD group, **When** they next interact with the portal, **Then** they are re-challenged for authentication or shown an access denied state
5. **Given** an authenticated user has no recognised role assigned in AD, **When** they log in, **Then** they are shown a clear message indicating their account has no portal access, rather than an unhandled error

---

### User Story 2 - Keyer: Review Extraction Results and Correct AI Output (Priority: P1)

A Keyer is notified that a payment instruction has been processed by the extraction AI step and requires their review. They open the document viewer and see the original document alongside the AI-extracted fields. All fields are editable. The Keyer reviews each extracted field against the document, corrects any errors, marks fields as confirmed or flagged, and submits their review. Their actions and any corrections they made are appended to the shared workflow comment trail.

**Why this priority**: The Keyer review is the first human checkpoint in the workflow. AI extraction results feed directly into authentication and verification — errors not caught here propagate downstream. This is the earliest and highest-leverage human correction point.

**Independent Test**: Can be tested by presenting a Keyer with a completed extraction result (with deliberate errors seeded) and confirming they can view the document, edit fields, confirm or flag them, submit the review, and that the correction is reflected in the workflow record and the comment trail — without any Authenticator or Verifier action being required.

**Acceptance Scenarios**:

1. **Given** a payment instruction has reached the Keyer review step, **When** the Keyer opens their workspace, **Then** the document is displayed alongside the AI-extracted fields in an editable side-by-side view
2. **Given** the Keyer is reviewing extracted fields, **When** they edit a field value, **Then** the correction is staged locally and highlighted as a user correction distinct from the original AI extraction
3. **Given** the Keyer has reviewed all fields, **When** they submit their review, **Then** all confirmed and corrected field values are saved, a summary of changes is appended to the shared comment trail with the Keyer's identity and timestamp, and the workflow advances to the next step
4. **Given** the Keyer notices a critical issue that prevents proceeding, **When** they flag the document and add a comment, **Then** the workflow is paused with a flag status and the comment is appended to the comment trail
5. **Given** the AI extraction included a signature bounding box, **When** the Keyer views the document, **Then** the detected signature region is visually highlighted on the document for the Keyer to confirm or reject

---

### User Story 3 - Authenticator: Review Authentication Check Results and Respond to HITL (Priority: P1)

An Authenticator receives a payment instruction that has passed Keyer review and has been run through the authentication toolset. They see the results of all authentication checks (fraud, account info, confirmation of payee, signature match, duplicate check) displayed against the document. For any step that the engine has paused for human confirmation (HITL), the Authenticator is prompted with the specific question or decision required. They respond to each HITL prompt, review and approve or override check results, and submit their decision. Their responses and any overrides are appended to the shared comment trail.

**Why this priority**: The Authenticator is the human firewall against fraudulent or erroneous payments advancing. Their HITL responses directly resume or redirect the engine workflow. This role has the most direct impact on payment safety.

**Independent Test**: Can be tested by presenting an Authenticator with a workflow paused at an authentication HITL step and confirming they can see the check results, respond to the HITL prompt, override a check outcome if permitted, submit their decision, and that the workflow resumes with their input recorded in the comment trail.

**Acceptance Scenarios**:

1. **Given** a payment instruction has reached the Authenticator review step, **When** the Authenticator opens their workspace, **Then** the document and all authentication check results are displayed, with HITL pending items clearly distinguished from auto-passed checks
2. **Given** one or more authentication checks are paused for HITL, **When** the Authenticator views the pending items, **Then** each HITL prompt clearly states what decision or input is required and provides the relevant check context
3. **Given** the Authenticator provides a response to a HITL prompt, **When** they submit the response, **Then** the workflow engine receives the feedback, the relevant step resumes, and the Authenticator's response is appended to the shared comment trail with their identity and timestamp
4. **Given** an authentication check result appears incorrect, **When** the Authenticator overrides the result with a correction and a reason, **Then** the override is saved, the corrected value is used downstream, and the override is recorded in the comment trail
5. **Given** the Authenticator identifies a payment instruction that should not proceed, **When** they reject it with a reason, **Then** the workflow is terminated with a rejected status and the reason is appended to the comment trail

---

### User Story 4 - Verifier: Final Review and Payment Queue Approval (Priority: P2)

A Verifier receives a payment instruction that has passed Keyer and Authenticator reviews. They see a consolidated view: the original document, the extracted fields, the full authentication check summary, and the complete comment trail from all previous operators. If the verification AI step has flagged issues, the Verifier sees these prominently. They review the consolidated evidence, respond to any HITL prompts at the verification stage, and make the final approval or rejection decision to release the payment to the queue.

**Why this priority**: The Verifier is the last human gate before payment execution. Their approval triggers the payments queue submission. Without this role functioning correctly in the UI, no payment can be safely released.

**Independent Test**: Can be tested by presenting a Verifier with a workflow that has passed all prior stages and confirming they can see the full consolidated view, respond to any verification HITL, submit a final approve or reject decision, and that the outcome is recorded and the workflow is marked complete or rejected accordingly.

**Acceptance Scenarios**:

1. **Given** a payment instruction has reached the Verifier review step, **When** the Verifier opens their workspace, **Then** they see the document, extracted fields, full authentication check summary, verification check result, and the complete comment trail from Keyer and Authenticator
2. **Given** the Verifier reviews all evidence, **When** they approve the payment, **Then** the workflow is marked verified, the engine is notified to release the instruction to the payments queue, and the approval is appended to the comment trail
3. **Given** the Verifier identifies a blocking issue, **When** they reject the payment with a reason, **Then** the workflow is marked rejected, the reason is appended to the comment trail, and no queue submission occurs
4. **Given** there are outstanding HITL prompts at the verification stage, **When** the Verifier submits their response, **Then** the engine resumes the verification step and the Verifier is presented with the updated result before making their final decision

---

### User Story 5 - Shared Workflow Comment Trail (Priority: P2)

Every operator who touches a payment instruction — Keyer, Authenticator, Verifier — can read the accumulated comment trail showing what each previous operator did, noted, or corrected. Each operator can append their own comment at any point during their review. The trail is in chronological order, attributed, and immutable once written — no one can edit or delete a prior comment.

**Why this priority**: The comment trail is the shared working memory of the workflow. Without it, each operator works in isolation with no context from prior steps. It is also essential for audit and dispute resolution.

**Independent Test**: Can be tested by running a workflow through all three operator stages with each operator adding a comment and a correction, then viewing the final comment trail and confirming all entries are present, correctly attributed, in chronological order, and that no earlier entry can be edited or deleted.

**Acceptance Scenarios**:

1. **Given** an operator is reviewing a payment instruction, **When** they add a comment, **Then** the comment is saved with their identity, role, and timestamp, and is immediately visible to any other operator or admin viewing the same instruction
2. **Given** a prior operator has added a comment, **When** the current operator views the comment trail, **Then** they cannot edit or delete any prior entry — only append new ones
3. **Given** an operator makes a field correction or check override, **When** the correction is saved, **Then** a system-generated comment summarising the correction is automatically appended to the trail alongside any manual comment the operator provided
4. **Given** the workflow completes, **When** an admin views the instruction, **Then** the full comment trail including all operator comments and system-generated correction summaries is available and queryable

---

### User Story 6 - Admin: Audit Logs, Stats, and System Oversight (Priority: P3)

An Admin user logs in and has access to a dedicated administration area not visible to operator roles. From here they can view the audit log (every significant system event across all workflows), browse aggregated statistics (throughput, pass rates, processing times, check failure breakdowns), search and inspect any payment instruction regardless of its status, and review the comment trail for any workflow.

**Why this priority**: Admin oversight is required for governance, compliance, and operational health monitoring. It does not block day-to-day processing but is non-negotiable for a production-ready system.

**Independent Test**: Can be tested by logging in as an Admin and confirming access to the audit log, stats dashboard, unrestricted payment instruction search, and comment trail for any instruction — and confirming that a non-admin role cannot access any of these views.

**Acceptance Scenarios**:

1. **Given** an Admin is logged in, **When** they open the audit log view, **Then** all system events across all workflows are displayed in reverse-chronological order, filterable by date range, event type, and workflow ID
2. **Given** an Admin opens the stats view, **When** they select a date range, **Then** aggregate metrics are displayed: total workflows started, completed, failed; average processing duration; check-level pass/fail rates; and per-role action counts
3. **Given** an Admin searches for a payment instruction, **When** they select a result, **Then** they can see the full record including extracted fields, all check results, workflow history, and the complete comment trail — regardless of the instruction's current state
4. **Given** a non-admin role attempts to access the admin area URL directly, **When** the navigation is attempted, **Then** access is denied and the user is redirected to their own workspace

---

### Edge Cases

- What happens if the user's AD group membership changes while they are in an active session — do they retain their old role until they re-authenticate?
- What happens if a HITL prompt arrives for a workflow step that has already timed out or been superseded?
- What happens if two Authenticators attempt to respond to the same HITL prompt simultaneously?
- What happens if the API service is unavailable when an operator submits a review — are their changes lost, or held locally until reconnection?
- What happens if a document file is too large to render in the browser within an acceptable time?
- What happens if an operator leaves a review partially complete and closes their browser — is progress saved as a draft?
- What happens if the comment trail for a single workflow becomes very long (hundreds of entries) — is pagination or collapsing applied?
- What happens if a Verifier tries to approve a payment where not all prior HITL steps have been responded to?

## Requirements *(mandatory)*

### Functional Requirements

**Authentication and Access Control**

- **FR-001**: The portal MUST authenticate all users via SSO using Windows Active Directory — no separate credential store or login form is permitted
- **FR-002**: The portal MUST determine each user's role (Keyer, Authenticator, Verifier, Admin) from their AD group membership and enforce role-based access to all views and actions
- **FR-003**: Users MUST only see navigation items, workspace views, and action controls that correspond to their assigned role; cross-role access MUST be denied with a clear message
- **FR-004**: Admin users MUST have access to audit logs, stats, and all payment instruction records regardless of status; this access MUST NOT be available to operator roles

**Keyer Workspace**

- **FR-005**: The Keyer workspace MUST display the original payment instruction document alongside all AI-extracted fields in an editable side-by-side layout
- **FR-006**: Keyers MUST be able to edit any extracted field value; edited values MUST be visually distinguished from the original AI extraction
- **FR-007**: Signature bounding boxes detected by the extraction toolset MUST be visually highlighted on the document in the Keyer view for confirmation or rejection
- **FR-008**: Keyers MUST be able to flag a document with a reason, which pauses the workflow and appends the reason to the comment trail
- **FR-009**: On Keyer review submission, a system-generated summary of all corrections MUST be automatically appended to the shared comment trail alongside the Keyer's manual comment

**Authenticator Workspace**

- **FR-010**: The Authenticator workspace MUST display the document, extracted fields (read-only), and all authentication check results, with HITL-pending items clearly distinguished from auto-resolved checks
- **FR-011**: The portal MUST present each HITL prompt with the relevant check context and accept a structured response from the Authenticator that is forwarded to the engine via the API
- **FR-012**: Authenticators MUST be able to override an authentication check result with a correction and a mandatory reason; the override and reason MUST be appended to the comment trail
- **FR-013**: Authenticators MUST be able to reject a payment instruction with a reason, terminating the workflow

**Verifier Workspace**

- **FR-014**: The Verifier workspace MUST display a consolidated view: document, extracted fields, full authentication check summary, verification check result, and the complete comment trail from all prior operators
- **FR-015**: Verifiers MUST be able to approve or reject the payment instruction; approval notifies the engine to release to the payments queue; rejection terminates the workflow — both outcomes are appended to the comment trail
- **FR-016**: If outstanding HITL prompts exist at the verification stage, the Verifier MUST respond to them before they can submit a final approve or reject decision

**Shared Comment Trail**

- **FR-017**: Every operator action that changes workflow state (correction, override, flag, HITL response, approval, rejection) MUST generate an automatic system comment appended to the comment trail, in addition to any manual comment the operator provides
- **FR-018**: The comment trail MUST be append-only — no user at any role level may edit or delete any prior comment entry
- **FR-019**: Each comment entry MUST record: author identity, author role, timestamp, and comment body (manual or system-generated)
- **FR-020**: The comment trail MUST be displayed in chronological order and MUST be visible to all users sharing access to that workflow (all operators on that instruction, and Admin)

**Admin Area**

- **FR-021**: The Admin view MUST provide an audit log browser filterable by date range, event type, and workflow ID
- **FR-022**: The Admin view MUST provide a stats dashboard displaying aggregate metrics filterable by date range: workflow volumes, completion/failure rates, average duration, and check-level pass/fail breakdown
- **FR-023**: Admin MUST be able to search for and inspect any payment instruction regardless of its workflow status, including its full comment trail and all check results

**General**

- **FR-024**: The portal MUST display the live workflow status for a payment instruction (running step name, overall state) without requiring a full page reload, by polling the step-event API from feature 004
- **FR-025**: The portal MUST handle API unavailability gracefully — in-progress operator input MUST be preserved in local state so it is not lost if the API call fails, and a clear error message MUST be shown [NEEDS CLARIFICATION: should in-progress edits be persisted as a recoverable draft server-side, or is client-side preservation (surviving a page refresh) sufficient? This affects server-side complexity and data-loss risk]

### Key Entities

- **UserSession**: An authenticated portal session. Attributes: user identity (from AD), assigned role(s), session start time, last activity time
- **OperatorReview**: The record of an operator's actions on a workflow step. Attributes: workflow ID, step name, operator identity, role, field corrections (if any), HITL responses (if any), check overrides (if any), decision (approve / reject / flag), submitted timestamp
- **CommentEntry**: A single entry in the shared workflow comment trail. Attributes: workflow ID, author identity, author role, timestamp, comment body, entry type (manual / system-generated), related action reference
- **DocumentView**: The rendered payment instruction document as presented to operators. Attributes: instruction ID, document reference, signature highlight regions, current extracted field set, read/write access level (determined by role)

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user with a valid AD account is authenticated and their role workspace is fully loaded within 5 seconds of opening the portal URL — without any separate login step
- **SC-002**: An operator can complete a full review of a payment instruction (view document, review fields, respond to HITL, submit decision with comment) in under 5 minutes for a standard instruction
- **SC-003**: Workflow status updates (new step completed) appear in the operator's view within 10 seconds of the engine completing that step, without a full page reload
- **SC-004**: The shared comment trail for any payment instruction is visible and up to date across all operator sessions viewing the same instruction within 5 seconds of a new entry being submitted
- **SC-005**: Cross-role access attempts are blocked 100% of the time — no user can access, view, or act on any resource outside their assigned role
- **SC-006**: The Admin stats dashboard renders aggregate metrics for a 30-day date range within 5 seconds
- **SC-007**: An operator's in-progress review input is preserved if the API call to submit fails, allowing them to retry submission without re-entering their work

## Assumptions

- Windows Active Directory is the organisation's identity provider and is accessible from the user's browser environment; SSO is expected to work without additional VPN or network configuration by end users
- Role assignment is managed entirely through AD group membership; the portal does not maintain its own role store — changes to a user's role take effect at the next authentication
- Each payment instruction is processed by exactly one Keyer, then one Authenticator, then one Verifier in sequence; concurrent review of the same instruction by two users of the same role is not an expected scenario (though edge case handling applies)
- The document rendering capability (PDF / image display with annotation overlay for signature bounding boxes) is provided by a browser-native or licensed viewer component; selection of that component is an implementation detail
- State management approach (client-side) is an implementation decision; the specification defines the user-facing behaviours that state management must support, not the technology used to achieve it
- The portal communicates exclusively with the API-and-agents service (feature 004) and does not call any other backend service directly
