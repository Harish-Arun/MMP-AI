"""
Lambda handler: S3 ObjectCreated event → POST to mmp-ai-engine REST API.

Environment variables:
    ENGINE_REST_URL      — Base URL of mmp-ai-engine (e.g. http://engine:8000)
    MAX_RETRIES          — Max retry attempts for 5xx/timeout (default: 3)
    REQUEST_TIMEOUT_S    — HTTP request timeout in seconds (default: 10)
"""
from __future__ import annotations

import os
import uuid
from typing import Any
from urllib.parse import unquote_plus

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

_logger = structlog.get_logger(__name__)

ENGINE_REST_URL: str = os.environ.get("ENGINE_REST_URL", "http://localhost:8000")
MAX_RETRIES: int = int(os.environ.get("MAX_RETRIES", "3"))
REQUEST_TIMEOUT_S: int = int(os.environ.get("REQUEST_TIMEOUT_S", "10"))
_BACKOFF_MULTIPLIER: float = 2.0


def _is_retryable(exc: BaseException) -> bool:
    """Retry on 5xx responses and timeouts; do NOT retry on 4xx."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Entry point invoked by S3 ObjectCreated notification.

    Parses the S3 event, retrieves file metadata, and POSTs a
    WorkflowTriggerNotification to the mmp-ai-engine.
    """
    records = event.get("Records", [])
    if not records:
        _logger.warning("lambda_no_s3_records", event_keys=list(event.keys()))
        return {"statusCode": 200, "body": "no records"}

    s3_record = records[0]["s3"]
    bucket = s3_record["bucket"]["name"]
    key = unquote_plus(s3_record["object"]["key"])  # S3 events URL-encode the key
    size = s3_record["object"].get("size", 0)

    # Strip key prefix to recover bare filename
    filename = key.split("/")[-1]

    # Retrieve SHA-256 and detection_timestamp from S3 object metadata
    import boto3

    s3_client = boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT_URL") or os.environ.get("AWS_ENDPOINT_URL") or None,
        region_name=os.environ.get("AWS_REGION", "eu-west-2"),
    )
    head = s3_client.head_object(Bucket=bucket, Key=key)
    metadata = head.get("Metadata", {})
    sha256_hash = metadata.get("sha256", "")
    detection_timestamp = metadata.get("detection_timestamp", "")

    payload = {
        "s3_bucket": bucket,
        "s3_key": key,
        "filename": filename,
        "file_size_bytes": size,
        "detection_timestamp": detection_timestamp,
        "sha256_hash": sha256_hash,
    }

    request_id = str(uuid.uuid4())
    log = _logger.bind(filename=filename, sha256_hash=sha256_hash, request_id=request_id)

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=_BACKOFF_MULTIPLIER, min=1, max=30),
        stop=stop_after_attempt(MAX_RETRIES),
        reraise=True,
    )
    def _post() -> httpx.Response:
        response = httpx.post(
            f"{ENGINE_REST_URL}/api/v1/workflows/trigger",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "X-Source": "s3-lambda-trigger",
                "X-Request-Id": request_id,
            },
            timeout=REQUEST_TIMEOUT_S,
        )

        # Non-retryable client errors
        if response.status_code == 400:
            log.warning("engine_rejected_payload", status_code=400)
            return response
        if response.status_code == 409:
            log.warning("engine_duplicate_trigger", status_code=409)
            return response

        # Raises httpx.HTTPStatusError for 5xx → triggers retry
        response.raise_for_status()
        return response

    response = _post()
    log.info("engine_notified", status_code=response.status_code)
    return {"statusCode": response.status_code}
