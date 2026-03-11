"""
T035: Concurrency test — validates SC-003 (≥50 simultaneous file arrivals without loss).
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.settings import Settings
from src.models.models import FileEvent
from src.sftp.watcher import SFTPWatcher


def _make_settings() -> Settings:
    return Settings(
        sftp_host="localhost",
        sftp_username="test",
        sftp_password="test",
        sftp_remote_dir="/upload",
        s3_bucket="test-bucket",
        mongo_uri="mongodb://localhost:27017",
    )


def _make_store():
    store = MagicMock()
    store.is_known = AsyncMock(return_value=False)
    store.save = AsyncMock()
    return store


def _make_entry(filename: str, size: int):
    entry = MagicMock()
    entry.filename = filename
    entry.attrs = MagicMock()
    entry.attrs.size = size
    return entry


@pytest.mark.asyncio
async def test_50_simultaneous_file_arrivals_no_drop():
    """
    Simulate 50 FileEvents all becoming write-complete in a single _poll() iteration.
    Assert poll_forever yields exactly 50 distinct FileEvents without dropping any.
    Validates SC-003: handles ≥ 50 simultaneous file arrivals without loss.
    """
    n = 50
    settings = _make_settings()
    store = _make_store()
    watcher = SFTPWatcher(settings, store)

    filenames = [f"payment_{i:03d}.pdf" for i in range(n)]

    # First poll: put all 50 files into _pending (size varies to avoid zero-byte skip)
    entries_poll1 = [_make_entry(fn, 1024) for fn in filenames]
    mock_sftp1 = AsyncMock()
    mock_sftp1.readdir = AsyncMock(return_value=entries_poll1)

    poll1_events = []
    async for evt in watcher._poll(mock_sftp1):
        poll1_events.append(evt)
    assert poll1_events == [], "No events should be yielded on first poll"
    assert len(watcher._pending) == n, f"Expected {n} pending, got {len(watcher._pending)}"

    # Second poll: same sizes → all 50 become write-complete → yielded
    entries_poll2 = [_make_entry(fn, 1024) for fn in filenames]
    mock_sftp2 = AsyncMock()
    mock_sftp2.readdir = AsyncMock(return_value=entries_poll2)

    poll2_events = []
    async for evt in watcher._poll(mock_sftp2):
        poll2_events.append(evt)

    assert len(poll2_events) == n, f"Expected {n} events, got {len(poll2_events)}"
    yielded_names = {e.filename for e in poll2_events}
    assert yielded_names == set(filenames), "All 50 filenames must be yielded exactly once"
    assert len(watcher._pending) == 0, "All files should be removed from pending after yield"
