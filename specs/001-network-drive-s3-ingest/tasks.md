# Tasks: 001 Network Drive S3 Ingest

**Input**: Design documents from `specs/001-network-drive-s3-ingest/`  
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/lambda-to-engine.md](contracts/lambda-to-engine.md)

---

## Phase 1: Setup

**Purpose**: Create the `ingestion-service/` project skeleton and pin all dependencies before any implementation begins.

- [X] T001 Create `ingestion-service/` directory tree with all subdirectories and empty `__init__.py` files per project structure in plan.md (`src/config/`, `src/sftp/`, `src/uploader/`, `src/store/`, `src/models/`, `src/telemetry/`, `lambda/`, `scripts/`, `tests/unit/`, `tests/integration/`, `tests/bdd/features/`, `tests/bdd/steps/`)
- [X] T002 [P] Write `ingestion-service/requirements.txt` with pinned versions: `asyncssh>=2.14.0`, `boto3>=1.34.0`, `motor>=3.3.0`, `tenacity>=8.2.0`, `pydantic-settings>=2.1.0`, `pyyaml>=6.0`, `structlog>=24.1.0`, `opentelemetry-api>=1.23.0`, `opentelemetry-sdk>=1.23.0`, `opentelemetry-exporter-otlp>=1.23.0`, `prometheus-client>=0.20.0`, `aiohttp>=3.9.0`, `httpx>=0.26.0`
- [X] T003 [P] Write `ingestion-service/requirements-dev.txt`: `pytest>=8.0.0`, `pytest-asyncio>=0.23.0`, `pytest-bdd>=7.0.0`, `pytest-cov>=4.1.0`, `moto[s3]>=5.0.0`, `mongomock-motor>=0.0.21`, `ruff>=0.3.0`
- [X] T004 [P] Write `ingestion-service/.env.example` with all configurable parameters from `Settings` model (SFTP, S3, MongoDB, retry, allowlist, health port) — no real secrets, placeholder values only
- [X] T032 [P] Write `ingestion-service/pyproject.toml` — `[tool.pytest.ini_options]`: `asyncio_mode = "auto"` (**required** for `pytest-asyncio`; without this, async test coroutines are collected as synchronous and silently pass without being awaited), `testpaths = ["tests"]`, `addopts = "--strict-markers"`, `markers = ["bdd: marks BDD tests"]`; `[tool.ruff.lint]` targeting `src/` and `tests/` (G4 fix)
- [X] T033 [P] Write `ingestion-service/.gitignore` — exclude: `.env`, `__pycache__/`, `*.pyc`, `.coverage`, `htmlcov/`, `dist/`, `*.egg-info/`, `.pytest_cache/`, `*.zip` (Lambda deployment packages); prevents accidental commit of SFTP credentials or AWS secrets (constitution IX, G5 fix)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core shared infrastructure that every user story implementation depends on. No US work can start until this phase is complete.

**⚠️ CRITICAL**: `Settings`, all Pydantic models, the MongoDB store, and telemetry must be in place before SFTP watcher, uploader, or Lambda can be written.

- [X] T005 Write `ingestion-service/src/config/settings.py` — full `pydantic-settings` `Settings` class per data-model.md §1: SFTP fields (host, port, username, password, key_path, remote_dir, `sftp_poll_interval_s`), S3 fields (`s3_bucket`, `s3_key_prefix`, `s3_endpoint_url`, aws_region), retry fields (`sftp_max_reconnect_attempts`, `s3_max_upload_retries`, backoff_base), extension_allowlist, MongoDB fields (mongo_uri, mongo_db_name), health_port, otel_exporter_otlp_endpoint; add `model_validator` requiring at least one of `sftp_password` / `sftp_key_path`
- [X] T006 [P] Write `ingestion-service/config.yaml` — default values only (no secrets): sftp_poll_interval_s: 30, extension_allowlist: [".pdf"], sftp_max_reconnect_attempts: 5, s3_max_upload_retries: 5, backoff_base: 2.0, s3_key_prefix: "ingest", aws_region: "eu-west-2", health_port: 8080, mongo_db_name: "mmp_ai"
- [X] T007 [P] Write `ingestion-service/src/models/models.py` — Pydantic v2 schemas per data-model.md: `UploadStatus` enum (pending/success/failed), `FileEvent` (filename, remote_sftp_path, file_size_bytes, size_at_previous_poll, detection_timestamp, write_complete_timestamp, `is_write_complete` property), `UploadRecord` (all fields including sha256_hash, failure_reason, retry_count), `WorkflowTriggerNotification` (s3_bucket, s3_key, filename, file_size_bytes, detection_timestamp, sha256_hash)
- [X] T008 Write `ingestion-service/src/store/record_store.py` — `UploadRecordStore` class: `__init__(settings)` creates `motor.AsyncIOMotorClient`; `async init()` creates unique index on `filename`; `async is_known(filename) -> bool`; `async save(record: UploadRecord)` with `DuplicateKeyError` → WARNING log; `async get_all() -> list[UploadRecord]` (depends on T005, T007)
- [X] T009 [P] Write `ingestion-service/src/telemetry/setup.py` — `init_telemetry(settings)`: OTel `TracerProvider` + `MeterProvider` with OTLP exporter (if endpoint configured); Prometheus `Counter` for `files_detected_total{status}`, `upload_success_total`, `upload_failure_total`, `sftp_reconnect_total`; `Histogram` for `sftp_poll_duration_seconds`; export `get_tracer()` and counter accessors
- [X] T010 Write `ingestion-service/Dockerfile` — multi-stage: `FROM python:3.11-slim AS builder` installs deps to `/install`; final stage copies `/install` + source; `HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8080/health`; `CMD ["python", "main.py"]`
- [X] T037 [P] Write `ingestion-service/src/exceptions.py` — define `class UploadFailedError(Exception): pass` and `class FileDisappearedError(Exception): pass`; `UploadFailedError` is raised by `S3Uploader.upload()` (T017) when all `s3_max_upload_retries` are exhausted; `FileDisappearedError` is raised by `S3Uploader.upload()` on `asyncssh.SFTPNoSuchFile` (file gone before download); both are asserted in T014 unit tests; defining here in Phase 2 ensures all Phase 3+ tasks can `from src.exceptions import UploadFailedError, FileDisappearedError` without `ModuleNotFoundError` (NI2 fix)

**Checkpoint**: Foundation complete — US1, US2, US3 can now proceed independently.

---

## Phase 3: User Story 1 — Automatic File Detection and S3 Upload (Priority: P1) 🎯 MVP

**Goal**: SFTP-poll the Windows network drive, detect new `.pdf` files using size-stability check, compute SHA-256, upload to S3, persist `UploadRecord` to MongoDB, and prevent duplicate uploads.

**Independent Test**: Start the service against a running LocalStack S3 + SFTP test server. Drop a `.pdf` file on SFTP. Within 60 seconds assert the S3 object exists and an `upload_records` document appears in MongoDB with `status: "success"`. Drop the same filename again and assert only one MongoDB record exists (no second upload).

### BDD Tests for User Story 1

- [X] T011 [P] [US1] Write `ingestion-service/tests/bdd/features/file_detection.feature` — Gherkin scenarios from spec US1: (1) new PDF detected → uploaded within 60s → MongoDB record created; (2) file still being written → upload deferred until size-stable; (3) same filename placed again → duplicate WARNING, no re-upload; (4) zero-byte file across 2 polls → WARNING, not uploaded; (5) non-PDF extension → silently ignored, no upload
- [X] T012 [P] [US1] Write `ingestion-service/tests/bdd/features/upload.feature` — Gherkin scenarios: (1) upload succeeds → SHA-256 stored in UploadRecord and S3 metadata; (2) S3 returns 503 on first 2 attempts → retries → succeeds → retry_count stored; (3) all retries exhausted → UploadFailedError raised → structured ERROR log with filename, reason, retry_count

### Unit Tests for User Story 1

- [X] T013 [P] [US1] Write `ingestion-service/tests/unit/test_watcher.py` — mock `asyncssh.connect` + directory listing; assert: new file added to `_pending` on first detection; size unchanged across 2 polls → `is_write_complete=True`; size changed → still in `_pending`; zero-byte file → WARNING log after 2 polls; extension not in allowlist → silently skipped; `_connect_with_retry` re-attempts on `asyncssh.DisconnectError`
- [X] T014 [P] [US1] Write `ingestion-service/tests/unit/test_uploader.py` — `@mock_aws` from `moto`: assert S3 object created at correct bucket/key; assert `sha256_hash` in S3 object Metadata matches file content; assert retry decorator fires on `ClientError(503)`, succeeds on second attempt; assert `UploadFailedError` (from `src.exceptions`) raised after `s3_max_upload_retries` attempts exhausted; assert `FileDisappearedError` raised (not retried) when `asyncssh.SFTPNoSuchFile` is thrown during download
- [X] T015 [P] [US1] Write `ingestion-service/tests/unit/test_record_store.py` — `mongomock-motor`: `is_known("file.pdf")` returns `False` before save; `is_known` returns `True` after `save()`; second `save()` call with same filename does not raise — logs WARNING instead; `get_all()` returns all saved records

### Implementation for User Story 1

- [X] T016 [US1] Write `ingestion-service/src/sftp/watcher.py` — `SFTPWatcher(settings, record_store)`: `async def poll_forever()` async generator — the **public API** called from `main.py`; records poll start/end time on each iteration and calls `sftp_poll_duration_seconds.observe(elapsed)` (histogram registered in T009, instrumented here — A1 fix); internally calls `async _poll()` which lists remote dir → filters extension allowlist → checks RecordStore (`is_known`) → manages `_pending` dict with size-stability tracking (`FileEvent.is_write_complete`) → yields write-complete `FileEvent` objects; `async _connect_with_retry()` uses `tenacity` exponential backoff with `settings.sftp_max_reconnect_attempts` stop condition; structured `structlog` JSON log at every state transition (detected, growing, write-complete, duplicate-skip, zero-byte-skip, sftp-reconnect) (depends on T005, T007, T008, T009)
- [X] T017 [P] [US1] Write `ingestion-service/src/uploader/s3_uploader.py` — `S3Uploader(settings)`: `boto3.client('s3', endpoint_url=settings.s3_endpoint_url or None)`; `async upload(file_event, sftp_conn) -> UploadRecord` with `@retry(wait_exponential, stop_after_attempt(settings.s3_max_upload_retries))` from tenacity; stream-reads bytes from SFTP — on `asyncssh.SFTPNoSuchFile` catch **before** the retry decorator fires, log WARNING `"file_disappeared_before_download"` and raise `FileDisappearedError` (not retried — file is gone, caller removes from `_pending`); computes SHA-256 while streaming; calls `s3.put_object` with `Metadata={"sha256": hash, "detection_timestamp": ..., "original_filename": filename}`; returns `UploadRecord(status=SUCCESS)`; raises `UploadFailedError` on S3 retry exhaustion (depends on T005, T007, T009)
- [X] T018 [US1] Write `ingestion-service/tests/conftest.py` — shared pytest fixtures: `settings()` returning `Settings` with test values; `mock_s3()` using `moto` `mock_aws` decorator; `mock_mongo()` using `mongomock-motor`; `sample_file_event()` factory fixture
- [X] T019 [US1] Write `ingestion-service/tests/bdd/steps/step_defs.py` — `pytest-bdd` step definitions for `file_detection.feature` and `upload.feature` Gherkin steps; wire `@given/@when/@then` to `SFTPWatcher` and `S3Uploader` via `mongomock-motor` + `moto` fixtures from conftest.py (depends on T011, T012, T016, T017, T018)

**Checkpoint**: US1 complete — SFTP → S3 upload pipeline independently testable. `pytest tests/unit -v` and `pytest tests/bdd -v` should all pass at this point.

---

## Phase 4: User Story 2 — Workflow Trigger Notification (Priority: P2)

**Goal**: On every successful S3 upload, S3 automatically invokes the Lambda bridge function which POSTs to the mmp-ai-engine REST API with the `WorkflowTriggerNotification` payload. At-least-once delivery guaranteed via DLQ.

**Independent Test**: Upload a test PDF directly to LocalStack S3 (bypassing SFTP). Assert that a mocked engine HTTP server receives `POST /api/v1/workflows/trigger` with correct payload (s3_bucket, s3_key, filename, sha256_hash). Assert that 5xx engine responses are retried; 4xx/409 responses are not retried.

### BDD Tests for User Story 2

- [X] T020 [P] [US2] Write `ingestion-service/tests/bdd/features/lambda_notification.feature` — Gherkin scenarios from spec US2: (1) successful S3 upload → Lambda invoked → engine POST sent with correct payload; (2) engine returns 503 → Lambda retries → succeeds on next attempt; (3) engine returns 400 → non-retryable → WARNING log, no DLQ; (4) all retries exhausted on 5xx → Lambda invocation fails → DLQ captures event; (5) S3 upload failed → no Lambda invocation

### Integration Tests for User Story 2

- [X] T021 [US2] Write `ingestion-service/tests/integration/conftest.py` — `@pytest.fixture(scope="session")`: verify LocalStack running at `http://localhost:4566`; import and call `provision_localstack()` from `scripts/setup_localstack.py` (T027) — this single function performs S3 bucket creation, Lambda deployment, S3 → Lambda notification wiring, and SQS DLQ configuration (T034), avoiding re-implementation of provisioning logic (D1 fix); yield LocalStack-backed boto3 clients; teardown: delete S3 bucket contents + bucket, delete Lambda, delete SQS queue on session end (depends on T027, T034)
- [X] T022 [US2] Write `ingestion-service/tests/integration/test_pipeline.py` — test 1: upload test PDF via `S3Uploader` → assert S3 object exists → assert `upload_records` MongoDB doc with `status="success"` and `sha256_hash` set; test 2: start `aiohttp.web` mock engine server → trigger Lambda via S3 object creation → assert mock server received POST matching `WorkflowTriggerNotification` schema from `contracts/lambda-to-engine.md`; test 3: upload same filename again → assert `is_known=True`, no second S3 object version, no second engine POST (depends on T021)

### Implementation for User Story 2

- [X] T023 [US2] Write `ingestion-service/lambda/handler.py` — `lambda_handler(event, context)`: parse S3 event `event["Records"][0]["s3"]` for bucket, key, size; retrieve `sha256` and `detection_timestamp` from S3 object `Metadata` via `s3.head_object`; reconstruct `filename` by stripping `s3_key_prefix`; add `X-Request-Id` header (new UUID per invocation, per contract); call `_post_to_engine(payload)` decorated with `@retry(wait_exponential, stop_after_attempt(MAX_RETRIES))`; HTTP 400/409 → log WARNING + return (non-retryable, no DLQ); HTTP 5xx / timeout → `raise_for_status()` → retry → on exhaustion raise → DLQ captures; all structured logs to stdout (CloudWatch JSON via structlog); bind `sha256_hash` and `filename` as structlog context fields so Lambda notification events share a traceable key with the ingestion service's `upload_records` documents (cross-component log continuity for FR-009, I6 fix) (depends on T007)
- [X] T024 [P] [US2] Write `ingestion-service/lambda/requirements.txt` — `httpx>=0.26.0`, `tenacity>=8.2.0`, `structlog>=24.1.0`
- [X] T025 [US2] Extend `ingestion-service/tests/bdd/steps/step_defs.py` with step definitions for `lambda_notification.feature` — wire `@given/@when/@then` to `lambda/handler.py` invoked directly in tests; use `aiohttp.web` test server as engine mock; assert payload shape against `WorkflowTriggerNotification` model (depends on T020, T023)
- [X] T034 [US2] Extend `ingestion-service/scripts/setup_localstack.py` to add SQS DLQ provisioning inside `provision_localstack()`: step (6) `sqs.create_queue(QueueName="mmp-ai-dlq")` → retrieve queue ARN; step (7) `lambda_client.update_function_configuration(FunctionName="mmp-ai-s3-trigger", DeadLetterConfig={"TargetArn": dlq_arn})`; print DLQ ARN on success; satisfies FR-007 MUST "DLQ MUST be configured on the Lambda to prevent silent notification loss"; note: T027 (setup_localstack.py base) only depends on T001 and can be written as early as Phase 2 to unblock T034 and integration tests sooner (depends on T027)

**Checkpoint**: US2 complete — S3 → Lambda → engine POST pipeline testable independently with LocalStack. `pytest tests/integration -v` should pass.

---

## Phase 5: User Story 3 — Upload Visibility and Error Alerting (Priority: P3)

**Goal**: Operations staff can monitor file processing status via structured JSON logs and Prometheus metrics. All failures produce structured ERROR logs with filename, reason, timestamp, and retry count. Service exposes `/health` and `/-/metrics` HTTP endpoints.

**Independent Test**: Start the service with an unreachable SFTP host. Assert that SFTP connection failures produce structured ERROR log entries. Assert `GET /health` returns 200 with `{"status": "ok"}`. Assert `GET /-/metrics` returns Prometheus text with `sftp_reconnect_total` counter incremented.

### Implementation for User Story 3

- [X] T026 [US3] Write `ingestion-service/main.py` — asyncio entry point: load `Settings`; init `UploadRecordStore` + `await store.init()`; init `SFTPWatcher(settings, store)` and `S3Uploader(settings)`; `async poll_loop()`: `async for file_event in watcher.poll_forever()` → `upload()` → `store.save()` → increment `upload_success_total` counter; `async health_server()`: `aiohttp.web` app on `settings.health_port` with `GET /health` (returns `{"status":"ok","sftp":"connected","mongo":"connected","uptime_seconds":...}`) and `GET /-/metrics` (returns Prometheus text via `prometheus_client.generate_latest()`); `asyncio.gather(poll_loop(), health_server())`; handle `SIGTERM` gracefully — cancel tasks, close SFTP connection, close MongoDB client (depends on T008, T009, T016, T017)
- [X] T027 [P] [US3] Write `ingestion-service/scripts/setup_localstack.py` — boto3 script (run once after LocalStack starts): (1) `s3.create_bucket(Bucket=settings.s3_bucket)`; (2) zip `lambda/handler.py` + install `lambda/requirements.txt` into deployment package in memory; (3) `lambda_client.create_function("mmp-ai-s3-trigger", Runtime="python3.11", Handler="handler.lambda_handler", Code={"ZipFile": zip_bytes}, Environment={"Variables": {"ENGINE_REST_URL": ..., "MAX_RETRIES": "3"}})`; (4) `lambda_client.add_permission(...)` grant S3; (5) `s3.put_bucket_notification_configuration(...)` wire `s3:ObjectCreated:*` → Lambda ARN; print confirmation for each step; **wrap all steps in a callable `provision_localstack()` function** so that the integration conftest (T021) can import and invoke it without re-implementing provisioning logic (D1 fix)
- [X] T028 [P] [US3] Write `ingestion-service/docker-compose.localstack.yml` — services: `localstack` (image: `localstack/localstack`, ports: `4566:4566`, env: `SERVICES=s3,lambda,sqs` `DEBUG=1`, volumes: `/var/run/docker.sock`); `mongodb` (image: `mongo:7`, ports: `27017:27017`); `ingestion-service` (build: `.`, `env_file: .env`, depends_on: localstack + mongodb, ports: `8080:8080`); `grafana` (image: `grafana/grafana:latest`, ports: `3000:3000`, anonymous auth enabled, pre-configured Prometheus datasource pointed at `http://ingestion-service:8080/-/metrics`) — satisfies constitution VII Grafana non-negotiable technology requirement; also create `ingestion-service/grafana/provisioning/datasources/prometheus.yml` containing `apiVersion: 1` and a Prometheus datasource entry (`name: Prometheus, type: prometheus, url: http://ingestion-service:8080/-/metrics, access: proxy`); add volume bind-mount `- ./grafana/provisioning:/etc/grafana/provisioning` to the grafana service definition in the compose yaml; without this provisioning file Grafana boots with zero datasources and no metrics will be visible (NI6 fix)

**Checkpoint**: US3 complete — service runs end-to-end with full observability. Manual smoke test per quickstart.md should pass.

---

## Final Phase: Polish & Cross-Cutting Concerns

- [X] T029 Run full test suite and confirm all layers pass: `pytest tests/unit -v --cov=src --cov-report=term-missing` (target ≥ 80% coverage), `pytest tests/bdd -v`, `pytest tests/integration -v` (requires LocalStack + MongoDB)
- [X] T030 [P] Verify `ingestion-service/Dockerfile` builds and container starts: `docker compose -f docker-compose.localstack.yml up --build ingestion-service` → `GET http://localhost:8080/health` returns `{"status":"ok"}` → `GET http://localhost:8080/-/metrics` returns Prometheus text
- [X] T031 [P] Run setup script and full manual smoke test per `quickstart.md`: drop a `.pdf` into SFTP test folder → S3 object created → MongoDB record saved → Lambda invoked → engine mock POST received → drop same file again → duplicate WARNING, no second upload
- [X] T035 [P] Write `ingestion-service/tests/unit/test_watcher_concurrency.py` — simulate 50 `FileEvent` objects all becoming write-complete in a single `_poll()` iteration; assert `poll_forever()` yields exactly 50 distinct `FileEvent` objects without dropping any; assert `upload_success_total` Prometheus counter increments by 50 after all uploads; validates SC-003 "handles ≥ 50 simultaneous file arrivals without loss" against the sequential async-generator design (G2 fix)
- [X] T036 Write `.github/workflows/ci.yml` — trigger on `push` and `pull_request` targeting branches `001-network-drive-s3-ingest` and `main`; jobs: (1) `lint` — `ruff check ingestion-service/src/ ingestion-service/tests/ ingestion-service/lambda/`; (2) `unit-tests` — `pytest ingestion-service/tests/unit -v --cov=ingestion-service/src --cov-report=xml --cov-fail-under=80`; (3) `bdd-tests` — `pytest ingestion-service/tests/bdd -v`; upload coverage XML as artifact; **integration tests excluded from CI** (require live LocalStack + MongoDB — run locally per quickstart.md); satisfies constitution VIII MUST "all tests MUST be automated within CI pipelines" (C1 fix)

---

## Dependencies

```
T001 → T002, T003, T004, T032, T033 (parallel)
T001 → T005, T006, T007 (parallel)
T005 + T007 → T008
T001 → T009, T010 (parallel with each other)

T008 + T009 → T016 (US1 starts)
T005 + T007 + T009 → T017 (parallel with T016)
T011 + T012 + T016 + T017 → T018 → T019

T001 → T027 (setup script only needs directory tree — can be written from Phase 2 onwards; does NOT depend on T023)
T027 → T034 (SQS DLQ extends setup script)
T007 → T023 (US2 Lambda handler)
T023 + T034 → T021 → T022   ← T021 imports provision_localstack() from T027+T034
T020 + T023 → T025

T008 + T009 + T016 + T017 → T026 (US3 starts)
T026 + T027 → T028

T019 + T022 + T026 → T029 → T030, T031, T035 (parallel)
T019 → T036 (CI written once unit+bdd tests exist)
```

### Parallel Execution Opportunities

**Phase 1 (fully parallel within)**:
- T002, T003, T004, T032, T033 — all independent config/setup files

**US1 (can run in parallel internally)**:
- T013, T014, T015 (unit tests) — fully independent, different files
- T016, T017 (watcher + uploader) — different files, both depend on T008

**US2 (T020, T024 parallel with US1 unit tests)**:
- T020, T024 (BDD feature file + lambda requirements) — no code dependencies
- Note: T021 (integration conftest) depends on T027 → T034 (sequential provisioning chain); implement Phase 5 T027+T034 before running integration tests

**US3 (T026, T028 writable in parallel)**:
- T026, T028 — different files; T028 also depends on T027 being complete
- T027 → T034 is a sequential chain; cannot be parallelised

**Final Phase (T030, T031, T035 parallel after T029 passes)**

---

## Implementation Strategy

**MVP Scope**: Complete Phase 1 + Phase 2 + Phase 3 (US1) first.  
This delivers a working SFTP → S3 upload pipeline with MongoDB deduplication — standalone value, independently testable, deployable without the engine integration.

**Increment 2**: Add Phase 4 (US2 — Lambda bridge).  
Closes the loop: files uploaded to S3 automatically trigger the mmp-ai-engine workflow.

**Increment 3**: Add Phase 5 (US3 — Visibility).  
Adds operational confidence: structured error logs, Prometheus metrics, health endpoint.

---

## Summary

| Metric | Value |
|---|---|
| Total tasks | 36 |
| US1 (P1 — MVP) tasks | 9 (T011–T019) |
| US2 (P2) tasks | 7 (T020–T025, T034) |
| US3 (P3) tasks | 3 (T026–T028) |
| Foundational tasks | 6 (T005–T010) |
| Setup tasks | 6 (T001–T004, T032–T033) |
| Polish/CI tasks | 5 (T029–T031, T035–T036) |
| Parallelizable [P] tasks | 21 |
