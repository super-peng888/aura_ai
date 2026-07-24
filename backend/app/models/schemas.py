"""Pydantic models for API request/response schemas."""

from typing import Any, Literal, Optional, List
from pydantic import BaseModel, Field, model_validator
from datetime import datetime
from enum import Enum


# ============================================================================
# Enums
# ============================================================================

class ParseStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    INDEXING = "indexing"
    COMPLETED = "completed"
    FAILED = "failed"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ParseMode(str, Enum):
    PYMUPDF = "pymupdf"
    PYMUPDF_RICH = "pymupdf_rich"
    VLM = "vlm"
    OCR = "ocr"
    PADDLEOCR = "paddleocr"


class SplitMethod(str, Enum):
    SENTENCE = "sentence"
    TOKEN = "token"
    STRUCTURED = "structured"


# ============================================================================
# Common
# ============================================================================

class BaseResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: Optional[Any] = None


class PaginationParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


# ============================================================================
# Content Blocks (image-aware response)
# ============================================================================

class ContentBlock(BaseModel):
    type: str  # text | image | sources
    content: Optional[str] = None
    image_id: Optional[str] = None
    url: Optional[str] = None
    alt: Optional[str] = None
    description: Optional[str] = None
    page: Optional[int] = None
    sources: Optional[list[dict]] = None


# ============================================================================
# LLM Config (user-level model configuration)
# ============================================================================

class LLMConfig(BaseModel):
    """用户级 LLM 配置模型。前端通过此模型保存/读取用户的模型参数。"""

    provider: str = Field("openai", description="模型提供者: openai / azure")
    api_key: str = Field("", description="API 密钥")
    base_url: str = Field("https://api.openai.com/v1", description="API 基础地址")
    model: str = Field("gpt-4o", description="模型名称，如 gpt-4o / gpt-4o-mini / deepseek-chat")
    temperature: float = Field(0.7, ge=0, le=2, description="采样温度")

    def mask_api_key(self) -> str:
        """返回掩码后的 API Key，用于前端展示。"""
        if len(self.api_key) <= 8:
            return "***"
        return f"{self.api_key[:4]}****{self.api_key[-4:]}"


class LLMConfigResponse(BaseModel):
    provider: str
    base_url: str
    model: str
    temperature: float
    api_key_masked: str


class DefaultModelUpdate(BaseModel):
    provider: str = Field(..., pattern=r"^(deepseek|custom)$")


class UserModelConfigCreate(BaseModel):
    """用户自定义模型配置（新增）"""
    model: str = Field("gpt-4o", max_length=100)
    api_key: str = Field("", max_length=500)
    base_url: str = Field("https://api.openai.com/v1", max_length=500)
    max_tokens: int = Field(4096, ge=1, le=128000)
    temperature: float = Field(0.7, ge=0, le=2)
    top_p: float = Field(0.9, ge=0, le=1)
    timeout: int = Field(60, ge=1, le=300)


class UserModelConfigUpdate(BaseModel):
    """用户自定义模型配置（编辑）"""
    model: str = Field("gpt-4o", max_length=100)
    api_key: str = Field("", max_length=500)
    base_url: str = Field("https://api.openai.com/v1", max_length=500)
    max_tokens: int = Field(4096, ge=1, le=128000)
    temperature: float = Field(0.7, ge=0, le=2)
    top_p: float = Field(0.9, ge=0, le=1)
    timeout: int = Field(60, ge=1, le=300)


class UserModelConfigResponse(BaseModel):
    """返回给前端的用户自定义模型配置（api_key 掩码处理）"""
    id: str
    model: str = "gpt-4o"
    base_url: str = "https://api.openai.com/v1"
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 0.9
    timeout: int = 60
    api_key_masked: str = "未配置"
    is_current: bool = False


# ============================================================================
# System Retrieval Config（系统级检索配置，admin 可配）
# ============================================================================

class RetrievalConfigUpdate(BaseModel):
    """系统级检索配置（整体 upsert，仅检索策略键；模型类配置在 config.py 系统级维护）"""
    rerank_top_k: int = Field(5, ge=1, le=100)
    similarity_threshold: float = Field(0.0, ge=0, le=1)
    enable_query_rewrite: bool = True
    enable_keyword_search: bool = True
    enable_vector_search: bool = True
    enable_rerank: bool = True
    rag_mode: Literal["pipeline", "agentic"] = "pipeline"
    enable_graph_rag: bool = False
    graph_search_mode: Literal["auto", "local", "global"] = "auto"

    @model_validator(mode="after")
    def _check_search_enabled(self):
        """向量检索与关键词检索不能同时关闭（否则检索恒为空）。"""
        if not self.enable_keyword_search and not self.enable_vector_search:
            raise ValueError("向量检索与关键词检索不能同时关闭")
        return self


class RetrievalConfigResponse(BaseModel):
    """返回给前端的系统级检索配置"""
    rerank_top_k: int = 5
    similarity_threshold: float = 0.0
    enable_query_rewrite: bool = True
    enable_keyword_search: bool = True
    enable_vector_search: bool = True
    enable_rerank: bool = True
    rag_mode: Literal["pipeline", "agentic"] = "pipeline"
    enable_graph_rag: bool = False
    graph_search_mode: Literal["auto", "local", "global"] = "auto"


class ParseConfigUpdate(BaseModel):
    """系统级解析配置（VLM 视觉解析模型）整体 upsert；vlm_api_key 留空表示保持不变。"""
    vlm_model: str = Field("qwen3-vl-flash", min_length=1, max_length=100)
    vlm_base_url: str = Field(
        "https://dashscope.aliyuncs.com/compatible-mode/v1", min_length=1, max_length=512
    )
    vlm_api_key: Optional[str] = None
    vlm_detail_level: Literal["high", "low"] = "high"
    vlm_max_tokens: int = Field(4096, ge=256, le=32768)


class ParseConfigResponse(BaseModel):
    """返回给前端的系统级解析配置（api_key 仅掩码与配置标记，不明文外发）"""
    vlm_model: str = "qwen3-vl-flash"
    vlm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    vlm_api_key_masked: str = ""
    vlm_api_key_configured: bool = False
    vlm_detail_level: str = "high"
    vlm_max_tokens: int = 4096


# ============================================================================
# Chat
# ============================================================================

class ChatAttachment(BaseModel):
    filename: str
    url: str
    mime_type: Optional[str] = None


class ChatMessage(BaseModel):
    role: MessageRole
    content: str
    image_ids: list[str] = []


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    messages: list[ChatMessage]
    model_id: Optional[str] = None
    knowledge_base_ids: list[str] = []
    attachments: list[ChatAttachment] = []
    stream: bool = True
    temperature: float = Field(0.7, ge=0, le=2)
    user_id: str = "default"


class CitationItem(BaseModel):
    chunk_id: str
    document_id: str
    content: str
    page_number: Optional[int] = None
    similarity: float


class ImageAttachment(BaseModel):
    image_id: str
    url: str
    caption: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    page_number: Optional[int] = None


class ChatStreamChunk(BaseModel):
    delta: str = ""
    citations: list[CitationItem] = []
    images: list[ImageAttachment] = []
    finish_reason: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    query_type: str = "knowledge"
    content_blocks: list[ContentBlock] = []
    images: list[ImageAttachment] = []
    sources: list[dict] = []


# ============================================================================
# Category
# ============================================================================

class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    parent_id: Optional[str] = None


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    parent_id: Optional[str] = None
    sort_order: Optional[int] = None


class CategoryResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    parent_id: Optional[str] = None
    user_id: Optional[str] = None
    sort_order: int = 0
    created_at: datetime
    updated_at: datetime


class CategoryTreeNode(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    parent_id: Optional[str] = None
    user_id: Optional[str] = None
    sort_order: int = 0
    doc_count: int = 0
    children: List["CategoryTreeNode"] = []
    created_at: datetime


# ============================================================================
# Document
# ============================================================================

class DocumentUploadRequest(BaseModel):
    document_id: Optional[str] = None
    filename: str
    original_name: str
    file_size: int
    mime_type: str
    oss_url: str
    user_id: Optional[str] = None
    category_id: Optional[str] = None
    auto_parse: Optional[bool] = False


class BatchDeleteRequest(BaseModel):
    document_ids: list[str]


class BatchMoveRequest(BaseModel):
    document_ids: list[str]
    category_id: Optional[str] = None


class DocumentVersionResponse(BaseModel):
    id: str
    document_id: str
    version: int
    oss_url: str
    file_size: Optional[int] = None
    created_at: datetime


class DocumentResponse(BaseModel):
    id: str
    filename: str
    original_name: str
    file_size: int
    mime_type: str
    oss_url: str
    parse_status: ParseStatus
    parse_mode: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    dimension: Optional[int] = None
    strategy_id: Optional[str] = None
    page_count: Optional[int] = None
    category_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ChunkItem(BaseModel):
    chunk_id: str
    page: int
    content: str
    image_ids: List[str] = []
    heading: str = ""
    chunk_type: str = "text"


class DocumentParseRequest(BaseModel):
    """触发解析时的可选策略覆盖。全部为空时按 document.strategy_id > 用户默认 > 系统默认解析。"""
    strategy_id: Optional[str] = None
    parse_mode: Optional[ParseMode] = None
    chunk_size: Optional[int] = Field(None, ge=100, le=4000)
    chunk_overlap: Optional[int] = Field(None, ge=0, le=1000)
    split_method: Optional[SplitMethod] = None
    extract_images: Optional[bool] = None


class ChunkPreviewRequest(BaseModel):
    strategy_id: Optional[str] = None
    parse_mode: Optional[ParseMode] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    split_method: Optional[SplitMethod] = None
    extract_images: Optional[bool] = None


class ChunkPreviewResponse(BaseModel):
    chunks: List[ChunkItem]
    page_count: int
    total_images: int
    mode_used: str = "pymupdf"


# ============================================================================
# Parse Strategy
# ============================================================================

class ParseStrategyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    parse_mode: ParseMode = ParseMode.PYMUPDF
    chunk_size: int = Field(800, ge=100, le=4000)
    chunk_overlap: int = Field(100, ge=0, le=1000)
    dimension: int = Field(1536, ge=128, le=4096)
    split_method: SplitMethod = SplitMethod.SENTENCE
    extract_images: bool = False


class ParseStrategyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    parse_mode: Optional[ParseMode] = None
    chunk_size: Optional[int] = Field(None, ge=100, le=4000)
    chunk_overlap: Optional[int] = Field(None, ge=0, le=1000)
    dimension: Optional[int] = Field(None, ge=128, le=4096)
    split_method: Optional[SplitMethod] = None
    extract_images: Optional[bool] = None
    is_default: Optional[bool] = None


class ParseStrategyResponse(BaseModel):
    id: str
    name: str
    user_id: Optional[str] = None
    is_default: bool = False
    parse_mode: str
    chunk_size: int
    chunk_overlap: int
    dimension: int
    split_method: str
    extract_images: bool
    created_at: datetime
    updated_at: datetime


class ParseTaskResponse(BaseModel):
    id: str
    document_id: str
    status: ParseStatus
    progress: int
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class DocumentChunkResponse(BaseModel):
    id: str
    document_id: str
    content: str
    page_number: Optional[int] = None
    chunk_index: int
    image_ids: list[str] = []


class ImageResponse(BaseModel):
    id: str
    document_id: str
    page_number: Optional[int] = None
    oss_url: str
    thumbnail_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    caption: Optional[str] = None
    image_ref_id: str


# ============================================================================
# RAG Search (Debug)
# ============================================================================

class SearchRequest(BaseModel):
    query: str
    knowledge_base_ids: list[str] = []
    document_ids: list[str] = []
    top_k: int = 10
    filters: dict[str, Any] = {}


class SearchResultItem(BaseModel):
    chunk_id: str
    document_id: str
    content: str
    page_number: Optional[int] = None
    score: float
    search_type: str
    image_ids: list[str] = []


class SearchResponse(BaseModel):
    query: str
    rewritten_query: Optional[str] = None
    results: list[SearchResultItem]


# ============================================================================
# RBAC
# ============================================================================

class RoleResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: datetime


class PermissionCreateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    type: str = Field("api", pattern=r"^(menu|api|button)$")
    path: Optional[str] = Field(None, max_length=200)
    icon: Optional[str] = Field(None, max_length=50)
    parent_id: Optional[str] = None
    sort_order: int = Field(0, ge=0)
    hidden: bool = False


class PermissionUpdateRequest(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=100)
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    type: Optional[str] = Field(None, pattern=r"^(menu|api|button)$")
    path: Optional[str] = Field(None, max_length=200)
    icon: Optional[str] = Field(None, max_length=50)
    parent_id: Optional[str] = None
    sort_order: Optional[int] = Field(None, ge=0)
    hidden: Optional[bool] = None


class PermissionResponse(BaseModel):
    id: str
    code: str
    name: str
    description: Optional[str] = None
    type: str = "api"
    path: Optional[str] = None
    icon: Optional[str] = None
    parent_id: Optional[str] = None
    sort_order: int = 0
    hidden: bool = False
    created_at: datetime


class UserRoleUpdate(BaseModel):
    role: str = Field(..., pattern=r"^(admin|user)$")


# ============================================================================
# Auth
# ============================================================================

class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    password: str = Field(..., min_length=6, max_length=128)


class UserLoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserInfoResponse(BaseModel):
    id: str
    username: str
    email: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    role: str = "user"
    token_quota_monthly: int = 1_000_000
    token_used_monthly: int = 0
    token_reset_at: Optional[datetime] = None
    default_model_id: Optional[str] = None
    model_params: Optional[dict] = None  # 预设模型的只读参数
    created_at: datetime


class UserUpdateRequest(BaseModel):
    username: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    avatar_url: Optional[str] = Field(None, max_length=500)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6, max_length=128)


# ============================================================================
# Upload / OSS
# ============================================================================

class PresignUploadRequest(BaseModel):
    filename: str
    content_type: str = "application/octet-stream"


class PresignUploadResponse(BaseModel):
    presigned_url: str
    public_url: str
    filename: str


# ============================================================================
# Knowledge Base
# ============================================================================

class KnowledgeBaseCreate(BaseModel):
    name: str
    description: Optional[str] = None
    owner_id: Optional[str] = None


class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    owner_id: Optional[str] = None
    document_count: int = 0
    created_at: datetime


# ============================================================================
# Audit Log
# ============================================================================

class AuditLogCreate(BaseModel):
    user_id: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: dict[str, Any] = {}
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class AuditLogResponse(BaseModel):
    id: str
    user_id: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: dict[str, Any] = {}
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime


class AuditLogQuery(BaseModel):
    user_id: Optional[str] = None
    action: Optional[str] = None
    resource_type: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


# ============================================================================
# Memory
# ============================================================================

class MemorySearchResponse(BaseModel):
    user_id: str
    memories: list[dict]


# ============================================================================
# Schema Metadata（数据源 Schema 元数据编辑）
# ============================================================================

class SchemaColumnMeta(BaseModel):
    """字段级元数据"""
    alias: Optional[str] = Field(None, max_length=100, description="业务别名")
    description: Optional[str] = Field(None, max_length=1000, description="业务注释")
    enums: Optional[dict] = Field(None, description="枚举值映射，如 {'active': '活跃'}")
    hidden: bool = Field(False, description="是否对 LLM 隐藏")


class SchemaTableMeta(BaseModel):
    """表级元数据"""
    alias: Optional[str] = Field(None, max_length=100, description="业务别名")
    description: Optional[str] = Field(None, max_length=1000, description="业务注释")
    columns: dict[str, SchemaColumnMeta] = Field(default_factory=dict, description="字段元数据")
    hidden: bool = Field(False, description="是否对 LLM 隐藏")


class SchemaRelationship(BaseModel):
    """表关系定义"""
    name: Optional[str] = Field(None, max_length=100, description="关系名称")
    from_table: str = Field(..., max_length=100)
    from_column: str = Field(..., max_length=100)
    to_table: str = Field(..., max_length=100)
    to_column: str = Field(..., max_length=100)
    type: str = Field("many_to_one", pattern=r"^(one_to_one|one_to_many|many_to_one|many_to_many)$")


class SchemaMetric(BaseModel):
    """业务指标/语义指标定义"""
    name: str = Field(..., max_length=100, description="指标英文名")
    alias: Optional[str] = Field(None, max_length=100, description="指标中文名")
    description: Optional[str] = Field(None, max_length=1000)
    expression: str = Field(..., max_length=1000, description="SQL 表达式或公式")
    aggregation: Optional[str] = Field(None, pattern=r"^(sum|avg|count|min|max|count_distinct)$")
    dimensions: List[str] = Field(default_factory=list, description="常用下钻维度")


class SchemaMetadata(BaseModel):
    """数据源 Schema 元数据完整结构"""
    tables: dict[str, SchemaTableMeta] = Field(default_factory=dict)
    relationships: List[SchemaRelationship] = Field(default_factory=list)
    metrics: List[SchemaMetric] = Field(default_factory=list)


class SchemaMetadataUpdate(BaseModel):
    """Schema 元数据更新请求"""
    tables: Optional[dict[str, SchemaTableMeta]] = None
    relationships: Optional[List[SchemaRelationship]] = None
    metrics: Optional[List[SchemaMetric]] = None


# ============================================================================
# Data Agent (BI)
# ============================================================================

class BIChatRequest(BaseModel):
    """BI 对话请求"""
    messages: list[dict]
    data_context: Optional[str] = None
    data_source_id: Optional[str] = None


class BIQueryRequest(BaseModel):
    """SQL 查询请求"""
    sql: str
    data_source_id: Optional[str] = None


class BIExportRequest(BaseModel):
    """BI 导出请求"""
    title: str = "数据分析报告"
    messages: list[dict] = []
    charts: list[dict] = []
    tables: list[dict] = []


class DataSourceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field("postgresql", pattern=r"^(postgresql|mysql|clickhouse|csv)$")
    connection_config: dict = Field(default_factory=dict)
    is_active: bool = True


class DataSourceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    type: Optional[str] = Field(None, pattern=r"^(postgresql|mysql|clickhouse|csv)$")
    connection_config: Optional[dict] = None
    is_active: Optional[bool] = None


class DataSourceResponse(BaseModel):
    id: str
    name: str
    type: str
    connection_config: dict
    schema_metadata: SchemaMetadata = Field(default_factory=SchemaMetadata)
    is_active: bool
    user_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class BIQueryLogResponse(BaseModel):
    id: str
    user_id: Optional[str] = None
    data_source_id: Optional[str] = None
    natural_language_query: Optional[str] = None
    generated_sql: Optional[str] = None
    query_result_summary: dict = Field(default_factory=dict)
    execution_time_ms: int = 0
    row_count: int = 0
    status: str = "success"
    error_message: Optional[str] = None
    created_at: datetime


class BIReportCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    query_log_id: Optional[str] = None
    chart_configs: list[dict] = Field(default_factory=list)


class BIReportResponse(BaseModel):
    id: str
    user_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    query_log_id: Optional[str] = None
    chart_configs: list[dict] = Field(default_factory=list)
    is_shared: bool = False
    share_token: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class DataPermissionCreate(BaseModel):
    """数据权限创建请求"""
    user_id: Optional[str] = None
    data_source_id: Optional[str] = None
    allowed_tables: List[str] = Field(default_factory=list)
    allowed_columns: dict = Field(default_factory=dict)
    row_filters: dict = Field(default_factory=dict)


class DataPermissionUpdate(BaseModel):
    """数据权限更新请求"""
    allowed_tables: Optional[List[str]] = None
    allowed_columns: Optional[dict] = None
    row_filters: Optional[dict] = None


class DataPermissionResponse(BaseModel):
    """数据权限响应"""
    id: str
    user_id: Optional[str] = None
    data_source_id: Optional[str] = None
    allowed_tables: List[str] = Field(default_factory=list)
    allowed_columns: dict = Field(default_factory=dict)
    row_filters: dict = Field(default_factory=dict)
    created_at: datetime


class DataAnalysisStreamChunk(BaseModel):
    """Data Agent SSE 流式数据块"""
    type: str  # sql / query_result / chart / analysis / content_blocks / done
    data: Optional[Any] = None


class DashboardTrendsResponse(BaseModel):
    period: str
    labels: list[str]
    document_counts: list[int]
    conversation_counts: list[int]
    active_user_counts: list[int]

