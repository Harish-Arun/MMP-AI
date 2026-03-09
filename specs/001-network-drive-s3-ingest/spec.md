# Feature Specification: Network Drive to S3 Ingestion with Workflow Trigger

**Feature Branch**: `001-network-drive-s3-ingest`  
**Created**: 2026-03-09  
**Status**: Draft  
**Input**: User description: "create a component that will have a connection with network drive and the moment u get files in network drive, you'd upload it in the s3 bucket. Now when you have uploaded a file in s3 bucket it should send some notification to our mmp-ai-engine that will trigger our workflow."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Automatic File Detection and S3 Upload (Priority: P1)

A document arrives on a shared network drive (e.g., placed by back-office staff or a scanner). The ingestion component detects the new file automatically and uploads it to the designated S3 bucket without any manual intervention. The original file remains on the network drive until confirmed as safely stored.

**Why this priority**: This is the core value of the feature — eliminating manual upload steps and ensuring every document placed on the network drive reaches cloud storage reliably. Without this, no downstream processing can happen.

**Independent Test**: Can be tested by placing a file on the monitored network drive path and verifying within 60 seconds that the file appears in the S3 bucket with the correct name and content. Delivers standalone value as a reliable file synchronisation mechanism.

**Acceptance Scenarios**:

1. **Given** the ingestion service is running and monitoring the network drive, **When** a new file is placed on the network drive, **Then** the file is uploaded to the S3 bucket within 60 seconds and an upload record is created
2. **Given** a file is being written to the network drive in multiple parts (large file), **When** the file write completes, **Then** the upload only begins after the file is fully written and not in a partial state
3. **Given** the same file already exists in S3, **When** it is placed on the network drive again with the same name, **Then** the system detects the duplicate and does not re-upload or re-trigger the workflow
4. **Given** the S3 bucket is temporarily unavailable, **When** an upload attempt fails, **Then** the system retries with exponential back-off and succeeds once S3 is available again

---

### User Story 2 - Workflow Trigger Notification to mmp-ai-engine (Priority: P2)

After a file is successfully uploaded to S3, the ingestion component sends a notification to the mmp-ai-engine. The engine uses this notification to locate the file in S3 and begin the configured document processing workflow (extraction, signature detection, verification).

**Why this priority**: Without the notification, the mmp-ai-engine would have no trigger to begin processing. This closes the loop from file arrival to automated processing.

**Independent Test**: Can be tested by uploading a document directly to S3 (bypassing the network drive step) and manually posting the equivalent notification payload to the mmp-ai-engine API, confirming the workflow is triggered and the document moves through processing stages.

**Acceptance Scenarios**:

1. **Given** a file has been successfully uploaded to S3, **When** the upload completes, **Then** a notification is sent to the mmp-ai-engine containing the S3 file reference and relevant metadata
2. **Given** the mmp-ai-engine is temporarily unavailable, **When** the notification attempt fails, **Then** the system retries delivery and does not lose the event
3. **Given** the notification is delivered to the mmp-ai-engine, **When** the engine receives it, **Then** the workflow begins processing and the document status reflects "in progress"
4. **Given** a file upload to S3 fails, **When** the upload error occurs, **Then** no notification is sent to the mmp-ai-engine

---

### User Story 3 - Upload Visibility and Error Alerting (Priority: P3)

Operations staff can see which files have been detected, uploaded, and triggered workflows — and are alerted when files fail to upload or notifications fail to deliver, so they can intervene.

**Why this priority**: Builds operational confidence and provides a safety net. Failures are silent without this, leading to documents being missed in processing.

**Independent Test**: Can be tested by deliberately introducing a network drive path that does not exist and a valid S3 destination, then checking that an error log entry or alert is produced for the unreachable path.

**Acceptance Scenarios**:

1. **Given** an upload fails after all retries, **When** the failure threshold is reached, **Then** the failure is logged with the file name, timestamp, and reason, and an alert is raised
2. **Given** the network drive becomes disconnected, **When** the connection drops, **Then** the system logs the disconnection event and resumes monitoring automatically when the drive reconnects
3. **Given** a review of upload history is needed, **When** operations staff access logs, **Then** each entry shows file name, detection time, upload time, S3 location, and notification status

---

### Edge Cases

- What happens when a file is renamed or moved on the network drive after detection but before upload completes?
- How does the system handle zero-byte or corrupt files placed on the network drive?
- What happens when two files with identical names arrive in rapid succession?
- How does the system behave during a rolling restart or deployment?
- What happens if the S3 bucket storage quota is reached?
- How does the system handle files that are very large (>1 GB)?
- What if the mmp-ai-engine rejects the notification with a non-retryable error (e.g., invalid payload)?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST continuously monitor a configured network drive path for newly created or newly written files
- **FR-002**: The system MUST upload detected files to a designated S3 bucket within 60 seconds of the file being fully written
- **FR-003**: The system MUST wait for a file to be fully written before initiating upload (no partial file uploads)
- **FR-004**: The system MUST detect and skip files that already exist in S3 with identical content, preventing duplicate uploads and duplicate workflow triggers
- **FR-005**: The system MUST send a notification to the mmp-ai-engine upon each successful S3 upload, including the S3 file reference, original file name, and file metadata (size, detection timestamp)
- **FR-006**: The system MUST retry failed S3 uploads automatically using exponential back-off, up to a configurable maximum number of attempts
- **FR-007**: The system MUST retry failed mmp-ai-engine notifications automatically, ensuring at-least-once delivery
- **FR-008**: The system MUST NOT send a notification to the mmp-ai-engine for a file whose S3 upload did not succeed
- **FR-009**: The system MUST log each file event (detected, upload started, upload succeeded, upload failed, notification sent, notification failed) with a timestamp and file reference
- **FR-010**: The system MUST alert operations when a file fails to upload after all retries are exhausted
- **FR-011**: The system MUST recover automatically from network drive disconnections and resume monitoring when the drive is accessible again
- **FR-012**: The monitored network drive path and S3 destination MUST be externally configurable without code changes
- **FR-013**: The notification payload sent to the mmp-ai-engine MUST be of a format [NEEDS CLARIFICATION: the notification delivery mechanism is unspecified — should this use the existing mmp-ai-engine REST API, a message queue (e.g., SQS/SNS), or a webhook? This impacts reliability guarantees and retry behaviour significantly]
- **FR-014**: The system MUST support filtering which file types are monitored and uploaded [NEEDS CLARIFICATION: should all file types be ingested, or only specific document formats such as PDFs and images relevant to mortgage processing?]

### Key Entities

- **FileEvent**: Represents a file detected on the network drive. Attributes: file name, source path, file size, detection timestamp, write-completion timestamp
- **UploadRecord**: Tracks the outcome of an S3 upload attempt. Attributes: source file reference, S3 bucket, S3 key, upload timestamp, status (pending / success / failed), retry count
- **WorkflowTriggerNotification**: Represents the message sent to mmp-ai-engine. Attributes: S3 file reference, original file name, file metadata, notification timestamp, delivery status

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Files placed on the network drive are available in the S3 bucket within 60 seconds of the file being fully written, under normal conditions
- **SC-002**: 100% of files placed on the network drive are eventually uploaded to S3 and trigger the mmp-ai-engine workflow, with no silent failures
- **SC-003**: The system handles at least 50 files arriving simultaneously without losing any events or triggering duplicate workflows
- **SC-004**: Duplicate files (same file placed on the drive again) are identified and do not result in duplicate workflow triggers
- **SC-005**: Operations staff are alerted to any upload or notification failure within 5 minutes of the failure occurring
- **SC-006**: The system recovers from a network drive disconnection and resumes normal operation within 5 minutes of reconnection, without requiring a manual restart
- **SC-007**: Zero manual interventions are required under normal operating conditions to move files from the network drive through to workflow initiation

## Assumptions

- The network drive is accessible as a mounted or mapped path on the host where the ingestion component runs (e.g., a UNC path on Windows or a mount point on Linux)
- The mmp-ai-engine exposes an endpoint capable of receiving file-arrival events and using the S3 reference to retrieve and process documents
- Files on the network drive are considered immutable once written — they are not edited in place after creation
- The S3 bucket is pre-provisioned and the ingestion component has appropriate write permissions
- File retention on the network drive after upload is governed by existing operational policy; the ingestion component does not delete source files
- Standard web application performance expectations apply; no high-frequency trading or sub-second latency constraints exist for this component
