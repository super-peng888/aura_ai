"""Async index queue based on Redis Streams.

Producer: backend parses a document and pushes an index task.
Consumer: app.workers.index_worker reads the stream and calls the retrieval layer.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from app.config import get_settings
from app.utils.cache import get_redis

settings = get_settings()


async def enqueue_index_task(
    document_id: str,
    chunks: List[dict],
    uploaded_images: Optional[List[dict]] = None,
    doc_title: str = "",
    kb_id: str = "",
) -> str:
    """Enqueue a document indexing task into Redis Streams.

    Returns the Redis stream message ID.
    """
    redis = get_redis()
    payload = {
        "document_id": document_id,
        "chunks": chunks,
        "uploaded_images": uploaded_images or [],
        "doc_title": doc_title,
        "kb_id": kb_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    message_id = await redis.xadd(
        settings.INDEX_QUEUE_STREAM,
        {"payload": json.dumps(payload, ensure_ascii=False, default=str)},
        maxlen=settings.INDEX_QUEUE_MAX_LEN,
        approximate=True,
    )
    return str(message_id)


async def ensure_consumer_group() -> None:
    """Create the consumer group if it does not exist."""
    redis = get_redis()
    try:
        await redis.xgroup_create(
            settings.INDEX_QUEUE_STREAM,
            settings.INDEX_QUEUE_GROUP,
            id="0",
            mkstream=True,
        )
    except Exception as e:
        # Redis response error if group already exists
        if "already exists" not in str(e).lower():
            raise


async def read_index_tasks(consumer_name: str, count: int = 1, block_ms: int = 5000):
    """Read pending/new tasks from the consumer group.

    Returns list of tuples (message_id, payload_dict).
    """
    redis = get_redis()
    raw = await redis.xreadgroup(
        groupname=settings.INDEX_QUEUE_GROUP,
        consumername=consumer_name,
        streams={settings.INDEX_QUEUE_STREAM: ">"},
        count=count,
        block=block_ms,
    )

    tasks = []
    for stream, entries in raw:
        for message_id, fields in entries:
            payload_raw = fields.get("payload") or fields.get(b"payload")
            if isinstance(payload_raw, bytes):
                payload_raw = payload_raw.decode("utf-8")
            payload = json.loads(payload_raw)
            tasks.append((str(message_id), payload))
    return tasks


async def ack_index_task(message_id: str) -> None:
    """Acknowledge a processed task."""
    redis = get_redis()
    await redis.xack(settings.INDEX_QUEUE_STREAM, settings.INDEX_QUEUE_GROUP, message_id)


async def claim_stale_tasks(consumer_name: str, min_idle_ms: int = 60_000, count: int = 10):
    """Claim tasks that have been idle for too long (useful for failover)."""
    redis = get_redis()
    pending = await redis.xpending_range(
        settings.INDEX_QUEUE_STREAM,
        settings.INDEX_QUEUE_GROUP,
        min="-",
        max="+",
        count=count,
    )
    tasks = []
    for item in pending:
        if item["time_since_delivered"] >= min_idle_ms:
            claimed = await redis.xclaim(
                settings.INDEX_QUEUE_STREAM,
                settings.INDEX_QUEUE_GROUP,
                consumer_name,
                min_idle_time=min_idle_ms,
                message_ids=[item["message_id"]],
            )
            for message_id, fields in claimed:
                payload_raw = fields.get("payload") or fields.get(b"payload")
                if isinstance(payload_raw, bytes):
                    payload_raw = payload_raw.decode("utf-8")
                payload = json.loads(payload_raw)
                tasks.append((str(message_id), payload))
    return tasks
