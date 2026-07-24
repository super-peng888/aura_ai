"""Dashboard statistics API endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from datetime import datetime, timedelta, timezone

from app.models.schemas import BaseResponse, DashboardTrendsResponse
from app.db.base import AsyncSessionLocal
from app.db.repository import document_repo, user_repo, conversation_repo
from app.db.models import Document, Conversation, User
from app.api.auth import get_current_user
from app.utils.cache import cache_get_or_set

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


async def _fetch_stats() -> dict:
    """从数据库获取仪表盘统计数据。"""
    async with AsyncSessionLocal() as session:
        total_docs = await document_repo.count(session)
        total_users = await user_repo.count(session)
        total_conversations = await conversation_repo.count(session)
        completed_docs = len(await document_repo.get_by_status(session, "completed"))
        pending_docs = len(await document_repo.get_by_status(session, "pending"))

    return {
        "total_documents": total_docs,
        "total_users": total_users,
        "total_conversations": total_conversations,
        "completed_documents": completed_docs,
        "pending_documents": pending_docs,
    }


async def _fetch_trend_data(period: str = "daily") -> dict:
    """获取趋势统计数据（最近 7 天/周）。"""
    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)

        if period == "weekly":
            # 最近 7 周
            labels = []
            for i in range(6, -1, -1):
                week_start = now - timedelta(weeks=i)
                labels.append(f"W{week_start.isocalendar()[1]}")

            # 每周文档数
            doc_stmt = text("""
                SELECT DATE_TRUNC('week', created_at) as period, COUNT(*) as cnt
                FROM documents
                WHERE created_at >= NOW() - INTERVAL '7 weeks'
                GROUP BY period
                ORDER BY period
            """)
            # 每周会话数
            conv_stmt = text("""
                SELECT DATE_TRUNC('week', created_at) as period, COUNT(*) as cnt
                FROM conversations
                WHERE created_at >= NOW() - INTERVAL '7 weeks'
                GROUP BY period
                ORDER BY period
            """)
            # 每周活跃用户数
            user_stmt = text("""
                SELECT DATE_TRUNC('week', created_at) as period, COUNT(DISTINCT user_id) as cnt
                FROM conversations
                WHERE created_at >= NOW() - INTERVAL '7 weeks'
                GROUP BY period
                ORDER BY period
            """)
        else:
            # 最近 7 天
            labels = []
            for i in range(6, -1, -1):
                day = now - timedelta(days=i)
                labels.append(day.strftime("%m-%d"))

            doc_stmt = text("""
                SELECT DATE(created_at) as period, COUNT(*) as cnt
                FROM documents
                WHERE created_at >= NOW() - INTERVAL '7 days'
                GROUP BY period
                ORDER BY period
            """)
            conv_stmt = text("""
                SELECT DATE(created_at) as period, COUNT(*) as cnt
                FROM conversations
                WHERE created_at >= NOW() - INTERVAL '7 days'
                GROUP BY period
                ORDER BY period
            """)
            user_stmt = text("""
                SELECT DATE(created_at) as period, COUNT(DISTINCT user_id) as cnt
                FROM conversations
                WHERE created_at >= NOW() - INTERVAL '7 days'
                GROUP BY period
                ORDER BY period
            """)

        doc_result = await session.execute(doc_stmt)
        conv_result = await session.execute(conv_stmt)
        user_result = await session.execute(user_stmt)

        doc_rows = {str(r[0]): r[1] for r in doc_result.fetchall()}
        conv_rows = {str(r[0]): r[1] for r in conv_result.fetchall()}
        user_rows = {str(r[0]): r[1] for r in user_result.fetchall()}

        document_counts = []
        conversation_counts = []
        active_user_counts = []

        for i in range(7):
            if period == "weekly":
                date_key = (now - timedelta(weeks=(6 - i))).replace(hour=0, minute=0, second=0, microsecond=0)
                # PostgreSQL DATE_TRUNC 返回的格式
                date_str = str(date_key.date())
            else:
                date_key = (now - timedelta(days=(6 - i))).date()
                date_str = str(date_key)

            document_counts.append(doc_rows.get(date_str, 0))
            conversation_counts.append(conv_rows.get(date_str, 0))
            active_user_counts.append(user_rows.get(date_str, 0))

    return {
        "period": period,
        "labels": labels,
        "document_counts": document_counts,
        "conversation_counts": conversation_counts,
        "active_user_counts": active_user_counts,
    }


@router.get("/stats", response_model=BaseResponse)
async def get_dashboard_stats(current_user: User = Depends(get_current_user)):
    """获取仪表盘统计数据（Redis 缓存 30 秒）。"""
    stats = await cache_get_or_set("dashboard:stats", _fetch_stats, ttl=30)
    return BaseResponse(data=stats)


@router.get("/trends", response_model=BaseResponse)
async def get_dashboard_trends(
    period: str = "daily",
    current_user: User = Depends(get_current_user),
):
    """获取仪表盘趋势数据（最近 7 天/周）。"""
    if period not in ("daily", "weekly"):
        period = "daily"
    trends = await cache_get_or_set(
        f"dashboard:trends:{period}",
        lambda: _fetch_trend_data(period),
        ttl=60,
    )
    return BaseResponse(data=trends)
