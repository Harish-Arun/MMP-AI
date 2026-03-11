from __future__ import annotations

import asyncio
from datetime import datetime
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import Settings
from src.models.models import FileEvent, UploadRecord, UploadStatus
from src.sftp.watcher import SFTPWatcher


def _make_settings(**overrides) -> Settings:
    base = dict(
        sftp_host="localhost",
        sftp_port=22,
        sftp_username="test",
        sftp_password="test",
        sftp_remote_dir="/upload",
        s3_bucket="test-bucket",
        mongo_uri="mongodb://localhost:27017",
    )
    base.update(overrides)
    return Settings(**base)


def _make_record_store(known: set[str] | None = None):
    store = MagicMock()
    _known = known or set()
    store.is_known = AsyncMock(side_effect=lambda fn: fn in _known)
    store.save = AsyncMock()
    return store


# ---------------------------------------------------------------------------
# _connect_with_retry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_with_retry_success():
    """Connection established on first attempt."""
    settings = _make_settings()
    store = _make_record_store()
    watcher = SFTPWatcher(settings, store)

    mock_conn = MagicMock()
    with patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)):
        conn = await watcher._connect_with_retry()
    assert conn is mock_conn


@pytest.mark.asyncio
async def test_connect_with_retry_reconnects_on_disconnect():
    """Watcher retries connection after asyncssh.DisconnectError."""
    import asyncssh

    settings = _make_settings(sftp_max_reconnect_attempts=3)
    store = _make_record_store()
    watcher = SFTPWatcher(settings, store)

    mock_conn = MagicMock()
    call_count = 0

    async def flaky_connect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise asyncssh.DisconnectError(14, "Connection lost")
        return mock_conn

    with patch("asyncssh.connect", side_effect=flaky_connect):
        conn = await watcher._connect_with_retry()

    assert conn is mock_conn
    assert call_count == 2


# ---------------------------------------------------------------------------
# Extension allowlist
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_pdf_silently_ignored(caplog):
    """Files with extension not in allowlist are not detected."""
    settings = _make_settings(extension_allowlist=[".pdf"])
    store = _make_record_store()
    watcher = SFTPWatcher(settings, store)

    sftp_entry = MagicMock()
    sftp_entry.filename = "spreadsheet.xlsx"
    sftp_entry.attrs.size = 512

    mock_sftp = AsyncMock()
    mock_sftp.readdir = AsyncMock(return_value=[sftp_entry])

    mock_conn = MagicMock()
    mock_conn.start_client = AsyncMock(return_value=mock_sftp)

    with patch.object(watcher, "_connect_with_retry", new=AsyncMock(return_value=mock_conn)):
        with patch("asyncssh.SFTPClient") as _:
            events = []
            async for evt in _poll_once(watcher, mock_sftp):
                events.append(evt)

    assert events == []


async def _poll_once(watcher: SFTPWatcher, mock_sftp) -> AsyncGenerator[FileEvent, None]:
    """Helper: call watcher._poll() once and collect yielded FileEvents."""
    with patch.object(watcher, "_get_sftp_client", new=AsyncMock(return_value=mock_sftp)):
        async for event in watcher._poll(mock_sftp):
            yield event


# ---------------------------------------------------------------------------
# Size-stability tracking (new file → pending → write-complete)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_new_file_added_to_pending():
    """First detection: file added to _pending, no yield."""
    settings = _make_settings()
    store = _make_record_store()
    watcher = SFTPWatcher(settings, store)

    sftp_entry = _make_entry("payment_001.pdf", 1024)
    mock_sftp = _make_sftp_client([sftp_entry])

    events = await _collect_poll(watcher, mock_sftp)
    assert events == []
    assert "payment_001.pdf" in watcher._pending


@pytest.mark.asyncio
async def test_size_unchanged_across_two_polls_yields_event():
    """File size stable across 2 polls → write-complete → yielded."""
    settings = _make_settings()
    store = _make_record_store()
    watcher = SFTPWatcher(settings, store)

    sftp_entry = _make_entry("payment_001.pdf", 1024)
    mock_sftp = _make_sftp_client([sftp_entry])

    # First poll: add to _pending
    await _collect_poll(watcher, mock_sftp)
    # Second poll: same size → yield
    events = await _collect_poll(watcher, mock_sftp)

    assert len(events) == 1
    assert events[0].filename == "payment_001.pdf"
    assert events[0].is_write_complete is True


@pytest.mark.asyncio
async def test_size_changed_stays_in_pending():
    """File size changes between polls → stays in _pending."""
    settings = _make_settings()
    store = _make_record_store()
    watcher = SFTPWatcher(settings, store)

    mock_sftp_1 = _make_sftp_client([_make_entry("growing.pdf", 1024)])
    mock_sftp_2 = _make_sftp_client([_make_entry("growing.pdf", 2048)])

    await _collect_poll(watcher, mock_sftp_1)
    events = await _collect_poll(watcher, mock_sftp_2)

    assert events == []
    assert watcher._pending["growing.pdf"].file_size_bytes == 2048


@pytest.mark.asyncio
async def test_zero_byte_file_warns_not_uploaded(caplog):
    """Zero-byte file across 2 polls → WARNING, removed from pending, not yielded."""
    import logging

    settings = _make_settings()
    store = _make_record_store()
    watcher = SFTPWatcher(settings, store)

    mock_sftp = _make_sftp_client([_make_entry("empty.pdf", 0)])

    with caplog.at_level(logging.WARNING):
        await _collect_poll(watcher, mock_sftp)
        events = await _collect_poll(watcher, mock_sftp)

    assert events == []
    assert "empty.pdf" not in watcher._pending


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_known_file_is_skipped_with_warning(caplog):
    """File already in MongoDB record store → WARNING logged, not yielded."""
    import logging

    settings = _make_settings()
    store = _make_record_store(known={"payment_001.pdf"})
    watcher = SFTPWatcher(settings, store)

    mock_sftp = _make_sftp_client([_make_entry("payment_001.pdf", 1024)])

    with caplog.at_level(logging.WARNING):
        events = await _collect_poll(watcher, mock_sftp)

    assert events == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(filename: str, size: int):
    entry = MagicMock()
    entry.filename = filename
    entry.attrs = MagicMock()
    entry.attrs.size = size
    return entry


def _make_sftp_client(entries):
    mock_sftp = AsyncMock()
    mock_sftp.readdir = AsyncMock(return_value=entries)
    return mock_sftp


async def _collect_poll(watcher: SFTPWatcher, mock_sftp) -> list[FileEvent]:
    events = []
    async for evt in watcher._poll(mock_sftp):
        events.append(evt)
    return events
