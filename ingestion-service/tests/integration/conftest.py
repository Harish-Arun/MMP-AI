"""
Integration test fixtures for the ingestion-service pipeline.

Requires LocalStack running at http://localhost:4566 (start via docker-compose.localstack.yml).
These tests are intentionally excluded from CI — run locally per quickstart.md.
"""
from __future__ import annotations

import pytest

from src.config.settings import Settings

LOCALSTACK_URL = "http://localhost:4566"


def _localstack_available() -> bool:
    """Return True if LocalStack is reachable."""
    try:
        import httpx
        response = httpx.get(f"{LOCALSTACK_URL}/health", timeout=3)
        return response.status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="session")
def integration_settings() -> Settings:
    return Settings(
        sftp_host="localhost",
        sftp_username="test",
        sftp_password="test",
        sftp_remote_dir="/upload",
        s3_bucket="mmp-ai-documents",
        s3_key_prefix="ingest",
        s3_endpoint_url=LOCALSTACK_URL,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        aws_region="us-east-1",
        s3_max_upload_retries=3,
        sftp_max_reconnect_attempts=3,
        backoff_base=0.5,
        extension_allowlist=[".pdf"],
        mongo_uri="mongodb://localhost:27017",
        mongo_db_name="mmp_ai_integration_test",
    )


@pytest.fixture(scope="session")
def localstack_clients(integration_settings):
    """Provision LocalStack and return boto3 clients."""
    if not _localstack_available():
        pytest.skip("LocalStack not available — run docker-compose.localstack.yml first")

    from scripts.setup_localstack import provision_localstack

    s3_client, lambda_client, sqs_client = provision_localstack(integration_settings)

    yield {"s3": s3_client, "lambda": lambda_client, "sqs": sqs_client}

    # Teardown: delete all S3 objects and bucket, Lambda, SQS queue
    import boto3

    s3 = boto3.client("s3", endpoint_url=LOCALSTACK_URL, region_name="us-east-1",
                      aws_access_key_id="test", aws_secret_access_key="test")
    try:
        objects = s3.list_objects_v2(Bucket=integration_settings.s3_bucket).get("Contents", [])
        for obj in objects:
            s3.delete_object(Bucket=integration_settings.s3_bucket, Key=obj["Key"])
        s3.delete_bucket(Bucket=integration_settings.s3_bucket)
    except Exception:
        pass

    lam = boto3.client("lambda", endpoint_url=LOCALSTACK_URL, region_name="us-east-1",
                       aws_access_key_id="test", aws_secret_access_key="test")
    try:
        lam.delete_function(FunctionName="mmp-ai-s3-trigger")
    except Exception:
        pass

    sqs = boto3.client("sqs", endpoint_url=LOCALSTACK_URL, region_name="us-east-1",
                       aws_access_key_id="test", aws_secret_access_key="test")
    try:
        url = sqs.get_queue_url(QueueName="mmp-ai-dlq")["QueueUrl"]
        sqs.delete_queue(QueueUrl=url)
    except Exception:
        pass
