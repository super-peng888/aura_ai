"""FastAPI application entry point."""

import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.storage.milvus_client import milvus_client
from app.services.memory_service import memory_service
from app.api import chat, documents, health, auth, users, uploads, categories, audit, roles, conversations, dashboard, prompt_templates, parse_strategies, bi, retrieval_config, model_providers, mcp_servers, usage
from app.middleware.audit_middleware import AuditMiddleware

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")

    try:
        milvus_client.init()
        print("Milvus connected successfully")
    except Exception as e:
        print(f"Warning: Milvus connection failed: {e}", file=sys.stderr)

    # 兑底：重置上次进程遗留的 "running" 文档。解析由 BackgroundTasks 在 API
    # 进程内执行，进程一旦重启/崩溃，在飞任务被杀且永远回不到终态，
    # 前端会一直显示“解析中”。仅重置 running；indexing 归独立 index worker
    # 进程处理，不在此动。
    try:
        from sqlalchemy import update
        from app.db.models import Document
        from app.db.base import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                update(Document)
                .where(Document.parse_status == "running")
                .values(parse_status="failed", parse_error="解析进程中断（服务重启），请重新解析")
            )
            await session.commit()
            if result.rowcount:
                print(f"Reset {result.rowcount} stale 'running' document(s) to 'failed'")
    except Exception as e:
        print(f"Warning: reset stale running documents failed: {e}", file=sys.stderr)

    if settings.ENABLE_MEM0:
        await memory_service.init()
        if memory_service.is_ready():
            print("Mem0 memory service initialized")
        else:
            print("Warning: Mem0 initialization failed or disabled", file=sys.stderr)

    # 供应商/模型/角色指派历史迁移与兼底种子（幂等，新表有数据即跳过）
    from app.services.system_model_service import SystemModelService
    await SystemModelService.seed_defaults()

    # 模型用量埋点 flusher：周期性把内存队列中的用量事件批量落库 + Redis 计数
    from app.services.usage_service import usage_service
    await usage_service.start()

    # 内嵌 index worker：随后端自动拉起，消费 Redis Streams 的索引任务，
    # 避免因未手动启动独立 worker 而使文档卡在“索引中”。
    worker_task = None
    if settings.INDEX_WORKER_EMBEDDED:
        from app.workers.index_worker import _consume_loop
        worker_task = asyncio.create_task(_consume_loop())
        print("Embedded index worker started")

    yield

    print("Shutting down...")
    try:
        await usage_service.stop()  # 停 flusher 并把残余用量事件落库
    except Exception as e:
        print(f"Warning: usage service shutdown error: {e}", file=sys.stderr)
    if worker_task is not None:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Warning: embedded index worker shutdown error: {e}", file=sys.stderr)
    try:
        milvus_client.disconnect()
    except Exception:
        pass


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

origins = [o.strip() for o in settings.CORS_ORIGINS.split(",")] if "," in settings.CORS_ORIGINS else [settings.CORS_ORIGINS]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 审计日志中间件（必须在 CORS 之后，以便获取真实请求信息）
app.add_middleware(AuditMiddleware)

app.include_router(health.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(uploads.router, prefix="/api/v1")
app.include_router(categories.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(roles.router, prefix="/api/v1")
app.include_router(conversations.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(prompt_templates.router, prefix="/api/v1")
app.include_router(parse_strategies.router, prefix="/api/v1")
app.include_router(bi.router, prefix="/api/v1")
app.include_router(mcp_servers.router, prefix="/api/v1")
app.include_router(retrieval_config.router, prefix="/api/v1")
app.include_router(model_providers.router, prefix="/api/v1")
app.include_router(usage.router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
