"""Schema 管理器：数据库 Schema 自省、元数据合并与缓存管理。"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.config import get_settings
from app.db.base import engine as default_engine
from app.utils.cache import cache_get_or_set, cache_delete
from app.services.bi._helpers import _build_sync_runner, _run_with_timeout

settings = get_settings()


class SchemaManager:
    """数据库 Schema 自省、元数据合并与缓存管理。"""

    CACHE_PREFIX = "bi:schema:"
    CACHE_TTL = settings.BI_SCHEMA_CACHE_TTL

    @classmethod
    async def get_schema(
        cls,
        engine: Engine = None,
        data_source_id: str = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """获取数据库表结构（自动 introspection + 人工元数据合并，带 Redis 缓存）。"""
        cache_key = f"{cls.CACHE_PREFIX}{data_source_id or 'default'}"

        async def _fetch():
            introspected = await cls._inspect_schema(engine or default_engine)
            return cls._merge_metadata(introspected, metadata or {})

        return await cache_get_or_set(cache_key, _fetch, ttl=cls.CACHE_TTL)

    @classmethod
    async def _inspect_schema(cls, engine: Engine) -> dict:
        """同步执行 Schema 自省（在异步线程中运行，带超时）。"""
        def _sync_inspect(sync_conn):
            inspector = inspect(sync_conn)
            schema = {}
            for table_name in inspector.get_table_names():
                try:
                    columns = inspector.get_columns(table_name)
                    schema[table_name] = {
                        "name": table_name,
                        "alias": None,
                        "description": None,
                        "hidden": False,
                        "columns": [
                            {
                                "name": c["name"],
                                "type": str(c["type"]),
                                "alias": None,
                                "description": None,
                                "enums": None,
                                "hidden": False,
                            }
                            for c in columns
                        ],
                    }
                except Exception:
                    # 某些系统表可能无法获取列信息，跳过
                    continue
            return schema

        runner = _build_sync_runner(engine, _sync_inspect)
        return await _run_with_timeout(
            runner,
            timeout=settings.BI_QUERY_TIMEOUT_SECONDS,
            operation="Schema 自省",
        )

    @classmethod
    def _merge_metadata(cls, schema: dict, metadata: dict) -> dict:
        """将人工编辑的 schema_metadata 合并到自动 introspection 结果中。"""
        if not metadata:
            return schema

        tables_meta = metadata.get("tables", {})
        for table_name, table_info in schema.items():
            meta = tables_meta.get(table_name, {})
            if meta.get("alias"):
                table_info["alias"] = meta["alias"]
            if meta.get("description"):
                table_info["description"] = meta["description"]
            if meta.get("hidden"):
                table_info["hidden"] = True

            columns_meta = meta.get("columns", {})
            for col in table_info.get("columns", []):
                col_meta = columns_meta.get(col["name"], {})
                if col_meta.get("alias"):
                    col["alias"] = col_meta["alias"]
                if col_meta.get("description"):
                    col["description"] = col_meta["description"]
                if col_meta.get("enums"):
                    col["enums"] = col_meta["enums"]
                if col_meta.get("hidden"):
                    col["hidden"] = True

        return schema

    @classmethod
    async def invalidate_cache(cls, data_source_id: str = None) -> None:
        """使 Schema 缓存失效。"""
        cache_key = f"{cls.CACHE_PREFIX}{data_source_id or 'default'}"
        await cache_delete(cache_key)

    @classmethod
    def format_for_llm(
        cls,
        schema: dict,
        allowed_tables: Optional[List[str]] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """将 Schema 格式化为 LLM 可读的文本（含别名、注释、枚举、关系、指标）。"""
        metadata = metadata or {}
        relationships = metadata.get("relationships", [])
        metrics = metadata.get("metrics", [])

        lines = ["## 数据库表结构", ""]
        visible_tables = set()

        for table_name, table_info in schema.items():
            if allowed_tables and table_name not in allowed_tables:
                continue
            if table_info.get("hidden"):
                continue

            visible_tables.add(table_name)
            display_name = table_info.get("alias") or table_name
            alias_part = f"（{display_name}）" if display_name != table_name else ""
            lines.append(f"### {table_name}{alias_part}")

            if table_info.get("description"):
                lines.append(f"  说明：{table_info['description']}")

            for col in table_info.get("columns", []):
                if col.get("hidden"):
                    continue
                col_display = col.get("alias") or col["name"]
                col_line = f"  - {col['name']}: {col['type']}"
                if col_display != col["name"]:
                    col_line += f"（{col_display}）"
                if col.get("description"):
                    col_line += f" // {col['description']}"
                if col.get("enums"):
                    col_line += f" 枚举：{col['enums']}"
                lines.append(col_line)
            lines.append("")

        # 关系说明
        if relationships:
            visible_relationships = [
                r for r in relationships
                if r.get("from_table") in visible_tables and r.get("to_table") in visible_tables
            ]
            if visible_relationships:
                lines.append("## 表关系")
                for r in visible_relationships:
                    name = r.get("name") or f"{r['from_table']}.{r['from_column']} -> {r['to_table']}.{r['to_column']}"
                    lines.append(
                        f"- {name}: {r['from_table']}.{r['from_column']} "
                        f"{r.get('type', 'many_to_one')} "
                        f"{r['to_table']}.{r['to_column']}"
                    )
                lines.append("")

        # 业务指标说明
        if metrics:
            visible_metrics = [
                m for m in metrics
                if not m.get("dimensions") or all(d.split('.')[0] in visible_tables for d in m.get("dimensions", []))
            ]
            if visible_metrics:
                lines.append("## 业务指标")
                for m in visible_metrics:
                    name = m.get("alias") or m.get("name")
                    expr = m.get("expression", "")
                    agg = f" 聚合：{m['aggregation']}" if m.get("aggregation") else ""
                    dims = f" 维度：{m['dimensions']}" if m.get("dimensions") else ""
                    desc = f" // {m['description']}" if m.get("description") else ""
                    lines.append(f"- {name}：{expr}{agg}{dims}{desc}")
                lines.append("")

        return "\n".join(lines)
