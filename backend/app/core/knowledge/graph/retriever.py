"""GraphRAG 检索侧：基于知识图谱（kg_* 四表）的 local / global 检索。

设计说明：
- 与索引侧（A 的 KnowledgeGraphRepository）零耦合：直接用 SQLAlchemy text() 写
  SQL，通过 app.db.base.AsyncSessionLocal 访问，避免并行开发的方法签名依赖。
- local_search：实体锚定（子串匹配优先，未命中再 LLM 提取关键实体，避免每查询
  多次 LLM 调用）→ kg_relations 1~2 跳邻居 → kg_chunk_entities 收集 chunk_ids
  → document_chunks 取内容 → 返回与 rag_pipeline 检索结果同构的 dict。
- 锚定匹配的归一化复用 extraction.normalize_entity_name（NFKC → casefold →
  去空白），与索引侧写入 kg_entities.name_normalized 的规则严格一致。
- global_search：kg_communities 的 summary 与 query 做 embedding 余弦相关度，
  取 top_k 包装为同构 dict（search_type="graph_global"）。
- 表为空 / 无命中 / 表不存在（索引侧尚未建表）均返回空列表，不报错。
"""

import math
import re
from typing import List

from sqlalchemy import text

from app.config import get_settings
from app.core.knowledge.graph.extraction import normalize_entity_name
from app.db.base import AsyncSessionLocal
from app.services.llm_service import llm_service
from app.services.embedding_service import embedding_service

settings = get_settings()

# 图结果没有与向量分数可比的分数：给一个可解释的固定基准分，
# 开启 rerank 时 reranker 会基于内容重打分，此基准仅作为兜底排序依据。
GRAPH_BASELINE_SCORE = 0.5

_MAX_ANCHORS = 8  # 单次查询最多锚定实体数
_MAX_ENTITIES = 50  # 邻居扩展后的实体数上限
_MAX_CHUNK_IDS = 40  # 收集的 chunk_id 上限
_MAX_COMMUNITIES = 200  # global 检索参与打分的社区上限


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


class GraphRetriever:
    """知识图谱检索器（local 实体邻域 / global 社区摘要两条路径）。"""

    # ------------------------------------------------------------------
    # 实体锚定
    # ------------------------------------------------------------------
    async def _anchor_entities(self, session, query: str) -> List[dict]:
        """从 query 中锚定图谱实体：子串匹配优先，未命中再 LLM 提取。

        query 与实体名两侧统一走 extraction.normalize_entity_name
        （NFKC 全半角 → casefold → 去空白），与索引侧写入
        kg_entities.name_normalized 的规则完全一致。
        """
        normalized_query = normalize_entity_name(query)
        if not normalized_query:
            return []

        # 简单匹配：实体归一化名是归一化查询的子串
        rows = (
            await session.execute(
                text(
                    "SELECT id, name, entity_type FROM kg_entities "
                    "WHERE name_normalized <> '' "
                    "AND position(name_normalized in :q) > 0 "
                    "ORDER BY length(name_normalized) DESC "
                    "LIMIT :lim"
                ),
                {"q": normalized_query, "lim": _MAX_ANCHORS},
            )
        ).mappings().all()
        if rows:
            return [dict(r) for r in rows]

        # 兜底：LLM 提取关键实体，再按名归一化匹配
        try:
            extracted = await llm_service.generate(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "从用户问题中提取关键实体（人名、机构、产品、术语等）。"
                            "只输出逗号分隔的实体名，不要解释；没有则输出空。"
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                temperature=0,
                max_tokens=100,
            )
        except Exception:
            return []
        names = [normalize_entity_name(n) for n in re.split(r"[,，;；\n]", extracted or "") if normalize_entity_name(n)]
        if not names:
            return []
        rows = (
            await session.execute(
                text(
                    "SELECT id, name, entity_type FROM kg_entities "
                    "WHERE name_normalized = ANY(:names) LIMIT :lim"
                ),
                {"names": names, "lim": _MAX_ANCHORS},
            )
        ).mappings().all()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # local search：实体邻域 → chunk 回溯
    # ------------------------------------------------------------------
    async def local_search(
        self,
        query: str,
        top_k: int = 5,
    ) -> List[dict]:
        """实体锚定 + 1~2 跳邻居 + chunk 回溯的局部图检索。"""
        try:
            async with AsyncSessionLocal() as session:
                anchors = await self._anchor_entities(session, query)
                if not anchors:
                    return []

                entity_ids = [str(a["id"]) for a in anchors]
                seen = set(entity_ids)
                frontier = entity_ids

                # 1~2 跳邻居扩展
                for _ in range(2):
                    if not frontier or len(seen) >= _MAX_ENTITIES:
                        break
                    rows = (
                        await session.execute(
                            text(
                                "SELECT source_entity_id, target_entity_id FROM kg_relations "
                                "WHERE source_entity_id = ANY(:ids) OR target_entity_id = ANY(:ids) "
                                "LIMIT 500"
                            ),
                            {"ids": frontier},
                        )
                    ).mappings().all()
                    next_frontier = []
                    for r in rows:
                        for eid in (str(r["source_entity_id"]), str(r["target_entity_id"])):
                            if eid not in seen:
                                seen.add(eid)
                                next_frontier.append(eid)
                                if len(seen) >= _MAX_ENTITIES:
                                    break
                    frontier = next_frontier

                # chunk 回溯
                rows = (
                    await session.execute(
                        text(
                            "SELECT chunk_id, doc_id FROM kg_chunk_entities "
                            "WHERE entity_id = ANY(:ids) LIMIT :lim"
                        ),
                        {"ids": list(seen), "lim": _MAX_CHUNK_IDS},
                    )
                ).mappings().all()
                chunk_doc = {r["chunk_id"]: r.get("doc_id") for r in rows}
                if not chunk_doc:
                    return []

                rows = (
                    await session.execute(
                        text(
                            "SELECT id, document_id, content, page_number, image_ids "
                            "FROM document_chunks WHERE id = ANY(:chunk_ids)"
                        ),
                        {"chunk_ids": list(chunk_doc.keys())},
                    )
                ).mappings().all()

                results = [
                    {
                        "chunk_id": r["id"],
                        "document_id": r["document_id"] or chunk_doc.get(r["id"]),
                        "content": r["content"],
                        "page_number": r.get("page_number"),
                        "score": GRAPH_BASELINE_SCORE,
                        "search_type": "graph",
                        "image_ids": r.get("image_ids") or [],
                    }
                    for r in rows
                ]
                return results[:top_k]
        except Exception as e:
            # 表不存在 / 查询失败均不阻断主检索链路
            print(f"[GraphRetriever] local_search error: {e}")
            return []

    # ------------------------------------------------------------------
    # global search：社区摘要相关性
    # ------------------------------------------------------------------
    async def global_search(
        self,
        query: str,
        top_k: int = 3,
    ) -> List[dict]:
        """kg_communities 的 summary 与 query 做 embedding 余弦相关度检索。"""
        try:
            async with AsyncSessionLocal() as session:
                rows = (
                    await session.execute(
                        text(
                            "SELECT id, title, summary, level FROM kg_communities "
                            "WHERE summary IS NOT NULL AND summary <> '' "
                            "ORDER BY level ASC, entity_count DESC "
                            "LIMIT :lim"
                        ),
                        {"lim": _MAX_COMMUNITIES},
                    )
                ).mappings().all()
        except Exception as e:
            print(f"[GraphRetriever] global_search error: {e}")
            return []

        if not rows:
            return []

        summaries = [f"{r.get('title') or ''}\n{r['summary']}" for r in rows]
        scored: List[tuple] = []
        try:
            query_vec = await embedding_service.embed_query(query)
            summary_vecs = await embedding_service.embed_dense(summaries)
            scored = [
                (i, _cosine(query_vec, vec)) for i, vec in enumerate(summary_vecs)
            ]
        except Exception as e:
            # embedding 失败时退化为关键词重叠打分，保证可用
            print(f"[GraphRetriever] global_search embedding fallback: {e}")
            q_terms = set(normalize_entity_name(query))
            scored = [
                (i, sum(1.0 for ch in q_terms if ch in normalize_entity_name(summaries[i])))
                for i in range(len(rows))
            ]

        scored = [s for s in scored if s[1] > 0]
        scored.sort(key=lambda x: x[1], reverse=True)

        return [
            {
                "chunk_id": str(rows[i]["id"]),
                "document_id": "",
                "content": summaries[i],
                "page_number": None,
                "score": float(score),
                "search_type": "graph_global",
                "image_ids": [],
            }
            for i, score in scored[:top_k]
        ]


graph_retriever = GraphRetriever()
