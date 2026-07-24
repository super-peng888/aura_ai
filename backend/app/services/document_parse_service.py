"""文档解析编排服务（Phase 2 自 app.api.documents 下沉）。

职责：下载源文件 -> 解析 -> 图片上传 OSS -> 分块 -> PG 元数据落库 -> 索引（队列或同步），
并统一 sync（parse-sync）/ async（index worker）两条路径的 parse_status 状态机：
running -> indexing（异步，索引交 worker）/ completed（同步），异常 -> failed。

索引完成后的 GraphRAG 图谱构建（build_graph_after_index）由本模块统一提供，
sync 路径与 index worker 共用，受检索配置 enable_graph_rag 开关控制。
"""

import asyncio
import logging
import os
import tempfile

from app.db.base import AsyncSessionLocal
from app.db.models import DocumentChunk, DocumentImage
from app.db.repository import (
    chunk_repo,
    document_repo,
    image_repo,
    parse_strategy_repo,
    user_repo,
)
from app.services import indexer
from app.services.document_parser import (
    ParseStrategyConfig,
    parse_document,
    split_pages_to_chunks,
)
from app.services.index_queue import enqueue_index_task
from app.services.parse_config_service import parse_config_service
from app.services.retrieval_config_service import retrieval_config_service

logger = logging.getLogger(__name__)


class DocumentNotFoundError(Exception):
    """文档不存在（API 层据此映射 404）。"""


async def download_file(oss_url: str, temp_path: str) -> str:
    """从 OSS URL 下载文件到本地临时路径。"""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(oss_url, timeout=60)
        resp.raise_for_status()
        with open(temp_path, "wb") as f:
            f.write(resp.content)
    return temp_path


def _strategy_from_row(strategy) -> ParseStrategyConfig:
    """ParseStrategy ORM 行 -> ParseStrategyConfig。"""
    return ParseStrategyConfig(
        parse_mode=strategy.parse_mode,
        chunk_size=strategy.chunk_size,
        chunk_overlap=strategy.chunk_overlap,
        split_method=strategy.split_method,
        extract_images=strategy.extract_images,
        dimension=strategy.dimension,
    )


async def get_user_strategy(session, user_id: str) -> ParseStrategyConfig:
    """获取用户默认解析策略，如果没有则返回系统默认。"""
    user = await user_repo.get(session, user_id)
    if user and user.default_strategy_id:
        strategy = await parse_strategy_repo.get(session, user.default_strategy_id)
        if strategy:
            return _strategy_from_row(strategy)
    return ParseStrategyConfig()


def _apply_strategy_override(strategy: ParseStrategyConfig, override) -> ParseStrategyConfig:
    """在基底策略上应用显式覆盖参数（DocumentParseRequest/ChunkPreviewRequest，None 字段跳过）。"""
    if not override:
        return strategy
    parse_mode = getattr(override, "parse_mode", None)
    if parse_mode is not None:
        strategy.parse_mode = parse_mode.value if hasattr(parse_mode, "value") else str(parse_mode)
    split_method = getattr(override, "split_method", None)
    if split_method is not None:
        strategy.split_method = split_method.value if hasattr(split_method, "value") else str(split_method)
    for field in ("chunk_size", "chunk_overlap", "extract_images"):
        value = getattr(override, field, None)
        if value is not None:
            setattr(strategy, field, value)
    return strategy


async def resolve_strategy(session, user_id: str, document=None, override=None) -> ParseStrategyConfig:
    """解析生效的解析策略。

    基底优先级：显式 strategy_id > document.strategy_id > 用户默认策略 > 系统默认；
    内联参数（parse_mode/chunk_size/chunk_overlap/split_method/extract_images）
    在基底策略上覆盖。
    """
    strategy_row = None
    explicit_strategy_id = getattr(override, "strategy_id", None) if override else None
    if explicit_strategy_id:
        strategy_row = await parse_strategy_repo.get(session, explicit_strategy_id)
    if strategy_row is None and document is not None and getattr(document, "strategy_id", None):
        strategy_row = await parse_strategy_repo.get(session, document.strategy_id)

    if strategy_row is not None:
        config = _strategy_from_row(strategy_row)
    else:
        config = await get_user_strategy(session, user_id)
    return _apply_strategy_override(config, override)


async def upload_raw_images(raw_images: list, doc_id: str) -> list:
    """将解析得到的原始图片上传到 OSS，返回包含 oss_url 的图片信息列表。"""
    from app.services.storage_service import storage_service
    uploaded = []
    for img in raw_images:
        object_key = await storage_service.upload_file(
            data=img["data"],
            document_id=doc_id,
            filename=img["filename"],
            content_type=img["content_type"],
            prefix="images",
        )
        oss_url = storage_service.get_url(object_key)
        uploaded.append({
            "image_id": img["image_id"],
            "oss_url": oss_url,
            "oss_key": object_key,
            "width": img.get("width"),
            "height": img.get("height"),
            "page_number": img.get("page_number"),
            "seq": img.get("seq"),
        })
    return uploaded


async def save_parse_metadata(
    document_id: str,
    chunks: list[dict],
    uploaded_images: list[dict],
    strategy: ParseStrategyConfig,
) -> None:
    """Persist chunk and image metadata to PostgreSQL with a pending milvus_id.

    自包含 session（AsyncSessionLocal）并显式 commit，调用方无需管理事务。
    """
    async with AsyncSessionLocal() as session:
        for idx, chunk in enumerate(chunks):
            db_chunk = DocumentChunk(
                document_id=document_id,
                content=chunk["content"],
                milvus_id="pending",
                page_number=chunk.get("page"),
                chunk_index=idx,
                image_ids=chunk.get("image_ids", []),
            )
            await chunk_repo.create(session, db_chunk)

        for img in uploaded_images:
            db_image = DocumentImage(
                document_id=document_id,
                page_number=img.get("page_number"),
                oss_url=img.get("oss_url", ""),
                image_ref_id=img["image_id"],
                width=img.get("width"),
                height=img.get("height"),
            )
            await image_repo.create(session, db_image)

        await session.commit()


def _resolve_chunk_index(chunk_payload: dict, fallback: int) -> int:
    """解析 chunk payload 对应的 PG chunk_index。

    优先从 chunk_id 后缀解析（split_pages_to_chunks 生成的 chunk_id 形如
    ``{doc_id}_chunk_{idx:04d}``，后缀即 chunk_index），其次显式 chunk_index
    字段，最后退化为 payload 在列表中的位置。
    """
    chunk_id = chunk_payload.get("chunk_id")
    if chunk_id:
        try:
            return int(str(chunk_id).rsplit("_chunk_", 1)[1])
        except (IndexError, ValueError):
            pass
    chunk_index = chunk_payload.get("chunk_index")
    if isinstance(chunk_index, int):
        return chunk_index
    return fallback


async def update_chunk_milvus_ids(document_id: str, chunks: list[dict], milvus_ids: list[str]) -> None:
    """索引完成后回填各 chunk 的 milvus_id 并显式 commit 落库。

    sync（parse-sync）与 async（index worker）两条索引路径共用的唯一实现。
    milvus_ids 与 chunks 顺序对齐（indexer.index_document 的返回约定）；
    到 PG chunk 记录的映射按 chunk_id（后缀即 chunk_index）定位，比按列表
    位置对齐更防乱序；PG 中无匹配记录时兜底新建。
    自包含 session（AsyncSessionLocal），调用方无需管理事务。
    """
    if not chunks or not milvus_ids:
        return
    if len(chunks) != len(milvus_ids):
        logger.warning(
            "update_chunk_milvus_ids: document %s chunks(%d) 与 milvus_ids(%d) 长度不一致，按较短者对齐",
            document_id, len(chunks), len(milvus_ids),
        )

    async with AsyncSessionLocal() as session:
        db_chunks = await chunk_repo.list_by_document(session, document_id)
        db_by_index = {c.chunk_index: c for c in db_chunks}

        for pos, (chunk_payload, milvus_id) in enumerate(zip(chunks, milvus_ids)):
            chunk_index = _resolve_chunk_index(chunk_payload, pos)
            db_chunk = db_by_index.get(chunk_index)
            if db_chunk is not None:
                db_chunk.milvus_id = str(milvus_id)
            else:
                # Fallback: create chunk record if missing
                session.add(DocumentChunk(
                    document_id=document_id,
                    content=chunk_payload["content"],
                    milvus_id=str(milvus_id),
                    page_number=chunk_payload.get("page", chunk_payload.get("page_number")),
                    chunk_index=chunk_index,
                    image_ids=chunk_payload.get("image_ids", []),
                ))

        await session.commit()


async def build_graph_after_index(document_id: str, chunks: list[dict]) -> None:
    """向量索引完成后的 GraphRAG 图谱构建（入库侧）。

    受检索配置 enable_graph_rag 开关控制；失败仅记日志，不阻断索引主流程。
    sync（parse-sync）与 async（index worker）两条索引路径共用。
    """
    try:
        cfg = await retrieval_config_service.resolve()
        if not cfg.get("enable_graph_rag", False):
            return
        from app.core.knowledge.graph import builder as graph_builder

        graph_stats = await graph_builder.build_document_graph(document_id, chunks)
        community_stats = await graph_builder.rebuild_communities()
        logger.info(
            "GraphRAG for document %s: graph=%s communities=%s",
            document_id, graph_stats, community_stats,
        )
    except Exception:
        logger.exception("GraphRAG build failed for document %s (ignored)", document_id)


async def index_document_sync(
    document_id: str,
    chunks: list[dict],
    doc_title: str = "",
    kb_id: str = "",
) -> list:
    """parse-sync 的同步索引路径：向量索引 + milvus_id 回填 + （开关内）图谱构建。"""
    milvus_ids = await indexer.index_document(document_id, chunks, doc_title=doc_title, kb_id=kb_id)
    await update_chunk_milvus_ids(document_id, chunks, milvus_ids)
    await build_graph_after_index(document_id, chunks)
    return milvus_ids


async def do_parse(
    doc_id: str,
    temp_path: str,
    user_id: str,
    *,
    enqueue_index: bool = True,
    strategy_override=None,
) -> dict:
    """Parse, upload images, chunk, then either enqueue or sync index."""
    async with AsyncSessionLocal() as session:
        doc = await document_repo.get(session, doc_id)
        strategy = await resolve_strategy(session, user_id, doc, strategy_override)
        doc_title = (doc.original_name if doc else "") or ""
        kb_id = (doc.category_id if doc else None) or ""

    # 注入系统级 VLM 配置（仅 vlm 模式会读取；其余模式注入亦无副作用）
    strategy.vlm_config = await parse_config_service.resolve_vlm_for_strategy()

    # 1. 同步解析（在线程池中执行，避免阻塞事件循环）
    loop = asyncio.get_running_loop()
    parse_result = await loop.run_in_executor(None, parse_document, temp_path, doc_id, strategy)

    # 2. 异步上传图片到 OSS
    uploaded_images = await upload_raw_images(parse_result.raw_images, doc_id)

    # 3. 将 OSS URL 回填到 page.images 中
    for page in parse_result.pages:
        for img in page.images:
            for up in uploaded_images:
                if up["image_id"] == img.get("image_id"):
                    img["oss_url"] = up["oss_url"]

    # 4. 分块
    chunks = split_pages_to_chunks(parse_result.pages, strategy, doc_id)

    # 5. 保存业务元数据（chunk / image）到 PG（自包含 commit）
    await save_parse_metadata(doc_id, chunks, uploaded_images, strategy)

    result = {
        "doc_id": doc_id,
        "pages": parse_result.pages,
        "chunks": chunks,
        "uploaded_images": uploaded_images,
        "total_images": len(uploaded_images),
        "mode_used": parse_result.mode_used,
        "strategy": strategy,
    }

    # 6. 向量化：后台任务走队列，同步任务直接索引
    if enqueue_index:
        await enqueue_index_task(
            document_id=doc_id,
            chunks=chunks,
            uploaded_images=uploaded_images,
            doc_title=doc_title,
            kb_id=kb_id,
        )
    else:
        await index_document_sync(doc_id, chunks, doc_title=doc_title, kb_id=kb_id)

    return result


async def run_parse_pipeline(document_id: str, *, enqueue_index: bool, strategy_override=None) -> dict:
    """文档解析状态机（sync / async 两条路径共用）。

    状态流转：running -> indexing（enqueue_index=True，索引交 worker 异步完成）
    / completed（enqueue_index=False，同步索引完成后直接终态）；
    任一步骤异常 -> failed 并落库 parse_error，随后原样抛出由调用方处理。

    strategy_override：可选的 DocumentParseRequest；显式指定 strategy_id 时
    持久化到 document.strategy_id，后续解析默认沿用。
    """
    async with AsyncSessionLocal() as session:
        doc = await document_repo.get(session, document_id)
        if not doc:
            raise DocumentNotFoundError(document_id)
        doc.parse_status = "running"
        if strategy_override is not None and getattr(strategy_override, "strategy_id", None):
            doc.strategy_id = strategy_override.strategy_id
        await session.commit()
        user_id = doc.user_id
        oss_url = doc.oss_url
        filename = doc.filename

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp:
            temp_path = tmp.name

        await download_file(oss_url, temp_path)
        result = await do_parse(
            document_id, temp_path, user_id,
            enqueue_index=enqueue_index, strategy_override=strategy_override,
        )

        async with AsyncSessionLocal() as session:
            doc = await document_repo.get(session, document_id)
            doc.parse_status = "indexing" if enqueue_index else "completed"
            doc.page_count = len(result["pages"])
            doc.parse_error = None
            strategy = result.get("strategy")
            if strategy:
                doc.parse_mode = strategy.parse_mode
                doc.chunk_size = strategy.chunk_size
                doc.chunk_overlap = strategy.chunk_overlap
                doc.dimension = strategy.dimension
            await session.commit()

        return result
    except Exception as e:
        async with AsyncSessionLocal() as session:
            doc = await document_repo.get(session, document_id)
            if doc:
                doc.parse_status = "failed"
                doc.parse_error = str(e)
                await session.commit()
        raise
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


async def trigger_parse_background(document_id: str, strategy_override=None) -> None:
    """后台触发文档解析（BackgroundTasks 入口）。

    状态流转由 run_parse_pipeline 统一负责；异常已落库为 failed，此处仅记日志。
    """
    try:
        await run_parse_pipeline(document_id, enqueue_index=True, strategy_override=strategy_override)
    except Exception:
        logger.exception("Background parse failed for document %s", document_id)
