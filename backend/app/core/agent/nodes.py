"""LangGraph 节点函数与条件路由（Phase 2 自 app.core.agent 模块拆分）。

- rag_mode="pipeline"（默认）：rag 意图走固定 retrieve → generate 管道
- rag_mode="agentic"（检索配置）：rag 意图走 agent_reason → tool_exec 工具调用循环，
  LLM 自主决定调用 knowledge_search 工具（上限 MAX_TOOL_CALLS 次），SSE 事件序列与 pipeline 模式一致
"""

from typing import List, Optional

from langgraph.config import get_stream_writer
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.config import get_settings
from app.core.agent.state import AgentState
from app.core.agent.tools import (
    MAX_TOOL_CALLS,
    _resolve_chat_model,
    _run_knowledge_search,
    knowledge_search,
)
from app.core.knowledge.rag_pipeline import rag_pipeline
from app.services.llm_service import llm_service
from app.services.memory_service import memory_service
from app.services.retrieval_config_service import retrieval_config_service

settings = get_settings()


async def load_memory_node(state: AgentState) -> dict:
    """从 Mem0 加载用户长期记忆。"""
    user_id = state.get("user_id", "default")
    query = state["query"]
    memories = await memory_service.search(query, user_id=user_id, limit=5)
    memory_text = "\n".join([m["memory"] for m in memories])
    return {"user_memory": memory_text}


async def classify_intent_node(state: AgentState) -> dict:
    """使用用户配置的模型进行意图分类，同时解析检索配置的 RAG 模式（路由用）。"""
    query = state["query"]

    system = (
        "判断用户意图类型，只回复一个单词："
        "rag（需要检索文档）/ direct（直接回答）/ clarify（需要澄清）/ data_analysis（数据分析或报表生成）"
    )
    try:
        result = await llm_service.generate(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"用户问题：{query}"},
            ],
            temperature=0,
            max_tokens=20,
        )
        intent = result.strip().lower().split()[0]
        if intent not in ("rag", "direct", "clarify", "data_analysis"):
            intent = "rag"
    except Exception:
        intent = "rag"

    # rag_mode 决定 rag 意图走固定管道（retrieve）还是工具调用循环（agent_reason）
    try:
        cfg = await retrieval_config_service.resolve()
        rag_mode = cfg.get("rag_mode") or "pipeline"
    except Exception:
        rag_mode = "pipeline"
    return {"intent": intent, "rag_mode": rag_mode}


def _chunks_to_citations(contexts: list) -> list:
    """检索片段 → citations 契约（与前端 SSE citations 事件一致）。"""
    return [
        {
            "chunk_id": c["chunk_id"],
            "document_id": c["document_id"],
            "content": c["content"][:200] + "...",
            "page_number": c.get("page_number"),
            "similarity": c.get("score", 0),
        }
        for c in contexts
    ]


async def retrieve_context_node(state: AgentState) -> dict:
    """rag_mode="pipeline" 时的固定检索节点：检索相关文档片段和图片。"""
    if state["intent"] != "rag":
        return {}

    result = await rag_pipeline.search(
        query=state["query"],
        knowledge_base_ids=state.get("knowledge_base_ids"),
        top_k=settings.RAG_RERANK_TOP_K,
    )

    contexts = result["results"]
    # search() 内部已通过 _resolve_images 解析图片，无需二次调用

    all_images = []
    for ctx in contexts:
        if ctx.get("images"):
            all_images.extend(ctx["images"])

    return {
        "contexts": contexts,
        "images": all_images,
        "citations": _chunks_to_citations(contexts),
    }


# ============================================================================
# Agentic 工具调用循环（rag_mode="agentic" 时替代 retrieve 固定管道）
# ============================================================================

AGENT_REASON_SYSTEM_PROMPT = (
    "你是企业知识库问答助手。回答用户问题前，如需要文档资料支撑，"
    "请调用 knowledge_search 工具检索（可用不同查询多次检索以补全信息）；"
    "当资料足够或直接可答时，不要再调用工具，直接结束检索。"
)


async def agent_reason_node(state: AgentState) -> dict:
    """Agentic 推理节点：LLM（绑定 knowledge_search 工具）决定是否需要检索。

    LLM 返回 tool_calls → 条件边路由到 tool_exec 执行后回到本节点继续推理；
    无 tool_calls（或调用失败兜底）→ 进入 generate。循环由 tool_call_count 上限约束。
    """
    try:
        model = await _resolve_chat_model(state.get("llm_config"))
        bound = model.bind_tools([knowledge_search])

        lc_messages: List[BaseMessage] = [SystemMessage(content=AGENT_REASON_SYSTEM_PROMPT)]
        for m in _history_to_dicts(state.get("messages")):
            if m["role"] == "assistant":
                lc_messages.append(AIMessage(content=m["content"] or ""))
            elif m["role"] != "system":
                lc_messages.append(HumanMessage(content=m["content"] or ""))
        lc_messages.append(HumanMessage(content=state["query"]))
        lc_messages.extend(state.get("tool_messages") or [])

        ai_msg = await bound.ainvoke(lc_messages)
        return {"tool_messages": (state.get("tool_messages") or []) + [ai_msg]}
    except Exception as e:
        # 推理失败兜底：不再调用工具，直接进 generate（按无检索结果生成）
        print(f"[agent_reason] error: {e}")
        return {}


async def tool_exec_node(state: AgentState) -> dict:
    """执行 agent_reason 产出的工具调用，累积 contexts/citations（images 取最后一次检索）。

    不通过 stream writer 发任何事件（前端无感知）；检索结果经 state updates
    进入 AgentService.chat 的 updates 流，沿用现有 citations/images 事件序列。
    """
    tool_messages = list(state.get("tool_messages") or [])
    last_ai = tool_messages[-1] if tool_messages else None
    tool_calls = getattr(last_ai, "tool_calls", None) or []
    if not tool_calls:
        return {"tool_call_count": state.get("tool_call_count", 0)}

    kb_ids = state.get("knowledge_base_ids") or None
    contexts = list(state.get("contexts") or [])
    seen_chunk_ids = {c["chunk_id"] for c in contexts}
    citations = list(state.get("citations") or [])
    images = list(state.get("images") or [])
    count = state.get("tool_call_count", 0)

    for call in tool_calls:
        args = call.get("args") or {}
        if call.get("name") != knowledge_search.name:
            tool_messages.append(
                ToolMessage(content=f"未知工具: {call.get('name')}", tool_call_id=call.get("id"))
            )
            continue
        try:
            top_k = int(args.get("top_k") or 5)
        except (TypeError, ValueError):
            top_k = 5
        try:
            text_out, new_contexts = await _run_knowledge_search(
                query=args.get("query") or state["query"],
                top_k=top_k,
                knowledge_base_ids=kb_ids,
            )
        except Exception as e:
            text_out, new_contexts = f"检索失败: {e}", []
        tool_messages.append(ToolMessage(content=text_out, tool_call_id=call.get("id")))
        count += 1

        fresh_images = []
        for c in new_contexts:
            if c["chunk_id"] not in seen_chunk_ids:
                seen_chunk_ids.add(c["chunk_id"])
                contexts.append(c)
                citations.extend(_chunks_to_citations([c]))
            if c.get("images"):
                fresh_images.extend(c["images"])
        images = fresh_images  # images/content_blocks 用最后一次 search 的结果

    return {
        "tool_messages": tool_messages,
        "contexts": contexts,
        "citations": citations,
        "images": images,
        "tool_call_count": count,
    }


def _history_to_dicts(messages: list) -> List[dict]:
    """将 state.messages（add_messages reducer 可能已转为 LangChain Message）还原为 dict 列表。"""
    out = []
    for m in messages or []:
        if isinstance(m, dict):
            out.append({"role": m.get("role"), "content": m.get("content")})
        else:
            role = getattr(m, "type", "user")
            role = {"human": "user", "ai": "assistant"}.get(role, role)
            out.append({"role": role, "content": getattr(m, "content", "")})
    return out


async def generate_response_node(state: AgentState) -> dict:
    """在图内生成回答，并通过 stream writer 实时输出文本增量（custom 流）。

    - data_analysis：由 AgentService.chat 在图外走 data_agent 流式分支，此处不生成
    - rag：使用 generate_with_citations（contexts 来自 retrieve 或工具循环累积）
    - clarify：固定澄清话术
    - direct（或 rag 无任何片段）：普通流式生成
    """
    intent = state["intent"]
    if intent == "data_analysis":
        return {"response": ""}

    writer = get_stream_writer()
    temperature = state.get("temperature", 0.7)
    query = state["query"]
    history = _history_to_dicts(state.get("messages"))

    if intent == "clarify":
        text = "我不太确定您的问题，能否请您再详细描述一下？或者告诉我您想了解哪个方面的内容？"
        writer(text)
        return {"response": text}

    contexts = state.get("contexts") or []

    if intent == "rag" and contexts:
        llm_contexts = [
            {"content": c["content"], "page_number": c.get("page_number"), "document_id": c["document_id"]}
            for c in contexts
        ]
        full_response = ""
        async for delta in llm_service.generate_with_citations(
            query=query,
            contexts=llm_contexts,
            conversation_history=history or None,
            temperature=temperature,
            user_memory=state.get("user_memory", ""),
        ):
            full_response += delta
            writer(delta)
        return {"response": full_response}

    messages = history + [{"role": "user", "content": query}]
    full_response = ""
    async for delta in llm_service.generate_stream(
        messages=messages,
        temperature=temperature,
    ):
        full_response += delta
        writer(delta)
    return {"response": full_response}


async def save_memory_node(state: AgentState) -> dict:
    """将本轮对话摘要保存到 Mem0。"""
    user_id = state.get("user_id", "default")
    query = state["query"]
    response = state.get("response", "")
    if query:
        await memory_service.add(query, user_id=user_id)
    if response and len(response) < 500:
        await memory_service.add(f"结论: {response[:200]}", user_id=user_id)
    return {}


# ============================================================================
# Router
# ============================================================================

def intent_router(state: AgentState) -> str:
    intent = state["intent"]
    if intent == "rag":
        # agentic 模式：工具调用循环替代固定 retrieve 管道
        if state.get("rag_mode") == "agentic":
            return "agent_reason"
        return "retrieve"
    if intent == "data_analysis":
        return "data_analysis"
    return "generate"


def route_after_reason(state: AgentState) -> str:
    """LLM 请求调工具且未达上限 → tool_exec；否则进入生成。"""
    tool_messages = state.get("tool_messages") or []
    last_ai = tool_messages[-1] if tool_messages else None
    tool_calls = getattr(last_ai, "tool_calls", None) or []
    if tool_calls and state.get("tool_call_count", 0) < MAX_TOOL_CALLS:
        return "tool_exec"
    return "generate"
