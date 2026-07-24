"""数据权限应用器：根据 DataPermission 对 Schema 和 SQL 进行权限控制。"""

from __future__ import annotations

from typing import List, Optional

import sqlparse
from fastapi import HTTPException
from sqlparse.tokens import Comment, Name

from app.db.base import AsyncSessionLocal
from app.db.repository import data_permission_repo
from app.db.models import DataPermission


def _extract_tables(sql: str) -> List[str]:
    """从 SQL 中提取表名（支持 FROM / JOIN，跳过空白与注释，忽略别名）。

    注意：FROM 与表名之间通常有空白 token，捕获时必须跳过而非重置，
    否则常规 `FROM <table>` 会提取为空、表白名单校验形同虚设。
    """
    tables: set = set()
    for statement in sqlparse.parse(sql):
        capture_next = False
        for token in statement.tokens:
            if token.is_whitespace or (token.ttype and token.ttype in Comment):
                continue
            if token.is_keyword:
                val = token.value.upper()
                capture_next = val == "FROM" or val.endswith("JOIN")
                continue
            if not capture_next:
                continue
            capture_next = False
            if isinstance(token, sqlparse.sql.IdentifierList):
                for ident in token.get_identifiers():
                    name = ident.get_real_name()
                    if name:
                        tables.add(name.strip('"').strip("'"))
            elif isinstance(token, sqlparse.sql.Identifier):
                name = token.get_real_name()
                if name:
                    tables.add(name.strip('"').strip("'"))
            elif token.ttype in Name:
                tables.add(token.value.strip('"').strip("'"))
    return list(tables)


class DataPermissionApplier:
    """根据 DataPermission 对 Schema 和 SQL 进行权限控制。"""

    @staticmethod
    async def get_permission(user_id: Optional[str], data_source_id: Optional[str]) -> Optional[DataPermission]:
        """获取用户对指定数据源的数据权限。"""
        if not user_id:
            return None
        async with AsyncSessionLocal() as session:
            return await data_permission_repo.get_by_user_and_source(
                session, user_id, data_source_id or ""
            )

    @staticmethod
    def filter_schema(schema: dict, permission: Optional[DataPermission]) -> dict:
        """根据权限过滤 Schema（表级 + 字段级）。"""
        if not permission:
            return schema
        allowed_tables = permission.allowed_tables or []
        allowed_columns = permission.allowed_columns or {}
        if not allowed_tables:
            return schema

        filtered = {}
        for table_name, table_info in schema.items():
            if table_name not in allowed_tables:
                continue
            col_whitelist = allowed_columns.get(table_name)
            columns = table_info.get("columns", [])
            if col_whitelist and isinstance(col_whitelist, list):
                columns = [c for c in columns if c.get("name") in col_whitelist]
            filtered[table_name] = {**table_info, "columns": columns}
        return filtered

    @staticmethod
    def validate_tables(sql: str, permission: Optional[DataPermission]) -> None:
        """校验 SQL 中引用的表是否在允许列表中。"""
        if not permission:
            return
        allowed_tables = permission.allowed_tables or []
        if not allowed_tables:
            return
        tables = _extract_tables(sql)
        for t in tables:
            if t not in allowed_tables:
                raise HTTPException(status_code=403, detail=f"无权限访问表: {t}")

    @staticmethod
    def inject_row_filters(sql: str, permission: Optional[DataPermission]) -> str:
        """为 SQL 注入行级过滤条件。"""
        if not permission or not permission.row_filters:
            return sql
        row_filters = permission.row_filters or {}
        conditions = [f"({expr})" for expr in row_filters.values() if expr]
        if not conditions:
            return sql

        where_clause = " AND ".join(conditions)
        cleaned = sql.rstrip("; ")
        lower_sql = cleaned.lower()

        if " where " in lower_sql:
            return f"{cleaned} AND {where_clause}"

        # 在 ORDER BY / GROUP BY / LIMIT 之前注入 WHERE
        insert_pos = len(cleaned)
        for kw in [" order by ", " group by ", " limit "]:
            idx = lower_sql.find(kw)
            if idx != -1:
                insert_pos = idx
                break
        return f"{cleaned[:insert_pos]} WHERE {where_clause}{cleaned[insert_pos:]}"
