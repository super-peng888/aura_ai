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
    """多模态图像向量入库：chunks 带 image_ids 时，下载图片二进制 →
    图文融合向量（图片+标题上下文，enable_fusion）→ 作为 chunk_type="image"
    的 Milvus 记录写入；无标题上下文时退化为图片独立向量。

    - 图片二进制来源：PG DocumentImage 的 oss_url（HTTP 直接下载，与 download_file 同款）
    - content 存 [IMG:xxx] 占位 + 所属 chunk 标题上下文
    - 任何一步失败仅记 warning 跳过，不阻断文档索引主流程
    """
    if not settings.DASHSCOPE_API_KEY:
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

        # 图文融合向量：图片 + 「文档名 > 标题路径」上下文融合为 1 个向量，
        # 检索时无论以文搜图还是语义描述都能命中；无上下文时退化为图片独立向量。
        # 文本向量模型（非多模态）不支持图片：有上下文的走纯文本向量，其余跳过
        supports_image = await embedding_service.supports_image()
        vectors = []
        indexable = []
        for img, binary in zip(kept, binaries):
            ctx = " > ".join(
                p for p in (doc_title, wanted[img.image_ref_id].get("heading") or "") if p
            )
            if supports_image:
                if ctx:
                    vectors.append(await embedding_service.embed_fused(text=ctx, images=[binary]))
                else:
                    vectors.append((await embedding_service.embed_images([binary]))[0])
            elif ctx:
                vectors.append(await embedding_service.embed_fused(text=ctx))
            else:
                logger.warning(
                    "当前向量模型不支持图片且图片 %s 无上下文文本，跳过图像索引", img.image_ref_id
                )
                continue
            indexable.append(img)
        kept = indexable
        if not kept:
            return

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
    """Embed chunks and insert them into Milvus.

    doc_title / kb_id 写入每条 chunk 的 metadata，用于检索侧过滤。
    chunk dict 的可选字段 heading / chunk_type 分别写入 heading_path / chunk_type。
    向量输入拼接「文档名 > 标题路径」前缀（轻量 contextual retrieval）：
    节正文往往不含所属章节/文档的关键词，结构语义补进向量可提升召回；
    Milvus 存储的 content 保持原文，引用展示不受影响。
    chunks 带 image_ids 时，额外把图像以 chunk_type="image" 记录入库
    （失败不阻断，见 _index_image_chunks）。

    Returns the list of milvus_ids (as strings) aligned with `chunks` order.
    """
    from app.services.embedding_service import embedding_service
    from app.storage.milvus_client import milvus_client

    texts = [c["content"] for c in chunks]
    embed_texts = []
    for c in chunks:
        prefix = " > ".join(p for p in (doc_title, c.get("heading") or "") if p)
        embed_texts.append(f"{prefix}\n{c['content']}" if prefix else c["content"])
    dense_vectors = await embedding_service.embed_dense(embed_texts)

    milvus_ids = milvus_client.insert_chunks(
        chunk_ids=[c["chunk_id"] for c in chunks],
        document_ids=[document_id] * len(chunks),
        contents=texts,
        embeddings=dense_vectors,
        sparse_embeddings=None,
        metadata_list=[
            {
                "page_number": c.get("page", c.get("page_number", 1)),
                "chunk_index": i,
                "image_ids": c.get("image_ids", []),
                "doc_title": doc_title,
                "kb_id": kb_id,
                "heading_path": c.get("heading", ""),
                "chunk_type": c.get("chunk_type", "text"),
                # 父子分块：子块携带父节 id 与完整内容，检索命中后回捞父节送 LLM
                **(
                    {"parent_id": c["parent_id"], "parent_content": c["parent_content"]}
                    if c.get("parent_id")
                    else {}
                ),
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
