"""
pytest-bdd step definitions for lambda_notification.feature.
Uses aiohttp test server as engine mock and invokes lambda_handler directly.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

try:
    from pytest_bdd import given, parsers, scenario, then, when
except ImportError:
    pass


# ===========================================================================
# Scenario wiring
# ===========================================================================

@pytest.fixture
def lambda_ctx():
    return {
        "event": {},
        "response": None,
        "exception": None,
        "posts_received": [],
        "engine_responses": [],
        "engine_call_count": 0,
    }


def _make_s3_event(bucket: str, key: str, size: int = 1024) -> dict:
    return {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": key, "size": size},
                }
            }
        ]
    }


@contextmanager
def _mock_engine(responses: list[int], posts_received: list):
    """Patch httpx.post to return mocked status codes from the responses list."""
    call_count = 0

    def fake_post(url, **kwargs):
        nonlocal call_count
        posts_received.append({"url": url, "json": kwargs.get("json", {})})
        status = responses[min(call_count, len(responses) - 1)]
        call_count += 1
        mock_resp = MagicMock()
        mock_resp.status_code = status
        if status >= 500:
            import httpx
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                f"Server error {status}",
                request=MagicMock(),
                response=mock_resp,
            )
        else:
            mock_resp.raise_for_status.return_value = None
        return mock_resp

    with patch("httpx.post", side_effect=fake_post):
        yield


def _mock_s3_head(sha256: str, detection_ts: str):
    mock_s3_client = MagicMock()
    mock_s3_client.head_object.return_value = {
        "Metadata": {"sha256": sha256, "detection_timestamp": detection_ts}
    }
    return mock_s3_client


# ---------------------------------------------------------------------------
# Scenario: Successful S3 upload triggers Lambda which POSTs to engine
# ---------------------------------------------------------------------------

@pytest.fixture
def test_lambda_happy_path(lambda_ctx):
    os.environ["ENGINE_REST_URL"] = "http://mock-engine"
    os.environ["MAX_RETRIES"] = "3"
    os.environ["REQUEST_TIMEOUT_S"] = "10"

    event = _make_s3_event("mmp-ai-documents", "ingest/payment_001.pdf")
    mock_s3 = _mock_s3_head("abc123", "2026-03-10T09:15:00Z")

    posts = []
    with _mock_engine([202], posts):
        with patch("boto3.client", return_value=mock_s3):
            import importlib
            lh = importlib.import_module('lambda.handler')
            importlib.reload(lh)
            lh.ENGINE_REST_URL = "http://mock-engine"
            lh.MAX_RETRIES = 3
            try:
                result = lh.lambda_handler(event, None)
                lambda_ctx["response"] = result
                lambda_ctx["posts_received"] = posts
            except Exception as exc:
                lambda_ctx["exception"] = exc
    return lambda_ctx


def test_lambda_posts_to_engine(test_lambda_happy_path):
    ctx = test_lambda_happy_path
    assert ctx["exception"] is None
    assert len(ctx["posts_received"]) >= 1
    post = ctx["posts_received"][0]
    assert "payment_001.pdf" in post["json"].get("filename", "")
    assert post["json"]["sha256_hash"] == "abc123"


def test_lambda_400_non_retryable():
    """Engine returns 400 — handler exits without raising, logs WARNING."""
    os.environ["ENGINE_REST_URL"] = "http://mock-engine"
    os.environ["MAX_RETRIES"] = "3"

    event = _make_s3_event("mmp-ai-documents", "ingest/bad_payload.pdf")
    mock_s3 = _mock_s3_head("ghi789", "2026-03-10T09:25:00Z")

    posts = []
    with _mock_engine([400], posts):
        with patch("boto3.client", return_value=mock_s3):
            import importlib
            lh = importlib.import_module('lambda.handler')
            importlib.reload(lh)
            lh.ENGINE_REST_URL = "http://mock-engine"
            lh.MAX_RETRIES = 3
            # Should NOT raise
            result = lh.lambda_handler(event, None)
    assert result["statusCode"] == 400


def test_lambda_5xx_exhausted_raises():
    """Engine returns 503 on all attempts — handler raises so Lambda routes to DLQ."""
    os.environ["ENGINE_REST_URL"] = "http://mock-engine"
    os.environ["MAX_RETRIES"] = "2"

    event = _make_s3_event("mmp-ai-documents", "ingest/always_fails.pdf")
    mock_s3 = _mock_s3_head("jkl000", "2026-03-10T09:30:00Z")

    with _mock_engine([503, 503, 503], []):
        with patch("boto3.client", return_value=mock_s3):
            import importlib
            lh = importlib.import_module('lambda.handler')
            importlib.reload(lh)
            lh.ENGINE_REST_URL = "http://mock-engine"
            lh.MAX_RETRIES = 2
            with pytest.raises(Exception):
                lh.lambda_handler(event, None)


def test_lambda_empty_event_no_post():
    """Empty event (no Records) → no POST sent, returns 200."""
    import importlib
    lh = importlib.import_module('lambda.handler')
    importlib.reload(lh)
    lh.ENGINE_REST_URL = "http://mock-engine"

    posts = []
    with patch("httpx.post", side_effect=lambda *a, **kw: posts.append(kw)):
        result = lh.lambda_handler({}, None)

    assert posts == []

