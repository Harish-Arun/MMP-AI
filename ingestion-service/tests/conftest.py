from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from moto import mock_aws

from src.config.settings import Settings
from src.models.models import FileEvent, UploadRecord, UploadStatus
from src.store.record_store import UploadRecordStore


# ---------------------------------------------------------------------------
# Settings fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def settings() -> Settings:
    return Settings(
        sftp_host="localhost",
        sftp_port=22,
        sftp_username="test",
        sftp_password="test",
        sftp_remote_dir="/upload",
        s3_bucket="test-bucket",
        s3_key_prefix="ingest",
        s3_endpoint_url=None,
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        aws_region="us-east-1",
        s3_max_upload_retries=3,
        sftp_max_reconnect_attempts=3,
        backoff_base=0.01,
        extension_allowlist=[".pdf"],
        mongo_uri="mongodb://localhost:27017",
        mongo_db_name="test_db",
        health_port=8080,
    )


# ---------------------------------------------------------------------------
# MongoDB mock fixture (mongomock-motor)
# ---------------------------------------------------------------------------

@pytest.fixture
async def mock_mongo_store(settings):
    """UploadRecordStore backed by mongomock-motor (no real MongoDB required)."""
    import mongomock_motor

    mock_client = mongomock_motor.AsyncMongoMockClient()
    store = UploadRecordStore.__new__(UploadRecordStore)
    store._client = mock_client
    store._db = mock_client[settings.mongo_db_name]
    store._collection = store._db["upload_records"]
    await store.init()
    return store


# ---------------------------------------------------------------------------
# S3 mock fixture (moto)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_s3(settings):
    """Provides a moto-mocked S3 environment with the test bucket pre-created."""
    import boto3

    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="test-bucket")
        yield


# ---------------------------------------------------------------------------
# Sample FileEvent factory fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_file_event() -> FileEvent:
    return FileEvent(
        filename="payment_001.pdf",
        remote_sftp_path="/upload/payment_001.pdf",
        file_size_bytes=1024,
        size_at_previous_poll=1024,
        detection_timestamp=datetime.utcnow(),
        write_complete_timestamp=datetime.utcnow(),
    )
