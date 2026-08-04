"""RAG Pipeline: query rewrite, retrieval, rerank, image resolution, content blocks.

说明：
- 查询改写（rewrite_query）等 LLM 调用的用户模型配置由请求上下文
  （app.utils.request_context）解析，无需透传 user_id
"""

import re
from typing import List, Optional

from app.config import get_settings
from app.services.llm_service import llm_service
from app.services.embedding_service import embedding_service
from app.core.knowledge.retrieval import retrieval_service
from app.core.knowledge.reranker import reranker_service
from app.core.knowledge.graph.retriever import graph_retriever
from app.services.retrieval_config_service import retrieval_config_service
from app.db.repository import image_repo
from app.db.base import AsyncSessionLocal

settings = get_settings()

IMAGE_PLACEHOLDER_RE = re.compile(r"\[IMG:([a-zA-Z0-9_]+)\]")


class RAGPipeline:
    """End-to-end RAG pipeline with image-aware response assembly."""

    def __init__(self):
        self.enable_query_rewrite = settings.RAG_ENABLE_QUERY_REWRITE
        self.enable_rerank = settings.RAG_ENABLE_RERANK
        self.similarity_threshold = settings.RAG_SIMILARITY_THRESHOLD

    async def search(
        self,
        query: str,
        document_ids: Optional[List[str]] = None,
        knowledge_base_ids: Optional[List[str]] = None,
        top_k: Optional[int] = None,
        filters: Optional[dict] = None,
    ) -> dict:
        """
        执行 RAG 搜索。

        Args:
            query: 用户原始查询
            document_ids: 限制搜索的文档范围
            knowledge_base_ids: 知识库过滤
            top_k: 返回结果数（None 时使用检索配置的 rerank_top_k）
            filters: 元数据过滤
        """
        # 运行时检索配置（DB 覆盖 .env 默认，admin 页面可配，无需重启）
        cfg = await retrieval_config_service.resolve()
        enable_query_rewrite = cfg["enable_query_rewrite"]
        top_k = top_k or cfg["rerank_top_k"]

        rewritten_query = query
        if enable_query_rewrite:
            rewritten_query = await llm_service.rewrite_query(query)

        query_embedding = await embedding_service.embed_query(rewritten_query)

        retrieved = await retrieval_service.retrieve(
            query=rewritten_query,
            query_embedding=query_embedding,
            document_ids=document_ids,
            knowledge_base_ids=knowledge_base_ids,
            top_k=top_k * 2,
            filters=filters,
            enable_keyword=cfg["enable_keyword_search"],
            enable_vector=cfg["enable_vector_search"],
        )

        # GraphRAG 融合：开启时把图检索结果并入候选，一起进 rerank。
        # 图结果 score 为固定基准分（无量纲可比性），由 reranker 基于内容重打分，
        # 并以 search_type="graph"/"graph_global" 标记来源。
        if cfg.get("enable_graph_rag"):
            graph_results = await self._graph_search(rewritten_query, top_k=top_k, cfg=cfg)
            if graph_results:
                seen_chunk_ids = {c["chunk_id"] for c in retrieved}
                retrieved = retrieved + [c for c in graph_results if c["chunk_id"] not in seen_chunk_ids]

        if cfg["enable_rerank"] and retrieved:
            retrieved = await reranker_service.rerank(rewritten_query, retrieved, top_k=top_k)
        else:
            retrieved = retrieved[:top_k]

        similarity_threshold = cfg["similarity_threshold"]
        if similarity_threshold and similarity_threshold > 0:
            # 阈值只对 rerank 重打分（relevance_score，0~1 量纲）的结果生效：
            # - graph/graph_global：图结果分数不可比，豁免（既有语义）
            # - 未经 rerank（关闭/降级）：score 是 Milvus RRF 融合分（量级 ~1/60），
            #   与 0~1 阈值量纲不可比，一旦过滤会把全部结果误杀成空上下文，
            #   导致 LLM 无资料纯自由发挥（检索失效的隐蔽根因）
            retrieved = [
                c for c in retrieved
                if not c.get("reranked")
                or c.get("score", 0) >= similarity_threshold
                or c.get("search_type") in ("graph", "graph_global")
            ]

        results_with_images = await self._resolve_images(self._expand_to_parents(retrieved))

        return {
            "query": query,
            "rewritten_query": rewritten_query if enable_query_rewrite else None,
            "results": results_with_images,
        }

    @staticmethod
    def _expand_to_parents(chunks: List[dict]) -> List[dict]:
        """父子分块（small-to-big）：命中子块后回捞父节完整内容送 LLM。

        - 入参已按分数降序（rerank/RRF 后），同一父节的多个子块只保留
          排位最高的一个，并将 content 换为父节完整内容；
        - 无 parent_id 的结果（非 markdown / 单子块节 / 图检索）按 chunk_id 去重，原样保留；
        - rerank 基于精确子块打分，回捞发生在排序之后，不影响相关性判断。
        """
        seen: set = set()
        out: List[dict] = []
        for c in chunks:
            pid = c.get("parent_id")
            key = pid or c.get("chunk_id")
            if key in seen:
                continue
            seen.add(key)
            if pid and c.get("parent_content"):
                c = {**c, "content": c["parent_content"]}
            out.append(c)
        return out

    @staticmethod
    async def _graph_search(query: str, top_k: int, cfg: dict) -> List[dict]:
        """按 graph_search_mode 执行图检索（local/global/auto=并集），按 chunk_id 去重。"""
        mode = (cfg.get("graph_search_mode") or "auto").lower()
        results: List[dict] = []
        if mode in ("local", "auto"):
            results.extend(await graph_retriever.local_search(query, top_k=top_k))
        if mode in ("global", "auto"):
            results.extend(await graph_retriever.global_search(query, top_k=top_k))
        seen: set = set()
        deduped: List[dict] = []
        for r in results:
            if r["chunk_id"] in seen:
                continue
            seen.add(r["chunk_id"])
            deduped.append(r)
        return deduped

    async def _resolve_images(self, chunks: List[dict]) -> List[dict]:
        all_image_ids = set()
        for chunk in chunks:
            chunk_image_ids = chunk.get("image_ids", [])
            if isinstance(chunk_image_ids, str):
                import json
                try:
                    chunk_image_ids = json.loads(chunk_image_ids)
                except Exception:
                    chunk_image_ids = []
            all_image_ids.update(chunk_image_ids)
            refs = IMAGE_PLACEHOLDER_RE.findall(chunk["content"])
            all_image_ids.update(refs)

        if not all_image_ids:
            return chunks

        async with AsyncSessionLocal() as session:
            images = await image_repo.get_by_ref_ids(session, list(all_image_ids))
            image_map = {img.image_ref_id: img for img in images}

        for chunk in chunks:
            chunk_images = []
            chunk_image_ids = chunk.get("image_ids", [])
            if isinstance(chunk_image_ids, str):
                import json
                try:
                    chunk_image_ids = json.loads(chunk_image_ids)
                except Exception:
                    chunk_image_ids = []

            for img_id in chunk_image_ids:
                img = image_map.get(img_id)
                if img:
                    chunk_images.append({
                        "image_id": img_id,
                        "url": img.oss_url,
                        "thumbnail_url": img.thumbnail_url,
                        "caption": img.caption,
                        "width": img.width,
                        "height": img.height,
                        "page_number": img.page_number,
                    })
            chunk["images"] = chunk_images

        return chunks

    @staticmethod
    def to_content_blocks(text: str, images: List[dict], sources: List[dict]) -> List[dict]:
        blocks = []
        display_text = text
        for img in images:
            display_text = display_text.replace(
                f"[IMG:{img['image_id']}]",
                f"📎 [图片: {img.get('caption', img['image_id'])}]"
            )
        blocks.append({"type": "text", "content": display_text})

        for img in images:
            blocks.append({
                "type": "image",
                "image_id": img["image_id"],
                "url": img["url"],
                "alt": img.get("caption", ""),
                "description": img.get("caption", ""),
                "page": img.get("page_number"),
            })

        if sources:
            blocks.append({
                "type": "sources",
                "sources": [
                    {
                        "doc_id": s.get("document_id", ""),
                        "page": s.get("page_number"),
                        "score": s.get("similarity", 0),
                        "snippet": s.get("content", "")[:200],
                    }
                    for s in sources
                ],
            })

        return blocks


rag_pipeline = RAGPipeline()
