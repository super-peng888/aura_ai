"""Tests for Data Agent（app.core.data_agent）。

拆包前托底：锁定 classify 三分支路由、validate_and_execute 失败回退、
流式输出协议。llm_service / bi_service 全部 mock，不连真实服务。
"""

from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.core.data_agent import (
    DataAgentService,
    DataPermissionApplier,
    _extract_json,
    build_data_agent_graph,
    clarification_node,
    classify_intent_node,
    direct_analysis_node,
    generate_sql_node,
    intent_router,
    load_context_node,
    refine_visualization_node,
    validate_and_execute_node,
)


def _state(**overrides):
    state = {
        "messages": [],
        "query": "上个月的销售趋势如何？",
        "user_id": "u1",
        "llm_config": None,
        "data_source_id": None,
        "schema": {},
        "schema_metadata": None,
        "allowed_tables": [],
        "intent": "",
        "generated_sql": "",
        "query_result": None,
        "analysis": "",
        "charts": [],
        "tables": [],
        "error": None,
    }
    state.update(overrides)
    return state


def _mock_llm(return_value=None, side_effect=None):
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=return_value, side_effect=side_effect)
    return llm


def _mock_bi():
    bi = MagicMock()
    bi.get_data_source = AsyncMock(return_value=None)
    bi.get_schema = AsyncMock(return_value={})
    bi.execute_query = AsyncMock(return_value={"columns": ["id"], "rows": [["1"]], "row_count": 1})
    bi.format_schema_for_llm = MagicMock(return_value="schema text")
    return bi


# ============================================================================
# _extract_json 工具
# ============================================================================

class TestExtractJson:
    def test_plain_json(self):
        assert _extract_json('{"a": 1}') == {"a": 1}

    def test_strips_markdown_fence(self):
        assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_extracts_json_from_surrounding_text(self):
        assert _extract_json('前置说明 {"a": 1} 后置说明') == {"a": 1}

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            _extract_json("not json at all")


# ============================================================================
# intent_router（纯函数）
# ============================================================================

class TestIntentRouter:
    def test_sql_query_routes_to_generate_sql(self):
        assert intent_router(_state(intent="sql_query")) == "generate_sql"

    def test_direct_routes_to_direct_analysis(self):
        assert intent_router(_state(intent="direct")) == "direct"

    def test_clarify_routes_to_clarification(self):
        assert intent_router(_state(intent="clarify")) == "clarify"

    def test_unknown_falls_back_to_generate_sql(self):
        assert intent_router(_state(intent="whatever")) == "generate_sql"
        assert intent_router(_state(intent="")) == "generate_sql"


# ============================================================================
# classify_intent_node
# ============================================================================

@pytest.mark.asyncio
class TestClassifyIntentNode:
    @pytest.mark.parametrize("llm_reply,expected", [
        ("sql_query", "sql_query"),
        ("direct", "direct"),
        ("clarify", "clarify"),
        ("SQL_QUERY\n", "sql_query"),  # 大小写/空白归一化
        ("无法理解", "sql_query"),     # 非法值回退
    ])
    async def test_classify_three_branches_and_fallback(self, llm_reply, expected):
        with patch("app.core.data_agent.llm_service", _mock_llm(return_value=llm_reply)):
            out = await classify_intent_node(_state())
        assert out["intent"] == expected

    async def test_llm_exception_falls_back_to_sql_query(self):
        with patch("app.core.data_agent.llm_service", _mock_llm(side_effect=RuntimeError("llm down"))):
            out = await classify_intent_node(_state())
        assert out["intent"] == "sql_query"


# ============================================================================
# generate_sql_node
# ============================================================================

@pytest.mark.asyncio
class TestGenerateSqlNode:
    async def test_valid_json_response_parsed(self):
        reply = '{"sql": "SELECT 1", "analysis": "分析", "charts": [{"title": "t"}], "tables": []}'
        with patch("app.core.data_agent.llm_service", _mock_llm(return_value=reply)), \
             patch("app.core.data_agent.bi_service", _mock_bi()):
            out = await generate_sql_node(_state(schema={"orders": {}}))

        assert out["generated_sql"] == "SELECT 1"
        assert out["analysis"] == "分析"
        assert out["charts"] == [{"title": "t"}]
        assert out["tables"] == []

    async def test_invalid_json_falls_back_to_raw_analysis(self):
        with patch("app.core.data_agent.llm_service", _mock_llm(return_value="不是 JSON")), \
             patch("app.core.data_agent.bi_service", _mock_bi()):
            out = await generate_sql_node(_state())

        assert out["generated_sql"] == ""
        assert out["analysis"] == "不是 JSON"
        assert out["error"] == "JSON 解析失败"
        assert out["charts"] == [] and out["tables"] == []


# ============================================================================
# validate_and_execute_node（失败回退是重点）
# ============================================================================

@pytest.mark.asyncio
class TestValidateAndExecuteNode:
    async def test_empty_sql_skips_execution(self):
        out = await validate_and_execute_node(_state(generated_sql=""))
        assert out == {"query_result": None}

    async def test_permission_violation_returns_error_without_execute(self):
        bi = _mock_bi()
        with patch("app.core.data_agent.bi_service", bi), \
             patch.object(DataPermissionApplier, "get_permission", new=AsyncMock(return_value=MagicMock())), \
             patch.object(DataPermissionApplier, "validate_tables",
                          side_effect=HTTPException(status_code=403, detail="无权限访问表: secret")):
            out = await validate_and_execute_node(_state(generated_sql="SELECT * FROM secret"))

        assert out["query_result"] is None
        assert out["error"] == "无权限访问表: secret"
        bi.execute_query.assert_not_awaited()

    async def test_success_injects_row_filters_and_executes(self):
        """行级过滤注入后的 SQL 才下发执行。"""
        perm = SimpleNamespace(allowed_tables=[], row_filters={"orders": "tenant_id = 't1'"})
        bi = _mock_bi()
        with patch("app.core.data_agent.bi_service", bi), \
             patch.object(DataPermissionApplier, "get_permission", new=AsyncMock(return_value=perm)):
            out = await validate_and_execute_node(_state(generated_sql="SELECT * FROM orders"))

        assert out["query_result"]["row_count"] == 1
        executed_sql = bi.execute_query.call_args.args[0]
        assert executed_sql == "SELECT * FROM orders WHERE (tenant_id = 't1')"
        assert bi.execute_query.call_args.kwargs["user_id"] == "u1"

    async def test_execute_failure_falls_back_to_error(self):
        """执行失败不抛出，回退为 query_result=None + error。"""
        bi = _mock_bi()
        bi.execute_query = AsyncMock(side_effect=HTTPException(status_code=400, detail="查询执行失败: boom"))
        with patch("app.core.data_agent.bi_service", bi), \
             patch.object(DataPermissionApplier, "get_permission", new=AsyncMock(return_value=None)):
            out = await validate_and_execute_node(_state(generated_sql="SELECT * FROM orders"))

        assert out["query_result"] is None
        assert "查询执行失败" in out["error"]


# ============================================================================
# direct_analysis_node / clarification_node / load_context_node
# ============================================================================

@pytest.mark.asyncio
class TestOtherNodes:
    async def test_direct_analysis_success(self):
        with patch("app.core.data_agent.llm_service", _mock_llm(return_value="建议按周聚合看趋势")):
            out = await direct_analysis_node(_state())
        assert out["analysis"] == "建议按周聚合看趋势"
        assert out["generated_sql"] == ""
        assert out["query_result"] is None

    async def test_direct_analysis_llm_failure(self):
        with patch("app.core.data_agent.llm_service", _mock_llm(side_effect=RuntimeError("down"))):
            out = await direct_analysis_node(_state())
        assert "分析生成失败" in out["analysis"]

    async def test_clarification_node_returns_fixed_prompt(self):
        out = await clarification_node(_state())
        assert "澄清" in out["analysis"] or "详细描述" in out["analysis"]
        assert out["generated_sql"] == ""
        assert out["query_result"] is None

    async def test_load_context_filters_schema_by_permission(self):
        bi = _mock_bi()
        bi.get_schema = AsyncMock(return_value={"orders": {}, "users": {}})
        perm = SimpleNamespace(allowed_tables=["orders"], allowed_columns={}, row_filters={})
        with patch("app.core.data_agent.bi_service", bi), \
             patch.object(DataPermissionApplier, "get_permission", new=AsyncMock(return_value=perm)):
            out = await load_context_node(_state())

        assert list(out["schema"].keys()) == ["orders"]
        assert out["allowed_tables"] == ["orders"]


# ============================================================================
# 图路由（重建 graph，节点全部打桩）
# ============================================================================

@pytest.mark.asyncio
class TestGraphRouting:
    def _build_graph_with_stub_nodes(self, intent):
        stubs = {
            "load_context_node": AsyncMock(return_value={"schema": {}, "allowed_tables": []}),
            "classify_intent_node": AsyncMock(return_value={"intent": intent}),
            "generate_sql_node": AsyncMock(return_value={"generated_sql": "SELECT 1", "analysis": "a", "charts": [], "tables": []}),
            "validate_and_execute_node": AsyncMock(return_value={"query_result": {"row_count": 1}}),
            "refine_visualization_node": AsyncMock(return_value={}),
            "direct_analysis_node": AsyncMock(return_value={"analysis": "direct", "charts": [], "tables": []}),
            "clarification_node": AsyncMock(return_value={"analysis": "clarify", "charts": [], "tables": []}),
        }
        patches = [patch(f"app.core.data_agent.{name}", stub) for name, stub in stubs.items()]
        for p in patches:
            p.start()
        graph = build_data_agent_graph()
        for p in patches:
            p.stop()
        return graph, stubs

    async def test_sql_query_path(self):
        graph, stubs = self._build_graph_with_stub_nodes("sql_query")
        result = await graph.ainvoke(_state())

        stubs["generate_sql_node"].assert_awaited_once()
        stubs["validate_and_execute_node"].assert_awaited_once()
        stubs["refine_visualization_node"].assert_awaited_once()
        stubs["direct_analysis_node"].assert_not_awaited()
        stubs["clarification_node"].assert_not_awaited()
        assert result["generated_sql"] == "SELECT 1"

    async def test_direct_path(self):
        graph, stubs = self._build_graph_with_stub_nodes("direct")
        result = await graph.ainvoke(_state())

        stubs["direct_analysis_node"].assert_awaited_once()
        stubs["generate_sql_node"].assert_not_awaited()
        stubs["validate_and_execute_node"].assert_not_awaited()
        stubs["clarification_node"].assert_not_awaited()
        assert result["analysis"] == "direct"

    async def test_clarify_path(self):
        graph, stubs = self._build_graph_with_stub_nodes("clarify")
        result = await graph.ainvoke(_state())

        stubs["clarification_node"].assert_awaited_once()
        stubs["generate_sql_node"].assert_not_awaited()
        stubs["direct_analysis_node"].assert_not_awaited()
        assert result["analysis"] == "clarify"


# ============================================================================
# DataAgentService.analyze 流式输出协议
# ============================================================================

@pytest.mark.asyncio
class TestAnalyzeStreaming:
    async def test_yields_sse_chunks_in_order(self):
        final_state = _state(
            generated_sql="SELECT 1",
            query_result={"columns": ["id"], "rows": [["1"]], "row_count": 1},
            analysis="分析结论",
            charts=[{"title": "c1", "type": "bar", "option": {}}],
            tables=[{"title": "t1", "headers": ["id"], "rows": [["1"]]}],
            error=None,
        )
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value=final_state)
        with patch("app.core.data_agent.data_agent_graph", mock_graph):
            chunks = [c async for c in DataAgentService().analyze("查询", user_id="u1")]

        assert [c["type"] for c in chunks] == ["sql", "query_result", "analysis", "chart", "table", "done"]
        assert chunks[0]["data"] == "SELECT 1"
        assert chunks[-1]["data"] is None

    async def test_error_chunk_emitted_before_analysis(self):
        final_state = _state(generated_sql="SELECT 1", error="查询执行失败: boom")
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value=final_state)
        with patch("app.core.data_agent.data_agent_graph", mock_graph):
            chunks = [c async for c in DataAgentService().analyze("查询")]

        types = [c["type"] for c in chunks]
        assert types == ["sql", "error", "done"]
        assert chunks[1]["data"] == "查询执行失败: boom"
