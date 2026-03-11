from __future__ import annotations

import structlog
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError

from src.models.models import UploadRecord
from src.telemetry.setup import get_tracer

_logger = structlog.get_logger(__name__)


class UploadRecordStore:
    """MongoDB-backed store for UploadRecord persistence and deduplication."""

    def __init__(self, settings) -> None:
        self._client = AsyncIOMotorClient(settings.mongo_uri)
        self._db = self._client[settings.mongo_db_name]
        self._collection = self._db["upload_records"]

    async def init(self) -> None:
        """Create a unique index on `filename` to enforce deduplication at the database level."""
        await self._collection.create_index("filename", unique=True)
        _logger.info("store_initialised", collection="upload_records")

    async def is_known(self, filename: str) -> bool:
        """Return True if an UploadRecord with this filename already exists."""
        doc = await self._collection.find_one({"filename": filename}, {"_id": 1})
        return doc is not None

    async def save(self, record: UploadRecord) -> None:
        """Persist an UploadRecord. Logs a WARNING instead of raising on duplicate filename."""
        tracer = get_tracer()
        with tracer.start_as_current_span("mongodb.save") as span:
            span.set_attribute("file.name", record.filename)
            span.set_attribute("db.collection", "upload_records")
            doc = record.model_dump(mode="json")
            try:
                await self._collection.insert_one(doc)
                span.set_attribute("db.operation", "insert")
                _logger.info("record_saved", filename=record.filename, status=record.status)
            except DuplicateKeyError:
                span.set_attribute("db.operation", "duplicate_skipped")
                _logger.warning("duplicate_record_skipped", filename=record.filename)

    async def get_all(self) -> list[UploadRecord]:
        """Return all UploadRecord documents from the store."""
        cursor = self._collection.find({}, {"_id": 0})
        docs = await cursor.to_list(length=None)
        return [UploadRecord(**doc) for doc in docs]

    async def close(self) -> None:
        """Close the MongoDB client connection."""
        self._client.close()
