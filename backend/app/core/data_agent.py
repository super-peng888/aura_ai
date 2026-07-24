"""Data Agent — 基于 LangGraph 的对话式数据分析工作流。

工作流：
START → load_context → classify_intent → [generate_sql | generate_direct]
    → validate_sql → execute_query → generate_visualization → END

输出格式（SSE 流式）：
- type=sql: 生成的 SQL
- type=query_result: 查询结果
- type=chart: ECharts 配置
- type=analysis: 分析文字
- type=done: 结束标记
"""

from typing import Annotated, AsyncIterator, List, Optional, TypedDict, Any
import json
import re

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from fastapi import HTTPException

from app.config import get_settings
from app.services.llm_service import llm_service
from app.services.bi_service import bi_service, DataPermissionApplier

settings = get_settings()


# ============================================================================
# Data Agent State
# ============================================================================

class DataAgentState(TypedDict):
    """Data Agent 工作流状态。"""

    messages: Annotated[list, add_messages]
    query: str
    user_id: str
    llm_config: Optional[dict]
    data_source_id: Optional[str]
    schema: dict
    schema_metadata: Optional[dict]
    allowed_tables: List[str]
    intent: str  # sql_query / direct_analysis / clarification
    generated_sql: str
    query_result: Optional[dict]
    analysis: str
    charts: List[dict]
    tables: List[dict]
    error: Optional[str]


# ============================================================================
# LLM Prompts
# ============================================================================

DATA_AGENT_SYSTEM_PROMPT = """你是一位高级数据分析师，擅长通过对话生成 SQL 查询和美观的数据可视化图表。

## 任务
根据用户的分析需求，按以下步骤处理：
1. 理解用户意图
2. 生成合适的 SELECT SQL 查询（PostgreSQL 语法）
3. 基于查询结果生成分析结论
4. 生成图表配置（ECharts Option JSON）

## 输出格式
你必须严格按以下 JSON 格式返回（不要包含 markdown 代码块标记）：

{
  "sql": "SELECT ... FROM ... WHERE ...",
  "analysis": "分析文字，解释数据洞察...",
  "charts": [
    {
      "title": "图表标题",
      "type": "pie|bar|line|radar|scatter",
      "option": { /* 完整的 ECharts option 对象 */ }
    }
  ],
  "tables": [
    {
      "title": "表格标题",
      "headers": ["列1", "列2", "列3"],
      "rows": [["值1", "值2", "值3"], ...]
    }
  ]
}

## SQL 规范
- 只生成 SELECT 语句，不允许任何增删改操作
- 使用 PostgreSQL 语法
- 合理使用 LIMIT 避免返回过多数据
- 需要聚合时使用 GROUP BY
- 日期字段使用标准函数

## ECharts 配置规范
- 使用 ECharts 5.x 语法
- 主题色推荐使用：#2563eb(主色), #10b981, #f59e0b, #ef4444, #8b5cf6, #ec4899, #06b6d4, #84cc16
- 饼图使用 roseType: 'area' 增强视觉效果
- 柱状图使用圆角 barBorderRadius: [4, 4, 0, 0]
- 折线图使用 smooth: true 和 areaStyle
- 所有图表必须包含 title 和 tooltip
- 背景设为透明
- 容器高度 320px

## 注意事项
- 如果用户没有明确指定表，根据字段名推断最合适的表
- 分析文字要专业、有洞察
- 只返回纯 JSON，不要包含 ```json 等标记
"""


# ============================================================================
# Nodes
# ============================================================================

async def load_context_node(state: DataAgentState) -> dict:
    """加载数据库 Schema 和用户数据权限。"""
    data_source = await bi_service.get_data_source(state.get("data_source_id"))
    schema = await bi_service.get_schema(data_source)
    permission = await DataPermissionApplier.get_permission(
        state.get("user_id"), state.get("data_source_id")
    )
    schema = DataPermissionApplier.filter_schema(schema, permission)
    allowed_tables = list(schema.keys())
    metadata = (data_source.schema_metadata or {}) if data_source else {}
    return {
        "schema": schema,
        "schema_metadata": metadata,
        "allowed_tables": allowed_tables,
    }


async def classify_intent_node(state: DataAgentState) -> dict:
    """判断用户意图：SQL 查询 / 直接分析 / 需要澄清。"""
    query = state["query"]
    llm_config = state.get("llm_config")

    system = (
        "判断用户意图类型，只回复一个单词："
        "sql_query（需要从数据库查询数据）/ direct（不需要查询，直接分析建议）/ clarify（需要澄清）"
    )
    try:
        result = await llm_service.generate(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"用户问题：{query}"},
            ],
            temperature=0,
            max_tokens=20,
            user_config=llm_config,
        )
        intent = result.strip().lower().split()[0]
        if intent not in ("sql_query", "direct", "clarify"):
            intent = "sql_query"
    except Exception:
        intent = "sql_query"
    return {"intent": intent}


async def generate_sql_node(state: DataAgentState) -> dict:
    """使用 LLM 生成 SQL 查询和初步分析。"""
    query = state["query"]
    schema = state.get("schema", {})
    allowed_tables = state.get("allowed_tables", [])
    llm_config = state.get("llm_config")

    schema_text = bi_service.format_schema_for_llm(
        schema, allowed_tables, state.get("schema_metadata")
    )

    messages = [
        {"role": "system", "content": DATA_AGENT_SYSTEM_PROMPT},
        {"role": "system", "content": f"当前数据库表结构:\n\n{schema_text}"},
        {"role": "user", "content": query},
    ]

    raw = await llm_service.generate(messages, temperature=0.3, max_tokens=4096, user_config=llm_config)

    try:
        result = _extract_json(raw)
    except Exception:
        return {
            "generated_sql": "",
            "analysis": raw,
            "charts": [],
            "tables": [],
            "error": "JSON 解析失败",
        }

    return {
        "generated_sql": result.get("sql", ""),
        "analysis": result.get("analysis", ""),
        "charts": result.get("charts", []),
        "tables": result.get("tables", []),
    }


async def validate_and_execute_node(state: DataAgentState) -> dict:
    """校验 SQL 安全性并执行查询。"""
    sql = state.get("generated_sql", "")
    if not sql:
        return {"query_result": None}

    permission = await DataPermissionApplier.get_permission(
        state.get("user_id"), state.get("data_source_id")
    )
    try:
        DataPermissionApplier.validate_tables(sql, permission)
        sql = DataPermissionApplier.inject_row_filters(sql, permission)
    except HTTPException as e:
        return {"query_result": None, "error": e.detail}

    data_source = await bi_service.get_data_source(state.get("data_source_id"))
    try:
        result = await bi_service.execute_query(
            sql,
            user_id=state.get("user_id"),
            data_source=data_source,
            natural_language_query=state.get("query"),
        )
        return {"query_result": result}
    except Exception as e:
        return {
            "query_result": None,
            "error": str(e),
        }


async def refine_visualization_node(state: DataAgentState) -> dict:
    """根据真实查询结果重新生成图表配置。"""
    query_result = state.get("query_result")
    if not query_result or not query_result.get("rows"):
        return {}

    llm_config = state.get("llm_config")

    refine_prompt = f"""SQL 已执行成功，查询结果如下：

表头: {query_result['columns']}
前 20 行数据:
{json.dumps(query_result['rows'][:20], ensure_ascii=False, indent=2)}

请根据以上真实数据重新生成图表配置（ECharts option），确保数据与查询结果一致。
只返回 JSON 格式，包含 analysis、charts、tables 三个字段。"""

    refine_messages = [
        {"role": "system", "content": DATA_AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": refine_prompt},
    ]

    try:
        refined_raw = await llm_service.generate(refine_messages, temperature=0.3, max_tokens=4096, user_config=llm_config)
        refined = _extract_json(refined_raw)
        return {
            "analysis": refined.get("analysis", state.get("analysis", "")),
            "charts": refined.get("charts", []),
            "tables": refined.get("tables", []),
        }
    except Exception:
        # 二次生成失败，保留第一次的结果
        return {}


async def direct_analysis_node(state: DataAgentState) -> dict:
    """不需要查询数据库，直接给出分析建议。"""
    query = state["query"]
    llm_config = state.get("llm_config")

    system = "你是一位数据分析师。用户提出了一个分析需求，请给出专业的分析思路和建议。"
    try:
        analysis = await llm_service.generate(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": query},
            ],
            temperature=0.7,
            max_tokens=2000,
            user_config=llm_config,
        )
    except Exception as e:
        analysis = f"分析生成失败: {str(e)}"

    return {
        "analysis": analysis,
        "generated_sql": "",
        "query_result": None,
        "charts": [],
        "tables": [],
    }


async def clarification_node(state: DataAgentState) -> dict:
    """需要用户澄清。"""
    return {
        "analysis": "我不太确定您的分析需求，能否请您再详细描述一下？例如：\n1. 您想分析哪个时间段的数据？\n2. 需要哪些维度的对比？\n3. 希望以什么形式展示结果（图表/表格）？",
        "generated_sql": "",
        "query_result": None,
        "charts": [],
        "tables": [],
    }


# ============================================================================
# Router
# ============================================================================

def intent_router(state: DataAgentState) -> str:
    intent = state.get("intent", "sql_query")
    if intent == "clarify":
        return "clarify"
    if intent == "direct":
        return "direct"
    return "generate_sql"


# ============================================================================
# Build Graph
# ============================================================================

def build_data_agent_graph() -> StateGraph:
    workflow = StateGraph(DataAgentState)

    workflow.add_node("load_context", load_context_node)
    workflow.add_node("classify", classify_intent_node)
    workflow.add_node("generate_sql", generate_sql_node)
    workflow.add_node("validate_and_execute", validate_and_execute_node)
    workflow.add_node("refine_visualization", refine_visualization_node)
    workflow.add_node("direct_analysis", direct_analysis_node)
    workflow.add_node("clarification", clarification_node)

    workflow.add_edge(START, "load_context")
    workflow.add_edge("load_context", "classify")
    workflow.add_conditional_edges(
        "classify",
        intent_router,
        {
            "generate_sql": "generate_sql",
            "direct": "direct_analysis",
            "clarify": "clarification",
        },
    )
    workflow.add_edge("generate_sql", "validate_and_execute")
    workflow.add_edge("validate_and_execute", "refine_visualization")
    workflow.add_edge("refine_visualization", END)
    workflow.add_edge("direct_analysis", END)
    workflow.add_edge("clarification", END)

    return workflow.compile()


data_agent_graph = build_data_agent_graph()


# ============================================================================
# Data Agent Service
# ============================================================================

class DataAgentService:
    """Data Agent 高层服务，支持流式输出。"""

    async def analyze(
        self,
        query: str,
        user_id: str = "default",
        data_source_id: Optional[str] = None,
        llm_config: Optional[dict] = None,
        conversation_history: Optional[List[dict]] = None,
    ) -> AsyncIterator[dict]:
        """执行数据分析流，产生 SSE 兼容的流式数据块。

        Yields:
            dict: {type: str, data: Any}
                - type="sql": 生成的 SQL 字符串
                - type="query_result": 查询结果 {columns, rows, row_count}
                - type="analysis": 分析文字
                - type="chart": 图表配置 {title, type, option}
                - type="table": 表格配置 {title, headers, rows}
                - type="error": 错误信息
                - type="done": 结束标记
        """
        state = DataAgentState(
            messages=conversation_history or [],
            query=query,
            user_id=user_id,
            llm_config=llm_config,
            data_source_id=data_source_id,
            schema={},
            schema_metadata=None,
            allowed_tables=[],
            intent="",
            generated_sql="",
            query_result=None,
            analysis="",
            charts=[],
            tables=[],
            error=None,
        )

        # 执行 LangGraph 工作流
        result = await data_agent_graph.ainvoke(state)

        # 流式输出结果
        if result.get("generated_sql"):
            yield {"type": "sql", "data": result["generated_sql"]}

        if result.get("query_result"):
            yield {"type": "query_result", "data": result["query_result"]}

        if result.get("error"):
            yield {"type": "error", "data": result["error"]}

        if result.get("analysis"):
            yield {"type": "analysis", "data": result["analysis"]}

        for chart in result.get("charts", []):
            yield {"type": "chart", "data": chart}

        for table in result.get("tables", []):
            yield {"type": "table", "data": table}

        yield {"type": "done", "data": None}


# ============================================================================
# Utils
# ============================================================================

def _extract_json(text: str) -> dict:
    """从 LLM 返回的文本中提取 JSON。"""
    cleaned = re.sub(r"```json\s*", "", text)
    cleaned = re.sub(r"```\s*", "", cleaned)
    cleaned = cleaned.strip()
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        return json.loads(match.group())
    return json.loads(cleaned)


data_agent_service = DataAgentService()
