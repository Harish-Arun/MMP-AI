from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from src.config.settings import Settings
from src.exceptions import FileDisappearedError, UploadFailedError
from src.models.models import FileEvent, UploadStatus
from src.uploader.s3_uploader import S3Uploader


def _make_settings(max_retries: int = 3) -> Settings:
    return Settings(
        sftp_host="localhost",
        sftp_username="test",
        sftp_password="test",
        sftp_remote_dir="/upload",
        s3_bucket="test-bucket",
        s3_key_prefix="ingest",
        s3_endpoint_url=None,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        aws_region="us-east-1",
        s3_max_upload_retries=max_retries,
        mongo_uri="mongodb://localhost:27017",
    )


def _make_file_event(filename: str = "payment_001.pdf", size: int = 1024) -> FileEvent:
    return FileEvent(
        filename=filename,
        remote_sftp_path=f"/upload/{filename}",
        file_size_bytes=size,
        size_at_previous_poll=size,
        detection_timestamp=datetime.now(UTC),
    )


def _make_mock_sftp(content: bytes = b"PDF content bytes") -> AsyncMock:
    mock_sftp = AsyncMock()
    mock_file = AsyncMock()
    mock_file.__aenter__ = AsyncMock(return_value=mock_file)
    mock_file.__aexit__ = AsyncMock(return_value=None)
    mock_file.read = AsyncMock(return_value=content)
    mock_sftp.open = AsyncMock(return_value=mock_file)
    return mock_sftp


# ---------------------------------------------------------------------------
# Successful upload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_creates_s3_object():
    """Successful upload creates S3 object at the expected key."""
    import boto3

    with mock_aws():
        settings = _make_settings()
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="test-bucket")

        uploader = S3Uploader(settings)
        event = _make_file_event("payment_001.pdf", 17)
        mock_sftp = _make_mock_sftp(b"PDF content bytes")

        record = await uploader.upload(event, mock_sftp)

        s3 = boto3.client("s3", region_name="us-east-1")
        obj = s3.head_object(Bucket="test-bucket", Key="ingest/payment_001.pdf")
        assert obj["ResponseMetadata"]["HTTPStatusCode"] == 200
        assert record.status == UploadStatus.SUCCESS


@pytest.mark.asyncio
async def test_upload_stores_sha256_hash():
    """SHA-256 of file content is stored in S3 metadata and returned in UploadRecord."""
    import boto3

    with mock_aws():
        content = b"PDF content bytes"
        expected_hash = hashlib.sha256(content).hexdigest()
        settings = _make_settings()
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="test-bucket")

        uploader = S3Uploader(settings)
        event = _make_file_event("payment_001.pdf", len(content))
        mock_sftp = _make_mock_sftp(content)

        record = await uploader.upload(event, mock_sftp)

        s3 = boto3.client("s3", region_name="us-east-1")
        obj = s3.head_object(Bucket="test-bucket", Key="ingest/payment_001.pdf")
        assert obj["Metadata"]["sha256"] == expected_hash
        assert record.sha256_hash == expected_hash


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_retries_on_503():
    """S3 ClientError(503) on first two attempts; succeeds on third."""
    import boto3

    with mock_aws():
        content = b"PDF retry bytes"
        settings = _make_settings(max_retries=3)
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="test-bucket")

        uploader = S3Uploader(settings)
        event = _make_file_event("payment_002.pdf", len(content))
        mock_sftp = _make_mock_sftp(content)

        call_count = 0
        original_put = uploader._s3.put_object

        def failing_put_object(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ClientError({"Error": {"Code": "503", "Message": "Service Unavailable"}}, "PutObject")
            return original_put(**kwargs)

        uploader._s3.put_object = failing_put_object
        record = await uploader.upload(event, mock_sftp)
        assert record.status == UploadStatus.SUCCESS
        assert record.retry_count == 2


@pytest.mark.asyncio
async def test_upload_raises_upload_failed_error_on_exhaustion():
    """After max retries exhausted, UploadFailedError is raised."""
    import boto3

    with mock_aws():
        content = b"PDF fail bytes"
        settings = _make_settings(max_retries=2)
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="test-bucket")

        uploader = S3Uploader(settings)
        event = _make_file_event("payment_003.pdf", len(content))
        mock_sftp = _make_mock_sftp(content)

        def always_fail(**kwargs):
            raise ClientError({"Error": {"Code": "503", "Message": "Service Unavailable"}}, "PutObject")

        uploader._s3.put_object = always_fail

        with pytest.raises(UploadFailedError):
            await uploader.upload(event, mock_sftp)


# ---------------------------------------------------------------------------
# FileDisappearedError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_file_disappeared_raises_file_disappeared_error():
    """asyncssh.SFTPNoSuchFile during download raises FileDisappearedError (not retried)."""
    import asyncssh

    settings = _make_settings()
    uploader = S3Uploader(settings)
    event = _make_file_event("vanishing_act.pdf")

    mock_sftp = AsyncMock()
    mock_sftp.open = AsyncMock(side_effect=asyncssh.SFTPNoSuchFile("/upload/vanishing_act.pdf"))

    with pytest.raises(FileDisappearedError):
        await uploader.upload(event, mock_sftp)
