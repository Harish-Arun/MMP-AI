from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class UploadStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class FileEvent(BaseModel):
    filename: str = Field(..., description="Bare filename (e.g. 'payment_001.pdf')")
    remote_sftp_path: str = Field(..., description="Full remote path on SFTP server")
    file_size_bytes: int = Field(..., description="File size at latest poll (bytes)")
    size_at_previous_poll: Optional[int] = Field(
        None,
        description="File size at previous poll cycle; None on first detection",
    )
    detection_timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when file was first detected",
    )
    write_complete_timestamp: Optional[datetime] = Field(
        None,
        description="UTC timestamp when size-stability check passed; None until confirmed complete",
    )

    @property
    def is_write_complete(self) -> bool:
        """True when file size is stable across two consecutive polls and non-zero."""
        return (
            self.size_at_previous_poll is not None
            and self.file_size_bytes == self.size_at_previous_poll
            and self.file_size_bytes > 0
        )


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
        description="UTC timestamp when S3 upload completed successfully",
    )
    status: UploadStatus = Field(UploadStatus.PENDING)
    retry_count: int = Field(0, description="Number of upload retry attempts made")
    failure_reason: Optional[str] = Field(
        None,
        description="Error message if status=FAILED; None on success",
    )


class WorkflowTriggerNotification(BaseModel):
    s3_bucket: str = Field(..., description="S3 bucket name containing the uploaded file")
    s3_key: str = Field(..., description="Full S3 object key including prefix")
    filename: str = Field(..., description="Bare filename without prefix")
    file_size_bytes: int = Field(..., description="File size in bytes at upload time")
    detection_timestamp: datetime = Field(..., description="When the file was first detected on SFTP")
    sha256_hash: str = Field(..., description="SHA-256 hex digest for integrity verification")
