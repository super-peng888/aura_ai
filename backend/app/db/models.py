"""SQLAlchemy ORM models."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    String,
    Integer,
    Text,
    DateTime,
    ForeignKey,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID

from app.db.base import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(100))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500))
    role: Mapped[str] = mapped_column(String(20), default="user")
    status: Mapped[str] = mapped_column(String(20), default="active")
    # DEPRECATED: llm_config 已废弃，新逻辑使用 user_model_configs 表 + default_model_id
    llm_config: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    token_quota_monthly: Mapped[int] = mapped_column(Integer, default=1_000_000)
    token_used_monthly: Mapped[int] = mapped_column(Integer, default=0)
    token_reset_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    default_strategy_id: Mapped[Optional[str]] = mapped_column(ForeignKey("parse_strategies.id"), nullable=True)
    # 用户当前绑定的预设模型 provider: qwen / deepseek / glm / custom
    default_model_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    conversations: Mapped[List["Conversation"]] = relationship(back_populates="user", lazy="selectin")
    documents: Mapped[List["Document"]] = relationship(back_populates="user", lazy="selectin")
    parse_strategies: Mapped[List["ParseStrategy"]] = relationship(
        back_populates="user", lazy="selectin", foreign_keys="ParseStrategy.user_id"
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    original_name: Mapped[str] = mapped_column(String(256), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    oss_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    category_id: Mapped[Optional[str]] = mapped_column(ForeignKey("categories.id"), nullable=True)
    parse_status: Mapped[str] = mapped_column(String(20), default="pending")
    parse_error: Mapped[Optional[str]] = mapped_column(Text)
    parse_mode: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    chunk_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chunk_overlap: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    dimension: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    strategy_id: Mapped[Optional[str]] = mapped_column(ForeignKey("parse_strategies.id"), nullable=True)
    page_count: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    user: Mapped[Optional["User"]] = relationship(back_populates="documents")
    category: Mapped[Optional["Category"]] = relationship(back_populates="documents")
    strategy: Mapped[Optional["ParseStrategy"]] = relationship(back_populates="documents", lazy="selectin")
    chunks: Mapped[List["DocumentChunk"]] = relationship(back_populates="document", lazy="selectin", cascade="all, delete-orphan")
    images: Mapped[List["DocumentImage"]] = relationship(back_populates="document", lazy="selectin", cascade="all, delete-orphan")
    parse_tasks: Mapped[List["ParseTask"]] = relationship(back_populates="document", lazy="selectin", cascade="all, delete-orphan")
    versions: Mapped[List["DocumentVersion"]] = relationship(back_populates="document", lazy="selectin", cascade="all, delete-orphan")
    quality_scores: Mapped[List["DocumentQualityScore"]] = relationship(back_populates="document", lazy="selectin", cascade="all, delete-orphan")


class ParseStrategy(Base):
    __tablename__ = "parse_strategies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    is_default: Mapped[bool] = mapped_column(default=False)
    # 解析模式: pymupdf | pymupdf_rich | vlm | ocr
    parse_mode: Mapped[str] = mapped_column(String(32), default="pymupdf")
    # 分片参数
    chunk_size: Mapped[int] = mapped_column(Integer, default=800)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=100)
    dimension: Mapped[int] = mapped_column(Integer, default=1536)
    # 切分方式: sentence | token | structured
    split_method: Mapped[str] = mapped_column(String(32), default="sentence")
    # 是否提取图片（仅 pymupdf_rich 模式下有效）
    extract_images: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    user: Mapped[Optional["User"]] = relationship(
        back_populates="parse_strategies", lazy="selectin", foreign_keys="ParseStrategy.user_id"
    )
    documents: Mapped[List["Document"]] = relationship(back_populates="strategy", lazy="selectin")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("categories.id"), nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    parent: Mapped[Optional["Category"]] = relationship(remote_side="Category.id", back_populates="children")
    children: Mapped[List["Category"]] = relationship(back_populates="parent", lazy="selectin", cascade="all, delete-orphan")
    documents: Mapped[List["Document"]] = relationship(back_populates="category", lazy="selectin")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    milvus_id: Mapped[str] = mapped_column(String(64), nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    image_ids: Mapped[Optional[List[str]]] = mapped_column(JSONB, default=list)
    chunk_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    search_vector: Mapped[Optional[str]] = mapped_column(TSVECTOR)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    document: Mapped["Document"] = relationship(back_populates="chunks")


class DocumentImage(Base):
    __tablename__ = "images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    oss_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(1024))
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    format: Mapped[Optional[str]] = mapped_column(String(20))
    caption: Mapped[Optional[str]] = mapped_column(Text)
    image_ref_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    ocr_text: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    image_type: Mapped[Optional[str]] = mapped_column(String(32))
    alt_text: Mapped[Optional[str]] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    document: Mapped["Document"] = relationship(back_populates="images")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    model_id: Mapped[str] = mapped_column(String(50), default="gpt-4o")
    is_shared: Mapped[bool] = mapped_column(default=False)
    share_token: Mapped[Optional[str]] = mapped_column(String(36), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[List["Message"]] = relationship(back_populates="conversation", lazy="selectin", cascade="all, delete-orphan", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citation_ids: Mapped[Optional[List[str]]] = mapped_column(JSONB, default=list)
    image_ids: Mapped[Optional[List[str]]] = mapped_column(JSONB, default=list)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    model_id: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class ParseTask(Base):
    __tablename__ = "parse_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    result_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    document: Mapped["Document"] = relationship(back_populates="parse_tasks")


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    oss_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    document: Mapped["Document"] = relationship(back_populates="versions")


class DocumentQualityScore(Base):
    __tablename__ = "document_quality_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)
    parse_score: Mapped[Optional[int]] = mapped_column(Integer)
    chunk_score: Mapped[Optional[int]] = mapped_column(Integer)
    retrieval_score: Mapped[Optional[int]] = mapped_column(Integer)
    overall_score: Mapped[Optional[int]] = mapped_column(Integer)
    details: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    document: Mapped["Document"] = relationship(back_populates="quality_scores")


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(50))
    is_system: Mapped[bool] = mapped_column(default=False)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(50))
    resource_id: Mapped[Optional[str]] = mapped_column(String(36))
    details: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    # 权限类型：menu（菜单）、button（按钮）、api（接口）
    type: Mapped[str] = mapped_column(String(20), default="api")
    # 菜单专用字段
    path: Mapped[Optional[str]] = mapped_column(String(200))
    icon: Mapped[Optional[str]] = mapped_column(String(50))
    parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("permissions.id"), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    hidden: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    children: Mapped[List["Permission"]] = relationship(
        back_populates="parent",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    parent: Mapped[Optional["Permission"]] = relationship(
        back_populates="children",
        remote_side="Permission.id",
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), nullable=False)
    permission_id: Mapped[str] = mapped_column(ForeignKey("permissions.id"), nullable=False)

    role: Mapped["Role"] = relationship(lazy="selectin")
    permission: Mapped["Permission"] = relationship(lazy="selectin")


class UserRole(Base):
    __tablename__ = "user_roles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), nullable=False)

    user: Mapped["User"] = relationship(lazy="selectin")
    role: Mapped["Role"] = relationship(lazy="selectin")


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(32), default="postgresql")
    connection_config: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    # 人工维护的 Schema 元数据：表/字段别名、注释、枚举、关系、指标等
    schema_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(default=True)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class BIQueryLog(Base):
    __tablename__ = "bi_query_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    data_source_id: Mapped[Optional[str]] = mapped_column(ForeignKey("data_sources.id"), nullable=True)
    natural_language_query: Mapped[Optional[str]] = mapped_column(Text)
    generated_sql: Mapped[Optional[str]] = mapped_column(Text)
    query_result_summary: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    execution_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="success")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class BIReport(Base):
    __tablename__ = "bi_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="未命名报表")
    description: Mapped[Optional[str]] = mapped_column(Text)
    query_log_id: Mapped[Optional[str]] = mapped_column(ForeignKey("bi_query_logs.id"), nullable=True)
    chart_configs: Mapped[Optional[List[dict]]] = mapped_column(JSONB, default=list)
    is_shared: Mapped[bool] = mapped_column(default=False)
    share_token: Mapped[Optional[str]] = mapped_column(String(36), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class UserModelConfig(Base):
    __tablename__ = "user_model_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(100))
    api_key: Mapped[Optional[str]] = mapped_column(String(500))  # Fernet 加密存储
    base_url: Mapped[Optional[str]] = mapped_column(String(500))
    max_tokens: Mapped[Optional[int]] = mapped_column(Integer, default=4096)
    temperature: Mapped[Optional[float]] = mapped_column(default=0.7)
    top_p: Mapped[Optional[float]] = mapped_column(default=0.9)
    timeout: Mapped[Optional[int]] = mapped_column(Integer, default=60)
    is_current: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class SystemRetrievalConfig(Base):
    __tablename__ = "system_retrieval_config"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # 注：本表另有 12 个历史遗留列（reranker_model/api_key/base_url、embedding_model/
    # base_url/api_key/dim、reranker provider 死键 + 两个 top_k 死键 + corrective loop 两键），
    # DB 列保留不迁移，代码面不再映射读写（模型类配置已收回 config.py 系统级维护 /
    # reranker 已改通用 HTTP 端点 / 检索路径从不使用 / corrective loop 已下线）。
    rerank_top_k: Mapped[Optional[int]] = mapped_column(Integer)
    similarity_threshold: Mapped[Optional[float]] = mapped_column()
    enable_query_rewrite: Mapped[Optional[bool]] = mapped_column()
    enable_keyword_search: Mapped[Optional[bool]] = mapped_column()
    enable_vector_search: Mapped[Optional[bool]] = mapped_column()
    enable_rerank: Mapped[Optional[bool]] = mapped_column()
    rag_mode: Mapped[Optional[str]] = mapped_column(String(20))  # RAG 模式：pipeline / agentic（NULL=pipeline）
    enable_graph_rag: Mapped[Optional[bool]] = mapped_column()  # GraphRAG 图检索融合开关（NULL=关闭）
    graph_search_mode: Mapped[Optional[str]] = mapped_column(String(20))  # 图检索模式：auto / local / global（NULL=auto）
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class SystemParseConfig(Base):
    """系统级解析配置（单行表）：VLM 视觉解析模型，admin 在配置中心维护。

    vlm_api_key 使用 Fernet 加密存储（复用 llm_service 的加解密工具）；
    字段为 NULL 时回落 config.py 的 VLM_* 环境变量默认值。
    """

    __tablename__ = "system_parse_config"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    vlm_model: Mapped[Optional[str]] = mapped_column(String(100))  # 默认 qwen3-vl-flash
    vlm_base_url: Mapped[Optional[str]] = mapped_column(String(512))
    vlm_api_key: Mapped[Optional[str]] = mapped_column(Text)  # Fernet 加密
    vlm_detail_level: Mapped[Optional[str]] = mapped_column(String(10))  # high / low
    vlm_max_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class DataPermission(Base):
    __tablename__ = "data_permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    data_source_id: Mapped[Optional[str]] = mapped_column(ForeignKey("data_sources.id"), nullable=True)
    allowed_tables: Mapped[Optional[List[str]]] = mapped_column(JSONB, default=list)
    allowed_columns: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    # 行级过滤条件，格式：{"table_name": "tenant_id = 'xxx'"}
    row_filters: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class KGEntity(Base):
    """GraphRAG 知识图谱实体。"""

    __tablename__ = "kg_entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    # 归一化名称（大小写折叠/去空白/全半角统一），同名实体据此合并
    name_normalized: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class KGRelation(Base):
    """GraphRAG 知识图谱实体间关系。"""

    __tablename__ = "kg_relations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    weight: Mapped[float] = mapped_column(default=1.0)
    # 产生该关系的 chunk（重建文档图谱时据此清理）
    chunk_id: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class KGChunkEntity(Base):
    """chunk 与实体的多对多关联（检索侧据此做实体 -> chunk 映射）。"""

    __tablename__ = "kg_chunk_entities"

    chunk_id: Mapped[str] = mapped_column(Text, primary_key=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kg_entities.id", ondelete="CASCADE"), primary_key=True
    )
    doc_id: Mapped[Optional[str]] = mapped_column(Text)


class KGCommunity(Base):
    """GraphRAG 社区（louvain 检测结果 + LLM 摘要，整体重写）。"""

    __tablename__ = "kg_communities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    community_key: Mapped[Optional[str]] = mapped_column(Text)
    title: Mapped[Optional[str]] = mapped_column(Text)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    entity_count: Mapped[Optional[int]] = mapped_column(Integer)
    entity_ids: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
