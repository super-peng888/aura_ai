"""向后兼容 shim — 实现已拆分至 app.services.bi 包。

保留本模块路径以保证既有调用方（app/api/bi.py、app/core/data_agent.py 等）
`from app.services.bi_service import ...` 零改动继续可用。
"""

from app.services.bi import (  # noqa: F401
    BIService,
    DataPermissionApplier,
    DataSourceConnector,
    QueryExecutor,
    SQLSecurityValidator,
    SchemaManager,
    _build_sync_runner,
    _decrypt_connection_config,
    _encrypt_connection_config,
    _extract_tables,
    _mask_connection_config,
    _run_with_timeout,
    bi_service,
)
