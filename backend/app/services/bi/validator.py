"""SQL 安全引擎：基于 SQL AST 的白名单校验器。"""

from __future__ import annotations

import sqlparse
from sqlparse.tokens import DML
from fastapi import HTTPException

from app.config import get_settings

settings = get_settings()


class SQLSecurityValidator:
    """基于 SQL AST 的白名单安全校验器。

    只允许 SELECT 语句，禁止一切 DML/DDL。
    """

    ALLOWED_STATEMENT_TYPES = {"SELECT"}
    FORBIDDEN_KEYWORDS = {
        "insert", "update", "delete", "drop", "alter", "create",
        "truncate", "grant", "revoke", "execute", "exec", "call",
        "lock", "unlock", "merge", "replace", "copy", "load",
    }

    @classmethod
    def validate(cls, sql: str) -> str:
        """校验 SQL 安全性，返回清洗后的 SQL。

        Raises:
            HTTPException: 当 SQL 包含非 SELECT 语句或危险操作时。
        """
        if not sql or not sql.strip():
            raise HTTPException(status_code=400, detail="SQL 不能为空")

        cleaned = sql.strip()

        # 快速黑名单预检（防止明显的危险操作）
        lower_sql = cleaned.lower()
        for kw in cls.FORBIDDEN_KEYWORDS:
            # 使用单词边界避免误伤字段名
            import re
            if re.search(rf"\b{kw}\b", lower_sql):
                raise HTTPException(status_code=403, detail=f"SQL 包含禁止的操作: {kw.upper()}")

        # AST 级白名单校验
        parsed = sqlparse.parse(cleaned)
        if not parsed:
            raise HTTPException(status_code=400, detail="SQL 解析失败")

        for statement in parsed:
            first_token = None
            for token in statement.tokens:
                if not token.is_whitespace:
                    first_token = token
                    break

            if first_token is None:
                raise HTTPException(status_code=400, detail="SQL 为空语句")

            # 检查是否为 DML 且不是 SELECT
            if first_token.ttype is DML:
                token_value = str(first_token).upper()
                if token_value not in cls.ALLOWED_STATEMENT_TYPES:
                    raise HTTPException(
                        status_code=403,
                        detail=f"只允许执行 SELECT 查询，检测到: {token_value}"
                    )
            elif first_token.ttype is not None or str(first_token).upper() not in cls.ALLOWED_STATEMENT_TYPES:
                # 非 DML token（如 DDL 关键字）
                token_upper = str(first_token).upper()
                if token_upper not in cls.ALLOWED_STATEMENT_TYPES:
                    raise HTTPException(
                        status_code=403,
                        detail=f"SQL 类型不被允许，只允许 SELECT: {token_upper}"
                    )

            # 检查子查询中是否嵌套了危险操作（如 UNION 后的注入）
            sql_str = str(statement).lower()
            # 禁止多语句（分号后跟非空白）
            import re
            if re.search(r";\s*\S", sql_str):
                raise HTTPException(status_code=403, detail="SQL 不允许包含多条语句")

        return cleaned

    @classmethod
    def inject_limit(cls, sql: str, max_rows: int = None) -> str:
        """如果 SQL 没有 LIMIT，自动注入 LIMIT。

        这是最后一道防线，防止返回过多数据。
        """
        max_rows = max_rows or settings.BI_MAX_RESULT_ROWS
        lower_sql = sql.lower()

        # 简单的启发式检查：如果已经有 limit 则不注入
        if "limit" in lower_sql:
            return sql

        # 在 SQL 末尾添加 LIMIT
        return f"{sql.rstrip('; ')} LIMIT {max_rows}"
