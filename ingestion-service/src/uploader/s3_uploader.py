from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import asyncssh
import boto3
import structlog
from botocore.exceptions import ClientError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
)

from src.config.settings import Settings
from src.exceptions import FileDisappearedError, UploadFailedError
from src.models.models import FileEvent, UploadRecord, UploadStatus
from src.telemetry.setup import get_tracer, upload_failure_total, upload_success_total

_logger = structlog.get_logger(__name__)


class S3Uploader:
    """Streams files from SFTP to S3 with SHA-256 hashing, tenacity retries, and telemetry."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._s3 = boto3.client(
            "s3",
            region_name=settings.aws_region,
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.aws_access_key_id or None,
            aws_secret_access_key=settings.aws_secret_access_key or None,
        )

    async def upload(self, file_event: FileEvent, sftp) -> UploadRecord:
        """
        Stream-download file from SFTP and upload to S3 with SHA-256 metadata.

        Raises:
            FileDisappearedError: if the file vanishes on SFTP before download.
            UploadFailedError: if all S3 upload retries are exhausted.
        """
        settings = self._settings
        s3_key = f"{settings.s3_key_prefix}/{file_event.filename}"
        retry_count = 0
        tracer = get_tracer()

        with tracer.start_as_current_span("s3.upload") as span:
            span.set_attribute("file.name", file_event.filename)
            span.set_attribute("s3.bucket", settings.s3_bucket)
            span.set_attribute("s3.key", s3_key)

        # Download from SFTP — FileDisappearedError is NOT retried
        try:
            async with await sftp.open(file_event.remote_sftp_path, "rb") as remote_file:
                content: bytes = await remote_file.read()
        except asyncssh.SFTPNoSuchFile:
            _logger.warning("file_disappeared_before_download", filename=file_event.filename)
            raise FileDisappearedError(file_event.filename)

        sha256_hash = hashlib.sha256(content).hexdigest()

        @retry(
            wait=wait_exponential(multiplier=settings.backoff_base, min=1, max=30),
            stop=stop_after_attempt(settings.s3_max_upload_retries),
            reraise=True,
        )
        def _put_to_s3() -> None:
            nonlocal retry_count
            retry_count += 1
            self._s3.put_object(
                Bucket=settings.s3_bucket,
                Key=s3_key,
                Body=content,
                Metadata={
                    "sha256": sha256_hash,
                    "detection_timestamp": file_event.detection_timestamp.isoformat(),
                    "original_filename": file_event.filename,
                },
            )

        try:
            _put_to_s3()
        except ClientError as exc:
            upload_failure_total.inc()
            _logger.error(
                "s3_upload_failed",
                filename=file_event.filename,
                error=str(exc),
                retry_count=retry_count,
            )
            raise UploadFailedError(file_event.filename) from exc

        # retry_count tracks number of calls; successful first call = retry_count=1 → 0 retries
        actual_retries = max(0, retry_count - 1)
        upload_success_total.inc()
        _logger.info("s3_upload_success", filename=file_event.filename, s3_key=s3_key, sha256=sha256_hash)

        return UploadRecord(
            filename=file_event.filename,
            remote_sftp_path=file_event.remote_sftp_path,
            s3_bucket=settings.s3_bucket,
            s3_key=s3_key,
            sha256_hash=sha256_hash,
            file_size_bytes=len(content),
            detection_timestamp=file_event.detection_timestamp,
            upload_timestamp=datetime.now(UTC),
            status=UploadStatus.SUCCESS,
            retry_count=actual_retries,
        )
