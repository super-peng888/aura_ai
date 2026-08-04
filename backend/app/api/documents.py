"""Document parsing and management API endpoints.

解析编排逻辑已下沉至 app.services.document_parse_service，本模块仅保留 HTTP 层：
参数校验、404/500 映射与响应组装。
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query, Depends, Body
from typing import Optional
import asyncio
import os
import tempfile

from app.models.schemas import (
    DocumentUploadRequest,
    DocumentResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    BaseResponse,
    ParseMode,
    BatchDeleteRequest,
    BatchMoveRequest,
    ChunkPreviewRequest,
    ChunkPreviewResponse,
    ChunkItem,
    DocumentParseRequest,
)
from sqlalchemy import func
from app.db.base import AsyncSessionLocal
from app.db.repository import document_repo, document_version_repo, image_repo
from app.db.models import User, DocumentVersion
from app.api.auth import require_permission, get_current_user
from app.services.document_parser import parse_document as parse_document_file
from app.services.document_parser import split_pages_to_chunks
from app.services.document_parse_service import (
    DocumentNotFoundError,
    download_file,
    resolve_strategy,
    resolve_temp_suffix,
    run_parse_pipeline,
    trigger_parse_background,
)
from app.services import indexer
from app.core.knowledge.rag_pipeline import rag_pipeline

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.get("", response_model=BaseResponse)
async def list_documents(
    current_user: User = Depends(require_permission("document:read")),
    category_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """获取文档列表，支持按分类和用户过滤。"""
    from sqlalchemy import select
    from app.db.models import Document

    async with AsyncSessionLocal() as session:
        stmt = select(Document)
        if category_id:
            stmt = stmt.where(Document.category_id == category_id)
        if user_id:
            stmt = stmt.where(Document.user_id == user_id)
        stmt = stmt.order_by(Document.created_at.desc())

        # 分页
        total_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await session.execute(total_stmt)
        total = total_result.scalar_one()

        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await session.execute(stmt)
        docs = result.scalars().all()

        data = [
            DocumentResponse(
                id=str(doc.id),
                filename=doc.filename,
                original_name=doc.original_name,
                file_size=doc.file_size,
                mime_type=doc.mime_type,
                oss_url=doc.oss_url,
                parse_status=doc.parse_status,
                parse_mode=getattr(doc, "parse_mode", "pymupdf"),
                chunk_size=getattr(doc, "chunk_size", 800),
                chunk_overlap=getattr(doc, "chunk_overlap", 100),
                dimension=getattr(doc, "dimension", 1536),
                page_count=doc.page_count,
                category_id=doc.category_id,
                created_at=doc.created_at,
                updated_at=doc.updated_at,
            )
            for doc in docs
        ]

    return BaseResponse(
        data={
            "items": data,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/{document_id}/parse")
async def trigger_document_parse(
    document_id: str,
    background_tasks: BackgroundTasks,
    request: Optional[DocumentParseRequest] = Body(None),
):
    """手动触发文档解析（后台异步执行）。

    可选请求体指定解析策略（strategy_id 或内联参数）；不传时按
    document.strategy_id > 用户默认策略 > 系统默认解析。
    """
    async with AsyncSessionLocal() as session:
        doc = await document_repo.get(session, document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

    # 后台执行解析；parse_status 流转由 document_parse_service 状态机统一负责
    background_tasks.add_task(trigger_parse_background, document_id, request)
    return BaseResponse(data={"message": "Document parsing started", "document_id": document_id})


@router.post("/{document_id}/parse-sync")
async def parse_document_sync(
    document_id: str,
    request: Optional[DocumentParseRequest] = Body(None),
):
    """同步执行文档解析（立即返回结果）。可选请求体同 /parse。"""
    try:
        result = await run_parse_pipeline(document_id, enqueue_index=False, strategy_override=request)
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return BaseResponse(
        data={
            "document_id": document_id,
            "chunk_count": len(result["chunks"]),
            "image_count": result["total_images"],
            "page_count": len(result["pages"]),
        }
    )


@router.get("/{document_id}/status")
async def get_document_status(document_id: str):
    async with AsyncSessionLocal() as session:
        doc = await document_repo.get(session, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return BaseResponse(
        data={
            "document_id": str(doc.id),
            "parse_status": doc.parse_status,
            "parse_error": doc.parse_error,
            "page_count": doc.page_count,
            "parse_mode": doc.parse_mode,
            "chunk_size": doc.chunk_size,
            "chunk_overlap": doc.chunk_overlap,
            "dimension": doc.dimension,
        }
    )


@router.post("/{document_id}/chunks/preview")
async def preview_chunks(document_id: str, request: ChunkPreviewRequest):
    """预览分块结果（不写入数据库/Milvus，仅返回分块数据）。

    策略解析与正式解析一致：显式 strategy_id > document.strategy_id > 用户默认 > 系统默认，
    内联参数在基底策略上覆盖；VLM 模式的模型配置为系统级（settings）。
    """
    async with AsyncSessionLocal() as session:
        doc = await document_repo.get(session, document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        strategy = await resolve_strategy(session, doc.user_id, doc, request)
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

        loop = asyncio.get_running_loop()
        parse_result = await loop.run_in_executor(None, parse_document_file, temp_path, document_id, strategy)
        chunks = split_pages_to_chunks(parse_result.pages, strategy, document_id)

        return BaseResponse(
            data=ChunkPreviewResponse(
                chunks=[
                    ChunkItem(
                        chunk_id=c["chunk_id"],
                        page=c["page"],
                        content=c["content"],
                        image_ids=c.get("image_ids", []),
                        heading=c.get("heading", ""),
                        chunk_type=c.get("chunk_type", "text"),
                    )
                    for c in chunks
                ],
                page_count=len(parse_result.pages),
                total_images=len(parse_result.raw_images),
                mode_used=parse_result.mode_used,
            ).model_dump()
        )
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


@router.get("/{document_id}/images")
async def list_document_images(document_id: str):
    """获取文档提取的图片列表（image_ref_id -> oss_url，供前端分块回显）。"""
    async with AsyncSessionLocal() as session:
        doc = await document_repo.get(session, document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        images = await image_repo.get_by_document(session, document_id)

    return BaseResponse(
        data=[
            {
                "id": str(img.id),
                "image_ref_id": img.image_ref_id,
                "oss_url": img.oss_url,
                "page_number": img.page_number,
                "width": img.width,
                "height": img.height,
            }
            for img in images
        ]
    )


@router.post("/search", response_model=SearchResponse)
async def search_documents(request: SearchRequest, current_user: User = Depends(get_current_user)):
    result = await rag_pipeline.search(
        query=request.query,
        document_ids=request.document_ids or None,
        knowledge_base_ids=request.knowledge_base_ids or None,
        top_k=request.top_k,
        filters=request.filters,
    )

    return SearchResponse(
        query=result["query"],
        rewritten_query=result.get("rewritten_query"),
        results=[
            SearchResultItem(
                chunk_id=r["chunk_id"],
                document_id=r["document_id"],
                content=r["content"],
                page_number=r.get("page_number"),
                score=r.get("score", 0),
                search_type=r.get("search_type", "unknown"),
                image_ids=r.get("image_ids", []),
            )
            for r in result["results"]
        ],
    )


@router.delete("/{document_id}")
async def delete_document(document_id: str, current_user: User = Depends(require_permission("document:delete"))):
    await indexer.delete_document(document_id)
    async with AsyncSessionLocal() as session:
        doc = await document_repo.get(session, document_id)
        if doc:
            await document_repo.delete(session, doc)
            await session.commit()
    return BaseResponse(data={"message": "Document deleted"})


@router.post("/batch-delete", response_model=BaseResponse)
async def batch_delete_documents(
    request: BatchDeleteRequest,
    current_user: User = Depends(require_permission("document:delete")),
):
    """批量删除文档。"""
    deleted = 0
    async with AsyncSessionLocal() as session:
        for doc_id in request.document_ids:
            await indexer.delete_document(doc_id)
            doc = await document_repo.get(session, doc_id)
            if doc:
                await document_repo.delete(session, doc)
                deleted += 1
        await session.commit()
    return BaseResponse(data={"deleted": deleted})


@router.get("/{document_id}/versions", response_model=BaseResponse)
async def list_document_versions(document_id: str):
    """获取文档的版本历史。"""
    async with AsyncSessionLocal() as session:
        doc = await document_repo.get(session, document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        versions = await document_version_repo.get_by_document(session, document_id)
    return BaseResponse(
        data=[
            {
                "id": str(v.id),
                "document_id": str(v.document_id),
                "version": v.version,
                "oss_url": v.oss_url,
                "file_size": v.file_size,
                "created_at": v.created_at,
            }
            for v in versions
        ]
    )


@router.post("/{document_id}/rollback", response_model=BaseResponse)
async def rollback_document(
    document_id: str,
    version_id: str,
    current_user: User = Depends(require_permission("document:write")),
):
    """回滚文档到指定版本。"""
    async with AsyncSessionLocal() as session:
        doc = await document_repo.get(session, document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        version = await document_version_repo.get(session, version_id)
        if not version or str(version.document_id) != document_id:
            raise HTTPException(status_code=404, detail="Version not found")

        # 创建当前版本快照
        next_version = await document_version_repo.get_next_version(session, document_id)
        await document_version_repo.create(session, DocumentVersion(
            document_id=document_id,
            version=next_version,
            oss_url=doc.oss_url,
            file_size=doc.file_size,
        ))

        # 回滚
        doc.oss_url = version.oss_url
        doc.file_size = version.file_size
        await session.commit()

    return BaseResponse(data={"message": "Document rolled back"})


@router.post("/batch-move", response_model=BaseResponse)
async def batch_move_documents(
    request: BatchMoveRequest,
    current_user: User = Depends(require_permission("document:write")),
):
    """批量移动文档到指定分类。"""
    moved = 0
    async with AsyncSessionLocal() as session:
        for doc_id in request.document_ids:
            doc = await document_repo.get(session, doc_id)
            if doc:
                doc.category_id = request.category_id
                moved += 1
        await session.commit()
    return BaseResponse(data={"moved": moved})
