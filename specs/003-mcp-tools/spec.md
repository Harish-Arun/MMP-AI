# Feature Specification: MCP Tools Service

**Feature Branch**: `003-mcp-tools`
**Created**: 2026-03-09
**Status**: Draft
**Input**: User description: "mcp-tools service providing tool sets to agents across three spectrums: 1. extraction - read payment instructions, extract fields/data, validate extraction, extract signature bounding boxes. 2. authentication - fraud checks, account info, confirmation of payee, signature authentication, duplicate checks. 3. verification - final verification that all checks passed and payment is okay to push to payments queue. All AI steps accompanied by an LLM-judge step to validate the step output; if invalid, the judge provides a suggestion and the AI step is retried."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Extraction Toolset: Read and Extract Payment Instruction Data (Priority: P1)

An agent submits a payment instruction document to the MCP tools service. The service's extraction tools read the document, extract all required payment fields and data, run validation checks on the extracted content, and additionally locate and extract the bounding box coordinates of any signatures present in the document. Once extraction is complete, a LLM-judge tool is invoked to assess the quality of the extracted output and decide whether the result is acceptable. If the judge is not satisfied, it provides a specific reason and the extraction step is automatically retried. The final result — fields, validation outcomes, signature locations, and judge verdict — is returned to the calling agent.

**Why this priority**: Extraction is the entry point for all downstream processing. Without reliable field extraction from the payment instruction, neither authentication nor verification can proceed. It is the root of the entire tool chain.

**Independent Test**: Can be tested by calling the extraction toolset in isolation with a sample payment instruction document and confirming returned fields, validation results, signature bounding boxes, and a LLM-judge verdict — all without requiring authentication or verification tools to be running.

**Acceptance Scenarios**:

1. **Given** a valid payment instruction document is submitted to the extraction toolset, **When** the extraction tool runs, **Then** all expected payment fields are extracted and returned in a structured format
2. **Given** extraction completes, **When** the validation checks run on the extracted fields, **Then** each field's validation status (pass / fail / warning) is returned alongside the field value
3. **Given** a document contains a signature, **When** the signature bounding box extraction tool runs, **Then** the bounding box coordinates for each detected signature region are returned
4. **Given** the extraction step produces a result, **When** the LLM-judge tool evaluates it, **Then** the judge returns a verdict of accepted or not-accepted, with a structured reason if not-accepted
5. **Given** the LLM-judge returns a not-accepted verdict, **When** the retry mechanism triggers, **Then** the extraction step is re-invoked with the judge's suggestion as additional context, and the judge re-evaluates the new output
6. **Given** extraction fails to produce a usable output after the maximum number of retries, **When** the retry limit is reached, **Then** the toolset returns a structured failure response to the agent indicating the reason and the last judge feedback

---

### User Story 2 - Authentication Toolset: Run Pre-Payment Authentication Checks (Priority: P2)

An agent invokes the authentication toolset with the extracted payment data. The service runs a sequence of checks — fraud detection, account information verification, confirmation of payee, signature authentication against reference signatures, and duplicate payment detection. Each AI-driven check in this sequence is paired with a LLM-judge step that validates whether the check was performed correctly. If the judge rejects a check's result, it provides a reason and triggers a retry. The final output is a consolidated authentication report covering the pass/fail status of each individual check.

**Why this priority**: Authentication checks protect against fraud and processing errors. They are the core compliance and risk controls for payment processing. Without them, invalid or fraudulent instructions could reach the payments queue.

**Independent Test**: Can be tested by calling the authentication toolset in isolation with a sample extracted payment payload and reference signature data, and confirming that all check results (fraud, account, payee, signature, duplicate) and their judge verdicts are returned — without requiring the verification toolset to run.

**Acceptance Scenarios**:

1. **Given** extracted payment data is submitted to the authentication toolset, **When** the fraud check tool runs, **Then** a fraud risk assessment result is returned (pass / flagged / fail) with a reason
2. **Given** payment data is submitted, **When** the account information check runs, **Then** the account details are confirmed as valid or returned with specific discrepancy details
3. **Given** payment data is submitted, **When** the confirmation of payee check runs, **Then** the payee name match result is returned (full match / close match / no match)
4. **Given** a signature bounding box is provided from extraction, **When** the signature authentication tool runs against reference signature data, **Then** a similarity verdict is returned (authentic / uncertain / not-authentic) with a confidence indicator
5. **Given** payment data is submitted, **When** the duplicate check tool runs, **Then** the tool returns whether an identical or near-identical payment has been processed within the lookback window
6. **Given** any AI-driven authentication check produces a result, **When** the LLM-judge evaluates it, **Then** a not-accepted verdict triggers a retry with the judge's suggestion incorporated, up to the configured maximum retries
7. **Given** all authentication checks complete (pass or noted failure), **When** the toolset finishes, **Then** a consolidated authentication report is returned listing each check, its result, and the judge verdict

---

### User Story 3 - Verification Toolset: Final Gate Before Payments Queue (Priority: P3)

An agent submits the authentication report and extracted data to the verification toolset. The service evaluates whether all required checks have passed and the payment instruction is clear to be forwarded to the payments queue. If all checks pass, the toolset returns a verified status. If any check failed or is unresolved, the toolset returns a not-verified status with details of what is blocking progression. The LLM-judge is also used here to validate the verification reasoning before a final verdict is issued.

**Why this priority**: Verification is the final control gate before a payment reaches the queue. It ensures no unresolved check from extraction or authentication silently allows a payment through. It is sequentially dependent on the previous two toolsets.

**Independent Test**: Can be tested by calling the verification toolset with a synthetic authentication report — one with all checks passing and one with at least one failing — and confirming that the verified and not-verified responses are correct and appropriately detailed, without requiring the extraction or authentication toolsets to re-run.

**Acceptance Scenarios**:

1. **Given** a complete authentication report with all checks passed is submitted to the verification toolset, **When** the verification tool runs, **Then** a verified status is returned, indicating the payment is cleared for the payments queue
2. **Given** an authentication report with one or more failed or unresolved checks is submitted, **When** the verification tool runs, **Then** a not-verified status is returned with details identifying each blocking check
3. **Given** the verification tool produces a reasoning output, **When** the LLM-judge evaluates the reasoning, **Then** a not-accepted verdict triggers a re-evaluation with the judge's suggestion, up to the configured maximum retries
4. **Given** verification returns a verified status, **When** the agent receives the response, **Then** the response includes sufficient metadata (workflow ID, document reference, check summary) for the downstream payments queue publisher to act on

---

### Edge Cases

- What happens if a payment instruction document is unreadable or in an unsupported format — is an error returned at the extraction stage before any checks run?
- What happens if the LLM-judge enters an infinite disagreement loop where every retry is also rejected — how is the maximum retry limit enforced and the result surfaced?
- What happens if a reference signature is missing when the signature authentication tool is invoked — does it fail, skip, or flag as inconclusive?
- What happens if the duplicate check lookback window configuration is absent or misconfigured?
- What happens if one authentication check passes but a later check in the sequence fails — are earlier pass results preserved in the report?
- What happens if a partial set of extracted fields is provided to the authentication toolset (e.g., missing account number)?
- How does the toolset behave if a downstream external check (e.g., confirmation of payee) is temporarily unavailable?

## Requirements *(mandatory)*

### Functional Requirements

**Extraction Tools**

- **FR-001**: The extraction toolset MUST accept a payment instruction document and return all expected payment fields in a structured format
- **FR-002**: The extraction toolset MUST run validation checks on each extracted field and return per-field validation status (pass / fail / warning) alongside the extracted value
- **FR-003**: The extraction toolset MUST detect and return the bounding box coordinates of all signature regions found in the document
- **FR-004**: Every AI-driven extraction step MUST be followed by a LLM-judge step that evaluates the extraction output and returns an accepted or not-accepted verdict with structured reasoning
- **FR-005**: When a LLM-judge returns a not-accepted verdict on an extraction step, the system MUST automatically retry that extraction step using the judge's suggestion as additional input, up to a configurable maximum number of retries
- **FR-006**: When the extraction retry limit is reached without an accepted verdict, the toolset MUST return a structured failure response containing the last judge feedback and the reason for failure

**Authentication Tools**

- **FR-007**: The authentication toolset MUST execute the following checks given extracted payment data: fraud check, account information check, confirmation of payee, signature authentication, and duplicate payment check
- **FR-008**: The signature authentication tool MUST compare the extracted signature bounding box against reference signature data and return a verdict (authentic / uncertain / not-authentic) with a confidence indicator
- **FR-009**: The duplicate payment check MUST identify whether an identical or near-identical payment has been submitted within a configurable lookback window
- **FR-010**: Every AI-driven authentication check MUST be paired with a LLM-judge step, applying the same retry-on-rejection pattern as extraction (FR-005, FR-006)
- **FR-011**: The authentication toolset MUST return a consolidated report listing every check, its result, and the corresponding judge verdict

**Verification Tools**

- **FR-012**: The verification toolset MUST accept a consolidated authentication report and return a verified or not-verified status for the payment instruction
- **FR-013**: A not-verified response MUST identify each check that is blocking verification and the reason it is unresolved
- **FR-014**: The verification reasoning MUST be evaluated by a LLM-judge step, applying the same retry-on-rejection pattern as extraction (FR-005, FR-006)
- **FR-015**: A verified response MUST include sufficient metadata for downstream consumers to identify the payment, the document, and the check summary

**Cross-Cutting**

- **FR-016**: All tools MUST return structured, consistent response envelopes (result payload, status, error detail, judge verdict where applicable)
- **FR-017**: The maximum number of LLM-judge retries per step MUST be externally configurable — it must not be hardcoded
- **FR-018**: All tools MUST be independently invocable — a caller can invoke any individual tool without needing to invoke any other tool in the same spectrum first [NEEDS CLARIFICATION: should the three toolset spectrums (extraction, authentication, verification) enforce a sequential execution order as a contract of this service, or should ordering be the responsibility of the calling agent driven by workflow config? This affects whether the tools service has any notion of a "workflow" or remains stateless/independent tools only]

### Key Entities

- **PaymentInstruction**: The input document submitted for processing. Attributes: document reference, document content, format, submission timestamp
- **ExtractionResult**: The structured output of the extraction toolset. Attributes: document reference, extracted fields (name-value pairs with validation status), signature bounding boxes (coordinates per detected signature), overall extraction status, judge verdict, retry count
- **SignatureBoundingBox**: The coordinates of a detected signature region within a document. Attributes: document reference, page number, coordinates (top-left x/y, width, height)
- **AuthenticationReport**: The consolidated output of the authentication toolset. Attributes: document reference, per-check results (check name, result, confidence where applicable, judge verdict), overall authentication status, retry count per check
- **VerificationResult**: The output of the verification toolset. Attributes: document reference, verified status, blocking checks (if not verified), judge verdict, metadata for downstream consumers
- **JudgeVerdict**: The output of any LLM-judge step. Attributes: step name, verdict (accepted / not-accepted), reasoning, suggestion (if not-accepted), retry number

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The extraction toolset processes a standard payment instruction document and returns extracted fields, validation statuses, and signature bounding boxes within 30 seconds
- **SC-002**: The LLM-judge retry mechanism resolves to an accepted verdict within the configured maximum retries for at least 95% of inputs that are processable (i.e., not corrupt or unsupported format)
- **SC-003**: The authentication toolset returns a consolidated report covering all five checks within 60 seconds for standard inputs
- **SC-004**: The verification toolset returns a clear verified or not-verified response within 15 seconds once a complete authentication report is provided
- **SC-005**: Any individual tool can be invoked and returns a valid structured response independently, without any other tool needing to run first
- **SC-006**: The maximum LLM-judge retry count can be changed via configuration alone and takes effect on the next tool invocation without any code change

## Assumptions

- Reference signature data required by the signature authentication tool is pre-provisioned and accessible to the tools service at runtime; this feature does not include provisioning or managing reference signatures
- The payments queue is an external system; the verification toolset returns a cleared result to the calling agent, which is responsible for forwarding to the queue — the tools service does not publish directly to the queue
- The LLM-judge is itself an AI tool hosted within the MCP tools service, not an external service
- "Near-identical" for duplicate payment detection is defined by a configurable matching policy (e.g., same payee, same amount, same account, within a time window); the default policy will be defined in business config
- All tools in this service are stateless with respect to one another — they do not share in-memory state; any cross-tool context (e.g., passing extraction results to authentication) is the responsibility of the calling agent
- External check dependencies (e.g., confirmation of payee service) are accessed via configured endpoints; availability and error handling of those external services is in scope for the authentication tools
