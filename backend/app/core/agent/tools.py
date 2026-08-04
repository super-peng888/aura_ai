"""Agentic 工具调用循环的检索工具与模型解析（rag 意图恒走 agentic 循环）。

- knowledge_search：暴露给 LLM 的知识库检索工具（bind_tools）
- _run_knowledge_search：工具循环共享的检索执行体（文本 + 结构化 contexts）
- _resolve_chat_model：解析用户级 LangChain ChatModel（供 bind_tools 使用）
- MAX_TOOL_CALLS：单次对话的工具调用上限
"""

from typing import Optional

from langchain_core.tools import tool

from app.core.knowledge.rag_pipeline import rag_pipeline
from app.services.llm_service import LLMFactory, UserModelConfigService

# 单次对话的工具调用上限：防止 LLM 无限检索，耗尽后强制进入生成
MAX_TOOL_CALLS = 4


@tool
async def knowledge_search(query: str, top_k: int = 5) -> str:
    """在企业知识库中检索与 query 相关的文档片段。

    Args:
        query: 检索问题或关键词，尽量具体
        top_k: 返回的片段数量（默认 5）

    Returns:
        带编号的文档片段文本；无结果时返回提示文本。
    """
    text_out, _ = await _run_knowledge_search(query=query, top_k=top_k)
    return text_out


# 单片段送 LLM 的字符上限：需容纳父子分块回捞的完整父块组（与
# document_parser._PARENT_GROUP_MAX_CHARS 对齐），截短会导致代码块/详解列表残缺。
_FRAGMENT_MAX_CHARS = 6000


async def _run_knowledge_search(
    query: str,
    top_k: int = 5,
    knowledge_base_ids: Optional[list] = None,
) -> tuple:
    """工具循环共享的检索执行体：返回 (LLM 可读文本, 结构化 contexts)。"""
    result = await rag_pipeline.search(
        query=query,
        knowledge_base_ids=knowledge_base_ids or None,
        top_k=top_k,
    )
    contexts = result.get("results") or []
    if not contexts:
        return "未检索到相关文档。", []
    lines = []
    for i, c in enumerate(contexts, 1):
        lines.append(
            f"[片段{i}] (document_id={c['document_id']}, page={c.get('page_number')})\n{c['content'][:_FRAGMENT_MAX_CHARS]}"
        )
    return "\n\n".join(lines), contexts


async def _resolve_chat_model(llm_config: Optional[dict] = None):
    """解析用户级 LangChain ChatModel（供 bind_tools 使用）。

    用户身份从请求上下文（request_context）读取，resolve() 无需透传 user_id。
    """
    config = llm_config or await UserModelConfigService.resolve()
    return LLMFactory.create_from_user_config(config).get_model()
