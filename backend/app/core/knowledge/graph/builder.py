"""GraphRAG 图构建：实体/关系入库（幂等）+ louvain 社区检测与 LLM 摘要。

- build_document_graph：单文档图谱构建，重建时先清理该文档旧关联与孤立关系
- rebuild_communities：全量实体/关系 -> networkx louvain -> LLM 摘要 -> 整体重写 kg_communities
  防抖：距上次重建 <60s 且实体数变化 <10% 则跳过（状态存 Redis）
"""

from __future__ import annotations

import json
import logging
import time

import networkx as nx

from app.core.knowledge.graph.extraction import extract_entities_relations
from app.db.base import AsyncSessionLocal
from app.db.repository import kg_repo
from app.utils.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

# 社区检测退化阈值：实体数低于该值直接跳过
COMMUNITY_MIN_ENTITIES = 5
# 社区重建防抖参数
COMMUNITY_DEBOUNCE_SECONDS = 60
COMMUNITY_DEBOUNCE_CHANGE_RATIO = 0.10
_CACHE_KEY_LAST_AT = "kg:community:last_rebuild_at"
_CACHE_KEY_LAST_COUNT = "kg:community:last_entity_count"
_CACHE_TTL = 7 * 24 * 3600


async def build_document_graph(document_id: str, chunks: list[dict]) -> dict:
    """构建单文档图谱（幂等）。

    流程：清理该文档旧的 chunk 关联与其产生的孤立关系 -> 抽取 -> upsert 实体 /
    写入关系 / 建立 chunk-entity 关联。同一事务内完成。
    """
    chunk_ids = [str(c.get("chunk_id")) for c in chunks if c.get("chunk_id")]
    entities, relations = await extract_entities_relations(chunks)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await kg_repo.remove_document_graph(session, document_id=document_id, chunk_ids=chunk_ids)

            entity_map: dict[str, object] = {}
            for ent in entities:
                linked_chunk_ids = sorted(set(ent.chunk_ids))
                row = await kg_repo.upsert_entity(
                    session,
                    name=ent.name,
                    entity_type=ent.entity_type,
                    description=ent.description,
                    name_normalized=ent.name_normalized,
                    chunk_delta=len(linked_chunk_ids),
                )
                entity_map[ent.name_normalized] = row
                for chunk_id in linked_chunk_ids:
                    await kg_repo.link_chunk_entity(
                        session, chunk_id=chunk_id, entity_id=row.id, doc_id=document_id
                    )

            relation_count = 0
            for rel in relations:
                src = entity_map.get(rel.source_normalized)
                tgt = entity_map.get(rel.target_normalized)
                if src is None or tgt is None or src.id == tgt.id:
                    continue
                await kg_repo.add_relation(
                    session,
                    source_entity_id=src.id,
                    target_entity_id=tgt.id,
                    relation_type=rel.relation_type,
                    description=rel.description,
                    weight=rel.weight,
                    chunk_id=rel.chunk_id,
                )
                relation_count += 1

    stats = {"entities": len(entity_map), "relations": relation_count}
    logger.info("GraphRAG build for document %s: %s", document_id, stats)
    return stats


# ---------------------------------------------------------------------------
# 社区重建
# ---------------------------------------------------------------------------

async def _should_rebuild(entity_count: int) -> bool:
    """防抖判断：距上次重建 <60s 且实体数变化 <10% 则跳过。Redis 故障时不阻断重建。"""
    try:
        last_at = await cache_get(_CACHE_KEY_LAST_AT)
        last_count = await cache_get(_CACHE_KEY_LAST_COUNT)
    except Exception as e:
        logger.warning("GraphRAG debounce cache read failed, rebuilding anyway: %s", e)
        return True
    if last_at is None or last_count is None:
        return True
    try:
        elapsed = time.time() - float(last_at)
        last_count = int(last_count)
    except (TypeError, ValueError):
        return True
    return not (
        elapsed < COMMUNITY_DEBOUNCE_SECONDS
        and last_count > 0
        and abs(entity_count - last_count) / last_count < COMMUNITY_DEBOUNCE_CHANGE_RATIO
    )


async def _record_rebuild(entity_count: int) -> None:
    try:
        await cache_set(_CACHE_KEY_LAST_AT, time.time(), ttl=_CACHE_TTL)
        await cache_set(_CACHE_KEY_LAST_COUNT, entity_count, ttl=_CACHE_TTL)
    except Exception as e:
        logger.warning("GraphRAG debounce cache write failed: %s", e)


async def _summarize_community(members: list[dict]) -> tuple[str, str]:
    """LLM 生成社区标题与摘要；失败时退化为实体名拼接。"""
    fallback_title = "、".join(m["name"] for m in members[:3])[:50]
    fallback_summary = "；".join(
        f"{m['name']}：{(m.get('description') or '')[:40]}" for m in members[:5]
    )[:200]

    from app.services.llm_service import llm_service  # 延迟导入，避免模块级依赖

    lines = [
        f"- {m['name']}（{m.get('entity_type') or '概念'}）：{(m.get('description') or '')[:100]}"
        for m in members[:20]
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "你是企业知识图谱分析助手。根据给定的实体列表，为该实体社区生成：\n"
                "1. title：不超过10个字的中文标题，概括社区主题\n"
                "2. summary：不超过80字的中文摘要，说明这些实体共同描述的主题与关键关系\n"
                '严格输出 JSON：{"title": "...", "summary": "..."}，不要输出其他内容。'
            ),
        },
        {"role": "user", "content": "实体列表：\n" + "\n".join(lines)},
    ]
    try:
        text = await llm_service.generate(messages, temperature=0.3, max_tokens=300)
        cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(cleaned)
        title = str(data.get("title") or "").strip()
        summary = str(data.get("summary") or "").strip()
        if title and summary:
            return title[:50], summary[:500]
    except Exception as e:
        logger.warning("GraphRAG community summarize failed, fallback: %s", e)
    return fallback_title, fallback_summary


async def rebuild_communities(force: bool = False) -> dict:
    """louvain 社区检测 + LLM 摘要，整体重写 kg_communities。

    退化与防抖：
    - 实体数 < COMMUNITY_MIN_ENTITIES 时跳过
    - 非 force 时按 Redis 记录做防抖（<60s 且实体数变化 <10% 跳过）
    """
    async with AsyncSessionLocal() as session:
        entities = list(await kg_repo.list_entities(session))
        relations = list(await kg_repo.list_relations(session))

    entity_count = len(entities)
    if entity_count < COMMUNITY_MIN_ENTITIES:
        return {"status": "skipped", "reason": "too_few_entities", "entity_count": entity_count}
    if not force and not await _should_rebuild(entity_count):
        return {"status": "skipped", "reason": "debounced", "entity_count": entity_count}

    graph = nx.Graph()
    for ent in entities:
        graph.add_node(
            str(ent.id),
            name=ent.name,
            entity_type=ent.entity_type or "",
            description=ent.description or "",
        )
    for rel in relations:
        src, tgt = str(rel.source_entity_id), str(rel.target_entity_id)
        if src in graph and tgt in graph and src != tgt:
            graph.add_edge(src, tgt, weight=rel.weight or 1.0)

    communities = nx.community.louvain_communities(graph, weight="weight", seed=42)

    rows = []
    for idx, members in enumerate(sorted(communities, key=len, reverse=True)):
        member_ids = sorted(str(m) for m in members)
        member_dicts = [{**graph.nodes[m], "id": m} for m in member_ids]
        title, summary = await _summarize_community(member_dicts)
        rows.append(
            {
                "level": 0,
                "community_key": f"c0-{idx}",
                "title": title,
                "summary": summary,
                "entity_count": len(member_ids),
                "entity_ids": member_ids,
            }
        )

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await kg_repo.replace_communities(session, rows)
    await _record_rebuild(entity_count)

    result = {"status": "rebuilt", "communities": len(rows), "entity_count": entity_count}
    logger.info("GraphRAG communities rebuilt: %s", result)
    return result
