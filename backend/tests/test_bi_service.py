"""Tests for BI service（app.services.bi_service）。

拆包前托底：锁定 SQLSecurityValidator / DataPermissionApplier / SchemaManager /
QueryExecutor / 连接配置加解密掩码 的现有行为。全部 mock，不连真实 DB/Redis。
"""

from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from app.config import get_settings
from app.services.bi_service import (
    BIService,
    DataPermissionApplier,
    QueryExecutor,
    SchemaManager,
    SQLSecurityValidator,
    _build_sync_runner,
    _decrypt_connection_config,
    _encrypt_connection_config,
    _extract_tables,
    _mask_connection_config,
    _run_with_timeout,
    bi_service,
)

settings = get_settings()


def _make_permission(**overrides):
    perm = SimpleNamespace(
        allowed_tables=[],
        allowed_columns={},
        row_filters={},
    )
    for k, v in overrides.items():
        setattr(perm, k, v)
    return perm


def _make_schema():
    return {
        "orders": {
            "name": "orders",
            "alias": "订单表",
            "description": "订单主表",
            "hidden": False,
            "columns": [
                {"name": "id", "type": "INTEGER", "alias": None, "description": "主键", "enums": None, "hidden": False},
                {"name": "status", "type": "VARCHAR", "alias": "状态", "description": None, "enums": ["paid", "pending"], "hidden": False},
                {"name": "secret_col", "type": "VARCHAR", "alias": None, "description": None, "enums": None, "hidden": True},
            ],
        },
        "users": {
            "name": "users",
            "alias": None,
            "description": None,
            "hidden": False,
            "columns": [
                {"name": "id", "type": "INTEGER", "alias": None, "description": None, "enums": None, "hidden": False},
            ],
        },
        "internal_log": {
            "name": "internal_log",
            "alias": None,
            "description": None,
            "hidden": True,
            "columns": [
                {"name": "id", "type": "INTEGER", "alias": None, "description": None, "enums": None, "hidden": False},
            ],
        },
    }


# ============================================================================
# 连接配置加解密 / 掩码
# ============================================================================

class TestConnectionConfigCrypto:
    def test_encrypt_none_or_empty_returns_empty_dict(self):
        assert _encrypt_connection_config(None) == {}
        assert _encrypt_connection_config({}) == {}
        assert _decrypt_connection_config(None) == {}
        assert _mask_connection_config(None) == {}

    def test_encrypt_without_password_unchanged(self):
        cfg = {"host": "h", "port": 5432}
        assert _encrypt_connection_config(cfg) == cfg
        assert _decrypt_connection_config(cfg) == cfg

    def test_encrypt_decrypt_roundtrip_with_fernet(self):
        """配置 Fernet 时：加密后可解密回明文，且密文不等于明文。"""
        fernet = Fernet(Fernet.generate_key())
        mock_settings = MagicMock()
        mock_settings.get_fernet.return_value = fernet
        cfg = {"host": "h", "user": "u", "password": "s3cret"}

        with patch("app.services.bi.connections.settings", mock_settings):
            encrypted = _encrypt_connection_config(cfg)
            assert encrypted["password"] != "s3cret"
            assert encrypted["host"] == "h"
            decrypted = _decrypt_connection_config(encrypted)

        assert decrypted["password"] == "s3cret"

    def test_decrypt_failure_passthrough_plaintext(self):
        """解密失败（如旧明文数据）时按原文透传。"""
        fernet = Fernet(Fernet.generate_key())
        mock_settings = MagicMock()
        mock_settings.get_fernet.return_value = fernet
        cfg = {"password": "plain-legacy-password"}

        with patch("app.services.bi.connections.settings", mock_settings):
            assert _decrypt_connection_config(cfg)["password"] == "plain-legacy-password"

    def test_mask_hides_password(self):
        cfg = {"host": "h", "password": "s3cret"}
        masked = _mask_connection_config(cfg)
        assert masked["password"] == "********"
        assert masked["host"] == "h"
        assert cfg["password"] == "s3cret"  # 原 dict 不被修改

    def test_mask_without_password_unchanged(self):
        cfg = {"host": "h", "password": ""}
        assert _mask_connection_config(cfg) == cfg


# ============================================================================
# SQL 安全校验器
# ============================================================================

class TestSQLSecurityValidator:
    def test_valid_select_passes_and_stripped(self):
        assert SQLSecurityValidator.validate("  SELECT id FROM users  ") == "SELECT id FROM users"

    def test_empty_sql_rejected_400(self):
        with pytest.raises(HTTPException) as exc:
            SQLSecurityValidator.validate("")
        assert exc.value.status_code == 400
        with pytest.raises(HTTPException) as exc:
            SQLSecurityValidator.validate("   ")
        assert exc.value.status_code == 400

    @pytest.mark.parametrize("sql,kw", [
        ("DROP TABLE users", "DROP"),
        ("DELETE FROM users", "DELETE"),
        ("UPDATE users SET x = 1", "UPDATE"),
        ("INSERT INTO users VALUES (1)", "INSERT"),
        ("ALTER TABLE users ADD c INT", "ALTER"),
        ("TRUNCATE TABLE users", "TRUNCATE"),
    ])
    def test_blacklist_keywords_rejected_403(self, sql, kw):
        with pytest.raises(HTTPException) as exc:
            SQLSecurityValidator.validate(sql)
        assert exc.value.status_code == 403
        assert kw in exc.value.detail

    def test_blacklist_word_boundary_no_false_positive(self):
        """字段名含黑名单前缀（updated_at / created_by）不应误伤。"""
        assert SQLSecurityValidator.validate(
            "SELECT updated_at, created_by, deleted_flag FROM users"
        ) == "SELECT updated_at, created_by, deleted_flag FROM users"

    def test_pure_select_multi_statement_passes(self):
        """现状锁定：sqlparse 按分号拆成多条独立 SELECT 时逐条校验，均放行。"""
        assert SQLSecurityValidator.validate("SELECT 1; SELECT 2") == "SELECT 1; SELECT 2"

    def test_semicolon_followed_by_content_rejected(self):
        """现状锁定：单条语句字符串内出现 ';' 后跟非空白（如字符串字面量）被多语句规则拦截。"""
        with pytest.raises(HTTPException) as exc:
            SQLSecurityValidator.validate("SELECT * FROM t WHERE a = 'x; y'")
        assert exc.value.status_code == 403
        assert "多条语句" in exc.value.detail

    def test_comment_cannot_bypass_blacklist(self):
        """黑名单基于原始文本正则，注释中出现 DROP 同样被拦截。"""
        with pytest.raises(HTTPException) as exc:
            SQLSecurityValidator.validate("SELECT 1 -- DROP TABLE x")
        assert exc.value.status_code == 403
        assert "DROP" in exc.value.detail

    def test_comment_obfuscated_keyword_rejected(self):
        """DR/**/OP 绕过黑名单正则，但 AST 白名单仍拒绝非 SELECT 起始 token。"""
        with pytest.raises(HTTPException) as exc:
            SQLSecurityValidator.validate("DR/**/OP TABLE x")
        assert exc.value.status_code == 403

    def test_cte_with_rejected(self):
        """现状锁定：WITH (CTE) 首 token 非 SELECT，被白名单拒绝。"""
        with pytest.raises(HTTPException) as exc:
            SQLSecurityValidator.validate("WITH cte AS (SELECT 1) SELECT * FROM cte")
        assert exc.value.status_code == 403


class TestInjectLimit:
    def test_injects_limit_when_missing(self):
        out = SQLSecurityValidator.inject_limit("SELECT * FROM users")
        assert out == f"SELECT * FROM users LIMIT {settings.BI_MAX_RESULT_ROWS}"

    def test_strips_trailing_semicolon_before_inject(self):
        out = SQLSecurityValidator.inject_limit("SELECT * FROM users;")
        assert out == f"SELECT * FROM users LIMIT {settings.BI_MAX_RESULT_ROWS}"

    def test_existing_limit_not_duplicated(self):
        assert SQLSecurityValidator.inject_limit("SELECT * FROM users LIMIT 10") == "SELECT * FROM users LIMIT 10"

    def test_existing_limit_case_insensitive(self):
        assert SQLSecurityValidator.inject_limit("select * from users limit 10") == "select * from users limit 10"

    def test_custom_max_rows(self):
        assert SQLSecurityValidator.inject_limit("SELECT 1", max_rows=50) == "SELECT 1 LIMIT 50"


# ============================================================================
# 数据权限应用器
# ============================================================================

class TestDataPermissionApplierSchema:
    def test_filter_schema_no_permission_passthrough(self):
        schema = _make_schema()
        assert DataPermissionApplier.filter_schema(schema, None) is schema

    def test_filter_schema_empty_allowed_tables_passthrough(self):
        schema = _make_schema()
        perm = _make_permission(allowed_tables=[])
        assert DataPermissionApplier.filter_schema(schema, perm) is schema

    def test_filter_schema_table_whitelist(self):
        schema = _make_schema()
        perm = _make_permission(allowed_tables=["orders"])
        filtered = DataPermissionApplier.filter_schema(schema, perm)
        assert list(filtered.keys()) == ["orders"]

    def test_filter_schema_column_whitelist(self):
        schema = _make_schema()
        perm = _make_permission(
            allowed_tables=["orders"],
            allowed_columns={"orders": ["id"]},
        )
        filtered = DataPermissionApplier.filter_schema(schema, perm)
        assert [c["name"] for c in filtered["orders"]["columns"]] == ["id"]


class TestDataPermissionApplierValidateTables:
    def test_validate_tables_no_permission_noop(self):
        DataPermissionApplier.validate_tables("SELECT * FROM anything", None)

    def test_validate_tables_empty_allowed_tables_noop(self):
        perm = _make_permission(allowed_tables=[])
        DataPermissionApplier.validate_tables("SELECT * FROM anything", perm)

    def test_validate_tables_normal_sql_not_whitelisted_raises_403(self):
        """常规 `FROM <table>`（有空白）也会被提取，白名单外的表被拦截。"""
        perm = _make_permission(allowed_tables=["orders"])
        with pytest.raises(HTTPException) as exc:
            DataPermissionApplier.validate_tables("SELECT * FROM secret_table", perm)
        assert exc.value.status_code == 403
        assert "无权限访问表" in exc.value.detail

    def test_validate_tables_normal_sql_whitelisted_passes(self):
        perm = _make_permission(allowed_tables=["orders"])
        DataPermissionApplier.validate_tables("SELECT * FROM orders", perm)
        DataPermissionApplier.validate_tables(
            "SELECT o.id FROM orders o JOIN users u ON u.id = o.user_id",
            _make_permission(allowed_tables=["orders", "users"]),
        )

    def test_validate_tables_alias_not_treated_as_table(self):
        """别名不作为表名参与白名单校验。"""
        perm = _make_permission(allowed_tables=["orders"])
        DataPermissionApplier.validate_tables("SELECT o.id FROM orders o", perm)

    def test_validate_tables_extracted_table_not_whitelisted_raises_403(self):
        """提取生效的语句形态（FROM 后紧跟非空白 token）下，表白名单外名称被拦截。"""
        perm = _make_permission(allowed_tables=["orders"])
        with pytest.raises(HTTPException) as exc:
            DataPermissionApplier.validate_tables("SELECT id FROM(SELECT 1) t", perm)
        assert exc.value.status_code == 403
        assert "无权限访问表" in exc.value.detail

    def test_inject_row_filters_no_permission_unchanged(self):
        sql = "SELECT * FROM orders"
        assert DataPermissionApplier.inject_row_filters(sql, None) == sql
        perm = _make_permission(row_filters={})
        assert DataPermissionApplier.inject_row_filters(sql, perm) == sql

    def test_inject_row_filters_appends_and_to_existing_where(self):
        perm = _make_permission(row_filters={"orders": "tenant_id = 't1'"})
        out = DataPermissionApplier.inject_row_filters("SELECT * FROM orders WHERE status = 'paid'", perm)
        assert out == "SELECT * FROM orders WHERE status = 'paid' AND (tenant_id = 't1')"

    def test_inject_row_filters_inserts_where_before_order_by(self):
        perm = _make_permission(row_filters={"orders": "tenant_id = 't1'"})
        out = DataPermissionApplier.inject_row_filters("SELECT * FROM orders ORDER BY id DESC", perm)
        assert out == "SELECT * FROM orders WHERE (tenant_id = 't1') ORDER BY id DESC"

    def test_inject_row_filters_inserts_where_before_limit(self):
        perm = _make_permission(row_filters={"orders": "tenant_id = 't1'"})
        out = DataPermissionApplier.inject_row_filters("SELECT * FROM orders LIMIT 10", perm)
        assert out == "SELECT * FROM orders WHERE (tenant_id = 't1') LIMIT 10"

    def test_inject_row_filters_appends_where_at_end(self):
        perm = _make_permission(row_filters={"orders": "tenant_id = 't1'"})
        out = DataPermissionApplier.inject_row_filters("SELECT * FROM orders;", perm)
        assert out == "SELECT * FROM orders WHERE (tenant_id = 't1')"

    def test_inject_row_filters_multiple_conditions_joined_with_and(self):
        perm = _make_permission(row_filters={"orders": "tenant_id = 't1'", "users": "region = 'east'"})
        out = DataPermissionApplier.inject_row_filters("SELECT * FROM orders", perm)
        assert out == "SELECT * FROM orders WHERE (tenant_id = 't1') AND (region = 'east')"


class TestExtractTables:
    def test_normal_from_with_whitespace_extracts(self):
        """FROM/JOIN 与表名之间的空白被跳过，常规 SQL 正常提取。"""
        assert _extract_tables("SELECT id FROM orders") == ["orders"]
        assert set(_extract_tables(
            "SELECT o.id FROM orders o JOIN users u ON u.id = o.user_id"
        )) == {"orders", "users"}

    def test_from_followed_by_subquery_extracts_alias(self):
        """FROM 后紧跟子查询时提取其别名。"""
        tables = _extract_tables("SELECT id FROM(SELECT 1) t")
        assert tables == ["t"]

    def test_quoted_and_comma_separated_tables(self):
        assert set(_extract_tables('SELECT * FROM "orders", users')) == {"orders", "users"}


# ============================================================================
# Schema 管理器
# ============================================================================

class TestSchemaManagerMerge:
    def test_merge_no_metadata_passthrough(self):
        schema = _make_schema()
        assert SchemaManager._merge_metadata(schema, {}) is schema

    def test_merge_metadata_applies_alias_description_enums_hidden(self):
        schema = _make_schema()
        metadata = {
            "tables": {
                "users": {
                    "alias": "用户表",
                    "description": "系统用户",
                    "hidden": True,
                    "columns": {
                        "id": {"alias": "用户ID", "description": "uid", "enums": ["1"], "hidden": True},
                    },
                }
            }
        }
        merged = SchemaManager._merge_metadata(schema, metadata)
        users = merged["users"]
        assert users["alias"] == "用户表"
        assert users["description"] == "系统用户"
        assert users["hidden"] is True
        col = users["columns"][0]
        assert col["alias"] == "用户ID"
        assert col["description"] == "uid"
        assert col["enums"] == ["1"]
        assert col["hidden"] is True
        # 未提及的表不受影响
        assert merged["orders"]["alias"] == "订单表"


class TestSchemaManagerFormatForLLM:
    def test_format_contains_alias_description_enums(self):
        text = SchemaManager.format_for_llm(_make_schema())
        assert text.startswith("## 数据库表结构")
        assert "### orders（订单表）" in text
        assert "说明：订单主表" in text
        assert "- status: VARCHAR（状态）" in text
        assert "枚举：['paid', 'pending']" in text
        assert "- id: INTEGER // 主键" in text

    def test_format_skips_hidden_tables_and_columns(self):
        text = SchemaManager.format_for_llm(_make_schema())
        assert "internal_log" not in text
        assert "secret_col" not in text

    def test_format_allowed_tables_filter(self):
        text = SchemaManager.format_for_llm(_make_schema(), allowed_tables=["users"])
        assert "### users" in text
        assert "### orders" not in text

    def test_format_relationships_only_between_visible_tables(self):
        metadata = {
            "relationships": [
                {"from_table": "orders", "from_column": "user_id", "to_table": "users", "to_column": "id"},
                {"from_table": "orders", "from_column": "x", "to_table": "internal_log", "to_column": "id"},
            ]
        }
        text = SchemaManager.format_for_llm(_make_schema(), metadata=metadata)
        assert "## 表关系" in text
        assert "orders.user_id many_to_one users.id" in text
        assert "internal_log" not in text

    def test_format_metrics(self):
        metadata = {
            "metrics": [
                {"name": "gmv", "alias": "成交额", "expression": "SUM(amount)", "aggregation": "sum",
                 "dimensions": ["orders.status"], "description": "GMV"},
            ]
        }
        text = SchemaManager.format_for_llm(_make_schema(), metadata=metadata)
        assert "## 业务指标" in text
        assert "- 成交额：SUM(amount)" in text
        assert "聚合：sum" in text
        assert "// GMV" in text


@pytest.mark.asyncio
class TestSchemaManagerGetSchema:
    async def test_get_schema_merges_metadata_and_uses_cache(self):
        async def _passthrough(key, factory, ttl=300, prefix=None):
            return await factory()

        introspected = _make_schema()
        metadata = {"tables": {"users": {"alias": "用户表"}}}
        with patch("app.services.bi.schema.cache_get_or_set", side_effect=_passthrough), \
             patch.object(SchemaManager, "_inspect_schema", new=AsyncMock(return_value=introspected)):
            schema = await SchemaManager.get_schema(engine=MagicMock(), data_source_id="ds-1", metadata=metadata)

        assert schema["users"]["alias"] == "用户表"
        assert "orders" in schema


# ============================================================================
# 查询执行器
# ============================================================================

class TestQueryExecutorCacheKey:
    def test_cache_key_deterministic_and_source_sensitive(self):
        k1 = QueryExecutor._build_cache_key("SELECT 1", None)
        k2 = QueryExecutor._build_cache_key("SELECT 1", None)
        k3 = QueryExecutor._build_cache_key("SELECT 1", "ds-1")
        k4 = QueryExecutor._build_cache_key("SELECT 2", None)
        assert k1 == k2
        assert k1 != k3
        assert k1 != k4
        assert len(k1) == 32  # md5 hexdigest


@pytest.mark.asyncio
class TestQueryExecutorExecute:
    async def test_cache_hit_returns_cached_without_db(self):
        cached_result = {"columns": ["id"], "rows": [["1"]], "row_count": 1}
        with patch("app.services.bi.executor.cache_get", new=AsyncMock(return_value=cached_result)) as mock_get, \
             patch.object(QueryExecutor, "_execute_with_timeout", new=AsyncMock()) as mock_exec, \
             patch("app.services.bi.executor.cache_set", new=AsyncMock()) as mock_set:
            result = await QueryExecutor.execute("SELECT id FROM users")

        assert result["cached"] is True
        assert result["row_count"] == 1
        mock_get.assert_awaited_once()
        mock_exec.assert_not_awaited()
        mock_set.assert_not_awaited()

    async def test_cache_miss_executes_writes_cache_and_log(self):
        db_result = {"columns": ["id"], "rows": [["1"], ["2"]], "row_count": 2}
        with patch("app.services.bi.executor.cache_get", new=AsyncMock(return_value=None)), \
             patch.object(QueryExecutor, "_execute_with_timeout", new=AsyncMock(return_value=dict(db_result))) as mock_exec, \
             patch.object(QueryExecutor, "_log_query", new=AsyncMock()) as mock_log, \
             patch("app.services.bi.executor.cache_set", new=AsyncMock()) as mock_set:
            result = await QueryExecutor.execute(
                "SELECT id FROM users", user_id="u1", data_source_id="ds-1",
                natural_language_query="查用户",
            )

        assert result["cached"] is False
        assert result["row_count"] == 2
        assert "execution_time_ms" in result

        # 实际下发 DB 的 SQL 已被注入 LIMIT
        executed_sql = mock_exec.call_args.args[0]
        assert executed_sql.endswith(f"LIMIT {settings.BI_MAX_RESULT_ROWS}")

        # 审计日志：success
        mock_log.assert_awaited_once()
        log_kwargs = mock_log.call_args.kwargs
        assert log_kwargs["status"] == "success"
        assert log_kwargs["row_count"] == 2
        assert log_kwargs["user_id"] == "u1"

        # 写缓存
        mock_set.assert_awaited_once()
        set_args = mock_set.call_args
        assert set_args.kwargs["ttl"] == QueryExecutor.CACHE_TTL
        assert set_args.kwargs["prefix"] == QueryExecutor.CACHE_PREFIX
        assert set_args.args[1]["row_count"] == 2

    async def test_execution_error_logs_and_raises_400(self):
        with patch("app.services.bi.executor.cache_get", new=AsyncMock(return_value=None)), \
             patch.object(QueryExecutor, "_execute_with_timeout", new=AsyncMock(side_effect=RuntimeError("boom"))), \
             patch.object(QueryExecutor, "_log_query", new=AsyncMock()) as mock_log, \
             patch("app.services.bi.executor.cache_set", new=AsyncMock()) as mock_set:
            with pytest.raises(HTTPException) as exc:
                await QueryExecutor.execute("SELECT id FROM users")

        assert exc.value.status_code == 400
        assert "boom" in exc.value.detail
        log_kwargs = mock_log.call_args.kwargs
        assert log_kwargs["status"] == "error"
        assert "boom" in log_kwargs["error_message"]
        mock_set.assert_not_awaited()

    async def test_unsafe_sql_rejected_before_cache_and_db(self):
        with patch("app.services.bi.executor.cache_get", new=AsyncMock()) as mock_get, \
             patch.object(QueryExecutor, "_execute_with_timeout", new=AsyncMock()) as mock_exec:
            with pytest.raises(HTTPException) as exc:
                await QueryExecutor.execute("DELETE FROM users")
        assert exc.value.status_code == 403
        mock_get.assert_not_awaited()
        mock_exec.assert_not_awaited()


# ============================================================================
# BIService 门面
# ============================================================================

@pytest.mark.asyncio
class TestBIServiceFacade:
    async def test_singleton_and_component_wiring(self):
        assert isinstance(bi_service, BIService)
        assert bi_service.validator is SQLSecurityValidator
        assert bi_service.schema_manager is SchemaManager
        assert bi_service.query_executor is QueryExecutor

    async def test_execute_query_clamps_timeout_to_max(self):
        """数据源配置的 query_timeout_seconds 超过全局上限时被钳制。"""
        source = SimpleNamespace(
            id="ds-1",
            connection_config={"query_timeout_seconds": 99999},
        )
        with patch.object(type(bi_service).connector, "get_engine", return_value=MagicMock()), \
             patch.object(QueryExecutor, "execute", new=AsyncMock(return_value={"ok": True})) as mock_exec:
            await bi_service.execute_query("SELECT 1", data_source=source)

        assert mock_exec.call_args.kwargs["timeout"] == settings.BI_MAX_QUERY_TIMEOUT_SECONDS

    async def test_execute_query_uses_source_timeout(self):
        source = SimpleNamespace(
            id="ds-1",
            connection_config={"query_timeout_seconds": 5},
        )
        with patch.object(type(bi_service).connector, "get_engine", return_value=MagicMock()), \
             patch.object(QueryExecutor, "execute", new=AsyncMock(return_value={"ok": True})) as mock_exec:
            await bi_service.execute_query("SELECT 1", data_source=source)

        assert mock_exec.call_args.kwargs["timeout"] == 5


# ============================================================================
# 异步辅助函数
# ============================================================================

@pytest.mark.asyncio
class TestAsyncHelpers:
    async def test_run_with_timeout_success(self):
        async def _ok():
            return 42
        assert await _run_with_timeout(_ok(), timeout=5) == 42

    async def test_run_with_timeout_raises_504(self):
        import asyncio

        async def _slow():
            await asyncio.sleep(5)
        with pytest.raises(HTTPException) as exc:
            await _run_with_timeout(_slow(), timeout=1, operation="测试操作")
        assert exc.value.status_code == 504
        assert "测试操作" in exc.value.detail


class TestSyncHelpers:
    def test_build_sync_runner_async_engine_uses_run_sync(self):
        engine = MagicMock()
        engine.run_sync = MagicMock(return_value="runner")
        assert _build_sync_runner(engine, lambda c: None) == "runner"
