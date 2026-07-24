"""Tests for GraphRAG 入库侧：extraction 解析/归一、builder 幂等与社区检测。

全部不连真实 PG / Milvus / LLM：langextract 与 repository 均 mock。
"""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import langextract as lx

from app.core.knowledge.graph import builder, extraction
from app.core.knowledge.graph.extraction import Entity, Relation, normalize_entity_name


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _lx_extraction(ext_class, text, **attrs):
    return lx.data.Extraction(extraction_class=ext_class, extraction_text=text, attributes=attrs)


def _make_session_patch():
    """返回 (session_mock, AsyncSessionLocal 替代工厂)。"""
    session = AsyncMock()
    begin_cm = MagicMock()
    begin_cm.__aenter__ = AsyncMock(return_value=None)
    begin_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin_cm)

    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)
    return session, MagicMock(return_value=session_cm)


def _fake_entity(eid, name, entity_type="组织", description=""):
    return SimpleNamespace(id=eid, name=name, entity_type=entity_type, description=description)


def _fake_relation(src, tgt, weight=1.0):
    return SimpleNamespace(source_entity_id=src, target_entity_id=tgt, weight=weight)


# ---------------------------------------------------------------------------
# 实体归一
# ---------------------------------------------------------------------------

class TestNormalizeEntityName:
    def test_case_fold(self):
        assert normalize_entity_name("DeepSeek") == "deepseek"

    def test_whitespace_removed(self):
        assert normalize_entity_name("阿里 巴巴\t集团\n") == "阿里巴巴集团"

    def test_fullwidth_to_halfwidth(self):
        # NFKC 全角转半角 + 大小写折叠
        assert normalize_entity_name("ＡＩ平台") == "ai平台"

    def test_empty(self):
        assert normalize_entity_name("") == ""
        assert normalize_entity_name(None) == ""


# ---------------------------------------------------------------------------
# extraction：解析 / 合并 / 异常容忍
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestExtractEntitiesRelations:
    async def test_parse_via_lx_extract(self):
        """mock lx.extract 返回 AnnotatedDocument，验证解析出实体与关系。"""
        fake_doc = lx.data.AnnotatedDocument(
            extractions=[
                _lx_extraction("entity", "阿里巴巴", entity_type="组织", description="科技公司"),
                _lx_extraction("entity", "通义千问", entity_type="产品", description="大模型"),
                _lx_extraction(
                    "relation",
                    "阿里巴巴发布了通义千问",
                    source="阿里巴巴", target="通义千问",
                    relation_type="发布", description="阿里巴巴发布通义千问",
                ),
            ]
        )
        chunks = [{"chunk_id": "c1", "content": "阿里巴巴发布了通义千问。"}]
        with patch.object(extraction, "_get_model_config", return_value=MagicMock()), \
             patch.object(extraction.lx, "extract", return_value=fake_doc) as mock_extract:
            entities, relations = await extraction.extract_entities_relations(chunks)

        # langextract 调用方式：fence 输出 + 关闭 schema 约束（OpenAI 兼容端点）
        kwargs = mock_extract.call_args.kwargs
        assert kwargs["fence_output"] is True
        assert kwargs["use_schema_constraints"] is False

        assert [(e.name, e.entity_type) for e in entities] == [("阿里巴巴", "组织"), ("通义千问", "产品")]
        assert entities[0].chunk_ids == ["c1"]
        assert entities[0].name_normalized == "阿里巴巴"
        assert len(relations) == 1
        rel = relations[0]
        assert (rel.source_normalized, rel.target_normalized, rel.relation_type) == ("阿里巴巴", "通义千问", "发布")
        assert rel.chunk_id == "c1"

    async def test_entity_merge_across_chunks(self):
        """跨 chunk 同名实体（大小写/空白/全半角差异）应合并，chunk_ids 去重合并。"""
        side_effect = [
            [_lx_extraction("entity", "DeepSeek", entity_type="组织", description="短描述")],
            [_lx_extraction("entity", "deep seek", entity_type="组织", description="更长的描述信息")],
        ]
        chunks = [
            {"chunk_id": "c1", "content": "第一段"},
            {"chunk_id": "c2", "content": "第二段"},
        ]
        with patch.object(extraction, "_extract_chunk_sync", side_effect=side_effect):
            entities, relations = await extraction.extract_entities_relations(chunks)

        assert len(entities) == 1
        ent = entities[0]
        assert ent.name_normalized == "deepseek"
        assert ent.chunk_ids == ["c1", "c2"]
        assert ent.description == "更长的描述信息"  # 取最长描述
        assert relations == []

    async def test_relation_merge_accumulates_weight(self):
        """同一 (source, target, relation_type) 多次出现时权重累加。"""
        side_effect = [
            [_lx_extraction("relation", "A投资B", source="公司A", target="公司B", relation_type="投资", description="x")],
            [_lx_extraction("relation", "A投资B", source="公司 A", target="公司B", relation_type="投资", description="y")],
        ]
        chunks = [{"chunk_id": "c1", "content": "一"}, {"chunk_id": "c2", "content": "二"}]
        with patch.object(extraction, "_extract_chunk_sync", side_effect=side_effect):
            _, relations = await extraction.extract_entities_relations(chunks)

        assert len(relations) == 1
        assert relations[0].weight == 2.0

    async def test_chunk_failure_does_not_block_others(self):
        """单 chunk 抽取抛异常时跳过该 chunk，其余正常处理。"""
        side_effect = [
            RuntimeError("LLM 超时"),
            [_lx_extraction("entity", "阿里云", entity_type="组织", description="云计算")],
        ]
        chunks = [{"chunk_id": "bad", "content": "会失败的 chunk"}, {"chunk_id": "ok", "content": "正常 chunk"}]
        with patch.object(extraction, "_extract_chunk_sync", side_effect=side_effect):
            entities, relations = await extraction.extract_entities_relations(chunks)

        assert [e.name for e in entities] == ["阿里云"]
        assert entities[0].chunk_ids == ["ok"]

    async def test_empty_content_skipped(self):
        chunks = [{"chunk_id": "c1", "content": "  "}]
        with patch.object(extraction, "_extract_chunk_sync") as mock_sync:
            entities, relations = await extraction.extract_entities_relations(chunks)
        mock_sync.assert_not_called()
        assert entities == [] and relations == []


# ---------------------------------------------------------------------------
# builder：build_document_graph 幂等
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestBuildDocumentGraph:
    def _mock_repo(self):
        repo = AsyncMock()

        async def _upsert(session, *, name, name_normalized, **kwargs):
            return SimpleNamespace(id=f"ent-{name_normalized}", name=name)

        repo.upsert_entity = AsyncMock(side_effect=_upsert)
        return repo

    def _extract_result(self):
        entities = [
            Entity(name="阿里巴巴", entity_type="组织", description="科技公司",
                   name_normalized="阿里巴巴", chunk_ids=["c1"]),
            Entity(name="通义千问", entity_type="产品", description="大模型",
                   name_normalized="通义千问", chunk_ids=["c1", "c2"]),
        ]
        relations = [
            Relation(source_name="阿里巴巴", target_name="通义千问", relation_type="发布",
                     description="d", weight=1.0, chunk_id="c1",
                     source_normalized="阿里巴巴", target_normalized="通义千问"),
            #  dangling：目标未被抽为实体，应被丢弃
            Relation(source_name="阿里巴巴", target_name="不存在实体", relation_type="相关",
                     description="", weight=1.0, chunk_id="c1",
                     source_normalized="阿里巴巴", target_normalized="不存在实体"),
        ]
        return entities, relations

    async def test_build_writes_entities_relations_links(self):
        repo = self._mock_repo()
        session, session_factory = _make_session_patch()
        chunks = [{"chunk_id": "c1", "content": "x"}, {"chunk_id": "c2", "content": "y"}]

        with patch.object(builder, "kg_repo", repo), \
             patch.object(builder, "AsyncSessionLocal", session_factory), \
             patch.object(builder, "extract_entities_relations",
                          AsyncMock(return_value=self._extract_result())):
            stats = await builder.build_document_graph("doc-1", chunks)

        assert stats == {"entities": 2, "relations": 1}
        # 先清理旧图谱
        repo.remove_document_graph.assert_awaited_once_with(
            session, document_id="doc-1", chunk_ids=["c1", "c2"]
        )
        # 实体 upsert 带 chunk_delta
        upsert_kwargs = [c.kwargs for c in repo.upsert_entity.await_args_list]
        assert {k["name_normalized"] for k in upsert_kwargs} == {"阿里巴巴", "通义千问"}
        assert next(k for k in upsert_kwargs if k["name"] == "通义千问")["chunk_delta"] == 2
        # chunk-entity 关联：c1 挂 2 实体，c2 挂 1 实体
        assert repo.link_chunk_entity.await_count == 3
        link_doc_ids = {c.kwargs["doc_id"] for c in repo.link_chunk_entity.await_args_list}
        assert link_doc_ids == {"doc-1"}
        # dangling 关系被丢弃
        repo.add_relation.assert_awaited_once()
        rel_kwargs = repo.add_relation.await_args.kwargs
        assert rel_kwargs["source_entity_id"] == "ent-阿里巴巴"
        assert rel_kwargs["target_entity_id"] == "ent-通义千问"
        assert rel_kwargs["chunk_id"] == "c1"

    async def test_rebuild_cleans_previous_graph_first(self):
        """重复构建同一文档：每次先 remove_document_graph 再写入（幂等）。"""
        repo = self._mock_repo()
        _, session_factory = _make_session_patch()
        chunks = [{"chunk_id": "c1", "content": "x"}]

        with patch.object(builder, "kg_repo", repo), \
             patch.object(builder, "AsyncSessionLocal", session_factory), \
             patch.object(builder, "extract_entities_relations",
                          AsyncMock(return_value=self._extract_result())):
            await builder.build_document_graph("doc-1", chunks)
            await builder.build_document_graph("doc-1", chunks)

        assert repo.remove_document_graph.await_count == 2
        assert repo.upsert_entity.await_count == 4
        call_names = [c[0] for c in repo.mock_calls]
        # 第二次构建同样是先清理后写入
        second_remove = len(call_names) - 1 - call_names[::-1].index("remove_document_graph")
        last_upsert = len(call_names) - 1 - call_names[::-1].index("upsert_entity")
        assert second_remove < last_upsert


# ---------------------------------------------------------------------------
# builder：rebuild_communities（louvain 分组 / 退化 / 防抖）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRebuildCommunities:
    def _two_cluster_graph(self):
        entities = [_fake_entity(f"e{i}", f"实体{i}") for i in range(1, 7)]
        relations = [
            _fake_relation("e1", "e2"), _fake_relation("e2", "e3"), _fake_relation("e1", "e3"),
            _fake_relation("e4", "e5"), _fake_relation("e5", "e6"), _fake_relation("e4", "e6"),
        ]
        return entities, relations

    async def test_skip_when_too_few_entities(self):
        repo = AsyncMock()
        repo.list_entities = AsyncMock(return_value=[_fake_entity(f"e{i}", f"实体{i}") for i in range(4)])
        repo.list_relations = AsyncMock(return_value=[])
        _, session_factory = _make_session_patch()

        with patch.object(builder, "kg_repo", repo), \
             patch.object(builder, "AsyncSessionLocal", session_factory):
            result = await builder.rebuild_communities()

        assert result["status"] == "skipped"
        assert result["reason"] == "too_few_entities"
        repo.replace_communities.assert_not_called()

    async def test_louvain_groups_two_clusters(self):
        entities, relations = self._two_cluster_graph()
        repo = AsyncMock()
        repo.list_entities = AsyncMock(return_value=entities)
        repo.list_relations = AsyncMock(return_value=relations)
        _, session_factory = _make_session_patch()

        with patch.object(builder, "kg_repo", repo), \
             patch.object(builder, "AsyncSessionLocal", session_factory), \
             patch.object(builder, "cache_get", AsyncMock(return_value=None)), \
             patch.object(builder, "cache_set", AsyncMock()), \
             patch.object(builder, "_summarize_community", AsyncMock(return_value=("标题", "摘要"))):
            result = await builder.rebuild_communities()

        assert result["status"] == "rebuilt"
        assert result["communities"] == 2
        rows = repo.replace_communities.await_args.args[1]
        assert len(rows) == 2
        assert sorted(r["entity_count"] for r in rows) == [3, 3]
        all_ids = sorted(i for r in rows for i in r["entity_ids"])
        assert all_ids == [f"e{i}" for i in range(1, 7)]
        assert all(r["level"] == 0 and r["title"] == "标题" for r in rows)

    async def test_debounce_skips_recent_rebuild(self):
        """距上次 <60s 且实体数变化 <10%：跳过。"""
        entities, relations = self._two_cluster_graph()
        repo = AsyncMock()
        repo.list_entities = AsyncMock(return_value=entities)
        repo.list_relations = AsyncMock(return_value=relations)
        _, session_factory = _make_session_patch()

        cache_state = {
            builder._CACHE_KEY_LAST_AT: time.time(),
            builder._CACHE_KEY_LAST_COUNT: 6,
        }

        async def _cache_get(key):
            return cache_state.get(key)

        with patch.object(builder, "kg_repo", repo), \
             patch.object(builder, "AsyncSessionLocal", session_factory), \
             patch.object(builder, "cache_get", side_effect=_cache_get), \
             patch.object(builder, "cache_set", AsyncMock()):
            result = await builder.rebuild_communities()

        assert result["status"] == "skipped"
        assert result["reason"] == "debounced"
        repo.replace_communities.assert_not_called()

    async def test_debounce_passes_when_entity_count_changed(self):
        """实体数变化 >=10%：即使 <60s 也重建。"""
        entities, relations = self._two_cluster_graph()
        repo = AsyncMock()
        repo.list_entities = AsyncMock(return_value=entities)
        repo.list_relations = AsyncMock(return_value=relations)
        _, session_factory = _make_session_patch()

        cache_state = {
            builder._CACHE_KEY_LAST_AT: time.time(),
            builder._CACHE_KEY_LAST_COUNT: 100,  # 6 vs 100，变化远超 10%
        }

        async def _cache_get(key):
            return cache_state.get(key)

        with patch.object(builder, "kg_repo", repo), \
             patch.object(builder, "AsyncSessionLocal", session_factory), \
             patch.object(builder, "cache_get", side_effect=_cache_get), \
             patch.object(builder, "cache_set", AsyncMock()), \
             patch.object(builder, "_summarize_community", AsyncMock(return_value=("t", "s"))):
            result = await builder.rebuild_communities()

        assert result["status"] == "rebuilt"
        repo.replace_communities.assert_awaited_once()

    async def test_summarize_fallback_on_llm_failure(self):
        """LLM 摘要失败时退化为实体名拼接，不抛异常。"""
        members = [{"name": "阿里巴巴", "entity_type": "组织", "description": "科技公司"}]
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=RuntimeError("LLM down"))
        with patch("app.services.llm_service.llm_service", mock_llm):
            title, summary = await builder._summarize_community(members)
        assert "阿里巴巴" in title
        assert "阿里巴巴" in summary
