"""Data Analysis BI API — 纯路由层，业务逻辑委托给 Service。

端点：
- GET  /bi/schema          获取数据库表结构
- POST /bi/query           执行只读 SQL 查询
- POST /bi/chat            对话式数据分析（非流式）
- POST /bi/chat/stream     对话式数据分析（SSE 流式）
- POST /bi/export          导出 HTML 报告
- GET  /bi/data-sources    数据源列表
- POST /bi/data-sources    创建数据源
- GET  /bi/query-logs      查询历史
- GET  /bi/reports         报表列表
- POST /bi/reports         保存报表
"""

import json
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.models.schemas import (
    BaseResponse,
    BIChatRequest,
    BIQueryRequest,
    BIExportRequest,
    DataSourceCreate,
    DataSourceUpdate,
    DataSourceResponse,
    BIReportCreate,
    BIReportResponse,
    BIQueryLogResponse,
    DataPermissionCreate,
    DataPermissionUpdate,
    DataPermissionResponse,
    SchemaMetadata,
    SchemaMetadataUpdate,
)
from app.db.models import User, DataSource, DataPermission, BIReport
from app.db.base import AsyncSessionLocal
from app.db.repository import data_source_repo, bi_query_log_repo, bi_report_repo, data_permission_repo, user_repo
from app.api.auth import get_current_user
from app.services.bi_service import bi_service, _encrypt_connection_config, _mask_connection_config
from app.core.data_agent import data_agent_service

router = APIRouter(prefix="/bi", tags=["BI"])


# ============================================================================
# Schema & Query（基础查询）
# ============================================================================

@router.get("/schema", response_model=BaseResponse)
async def get_schema(current_user: User = Depends(get_current_user)):
    """获取数据库表结构（只读元数据，带缓存）。"""
    schema = await bi_service.get_schema()
    return BaseResponse(data={"schema": schema, "table_count": len(schema)})


async def _check_data_source_access(
    session, data_source_id: str, current_user: User
) -> DataSource:
    """校验用户是否有权访问指定数据源。"""
    data_source = await data_source_repo.get(session, data_source_id)
    if not data_source:
        raise HTTPException(status_code=404, detail="数据源不存在")
    if str(data_source.user_id) != str(current_user.id) and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="无权访问该数据源")
    return data_source


def _build_data_source_response(source: DataSource) -> dict:
    """构建数据源响应（含掩码后的连接配置和 Schema 元数据）。"""
    return DataSourceResponse(
        id=str(source.id),
        name=source.name,
        type=source.type,
        connection_config=_mask_connection_config(source.connection_config or {}),
        schema_metadata=source.schema_metadata or {},
        is_active=source.is_active,
        user_id=str(source.user_id) if source.user_id else None,
        created_at=source.created_at,
        updated_at=source.updated_at,
    ).model_dump()


@router.post("/query", response_model=BaseResponse)
async def execute_query(
    request: BIQueryRequest,
    current_user: User = Depends(get_current_user),
):
    """执行只读 SQL 查询（AST 白名单校验后执行，带审计日志）。"""
    data_source = None
    if request.data_source_id:
        async with AsyncSessionLocal() as session:
            data_source = await _check_data_source_access(session, request.data_source_id, current_user)

    try:
        result = await bi_service.execute_query(
            request.sql,
            user_id=str(current_user.id),
            data_source=data_source,
            natural_language_query=None,
        )
        return BaseResponse(data=result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"查询执行失败: {str(e)}")


# ============================================================================
# Chat（对话式数据分析）
# ============================================================================

@router.post("/chat", response_model=BaseResponse)
async def bi_chat(
    request: BIChatRequest,
    current_user: User = Depends(get_current_user),
):
    """对话式数据分析：自动生成 SQL → 执行查询 → 生成图表（非流式）。"""
    user_config = current_user.llm_config or {}

    if request.data_source_id:
        async with AsyncSessionLocal() as session:
            await _check_data_source_access(session, request.data_source_id, current_user)

    chunks = []
    async for chunk in data_agent_service.analyze(
        query=request.messages[-1]["content"] if request.messages else "",
        user_id=str(current_user.id),
        data_source_id=request.data_source_id,
        llm_config=user_config,
        conversation_history=request.messages[:-1] if len(request.messages) > 1 else None,
    ):
        chunks.append(chunk)

    # 组装响应
    result = {
        "sql": "",
        "analysis": "",
        "query_result": None,
        "query_error": None,
        "charts": [],
        "tables": [],
    }
    for chunk in chunks:
        if chunk["type"] == "sql":
            result["sql"] = chunk["data"]
        elif chunk["type"] == "query_result":
            result["query_result"] = chunk["data"]
        elif chunk["type"] == "error":
            result["query_error"] = chunk["data"]
        elif chunk["type"] == "analysis":
            result["analysis"] = chunk["data"]
        elif chunk["type"] == "chart":
            result["charts"].append(chunk["data"])
        elif chunk["type"] == "table":
            result["tables"].append(chunk["data"])

    return BaseResponse(data=result)


@router.post("/chat/stream")
async def bi_chat_stream(
    request: BIChatRequest,
    current_user: User = Depends(get_current_user),
):
    """对话式数据分析 SSE 流式接口。"""
    user_config = current_user.llm_config or {}

    if request.data_source_id:
        async with AsyncSessionLocal() as session:
            await _check_data_source_access(session, request.data_source_id, current_user)

    async def event_generator():
        async for chunk in data_agent_service.analyze(
            query=request.messages[-1]["content"] if request.messages else "",
            user_id=str(current_user.id),
            data_source_id=request.data_source_id,
            llm_config=user_config,
            conversation_history=request.messages[:-1] if len(request.messages) > 1 else None,
        ):
            yield {
                "event": chunk["type"],
                "data": json.dumps(chunk["data"], ensure_ascii=False, default=str),
            }

    return EventSourceResponse(event_generator())


# ============================================================================
# Export（报告导出）
# ============================================================================

@router.post("/export", response_model=BaseResponse)
async def bi_export(
    request: BIExportRequest,
    current_user: User = Depends(get_current_user),
):
    """导出数据分析报告为 HTML 网页。"""
    html = _build_html_report(request.title, request.messages, request.charts, request.tables)
    return BaseResponse(data={"html": html})


def _build_html_report(title: str, messages: List[dict], charts: List[dict], tables: List[dict]) -> str:
    """构建可下载的 HTML 报告。"""
    import datetime as dt

    chat_html = ""
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "user":
            chat_html += f'<div class="msg user">{content}</div>\n'
        elif role == "assistant":
            chat_html += f'<div class="msg assistant">{content}</div>\n'

    chart_containers = ""
    chart_scripts = ""
    for i, chart in enumerate(charts):
        chart_id = f"chart_{i}"
        chart_containers += f'''
        <div class="chart-box">
            <div class="chart-title">{chart.get("title", f"图表 {i+1}")}</div>
            <div id="{chart_id}" class="chart-container"></div>
        </div>
        '''
        option = json.dumps(chart.get("option", {}), ensure_ascii=False)
        chart_scripts += f'''
        var chart_{i}_inst = echarts.init(document.getElementById("{chart_id}"), null, {{renderer: "canvas"}});
        chart_{i}_inst.setOption({option});
        window.addEventListener("resize", function() {{ chart_{i}_inst.resize(); }});
        '''

    table_html = ""
    for t in tables:
        headers = t.get("headers", [])
        rows = t.get("rows", [])
        ths = "".join(f"<th>{h}</th>" for h in headers)
        trs = ""
        for row in rows:
            tds = "".join(f"<td>{cell}</td>" for cell in row)
            trs += f"<tr>{tds}</tr>"
        table_html += f'''
        <div class="table-box">
            <div class="table-title">{t.get("title", "数据表格")}</div>
            <table>
                <thead><tr>{ths}</tr></thead>
                <tbody>{trs}</tbody>
            </table>
        </div>
        '''

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
:root {{ --primary: #2563eb; --bg: #fafaf9; --card: #fff; --text: #292524; --muted: #78716c; --border: #e7e5e4; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; padding: 40px 20px; }}
.container {{ max-width: 960px; margin: 0 auto; }}
h1 {{ font-size: 28px; font-weight: 700; margin-bottom: 8px; letter-spacing: -0.02em; }}
.subtitle {{ color: var(--muted); font-size: 14px; margin-bottom: 32px; }}
.msg {{ padding: 12px 16px; border-radius: 12px; margin-bottom: 12px; font-size: 14px; max-width: 80%; }}
.msg.user {{ background: var(--primary); color: white; margin-left: auto; }}
.msg.assistant {{ background: var(--card); border: 1px solid var(--border); color: var(--text); }}
.chart-box, .table-box {{ background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 20px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }}
.chart-title, .table-title {{ font-size: 16px; font-weight: 600; margin-bottom: 16px; color: var(--text); }}
.chart-container {{ width: 100%; height: 360px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); }}
th {{ background: #fafaf9; font-weight: 600; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.03em; }}
tr:hover td {{ background: #fafaf9; }}
.footer {{ text-align: center; color: var(--muted); font-size: 12px; margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border); }}
</style>
</head>
<body>
<div class="container">
<h1>{title}</h1>
<p class="subtitle">生成时间：{dt.datetime.now().strftime("%Y-%m-%d %H:%M")}</p>

<div class="chat-section" style="margin-bottom: 32px;">
{chat_html}
</div>

{chart_containers}
{table_html}

<div class="footer">由 Aura AI Enterprise 数据分析引擎生成</div>
</div>
<script>
{chart_scripts}
</script>
</body>
</html>'''


# ============================================================================
# Data Source Management（数据源管理）
# ============================================================================

@router.get("/data-sources", response_model=BaseResponse)
async def list_data_sources(current_user: User = Depends(get_current_user)):
    """获取当前用户的数据源列表。"""
    async with AsyncSessionLocal() as session:
        sources = await data_source_repo.get_by_user(session, str(current_user.id))
    return BaseResponse(data=[
        _build_data_source_response(s)
        for s in sources
    ])


@router.get("/data-sources/{source_id}", response_model=BaseResponse)
async def get_data_source(
    source_id: str,
    current_user: User = Depends(get_current_user),
):
    """获取数据源详情。"""
    async with AsyncSessionLocal() as session:
        source = await _check_data_source_access(session, source_id, current_user)
    return BaseResponse(data=_build_data_source_response(source))


@router.put("/data-sources/{source_id}", response_model=BaseResponse)
async def update_data_source(
    source_id: str,
    request: DataSourceUpdate,
    current_user: User = Depends(get_current_user),
):
    """更新数据源配置。"""
    async with AsyncSessionLocal() as session:
        source = await _check_data_source_access(session, source_id, current_user)
        if request.name is not None:
            source.name = request.name
        if request.type is not None:
            source.type = request.type
        if request.connection_config is not None:
            source.connection_config = _encrypt_connection_config(request.connection_config)
        if request.is_active is not None:
            source.is_active = request.is_active
        await session.flush()
        await session.refresh(source)
        await session.commit()
        # 关闭旧连接池，下次使用时重建
        bi_service.connector.remove_engine(str(source.id))
        await bi_service.schema_manager.invalidate_cache(str(source.id))
    return BaseResponse(data=_build_data_source_response(source))


@router.delete("/data-sources/{source_id}", response_model=BaseResponse)
async def delete_data_source(
    source_id: str,
    current_user: User = Depends(get_current_user),
):
    """删除数据源。"""
    async with AsyncSessionLocal() as session:
        source = await _check_data_source_access(session, source_id, current_user)
        await data_source_repo.delete(session, source)
        await session.commit()
        bi_service.connector.remove_engine(str(source.id))
        await bi_service.schema_manager.invalidate_cache(str(source.id))
    return BaseResponse(data={"deleted": True})


@router.post("/data-sources/{source_id}/test", response_model=BaseResponse)
async def test_data_source(
    source_id: str,
    current_user: User = Depends(get_current_user),
):
    """测试数据源连通性。"""
    async with AsyncSessionLocal() as session:
        source = await _check_data_source_access(session, source_id, current_user)
    result = await bi_service.test_connection(source)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "连接失败"))
    return BaseResponse(data=result)


@router.post("/data-sources/{source_id}/sync-schema", response_model=BaseResponse)
async def sync_data_source_schema(
    source_id: str,
    current_user: User = Depends(get_current_user),
):
    """同步并返回数据源 Schema。"""
    async with AsyncSessionLocal() as session:
        source = await _check_data_source_access(session, source_id, current_user)
    await bi_service.schema_manager.invalidate_cache(str(source.id))
    schema = await bi_service.get_schema(source)
    return BaseResponse(data={"schema": schema, "table_count": len(schema)})


@router.get("/data-sources/{source_id}/schema-metadata", response_model=BaseResponse)
async def get_schema_metadata(
    source_id: str,
    current_user: User = Depends(get_current_user),
):
    """获取数据源的 Schema 元数据（表/字段别名、注释、枚举、关系、指标）。"""
    async with AsyncSessionLocal() as session:
        source = await _check_data_source_access(session, source_id, current_user)
    metadata = source.schema_metadata or {}
    return BaseResponse(data=SchemaMetadata(**metadata).model_dump())


@router.put("/data-sources/{source_id}/schema-metadata", response_model=BaseResponse)
async def update_schema_metadata(
    source_id: str,
    request: SchemaMetadataUpdate,
    current_user: User = Depends(get_current_user),
):
    """更新数据源的 Schema 元数据。"""
    async with AsyncSessionLocal() as session:
        source = await _check_data_source_access(session, source_id, current_user)

        current_metadata = source.schema_metadata or {}
        if request.tables is not None:
            current_metadata["tables"] = request.tables
        if request.relationships is not None:
            current_metadata["relationships"] = [r.model_dump() for r in request.relationships]
        if request.metrics is not None:
            current_metadata["metrics"] = [m.model_dump() for m in request.metrics]

        source.schema_metadata = current_metadata
        await session.flush()
        await session.refresh(source)
        await session.commit()
        await bi_service.schema_manager.invalidate_cache(str(source.id))
    return BaseResponse(data=SchemaMetadata(**source.schema_metadata).model_dump())


@router.get("/data-sources/{source_id}/schema-preview", response_model=BaseResponse)
async def preview_schema_for_llm(
    source_id: str,
    current_user: User = Depends(get_current_user),
):
    """预览合并后的 Schema（即 Data Agent 传给 LLM 的文本）。"""
    async with AsyncSessionLocal() as session:
        source = await _check_data_source_access(session, source_id, current_user)
    schema = await bi_service.get_schema(source)
    schema_text = bi_service.format_schema_for_llm(
        schema, allowed_tables=list(schema.keys()), metadata=source.schema_metadata or {}
    )
    return BaseResponse(data={"schema_text": schema_text, "table_count": len(schema)})


@router.post("/data-sources", response_model=BaseResponse)
async def create_data_source(
    request: DataSourceCreate,
    current_user: User = Depends(get_current_user),
):
    """创建新数据源。"""
    async with AsyncSessionLocal() as session:
        source = await data_source_repo.create(session, DataSource(
            name=request.name,
            type=request.type,
            connection_config=_encrypt_connection_config(request.connection_config),
            is_active=request.is_active,
            user_id=str(current_user.id),
        ))
        await session.commit()
    return BaseResponse(data=_build_data_source_response(source))


# ============================================================================
# Query Logs（查询历史/审计）
# ============================================================================

# ============================================================================
# Data Permissions（数据权限管理）
# ============================================================================

@router.get("/data-permissions", response_model=BaseResponse)
async def list_data_permissions(
    data_source_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """获取数据权限列表（普通用户只能查看自己的，管理员可查看全部）。"""
    async with AsyncSessionLocal() as session:
        if current_user.role == "admin":
            permissions = await data_permission_repo.list(
                session, limit=200
            )
        else:
            permissions = await data_permission_repo.get_by_user(
                session, str(current_user.id)
            )
        # 按数据源过滤
        if data_source_id:
            permissions = [p for p in permissions if str(p.data_source_id) == data_source_id]
    return BaseResponse(data=[
        DataPermissionResponse(
            id=str(p.id),
            user_id=str(p.user_id) if p.user_id else None,
            data_source_id=str(p.data_source_id) if p.data_source_id else None,
            allowed_tables=p.allowed_tables or [],
            allowed_columns=p.allowed_columns or {},
            row_filters=p.row_filters or {},
            created_at=p.created_at,
        ).model_dump()
        for p in permissions
    ])


@router.get("/data-permissions/me", response_model=BaseResponse)
async def get_my_data_permission(
    data_source_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的数据权限。"""
    async with AsyncSessionLocal() as session:
        permission = await data_permission_repo.get_by_user_and_source(
            session, str(current_user.id), data_source_id or ""
        )
    if not permission:
        return BaseResponse(data={
            "user_id": str(current_user.id),
            "data_source_id": data_source_id,
            "allowed_tables": [],
            "allowed_columns": {},
            "row_filters": {},
        })
    return BaseResponse(data=DataPermissionResponse(
        id=str(permission.id),
        user_id=str(permission.user_id) if permission.user_id else None,
        data_source_id=str(permission.data_source_id) if permission.data_source_id else None,
        allowed_tables=permission.allowed_tables or [],
        allowed_columns=permission.allowed_columns or {},
        row_filters=permission.row_filters or {},
        created_at=permission.created_at,
    ).model_dump())


@router.post("/data-permissions", response_model=BaseResponse)
async def create_data_permission(
    request: DataPermissionCreate,
    current_user: User = Depends(get_current_user),
):
    """创建数据权限（仅管理员可操作）。"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可配置数据权限")

    async with AsyncSessionLocal() as session:
        # 校验数据源是否存在且属于指定用户
        if request.data_source_id:
            source = await data_source_repo.get(session, request.data_source_id)
            if not source:
                raise HTTPException(status_code=404, detail="数据源不存在")
        # 校验用户是否存在
        if request.user_id:
            target_user = await user_repo.get(session, request.user_id)
            if not target_user:
                raise HTTPException(status_code=404, detail="用户不存在")

        permission = await data_permission_repo.create(session, DataPermission(
            user_id=request.user_id,
            data_source_id=request.data_source_id,
            allowed_tables=request.allowed_tables,
            allowed_columns=request.allowed_columns,
            row_filters=request.row_filters,
        ))
        await session.commit()
    return BaseResponse(data=DataPermissionResponse(
        id=str(permission.id),
        user_id=str(permission.user_id) if permission.user_id else None,
        data_source_id=str(permission.data_source_id) if permission.data_source_id else None,
        allowed_tables=permission.allowed_tables or [],
        allowed_columns=permission.allowed_columns or {},
        row_filters=permission.row_filters or {},
        created_at=permission.created_at,
    ).model_dump())


@router.put("/data-permissions/{permission_id}", response_model=BaseResponse)
async def update_data_permission(
    permission_id: str,
    request: DataPermissionUpdate,
    current_user: User = Depends(get_current_user),
):
    """更新数据权限（仅管理员可操作）。"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可配置数据权限")

    async with AsyncSessionLocal() as session:
        permission = await data_permission_repo.get(session, permission_id)
        if not permission:
            raise HTTPException(status_code=404, detail="数据权限不存在")
        if request.allowed_tables is not None:
            permission.allowed_tables = request.allowed_tables
        if request.allowed_columns is not None:
            permission.allowed_columns = request.allowed_columns
        if request.row_filters is not None:
            permission.row_filters = request.row_filters
        await session.flush()
        await session.refresh(permission)
        await session.commit()
    return BaseResponse(data=DataPermissionResponse(
        id=str(permission.id),
        user_id=str(permission.user_id) if permission.user_id else None,
        data_source_id=str(permission.data_source_id) if permission.data_source_id else None,
        allowed_tables=permission.allowed_tables or [],
        allowed_columns=permission.allowed_columns or {},
        row_filters=permission.row_filters or {},
        created_at=permission.created_at,
    ).model_dump())


@router.delete("/data-permissions/{permission_id}", response_model=BaseResponse)
async def delete_data_permission(
    permission_id: str,
    current_user: User = Depends(get_current_user),
):
    """删除数据权限（仅管理员可操作）。"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可配置数据权限")

    async with AsyncSessionLocal() as session:
        permission = await data_permission_repo.get(session, permission_id)
        if not permission:
            raise HTTPException(status_code=404, detail="数据权限不存在")
        await data_permission_repo.delete(session, permission)
        await session.commit()
    return BaseResponse(data={"deleted": True})


@router.get("/query-logs", response_model=BaseResponse)
async def list_query_logs(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的查询历史。"""
    async with AsyncSessionLocal() as session:
        logs = await bi_query_log_repo.list_by_user(session, str(current_user.id), limit=limit)
    return BaseResponse(data=[
        BIQueryLogResponse(
            id=str(log.id),
            user_id=str(log.user_id) if log.user_id else None,
            data_source_id=str(log.data_source_id) if log.data_source_id else None,
            natural_language_query=log.natural_language_query,
            generated_sql=log.generated_sql,
            query_result_summary=log.query_result_summary or {},
            execution_time_ms=log.execution_time_ms,
            row_count=log.row_count,
            status=log.status,
            error_message=log.error_message,
            created_at=log.created_at,
        ).model_dump()
        for log in logs
    ])


# ============================================================================
# Reports（报表管理）
# ============================================================================

@router.get("/reports", response_model=BaseResponse)
async def list_reports(current_user: User = Depends(get_current_user)):
    """获取当前用户的报表列表。"""
    async with AsyncSessionLocal() as session:
        reports = await bi_report_repo.list_by_user(session, str(current_user.id))
    return BaseResponse(data=[
        BIReportResponse(
            id=str(r.id),
            user_id=str(r.user_id) if r.user_id else None,
            title=r.title,
            description=r.description,
            query_log_id=str(r.query_log_id) if r.query_log_id else None,
            chart_configs=r.chart_configs or [],
            is_shared=r.is_shared,
            share_token=r.share_token,
            created_at=r.created_at,
            updated_at=r.updated_at,
        ).model_dump()
        for r in reports
    ])


@router.post("/reports", response_model=BaseResponse)
async def create_report(
    request: BIReportCreate,
    current_user: User = Depends(get_current_user),
):
    """保存报表。"""
    import uuid as uuid_mod
    async with AsyncSessionLocal() as session:
        report = await bi_report_repo.create(session, BIReport(
            user_id=str(current_user.id),
            title=request.title,
            description=request.description,
            query_log_id=request.query_log_id,
            chart_configs=request.chart_configs,
            is_shared=False,
            share_token=str(uuid_mod.uuid4()),
        ))
        await session.commit()
    return BaseResponse(data=BIReportResponse(
        id=str(report.id),
        user_id=str(report.user_id) if report.user_id else None,
        title=report.title,
        description=report.description,
        query_log_id=str(report.query_log_id) if report.query_log_id else None,
        chart_configs=report.chart_configs or [],
        is_shared=report.is_shared,
        share_token=report.share_token,
        created_at=report.created_at,
        updated_at=report.updated_at,
    ).model_dump())
