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
    MILVUS_ENABLE_HYBRID: bool = True

    # LLM Provider
    LLM_PROVIDER: str = "deepseek"  # deepseek / custom

    # DeepSeek (system default)
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_CHAT_MODEL: str = "deepseek-v4-flash"

    # 向量化与重排序模型（系统级，管理员维护；修改后重启生效。
    # api_key 不落库、不写 .env，由 pydantic 自动从系统环境变量 DASHSCOPE_API_KEY 读取）
    DASHSCOPE_API_KEY: str = ""
    MODEL_BASE_URL: str = "https://llm-nlwke5opzgdg5lpy.cn-beijing.maas.aliyuncs.com/compatible-api/v1"
    EMBEDDING_TEXT_MODEL: str = "qwen3.7-text-embedding"
    EMBEDDING_MULTIMODAL_MODEL: str = ""  # 多模态向量化模型（图像），未配置则不启用
    EMBEDDING_FUSION_MODEL: str = ""      # 融合向量化模型（一次调用同时产出 dense+sparse），未配置则 sparse 走本地 tokenizer
    EMBEDDING_DIM: int = 3072
    RERANK_MODEL: str = "qwen3-rerank"
    RERANK_BASE_URL: str = ""             # 空 = 用 MODEL_BASE_URL

    # OSS
    OSS_PROVIDER: str = "minio"
    OSS_ENDPOINT: str = "http://localhost:9000"
    OSS_ACCESS_KEY: str = "minioadmin"
    OSS_SECRET_KEY: str = "minioadmin"
    OSS_BUCKET: str = "aura-ai"
    OSS_REGION: str = "us-east-1"
    OSS_PUBLIC_URL: str = ""

    # Document Parsing
    PARSE_CHUNK_SIZE: int = 800
    PARSE_CHUNK_OVERLAP: int = 100
    PARSE_MAX_IMAGES_PER_DOC: int = 500
    PARSE_DEFAULT_MODE: str = "pymupdf"
    ENABLE_VLM_CAPTION: bool = False
    VLM_MODEL: str = "qwen-vl-max"
    VLM_API_BASE: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    VLM_API_KEY: str = ""
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
    # 注：Mem0 的 llm 实际使用系统默认 DeepSeek（DEEPSEEK_*），embedder 使用系统级
    # embedding 配置（EMBEDDING_TEXT_MODEL/EMBEDDING_DIM/MODEL_BASE_URL/DASHSCOPE_API_KEY），
    # 以上 PROVIDER/MODEL 键仅作占位保留。
    MEM0_VECTOR_STORE_PROVIDER: str = "qdrant"
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    MEM0_COLLECTION_NAME: str = "mem0_memories"

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
