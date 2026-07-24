"""审计日志服务 — 异步写入，不阻塞主请求。"""

import asyncio
from typing import Optional

from app.db.base import AsyncSessionLocal
from app.db.repository import audit_repo
from app.db.models import AuditLog


class AuditService:
    """审计日志服务。

    提供同步风格的 log_action 接口，内部通过 asyncio.create_task 异步写入数据库，
    避免阻塞 HTTP 响应。
    """

    def log_action(
        self,
        *,
        user_id: Optional[str] = None,
        action: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        """记录审计日志（异步写入，立即返回）。"""
        try:
            asyncio.create_task(
                self._do_log(
                    user_id=user_id,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    details=details or {},
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            )
        except RuntimeError:
            # 没有运行的事件循环（如单元测试环境），直接忽略
            pass

    async def _do_log(
        self,
        user_id: Optional[str],
        action: str,
        resource_type: Optional[str],
        resource_id: Optional[str],
        details: dict,
        ip_address: Optional[str],
        user_agent: Optional[str],
    ) -> None:
        try:
            async with AsyncSessionLocal() as session:
                log = AuditLog(
                    user_id=user_id,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    details=details,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                await audit_repo.create(session, log)
                await session.commit()
        except Exception:
            # 审计日志写入失败不应影响主业务
            pass


audit_service = AuditService()
