"""
ingestion-service entry point.

Starts two concurrent asyncio tasks:
  1. poll_loop  — SFTP poll → S3 upload → MongoDB persist
  2. health_server — aiohttp serving /health and /-/metrics
"""
from __future__ import annotations

import asyncio
import logging
import signal
import time
from datetime import datetime, timezone

import structlog
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src.config.settings import Settings
from src.sftp.watcher import SFTPWatcher
from src.store.record_store import UploadRecordStore
from src.telemetry.setup import (
    get_tracer,
    init_telemetry,
    upload_failure_total,
    upload_success_total,
)
from src.uploader.s3_uploader import S3Uploader
from src.exceptions import FileDisappearedError, UploadFailedError

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)

_logger = structlog.get_logger(__name__)
_start_time = time.monotonic()

# Global references for health checks
_sftp_connected = False
_mongo_connected = False


async def poll_loop(watcher: SFTPWatcher, uploader: S3Uploader, store: UploadRecordStore) -> None:
    global _sftp_connected
    async for file_event in watcher.poll_forever():
        _sftp_connected = True
        tracer = get_tracer()
        with tracer.start_as_current_span("file.process") as span:
            span.set_attribute("file.name", file_event.filename)
            span.set_attribute("file.size_bytes", file_event.file_size_bytes)
            span.set_attribute("sftp.path", file_event.remote_sftp_path)
            try:
                sftp = await watcher._get_sftp_client()
                record = await uploader.upload(file_event, sftp)
                await store.save(record)
                upload_success_total.inc()
                span.set_attribute("s3.key", record.s3_key)
                span.set_attribute("file.sha256", record.sha256_hash)
                _logger.info("file_processed", filename=file_event.filename, s3_key=record.s3_key)
                _logger.info(
                    "handoff_complete",
                    filename=file_event.filename,
                    detail="downstream handled by Lambda",
                )
            except FileDisappearedError as exc:
                span.set_attribute("error", True)
                span.set_attribute("error.type", "FileDisappearedError")
                _logger.warning("file_disappeared", filename=str(exc))
            except UploadFailedError as exc:
                upload_failure_total.inc()
                span.set_attribute("error", True)
                span.set_attribute("error.type", "UploadFailedError")
                _logger.error("upload_failed", filename=str(exc))
            except Exception as exc:
                upload_failure_total.inc()
                span.set_attribute("error", True)
                span.set_attribute("error.type", type(exc).__name__)
                _logger.error("unexpected_error", error=str(exc), filename=file_event.filename)


async def health_server(settings: Settings, store: UploadRecordStore) -> None:
    app = web.Application()

    async def health_handler(request: web.Request) -> web.Response:
        uptime = time.monotonic() - _start_time
        try:
            await store._collection.find_one({}, {"_id": 1})
            mongo_status = "connected"
        except Exception:
            mongo_status = "unreachable"

        return web.json_response({
            "status": "ok",
            "sftp": "connected" if _sftp_connected else "initialising",
            "mongo": mongo_status,
            "uptime_seconds": round(uptime, 1),
        })

    async def metrics_handler(request: web.Request) -> web.Response:
        data = generate_latest()
        return web.Response(body=data, content_type=CONTENT_TYPE_LATEST)

    app.router.add_get("/health", health_handler)
    app.router.add_get("/-/metrics", metrics_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.health_port)
    await site.start()
    _logger.info("health_server_started", port=settings.health_port)

    try:
        await asyncio.Event().wait()  # run forever until cancelled
    finally:
        await runner.cleanup()


async def main() -> None:
    global _mongo_connected

    settings = Settings()
    init_telemetry(settings)

    store = UploadRecordStore(settings)
    await store.init()
    _mongo_connected = True

    watcher = SFTPWatcher(settings, store)
    uploader = S3Uploader(settings)

    loop = asyncio.get_running_loop()

    async def _shutdown(tasks):
        _logger.info("shutdown_initiated")
        for task in tasks:
            task.cancel()
        await watcher.close()
        await store.close()
        _logger.info("shutdown_complete")

    poll_task = asyncio.create_task(poll_loop(watcher, uploader, store))
    health_task = asyncio.create_task(health_server(settings, store))
    all_tasks = [poll_task, health_task]

    # add_signal_handler is Unix-only; fall back to signal.signal on Windows
    import sys
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(_shutdown(all_tasks)))

    try:
        await asyncio.gather(*all_tasks)
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        await _shutdown(all_tasks)


if __name__ == "__main__":
    asyncio.run(main())
