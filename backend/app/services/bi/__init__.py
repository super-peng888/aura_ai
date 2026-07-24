"""BI Service 包 — Data Agent 核心服务层。

由 app/services/bi_service.py 拆分而来，职责分离：
- connections: 连接配置加解密 / 掩码
- validator: SQL AST 白名单校验（只允许 SELECT）
- schema: 数据库 Schema 自省与缓存
- executor: 只读查询执行、结果缓存、性能审计
- connector: 多数据源连接管理
- permission: 行级数据权限
- facade: BIService 统一服务入口与 bi_service 单例

内部依赖单向：facade → {validator, schema, executor, connector, permission}。
"""

from app.services.bi.connections import (
    _decrypt_connection_config,
    _encrypt_connection_config,
    _mask_connection_config,
)
from app.services.bi._helpers import _build_sync_runner, _run_with_timeout
from app.services.bi.validator import SQLSecurityValidator
from app.services.bi.schema import SchemaManager
from app.services.bi.executor import QueryExecutor
from app.services.bi.connector import DataSourceConnector
from app.services.bi.permission import DataPermissionApplier, _extract_tables
from app.services.bi.facade import BIService, bi_service

__all__ = [
    "BIService",
    "bi_service",
    "SQLSecurityValidator",
    "SchemaManager",
    "QueryExecutor",
    "DataSourceConnector",
    "DataPermissionApplier",
    "_encrypt_connection_config",
    "_decrypt_connection_config",
    "_mask_connection_config",
    "_run_with_timeout",
    "_build_sync_runner",
    "_extract_tables",
]
