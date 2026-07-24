"""Agent LangGraph 装配（Phase 2 自 app.core.agent 模块拆分）。"""

from langgraph.graph import StateGraph, START, END

from app.core.agent.nodes import (
    agent_reason_node,
    classify_intent_node,
    generate_response_node,
    intent_router,
    load_memory_node,
    retrieve_context_node,
    route_after_reason,
    save_memory_node,
    tool_exec_node,
)
from app.core.agent.state import AgentState


def build_agent_graph() -> StateGraph:
    workflow = StateGraph(AgentState)

    workflow.add_node("load_memory", load_memory_node)
    workflow.add_node("classify", classify_intent_node)
    workflow.add_node("retrieve", retrieve_context_node)
    workflow.add_node("agent_reason", agent_reason_node)
    workflow.add_node("tool_exec", tool_exec_node)
    workflow.add_node("generate", generate_response_node)
    workflow.add_node("save_memory", save_memory_node)

    workflow.add_edge(START, "load_memory")
    workflow.add_edge("load_memory", "classify")
    workflow.add_conditional_edges(
        "classify",
        intent_router,
        {
            "retrieve": "retrieve",
            "agent_reason": "agent_reason",
            "generate": "generate",
            "data_analysis": "generate",
        },
    )
    workflow.add_edge("retrieve", "generate")
    workflow.add_conditional_edges(
        "agent_reason",
        route_after_reason,
        {"tool_exec": "tool_exec", "generate": "generate"},
    )
    workflow.add_edge("tool_exec", "agent_reason")
    workflow.add_edge("generate", "save_memory")
    workflow.add_edge("save_memory", END)

    return workflow


agent_graph = build_agent_graph().compile()
