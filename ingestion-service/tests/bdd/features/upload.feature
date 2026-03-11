Feature: S3 Upload with SHA-256 and Retry
  As a system operator
  I want files uploaded to S3 with integrity hashes and resilient retries
  So that uploads are reliable and data integrity is guaranteed

  Background:
    Given the S3 uploader is configured with max_retries=3
    And a LocalStack S3 bucket "test-bucket" exists

  Scenario: Successful upload stores SHA-256 in UploadRecord and S3 metadata
    Given a file "payment_002.pdf" with known content "PDF content bytes"
    When the file is uploaded to S3
    Then an S3 object exists at key "ingest/payment_002.pdf"
    And the S3 object metadata contains the SHA-256 hash of "PDF content bytes"
    And the returned UploadRecord has status "success" with the matching sha256_hash

  Scenario: S3 returns 503 on first two attempts - retries succeed
    Given a file "payment_003.pdf" with content "PDF retry bytes"
    And S3 returns a 503 error on the first 2 attempts
    When the file is uploaded to S3
    Then the upload succeeds on the third attempt
    And the returned UploadRecord has retry_count of 2

  Scenario: All retries exhausted - UploadFailedError raised
    Given a file "payment_004.pdf" with content "PDF fail bytes"
    And S3 returns a 503 error on all attempts
    When the file is uploaded to S3
    Then an UploadFailedError is raised
