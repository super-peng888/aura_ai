"""文档解析编排服务（Phase 2 自 app.api.documents 下沉）。

职责：下载源文件 -> 解析 -> 图片上传 OSS -> 分块 -> PG 图片元数据落库 -> 索引（队列或同步），
并统一 sync（parse-sync）/ async（index worker）两条路径的 parse_status 状态机：
running -> indexing（异步，索引交 worker）/ completed（同步），异常 -> failed。

分块内容不再写入 PG（Milvus 的 content+metadata 已完整承载分块数据）。

索引完成后的 GraphRAG 图谱构建（build_graph_after_index）由本模块统一提供，
sync 路径与 index worker 共用，受检索配置 enable_graph_rag 开关控制。
"""

import asyncio
import logging
import mimetypes
import os
import tempfile
from typing import Optional

from app.db.base import AsyncSessionLocal
from app.db.models import DocumentImage
from app.config import get_settings
from app.db.repository import (
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
from app.services.retrieval_config_service import retrieval_config_service

logger = logging.getLogger(__name__)
settings = get_settings()


# Office 类 mime 显式后缀映射：Windows 上 mimetypes 受注册表影响，可能把
# docx 的 mime 猜成 .doc，导致解析路由/报错文案错乱，故不依赖系统猜测。
_MIME_SUFFIX_OVERRIDES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
}


def resolve_temp_suffix(filename: str, original_name: str = "", mime_type: str = "") -> str:
    """推断下载源文件的临时后缀。

    解析路由（parse_document 按 path.suffix 区分 文本/图片/PDF）与 PyMuPDF/OCR
    均依赖文件扩展名，缺失会导致 "cannot find document handler"。上传时
    filename 由 mimetypes 推断，在 Windows 上可能因注册表缺失而为空，故依次
    回退到用户原始文件名 original_name，最后按 mime_type 猜测。
    """
    for name in (filename, original_name):
        ext = os.path.splitext(name or "")[1]
        if ext:
            return ext
    if mime_type:
        return _MIME_SUFFIX_OVERRIDES.get(mime_type) or mimetypes.guess_extension(mime_type) or ""
    return ""


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
        vlm_model_ref=strategy.vlm_model_ref,
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


async def _inject_vlm_config(session, strategy: ParseStrategyConfig, user_id: Optional[str] = None) -> ParseStrategyConfig:
    """parse_mode=vlm 时按 vlm_model_ref 解析多模态模型配置并注入 vlm_* 字段。

    None/'system' → 跟随系统 VLM 角色（system_model_service.resolve("general")）；
    具体 id → provider_models（需 capability=multi_modal，且为系统或本人私有
    供应商下的模型），缺失或不满足时回落系统 VLM 角色并记 warning。
    document_parser 在线程池同步执行不能查库，故在此异步解析后注入。
    """
    if strategy.parse_mode != "vlm":
        return strategy

    ref = strategy.vlm_model_ref
    if ref and ref != "system":
        from app.db.repository import provider_model_repo
        from app.services.llm_service import decrypt_api_key
        from app.services.system_model_service import _env_api_key_by_name, _env_key_name

        row = await provider_model_repo.get(session, ref)
        owner_ok = row is not None and (
            row.provider.owner_id is None or row.provider.owner_id == user_id
        )
        if row and row.capability == "multi_modal" and owner_ok:
            api_key = decrypt_api_key(row.provider.api_key) if row.provider.api_key else ""
            if not api_key:
                api_key = _env_api_key_by_name(_env_key_name(row.provider.base_url, row.model))
            strategy.vlm_model = row.model
            strategy.vlm_base_url = row.provider.base_url
            strategy.vlm_api_key = api_key
            return strategy
        logger.warning("解析策略引用的多模态模型 %s 不存在或不可用，回落系统 VLM 角色", ref)

    from app.services.system_model_service import system_model_service

    general = await system_model_service.resolve("general")
    strategy.vlm_model = general["model"]
    strategy.vlm_base_url = general["base_url"]
    strategy.vlm_api_key = general["api_key"]
    return strategy


async def resolve_strategy(session, user_id: str, document=None, override=None) -> ParseStrategyConfig:
    """解析生效的解析策略。

    基底优先级：显式 strategy_id > document.strategy_id > 用户默认策略 > 系统默认；
    内联参数（parse_mode/chunk_size/chunk_overlap/split_method/extract_images）
    在基底策略上覆盖；parse_mode=vlm 时按 vlm_model_ref 注入多模态模型配置。
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
    config = _apply_strategy_override(config, override)
    return await _inject_vlm_config(session, config, user_id)


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
    uploaded_images: list[dict],
) -> None:
    """持久化图片元数据到 PostgreSQL。

    分块内容不再写 PG：Milvus 的 content 字段即原始分块数据，metadata 含
    page/chunk_index/image_ids 等，可按 document_id 标量查询，无需关系库冗余存储。
    自包含 session（AsyncSessionLocal）并显式 commit，调用方无需管理事务。
    重新解析时先清理旧图片记录，避免 image_ref_id（确定性命名）唯一约束冲突。
    """
    async with AsyncSessionLocal() as session:
        await image_repo.delete_by_document(session, document_id)
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
    """parse-sync 的同步索引路径：向量索引 + （开关内）图谱构建。"""
    milvus_ids = await indexer.index_document(document_id, chunks, doc_title=doc_title, kb_id=kb_id)
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

    # 5. 保存图片元数据到 PG（自包含 commit；分块内容只存 Milvus）
    await save_parse_metadata(doc_id, uploaded_images)

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
        original_name = doc.original_name
        mime_type = doc.mime_type

    temp_path = None
    try:
        suffix = resolve_temp_suffix(filename, original_name, mime_type)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            temp_path = tmp.name

        await download_file(oss_url, temp_path)
        result = await asyncio.wait_for(
            do_parse(
                document_id, temp_path, user_id,
                enqueue_index=enqueue_index, strategy_override=strategy_override,
            ),
            timeout=settings.PARSE_TIMEOUT_SECONDS,
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
    except asyncio.TimeoutError:
        async with AsyncSessionLocal() as session:
            doc = await document_repo.get(session, document_id)
            if doc:
                doc.parse_status = "failed"
                doc.parse_error = f"解析超时（>{settings.PARSE_TIMEOUT_SECONDS}s），已中止，请重新解析"
                await session.commit()
        raise
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
