"""统一 BI 服务入口（门面）与全局单例。"""

from __future__ import annotations

from typing import Any, List, Optional

from sqlalchemy import text

from app.config import get_settings
from app.db.base import AsyncSessionLocal
from app.db.repository import data_source_repo
from app.services.bi.connections import _decrypt_connection_config
from app.services.bi.connector import DataSourceConnector
from app.services.bi.executor import QueryExecutor
from app.services.bi.schema import SchemaManager
from app.services.bi.validator import SQLSecurityValidator

settings = get_settings()


class BIService:
    """Data Agent 统一服务入口。"""

    validator = SQLSecurityValidator
    schema_manager = SchemaManager
    query_executor = QueryExecutor
    connector = DataSourceConnector

    async def get_schema(self, data_source: Optional[Any] = None) -> dict:
        """获取数据库 Schema（自动 introspection + 人工元数据合并，带缓存）。"""
        engine = self.connector.get_engine(data_source)
        source_id = str(data_source.id) if data_source else None
        metadata = (data_source.schema_metadata or {}) if data_source else {}
        return await self.schema_manager.get_schema(engine, source_id, metadata)

    async def execute_query(
        self,
        sql: str,
        *,
        user_id: Optional[str] = None,
        data_source: Optional[Any] = None,
        natural_language_query: Optional[str] = None,
    ) -> dict:
        """执行安全的只读查询。"""
        engine = self.connector.get_engine(data_source)

        # 按数据源配置超时，并设置全局上限
        timeout = settings.BI_QUERY_TIMEOUT_SECONDS
        if data_source and data_source.connection_config:
            cfg = _decrypt_connection_config(data_source.connection_config)
            source_timeout = cfg.get("query_timeout_seconds")
            if source_timeout is not None:
                timeout = int(source_timeout)
        timeout = max(1, min(timeout, settings.BI_MAX_QUERY_TIMEOUT_SECONDS))

        return await self.query_executor.execute(
            sql,
            engine=engine,
            user_id=user_id,
            data_source_id=str(data_source.id) if data_source else None,
            natural_language_query=natural_language_query,
            timeout=timeout,
        )

    async def get_data_source(self, data_source_id: Optional[str]) -> Optional[Any]:
        """根据 ID 加载数据源配置。"""
        if not data_source_id:
            return None
        async with AsyncSessionLocal() as session:
            return await data_source_repo.get(session, data_source_id)

    async def test_connection(self, data_source: Any) -> dict:
        """测试数据源连通性。"""
        engine = self.connector.get_engine(data_source)

        def _test(sync_conn):
            result = sync_conn.execute(text("SELECT 1"))
            return result.scalar() == 1

        try:
            if hasattr(engine, "run_sync"):
                ok = await engine.run_sync(_test)
            else:
                with engine.connect() as conn:
                    ok = _test(conn)
            return {"success": bool(ok)}
        except Exception as e:
            return {"success": False, "error": str(e)[:500]}

    def format_schema_for_llm(
        self,
        schema: dict,
        allowed_tables: Optional[List[str]] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """将 Schema 格式化为 LLM 提示文本。"""
        return self.schema_manager.format_for_llm(schema, allowed_tables, metadata)


# 全局单例
bi_service = BIService()
