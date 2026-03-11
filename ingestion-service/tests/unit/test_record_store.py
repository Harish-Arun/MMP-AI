from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.models.models import UploadRecord, UploadStatus


def _make_record(filename: str = "payment_001.pdf") -> UploadRecord:
    return UploadRecord(
        filename=filename,
        remote_sftp_path=f"/upload/{filename}",
        s3_bucket="test-bucket",
        s3_key=f"ingest/{filename}",
        sha256_hash="abc123",
        file_size_bytes=1024,
        detection_timestamp=datetime.now(UTC),
        upload_timestamp=datetime.now(UTC),
        status=UploadStatus.SUCCESS,
    )


@pytest.mark.asyncio
async def test_is_known_returns_false_before_save(mock_mongo_store):
    assert await mock_mongo_store.is_known("payment_001.pdf") is False


@pytest.mark.asyncio
async def test_is_known_returns_true_after_save(mock_mongo_store):
    record = _make_record("payment_001.pdf")
    await mock_mongo_store.save(record)
    assert await mock_mongo_store.is_known("payment_001.pdf") is True


@pytest.mark.asyncio
async def test_second_save_does_not_raise(mock_mongo_store):
    """Duplicate filename save does NOT raise — logs WARNING instead."""
    record = _make_record("payment_001.pdf")
    await mock_mongo_store.save(record)
    # Should not raise
    await mock_mongo_store.save(record)


@pytest.mark.asyncio
async def test_get_all_returns_saved_records(mock_mongo_store):
    r1 = _make_record("payment_001.pdf")
    r2 = _make_record("payment_002.pdf")
    await mock_mongo_store.save(r1)
    await mock_mongo_store.save(r2)
    records = await mock_mongo_store.get_all()
    filenames = {r.filename for r in records}
    assert filenames == {"payment_001.pdf", "payment_002.pdf"}


@pytest.mark.asyncio
async def test_get_all_returns_empty_on_empty_store(mock_mongo_store):
    records = await mock_mongo_store.get_all()
    assert records == []
