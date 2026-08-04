"""Application configuration using Pydantic Settings."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # App
    APP_NAME: str = "Aura AI Enterprise"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # PostgreSQL
    PG_HOST: str = "localhost"
    PG_PORT: int = 5432
    PG_USER: str = "aura"
    PG_PASSWORD: str = "aura123"
    PG_DATABASE: str = "aura_ai"
    PG_POOL_SIZE: int = 20

    @property
    def pg_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.PG_USER}:{self.PG_PASSWORD}"
            f"@{self.PG_HOST}:{self.PG_PORT}/{self.PG_DATABASE}"
        )

    # Milvus
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_COLLECTION: str = "document_chunks"

    # LLM Provider
    LLM_PROVIDER: str = "deepseek"  # deepseek / custom

    # DeepSeek (system default)
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_CHAT_MODEL: str = "deepseek-v4-flash"

    # 向量化与重排序模型（系统级，管理员维护；修改后重启生效。
    # api_key 不落库、不写 .env，由 pydantic 自动从系统环境变量 DASHSCOPE_API_KEY 读取）
    DASHSCOPE_API_KEY: str = ""
    MODEL_BASE_URL: str = "https://llm-nlwke5opzgdg5lpy.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    # 向量化：单一多模态模型（文本/图片同一向量空间），通过 dashscope SDK 的 MultiModalEmbedding.call() 调用
    EMBEDDING_MODEL: str = "qwen3-vl-embedding"
    EMBEDDING_DIM: int = 1024  # qwen3-vl-embedding 支持 {256,512,768,1024,1536,2048,2560}；保持 1024 与既有 Milvus collection 一致
    RERANK_MODEL: str = "qwen3-rerank"
    RERANK_BASE_URL: str = "https://llm-nlwke5opzgdg5lpy.cn-beijing.maas.aliyuncs.com/compatible-api/v1"             # 完整 rerank 端点（不自动拼接路径）；空 = 用 MODEL_BASE_URL

    # OSS (RustFS，本地部署，S3 兼容)
    OSS_ENDPOINT: str = "http://localhost:9000"
    OSS_ACCESS_KEY: str = "rustfsadmin"
    OSS_SECRET_KEY: str = "rustfsadmin"
    OSS_BUCKET: str = "aura-ai"
    OSS_PUBLIC_URL: str = ""

    # Document Parsing
    PARSE_CHUNK_SIZE: int = 800
    PARSE_CHUNK_OVERLAP: int = 100
    PARSE_MAX_IMAGES_PER_DOC: int = 500
    PARSE_DEFAULT_MODE: str = "pymupdf"
    ENABLE_VLM_CAPTION: bool = False
    # VLM 多模态解析模型（qwen 系，密钥统一走 DASHSCOPE_API_KEY，页面只读展示）
    VLM_MODEL: str = "qwen3.7-plus"
    VLM_API_BASE: str = "https://llm-nlwke5opzgdg5lpy.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    VLM_API_KEY: str = ""  # 已废弃：解析改用 DASHSCOPE_API_KEY，保留字段避免 .env 存量配置报错
    VLM_DETAIL_LEVEL: str = "high"

    # OCR
    OCR_ENGINE: str = "paddleocr"
    OCR_LANG: str = "ch"

    # RAG
    RAG_TOP_K_KEYWORD: int = 20
    RAG_TOP_K_VECTOR: int = 20
    RAG_RERANK_TOP_K: int = 5
    RAG_SIMILARITY_THRESHOLD: float = 0.6
    RAG_ENABLE_QUERY_REWRITE: bool = True
    RAG_ENABLE_KEYWORD_SEARCH: bool = True
    RAG_ENABLE_VECTOR_SEARCH: bool = True
    RAG_ENABLE_RERANK: bool = True

    # Mem0 Memory
    ENABLE_MEM0: bool = True
    MEM0_LLM_PROVIDER: str = "openai"
    MEM0_LLM_MODEL: str = "gpt-4o-mini"
    MEM0_EMBEDDER_PROVIDER: str = "openai"
    # Mem0 只支持 OpenAI 兼容 embedder，无法复用 DashScope 原生多模态向量端点，
    # 故单独配文本 embedding 模型（走 MODEL_BASE_URL + DASHSCOPE_API_KEY）
    MEM0_EMBEDDER_MODEL: str = "qwen3.7-text-embedding"
    # 注：Mem0 的 llm 实际使用系统默认 DeepSeek（DEEPSEEK_*），以上 PROVIDER/LLM_MODEL 键仅作占位保留。
    # 向量存储：复用系统 Milvus（对象存储已统一为 RustFS）以降低运维成本；
    # Mem0 会自动创建独立 collection（与 document_chunks 互不干扰）。
    MEM0_VECTOR_STORE_PROVIDER: str = "milvus"
    MEM0_COLLECTION_NAME: str = "mem0_memories"
    MILVUS_TOKEN: str = ""  # 本地 Milvus standalone 无鉴权，留空即可
    # [legacy] 仅当 MEM0_VECTOR_STORE_PROVIDER=qdrant 时使用
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # JWT
    JWT_SECRET: str = "aura-ai-jwt-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24

    # API Key Encryption (Fernet)
    API_KEY_ENCRYPTION_KEY: str = ""

    @property
    def has_api_key_encryption(self) -> bool:
        """Check if API key encryption is configured."""
        return bool(self.API_KEY_ENCRYPTION_KEY)

    def get_fernet(self):
        """Get Fernet instance for API key encryption."""
        if not self.API_KEY_ENCRYPTION_KEY:
            return None
        from cryptography.fernet import Fernet
        return Fernet(self.API_KEY_ENCRYPTION_KEY.encode())

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""

    # CORS
    CORS_ORIGINS: str = "*"

    # Async Index Queue (Redis Streams)
    INDEX_QUEUE_STREAM: str = "aura:index:tasks"
    INDEX_QUEUE_GROUP: str = "indexers"
    INDEX_QUEUE_MAX_LEN: int = 10000
    # 随后端进程内嵌启动 index worker（无需再手动跑 python -m app.workers.index_worker）。
    # 若采用独立部署的 worker 进程，可设为 False 避免重复消费。
    INDEX_WORKER_EMBEDDED: bool = True
    # 认领空闲超过该毫秒数的“在飞”索引任务（进程崩溃后重新拉起时接管，兜底“索引中”卡死）。
    INDEX_WORKER_CLAIM_IDLE_MS: int = 60000
    # 单文档解析（running）超时秒数：超过则视为 hang，置 failed，避免永久“解析中”。
    PARSE_TIMEOUT_SECONDS: int = 600
    # 看门狗扫描间隔（秒）：周期性重置运行期遗留的 running 文档（进程被杀且未走 finally）。
    PARSE_WATCHDOG_INTERVAL_SECONDS: int = 120

    # MCP (Model Context Protocol) 外部工具服务器
    # JSON 字典：{"服务器名": {"transport": "streamable_http"|"sse", "url": "http://..."}}
    # 也支持简写 {"服务器名": "http://..."}（默认 streamable_http）。空字符串表示不启用。
    MCP_SERVERS: str = ""
    # MCP 工具发现/调用超时（秒）
    MCP_TOOLS_TIMEOUT_SECONDS: int = 15
    # 工具列表缓存 TTL（秒）：成功后缓存；失败短缓存避免每轮对话都卡连接
    MCP_TOOLS_CACHE_TTL: int = 300
    MCP_TOOLS_FAILURE_TTL: int = 30

    # Data Agent (BI) Configuration
    BI_QUERY_TIMEOUT_SECONDS: int = 30
    BI_MAX_QUERY_TIMEOUT_SECONDS: int = 300
    BI_MAX_RESULT_ROWS: int = 1000
    BI_SCHEMA_CACHE_TTL: int = 300
    BI_QUERY_CACHE_TTL: int = 120
    BI_DEFAULT_POOL_SIZE: int = 2
    BI_DEFAULT_MAX_OVERFLOW: int = 0
    BI_DEFAULT_POOL_RECYCLE: int = 3600
    BI_DEFAULT_POOL_TIMEOUT: int = 10
    BI_READONLY_DB_USER: str = ""
    BI_READONLY_DB_PASSWORD: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
