"""系统级解析配置管理 API（VLM 视觉解析模型，仅 admin）。"""

from fastapi import APIRouter, Depends, HTTPException

from app.models.schemas import BaseResponse, ParseConfigUpdate, ParseConfigResponse
from app.db.models import User
from app.api.auth import get_current_user
from app.services.parse_config_service import parse_config_service

router = APIRouter(prefix="/parse-config", tags=["ParseConfig"])


@router.get("/", response_model=BaseResponse)
async def get_parse_config(current_user: User = Depends(get_current_user)):
    """获取生效的解析配置（vlm_api_key 掩码回显，不明文外发）。"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return BaseResponse(data=ParseConfigResponse(**await parse_config_service.get_for_api()).model_dump())


@router.put("/", response_model=BaseResponse)
async def update_parse_config(
    request: ParseConfigUpdate,
    current_user: User = Depends(get_current_user),
):
    """整体 upsert 解析配置；vlm_api_key 留空表示保持不变。保存后运行时生效。"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    saved = await parse_config_service.save(request.model_dump())
    return BaseResponse(data=ParseConfigResponse(**saved).model_dump())
