class UploadFailedError(Exception):
    """Raised when all S3 upload retries are exhausted for a file."""


class FileDisappearedError(Exception):
    """Raised when a file on SFTP disappears before it can be downloaded (SFTPNoSuchFile)."""
