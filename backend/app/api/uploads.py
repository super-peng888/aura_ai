"""File upload and OSS presigned URL endpoints."""

import uuid
import mimetypes
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form

from app.models.schemas import PresignUploadRequest, PresignUploadResponse, BaseResponse
from app.db.models import User, Document
from app.db.base import AsyncSessionLocal
from app.db.repository import document_repo, user_repo
from app.services.storage_service import storage_service
from app.api.auth import get_current_user

router = APIRouter(prefix="/uploads", tags=["Uploads"])


@router.post("/presign", response_model=BaseResponse)
async def get_presigned_url(
    request: PresignUploadRequest,
    current_user: User = Depends(get_current_user),
):
    ext = mimetypes.guess_extension(request.content_type) or ""
    unique_name = f"{uuid.uuid4().hex}{ext}"
    presigned_url = await storage_service.get_presigned_upload_url(unique_name, request.content_type)
    public_url = storage_service.get_url(unique_name)

    return BaseResponse(
        data=PresignUploadResponse(
            presigned_url=presigned_url,
            public_url=public_url,
            filename=unique_name,
        ).model_dump()
    )


@router.post("/document", response_model=BaseResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    auto_parse: bool = Form(False),
    category_id: Optional[str] = Form(None),
    strategy_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
):
    """上传文档到 OSS 并创建数据库记录。可选立即解析。

    strategy_id：可选的解析策略 ID，持久化到文档，解析时优先于用户默认策略。
    auto_parse=True 时解析通过 BackgroundTasks 真后台执行，不阻塞上传响应。
    """
    content = await file.read()
    ext = mimetypes.guess_extension(file.content_type or "application/octet-stream") or ""
    filename = f"{uuid.uuid4().hex}{ext}"

    object_key = await storage_service.upload_file(
        data=content,
        document_id="direct-upload",
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        prefix="documents",
    )
    public_url = storage_service.get_url(object_key)

    async with AsyncSessionLocal() as session:
        doc = Document(
            filename=filename,
            original_name=file.filename or filename,
            file_size=len(content),
            mime_type=file.content_type or "application/octet-stream",
            oss_url=public_url,
            user_id=str(current_user.id),
            category_id=category_id,
            strategy_id=strategy_id or None,
            parse_status="pending",
        )
        await document_repo.create(session, doc)
        await session.commit()

    # 如果请求立即解析，BackgroundTasks 真后台触发（旧版在请求内同步 await 整条流水线）
    if auto_parse:
        from app.services.document_parse_service import trigger_parse_background
        background_tasks.add_task(trigger_parse_background, str(doc.id))

    return BaseResponse(
        data={
            "document_id": str(doc.id),
            "filename": filename,
            "original_name": file.filename,
            "oss_url": public_url,
            "size": len(content),
            "parse_status": doc.parse_status,
        }
    )


@router.post("/avatar", response_model=BaseResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    ext = mimetypes.guess_extension(file.content_type or "image/png") or ".png"
    filename = f"avatar_{current_user.id}_{uuid.uuid4().hex[:8]}{ext}"

    object_key = await storage_service.upload_file(
        data=content,
        document_id="avatars",
        filename=filename,
        content_type=file.content_type or "image/png",
        prefix="avatars",
    )
    public_url = storage_service.get_url(object_key)

    async with AsyncSessionLocal() as session:
        current_user.avatar_url = public_url
        await user_repo.create(session, current_user)

    return BaseResponse(data={"avatar_url": public_url})
