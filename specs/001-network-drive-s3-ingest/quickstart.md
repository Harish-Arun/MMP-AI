# Quickstart: 001 Network Drive S3 Ingest — Local Development with LocalStack

**Branch**: `001-network-drive-s3-ingest` | **Date**: 2026-03-11

This guide gets the ingestion service running locally end-to-end using LocalStack (S3 + Lambda), a local MongoDB container, and a local SFTP server.

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Docker Desktop | ≥ 4.x | https://www.docker.com/products/docker-desktop |
| Python | 3.11+ | https://www.python.org/downloads/ |
| AWS CLI v2 | latest | https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html |
| `awslocal` (optional shorthand) | latest | `pip install awscli-local` |

Ensure Docker Desktop is running before proceeding.

---

## Step 1: Start LocalStack + MongoDB

Both services are defined in `docker-compose.localstack.yml`. Start them together:

```cmd
cd ingestion-service
docker compose -f docker-compose.localstack.yml up localstack mongodb -d
```

Verify LocalStack is ready (wait ~15 seconds):
```cmd
curl http://localhost:4566/_localstack/health
rem Expect: {"services": {"s3": "running", "lambda": "available", ...}}
```

> LocalStack may show status `"unhealthy"` in `docker ps` — this is a Docker healthcheck path mismatch and can be ignored. If `curl` returns the health JSON, it is working.

Verify MongoDB:
```cmd
docker compose -f docker-compose.localstack.yml exec mongodb mongosh --eval "db.runCommand({ping:1})"
rem Expect: { ok: 1 }
```

---

## Step 1b: Start Observability Stack (optional but recommended)

Starts an OTel Collector, Jaeger (traces), Prometheus (metrics), and Grafana (dashboards).

```cmd
docker compose -f docker-compose.localstack.yml up otel-collector jaeger prometheus grafana -d
```

| UI | URL | What you see |
|---|---|---|
| Jaeger | http://localhost:16686 | Per-file traces: `file.process` → `s3.upload` → `mongodb.save` |
| Prometheus | http://localhost:9090 | Raw metrics: `upload_success_total`, `sftp_poll_duration_seconds`, etc. |
| Grafana | http://localhost:3000 | Dashboards — Prometheus and Jaeger datasources pre-wired |

Traces are enabled by default in `.env`:
```dotenv
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```
To disable (no-op mode), blank it: `OTEL_EXPORTER_OTLP_ENDPOINT=`

---

## Step 2: Start a Local SFTP Server

```cmd
mkdir test-uploads
docker run -d --name sftp-test -p 2222:22 -v "%cd%\test-uploads:/home/testuser/uploads" atmoz/sftp testuser:testpassword:::uploads
```

---

## Step 3: Install Python Dependencies

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

---

## Step 4: Configure Environment

```cmd
copy .env.example .env
notepad .env
```

Set these values:
```dotenv
SFTP_HOST=localhost
SFTP_PORT=2222
SFTP_USERNAME=testuser
SFTP_PASSWORD=testpassword
SFTP_KEY_PATH=
SFTP_REMOTE_DIR=/uploads
SFTP_POLL_INTERVAL_S=10

S3_BUCKET=mmp-ai-documents
S3_KEY_PREFIX=ingest
S3_ENDPOINT_URL=http://localhost:4566
AWS_REGION=eu-west-2
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test

MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=mmp_ai

HEALTH_PORT=8080
EXTENSION_ALLOWLIST=[".pdf"]
```

> **Important**: ensure `SFTP_KEY_PATH=` is blank (not `/path/to/id_rsa`), otherwise the service will try to load a non-existent key file.

---

## Step 5: Provision LocalStack (S3 Bucket + Lambda + DLQ)

Run once after LocalStack starts. Re-running is safe (idempotent) — it will update the Lambda code and env vars if they have changed:

```cmd
python scripts\setup_localstack.py
```

Expected output:
```
[1/6] S3 bucket created: mmp-ai-documents
[2/6] Lambda deployed: arn:aws:lambda:us-east-1:000000000000:function:mmp-ai-s3-trigger
[3/6] Lambda S3 invoke permission added
[4/6] S3 → Lambda notification wired: s3:ObjectCreated:* → ...
[5/6] SQS DLQ created: arn:aws:sqs:us-east-1:000000000000:mmp-ai-dlq
[6/6] DLQ attached to Lambda: arn:aws:sqs:us-east-1:000000000000:mmp-ai-dlq
```

> The script installs Lambda dependencies (`httpx`, `tenacity`, `structlog`) into the zip automatically. First run takes ~30 seconds.

Verify:
```cmd
rem Option A: aws CLI (explicit LocalStack endpoint)
aws --endpoint-url=http://localhost:4566 s3 ls
aws --endpoint-url=http://localhost:4566 lambda list-functions

rem Option B: awslocal shorthand
awslocal s3 ls
awslocal lambda list-functions
```

---

## Step 6: Start the Engine (mock or real)

The Lambda POSTs a `WorkflowTriggerNotification` to the engine at `ENGINE_REST_URL` when a file lands in S3.

### Option A — Mock engine (local dev, default)

The mock just prints the trigger payload and returns 202. Good for verifying the end-to-end pipeline without needing the real engine.

```cmd
rem Open a second CMD window
python scripts\mock_engine.py
rem Listening on http://0.0.0.0:8000
```

The Lambda is pre-configured to call `http://host.docker.internal:8000` which routes to this mock.

### Option B — Real engine endpoint

When the mmp-ai-engine is deployed (feature 002-004), update `ENGINE_REST_URL` in `setup_localstack.py` then re-provision:

1. Open `scripts\setup_localstack.py` and change the default:
   ```python
   # Near the top — change this constant:
   ENGINE_REST_URL = os.environ.get("ENGINE_REST_URL", "http://host.docker.internal:8000")
   ```
   Either edit the default, or just set an env var before running:
   ```cmd
   set ENGINE_REST_URL=https://engine.your-domain.com
   python scripts\setup_localstack.py
   ```

2. The script will update the Lambda env var live — no restart of LocalStack needed.

3. Verify the Lambda now has the new URL:
   ```cmd
   rem Option A: aws CLI
   aws --endpoint-url=http://localhost:4566 lambda get-function-configuration --function-name mmp-ai-s3-trigger --query "Environment.Variables"

   rem Option B: awslocal
   awslocal lambda get-function-configuration --function-name mmp-ai-s3-trigger --query "Environment.Variables"
   ```

> **On real AWS**: set `ENGINE_REST_URL` as a Lambda environment variable via the AWS Console, `aws lambda update-function-configuration`, or your Terraform/CDK config. No code change required — the Lambda reads it at runtime.

---

## Step 7: Start the Ingestion Service

```cmd
python main.py
```

Expected startup logs (JSON):
```json
{"event": "telemetry_initialised", ...}
{"event": "store_initialised", "collection": "upload_records", ...}
{"event": "sftp_connecting", "host": "localhost", "port": 2222, ...}
{"event": "health_server_started", "port": 8080, ...}
{"event": "sftp_connected", "host": "localhost", ...}
```

Verify health:
```cmd
curl http://localhost:8080/health
```

> On Windows, `Ctrl+C` cleanly stops the service.

---

## Step 8: Smoke Test — Drop a PDF

Copy any PDF into `test-uploads\` (simulating a file arriving on the network drive):

```cmd
copy "C:\path\to\any.pdf" "test-uploads\payment_001.pdf"
```

Within ~20 seconds (two poll cycles for size-stability) you will see in the service logs:
```json
{"event": "file_detected", "filename": "payment_001.pdf", "size": 98070, ...}
{"event": "file_write_complete", "filename": "payment_001.pdf", ...}
{"event": "s3_upload_success", "filename": "payment_001.pdf", "s3_key": "ingest/payment_001.pdf", "sha256": "...", ...}
{"event": "record_saved", "filename": "payment_001.pdf", "status": "success", ...}
{"event": "file_processed", "filename": "payment_001.pdf", "s3_key": "ingest/payment_001.pdf", ...}
```

And in the mock engine window:
```json
[mock-engine] Trigger received:
{
  "s3_bucket": "mmp-ai-documents",
  "s3_key": "ingest/payment_001.pdf",
  "filename": "payment_001.pdf",
  "sha256_hash": "...",
  ...
}
```

Verify S3:
```cmd
rem Option A: aws CLI
aws --endpoint-url=http://localhost:4566 s3 ls s3://mmp-ai-documents/ingest/

rem Option B: awslocal
awslocal s3 ls s3://mmp-ai-documents/ingest/
```

Verify MongoDB:
```cmd
docker compose -f docker-compose.localstack.yml exec mongodb mongosh mmp_ai --eval "db.upload_records.find({}, {filename:1, sha256_hash:1, status:1, _id:0}).pretty()"
```

---

## Step 9: Test Deduplication

Files already uploaded are silently skipped on subsequent polls — no re-upload, no log spam. The service keeps an in-memory cache so MongoDB is not queried on every poll for known files.

To verify: drop the same filename again. No new S3 object or MongoDB record will be created.

---

## Step 10: Run All Tests

```cmd
rem Unit tests
.venv\Scripts\pytest tests\unit -v --cov=src --cov-report=term-missing

rem BDD tests
.venv\Scripts\pytest tests\bdd -v

rem All tests
.venv\Scripts\pytest tests\unit tests\bdd -v
```

---

## Tear Down

```cmd
docker compose -f docker-compose.localstack.yml down
docker stop sftp-test && docker rm sftp-test
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `SFTP connection refused` | SFTP container not started | Run Step 2 |
| `No such file or directory: '\\path\\to\\id_rsa'` | `SFTP_KEY_PATH` not blanked in `.env` | Set `SFTP_KEY_PATH=` |
| `S3 bucket not found` | Setup script not run | Run Step 5 |
| `MongoDB connection refused` | MongoDB not started | Run Step 1 |
| `No module named 'httpx'` in Lambda | Old zip without dependencies | Re-run `setup_localstack.py` |
| Lambda `404 HeadObject` | S3 key URL-encoding mismatch | Fixed in `handler.py` — re-run setup |
| Lambda `EndpointConnectionError localhost` | `S3_ENDPOINT_URL` pointed at localhost | Fixed — `AWS_ENDPOINT_URL` injected by LocalStack |
| `NotImplementedError` on startup (Windows) | `loop.add_signal_handler` Unix-only | Fixed in `main.py` |
| Duplicate warnings flooding logs | Files stay on SFTP permanently | Expected — fixed to silent after first detection |
| File not detected after 60s | Extension not in allowlist | Check `EXTENSION_ALLOWLIST` in `.env` |
| `InternalError: Version cannot be updated if old one is not running` | Lambda in `Pending` state when DLQ update runs | Fixed — `function_active` waiter added before step 6 |
| No traces in Jaeger | OTel collector not running or endpoint blank | Start observability stack (Step 1b); check `OTEL_EXPORTER_OTLP_ENDPOINT` in `.env` |
| Lambda logs show both success and error around same time | Logs are interleaved from multiple warm Lambda containers/invocations | Correlate by `request_id`; use `engine_notify_failed` vs `engine_notified` events to determine final result per invocation |
