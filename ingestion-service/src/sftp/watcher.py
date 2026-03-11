from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import AsyncGenerator

import asyncssh
import structlog
from tenacity import (
    RetryError,
    retry,
    stop_after_attempt,
    wait_exponential,
)

from src.config.settings import Settings
from src.models.models import FileEvent
from src.store.record_store import UploadRecordStore
from src.telemetry.setup import (
    files_detected_total,
    sftp_poll_duration_seconds,
    sftp_reconnect_total,
)

_logger = structlog.get_logger(__name__)


class SFTPWatcher:
    """Polls an SFTP remote directory, detects new write-complete files, and yields FileEvents."""

    def __init__(self, settings: Settings, record_store: UploadRecordStore) -> None:
        self._settings = settings
        self._store = record_store
        # filename → FileEvent for files pending write-completion check
        self._pending: dict[str, FileEvent] = {}
        # in-memory set of filenames already uploaded — avoids repeated DB lookups and log spam
        self._known_duplicates: set[str] = set()
        self._conn: asyncssh.SSHClientConnection | None = None

    async def poll_forever(self) -> AsyncGenerator[FileEvent, None]:
        """Public API: async generator yielding write-complete FileEvents continuously."""
        while True:
            start = time.monotonic()
            try:
                sftp = await self._get_sftp_client()
                async for event in self._poll(sftp):
                    yield event
            except Exception as exc:
                _logger.error("poll_cycle_error", error=str(exc))
            finally:
                elapsed = time.monotonic() - start
                sftp_poll_duration_seconds.observe(elapsed)

            await asyncio.sleep(self._settings.sftp_poll_interval_s)

    async def _poll(self, sftp) -> AsyncGenerator[FileEvent, None]:
        """Single poll cycle: list remote dir, update pending, yield write-complete events."""
        try:
            entries = await sftp.readdir(self._settings.sftp_remote_dir)
        except asyncssh.SFTPNoSuchFile:
            _logger.error("remote_dir_not_found", remote_dir=self._settings.sftp_remote_dir)
            return

        for entry in entries:
            filename = entry.filename
            size = entry.attrs.size

            # Filter by extension allowlist
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if ext not in self._settings.extension_allowlist:
                continue

            # Deduplication: already uploaded
            if filename in self._known_duplicates:
                continue
            if await self._store.is_known(filename):
                self._known_duplicates.add(filename)
                _logger.debug("duplicate_filename_skipped", filename=filename)
                files_detected_total.labels(status="duplicate").inc()
                continue

            if filename not in self._pending:
                # First detection
                event = FileEvent(
                    filename=filename,
                    remote_sftp_path=f"{self._settings.sftp_remote_dir}/{filename}",
                    file_size_bytes=size,
                    size_at_previous_poll=None,
                    detection_timestamp=datetime.now(UTC),
                )
                self._pending[filename] = event
                files_detected_total.labels(status="detected").inc()
                _logger.info("file_detected", filename=filename, size=size)
            else:
                event = self._pending[filename]
                prev_size = event.file_size_bytes

                # Zero-byte check across two polls (prev_size is file_size_bytes from last poll)
                if size == 0 and prev_size == 0:
                    _logger.warning("zero_byte_file_skipped", filename=filename)
                    files_detected_total.labels(status="zero_byte").inc()
                    del self._pending[filename]
                    continue

                # Update the event with new size
                updated = FileEvent(
                    filename=event.filename,
                    remote_sftp_path=event.remote_sftp_path,
                    file_size_bytes=size,
                    size_at_previous_poll=prev_size,
                    detection_timestamp=event.detection_timestamp,
                )
                self._pending[filename] = updated

                if updated.is_write_complete:
                    complete_event = FileEvent(
                        filename=updated.filename,
                        remote_sftp_path=updated.remote_sftp_path,
                        file_size_bytes=updated.file_size_bytes,
                        size_at_previous_poll=updated.size_at_previous_poll,
                        detection_timestamp=updated.detection_timestamp,
                        write_complete_timestamp=datetime.now(UTC),
                    )
                    del self._pending[filename]
                    _logger.info("file_write_complete", filename=filename, size=size)
                    yield complete_event
                else:
                    _logger.info("file_growing", filename=filename, prev_size=prev_size, new_size=size)

    async def _get_sftp_client(self):
        """Return an SFTP client, (re)connecting if needed."""
        if self._conn is None:
            self._conn = await self._connect_with_retry()
        try:
            sftp = await self._conn.start_sftp_client()
            return sftp
        except Exception:
            self._conn = None
            self._conn = await self._connect_with_retry()
            return await self._conn.start_sftp_client()

    async def _connect_with_retry(self) -> asyncssh.SSHClientConnection:
        """Establish SFTP/SSH connection with tenacity exponential backoff."""
        settings = self._settings

        @retry(
            wait=wait_exponential(multiplier=settings.backoff_base, min=1, max=60),
            stop=stop_after_attempt(settings.sftp_max_reconnect_attempts),
            reraise=True,
        )
        async def _attempt():
            sftp_reconnect_total.inc()
            connect_kwargs: dict = {
                "host": settings.sftp_host,
                "port": settings.sftp_port,
                "username": settings.sftp_username,
                "known_hosts": None,
            }
            if settings.sftp_key_path:
                connect_kwargs["client_keys"] = [settings.sftp_key_path]
            else:
                connect_kwargs["password"] = settings.sftp_password
            _logger.info("sftp_connecting", host=settings.sftp_host, port=settings.sftp_port)
            return await asyncssh.connect(**connect_kwargs)

        conn = await _attempt()
        _logger.info("sftp_connected", host=settings.sftp_host)
        return conn

    async def close(self) -> None:
        """Close the underlying SSH connection if open."""
        if self._conn:
            self._conn.close()
            self._conn = None
