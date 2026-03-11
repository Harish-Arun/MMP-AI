# Research: 001 Network Drive S3 Ingest

**Branch**: `001-network-drive-s3-ingest` | **Date**: 2026-03-10  
**Purpose**: Resolve all technical unknowns from the implementation plan before design begins.

---

## R-001: SFTP Client Library Selection

**Question**: Which Python SFTP library is most appropriate for an async, containerised polling service?

**Decision**: `asyncssh`

**Rationale**:
- `asyncssh` is fully async-native (built on `asyncio`), eliminating any risk of blocking the event loop during SFTP directory listing or file download — critical for a poll-loop service
- `paramiko` is the historically dominant choice but is synchronous; wrapping it in `asyncio.run_in_executor` adds complexity and thread-pool overhead
- `asyncssh` supports both password and public-key authentication out of the box (FR-012)
- Active maintenance, permissive licence (Eclipse Public License 2.0)
- Reconnect on `asyncssh.DisconnectError` / `ConnectionLost` is straightforward (`try/except` around connect, retry with `tenacity`)

**Alternatives considered**:
- `paramiko` — rejected: synchronous, blocks event loop
- `pysftp` — rejected: thin wrapper around paramiko, same blocking concern, less actively maintained
- `fabric` — rejected: designed for SSH command execution, not SFTP file transfer polling

---

## R-002: S3 Client and LocalStack Compatibility

**Question**: How should the S3 client be configured to seamlessly switch between LocalStack (local dev) and real AWS (production) without code changes?

**Decision**: `boto3` with `endpoint_url` injected via configuration (`pydantic-settings`)

**Rationale**:
- `boto3` is the AWS-blessed Python SDK for S3; the constitution II SDK-free rule applies only to LLM provider SDKs
- LocalStack community free tier fully emulates the S3 API on `http://localhost:4566`; `boto3` works against it identically to AWS by setting `endpoint_url=http://localhost:4566`
- When `endpoint_url` is `None` or unset, `boto3` resolves to the real AWS regional endpoint — no code branching required
- `AWS_ACCESS_KEY_ID=test`, `AWS_SECRET_ACCESS_KEY=test`, `AWS_DEFAULT_REGION=us-east-1` are standard LocalStack dummy credentials; same env vars used in CI
- `moto[s3]` intercepts `boto3` calls in unit/BDD tests without LocalStack being running — offline, fast, zero-infra

**Pattern**:
```python
import boto3
from src.config.settings import Settings

def make_s3_client(settings: Settings):
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url or None,
        region_name=settings.aws_region,
    )
```

**Alternatives considered**:
- `aioboto3` — considered; adds async wrapper but introduces additional dependency and `moto` compatibility is less reliable; not worth the complexity for a batch-upload service
- `httpx` direct S3 REST calls — rejected: would require manual request signing (SigV4); `boto3` handles this correctly

---

## R-003: File Completeness Detection over SFTP

**Question**: How do we reliably determine that a file being written to the SFTP server is fully written before uploading (FR-003)?

**Decision**: Size-stability check across two consecutive poll cycles

**Rationale**:
- SFTP provides no native "file-write-complete" event; the drive is Windows-based with no inotify/fanotify access
- The size-stability pattern is the standard approach for remote/network targets: record file size on first detection; on next poll, if size is unchanged → file is stable → safe to upload
- Two consecutive identical sizes is sufficient for batch document uploads (PDF files from scanners) which are written atomically or in large sequential blocks
- Zero-byte files: treated as unstable on first poll (size=0); if still 0 on second poll, flagged as WARNING and skipped (cannot upload an empty file meaningfully)
- Poll interval default is 30 seconds — sufficient gap between size checks for all expected document sizes

**Implementation**:
```python
# FileEvent tracks size progression
if event.size_at_previous_poll == event.current_size and event.current_size > 0:
    event.write_complete = True  # safe to upload
```

**Alternatives considered**:
- Locking file detection (try to open exclusive) — rejected: SFTP protocol does not expose lock state
- Fixed delay after detection — rejected: non-deterministic; fails for large files
- Checking mtime stability — considered but size is more reliable; mtime can lag on Windows SMB/SFTP bridges

---

## R-004: Retry Strategy

**Question**: What retry library and strategy should be used for S3 upload failures (FR-006) and Lambda-to-engine REST failures (FR-007)?

**Decision**: `tenacity` with exponential backoff + jitter

**Rationale**:
- `tenacity` is the most widely adopted retry library in the Python ecosystem; clean decorator API; supports `wait_exponential`, `wait_random`, `stop_after_attempt`, and callback hooks for logging
- Exponential backoff with jitter prevents thundering-herd when multiple concurrent uploads fail simultaneously (e.g., S3 briefly unavailable)
- Configurable `max_retries` and `backoff_base` via settings (FR-012)
- `tenacity` works identically for sync code (Lambda handler) and async code (upload service)

**Configuration**:
```python
from tenacity import retry, wait_exponential, stop_after_attempt, before_sleep_log

@retry(
    wait=wait_exponential(multiplier=settings.backoff_base, min=1, max=60),
    stop=stop_after_attempt(settings.max_retries),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
async def upload(...): ...
```

**Alternatives considered**:
- `backoff` library — considered; simpler API but less flexible for async and less maintained
- Manual retry loops — rejected: verbose, harder to test, easy to get wrong under concurrent load

---

## R-005: MongoDB Persistence with Motor

**Question**: How should the `UploadRecord` store be implemented using MongoDB in an async Python service?

**Decision**: `motor` (async MongoDB driver) with `mongomock-motor` for unit/BDD test isolation

**Rationale**:
- `motor` is the official async Python driver for MongoDB, built on top of `pymongo`; fully compatible with `asyncio`
- The `upload_records` collection stores `FileEvent` and upload outcome; a unique index on `filename` provides O(log n) deduplication lookups (FR-004)
- `mongomock-motor` provides an in-memory MongoDB mock that implements the same `motor` async API — unit/BDD tests run without a running MongoDB server; no Docker required for fast tests
- Integration tests use the real MongoDB container the user already has provisioned

**Schema** (document shape in `upload_records`):
```json
{
  "_id": ObjectId,
  "filename": "payment_instruction_001.pdf",
  "remote_sftp_path": "/uploads/payment_instruction_001.pdf",
  "s3_bucket": "mmp-ai-documents",
  "s3_key": "ingest/payment_instruction_001.pdf",
  "sha256_hash": "e3b0c44298fc1c14...",
  "file_size_bytes": 204800,
  "detection_timestamp": ISODate,
  "upload_timestamp": ISODate,
  "status": "success",
  "retry_count": 0
}
```

**Unique index**:
```python
await collection.create_index("filename", unique=True)
```

**Alternatives considered**:
- `aiosqlite` (SQLite) — rejected at user direction; project-wide persistence is MongoDB
- `beanie` (ODM on top of motor) — considered; adds schema-validation convenience but is an unnecessary abstraction for a single-collection service

---

## R-006: Lambda Bridge Pattern for LocalStack Free Tier

**Question**: Does the S3 → Lambda → REST pattern work in LocalStack community (free) tier, and what are the wiring steps?

**Decision**: Yes. LocalStack community supports S3 event notifications to Lambda. Wire via `boto3` setup script.

**Rationale**:
- LocalStack community edition supports: S3 bucket creation, Lambda function deployment (Python 3.11 runtime), and S3 event notification configuration (`put_bucket_notification_configuration`) — all three required for this pattern
- Lambda is invoked synchronously by LocalStack when an object is created in S3
- The Lambda receives a standard AWS S3 event JSON payload — identical format between LocalStack and real AWS; no branching needed
- Lambda `handler.py` calls `httpx.post` to the engine's REST endpoint; in local dev, the engine URL is `http://host.docker.internal:{port}` or the Docker network service name

**LocalStack wiring script steps**:
```python
# 1. Create S3 bucket
s3.create_bucket(Bucket="mmp-ai-documents")

# 2. Deploy Lambda (zip handler.py + requirements)
lambda_client.create_function(
    FunctionName="mmp-ai-s3-trigger",
    Runtime="python3.11",
    Handler="handler.lambda_handler",
    Code={"ZipFile": zip_bytes},
    ...
)

# 3. Grant S3 permission to invoke Lambda
lambda_client.add_permission(
    FunctionName="mmp-ai-s3-trigger",
    StatementId="s3-invoke",
    Action="lambda:InvokeFunction",
    Principal="s3.amazonaws.com",
    SourceArn=f"arn:aws:s3:::mmp-ai-documents",
)

# 4. Configure S3 notification
s3.put_bucket_notification_configuration(
    Bucket="mmp-ai-documents",
    NotificationConfiguration={
        "LambdaFunctionConfigurations": [{
            "LambdaFunctionArn": lambda_arn,
            "Events": ["s3:ObjectCreated:*"],
        }]
    },
)
```

**Alternatives considered**:
- S3 → SQS → engine polling — considered initially; rejected in favour of Lambda push model per user decision (simpler engine integration, no polling loop needed in engine)
- S3 → SNS → Lambda fan-out — rejected: SNS is a paid LocalStack Pro feature; overkill for single consumer

---

## R-007: BDD Framework Selection

**Question**: Which BDD framework integrates best with `pytest` for this Python service?

**Decision**: `pytest-bdd`

**Rationale**:
- `pytest-bdd` integrates directly with `pytest` — same runner, same fixtures, same `conftest.py`; no separate test runner or configuration needed
- Gherkin `.feature` files map 1:1 with the acceptance scenarios in the spec (US1, US2, US3) — scenarios can be copied/adapted directly from `spec.md`
- `@given`, `@when`, `@then` step decorators compose cleanly with `pytest` fixtures (including `moto` mock and `mongomock-motor` mock)
- Async step support via `pytest-asyncio` + `pytest-bdd` is stable

**Alternatives considered**:
- `behave` — rejected: separate runner from pytest; fixtures not compatible; more ceremony
- `lettuce` — rejected: unmaintained
- No BDD, acceptance tests only — rejected: constitution VIII mandates BDD

---

## R-008: Observability Stack (OTel + Prometheus)

**Question**: How should OpenTelemetry and Prometheus be wired into this service per constitution VII?

**Decision**: OTel SDK with OTLP exporter (configurable) + `prometheus-client` with HTTP server on `/metrics`

**Rationale**:
- `opentelemetry-sdk` with `opentelemetry-exporter-otlp` allows the service to export traces/metrics to any OTLP-compatible collector (Jaeger, Grafana Alloy, etc.) — endpoint configurable via `OTEL_EXPORTER_OTLP_ENDPOINT` env var (standard OTel env convention)
- `prometheus-client` exposes operational counters and histograms at `GET /-/metrics` on the health server port (8080)
- Key metrics: `files_detected_total`, `upload_success_total`, `upload_failure_total`, `sftp_reconnect_total`, `sftp_poll_duration_seconds` (histogram)
- Health endpoint `GET /health` returns `{"status": "ok", "mongo": "connected", "sftp": "connected"}` — liveness + dependency readiness in one response

**Alternatives considered**:
- Prometheus push gateway — rejected: pull model (scrape) is the standard pattern; push gateway is for batch jobs
- Datadog/New Relic SDKs — rejected: vendor lock-in; constitution IX prefers vendor-neutral

---

## Summary of Decisions

| # | Topic | Decision |
|---|---|---|
| R-001 | SFTP client | `asyncssh` (async-native) |
| R-002 | S3 client + LocalStack | `boto3` with configurable `endpoint_url` |
| R-003 | File completeness detection | Size-stability across 2 polls |
| R-004 | Retry strategy | `tenacity` with exponential backoff + jitter |
| R-005 | MongoDB persistence | `motor` + `mongomock-motor` for tests |
| R-006 | Lambda LocalStack wiring | S3→Lambda via `put_bucket_notification_configuration` |
| R-007 | BDD framework | `pytest-bdd` integrated with `pytest` |
| R-008 | Observability | OTel SDK (OTLP) + `prometheus-client` on port 8080 |
