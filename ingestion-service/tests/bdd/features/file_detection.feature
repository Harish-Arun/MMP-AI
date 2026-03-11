Feature: Automatic File Detection
  As an operations engineer
  I want new PDF files placed on the SFTP server to be automatically detected and uploaded to S3
  So that document processing can be triggered without manual intervention

  Background:
    Given the SFTP watcher is configured with extension allowlist [".pdf"]
    And the MongoDB record store is empty

  Scenario: New PDF file detected and uploaded within 60 seconds
    Given a file "payment_001.pdf" of size 1024 bytes exists on the SFTP server
    When the watcher completes two poll cycles with the same file size
    Then the file event "payment_001.pdf" is yielded as write-complete
    And an UploadRecord with status "success" is saved to MongoDB

  Scenario: File still being written - upload deferred until size stable
    Given a file "growing_report.pdf" of size 1024 bytes exists on the SFTP server
    When the watcher completes the first poll cycle
    Then the file event "growing_report.pdf" is NOT yet yielded as write-complete
    When the file size changes to 2048 bytes on the second poll
    Then the file event "growing_report.pdf" is still NOT yet yielded as write-complete
    When the watcher completes a third poll cycle with the same size 2048 bytes
    Then the file event "growing_report.pdf" is yielded as write-complete

  Scenario: Same filename placed again - duplicate warning, no re-upload
    Given a file "payment_001.pdf" has already been uploaded and recorded in MongoDB
    And a file "payment_001.pdf" of size 1024 bytes exists on the SFTP server
    When the watcher performs a poll cycle
    Then the duplicate is detected and a WARNING log is emitted
    And the file "payment_001.pdf" is NOT yielded for upload

  Scenario: Zero-byte file across two polls - warning, not uploaded
    Given a file "empty_doc.pdf" of size 0 bytes exists on the SFTP server
    When the watcher completes two poll cycles with size 0
    Then a WARNING log is emitted for "empty_doc.pdf"
    And the file "empty_doc.pdf" is NOT yielded for upload

  Scenario: Non-PDF file silently ignored
    Given a file "spreadsheet.xlsx" of size 512 bytes exists on the SFTP server
    When the watcher performs a poll cycle
    Then "spreadsheet.xlsx" is silently ignored
    And no log event is emitted for "spreadsheet.xlsx"
