"""查询执行器：只读查询执行、结果缓存、性能审计。"""

from __future__ import annotations

import hashlib
import time
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import get_settings
from app.db.base import engine as default_engine, AsyncSessionLocal
from app.db.repository import bi_query_log_repo
from app.db.models import BIQueryLog
from app.utils.cache import cache_get, cache_set
from app.services.bi._helpers import _build_sync_runner, _run_with_timeout
from app.services.bi.validator import SQLSecurityValidator

settings = get_settings()


class QueryExecutor:
    """只读查询执行器，带缓存和审计。"""

    CACHE_PREFIX = "bi:query:"
    CACHE_TTL = settings.BI_QUERY_CACHE_TTL

    @classmethod
    async def execute(
        cls,
        sql: str,
        *,
        engine: Engine = None,
        user_id: Optional[str] = None,
        data_source_id: Optional[str] = None,
        natural_language_query: Optional[str] = None,
        max_rows: int = None,
        timeout: int = None,
    ) -> dict:
        """执行安全的只读查询，返回标准化结果。

        流程：
        1. 安全校验（AST 白名单）
        2. 注入 LIMIT 保护
        3. 检查缓存
        4. 执行查询（带超时）
        5. 记录审计日志
        6. 写入缓存
        """
        max_rows = max_rows or settings.BI_MAX_RESULT_ROWS
        timeout = timeout or settings.BI_QUERY_TIMEOUT_SECONDS

        # 1. 安全校验
        safe_sql = SQLSecurityValidator.validate(sql)
        safe_sql = SQLSecurityValidator.inject_limit(safe_sql, max_rows)

        # 2. 缓存检查
        cache_key = cls._build_cache_key(safe_sql, data_source_id)
        cached = await cache_get(cache_key, prefix=cls.CACHE_PREFIX)
        if cached:
            cached["cached"] = True
            return cached

        # 3. 执行查询
        start_time = time.time()
        try:
            result = await cls._execute_with_timeout(
                safe_sql, engine=engine or default_engine, timeout=timeout
            )
            execution_time_ms = int((time.time() - start_time) * 1000)
            result["execution_time_ms"] = execution_time_ms
            result["cached"] = False

            # 4. 记录审计日志（异步，不阻塞返回）
            await cls._log_query(
                user_id=user_id,
                data_source_id=data_source_id,
                natural_language_query=natural_language_query,
                generated_sql=safe_sql,
                row_count=result.get("row_count", 0),
                execution_time_ms=execution_time_ms,
                status="success",
            )

            # 5. 写入缓存
            await cache_set(cache_key, result, ttl=cls.CACHE_TTL, prefix=cls.CACHE_PREFIX)

            return result

        except HTTPException:
            raise
        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            await cls._log_query(
                user_id=user_id,
                data_source_id=data_source_id,
                natural_language_query=natural_language_query,
                generated_sql=safe_sql,
                execution_time_ms=execution_time_ms,
                status="error",
                error_message=str(e)[:500],
            )
            raise HTTPException(status_code=400, detail=f"查询执行失败: {str(e)}")

    @classmethod
    async def _execute_with_timeout(cls, sql: str, engine: Engine, timeout: int) -> dict:
        """在异步线程中执行 SQL，带数据库层超时与 Python 层兜底超时。"""
        def _sync_query(sync_conn):
            # 根据数据库类型设置会话/语句级超时，并强制只读事务
            dialect = sync_conn.dialect.name if hasattr(sync_conn, "dialect") else "unknown"
            if dialect == "postgresql":
                sync_conn.execute(text(f"SET statement_timeout = {timeout * 1000}"))
                sync_conn.execute(text("SET TRANSACTION READ ONLY"))
            elif dialect == "mysql":
                sync_conn.execute(text(f"SET SESSION max_execution_time = {timeout * 1000}"))
            elif dialect == "mariadb":
                sync_conn.execute(text(f"SET SESSION max_statement_time = {timeout}"))

            result = sync_conn.execute(text(sql))
            columns = list(result.keys())
            rows = []
            for row in result.fetchall():
                rows.append([str(cell) if cell is not None else "" for cell in row])

            return {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
            }

        runner = _build_sync_runner(engine, _sync_query)
        # Python 层兜底超时：给数据库层超时留出 5 秒缓冲
        return await _run_with_timeout(
            runner,
            timeout=timeout + 5,
            operation="查询执行",
        )

    @classmethod
    def _build_cache_key(cls, sql: str, data_source_id: Optional[str]) -> str:
        """基于 SQL 和数据源构建缓存键。"""
        key_str = f"{data_source_id or 'default'}:{sql}"
        return hashlib.md5(key_str.encode()).hexdigest()

    @classmethod
    async def _log_query(
        cls,
        user_id: Optional[str],
        data_source_id: Optional[str],
        natural_language_query: Optional[str],
        generated_sql: str,
        row_count: int = 0,
        execution_time_ms: int = 0,
        status: str = "success",
        error_message: Optional[str] = None,
    ) -> None:
        """记录查询审计日志。"""
        try:
            async with AsyncSessionLocal() as session:
                await bi_query_log_repo.create(session, BIQueryLog(
                    user_id=user_id,
                    data_source_id=data_source_id,
                    natural_language_query=natural_language_query,
                    generated_sql=generated_sql[:2000],
                    row_count=row_count,
                    execution_time_ms=execution_time_ms,
                    status=status,
                    error_message=error_message,
                ))
                await session.commit()
        except Exception as e:
            # 审计日志失败不应影响主流程
            print(f"[BI Audit] Failed to log query: {e}")
