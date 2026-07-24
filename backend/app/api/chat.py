"""Chat API endpoints — 支持用户级模型配置。

变更说明：
- 从 current_user.llm_config 读取用户的模型配置
- 通过 _chat_generator 将 user_config 透传给 agent_service
- 如果用户未配置 API Key，自动回退到系统默认配置
"""

import json
from typing import AsyncIterator, Optional
from fastapi import APIRouter, HTTPException, Depends
from sse_starlette.sse import EventSourceResponse

from app.models.schemas import ChatRequest, BaseResponse, ChatResponse
from app.core.agent import agent_service
from app.db.base import AsyncSessionLocal
from app.db.repository import message_repo
from app.db.models import User, Message
from app.api.auth import get_current_user, require_permission
router = APIRouter(prefix="/chat", tags=["Chat"])


def _extract_user_provider(current_user: User) -> Optional[str]:
    """
    提取用户当前绑定的模型 provider。
    返回 None 表示让后端自动通过 user_id 查数据库解析。
    """
    return current_user.default_model_id or None


def _check_quota(current_user: User) -> None:
    """检查用户当月 token 配额是否耗尽。"""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    reset_at = current_user.token_reset_at

    # 如果跨月，自动重置
    if reset_at is None or (reset_at.year != now.year or reset_at.month != now.month):
        current_user.token_used_monthly = 0
        current_user.token_reset_at = now
        return

    if current_user.token_used_monthly >= current_user.token_quota_monthly:
        raise HTTPException(
            status_code=429,
            detail=f"本月 Token 配额已用尽（{current_user.token_used_monthly}/{current_user.token_quota_monthly}），请联系管理员升级配额。",
        )


async def _chat_generator(request: ChatRequest, current_user: User) -> AsyncIterator[dict]:
    """统一的 chat 生成器，同时处理流式与非流式场景。"""
    _check_quota(current_user)

    messages = []
    if request.conversation_id:
        async with AsyncSessionLocal() as session:
            db_messages = await message_repo.list_by_conversation(session, request.conversation_id, limit=20)
        for msg in db_messages:
            messages.append({"role": msg.role, "content": msg.content})

    user_msg = request.messages[-1].content if request.messages else ""
    messages.append({"role": "user", "content": user_msg})

    full_response = ""
    citations = []
    images = []
    content_blocks = []

    async for chunk in agent_service.chat(
        query=user_msg,
        user_id=str(current_user.id),
        conversation_history=messages[:-1],
        conversation_id=request.conversation_id,
        knowledge_base_ids=request.knowledge_base_ids,
        temperature=request.temperature,
        attachments=[att.model_dump() for att in request.attachments],
    ):
        if chunk["type"] == "text":
            full_response += chunk["data"]
        elif chunk["type"] == "analysis":
            # Data Agent 分析文字
            full_response = chunk["data"]
        elif chunk["type"] == "citations":
            citations = chunk["data"]
        elif chunk["type"] == "images":
            images = chunk["data"]
        elif chunk["type"] == "content_blocks":
            content_blocks = chunk["data"]

        yield chunk

    # 保存助手消息到数据库
    if request.conversation_id:
        try:
            async with AsyncSessionLocal() as session:
                await message_repo.create(session, Message(
                    conversation_id=request.conversation_id,
                    role="assistant",
                    content=full_response,
                    citation_ids=[c["chunk_id"] for c in citations],
                    image_ids=[img["image_id"] for img in images],
                    model_id=request.model_id or "gpt-4o",
                ))
                # 估算并累加 token 使用量（粗略：每 4 字符 ≈ 1 token）
                total_chars = len(user_msg) + len(full_response)
                estimated_tokens = max(1, total_chars // 4)
                current_user.token_used_monthly += estimated_tokens
                await session.commit()
        except Exception as e:
            print(f"[chat] Failed to save message: {e}")


@router.post("/", response_model=BaseResponse)
async def chat(request: ChatRequest, current_user: User = Depends(require_permission("chat:use"))):
    """非流式对话接口。"""
    full_response = ""
    citations = []
    images = []
    content_blocks = []

    async for chunk in _chat_generator(request, current_user):
        if chunk["type"] == "text":
            full_response += chunk["data"]
        elif chunk["type"] == "citations":
            citations = chunk["data"]
        elif chunk["type"] == "images":
            images = chunk["data"]
        elif chunk["type"] == "content_blocks":
            content_blocks = chunk["data"]

    return BaseResponse(
        data=ChatResponse(
            answer=full_response,
            query_type="knowledge",
            content_blocks=content_blocks,
            images=images,
            sources=citations,
        ).model_dump()
    )


@router.post("/stream")
async def chat_stream(request: ChatRequest, current_user: User = Depends(require_permission("chat:use"))):
    """流式对话接口（SSE）。

    支持的事件类型：
    - text: 普通文本片段（rag/direct）
    - citations: 引用来源列表
    - images: 关联图片列表
    - content_blocks: 图文内容块
    - sql: Data Agent 生成的 SQL
    - query_result: 查询结果 {columns, rows, row_count}
    - analysis: Data Agent 分析文字
    - chart: ECharts 图表配置 {title, type, option}
    - table: 表格配置 {title, headers, rows}
    - error: 错误信息
    - done: 结束标记
    """
    async def event_generator() -> AsyncIterator[dict]:
        async for chunk in _chat_generator(request, current_user):
            data = chunk["data"]
            # 统一将非字符串数据序列化为 JSON，确保 SSE 传输一致性
            if data is not None and not isinstance(data, str):
                data = json.dumps(data, ensure_ascii=False, default=str)
            yield {
                "event": chunk["type"],
                "data": data,
            }

    return EventSourceResponse(event_generator())


# =============================================================================
# 对话分享
# =============================================================================

import uuid

@router.post("/conversations/{conversation_id}/share", response_model=BaseResponse)
async def share_conversation(
    conversation_id: str,
    current_user: User = Depends(require_permission("chat:use")),
):
    """生成对话分享链接。"""
    async with AsyncSessionLocal() as session:
        conv = await conversation_repo.get(session, conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if str(conv.user_id) != str(current_user.id) and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Not your conversation")

        conv.is_shared = True
        conv.share_token = str(uuid.uuid4())
        await session.commit()

    return BaseResponse(data={"share_token": conv.share_token})


@router.get("/share/{token}", response_model=BaseResponse)
async def get_shared_conversation(token: str):
    """免登录访问共享对话。"""
    async with AsyncSessionLocal() as session:
        conv = await conversation_repo.get_by_share_token(session, token)
        if not conv:
            raise HTTPException(status_code=404, detail="Shared conversation not found or not shared")

        messages = await message_repo.list_by_conversation(session, str(conv.id), limit=100)

    return BaseResponse(
        data={
            "conversation": {
                "id": str(conv.id),
                "title": conv.title,
                "model_id": conv.model_id,
                "created_at": conv.created_at,
            },
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "created_at": msg.created_at,
                }
                for msg in messages
            ],
        }
    )
