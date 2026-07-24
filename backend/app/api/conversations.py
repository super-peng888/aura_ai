"""Conversation management API endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from pydantic import BaseModel
from app.models.schemas import BaseResponse
from app.db.base import AsyncSessionLocal
from app.db.repository import conversation_repo, message_repo
from app.db.models import User, Conversation, Message
from app.api.auth import require_permission

router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.get("", response_model=BaseResponse)
async def list_conversations(
    current_user: User = Depends(require_permission("chat:use")),
    limit: int = Query(100, ge=1, le=200),
):
    """获取当前用户的会话列表。"""
    async with AsyncSessionLocal() as session:
        conversations = await conversation_repo.list_by_user(session, str(current_user.id), limit=limit)
    return BaseResponse(
        data=[
            {
                "id": str(c.id),
                "title": c.title,
                "model_id": c.model_id,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
            }
            for c in conversations
        ]
    )


@router.post("", response_model=BaseResponse)
async def create_conversation(
    title: Optional[str] = None,
    current_user: User = Depends(require_permission("chat:use")),
):
    """创建新会话。"""
    async with AsyncSessionLocal() as session:
        conv = Conversation(
            user_id=str(current_user.id),
            title=title or "新对话",
        )
        conv = await conversation_repo.create(session, conv)
        await session.commit()
    return BaseResponse(
        data={
            "id": str(conv.id),
            "title": conv.title,
            "created_at": conv.created_at,
        }
    )


class ConversationTitleUpdate(BaseModel):
    title: str


@router.put("/{conversation_id}", response_model=BaseResponse)
async def update_conversation(
    conversation_id: str,
    request: ConversationTitleUpdate,
    current_user: User = Depends(require_permission("chat:use")),
):
    """更新会话标题。"""
    async with AsyncSessionLocal() as session:
        conv = await conversation_repo.get(session, conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if str(conv.user_id) != str(current_user.id) and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Not your conversation")

        conv.title = request.title
        await session.commit()

    return BaseResponse(data={"id": str(conv.id), "title": conv.title})


@router.get("/{conversation_id}/messages", response_model=BaseResponse)
async def get_conversation_messages(
    conversation_id: str,
    current_user: User = Depends(require_permission("chat:use")),
):
    """获取会话的消息列表。"""
    async with AsyncSessionLocal() as session:
        conv = await conversation_repo.get(session, conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if str(conv.user_id) != str(current_user.id) and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Not your conversation")

        messages = await message_repo.list_by_conversation(session, conversation_id, limit=100)

    return BaseResponse(
        data=[
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at,
            }
            for m in messages
        ]
    )


@router.delete("/{conversation_id}", response_model=BaseResponse)
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(require_permission("chat:use")),
):
    """删除会话。"""
    async with AsyncSessionLocal() as session:
        conv = await conversation_repo.get(session, conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if str(conv.user_id) != str(current_user.id) and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Not your conversation")

        await conversation_repo.delete(session, conv)
        await session.commit()

    return BaseResponse(data={"message": "Conversation deleted"})
