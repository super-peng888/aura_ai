"""审计日志中间件 — 自动记录关键 API 操作。"""

from typing import Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.services.audit_service import audit_service


class AuditMiddleware(BaseHTTPMiddleware):
    """自动记录敏感操作的审计日志。

    规则：
    - POST /documents/parse    → document:create
    - DELETE /documents/*      → document:delete
    - POST /categories         → category:create
    - PUT /categories/*        → category:update
    - DELETE /categories/*     → category:delete
    - POST /chat               → chat:use
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # 只记录成功的请求（2xx）
        if response.status_code < 200 or response.status_code >= 300:
            return response

        action = self._resolve_action(request)
        if not action:
            return response

        user_id = self._get_user_id(request)
        resource_id = self._get_resource_id(request)

        audit_service.log_action(
            user_id=user_id,
            action=action,
            resource_type=action.split(":")[0],
            resource_id=resource_id,
            details={"method": request.method, "path": request.url.path},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )

        return response

    def _resolve_action(self, request: Request) -> Optional[str]:
        path = request.url.path
        method = request.method

        if path.startswith("/api/v1/documents/parse") and method == "POST":
            return "document:create"
        if path.startswith("/api/v1/documents/") and method == "DELETE":
            return "document:delete"
        if path == "/api/v1/categories" and method == "POST":
            return "category:create"
        if path.startswith("/api/v1/categories/") and method == "PUT":
            return "category:update"
        if path.startswith("/api/v1/categories/") and method == "DELETE":
            return "category:delete"
        if path.startswith("/api/v1/chat") and method == "POST":
            return "chat:use"

        return None

    def _get_user_id(self, request: Request) -> Optional[str]:
        """从请求状态中获取当前用户 ID（由 auth dependency 注入）。"""
        return getattr(request.state, "user_id", None)

    def _get_resource_id(self, request: Request) -> Optional[str]:
        """尝试从路径中提取资源 ID。"""
        parts = request.url.path.rstrip("/").split("/")
        if len(parts) >= 2:
            # /api/v1/documents/{id} → 取最后一段
            last = parts[-1]
            if last not in ("parse", "stream", "search"):
                return last
        return None
