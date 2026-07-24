"""Standalone worker that consumes Redis Streams index tasks.

Run with:
    cd backend && python -m app.workers.index_worker
"""

import asyncio
import json
import logging
import socket
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.config import get_settings
from app.db.base import AsyncSessionLocal
from app.db.models import Document
from app.db.repository import document_repo
from app.services.index_queue import (
    ensure_consumer_group,
    read_index_tasks,
    ack_index_task,
)
from app.services import indexer
from app.services.document_parse_service import build_graph_after_index, update_chunk_milvus_ids
from app.utils.cache import close_redis

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

CONSUMER_NAME = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"


async def _update_document_status(
    session,
    document_id: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    doc = await document_repo.get(session, document_id)
    if not doc:
        logger.warning("Document %s not found when updating status", document_id)
        return
    doc.parse_status = status
    if error is not None:
        doc.parse_error = error
    if status == "completed":
        doc.parse_error = None
    await session.commit()


async def _process_task(payload: dict) -> None:
    document_id = payload["document_id"]
    chunks = payload.get("chunks", [])
    doc_title = payload.get("doc_title", "")
    kb_id = payload.get("kb_id", "")

    logger.info("Processing index task for document %s (%s chunks)", document_id, len(chunks))

    # 兼容旧队列消息：缺少 doc_title/kb_id 时从 PG 补全
    if not doc_title or not kb_id:
        async with AsyncSessionLocal() as session:
            doc = await document_repo.get(session, document_id)
            if doc:
                doc_title = doc_title or (doc.original_name or "")
                kb_id = kb_id or (doc.category_id or "")

    async with AsyncSessionLocal() as session:
        await _update_document_status(session, document_id, "indexing")

    try:
        milvus_ids = await indexer.index_document(
            document_id=document_id,
            chunks=chunks,
            doc_title=doc_title,
            kb_id=kb_id,
        )

        await update_chunk_milvus_ids(document_id, chunks, milvus_ids)
        async with AsyncSessionLocal() as session:
            await _update_document_status(session, document_id, "completed")

        logger.info("Indexed document %s -> %s milvus ids", document_id, len(milvus_ids))

        # GraphRAG 图谱构建（入库侧，与 parse-sync 同步路径共用；失败不阻断主流程）。
        await build_graph_after_index(document_id, chunks)

    except Exception as e:
        logger.exception("Failed to index document %s", document_id)
        async with AsyncSessionLocal() as session:
            await _update_document_status(session, document_id, "failed", error=str(e))
        raise


async def _consume_loop() -> None:
    await ensure_consumer_group()
    logger.info("Index worker started: consumer=%s", CONSUMER_NAME)

    while True:
        try:
            tasks = await read_index_tasks(CONSUMER_NAME, count=1, block_ms=5000)
            if not tasks:
                continue

            for message_id, payload in tasks:
                try:
                    await _process_task(payload)
                    await ack_index_task(message_id)
                except Exception:
                    # Already logged and marked document as failed; ack to avoid endless retry.
                    try:
                        await ack_index_task(message_id)
                    except Exception as ack_err:
                        logger.error("Failed to ack message %s: %s", message_id, ack_err)

        except asyncio.CancelledError:
            logger.info("Index worker cancelled")
            break
        except Exception as e:
            logger.exception("Unexpected error in consume loop: %s", e)
            await asyncio.sleep(1)


async def main() -> None:
    try:
        await _consume_loop()
    finally:
        await close_redis()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Index worker stopped by user")
