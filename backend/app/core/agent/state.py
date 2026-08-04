"""Agent 工作流状态定义（Phase 2 自 app.core.agent 模块拆分）。"""

from typing import Annotated, Optional, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """LangGraph 工作流状态定义。

    字段说明：
        messages: 对话消息列表（LangGraph reducer 自动累积）
        query: 当前用户输入
        user_id: 用户标识（用于 Mem0 记忆）
        user_memory: 从 Mem0 检索到的长期记忆文本
        llm_config: 用户级模型配置字典，在节点间传递以确保使用用户自己的 API Key
        intent: 意图分类结果（rag / direct / clarify / data_analysis）
        contexts: RAG 检索到的文档片段
        images: 关联的图片列表
        citations: 引用来源信息
        response: 最终回答文本
        content_blocks: 图文内容块（供前端渲染）
        needs_clarification: 是否需要澄清
        conversation_id: 会话 ID
        knowledge_base_ids: 知识库过滤列表
        temperature: 生成温度
        data_agent_context: Data Agent 分析上下文（当 intent=data_analysis 时使用）
        thoughts: 思维链步骤累积（实时经 stream writer 推送，此处仅作状态占位）
        tool_call_count: agentic 模式已执行的工具调用次数（上限 MAX_TOOL_CALLS）
        tool_messages: agentic 模式工具循环的消息轨迹（AI 工具调用 + ToolMessage）
        searched_queries: 已检索过的查询（相同 query 去重，防 LLM 重复检索）
    """

    messages: Annotated[list, add_messages]
    query: str
    user_id: str
    user_memory: str
    llm_config: dict
    intent: str
    contexts: list
    images: list
    citations: list
    response: str
    content_blocks: list
    needs_clarification: bool
    conversation_id: Optional[str]
    knowledge_base_ids: list
    temperature: float
    data_agent_context: Optional[dict]
    attachments: list
    thoughts: list
    tool_call_count: int
    tool_messages: list
    searched_queries: list
