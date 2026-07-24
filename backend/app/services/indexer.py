"""Document indexer: generate embeddings and insert/delete chunks in Milvus.

PG chunk bookkeeping (milvus_id backfill) is the caller's responsibility.
"""

import hashlib
import logging
from typing import List

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def _image_chunk_id(chunk_id: str, image_id: str) -> str:
    """图像 chunk 的确定性 chunk_id（短哈希，保证 reindex/删除可定位且不超 64 字符）。"""
    digest = hashlib.sha1(f"{chunk_id}#{image_id}".encode()).hexdigest()[:32]
    return f"img_{digest}"


async def _index_image_chunks(
    document_id: str,
    chunks: List[dict],
    doc_title: str,
    kb_id: str,
) -> None:
    """多模态图像向量入库：chunks 带 image_ids 且配置了 EMBEDDING_MULTIMODAL_MODEL 时，
    下载图片二进制 → embed_images → 作为 chunk_type="image" 的 Milvus 记录写入。

    - 图片二进制来源：PG DocumentImage 的 oss_url（HTTP 直接下载，与 download_file 同款）
    - content 存 [IMG:xxx] 占位 + 所属 chunk 标题上下文；sparse 向量用空稀疏 {}
      （图像无语义词项，混入标题文本的伪稀疏反而引入噪声）
    - 任何一步失败仅记 warning 跳过，不阻断文档索引主流程
    """
    if not settings.EMBEDDING_MULTIMODAL_MODEL:
        return

    wanted: dict[str, dict] = {}  # image_id -> 所属 chunk（首次出现者，携带标题上下文）
    for c in chunks:
        for image_id in c.get("image_ids") or []:
            wanted.setdefault(image_id, c)
    if not wanted:
        return

    try:
        import httpx

        from app.db.base import AsyncSessionLocal
        from app.db.repository import image_repo
        from app.services.embedding_service import embedding_service
        from app.storage.milvus_client import milvus_client

        async with AsyncSessionLocal() as session:
            images = await image_repo.get_by_ref_ids(session, list(wanted.keys()))
        images = [img for img in images if img.oss_url]
        if not images:
            return

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            binaries = []
            kept = []
            for img in images:
                try:
                    resp = await client.get(img.oss_url)
                    resp.raise_for_status()
                    binaries.append(resp.content)
                    kept.append(img)
                except Exception as e:
                    logger.warning("下载图片 %s 失败，跳过图像索引: %s", img.image_ref_id, e)
        if not binaries:
            return

        vectors = await embedding_service.embed_images(binaries)

        milvus_client.insert_chunks(
            chunk_ids=[_image_chunk_id(wanted[img.image_ref_id]["chunk_id"], img.image_ref_id) for img in kept],
            document_ids=[document_id] * len(kept),
            contents=[
                f"[IMG:{img.image_ref_id}] {wanted[img.image_ref_id].get('heading') or ''}".strip()
                for img in kept
            ],
            embeddings=vectors,
            sparse_embeddings=[{}] * len(kept),
            metadata_list=[
                {
                    "page_number": img.page_number or wanted[img.image_ref_id].get("page", 1),
                    "chunk_index": wanted[img.image_ref_id].get("chunk_index", 0),
                    "image_ids": [img.image_ref_id],
                    "doc_title": doc_title,
                    "kb_id": kb_id,
                    "heading_path": wanted[img.image_ref_id].get("heading", ""),
                    "chunk_type": "image",
                }
                for img in kept
            ],
        )
        logger.info("Indexed %d image chunks for document %s", len(kept), document_id)
    except Exception:
        logger.exception("Image embedding indexing failed for document %s (ignored)", document_id)


async def index_document(
    document_id: str,
    chunks: List[dict],
    doc_title: str = "",
    kb_id: str = "",
) -> list:
    """Embed chunks (dense + sparse) and insert them into Milvus.

    doc_title / kb_id 写入每条 chunk 的 metadata，用于检索侧过滤。
    chunk dict 的可选字段 heading / chunk_type 分别写入 heading_path / chunk_type。
    配置了 EMBEDDING_MULTIMODAL_MODEL 且 chunks 带 image_ids 时，额外把图像
    以 chunk_type="image" 记录入库（失败不阻断，见 _index_image_chunks）。

    Returns the list of milvus_ids (as strings) aligned with `chunks` order.
    """
    from app.services.embedding_service import embedding_service
    from app.storage.milvus_client import milvus_client

    texts = [c["content"] for c in chunks]
    dense_vectors = await embedding_service.embed_dense(texts)
    sparse_vectors = await embedding_service.embed_sparse(texts)

    milvus_ids = milvus_client.insert_chunks(
        chunk_ids=[c["chunk_id"] for c in chunks],
        document_ids=[document_id] * len(chunks),
        contents=texts,
        embeddings=dense_vectors,
        sparse_embeddings=sparse_vectors,
        metadata_list=[
            {
                "page_number": c.get("page", c.get("page_number", 1)),
                "chunk_index": i,
                "image_ids": c.get("image_ids", []),
                "doc_title": doc_title,
                "kb_id": kb_id,
                "heading_path": c.get("heading", ""),
                "chunk_type": c.get("chunk_type", "text"),
            }
            for i, c in enumerate(chunks)
        ],
    )

    await _index_image_chunks(document_id, chunks, doc_title, kb_id)

    return [str(mid) for mid in milvus_ids]


async def delete_document(document_id: str) -> None:
    """Delete all Milvus chunks belonging to a document."""
    from app.storage.milvus_client import milvus_client

    milvus_client.delete_by_document(document_id)
