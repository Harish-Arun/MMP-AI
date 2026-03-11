Feature: Lambda Workflow Trigger Notification
  As the mmp-ai system
  I want the S3 Lambda bridge to notify the engine after every successful upload
  So that document processing is triggered automatically and reliably

  Background:
    Given the Lambda handler is configured with ENGINE_REST_URL and MAX_RETRIES=3

  Scenario: Successful S3 upload triggers Lambda which POSTs to engine
    Given a valid S3 event for file "payment_001.pdf" in bucket "mmp-ai-documents"
    And the S3 object has metadata sha256 "abc123" and detection_timestamp "2026-03-10T09:15:00Z"
    And the engine returns HTTP 202
    When the lambda_handler is invoked with the S3 event
    Then the engine receives a POST to "/api/v1/workflows/trigger"
    And the POST body contains s3_bucket "mmp-ai-documents" and filename "payment_001.pdf"
    And the POST body contains sha256_hash "abc123"

  Scenario: Engine returns 503 - Lambda retries and succeeds
    Given a valid S3 event for file "payment_002.pdf" in bucket "mmp-ai-documents"
    And the S3 object has metadata sha256 "def456" and detection_timestamp "2026-03-10T09:20:00Z"
    And the engine returns HTTP 503 on the first attempt then HTTP 202
    When the lambda_handler is invoked with the S3 event
    Then the engine receives the POST after a retry

  Scenario: Engine returns 400 - non-retryable, no DLQ
    Given a valid S3 event for file "bad_payload.pdf" in bucket "mmp-ai-documents"
    And the S3 object has metadata sha256 "ghi789" and detection_timestamp "2026-03-10T09:25:00Z"
    And the engine returns HTTP 400
    When the lambda_handler is invoked with the S3 event
    Then the handler exits without raising
    And a WARNING log is emitted for the 400 response

  Scenario: All retries exhausted on 5xx - Lambda raises so DLQ captures event
    Given a valid S3 event for file "always_fails.pdf" in bucket "mmp-ai-documents"
    And the S3 object has metadata sha256 "jkl000" and detection_timestamp "2026-03-10T09:30:00Z"
    And the engine returns HTTP 503 on all attempts
    When the lambda_handler is invoked with the S3 event
    Then the handler raises an exception so Lambda routes the event to DLQ

  Scenario: S3 upload failed - no Lambda invocation
    Given no S3 event is provided
    When the lambda_handler receives an empty event
    Then no POST is sent to the engine
