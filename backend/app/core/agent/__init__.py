"""LangGraph Agent 包：Mem0 记忆、图文 RAG、用户级 LLM 配置（Phase 2 自 app.core.agent 模块拆分）。

结构：
    state.py   AgentState
    nodes.py   节点函数 + 条件路由
    tools.py   knowledge_search 工具 + 检索执行体 + 用户级 ChatModel 解析 + MAX_TOOL_CALLS
    graph.py   build_agent_graph + 编译产物 agent_graph
    service.py AgentService（chat 流式编排）

对外契约与原 app.core.agent 模块一致，现有 import 路径无需改动：
    from app.core.agent import agent_service, agent_graph, build_agent_graph, AgentState, MAX_TOOL_CALLS

设计要点：
- AgentState 携带 llm_config 字段，在节点间传递用户模型配置（用户自己的 API Key）
- rag 意图恒走 agent_reason → tool_exec 工具调用循环（agentic），
  LLM 自主决定调用 knowledge_search 工具（上限 MAX_TOOL_CALLS 次），并通过 thought 事件推送思维链
"""

from app.core.agent.state import AgentState
from app.core.agent.tools import (
    MAX_TOOL_CALLS,
    _resolve_chat_model,
    _run_knowledge_search,
    knowledge_search,
)
from app.core.agent.nodes import (
    agent_reason_node,
    classify_intent_node,
    generate_response_node,
    intent_router,
    load_memory_node,
    route_after_reason,
    save_memory_node,
    tool_exec_node,
)
from app.core.agent.graph import agent_graph, build_agent_graph
from app.core.agent.service import AgentService, agent_service

__all__ = [
    "AgentState",
    "MAX_TOOL_CALLS",
    "knowledge_search",
    "_run_knowledge_search",
    "_resolve_chat_model",
    "load_memory_node",
    "classify_intent_node",
    "agent_reason_node",
    "tool_exec_node",
    "generate_response_node",
    "save_memory_node",
    "intent_router",
    "route_after_reason",
    "build_agent_graph",
    "agent_graph",
    "AgentService",
    "agent_service",
]
