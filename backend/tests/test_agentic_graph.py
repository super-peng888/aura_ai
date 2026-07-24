"""Tests for GraphRAG 检索侧 + agentic 工具调用模式。

覆盖：
- 检索配置 resolve defaults 三新键（rag_mode / enable_graph_rag / graph_search_mode）
- RetrievalConfigUpdate/Response schema 对枚举值的校验
- graph retriever：local_search 实体命中链路 / 空表返回 []；global_search 余弦排序
- rag_pipeline.search() 图检索融合（开/关、去重）
- agentic 工具循环：tool_calls → 无 tool_calls 序列、调用上限、SSE 序列

全部 mock，不连接任何真实服务（风格参照 test_retrieval_config.py）。
"""

from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from app.core.agent import nodes as agent_nodes_module
from app.core.agent import service as agent_service_module
from app.core.agent import tools as agent_tools_module
from app.core.agent import AgentState, MAX_TOOL_CALLS, agent_graph, agent_service
from app.core.knowledge import rag_pipeline as rag_pipeline_module
from app.core.knowledge.graph import retriever as retriever_module
from app.core.knowledge.graph.extraction import normalize_entity_name
from app.core.knowledge.graph.retriever import graph_retriever
from app.models.schemas import RetrievalConfigResponse, RetrievalConfigUpdate
from app.services.retrieval_config_service import RetrievalConfigService

QUERY = "报销流程是什么"


# ============================================================================
# 通用构造
# ============================================================================

def _chunks(*ids, with_images=False, search_type="hybrid"):
    return [
        {
            "chunk_id": cid,
            "document_id": "d1",
            "content": f"片段内容 {cid}",
            "score": 0.9,
            "page_number": 1,
            "search_type": search_type,
            "image_ids": [],
            "images": [{"id": "img-1", "url": "http://x/img.png"}] if with_images else [],
        }
        for cid in ids
    ]


def _state(**overrides):
    state = AgentState(
        messages=[],
        query=QUERY,
        user_id="u1",
        user_memory="",
        llm_config={},
        intent="",
        contexts=[],
        images=[],
        citations=[],
        response="",
        content_blocks=[],
        needs_clarification=False,
        conversation_id=None,
        knowledge_base_ids=[],
        temperature=0.7,
        data_agent_context=None,
        attachments=[],
        rag_mode="pipeline",
        tool_call_count=0,
        tool_messages=[],
    )
    state.update(overrides)
    return state


def _cfg(**overrides):
    cfg = {
        "rag_mode": "pipeline",
        "enable_graph_rag": False,
        "graph_search_mode": "auto",
    }
    cfg.update(overrides)
    return cfg


def _stream_fn(*deltas):
    def _fn(**kwargs):
        async def _gen():
            for d in deltas:
                yield d

        return _gen()

    return _fn


def _llm_generate(classify_intent="rag"):
    async def _fake(messages, temperature=0.7, max_tokens=None, user_config=None):
        return classify_intent

    return AsyncMock(side_effect=_fake)


def _agent_patches(cfg, retrieved):
    """patch agent 各子模块的 memory / llm / rag_pipeline / retrieval_config_service。

    拆分后依赖绑定在各使用方命名空间：nodes（节点）、tools（检索执行体）、service（chat 编排），
    rag_pipeline 需在三处同时 patch 为同一 mock。
    """
    mock_memory = MagicMock()
    mock_memory.search = AsyncMock(return_value=[])
    mock_memory.add = AsyncMock()

    mock_llm = MagicMock()
    mock_llm.generate = _llm_generate()
    mock_llm.generate_with_citations = MagicMock(side_effect=_stream_fn("答", "案"))
    mock_llm.generate_stream = MagicMock(side_effect=_stream_fn("答", "案"))

    mock_rag = MagicMock()
    mock_rag.search = AsyncMock(return_value={"results": retrieved})
    mock_rag.to_content_blocks = MagicMock(return_value=[])

    mock_cfg_svc = MagicMock()
    mock_cfg_svc.resolve = AsyncMock(return_value=cfg)

    return [
        patch.object(agent_nodes_module, "memory_service", mock_memory),
        patch.object(agent_nodes_module, "llm_service", mock_llm),
        patch.object(agent_nodes_module, "rag_pipeline", mock_rag),
        patch.object(agent_nodes_module, "retrieval_config_service", mock_cfg_svc),
        patch.object(agent_tools_module, "rag_pipeline", mock_rag),
        patch.object(agent_service_module, "rag_pipeline", mock_rag),
    ]


class _patch_stack:
    def __init__(self, patches):
        self.patches = patches

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


def _mocks(patches):
    return SimpleNamespace(
        memory=patches[0].new,
        llm=patches[1].new,
        rag=patches[2].new,
        cfg_svc=patches[3].new,
    )


def _ai_msg(content="", tool_calls=None):
    return AIMessage(content=content, tool_calls=tool_calls or [])


def _fake_model(ai_messages):
    """bind_tools 后 ainvoke 按序返回 AIMessage 的假模型。"""
    bound = MagicMock()
    bound.ainvoke = AsyncMock(side_effect=list(ai_messages))
    model = MagicMock()
    model.bind_tools = MagicMock(return_value=bound)
    return model


# ============================================================================
# 配置 resolve defaults + schema 校验
# ============================================================================

@pytest.mark.asyncio
class TestGraphRAGConfigDefaults:
    async def test_resolve_defaults_include_graphrag_keys(self):
        """resolve defaults：rag_mode=pipeline、enable_graph_rag=False、graph_search_mode=auto。"""

        async def _cache_passthrough(key, factory, ttl=300, prefix=None):
            return await factory()

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.retrieval_config_service.cache_get_or_set", side_effect=_cache_passthrough), \
             patch("app.services.retrieval_config_service.AsyncSessionLocal", MagicMock(return_value=cm)), \
             patch("app.services.retrieval_config_service.retrieval_config_repo") as mock_repo:
            mock_repo.get_singleton = AsyncMock(return_value=None)
            cfg = await RetrievalConfigService.resolve()

        assert cfg["rag_mode"] == "pipeline"
        assert cfg["enable_graph_rag"] is False
        assert cfg["graph_search_mode"] == "auto"

    async def test_db_row_overrides_graphrag_keys(self):
        """DB 行非 NULL 的三新键覆盖默认值。"""

        async def _cache_passthrough(key, factory, ttl=300, prefix=None):
            return await factory()

        row = SimpleNamespace(
            reranker_provider=None, reranker_model=None, reranker_api_key=None,
            reranker_base_url=None,
            embedding_model=None, embedding_base_url=None,
            embedding_api_key=None, embedding_dim=None,
            rerank_top_k=None, similarity_threshold=None, enable_query_rewrite=None,
            enable_keyword_search=None, enable_vector_search=None, enable_rerank=None,
            rag_mode="agentic", enable_graph_rag=True, graph_search_mode="local",
        )
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.retrieval_config_service.cache_get_or_set", side_effect=_cache_passthrough), \
             patch("app.services.retrieval_config_service.AsyncSessionLocal", MagicMock(return_value=cm)), \
             patch("app.services.retrieval_config_service.retrieval_config_repo") as mock_repo:
            mock_repo.get_singleton = AsyncMock(return_value=row)
            cfg = await RetrievalConfigService.resolve()

        assert cfg["rag_mode"] == "agentic"
        assert cfg["enable_graph_rag"] is True
        assert cfg["graph_search_mode"] == "local"


class TestGraphRAGSchema:
    def test_update_schema_accepts_valid_values(self):
        data = RetrievalConfigUpdate(rag_mode="agentic", enable_graph_rag=True, graph_search_mode="global")
        assert data.rag_mode == "agentic"
        assert data.graph_search_mode == "global"
        # 默认值
        default = RetrievalConfigUpdate()
        assert default.rag_mode == "pipeline"
        assert default.enable_graph_rag is False
        assert default.graph_search_mode == "auto"

    def test_update_schema_rejects_invalid_rag_mode(self):
        with pytest.raises(ValidationError):
            RetrievalConfigUpdate(rag_mode="smart")

    def test_update_schema_rejects_invalid_graph_search_mode(self):
        with pytest.raises(ValidationError):
            RetrievalConfigUpdate(graph_search_mode="hybrid")

    def test_response_schema_includes_new_fields(self):
        resp = RetrievalConfigResponse(
            **{**RetrievalConfigResponse().model_dump(),
               "rag_mode": "agentic", "enable_graph_rag": True, "graph_search_mode": "local"}
        )
        dumped = resp.model_dump()
        assert dumped["rag_mode"] == "agentic"
        assert dumped["enable_graph_rag"] is True
        assert dumped["graph_search_mode"] == "local"


# ============================================================================
# Graph retriever
# ============================================================================

class _FakeResult:
    """模拟 SQLAlchemy Result 的 mappings().all() 链路。"""

    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class TestNormalizeAlignment:
    """检索侧归一化与索引侧 name_normalized 严格同规则（纯函数层面）。

    索引侧（extraction.normalize_entity_name）：NFKC（全半角统一）→ casefold → 去空白。
    若检索侧只做 lower + 去空白，全角字符（如ＡＩ）与 casefold 专有映射（如 ß→ss）会漏匹配。
    """

    def test_retriever_reuses_extraction_normalizer(self):
        """检索侧锚定归一化直接复用 extraction.normalize_entity_name（同一函数）。"""
        assert retriever_module.normalize_entity_name is normalize_entity_name

    def test_fullwidth_casefold_whitespace(self):
        """全角→半角、casefold（非 lower）、去除所有空白（含全角空格）。"""
        assert normalize_entity_name("什么是ＡＩ　平台？") == "什么是ai平台?"
        assert normalize_entity_name("Straße") == "strasse"  # lower() 只得 "straße"


@pytest.mark.asyncio
class TestAnchorNormalization:
    """锚定 SQL 参数层面的归一化对齐（query 与 LLM 兜底提取名）。"""

    async def test_anchor_sql_receives_normalized_query(self):
        """子串锚定 SQL 的 :q 参数为完整归一化后的 query。"""
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=_FakeResult([{"id": "e1", "name": "AI平台", "entity_type": "产品"}])
        )
        anchors = await graph_retriever._anchor_entities(session, "什么是ＡＩ　平台？")

        assert session.execute.call_args.args[1]["q"] == "什么是ai平台?"
        assert [a["id"] for a in anchors] == ["e1"]

    async def test_llm_fallback_names_normalized_same_rule(self):
        """LLM 兜底提取的实体名按同一规则归一后再做等值匹配。"""
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _FakeResult([]),  # 子串未命中
            _FakeResult([{"id": "e9", "name": "DeepSeek", "entity_type": "组织"}]),
        ])
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="ＤｅｅｐＳｅｅｋ，通义 千问")
        with patch.object(retriever_module, "llm_service", mock_llm):
            anchors = await graph_retriever._anchor_entities(session, "无关问题")

        assert session.execute.call_args.args[1]["names"] == ["deepseek", "通义千问"]
        assert [a["id"] for a in anchors] == ["e9"]

    async def test_whitespace_only_query_returns_empty(self):
        """归一化后为空（纯空白 query）直接返回 []，不发起 SQL。"""
        session = AsyncMock()
        anchors = await graph_retriever._anchor_entities(session, " 　 ")
        assert anchors == []
        session.execute.assert_not_called()


def _session_local_mock(execute_side_effects):
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=execute_side_effects)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm), session


@pytest.mark.asyncio
class TestLocalSearch:
    async def test_entity_hit_collects_chunks(self):
        """子串锚定命中 → 邻居扩展 → chunk 回溯 → document_chunks 内容同构返回。"""
        session_local, session = _session_local_mock([
            # 1. 锚定实体（子串匹配命中）
            _FakeResult([{"id": "e1", "name": "报销", "entity_type": "concept"}]),
            # 2. 第 1 跳邻居
            _FakeResult([{"source_entity_id": "e1", "target_entity_id": "e2"}]),
            # 3. 第 2 跳邻居（无新增）
            _FakeResult([]),
            # 4. chunk 回溯
            _FakeResult([{"chunk_id": "c1", "doc_id": "d1"}, {"chunk_id": "c2", "doc_id": "d1"}]),
            # 5. document_chunks 内容
            _FakeResult([
                {"id": "c1", "document_id": "d1", "content": "报销流程说明", "page_number": 2, "image_ids": []},
                {"id": "c2", "document_id": "d1", "content": "报销额度规则", "page_number": 3, "image_ids": []},
            ]),
        ])
        with patch.object(retriever_module, "AsyncSessionLocal", session_local):
            results = await graph_retriever.local_search(QUERY, top_k=5)

        assert [r["chunk_id"] for r in results] == ["c1", "c2"]
        assert all(r["search_type"] == "graph" for r in results)
        assert results[0]["content"] == "报销流程说明"
        assert results[0]["page_number"] == 2
        assert results[0]["score"] > 0
        # 子串命中后不应触发 LLM 实体提取之外的调用（5 次 SQL 即全链路）
        assert session.execute.await_count == 5

    async def test_empty_table_returns_empty_list(self):
        """无锚定命中且 LLM 提取也为空 → 返回 []，不报错。"""
        session_local, session = _session_local_mock([_FakeResult([])])
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="")
        with patch.object(retriever_module, "AsyncSessionLocal", session_local), \
             patch.object(retriever_module, "llm_service", mock_llm):
            results = await graph_retriever.local_search("完全无关的问题", top_k=5)

        assert results == []

    async def test_llm_fallback_anchor(self):
        """子串未命中 → LLM 提取实体名 → 名归一化匹配命中。"""
        session_local, _ = _session_local_mock([
            _FakeResult([]),  # 子串未命中
            _FakeResult([{"id": "e9", "name": "差旅报销", "entity_type": "concept"}]),  # LLM 提取后命中
            _FakeResult([]),  # 第 1 跳无邻居
            _FakeResult([{"chunk_id": "c9", "doc_id": "d9"}]),
            _FakeResult([
                {"id": "c9", "document_id": "d9", "content": "差旅报销制度", "page_number": None, "image_ids": []},
            ]),
        ])
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="差旅报销")
        with patch.object(retriever_module, "AsyncSessionLocal", session_local), \
             patch.object(retriever_module, "llm_service", mock_llm):
            results = await graph_retriever.local_search("差旅怎么报销", top_k=5)

        assert [r["chunk_id"] for r in results] == ["c9"]
        mock_llm.generate.assert_awaited_once()

    async def test_db_error_returns_empty_list(self):
        """表不存在 / SQL 异常 → 返回 []，不抛出。"""
        session_local, _ = _session_local_mock([RuntimeError("relation kg_entities does not exist")])
        with patch.object(retriever_module, "AsyncSessionLocal", session_local):
            results = await graph_retriever.local_search(QUERY, top_k=5)
        assert results == []


@pytest.mark.asyncio
class TestGlobalSearch:
    async def test_communities_ranked_by_cosine(self):
        """社区 summary 按与 query 的 embedding 余弦排序取 top_k。"""
        session_local, _ = _session_local_mock([
            _FakeResult([
                {"id": "comm-1", "title": "报销制度", "summary": "各类报销流程与额度", "level": 0},
                {"id": "comm-2", "title": "考勤制度", "summary": "打卡与请假规则", "level": 0},
            ]),
        ])
        mock_embedding = MagicMock()
        mock_embedding.embed_query = AsyncMock(return_value=[1.0, 0.0])
        mock_embedding.embed_dense = AsyncMock(return_value=[[1.0, 0.0], [0.0, 1.0]])
        with patch.object(retriever_module, "AsyncSessionLocal", session_local), \
             patch.object(retriever_module, "embedding_service", mock_embedding):
            results = await graph_retriever.global_search(QUERY, top_k=1)

        assert len(results) == 1
        assert results[0]["chunk_id"] == "comm-1"
        assert results[0]["search_type"] == "graph_global"
        assert "报销流程与额度" in results[0]["content"]

    async def test_empty_communities_returns_empty_list(self):
        session_local, _ = _session_local_mock([_FakeResult([])])
        with patch.object(retriever_module, "AsyncSessionLocal", session_local):
            results = await graph_retriever.global_search(QUERY, top_k=3)
        assert results == []


# ============================================================================
# rag_pipeline.search() 图检索融合
# ============================================================================

@pytest.mark.asyncio
class TestSearchGraphFusion:
    def _pipeline_patches(self, cfg, retrieved, graph=None):
        mock_cfg_svc = MagicMock()
        mock_cfg_svc.resolve = AsyncMock(return_value=cfg)
        mock_embedding = MagicMock()
        mock_embedding.embed_query = AsyncMock(return_value=[0.1])
        mock_embedding.embed_query_sparse = AsyncMock(return_value={})
        mock_retrieval = MagicMock()
        mock_retrieval.retrieve = AsyncMock(return_value=retrieved)
        mock_reranker = MagicMock()
        mock_reranker.rerank = AsyncMock(
            side_effect=lambda q, chunks, top_k=None: chunks[:top_k]
        )
        mock_graph = MagicMock()
        graph = graph or {}
        mock_graph.local_search = AsyncMock(return_value=graph.get("local", []))
        mock_graph.global_search = AsyncMock(return_value=graph.get("global", []))
        patches = [
            patch.object(rag_pipeline_module, "retrieval_config_service", mock_cfg_svc),
            patch.object(rag_pipeline_module, "embedding_service", mock_embedding),
            patch.object(rag_pipeline_module, "retrieval_service", mock_retrieval),
            patch.object(rag_pipeline_module, "reranker_service", mock_reranker),
            patch.object(rag_pipeline_module, "graph_retriever", mock_graph),
        ]
        return patches, mock_graph, mock_reranker

    def _search_cfg(self, **overrides):
        cfg = {
            "enable_query_rewrite": False,
            "rerank_top_k": 5,
            "enable_keyword_search": True,
            "enable_vector_search": True,
            "enable_rerank": True,
            "similarity_threshold": 0.0,
            "enable_graph_rag": False,
            "graph_search_mode": "auto",
        }
        cfg.update(overrides)
        return cfg

    async def test_graph_disabled_no_graph_calls(self):
        """enable_graph_rag=False（默认）：不调图检索，行为与现状一致。"""
        patches, mock_graph, mock_reranker = self._pipeline_patches(
            self._search_cfg(enable_graph_rag=False), _chunks("c1"),
        )
        with _patch_stack(patches):
            result = await rag_pipeline_module.rag_pipeline.search(QUERY, top_k=5)

        mock_graph.local_search.assert_not_awaited()
        mock_graph.global_search.assert_not_awaited()
        assert [c["chunk_id"] for c in result["results"]] == ["c1"]

    async def test_graph_enabled_auto_merges_and_dedups(self):
        """auto 模式：local+global 并集融合，与向量结果按 chunk_id 去重后一起进 rerank。"""
        hybrid = _chunks("c1", "g1")  # g1 同时被向量与图检索命中
        graph = {
            "local": _chunks("g1", "g2", search_type="graph"),
            "global": [_chunks("g3", search_type="graph_global")[0]],
        }
        patches, mock_graph, mock_reranker = self._pipeline_patches(
            self._search_cfg(enable_graph_rag=True, graph_search_mode="auto"), hybrid, graph,
        )
        with _patch_stack(patches):
            result = await rag_pipeline_module.rag_pipeline.search(QUERY, top_k=10)

        mock_graph.local_search.assert_awaited_once()
        mock_graph.global_search.assert_awaited_once()
        # rerank 收到的候选：hybrid(c1,g1) + 图新增(g2,g3)，g1 不重复
        rerank_input_ids = [c["chunk_id"] for c in mock_reranker.rerank.call_args.args[1]]
        assert rerank_input_ids == ["c1", "g1", "g2", "g3"]
        result_ids = [c["chunk_id"] for c in result["results"]]
        assert result_ids.count("g1") == 1
        by_id = {c["chunk_id"]: c for c in result["results"]}
        assert by_id["g2"]["search_type"] == "graph"
        assert by_id["g3"]["search_type"] == "graph_global"

    async def test_graph_mode_local_only(self):
        """graph_search_mode=local：只调 local_search。"""
        patches, mock_graph, _ = self._pipeline_patches(
            self._search_cfg(enable_graph_rag=True, graph_search_mode="local"),
            _chunks("c1"),
            {"local": _chunks("g1", search_type="graph")},
        )
        with _patch_stack(patches):
            result = await rag_pipeline_module.rag_pipeline.search(QUERY, top_k=10)

        mock_graph.local_search.assert_awaited_once()
        mock_graph.global_search.assert_not_awaited()
        assert [c["chunk_id"] for c in result["results"]] == ["c1", "g1"]

    async def test_graph_results_survive_threshold(self):
        """图结果分数不可比，similarity_threshold 不过滤 search_type=graph* 的结果。"""
        patches, _, _ = self._pipeline_patches(
            self._search_cfg(
                enable_graph_rag=True, graph_search_mode="local",
                enable_rerank=False, similarity_threshold=0.8,
            ),
            [{"chunk_id": "c1", "document_id": "d1", "content": "x", "score": 0.3, "image_ids": []}],
            {"local": _chunks("g1", search_type="graph")},
        )
        with _patch_stack(patches):
            result = await rag_pipeline_module.rag_pipeline.search(QUERY, top_k=10)

        # 低分向量结果 c1 被过滤，图结果 g1 保留
        assert [c["chunk_id"] for c in result["results"]] == ["g1"]


# ============================================================================
# Agentic 工具调用循环
# ============================================================================

@pytest.mark.asyncio
class TestAgenticLoop:
    def _tool_call(self, query="报销流程", top_k=5, call_id="tc-1"):
        return {"name": "knowledge_search", "args": {"query": query, "top_k": top_k}, "id": call_id}

    async def test_agentic_tool_call_then_generate(self):
        """LLM 先请求工具再停止：tool_exec 累积 contexts，generate 用其生成。"""
        model = _fake_model([
            _ai_msg(tool_calls=[self._tool_call()]),
            _ai_msg(content="基于资料的回答"),
        ])
        patches = _agent_patches(_cfg(rag_mode="agentic"), _chunks("c1"))
        mocks = _mocks(patches)
        patches.append(patch.object(agent_nodes_module, "_resolve_chat_model", AsyncMock(return_value=model)))
        with _patch_stack(patches):
            result = await agent_graph.ainvoke(_state())

        # 固定管道被替代：rag_pipeline.search 仅被工具循环调用 1 次
        mocks.rag.search.assert_awaited_once()
        assert mocks.rag.search.await_args.kwargs["query"] == "报销流程"
        assert result["tool_call_count"] == 1
        # generate 走 generate_with_citations，contexts 来自工具累积
        mocks.llm.generate_with_citations.assert_called_once()
        kw = mocks.llm.generate_with_citations.call_args.kwargs
        assert [c["content"] for c in kw["contexts"]] == ["片段内容 c1"]
        assert result["response"] == "答案"
        # 图内未走 retrieve：llm.generate 仅 classify 一次
        assert mocks.llm.generate.await_count == 1

    async def test_agentic_no_tool_call_goes_straight_to_generate(self):
        """LLM 首轮即不调工具：跳过检索，按无片段直接生成。"""
        model = _fake_model([_ai_msg(content="直接回答")])
        patches = _agent_patches(_cfg(rag_mode="agentic"), _chunks("c1"))
        mocks = _mocks(patches)
        patches.append(patch.object(agent_nodes_module, "_resolve_chat_model", AsyncMock(return_value=model)))
        with _patch_stack(patches):
            result = await agent_graph.ainvoke(_state())

        mocks.rag.search.assert_not_awaited()
        mocks.llm.generate_with_citations.assert_not_called()
        mocks.llm.generate_stream.assert_called_once()
        assert result["tool_call_count"] == 0
        assert result["response"] == "答案"

    async def test_agentic_multi_round_accumulates(self):
        """两轮工具调用：contexts/citations 累积去重，tool_call_count=2。"""
        model = _fake_model([
            _ai_msg(tool_calls=[self._tool_call(call_id="tc-1")]),
            _ai_msg(tool_calls=[self._tool_call(query="报销额度", call_id="tc-2")]),
            _ai_msg(content="综合两轮资料回答"),
        ])
        patches = _agent_patches(_cfg(rag_mode="agentic"), [])
        mocks = _mocks(patches)
        mocks.rag.search = AsyncMock(side_effect=[
            {"results": _chunks("c1")},
            {"results": _chunks("c1", "c2")},  # c1 重复命中应去重
        ])
        patches.append(patch.object(agent_nodes_module, "_resolve_chat_model", AsyncMock(return_value=model)))
        with _patch_stack(patches):
            result = await agent_graph.ainvoke(_state())

        assert mocks.rag.search.await_count == 2
        assert result["tool_call_count"] == 2
        assert [c["chunk_id"] for c in result["contexts"]] == ["c1", "c2"]
        assert len(result["citations"]) == 2
        mocks.llm.generate_with_citations.assert_called_once()

    async def test_agentic_tool_call_limit_forces_generate(self):
        """LLM 持续请求工具：达到 MAX_TOOL_CALLS 后强制进入 generate。"""
        model = _fake_model([_ai_msg(tool_calls=[self._tool_call(call_id=f"tc-{i}")]) for i in range(10)])
        patches = _agent_patches(_cfg(rag_mode="agentic"), _chunks("c1"))
        mocks = _mocks(patches)
        patches.append(patch.object(agent_nodes_module, "_resolve_chat_model", AsyncMock(return_value=model)))
        with _patch_stack(patches):
            result = await agent_graph.ainvoke(_state())

        assert result["tool_call_count"] == MAX_TOOL_CALLS
        assert mocks.rag.search.await_count == MAX_TOOL_CALLS
        mocks.llm.generate_with_citations.assert_called_once()
        assert result["response"] == "答案"

    async def test_agentic_sse_sequence_matches_pipeline(self):
        """SSE 兼容：事件序列与 pipeline 模式一致（citations→images→text→content_blocks→done），
        工具调用过程不产生新事件类型。"""
        model = _fake_model([
            _ai_msg(tool_calls=[self._tool_call()]),
            _ai_msg(content="基于资料的回答"),
        ])
        patches = _agent_patches(_cfg(rag_mode="agentic"), _chunks("c1", with_images=True))
        patches.append(patch.object(agent_nodes_module, "_resolve_chat_model", AsyncMock(return_value=model)))
        with _patch_stack(patches):
            events = [e async for e in agent_service.chat(query=QUERY, user_id="u1")]

        assert [e["type"] for e in events] == [
            "citations", "images", "text", "text", "content_blocks", "done",
        ]
        assert events[2]["data"] == "答"
        assert events[3]["data"] == "案"

    async def test_pipeline_mode_untouched_by_agentic_nodes(self):
        """rag_mode=pipeline（默认）：不经过 agent_reason，行为与上轮一致。"""
        model = _fake_model([_ai_msg(content="不应被调用")])
        patches = _agent_patches(_cfg(rag_mode="pipeline"), _chunks("c1"))
        mocks = _mocks(patches)
        patches.append(patch.object(agent_nodes_module, "_resolve_chat_model", AsyncMock(return_value=model)))
        with _patch_stack(patches):
            result = await agent_graph.ainvoke(_state())

        mocks.rag.search.assert_awaited_once()  # 固定 retrieve 节点
        model.bind_tools.assert_not_called()
        assert result["tool_call_count"] == 0
        assert result["response"] == "答案"
