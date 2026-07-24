"""Tests for system retrieval config service + reranker（settings 直读）。

模型类配置（reranker_model/base_url/api_key、embedding_*）已收回 config.py 系统级
维护，retrieval_config 只保留检索策略键；reranker 直读 settings（RERANK_MODEL /
RERANK_BASE_URL or MODEL_BASE_URL / DASHSCOPE_API_KEY），未配置按 score 截断降级。
"""

from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.db.models import SystemRetrievalConfig
from app.db.repository import RetrievalConfigRepository
from app.models.schemas import RetrievalConfigUpdate
from app.services.retrieval_config_service import RetrievalConfigService
from app.core.knowledge import reranker as reranker_module
from app.core.knowledge.reranker import reranker_service
from app.core.knowledge import rag_pipeline

settings = get_settings()


def _make_row(**overrides):
    """构造一个 system_retrieval_config 行的 mock（默认全 NULL = 回落内置默认）。"""
    row = SimpleNamespace(
        id="cfg-1",
        rerank_top_k=None,
        similarity_threshold=None,
        enable_query_rewrite=None,
        enable_keyword_search=None,
        enable_vector_search=None,
        enable_rerank=None,
        rag_mode=None,
        enable_graph_rag=None,
        graph_search_mode=None,
    )
    for k, v in overrides.items():
        setattr(row, k, v)
    return row


async def _cache_passthrough(key, factory, ttl=300, prefix=None):
    """跳过 Redis，直接执行 factory。"""
    return await factory()


def _mock_session_local():
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=AsyncMock())
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


def _default_cfg(**overrides):
    cfg = {
        "rerank_top_k": 5,
        "similarity_threshold": 0.0,
        "enable_query_rewrite": False,
        "enable_keyword_search": True,
        "enable_vector_search": True,
        "enable_rerank": False,
    }
    cfg.update(overrides)
    return cfg


def _mock_http_client(results=None, side_effect=None):
    """构造 mock httpx.AsyncClient：post 返回 Cohere/Jina 通用形状的 rerank 响应。"""
    client = MagicMock()
    if side_effect is not None:
        client.post = AsyncMock(side_effect=side_effect)
    else:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"results": results if results is not None else []})
        client.post = AsyncMock(return_value=resp)
    return client


def _set_reranker_settings(monkeypatch, **overrides):
    """覆盖 reranker 模块内 settings 的字段，并重置懒加载 client。"""
    base = {
        "RERANK_MODEL": "qwen3-rerank",
        "RERANK_BASE_URL": "",
        "MODEL_BASE_URL": "https://maas.example.com/v1",
        "DASHSCOPE_API_KEY": "sk-test",
    }
    base.update(overrides)
    for key, value in base.items():
        monkeypatch.setattr(reranker_module.settings, key, value)
    reranker_service._client = None


@pytest.mark.asyncio
class TestResolve:
    async def test_resolve_without_db_row_falls_back_to_defaults(self):
        """无 DB 行时回落内置默认（仅检索策略键）。"""
        with patch("app.services.retrieval_config_service.cache_get_or_set", side_effect=_cache_passthrough), \
             patch("app.services.retrieval_config_service.AsyncSessionLocal", _mock_session_local()), \
             patch("app.services.retrieval_config_service.retrieval_config_repo") as mock_repo:
            mock_repo.get_singleton = AsyncMock(return_value=None)
            cfg = await RetrievalConfigService.resolve()

        assert cfg["rerank_top_k"] == settings.RAG_RERANK_TOP_K
        assert cfg["similarity_threshold"] == 0.0
        assert cfg["enable_query_rewrite"] == settings.RAG_ENABLE_QUERY_REWRITE
        assert cfg["enable_rerank"] == settings.RAG_ENABLE_RERANK
        assert cfg["rag_mode"] == "pipeline"
        assert cfg["enable_graph_rag"] is False
        assert cfg["graph_search_mode"] == "auto"
        # 模型类配置已收回 config.py，不再出现在检索配置里
        assert "reranker_model" not in cfg
        assert "embedding_model" not in cfg

    async def test_resolve_with_db_row_overrides(self):
        """DB 行非 NULL 字段覆盖内置默认。"""
        row = _make_row(rerank_top_k=8, enable_rerank=False, similarity_threshold=0.3)
        with patch("app.services.retrieval_config_service.cache_get_or_set", side_effect=_cache_passthrough), \
             patch("app.services.retrieval_config_service.AsyncSessionLocal", _mock_session_local()), \
             patch("app.services.retrieval_config_service.retrieval_config_repo") as mock_repo:
            mock_repo.get_singleton = AsyncMock(return_value=row)
            cfg = await RetrievalConfigService.resolve()

        assert cfg["rerank_top_k"] == 8
        assert cfg["enable_rerank"] is False
        assert cfg["similarity_threshold"] == 0.3

    async def test_get_for_api_keys(self):
        row = _make_row(rerank_top_k=7)
        with patch("app.services.retrieval_config_service.cache_get_or_set", side_effect=_cache_passthrough), \
             patch("app.services.retrieval_config_service.AsyncSessionLocal", _mock_session_local()), \
             patch("app.services.retrieval_config_service.retrieval_config_repo") as mock_repo:
            mock_repo.get_singleton = AsyncMock(return_value=row)
            data = await RetrievalConfigService.get_for_api()

        assert data["rerank_top_k"] == 7
        assert set(data.keys()) == {
            "rerank_top_k", "similarity_threshold",
            "enable_query_rewrite", "enable_keyword_search", "enable_vector_search", "enable_rerank",
            "rag_mode", "enable_graph_rag", "graph_search_mode",
        }


@pytest.mark.asyncio
class TestSave:
    async def test_save_upserts_and_invalidates_cache(self):
        """save() 写库后应清除缓存。"""
        data = _default_cfg(rerank_top_k=9)
        with patch("app.services.retrieval_config_service.AsyncSessionLocal", _mock_session_local()), \
             patch("app.services.retrieval_config_service.retrieval_config_repo") as mock_repo, \
             patch("app.services.retrieval_config_service.cache_delete", new=AsyncMock()) as mock_del, \
             patch.object(RetrievalConfigService, "get_for_api", new=AsyncMock(return_value={})):
            mock_repo.get_singleton = AsyncMock(return_value=None)
            mock_repo.upsert = AsyncMock()
            await RetrievalConfigService.save(data)

        mock_repo.upsert.assert_awaited_once()
        saved = mock_repo.upsert.call_args.args[1]
        assert saved.rerank_top_k == 9
        mock_del.assert_awaited_once_with("retrieval_config:system", prefix="")


@pytest.mark.asyncio
class TestRepositoryUpsertGraphKeys:
    """bug A 回归：upsert 更新已有配置行时 rag_mode / enable_graph_rag / graph_search_mode 必须生效。

    历史上 UPDATABLE_FIELDS 缺这三键，已有行 save() 后三键保持旧值不更新。
    """

    async def test_upsert_updates_graph_keys_on_existing_row(self):
        repo = RetrievalConfigRepository()
        existing = SystemRetrievalConfig(
            rerank_top_k=5,
            similarity_threshold=0.0,
            enable_query_rewrite=False,
            enable_keyword_search=True,
            enable_vector_search=True,
            enable_rerank=False,
            rag_mode="pipeline",
            enable_graph_rag=False,
            graph_search_mode="auto",
        )
        new_config = SystemRetrievalConfig(
            rerank_top_k=10,
            similarity_threshold=0.5,
            enable_query_rewrite=True,
            enable_keyword_search=False,
            enable_vector_search=True,
            enable_rerank=True,
            rag_mode="agentic",
            enable_graph_rag=True,
            graph_search_mode="local",
        )
        session = AsyncMock()
        with patch.object(repo, "get_singleton", new=AsyncMock(return_value=existing)):
            result = await repo.upsert(session, new_config)

        assert result is existing
        assert existing.rag_mode == "agentic"
        assert existing.enable_graph_rag is True
        assert existing.graph_search_mode == "local"
        # 原有可更新字段不受影响
        assert existing.rerank_top_k == 10


class TestSearchSwitchValidation:
    """双关校验：向量检索与关键词检索不能同时关闭（API 层 422 语义来自 schema 校验）。"""

    def test_both_search_disabled_rejected(self):
        with pytest.raises(ValidationError, match="向量检索与关键词检索不能同时关闭"):
            RetrievalConfigUpdate(enable_keyword_search=False, enable_vector_search=False)

    def test_single_search_enabled_accepted(self):
        assert RetrievalConfigUpdate(enable_keyword_search=False).enable_vector_search is True
        assert RetrievalConfigUpdate(enable_vector_search=False).enable_keyword_search is True
        assert RetrievalConfigUpdate().enable_keyword_search is True


@pytest.mark.asyncio
class TestRerankerSettings:
    """通用 HTTP rerank 端点（settings 直读）：请求形状 / 重排正确性 / 失败降级 / 未配置降级。"""

    async def test_http_request_shape_and_reorder(self, monkeypatch):
        """POST {base_url}/rerank，body 为通用形状（model/query/documents/top_n），按 results 重排。"""
        _set_reranker_settings(
            monkeypatch, RERANK_BASE_URL="https://rerank.example.com/v1", DASHSCOPE_API_KEY="cfg-key-xyz",
        )
        chunks = [
            {"chunk_id": "c1", "content": "甲", "score": 0.1},
            {"chunk_id": "c2", "content": "乙", "score": 0.9},
        ]
        mock_client = _mock_http_client(results=[
            {"index": 1, "relevance_score": 0.95},
            {"index": 0, "relevance_score": 0.3},
        ])
        with patch("app.core.knowledge.reranker.httpx.AsyncClient", return_value=mock_client) as mock_ctor:
            out = await reranker_service.rerank("q", chunks, top_k=2)

        # client 按 settings 懒加载构建，带 Bearer 头与 30s 超时
        mock_ctor.assert_called_once()
        ctor_kwargs = mock_ctor.call_args.kwargs
        assert ctor_kwargs["headers"]["Authorization"] == "Bearer cfg-key-xyz"
        assert ctor_kwargs["timeout"] == 30.0

        # base_url 未以 /rerank 结尾 → 拼接 /rerank
        post_kwargs = mock_client.post.call_args.kwargs
        assert mock_client.post.call_args.args[0] == "https://rerank.example.com/v1/rerank"
        assert post_kwargs["json"] == {
            "model": "qwen3-rerank",
            "query": "q",
            "documents": ["甲", "乙"],
            "top_n": 2,
        }

        # 按 rerank 结果重排并重打分
        assert [c["chunk_id"] for c in out] == ["c2", "c1"]
        assert out[0]["score"] == 0.95
        assert all(c["search_type"] == "rerank" for c in out)

    async def test_rerank_base_url_empty_uses_model_base_url(self, monkeypatch):
        """RERANK_BASE_URL 为空时回落 MODEL_BASE_URL。"""
        _set_reranker_settings(monkeypatch, MODEL_BASE_URL="https://maas.example.com/v1")
        chunks = [{"chunk_id": "c1", "content": "甲", "score": 0.1}]
        mock_client = _mock_http_client(results=[{"index": 0, "relevance_score": 0.9}])
        with patch("app.core.knowledge.reranker.httpx.AsyncClient", return_value=mock_client):
            await reranker_service.rerank("q", chunks, top_k=1)
        assert mock_client.post.call_args.args[0] == "https://maas.example.com/v1/rerank"

    async def test_base_url_ending_with_rerank_not_appended(self):
        """base_url 已以 /rerank 结尾时不重复拼接。"""
        assert reranker_service._endpoint("https://api.jina.ai/v1/rerank") == "https://api.jina.ai/v1/rerank"
        assert reranker_service._endpoint("https://api.jina.ai/v1/rerank/") == "https://api.jina.ai/v1/rerank"
        assert reranker_service._endpoint("https://rerank.example.com/v1") == "https://rerank.example.com/v1/rerank"

    async def test_rerank_preserves_existing_search_type(self, monkeypatch):
        """rerank 不覆写已有 search_type（graph 结果豁免 similarity_threshold 的依据）。"""
        _set_reranker_settings(monkeypatch)
        chunks = [
            {"chunk_id": "g1", "content": "图检索结果", "score": 0.99, "search_type": "graph"},
            {"chunk_id": "c1", "content": "向量结果", "score": 0.1},
        ]
        mock_client = _mock_http_client(results=[
            {"index": 0, "relevance_score": 0.05},
            {"index": 1, "relevance_score": 0.9},
        ])
        with patch("app.core.knowledge.reranker.httpx.AsyncClient", return_value=mock_client):
            out = await reranker_service.rerank("q", chunks, top_k=2)

        by_id = {c["chunk_id"]: c for c in out}
        assert by_id["g1"]["search_type"] == "graph"  # 已有值保留，不被覆写为 rerank
        assert by_id["c1"]["search_type"] == "rerank"  # 缺失时才标记 rerank
        assert by_id["g1"]["score"] == 0.05  # 分数仍按 rerank 结果重打

    async def test_http_failure_falls_back_to_score_truncate(self, monkeypatch):
        """HTTP 调用失败：记 warning 并按原 score 截断降级（rerank 失败不该让问答失败）。"""
        _set_reranker_settings(monkeypatch)
        chunks = [
            {"chunk_id": "c1", "content": "甲", "score": 0.1},
            {"chunk_id": "c2", "content": "乙", "score": 0.9},
            {"chunk_id": "c3", "content": "丙", "score": 0.5},
        ]
        mock_client = _mock_http_client(side_effect=Exception("connection refused"))
        with patch("app.core.knowledge.reranker.httpx.AsyncClient", return_value=mock_client):
            out = await reranker_service.rerank("q", chunks, top_k=2)
        assert [c["chunk_id"] for c in out] == ["c2", "c3"]

    async def test_http_error_status_falls_back_to_score_truncate(self, monkeypatch):
        """HTTP 4xx/5xx（raise_for_status 抛错）同样按 score 截断降级。"""
        _set_reranker_settings(monkeypatch)
        chunks = [
            {"chunk_id": "c1", "content": "甲", "score": 0.1},
            {"chunk_id": "c2", "content": "乙", "score": 0.9},
        ]
        resp = MagicMock()
        resp.raise_for_status = MagicMock(side_effect=Exception("401 Unauthorized"))
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=resp)
        with patch("app.core.knowledge.reranker.httpx.AsyncClient", return_value=mock_client):
            out = await reranker_service.rerank("q", chunks, top_k=1)
        assert [c["chunk_id"] for c in out] == ["c2"]

    async def test_missing_api_key_degrades_to_score_truncate(self, monkeypatch):
        """DASHSCOPE_API_KEY 未配置 → warning 降级，按原 score 截断（不阻断问答）。"""
        _set_reranker_settings(monkeypatch, DASHSCOPE_API_KEY="")
        chunks = [
            {"chunk_id": "c1", "content": "甲", "score": 0.1},
            {"chunk_id": "c2", "content": "乙", "score": 0.9},
        ]
        with patch("app.core.knowledge.reranker.httpx.AsyncClient") as mock_ctor:
            out = await reranker_service.rerank("q", chunks, top_k=1)
        mock_ctor.assert_not_called()  # 未配置不发 HTTP 请求
        assert [c["chunk_id"] for c in out] == ["c2"]

    async def test_missing_model_degrades_to_score_truncate(self, monkeypatch):
        """RERANK_MODEL 为空 → 同样降级截断。"""
        _set_reranker_settings(monkeypatch, RERANK_MODEL="")
        chunks = [
            {"chunk_id": "c1", "content": "甲", "score": 0.1},
            {"chunk_id": "c2", "content": "乙", "score": 0.9},
        ]
        with patch("app.core.knowledge.reranker.httpx.AsyncClient") as mock_ctor:
            out = await reranker_service.rerank("q", chunks, top_k=1)
        mock_ctor.assert_not_called()
        assert [c["chunk_id"] for c in out] == ["c2"]


@pytest.mark.asyncio
class TestSearchThresholdFilter:
    def _patch_pipeline(self, cfg, retrieved):
        mock_cfg_svc = MagicMock()
        mock_cfg_svc.resolve = AsyncMock(return_value=cfg)
        mock_embedding = MagicMock()
        mock_embedding.embed_query = AsyncMock(return_value=[0.1])
        mock_embedding.embed_query_sparse = AsyncMock(return_value={})
        mock_retrieval = MagicMock()
        mock_retrieval.retrieve = AsyncMock(return_value=retrieved)
        mock_reranker = MagicMock()
        mock_reranker.rerank = AsyncMock(side_effect=lambda q, c, top_k=None: c[:top_k])
        return [
            patch("app.core.knowledge.rag_pipeline.retrieval_config_service", mock_cfg_svc),
            patch("app.core.knowledge.rag_pipeline.embedding_service", mock_embedding),
            patch("app.core.knowledge.rag_pipeline.retrieval_service", mock_retrieval),
            patch("app.core.knowledge.rag_pipeline.reranker_service", mock_reranker),
        ]

    async def test_threshold_above_zero_filters_low_scores(self):
        """similarity_threshold > 0 时过滤低分结果。"""
        retrieved = [
            {"chunk_id": "c1", "document_id": "d1", "content": "甲", "score": 0.9, "image_ids": []},
            {"chunk_id": "c2", "document_id": "d1", "content": "乙", "score": 0.5, "image_ids": []},
            {"chunk_id": "c3", "document_id": "d1", "content": "丙", "score": 0.2, "image_ids": []},
        ]
        cfg = _default_cfg(similarity_threshold=0.4)
        patches = self._patch_pipeline(cfg, retrieved)
        for p in patches:
            p.start()
        try:
            result = await rag_pipeline.rag_pipeline.search("q", top_k=5)
        finally:
            for p in patches:
                p.stop()
        assert [c["chunk_id"] for c in result["results"]] == ["c1", "c2"]

    async def test_threshold_zero_keeps_all(self):
        """similarity_threshold = 0 时不过滤（与改造前行为一致）。"""
        retrieved = [
            {"chunk_id": "c1", "document_id": "d1", "content": "甲", "score": 0.9, "image_ids": []},
            {"chunk_id": "c2", "document_id": "d1", "content": "乙", "score": 0.2, "image_ids": []},
        ]
        cfg = _default_cfg(similarity_threshold=0.0)
        patches = self._patch_pipeline(cfg, retrieved)
        for p in patches:
            p.start()
        try:
            result = await rag_pipeline.rag_pipeline.search("q", top_k=5)
        finally:
            for p in patches:
                p.stop()
        assert [c["chunk_id"] for c in result["results"]] == ["c1", "c2"]

    async def test_top_k_none_uses_config_rerank_top_k(self):
        """top_k 未显式传入时使用配置的 rerank_top_k。"""
        retrieved = [
            {"chunk_id": f"c{i}", "document_id": "d1", "content": "x", "score": 0.9 - i * 0.1, "image_ids": []}
            for i in range(10)
        ]
        cfg = _default_cfg(rerank_top_k=3)
        patches = self._patch_pipeline(cfg, retrieved)
        for p in patches:
            p.start()
        try:
            result = await rag_pipeline.rag_pipeline.search("q")
        finally:
            for p in patches:
                p.stop()
        assert len(result["results"]) == 3

    async def test_graph_results_exempt_from_threshold_after_rerank(self, monkeypatch):
        """图结果经真实 reranker 重打分后仍保留 search_type=graph，豁免 similarity_threshold。

        回归测试：reranker 曾无条件把 search_type 覆写为 "rerank"，导致图结果被阈值误杀。
        """
        _set_reranker_settings(monkeypatch)
        retrieved = [
            {"chunk_id": "c1", "document_id": "d1", "content": "向量片段", "score": 0.9, "image_ids": []},
            {"chunk_id": "g1", "document_id": "d1", "content": "图片段", "score": 0.99,
             "search_type": "graph", "image_ids": []},
        ]
        cfg = _default_cfg(enable_rerank=True, similarity_threshold=0.5)
        mock_client = _mock_http_client(results=[
            {"index": 0, "relevance_score": 0.6},
            {"index": 1, "relevance_score": 0.1},  # 图结果被 rerank 打到低分
        ])
        mock_cfg_svc = MagicMock()
        mock_cfg_svc.resolve = AsyncMock(return_value=cfg)
        mock_embedding = MagicMock()
        mock_embedding.embed_query = AsyncMock(return_value=[0.1])
        mock_embedding.embed_query_sparse = AsyncMock(return_value={})
        mock_retrieval = MagicMock()
        mock_retrieval.retrieve = AsyncMock(return_value=retrieved)
        patches = [
            patch("app.core.knowledge.rag_pipeline.retrieval_config_service", mock_cfg_svc),
            patch("app.core.knowledge.rag_pipeline.embedding_service", mock_embedding),
            patch("app.core.knowledge.rag_pipeline.retrieval_service", mock_retrieval),
            patch("app.core.knowledge.rag_pipeline.reranker_service", reranker_service),  # 真实 reranker
            patch("app.core.knowledge.reranker.httpx.AsyncClient", return_value=mock_client),
        ]
        for p in patches:
            p.start()
        try:
            result = await rag_pipeline.rag_pipeline.search("q", top_k=5)
        finally:
            for p in patches:
                p.stop()

        by_id = {c["chunk_id"]: c for c in result["results"]}
        # c1（0.6 >= 0.5）保留；g1（0.1 < 0.5）因 search_type=graph 豁免而保留
        assert set(by_id) == {"c1", "g1"}
        assert by_id["g1"]["search_type"] == "graph"
