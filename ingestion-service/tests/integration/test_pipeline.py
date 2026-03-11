"""
Integration tests: full pipeline against LocalStack + MongoDB.

Run locally only — requires:
  docker compose -f docker-compose.localstack.yml up localstack mongodb -d
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime

import pytest

from src.config.settings import Settings
from src.models.models import FileEvent, UploadStatus
from src.store.record_store import UploadRecordStore
from src.uploader.s3_uploader import S3Uploader


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Test 1: Upload pipeline — S3 object created + MongoDB record saved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_creates_s3_object_and_mongo_record(localstack_clients, integration_settings):
    """Upload a test PDF via S3Uploader; assert S3 object exists and MongoDB record is saved."""
    from unittest.mock import AsyncMock

    content = b"integration test PDF content"
    expected_hash = hashlib.sha256(content).hexdigest()

    store = UploadRecordStore(integration_settings)
    await store.init()

    uploader = S3Uploader(integration_settings)
    event = FileEvent(
        filename="integration_test_001.pdf",
        remote_sftp_path="/upload/integration_test_001.pdf",
        file_size_bytes=len(content),
        size_at_previous_poll=len(content),
        detection_timestamp=datetime.utcnow(),
        write_complete_timestamp=datetime.utcnow(),
    )

    mock_sftp = AsyncMock()
    mock_file = AsyncMock()
    mock_file.__aenter__ = AsyncMock(return_value=mock_file)
    mock_file.__aexit__ = AsyncMock(return_value=None)
    mock_file.read = AsyncMock(return_value=content)
    mock_sftp.open = AsyncMock(return_value=mock_file)

    record = await uploader.upload(event, mock_sftp)
    await store.save(record)

    # Assert S3 object exists
    s3 = localstack_clients["s3"]
    obj = s3.head_object(Bucket=integration_settings.s3_bucket, Key="ingest/integration_test_001.pdf")
    assert obj["Metadata"]["sha256"] == expected_hash

    # Assert MongoDB record
    assert await store.is_known("integration_test_001.pdf")
    records = await store.get_all()
    matching = [r for r in records if r.filename == "integration_test_001.pdf"]
    assert len(matching) == 1
    assert matching[0].status == UploadStatus.SUCCESS
    assert matching[0].sha256_hash == expected_hash

    await store.close()


# ---------------------------------------------------------------------------
# Test 2: Deduplication — second upload of same filename is blocked
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_duplicate_filename_not_re_uploaded(localstack_clients, integration_settings):
    """Uploading the same filename twice results in only one MongoDB record."""
    from unittest.mock import AsyncMock

    content = b"some PDF bytes"
    store = UploadRecordStore(integration_settings)
    await store.init()
    uploader = S3Uploader(integration_settings)

    event = FileEvent(
        filename="integration_dedup_001.pdf",
        remote_sftp_path="/upload/integration_dedup_001.pdf",
        file_size_bytes=len(content),
        size_at_previous_poll=len(content),
        detection_timestamp=datetime.utcnow(),
    )

    mock_sftp = AsyncMock()
    mock_file = AsyncMock()
    mock_file.__aenter__ = AsyncMock(return_value=mock_file)
    mock_file.__aexit__ = AsyncMock(return_value=None)
    mock_file.read = AsyncMock(return_value=content)
    mock_sftp.open = AsyncMock(return_value=mock_file)

    record = await uploader.upload(event, mock_sftp)
    await store.save(record)

    # Second attempt: is_known should block re-upload
    assert await store.is_known("integration_dedup_001.pdf") is True

    # Saving again should NOT raise (logs WARNING instead)
    await store.save(record)

    # Only one record in DB
    records = await store.get_all()
    matching = [r for r in records if r.filename == "integration_dedup_001.pdf"]
    assert len(matching) == 1

    await store.close()
