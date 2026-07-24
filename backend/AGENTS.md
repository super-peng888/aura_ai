# Aura AI Enterprise — 后端项目指南

> 本文档面向 AI 编程助手。如果你第一次接触这个项目，请先阅读本文件，再修改任何代码。

---

## 1. 项目概述

Aura AI Enterprise 后端是一个统一的 Python 服务，为前端（React）提供 RESTful API 和 SSE 流式对话能力。

核心能力：
- **RAG 对话**：基于上传文档的检索增强生成，支持文本+图片混合回答
- **文档解析**：PDF / Word / Excel 解析，提取文本分块和图片，向量化后存入 Milvus
- **用户级模型配置**：每个用户可配置自己的 LLM API Key，使用 Fernet 加密存储
- **Agent 工作流**：基于 LangGraph 的意图分类 → 查询改写 → 多路召回 → ReRank → 流式生成
- **长期记忆**：基于 Mem0 的用户级记忆系统

---

## 2. 技术栈

| 组件 | 技术 | 版本 |
|------|------|------|
| 语言 | Python | 3.11 |
| Web 框架 | FastAPI | 0.115 |
| 数据库 | PostgreSQL | 16 |
| ORM | SQLAlchemy | 2.0 (async) |
| 迁移 | Alembic | 1.14 |
| 向量数据库 | Milvus | 2.4 |
| 对象存储 | MinIO | 兼容 S3 |
| 缓存 | Redis | 7 (可选) |
| Agent 框架 | LangGraph | 0.2 |
| RAG 框架 | LlamaIndex | 0.11 |
| Embedding | OpenAI / BGE | - |
| 重排序 | Cohere / BGE-Reranker | - |
| 文档解析 | PyMuPDF | 1.24 |
| 记忆 | Mem0 | ≥0.1 |
| 部署 | Docker Compose | - |

---

## 3. 项目结构

```
backend/
├── app/
│   ├── main.py                 # FastAPI 入口， lifespan 管理 Milvus / Mem0 连接
│   ├── config.py               # Pydantic Settings，所有配置从环境变量/.env读取
│   ├── api/                    # FastAPI 路由层
│   │   ├── auth.py             # JWT 注册/登录/认证
│   │   ├── chat.py             # 流式/非流式对话接口
│   │   ├── documents.py        # 文档解析触发、状态查询、删除
│   │   ├── health.py           # 健康检查
│   │   ├── uploads.py          # OSS 预签名 URL、服务端上传
│   │   └── users.py            # 用户信息、LLM 配置、密码修改
│   ├── core/                   # 核心业务逻辑
│   │   ├── agent.py            # LangGraph 工作流（意图分类→检索→生成→数据分析）
│   │   ├── data_agent.py       # Data Agent 工作流（SQL 生成→查询→图表）
│   │   ├── rag_pipeline.py     # 端到端 RAG 流水线
│   │   ├── retrieval.py        # 多路召回（向量+关键词）
│   │   └── reranker.py         # ReRank 服务
│   ├── db/                     # 数据访问层
│   │   ├── base.py             # SQLAlchemy async engine + session
│   │   ├── models.py           # ORM 模型（User/Document/Chunk/Image/Message/DataSource/BIQueryLog...）
│   │   └── repository.py       # Repository 模式，通用 BaseRepository + 具体实现
│   ├── models/                 # Pydantic 模型
│   │   └── schemas.py          # 所有 API 请求/响应 Schema
│   ├── services/               # 服务层
│   │   ├── llm_service.py      # 用户级动态 LLM 调用（加密/解密 API Key）
│   │   ├── bi_service.py       # BI 核心服务（SQL 安全、Schema 管理、查询执行、审计）
│   │   ├── embedding_service.py# Embedding 服务（dense + sparse）
│   │   ├── document_parser.py  # 文档解析（PyMuPDF 等）
│   │   ├── indexer.py          # 文档索引到 Milvus
│   │   ├── image_service.py    # 图片上传、缩略图、预签名 URL
│   │   └── memory_service.py   # Mem0 记忆服务封装
│   ├── storage/
│   │   └── milvus_client.py    # Milvus 连接与集合管理
│   └── utils/                  # 工具函数
├── scripts/
│   └── init_db.sql             # PostgreSQL 初始化 Schema（含触发器）
├── docs/
│   ├── architecture.md         # 架构设计文档
│   └── security.md             # API Key 加密与生产环境安全指南
├── pyproject.toml              # Python 依赖与项目配置
├── Dockerfile                  # Python 服务镜像
├── docker-compose.yml          # 基础设施编排（PG/Milvus/MinIO/Redis）
└── .env.example                # 环境变量模板
```

---

## 4. 代码组织原则

### 4.1 分层架构

1. **API 层** (`app/api/`)：只处理 HTTP 请求/响应、参数校验、依赖注入，不写业务逻辑。
2. **Core 层** (`app/core/`)：编排业务工作流（Agent、RAG Pipeline），不直接操作数据库。
3. **Service 层** (`app/services/`)：实现可复用的领域能力（LLM 调用、Embedding、解析、索引）。
4. **DB 层** (`app/db/`)：ORM 模型 + Repository，所有数据库访问通过 Repository 进行。

### 4.2 关键设计模式

- **Repository 模式**：`BaseRepository[T]` 提供通用的 `get/list/create/delete`，子类扩展具体查询方法。
- **工厂模式**：`LLMFactory.create_from_user_config()` 根据用户配置动态创建 LLM 实例。
- **Pydantic Settings**：`app.config.Settings` 统一管理环境变量，通过 `@lru_cache` 的 `get_settings()` 获取。
- **全局单例**：`llm_service`、`agent_service`、`rag_pipeline` 等以模块级单例提供服务。

### 4.3 异步约定

- 所有 I/O 操作（DB、HTTP、OSS、Milvus）必须使用 `async/await`。
- SQLAlchemy 使用 `AsyncSession` + `async_sessionmaker`。
- DB Session 通过 `get_db()` 依赖注入，或在 service 层直接创建 `AsyncSessionLocal()` 上下文。

---

## 5. 环境变量与配置

配置集中在 `app/config.py`，通过 Pydantic Settings 从 `.env` 加载。关键变量：

```bash
# 数据库
PG_HOST=localhost
PG_PORT=5432
PG_USER=aura
PG_PASSWORD=aura123
PG_DATABASE=aura_ai

# Milvus
MILVUS_HOST=localhost
MILVUS_PORT=19530

# LLM（系统默认）
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_CHAT_MODEL=deepseek-v4-flash

# OpenAI（备用）
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_CHAT_MODEL=gpt-4o

# Reranker
COHERE_API_KEY=xxx

# OSS
OSS_PROVIDER=minio
OSS_ENDPOINT=http://localhost:9000
OSS_ACCESS_KEY=minioadmin
OSS_SECRET_KEY=minioadmin
OSS_BUCKET=aura-ai

# JWT
JWT_SECRET=change-this-in-production
JWT_EXPIRATION_HOURS=24

# API Key 加密（生产环境必须配置）
API_KEY_ENCRYPTION_KEY=          # 32-byte base64 Fernet key

# CORS
CORS_ORIGINS=*
```

> 开发环境若未配置 `API_KEY_ENCRYPTION_KEY`，用户 API Key 将明文透传；生产环境必须配置。

---

## 6. 构建与运行

### 6.1 本地开发

```bash
# 1. 创建虚拟环境
python -m venv .venv
source .venv/Scripts/activate        # Windows
# source .venv/bin/activate          # macOS/Linux

# 2. 安装依赖（使用 pyproject.toml）
pip install -e .

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY / OPENAI_API_KEY 等

# 4. 启动基础设施（PG/Milvus/MinIO/Redis）
docker-compose up -d postgres etcd minio milvus-standalone oss redis

# 5. 初始化数据库
psql -h localhost -U aura -d aura_ai -f scripts/init_db.sql

# 6. 启动应用
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 6.2 Docker 部署

```bash
cp .env.example .env
# 编辑 .env
docker-compose up -d
```

> `docker-compose.yml` 中的 `python-service` 当前被注释掉，需根据实际部署需求解注释或使用独立 Dockerfile 构建。

### 6.3 常用端口

| 服务 | 端口 |
|------|------|
| FastAPI | 8000 |
| PostgreSQL | 5432 |
| Milvus | 19530 |
| MinIO (OSS API) | 9000 |
| MinIO (OSS Console) | 9003 |
| Milvus MinIO | 9001/9002 |
| Redis | 6379 |

---

## 7. 代码风格指南

### 7.1 语言

- **注释和文档字符串使用中文**。项目内所有设计说明、变更记录、函数 docstring 均为中文。
- 代码标识符（变量、函数、类）使用英文。

### 7.2 导入顺序

```python
# 1. 标准库
# 2. 第三方库
# 3. 本项目模块（以 app. 开头）
```

### 7.3 类型注解

- 所有函数参数和返回值都应加类型注解。
- 使用 `Optional[...]`、`List[...]`、`AsyncIterator[...]` 等显式类型。
- Pydantic v2 用于所有 API Schema（`BaseModel`）。

### 7.4 错误处理

- API 层使用 FastAPI 的 `HTTPException`。
- Service 层抛出异常或返回默认值；在关键路径打印日志。
- DB 层在 `get_db()` 中自动处理 `commit/rollback/close`。

### 7.5 API 响应格式

所有接口统一返回：

```python
class BaseResponse(BaseModel):
    code: int = 0           # 0 表示成功，非 0 表示错误码
    message: str = "success"
    data: Optional[Any] = None
```

---

## 8. 关键业务逻辑说明

### 8.1 用户级 LLM 配置

- 用户 API Key 加密存储在 `users.llm_config -> api_key` 字段。
- 加密使用 Python `cryptography.fernet`，密钥为 `API_KEY_ENCRYPTION_KEY`。
- `llm_service.py` 提供 `encrypt_api_key()` 和 `decrypt_api_key()`。
- 每次调用 LLM 时，通过 `LLMFactory.create_from_user_config(user_config)` 动态创建模型实例。
- 若用户未配置，自动回退到系统默认配置（`.env` 中的 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` 等）。

### 8.2 Agent 工作流（LangGraph）

```
START -> load_memory -> classify -> [retrieve | generate | data_analysis] -> save_memory -> END
```

- `load_memory`：从 Mem0 检索用户长期记忆
- `classify`：意图分类（rag / direct / clarify / data_analysis）
- `retrieve`：调用 `rag_pipeline.search()` 检索文档片段和图片
- `generate`：流式生成回答（SSE 推送）
- `data_analysis`：调用 Data Agent 执行数据分析（SQL 生成 → 查询执行 → 图表生成）
- `save_memory`：将本轮对话保存到 Mem0

### 8.3 RAG Pipeline

1. **查询改写**：使用 LLM 扩展同义词、补全缩写
2. **多路召回**：
   - 向量检索（Milvus，dense + sparse hybrid search）
   - 关键词检索（PostgreSQL tsvector / BM25）
3. **融合排序**：RRF 或重排序模型（Cohere / BGE-Reranker）
4. **图片解析**：提取文本中的 `[IMG:xxx]` 占位符，查 `images` 表获取 URL
5. **内容组装**：生成 `content_blocks` 供前端渲染图文混排

### 8.4 文档解析流程

```
上传文件 -> OSS (MinIO)
    -> 写入 documents 表 (status=pending)
    -> 调用 parse API
    -> PyMuPDF 解析
        -> 文本分块 -> Embedding -> Milvus
        -> 图片提取 -> 上传 OSS -> 写入 images 表
```

### 8.5 Data Agent（数据分析）工作流

```
START -> load_context -> classify_intent -> [generate_sql | direct_analysis | clarification]
    -> validate_sql -> execute_query -> refine_visualization -> END
```

- `load_context`：加载数据库 Schema（带 Redis 缓存）和用户数据权限
- `classify_intent`：判断是 SQL 查询、直接分析还是澄清
- `generate_sql`：LLM 根据 Schema 生成 SELECT SQL
- `validate_sql`：`SQLSecurityValidator` 使用 `sqlparse` AST 白名单校验
- `execute_query`：`QueryExecutor` 在只读事务中执行，带超时控制和 LIMIT 保护
- `refine_visualization`：根据真实查询结果生成 ECharts 图表配置
- **审计**：每次查询自动记录到 `bi_query_logs` 表
- **缓存**：Schema 缓存 5 分钟，查询结果缓存 2 分钟

核心文件：
- `app/core/data_agent.py` — LangGraph Data Agent 工作流
- `app/services/bi_service.py` — BI 核心服务（SQL 安全、Schema 管理、查询执行）
- `app/api/bi.py` — BI API 路由层（纯路由，业务逻辑委托 Service）

数据表：
- `data_sources` — 数据源配置（支持多数据源）
- `bi_query_logs` — 查询历史与审计
- `bi_reports` — 保存的报表
- `data_permissions` — 数据权限控制（表级/字段级）

---

## 9. 安全注意事项

- **生产环境必须配置 `API_KEY_ENCRYPTION_KEY`**，并使用 `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 生成。
- `.env` 必须加入 `.gitignore`，禁止提交密钥。
- JWT Secret 长度应 ≥ 32 字符，定期轮换。
- 用户 API Key 密文不要打印在日志中，前端只显示掩码后的 Key（`sk-****xxxx`）。
- 数据库连接使用独立账号，遵循最小权限原则。
- HTTPS 必须在生产环境启用（TLS 1.2+）。

---

## 10. 依赖管理

- 本项目使用 `pyproject.toml` 管理依赖（已替代旧版的 `requirements.txt`）。
- 关键框架（如 `langchain`、`langgraph`）使用 `>=` 下限 + `<` 上限的方式锁定主版本，避免自动升级到不兼容的大版本。
- 新增依赖时，在 `pyproject.toml` 中明确标注用途（参考现有分组注释），并尽量给出兼容的版本范围。
- 本地安装命令：`pip install -e .`

---

## 11. 测试

当前项目中**尚未配置测试框架**。如果你需要添加测试，建议：

- 使用 `pytest` + `pytest-asyncio` 测试异步代码
- 使用 `httpx.AsyncClient` + `fastapi.TestClient` 测试 API
- 使用 `unittest.mock` / `pytest-mock` Mock 外部服务（LLM / Milvus / OSS）
- 测试文件建议放在 `tests/` 目录下，遵循 `test_<module>.py` 命名

---

## 12. 修改代码前的检查清单

- [ ] 是否已阅读 `docs/architecture.md` 和 `docs/security.md`？
- [ ] 新增配置是否已在 `app/config.py` 的 `Settings` 类中定义？
- [ ] 新增数据库表是否已在 `app/db/models.py` 和 `scripts/init_db.sql` 中同步？
- [ ] 新增 API 是否已在 `app/models/schemas.py` 中定义 Schema？
- [ ] 新增路由是否已在 `app/main.py` 中 `include_router`？
- [ ] Data Agent 相关变更是否同步到 `app/core/data_agent.py` 和 `app/services/bi_service.py`？
- [ ] SQL 相关操作是否经过 `SQLSecurityValidator` 校验？
- [ ] 涉及用户 API Key 的代码是否正确调用了 `encrypt_api_key` / `decrypt_api_key`？
- [ ] 所有 I/O 操作是否使用了 `async/await`？
- [ ] 注释是否使用中文？
