"""Audit log query API endpoints (admin only)."""

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.schemas import BaseResponse, AuditLogResponse
from app.db.base import AsyncSessionLocal
from app.db.repository import audit_repo
from app.db.models import AuditLog, User
from app.api.auth import get_current_user, require_permission

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


@router.get("", response_model=BaseResponse)
async def list_audit_logs(
    user_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_permission("admin:all")),
):
    """查询审计日志（仅管理员）。"""
    async with AsyncSessionLocal() as session:
        offset = (page - 1) * page_size
        logs = await audit_repo.query(
            session,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            start_date=start_date,
            end_date=end_date,
            limit=page_size,
            offset=offset,
        )
        total = await audit_repo.count_with_filters(
            session,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            start_date=start_date,
            end_date=end_date,
        )

        data = [
            AuditLogResponse(
                id=str(log.id),
                user_id=log.user_id,
                action=log.action,
                resource_type=log.resource_type,
                resource_id=log.resource_id,
                details=log.details or {},
                ip_address=log.ip_address,
                user_agent=log.user_agent,
                created_at=log.created_at,
            ).model_dump()
            for log in logs
        ]

    return BaseResponse(
        data={
            "items": data,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )
