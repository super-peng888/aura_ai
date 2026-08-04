"""LangGraph 节点函数与条件路由（Phase 2 自 app.core.agent 模块拆分）。

rag 意图恒走 agent_reason → tool_exec 工具调用循环：LLM 自主决定调用
knowledge_search 工具（上限 MAX_TOOL_CALLS 次）检索知识库，推理与检索步骤
经 stream writer 以 thought 事件实时推给前端 ThoughtChain。
"""

import asyncio
import logging
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
from app.services.llm_service import llm_service
from app.services.mcp_service import get_mcp_tools
from app.services.memory_service import memory_service
from app.services.usage_service import usage_service

settings = get_settings()
logger = logging.getLogger(__name__)


async def load_memory_node(state: AgentState) -> dict:
    """从 Mem0 加载用户长期记忆。"""
    user_id = state.get("user_id", "default")
    query = state["query"]
    memories = await memory_service.search(query, user_id=user_id, limit=5)
    memory_text = "\n".join([m["memory"] for m in memories])
    return {"user_memory": memory_text}


async def classify_intent_node(state: AgentState) -> dict:
    """使用用户配置的模型进行意图分类（路由用）。"""
    query = state["query"]

    system = (
        "你是企业知识库助手的意图分类器。判断用户意图类型，只回复一个单词："
        "rag（需要检索文档）/ direct（直接回答）/ clarify（需要澄清）/ data_analysis（数据分析或报表生成）。"
        "分类偏向：只要问题可能涉及企业文档、标准规范、业务流程、专业术语等知识内容，"
        "一律判为 rag（即使看起来像通用知识，知识库中也可能有更权威的内部资料）；"
        "仅寒暄闲聊、纯计算、翻译润色等与文档无关的请求才判 direct。"
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

    return {"intent": intent}


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


# ============================================================================
# Agentic 工具调用循环（rag 意图恒走此循环）
# ============================================================================

AGENT_REASON_SYSTEM_PROMPT = (
    "你是企业知识库问答助手，企业内部资料优先于你的自有知识。检索规则："
    "1) 涉及企业文档、标准规范、业务知识的问题，首轮必须先调用 knowledge_search 检索一次——"
    "即使你认为自己知道答案，知识库中可能有更权威的内部文档，不得跳过检索直接作答；"
    "2) 检索查询应保留用户原问题中的专业术语与关键词原文，不要翻译或过度改写；"
    "3) 同一个问题只检索一次，严禁用相同或语义相近的查询重复检索；"
    "4) 仅当已有结果缺失关键信息时，才用明显不同角度的新查询补检；"
    "5) 检索结果已能支撑回答（哪怕不完美）就不要再调用工具，立即结束检索；"
    "6) 除 knowledge_search 外若还提供了其他外部工具，当用户请求明确需要某工具的能力"
    "（如查询外部系统、执行专有操作）时直接调用该工具，无需先检索知识库。"
)


async def agent_reason_node(state: AgentState) -> dict:
    """Agentic 推理节点：LLM（绑定 knowledge_search 工具）决定是否需要检索。

    LLM 返回 tool_calls → 条件边路由到 tool_exec 执行后回到本节点继续推理；
    无 tool_calls（或调用失败兜底）→ 进入 generate。循环由 tool_call_count 上限约束。
    """
    writer = get_stream_writer()
    try:
        model = await _resolve_chat_model(state.get("llm_config"))
        # 外部 MCP 工具（未配置/不可用时为空列表，不影响知识库检索）
        mcp_tools = await get_mcp_tools()
        bound = model.bind_tools([knowledge_search, *mcp_tools])

        lc_messages: List[BaseMessage] = [SystemMessage(content=AGENT_REASON_SYSTEM_PROMPT)]
        for m in _history_to_dicts(state.get("messages")):
            if m["role"] == "assistant":
                lc_messages.append(AIMessage(content=m["content"] or ""))
            elif m["role"] != "system":
                lc_messages.append(HumanMessage(content=m["content"] or ""))
        lc_messages.append(HumanMessage(content=state["query"]))
        lc_messages.extend(state.get("tool_messages") or [])

        ai_msg = await bound.ainvoke(lc_messages)

        # 用量埋点：bind_tools 直调模型，不经 llm_service，单独记录
        um = getattr(ai_msg, "usage_metadata", None) or {}
        usage_service.track(
            "llm",
            getattr(model, "model_name", "") or "",
            scene="agent",
            prompt_tokens=int(um.get("input_tokens") or 0),
            completion_tokens=int(um.get("output_tokens") or 0),
            total_tokens=int(um.get("total_tokens") or 0),
        )

        # 思维链：有工具调用则逐个推送“检索知识库”，否则推送“资料充足，开始作答”
        tool_calls = getattr(ai_msg, "tool_calls", None) or []
        if tool_calls:
            for call in tool_calls:
                args = call.get("args") or {}
                if call.get("name") == knowledge_search.name:
                    writer({
                        "kind": "thought", "step": "tool_call", "title": "检索知识库",
                        "content": args.get("query") or state["query"], "status": "pending",
                    })
                else:
                    writer({
                        "kind": "thought", "step": "tool_call", "title": f"调用工具 {call.get('name')}",
                        "content": str(args)[:200], "status": "pending",
                    })
        else:
            writer({
                "kind": "thought", "step": "reasoning", "title": "资料充足，开始作答",
                "status": "success",
            })
        return {"tool_messages": (state.get("tool_messages") or []) + [ai_msg]}
    except Exception as e:
        # 推理失败兜底：不再调用工具，直接进 generate（按无检索结果生成）
        logger.exception("[agent_reason] 推理失败，降级为无检索直接生成: %s", e)
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

    writer = get_stream_writer()
    kb_ids = state.get("knowledge_base_ids") or None
    contexts = list(state.get("contexts") or [])
    seen_chunk_ids = {c["chunk_id"] for c in contexts}
    citations = list(state.get("citations") or [])
    images = list(state.get("images") or [])
    count = state.get("tool_call_count", 0)
    searched_queries = set(state.get("searched_queries") or [])
    mcp_tools = {t.name: t for t in await get_mcp_tools()}

    for call in tool_calls:
        args = call.get("args") or {}
        if call.get("name") != knowledge_search.name:
            tool_messages.append(await _exec_mcp_tool(call, mcp_tools, writer))
            if call.get("name") in mcp_tools:
                count += 1
            continue
        query = (args.get("query") or state["query"]).strip()
        # 相同查询去重：避免 LLM 用同一 query 重复检索（前端思维链重复“检索→再检索”）
        if query in searched_queries:
            tool_messages.append(ToolMessage(
                content="该查询已检索过，结果已在上文中，请勿重复检索；若信息足够请直接作答。",
                tool_call_id=call.get("id"),
            ))
            writer({
                "kind": "thought", "step": "tool_result", "title": "跳过重复检索",
                "content": query, "status": "success",
            })
            continue
        searched_queries.add(query)
        try:
            top_k = int(args.get("top_k") or 5)
        except (TypeError, ValueError):
            top_k = 5
        try:
            text_out, new_contexts = await _run_knowledge_search(
                query=query,
                top_k=top_k,
                knowledge_base_ids=kb_ids,
            )
        except Exception as e:
            # 检索异常（如 embedding 限流/网络故障）不能伪装成“命中 0 条”，
            # 否则无法与真实无结果区分，排查时也无日志可查
            logger.exception("knowledge_search 执行失败: query=%s", query)
            tool_messages.append(ToolMessage(
                content=f"检索失败: {e}", tool_call_id=call.get("id"),
            ))
            count += 1
            writer({
                "kind": "thought", "step": "tool_result", "title": "检索失败",
                "content": str(e)[:200], "status": "error",
            })
            continue
        tool_messages.append(ToolMessage(content=text_out, tool_call_id=call.get("id")))
        count += 1
        writer({
            "kind": "thought", "step": "tool_result", "title": "检索完成",
            "content": f"命中 {len(new_contexts)} 条", "status": "success",
        })

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
        "searched_queries": list(searched_queries),
    }


async def _exec_mcp_tool(call: dict, mcp_tools: dict, writer) -> ToolMessage:
    """执行单个 MCP 工具调用，返回 ToolMessage（失败/未知工具均降级为错误文本，不中断循环）。"""
    import json as _json

    name = call.get("name")
    args = call.get("args") or {}
    tool = mcp_tools.get(name)
    if tool is None:
        return ToolMessage(content=f"未知工具: {name}", tool_call_id=call.get("id"))
    try:
        result = await asyncio.wait_for(
            tool.ainvoke(args), timeout=settings.MCP_TOOLS_TIMEOUT_SECONDS
        )
        if not isinstance(result, str):
            result = _json.dumps(result, ensure_ascii=False, default=str)
        writer({
            "kind": "thought", "step": "tool_result", "title": f"工具 {name} 完成",
            "content": result[:200], "status": "success",
        })
        # 防御性截断：外部工具返回体不可控，避免撞爆 LLM 上下文
        return ToolMessage(content=result[:8000], tool_call_id=call.get("id"))
    except Exception as e:
        writer({
            "kind": "thought", "step": "tool_result", "title": f"工具 {name} 失败",
            "content": str(e)[:200], "status": "error",
        })
        return ToolMessage(content=f"工具 {name} 调用失败: {e}", tool_call_id=call.get("id"))


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
        # rag 意图恒走 agentic 工具调用循环
        return "agent_reason"
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
