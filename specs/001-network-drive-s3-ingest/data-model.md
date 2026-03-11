# Data Model: 001 Network Drive S3 Ingest

**Branch**: `001-network-drive-s3-ingest` | **Date**: 2026-03-10  
**Derived from**: `spec.md` Key Entities + `research.md` R-005

All models are defined as **Pydantic v2** schemas. The `UploadRecord` is persisted to MongoDB via `motor`. All other models are in-memory value objects used during the poll → upload pipeline.

---

## 1. Settings

*Source: FR-012 — all parameters externally configurable*

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        yaml_file="config.yaml",
    )

    # SFTP
    sftp_host: str = Field(..., description="SFTP server hostname or IP")
    sftp_port: int = Field(22, description="SFTP server port")
    sftp_username: str = Field(..., description="SFTP login username")
    sftp_password: Optional[str] = Field(None, description="SFTP password (mutually exclusive with sftp_key_path)")
    sftp_key_path: Optional[str] = Field(None, description="Path to SSH private key file")
    sftp_remote_dir: str = Field(..., description="Remote directory to poll for new files")
    sftp_poll_interval_s: int = Field(30, description="Seconds between SFTP poll cycles")

    # S3
    s3_bucket: str = Field(..., description="Target S3 bucket name")
    s3_key_prefix: str = Field("ingest", description="S3 key prefix (folder) for uploaded files")
    s3_endpoint_url: Optional[str] = Field(None, description="Override S3 endpoint (e.g. http://localhost:4566 for LocalStack)")
    aws_region: str = Field("eu-west-2", description="AWS region")
    aws_access_key_id: Optional[str] = Field(None)
    aws_secret_access_key: Optional[str] = Field(None)

    # Retry
    sftp_max_reconnect_attempts: int = Field(5, description="Maximum SFTP reconnection attempts before giving up (exponential backoff)")
    s3_max_upload_retries: int = Field(5, description="Maximum S3 upload retry attempts per file (exponential backoff)")
    backoff_base: float = Field(2.0, description="Exponential backoff multiplier (seconds)")

    # File filtering
    extension_allowlist: List[str] = Field([".pdf"], description="Allowed file extensions (lowercase)")

    # MongoDB
    mongo_uri: str = Field("mongodb://localhost:27017", description="MongoDB connection string")
    mongo_db_name: str = Field("mmp_ai", description="MongoDB database name")

    # Observability
    health_port: int = Field(8080, description="Port for /health and /-/metrics endpoints")
    otel_exporter_otlp_endpoint: Optional[str] = Field(None, description="OTLP exporter endpoint (e.g. http://otel-collector:4317)")
```

**Validation rules**:
- At least one of `sftp_password` or `sftp_key_path` must be provided (validated in `model_validator`)
- `extension_allowlist` entries must start with `.` and be lowercase
- `s3_key_prefix` must not start or end with `/`

---

## 2. FileEvent

*Source: spec.md Key Entities — "Represents a file detected on the SFTP server during a poll cycle"*

In-memory value object; not persisted to MongoDB.

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class FileEvent(BaseModel):
    filename: str = Field(..., description="Bare filename (e.g. 'payment_001.pdf')")
    remote_sftp_path: str = Field(..., description="Full remote path on SFTP server")
    file_size_bytes: int = Field(..., description="File size at latest poll (bytes)")
    size_at_previous_poll: Optional[int] = Field(
        None,
        description="File size at previous poll cycle; None on first detection"
    )
    detection_timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when file was first detected"
    )
    write_complete_timestamp: Optional[datetime] = Field(
        None,
        description="UTC timestamp when size-stability check passed; None until confirmed complete"
    )

    @property
    def is_write_complete(self) -> bool:
        """True when file size is stable across two consecutive polls and non-zero."""
        return (
            self.size_at_previous_poll is not None
            and self.file_size_bytes == self.size_at_previous_poll
            and self.file_size_bytes > 0
        )
```

**State transitions**:
```
DETECTED (size_at_previous_poll=None)
    → GROWING (size changed between polls)
    → STABLE / WRITE_COMPLETE (size unchanged, > 0) → eligible for upload
    → ZERO_BYTE_WARNING (size=0 across 2 polls) → skipped with WARNING log
```

---

## 3. UploadRecord

*Source: spec.md Key Entities — "Tracks the outcome of an S3 upload attempt"*  
*Persisted to MongoDB collection `upload_records`*

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from enum import Enum


class UploadStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class UploadRecord(BaseModel):
    filename: str = Field(..., description="Bare filename — unique identifier for deduplication")
    remote_sftp_path: str = Field(..., description="Source path on SFTP server")
    s3_bucket: str = Field(..., description="S3 bucket the file was uploaded to")
    s3_key: str = Field(..., description="Full S3 object key (e.g. 'ingest/payment_001.pdf')")
    sha256_hash: str = Field(..., description="SHA-256 hex digest of the uploaded file content")
    file_size_bytes: int = Field(..., description="File size in bytes at upload time")
    detection_timestamp: datetime = Field(..., description="UTC timestamp of first file detection")
    upload_timestamp: Optional[datetime] = Field(
        None,
        description="UTC timestamp when S3 upload completed successfully"
    )
    status: UploadStatus = Field(UploadStatus.PENDING)
    retry_count: int = Field(0, description="Number of upload retry attempts made")
    failure_reason: Optional[str] = Field(
        None,
        description="Error message if status=FAILED; None on success"
    )
```

**MongoDB document example**:
```json
{
  "_id": "ObjectId(...)",
  "filename": "payment_instruction_001.pdf",
  "remote_sftp_path": "/uploads/payment_instruction_001.pdf",
  "s3_bucket": "mmp-ai-documents",
  "s3_key": "ingest/payment_instruction_001.pdf",
  "sha256_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "file_size_bytes": 204800,
  "detection_timestamp": "2026-03-10T09:15:00Z",
  "upload_timestamp": "2026-03-10T09:15:12Z",
  "status": "success",
  "retry_count": 0,
  "failure_reason": null
}
```

**Indexes**:
- `{ filename: 1 }` — unique, required (deduplication gate, FR-004)
- `{ status: 1, upload_timestamp: -1 }` — compound, optional (for operational queries)

---

## 4. WorkflowTriggerNotification

*Source: spec.md Key Entities — "Represents the message sent to mmp-ai-engine by the Lambda function"*

This is the JSON payload that the Lambda bridge (`lambda/handler.py`) POSTs to the mmp-ai-engine REST API. Not stored in the ingestion service (the Lambda is stateless). Full contract in `contracts/lambda-to-engine.md`.

```python
from pydantic import BaseModel, Field
from datetime import datetime


class WorkflowTriggerNotification(BaseModel):
    s3_bucket: str = Field(..., description="S3 bucket containing the uploaded file")
    s3_key: str = Field(..., description="Full S3 object key")
    filename: str = Field(..., description="Original filename (bare, no prefix)")
    file_size_bytes: int = Field(..., description="File size in bytes")
    detection_timestamp: datetime = Field(
        ...,
        description="UTC timestamp of original file detection on SFTP server"
    )
    sha256_hash: str = Field(..., description="SHA-256 hex digest for integrity verification by engine")
```

---

## 5. Entity Relationships

```
FileEvent (in-memory, poll cycle)
    │
    │  upload attempt
    ▼
UploadRecord (persisted, MongoDB upload_records)
    │
    │  S3 object created → Lambda triggered
    ▼
WorkflowTriggerNotification (Lambda POST payload → mmp-ai-engine)
```

The `filename` field is the shared key across all three: it is the unique business identifier from detection through to engine notification.
