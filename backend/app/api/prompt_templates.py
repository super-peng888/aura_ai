"""Prompt template API endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from app.models.schemas import BaseResponse
from app.db.base import AsyncSessionLocal
from app.db.repository import prompt_template_repo
from app.utils.cache import cache_get_or_set

router = APIRouter(prefix="/prompt-templates", tags=["Prompt Templates"])


async def _fetch_templates() -> list:
    """从数据库获取所有模板。"""
    async with AsyncSessionLocal() as session:
        templates = await prompt_template_repo.list(session, limit=200)

    return [
        {
            "id": str(t.id),
            "name": t.name,
            "content": t.content,
            "category": t.category,
            "is_system": t.is_system,
            "created_at": t.created_at,
        }
        for t in templates
    ]


@router.get("", response_model=BaseResponse)
async def list_templates():
    """获取所有对话模板（Redis 缓存 60 秒）。"""
    data = await cache_get_or_set("prompt_templates:list", _fetch_templates, ttl=60)
    return BaseResponse(data=data)
