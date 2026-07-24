"""异步执行与超时辅助函数（bi 包内部共享）。"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException
from sqlalchemy.engine import Engine


async def _run_with_timeout(coro, timeout: int, operation: str = "操作") -> Any:
    """包装协程，超时后抛出 HTTPException。"""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"{operation}超时（{timeout} 秒），请优化 SQL 或联系管理员")


def _build_sync_runner(engine: Engine, sync_func):
    """为 SQLAlchemy Engine（sync 或 async）构造可等待的执行器。"""
    if hasattr(engine, "run_sync"):
        # 默认 async engine（如 asyncpg）
        return engine.run_sync(sync_func)

    # 外部数据源的 sync engine：在线程池中执行，避免阻塞事件循环
    def _run_in_thread():
        with engine.connect() as conn:
            return sync_func(conn)

    return asyncio.to_thread(_run_in_thread)
