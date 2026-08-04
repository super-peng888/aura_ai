"""高层 Agent 服务：驱动 LangGraph 工作流并输出 SSE 事件流（Phase 2 自 app.core.agent 模块拆分）。"""

from typing import AsyncIterator, List, Optional

from app.core.agent.graph import agent_graph
from app.core.agent.state import AgentState
from app.core.attachment_processor import process_attachments
from app.core.data_agent import data_agent_service
from app.core.knowledge.rag_pipeline import rag_pipeline


class AgentService:
    """高层 Agent 服务，支持用户级模型配置。"""

    async def chat(
        self,
        query: str,
        user_id: str = "default",
        conversation_history: Optional[List[dict]] = None,
        conversation_id: Optional[str] = None,
        knowledge_base_ids: Optional[List[str]] = None,
        temperature: float = 0.7,
        llm_config: Optional[dict] = None,
        attachments: Optional[List[dict]] = None,
    ) -> AsyncIterator[dict]:
        """
        执行 Agent 对话流。

        Args:
            query: 用户当前输入
            user_id: 用户标识（用于 Mem0 记忆）
            conversation_history: 历史消息列表
            conversation_id: 会话 ID
            knowledge_base_ids: 知识库过滤
            temperature: 生成温度
            llm_config: 用户级 LLM 配置（provider / api_key / base_url / model）
            attachments: 附件列表 [{filename, url, mime_type}]
        """
        # 处理附件：下载内容并附加到 query
        if attachments:
            attachment_text = await process_attachments(attachments)
            if attachment_text:
                query = query + attachment_text

        state = AgentState(
            messages=conversation_history or [],
            query=query,
            user_id=user_id,
            user_memory="",
            llm_config=llm_config or {},
            intent="",
            contexts=[],
            images=[],
            citations=[],
            response="",
            content_blocks=[],
            needs_clarification=False,
            conversation_id=conversation_id,
            knowledge_base_ids=knowledge_base_ids or [],
            temperature=temperature,
            data_agent_context=None,
            attachments=attachments or [],
            thoughts=[],
            tool_call_count=0,
            tool_messages=[],
        )

        # 驱动 LangGraph 工作流（意图分类、记忆加载、检索、图内生成）
        # updates 流跟踪各节点状态变化；custom 流转发 generate 节点的流式文本增量
        intent = ""
        citations: list = []
        images: list = []
        response = ""
        emitted_intro = False

        async for mode, payload in agent_graph.astream(state, stream_mode=["updates", "custom"]):
            if mode == "custom":
                # 思维链事件（dict）：实时透传给前端 ThoughtChain，不触发 citations 序列
                if isinstance(payload, dict):
                    if payload.get("kind") == "thought":
                        yield {"type": "thought", "data": payload}
                    continue
                # 首个文本增量之前，按原 SSE 契约先发 citations / images 事件
                if not emitted_intro and intent == "rag" and citations:
                    yield {"type": "citations", "data": citations}
                    if images:
                        yield {"type": "images", "data": images}
                emitted_intro = True
                yield {"type": "text", "data": payload}
                continue
            for node_update in payload.values():
                if not isinstance(node_update, dict):
                    continue
                if "intent" in node_update:
                    intent = node_update["intent"]
                if "citations" in node_update:
                    citations = node_update["citations"]
                if "images" in node_update:
                    images = node_update["images"]
                if "response" in node_update:
                    response = node_update["response"]

        if intent == "data_analysis":
            # Data Agent 分支：流式输出 SQL + 结果 + 图表 + 分析
            full_response = ""
            async for chunk in data_agent_service.analyze(
                query=query,
                user_id=user_id,
                conversation_history=conversation_history,
            ):
                yield chunk
                if chunk["type"] == "analysis":
                    full_response = chunk["data"]
            response = full_response

        # 组装图文内容块
        content_blocks = rag_pipeline.to_content_blocks(
            text=response,
            images=images,
            sources=citations,
        )
        yield {"type": "content_blocks", "data": content_blocks}
        yield {"type": "done", "data": None}


agent_service = AgentService()
