"""Health check endpoints with real dependency probes."""

from fastapi import APIRouter
from app.models.schemas import BaseResponse
from app.db.base import engine
from app.storage.milvus_client import milvus_client

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    return BaseResponse(data={"status": "healthy", "service": "aura-ai-enterprise"})


@router.get("/ready")
async def readiness_check():
    pg_status = "unknown"
    milvus_status = "unknown"

    try:
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        pg_status = "connected"
    except Exception as e:
        pg_status = f"error: {e}"

    try:
        milvus_client.connect()
        milvus_status = "connected"
    except Exception as e:
        milvus_status = f"error: {e}"

    return BaseResponse(
        data={
            "status": "ready",
            "dependencies": {
                "postgresql": pg_status,
                "milvus": milvus_status,
            },
        }
    )
