from __future__ import annotations

from typing import List, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # SFTP
    sftp_host: str = Field(..., description="SFTP server hostname or IP")
    sftp_port: int = Field(22, description="SFTP server port")
    sftp_username: str = Field(..., description="SFTP login username")
    sftp_password: Optional[str] = Field(None, description="SFTP password (mutually exclusive with sftp_key_path)")
    sftp_key_path: Optional[str] = Field(None, description="Path to SSH private key file")
    sftp_remote_dir: str = Field(..., description="Remote directory to poll for new files")
    sftp_poll_interval_s: int = Field(30, description="Seconds between SFTP poll cycles")

    # S3
    s3_bucket: str = Field(..., description="Target S3 bucket name")
    s3_key_prefix: str = Field("ingest", description="S3 key prefix (folder) for uploaded files")
    s3_endpoint_url: Optional[str] = Field(
        None, description="Override S3 endpoint (e.g. http://localhost:4566 for LocalStack)"
    )
    aws_region: str = Field("eu-west-2", description="AWS region")
    aws_access_key_id: Optional[str] = Field(None)
    aws_secret_access_key: Optional[str] = Field(None)

    # Retry
    sftp_max_reconnect_attempts: int = Field(5, description="Maximum SFTP reconnect attempts")
    s3_max_upload_retries: int = Field(5, description="Maximum S3 upload retry attempts per file")
    backoff_base: float = Field(2.0, description="Exponential backoff multiplier (seconds)")

    # File filtering
    extension_allowlist: List[str] = Field([".pdf"], description="Allowed file extensions (lowercase)")

    # MongoDB
    mongo_uri: str = Field("mongodb://localhost:27017", description="MongoDB connection string")
    mongo_db_name: str = Field("mmp_ai", description="MongoDB database name")

    # Observability
    health_port: int = Field(8080, description="Port for /health and /-/metrics endpoints")
    otel_exporter_otlp_endpoint: Optional[str] = Field(
        None, description="OTLP exporter endpoint (e.g. http://otel-collector:4317)"
    )

    @model_validator(mode="after")
    def require_sftp_auth(self) -> "Settings":
        if not self.sftp_password and not self.sftp_key_path:
            raise ValueError("At least one of sftp_password or sftp_key_path must be provided")
        return self

    @model_validator(mode="after")
    def validate_extension_allowlist(self) -> "Settings":
        for ext in self.extension_allowlist:
            if not ext.startswith(".") or ext != ext.lower():
                raise ValueError(f"extension_allowlist entry must start with '.' and be lowercase: {ext!r}")
        return self

    @model_validator(mode="after")
    def validate_s3_key_prefix(self) -> "Settings":
        if self.s3_key_prefix.startswith("/") or self.s3_key_prefix.endswith("/"):
            raise ValueError("s3_key_prefix must not start or end with '/'")
        return self
