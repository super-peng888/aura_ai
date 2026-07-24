"""批量重建 Milvus 索引：重新解析分块并写入完整元数据（doc_title/kb_id/heading_path/chunk_type）。

用法：
    python scripts/reindex_documents.py --all
    python scripts/reindex_documents.py --doc-id <id> [--doc-id <id> ...]

流程（每个文档）：
    删 Milvus 向量 -> 重新解析分块 -> 重建 PG chunk 记录 -> indexer.index_document（带新 metadata）
"""

import argparse
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, select

from app.db.base import AsyncSessionLocal
from app.db.models import Document, DocumentChunk
from app.services import indexer
from app.services.document_parser import parse_document, split_pages_to_chunks
from app.services.document_parse_service import (
    download_file,
    get_user_strategy,
    save_parse_metadata,
    update_chunk_milvus_ids,
)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="重建 Milvus 文档索引")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="重建全部文档")
    group.add_argument("--doc-id", dest="doc_ids", action="append", metavar="ID",
                       help="指定文档 ID（可多次传入）")
    return parser.parse_args(argv)


async def reindex_document(doc: Document) -> int:
    """重建单个文档的索引，返回 chunk 数。"""
    document_id = str(doc.id)

    async with AsyncSessionLocal() as session:
        strategy = await get_user_strategy(session, doc.user_id)

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(doc.filename)[1]) as tmp:
            temp_path = tmp.name
        await download_file(doc.oss_url, temp_path)

        # 同步解析（线程池）+ 分块；图片不重复上传，沿用既有 DocumentImage 记录
        loop = asyncio.get_event_loop()
        parse_result = await loop.run_in_executor(None, parse_document, temp_path, document_id, strategy)
        chunks = split_pages_to_chunks(parse_result.pages, strategy, document_id)

        # 删除旧的 Milvus 向量与 PG chunk 记录，重建 chunk 元数据
        await indexer.delete_document(document_id)
        async with AsyncSessionLocal() as session:
            await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
            await session.commit()
        await save_parse_metadata(document_id, chunks, [], strategy)

        milvus_ids = await indexer.index_document(
            document_id,
            chunks,
            doc_title=doc.original_name or "",
            kb_id=doc.category_id or "",
        )

        await update_chunk_milvus_ids(document_id, chunks, milvus_ids)
        async with AsyncSessionLocal() as session:
            fresh = await session.get(Document, document_id)
            if fresh:
                fresh.parse_status = "completed"
                fresh.page_count = len(parse_result.pages)
                fresh.parse_error = None
            await session.commit()

        return len(chunks)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


async def run(doc_ids=None) -> int:
    """批量重建入口。doc_ids 为 None 时重建全部文档。返回进程退出码。"""
    async with AsyncSessionLocal() as session:
        stmt = select(Document)
        if doc_ids:
            stmt = stmt.where(Document.id.in_(doc_ids))
        result = await session.execute(stmt)
        docs = list(result.scalars().all())
        session.expunge_all()

    total = len(docs)
    succeeded = failed = 0
    for i, doc in enumerate(docs, 1):
        try:
            n = await reindex_document(doc)
            succeeded += 1
            print(f"[{i}/{total}] {doc.id} OK ({n} chunks)")
        except Exception as e:
            failed += 1
            print(f"[{i}/{total}] {doc.id} FAIL: {e}")

    print(f"完成: 成功 {succeeded}, 失败 {failed}, 共 {total}")
    return 0 if failed == 0 else 1


def main(argv=None) -> int:
    args = parse_args(argv)
    doc_ids = None if args.all else args.doc_ids
    return asyncio.run(run(doc_ids))


if __name__ == "__main__":
    sys.exit(main())
