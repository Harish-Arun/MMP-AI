"""
LocalStack provisioning script for ingestion-service local development.

Run once after LocalStack starts:
    python scripts/setup_localstack.py

Or import provision_localstack() from integration tests (T021).
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Tuple

import boto3

LOCALSTACK_URL = os.environ.get("LOCALSTACK_URL", "http://localhost:4566")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
LAMBDA_NAME = "mmp-ai-s3-trigger"
DLQ_NAME = "mmp-ai-dlq"

_BOTO_KWARGS = dict(
    endpoint_url=LOCALSTACK_URL,
    region_name=AWS_REGION,
    aws_access_key_id="test",
    aws_secret_access_key="test",
)


def _build_lambda_zip() -> bytes:
    """Zip lambda/handler.py + its dependencies into an in-memory deployment package."""
    lambda_dir = Path(__file__).parent.parent / "lambda"
    buf = io.BytesIO()

    with tempfile.TemporaryDirectory() as tmp:
        # Install dependencies into a temp dir
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install",
             "-r", str(lambda_dir / "requirements.txt"),
             "-t", tmp, "--quiet"],
        )
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add installed packages
            for file in Path(tmp).rglob("*"):
                if file.is_file():
                    zf.write(file, file.relative_to(tmp))
            # Add handler.py at the root
            zf.write(lambda_dir / "handler.py", arcname="handler.py")

    return buf.getvalue()


def provision_localstack(settings=None) -> Tuple:
    """
    Idempotent LocalStack provisioning. Called by integration conftest (T021).

    Steps:
        1. Create S3 bucket
        2. Deploy Lambda function
        3. Grant S3 permission to invoke Lambda
        4. Wire S3 ObjectCreated → Lambda notification
        5. Create SQS DLQ (T034)
        6. Attach DLQ to Lambda (T034)

    Returns:
        (s3_client, lambda_client, sqs_client)
    """
    bucket = settings.s3_bucket if settings else os.environ.get("S3_BUCKET", "mmp-ai-documents")
    engine_url = os.environ.get("ENGINE_REST_URL", "http://host.docker.internal:8000")

    s3 = boto3.client("s3", **_BOTO_KWARGS)
    lam = boto3.client("lambda", **_BOTO_KWARGS)
    sqs = boto3.client("sqs", **_BOTO_KWARGS)
    iam = boto3.client("iam", **_BOTO_KWARGS)

    # Step 1: Create S3 bucket
    try:
        s3.create_bucket(Bucket=bucket)
        print(f"[1/6] S3 bucket created: {bucket}")
    except s3.exceptions.BucketAlreadyOwnedByYou:
        print(f"[1/6] S3 bucket already exists: {bucket}")
    except Exception as exc:
        if "BucketAlreadyExists" in str(exc) or "BucketAlreadyOwnedByYou" in str(exc):
            print(f"[1/6] S3 bucket already exists: {bucket}")
        else:
            raise

    # Step 2: Build and deploy Lambda
    zip_bytes = _build_lambda_zip()
    lambda_arn = None
    try:
        resp = lam.create_function(
            FunctionName=LAMBDA_NAME,
            Runtime="python3.11",
            Role="arn:aws:iam::000000000000:role/lambda-role",
            Handler="handler.lambda_handler",
            Code={"ZipFile": zip_bytes},
            Environment={
                "Variables": {
                    "ENGINE_REST_URL": engine_url,
                    "MAX_RETRIES": "3",
                    "REQUEST_TIMEOUT_S": "10",
                }
            },
            Timeout=30,
        )
        lambda_arn = resp["FunctionArn"]
        print(f"[2/6] Lambda deployed: {lambda_arn}")
    except lam.exceptions.ResourceConflictException:
        resp = lam.get_function(FunctionName=LAMBDA_NAME)
        lambda_arn = resp["Configuration"]["FunctionArn"]
        print(f"[2/6] Lambda already exists: {lambda_arn}")
        # Always sync env vars and code in case they changed
        lam.update_function_code(FunctionName=LAMBDA_NAME, ZipFile=zip_bytes)
        # Wait for code update to complete before updating config
        waiter = lam.get_waiter("function_updated")
        waiter.wait(FunctionName=LAMBDA_NAME)
        lam.update_function_configuration(
            FunctionName=LAMBDA_NAME,
            Environment={
                "Variables": {
                    "ENGINE_REST_URL": engine_url,
                    "MAX_RETRIES": "3",
                    "REQUEST_TIMEOUT_S": "10",
                }
            },
        )
        print(f"[2/6] Lambda env vars updated: ENGINE_REST_URL={engine_url}")

    # Step 3: Grant S3 permission to invoke Lambda
    try:
        lam.add_permission(
            FunctionName=LAMBDA_NAME,
            StatementId="s3-invoke-permission",
            Action="lambda:InvokeFunction",
            Principal="s3.amazonaws.com",
            SourceArn=f"arn:aws:s3:::{bucket}",
        )
        print("[3/6] Lambda S3 invoke permission added")
    except lam.exceptions.ResourceConflictException:
        print("[3/6] Lambda permission already exists")

    # Step 4: Wire S3 ObjectCreated → Lambda
    s3.put_bucket_notification_configuration(
        Bucket=bucket,
        NotificationConfiguration={
            "LambdaFunctionConfigurations": [
                {
                    "LambdaFunctionArn": lambda_arn,
                    "Events": ["s3:ObjectCreated:*"],
                }
            ]
        },
        SkipDestinationValidation=True,
    )
    print(f"[4/6] S3 → Lambda notification wired: s3:ObjectCreated:* → {lambda_arn}")

    # Step 5 (T034): Create SQS DLQ
    dlq_arn = None
    try:
        dlq_resp = sqs.create_queue(QueueName=DLQ_NAME)
        dlq_url = dlq_resp["QueueUrl"]
        attrs = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])
        dlq_arn = attrs["Attributes"]["QueueArn"]
        print(f"[5/6] SQS DLQ created: {dlq_arn}")
    except Exception as exc:
        if "QueueAlreadyExists" in str(exc) or "already exists" in str(exc).lower():
            dlq_url = sqs.get_queue_url(QueueName=DLQ_NAME)["QueueUrl"]
            attrs = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])
            dlq_arn = attrs["Attributes"]["QueueArn"]
            print(f"[5/6] SQS DLQ already exists: {dlq_arn}")
        else:
            raise

    # Step 6 (T034): Attach DLQ to Lambda
    # Wait for Lambda to reach Active state before any update_function_configuration call
    waiter = lam.get_waiter("function_active")
    waiter.wait(FunctionName=LAMBDA_NAME)
    lam.update_function_configuration(
        FunctionName=LAMBDA_NAME,
        DeadLetterConfig={"TargetArn": dlq_arn},
    )
    print(f"[6/6] DLQ attached to Lambda: {dlq_arn}")

    return s3, lam, sqs


if __name__ == "__main__":
    provision_localstack()
