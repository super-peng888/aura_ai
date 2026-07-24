"""数据源连接器：多数据源连接管理。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.config import get_settings
from app.services.bi.connections import _decrypt_connection_config

settings = get_settings()


class DataSourceConnector:
    """多数据源连接管理器。"""

    _engines: Dict[str, Engine] = {}

    @classmethod
    def get_engine(cls, data_source: Optional[Any] = None) -> Engine:
        """获取数据源对应的 SQLAlchemy Engine。

        每个数据源使用独立的连接池，实现资源隔离。
        连接池参数优先读取数据源配置，否则使用系统默认值。

        Args:
            data_source: DataSource ORM 对象或 None（使用默认主库）
        """
        if data_source is None:
            # 默认使用主库（但注意主库 engine 是 asyncpg，需要同步 wrapper）
            return cls._get_default_sync_engine()

        source_id = str(data_source.id)
        if source_id in cls._engines:
            return cls._engines[source_id]

        cfg = _decrypt_connection_config(data_source.connection_config or {})
        source_type = (data_source.type or "postgresql").lower()

        # 连接池隔离配置（按数据源可配）
        pool_size = max(1, int(cfg.get("pool_size", settings.BI_DEFAULT_POOL_SIZE)))
        max_overflow = max(0, int(cfg.get("max_overflow", settings.BI_DEFAULT_MAX_OVERFLOW)))
        pool_recycle = max(0, int(cfg.get("pool_recycle", settings.BI_DEFAULT_POOL_RECYCLE)))
        pool_timeout = max(1, int(cfg.get("pool_timeout", settings.BI_DEFAULT_POOL_TIMEOUT)))

        if source_type == "postgresql":
            dsn = (
                f"postgresql+psycopg2://{cfg.get('user')}:{cfg.get('password')}"
                f"@{cfg.get('host')}:{cfg.get('port', 5432)}/{cfg.get('database')}"
            )
        elif source_type == "mysql":
            dsn = (
                f"mysql+pymysql://{cfg.get('user')}:{cfg.get('password')}"
                f"@{cfg.get('host')}:{cfg.get('port', 3306)}/{cfg.get('database')}"
            )
        else:
            raise HTTPException(status_code=400, detail=f"暂不支持的数据源类型: {source_type}")

        engine = create_engine(
            dsn,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_recycle=pool_recycle,
            pool_timeout=pool_timeout,
        )
        cls._engines[source_id] = engine
        return engine

    @classmethod
    def _get_default_sync_engine(cls) -> Engine:
        """为主库创建一个独立的同步引擎，避免 BI 查询占满主库 async 连接池。"""
        cache_key = "__default_sync__"
        if cache_key in cls._engines:
            return cls._engines[cache_key]

        # 从 asyncpg DSN 转换为同步 DSN（psycopg2）
        dsn = settings.pg_dsn.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
        engine = create_engine(
            dsn,
            pool_pre_ping=True,
            pool_size=max(1, settings.PG_POOL_SIZE // 4),
            max_overflow=2,
            pool_recycle=settings.BI_DEFAULT_POOL_RECYCLE,
            pool_timeout=settings.BI_DEFAULT_POOL_TIMEOUT,
        )
        cls._engines[cache_key] = engine
        return engine

    @classmethod
    def remove_engine(cls, source_id: str) -> None:
        """移除并关闭数据源连接。"""
        engine = cls._engines.pop(source_id, None)
        if engine:
            engine.dispose()
