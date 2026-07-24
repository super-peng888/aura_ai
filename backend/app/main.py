"""FastAPI application entry point."""

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.storage.milvus_client import milvus_client
from app.services.memory_service import memory_service
from app.api import chat, documents, health, auth, users, uploads, categories, audit, roles, conversations, dashboard, prompt_templates, parse_strategies, bi, retrieval_config, parse_config
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

    if settings.ENABLE_MEM0:
        await memory_service.init()
        if memory_service.is_ready():
            print("Mem0 memory service initialized")
        else:
            print("Warning: Mem0 initialization failed or disabled", file=sys.stderr)

    yield

    print("Shutting down...")
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
app.include_router(retrieval_config.router, prefix="/api/v1")
app.include_router(parse_config.router, prefix="/api/v1")


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
