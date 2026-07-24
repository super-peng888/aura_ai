# Aura AI 后端架构设计（统一 Python 版）

## 1. 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              前端 (React)                                    │
│  Dashboard │ KnowledgeBase │ Chat │ DataAnalysis │ CategoryManage │ ...    │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    │                                     │
           ┌────────▼─────────┐                ┌────────▼─────────┐
           │  FastAPI         │                │  PostgreSQL      │
           │  (Python)        │◄──────────────►│  (关系数据)       │
           │                  │                │                  │
           │  • RESTful API   │                │  • users         │
           │  • JWT 认证       │                │  • conversations │
           │  • RAG 检索       │                │  • messages      │
           │  • LangGraph     │                │  • documents     │
           │  • Data Agent    │                │  • images        │
           │  • 文档解析       │                │  • chunks        │
           │  • SSE 流式       │                │  • data_sources  │
           │  • OSS 上传      │                │  • bi_query_logs │
           │                  │                │  • bi_reports    │
           └────────┬─────────┘                └──────────────────┘
                    │
           ┌────────▼─────────┐
           │  Milvus          │
           │  (向量数据库)     │
           │                  │
           │  • embeddings    │
           └──────────────────┘
                    │
           ┌────────▼─────────┐
           │  OSS / MinIO     │
           │  (对象存储)       │
           │                  │
           │  • 文档原文件     │
           │  • 解析图片       │
           └──────────────────┘
                    │
           ┌────────▼─────────┐
           │  Redis           │
           │  (缓存)           │
           │                  │
           │  • Schema 缓存    │
           │  • 查询结果缓存   │
           │  • Dashboard 缓存 │
           └──────────────────┘
```

## 2. 技术栈

| 组件 | 技术 | 版本 |
|------|------|------|
| Web 框架 | FastAPI | 0.115 |
| 数据库 | PostgreSQL | 16 |
| 向量库 | Milvus | 2.4 |
| 对象存储 | MinIO | 兼容 S3 |
| 缓存 | Redis | 7 |
| Agent 框架 | LangGraph | 0.2 |
| RAG 框架 | LlamaIndex | 0.11 |
| Embedding | OpenAI / BGE | - |
| 重排序 | Cohere / BGE-Reranker | - |
| 文档解析 | PyMuPDF | 1.24 |
| SQL 安全 | sqlparse | 0.5 |
| 部署 | Docker Compose | - |

## 3. 分层架构与调用链路

### 3.1 分层职责

```
┌─────────────────────────────────────────────────────────────┐
│  API 层 (app/api/)                                           │
│  职责：HTTP 路由、参数校验、依赖注入                            │
│  禁止：直接写业务逻辑                                          │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│  Core 层 (app/core/)                                         │
│  职责：编排业务工作流（Agent、RAG Pipeline、Data Agent）       │
│  禁止：直接操作数据库                                          │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│  Service 层 (app/services/)                                  │
│  职责：可复用的领域能力（LLM、Embedding、解析、索引、BI）      │
│  禁止：直接操作数据库                                          │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│  DB 层 (app/db/)                                             │
│  职责：ORM 模型 + Repository，所有数据库访问通过 Repository    │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 主 Agent 调用链路

```
用户提问
    │
    ▼
POST /api/v1/chat/stream
    │
    ▼
api/chat.py::_chat_generator()
    │
    ▼
core/agent/ 包::AgentService.chat()（service.py；2026-07 由 agent.py 拆分为
state/nodes/tools/graph/service 五模块，__init__.py 再导出，调用方零改动）
    │
    ▼
LangGraph 工作流:
    │
    ├──► load_memory_node ──► memory_service.search() ──► Mem0
    │
    ├──► classify_intent_node ──► llm_service.generate() ──► DeepSeek/OpenAI
    │         │
    │         ├──► "rag" ──► retrieve_context_node()
    │         │              │
    │         │              ├──► rag_pipeline.search()  (app/core/knowledge/rag_pipeline.py)
    │         │              │         │
    │         │              │         ├──► retrieval_config_service.resolve() ──► 检索参数运行时注入
    │         │              │         ├──► llm_service.rewrite_query()
    │         │              │         ├──► embedding_service.embed_query()
    │         │              │         ├──► retrieval_service.retrieve() ──► Milvus + PG
    │         │              │         │         （支持 knowledge_base_ids / metadata filter）
    │         │              │         ├──► 图检索融合（enable_graph_rag 开启时）:
    │         │              │         │         graph_retriever.local/global_search() ──► kg_* 图谱表
    │         │              │         │         （graph_search_mode: local / global / auto，与向量结果去重合并）
    │         │              │         ├──► reranker_service.rerank() ──► Cohere
    │         │              │         └──► rag_pipeline.to_content_blocks()
    │         │              │
    │         │              ├──► agent_reason_node ⇄ tool_exec_node
    │         │              │         （rag_mode=agentic 时替代固定 retrieve 管道：LLM 自主调用
    │         │              │          knowledge_search 工具循环检索，上限 MAX_TOOL_CALLS=4；
    │         │              │          修正检索已归一为该 agentic 单路径，原 corrective loop 已下线）
    │         │              └──► generate_response_node ──► llm_service.generate_with_citations() ──► SSE 流式输出
    │         │
    │         ├──► "data_analysis" ──► data_agent_service.analyze()
    │         │              │
    │         │              ├──► bi_service.get_schema() ──► Redis 缓存
    │         │              ├──► llm_service.generate() ──► SQL 生成
    │         │              ├──► bi_service.execute_query()
    │         │              │         ├──► SQLSecurityValidator.validate() ──► sqlparse AST
    │         │              │         ├──► QueryExecutor._execute_with_timeout() ──► PG 只读
    │         │              │         └──► QueryExecutor._log_query() ──► bi_query_logs
    │         │              └──► llm_service.generate() ──► 图表配置 + SSE 流式输出
    │         │
    │         ├──► "clarify" ──► 固定澄清文本
    │         │
    │         └──► "direct" ──► llm_service.generate_stream() ──► SSE 流式输出
    │
    └──► save_memory_node ──► memory_service.add() ──► Mem0
```

### 3.3 Data Agent（数据分析）调用链路

```
用户请求分析
    │
    ▼
POST /api/v1/bi/chat/stream
    │
    ▼
api/bi.py ──► data_agent_service.analyze()
    │
    ▼
LangGraph Data Agent:
    │
    ├──► load_context_node ──► bi_service.get_schema() ──► SchemaManager (Redis 缓存)
    │
    ├──► classify_intent_node ──► llm_service.generate()
    │         │
    │         ├──► "sql_query" ──► generate_sql_node()
    │         │              ├──► llm_service.generate() ──► SQL + 初步分析
    │         │              ├──► validate_and_execute_node()
    │         │              │         ├──► SQLSecurityValidator.validate() ──► sqlparse AST 白名单
    │         │              │         ├──► SQLSecurityValidator.inject_limit() ──► LIMIT 保护
    │         │              │         └──► QueryExecutor.execute()
    │         │              │                   ├──► cache_get() ──► 检查缓存
    │         │              │                   ├──► engine.run_sync() ──► 只读事务 + statement_timeout
    │         │              │                   ├──► cache_set() ──► 写入缓存
    │         │              │                   └──► _log_query() ──► bi_query_logs (审计)
    │         │              └──► refine_visualization_node() ──► 根据真实数据生成 ECharts
    │         │
    │         ├──► "direct" ──► direct_analysis_node() ──► 分析建议
    │         │
    │         └──► "clarify" ──► clarification_node() ──► 澄清提示
    │
    └──► SSE 流式输出: sql → query_result → analysis → chart → table → done
```

## 4. 数据流

### 4.1 文档上传与解析

```
用户上传PDF
    │
    ▼
前端 → POST /api/v1/uploads/document
    │
    ├──► 保存到 OSS (MinIO) ──► storage_service.upload_file()
    ├──► 写入 documents 表 (status=pending)
    │
    ▼
POST /api/v1/documents/{id}/parse（或 parse-sync 同步解析）
    │
    ▼
api/documents.py（纯 HTTP 层，编排已下沉）──► services/document_parse_service.py
    │         公开接口：do_parse / run_parse_pipeline / trigger_parse_background /
    │                  index_document_sync / build_graph_after_index
    │         （sync 与 async 路径共用同一状态机）
    ▼
services/document_parser.py::parse_document()
    │
    ├──► PyMuPDF 解析: _parse_with_pymupdf()
    │         ├──► 提取文本 ──► _sentence_split() / _token_split()
    │         ├──► 提取图片 ──► _extract_images_raw()
    │         └──► 组装页面 ──► _assemble_page_text()
    │
    ├──► PaddleOCR 解析: _parse_with_paddleocr()
    │         （parse_mode=paddleocr，"ocr" 为别名；逐页渲染位图 → OCR，用于扫描件/图片型文档）
    │
    ├──► 分块 + 写入 PG 元数据 ──► chunk_repo / image_repo
    │         ├──► content + search_vector (tsvector)
    │         └──► image_ids (JSONB)
    │
    └──► 索引入库（向量化）
              │
              ├──► 异步: index_queue.enqueue_index_task() ──► Redis Streams
              │         └──► workers/index_worker.py 消费任务
              │               ├──► indexer.index_document()
              │               └──► GraphRAG 图谱构建（enable_graph_rag 开启时）:
              │                     extraction.py langextract 抽取实体/关系
              │                     → builder.py 写入 kg_* 四表 → louvain 社区检测 + LLM 社区摘要
              │                     （失败仅记日志，不影响索引主流程）
              │
              └──► 同步 (parse-sync): document_parse_service.index_document_sync()
                        │
                        ├──► indexer.index_document()
                        │         ├──► embedding_service.embed_dense() + embed_sparse()
                        │         ├──► milvus_client.insert_chunks() ──► pymilvus 批量插入
                        │         │         （chunk metadata 含 doc_title / kb_id / heading_path / chunk_type）
                        │         └──► milvus_id 回填 PG document_chunks
                        └──► GraphRAG 图谱构建（enable_graph_rag 开启时）:
                                  build_graph_after_index()，与 worker 共用同一实现
                                  （sync 路径也建图；失败仅记日志，不影响索引主流程）
```

存量文档可用 `scripts/reindex_documents.py` 重建索引，为旧数据补齐新 metadata 字段
（脚本直接调用 services 层，不 import api 层）。

### 4.2 对话 RAG 流程

```
用户提问
    │
    ▼
LangGraph Agent:
    │
    ├──► Step 0: 加载检索配置 retrieval_config_service.resolve()
    │         （DB system_retrieval_config 覆盖 .env 默认，Redis 缓存 300s；
    │          admin 页面 GET/PUT /api/v1/retrieval-config 可配，保存即生效，无需重启；
    │          配置项已收敛为 12 键，保存时校验 keyword+vector 不可双关，否则 422）
    │
    ├──► Step 1: 意图分类 (RAG / direct / clarify / data_analysis)
    │
    ├──► Step 2: 查询改写 (LLM 扩展关键词)
    │
    ├──► Step 3: 多路召回
    │         ├── BM25 全文检索 (PostgreSQL tsvector)
    │         └── 向量相似度检索 (Milvus hybrid search: dense + sparse)
    │         ──► RRF 融合排序
    │         （支持 knowledge_base_ids / metadata filter 过滤）
    │         ※ rag_mode=agentic 时 Step 2-4 由 agent_reason ⇄ tool_exec 工具调用循环替代
    │          （修正检索已归一为该 agentic 单路径，原可选修正循环已下线）
    │
    ├──► Step 4: ReRank (Cohere / cross-encoder)
    │
    ├──► Step 5: 图文关联
    │         提取 [image_id=xxx] → 查 PG images 表 → 获取 URL
    │         组装为 content_blocks: [{type: "text"}, {type: "image"}, {type: "sources"}]
    │
    └──► Step 6: LLM 流式生成回复 (SSE)
```

### 4.3 Data Agent 查询流程

```
用户提问"分析最近7天的文档上传趋势"
    │
    ▼
LangGraph Data Agent:
    │
    ├──► 加载 Schema ──► SchemaManager.get_schema()
    │         ├──► cache_get("bi:schema:default")
    │         └──► engine.run_sync(_sync_inspect) ──► Redis 缓存 5min
    │
    ├──► LLM 生成 SQL
    │         ├──► 输入: Schema + 用户问题
    │         └──► 输出: SELECT DATE(created_at), COUNT(*) FROM documents ...
    │
    ├──► SQL 安全校验 ──► SQLSecurityValidator.validate()
    │         ├──► sqlparse.parse() ──► AST 白名单 (只允许 SELECT)
    │         ├──► 黑名单关键字检查
    │         └──► 多语句检查
    │
    ├──► LIMIT 自动注入 ──► SQLSecurityValidator.inject_limit()
    │         └──► 如果无 LIMIT，自动追加 LIMIT 1000
    │
    ├──► 查询执行 ──► QueryExecutor.execute()
    │         ├──► cache_get() ──► 检查相同 SQL 缓存
    │         ├──► SET TRANSACTION READ ONLY
    │         ├──► SET statement_timeout = 30000
    │         ├──► 执行查询
    │         ├──► cache_set() ──► 缓存 2min
    │         └──► _log_query() ──► bi_query_logs 表
    │
    └──► 可视化生成 ──► LLM 根据真实数据生成 ECharts option
              ├──► 折线图: smooth + areaStyle
              ├──► 柱状图: 圆角 barBorderRadius
              └──► 饼图: roseType: "area"
```

## 5. 数据库设计

### 5.1 PostgreSQL Schema

详见 `scripts/init_db.sql`

核心表：
- **users**: 用户基础信息（bcrypt 密码哈希、llm_config JSONB）
- **conversations**: 对话会话
- **messages**: 消息记录（含 citation_ids 和 image_ids JSONB）
- **documents**: 上传的文档元数据
- **document_chunks**: 文档片段（与 Milvus ID 关联、tsvector 全文索引）
- **images**: 解析出的图片元数据（含 image_ref_id 占位符映射）
- **parse_tasks**: 异步解析任务状态
- **data_sources**: BI 数据源配置（支持 postgresql/mysql/clickhouse/csv）
- **bi_query_logs**: 查询审计日志（SQL、执行时间、行数、状态）
- **bi_reports**: 保存的报表（图表配置 JSONB、分享令牌）
- **data_permissions**: 数据权限控制（表级/字段级白名单）
- **system_retrieval_config**: 系统级检索配置（单行；含 rag_mode / enable_graph_rag / graph_search_mode 三个 GraphRAG 字段）
- **kg_entities / kg_relations / kg_chunk_entities / kg_communities**: GraphRAG 知识图谱（实体、关系、chunk 关联、louvain 社区摘要）

### 5.2 Milvus Collection

- **collection_name**: `document_chunks`
- **fields**:
  - `id` (INT64, PK, auto_id)
  - `chunk_id` (VARCHAR, 关联 PG)
  - `document_id` (VARCHAR)
  - `embedding` (FLOAT_VECTOR, dim=1024)
  - `sparse_vector` (SPARSE_FLOAT_VECTOR, 用于 hybrid search)
  - `metadata` (JSON)

### 5.3 Redis 缓存键规范

| 键前缀 | 用途 | TTL |
|--------|------|-----|
| `aura:bi:schema:{source_id}` | 数据库 Schema 缓存 | 300s |
| `aura:bi:query:{hash}` | 查询结果缓存 | 120s |
| `aura:dashboard:stats` | 仪表盘统计 | 30s |
| `aura:dashboard:trends:{period}` | 趋势数据 | 60s |

## 6. API 端点全景

### 6.1 认证 (Auth)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/auth/register` | POST | 用户注册 |
| `/api/v1/auth/login` | POST | 登录获取 JWT |
| `/api/v1/auth/me` | GET | 获取当前用户信息 |
| `/api/v1/auth/permissions` | GET | 获取当前用户权限 |
| `/api/v1/auth/menus` | GET | 获取当前用户菜单 |

### 6.2 用户 (Users)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/users/me` | GET | 获取个人资料 |
| `/api/v1/users/me` | PUT | 更新个人资料 |
| `/api/v1/users/me/password` | PUT | 修改密码 |
| `/api/v1/users/me/llm-config` | GET | 获取 LLM 配置 |
| `/api/v1/users/me/llm-config` | PUT | 更新 LLM 配置 |
| `/api/v1/users/me/llm-config` | DELETE | 清除 LLM 配置 |
| `/api/v1/users` | GET | 用户列表（管理员）|
| `/api/v1/users/{id}/role` | PUT | 修改用户角色 |

### 6.3 对话 (Chat)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/chat` | POST | 非流式对话 |
| `/api/v1/chat/stream` | POST | 流式 SSE 对话 |
| `/api/v1/chat/conversations/{id}/share` | POST | 分享对话 |
| `/api/v1/chat/share/{token}` | GET | 访问分享对话 |

### 6.4 会话管理 (Conversations)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/conversations` | GET | 会话列表 |
| `/api/v1/conversations` | POST | 创建会话 |
| `/api/v1/conversations/{id}/messages` | GET | 会话消息 |
| `/api/v1/conversations/{id}` | DELETE | 删除会话 |

### 6.5 文档 (Documents)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/documents` | GET | 文档列表 |
| `/api/v1/documents/{id}/parse` | POST | 提交解析任务 |
| `/api/v1/documents/{id}/parse-sync` | POST | 同步解析 |
| `/api/v1/documents/{id}/status` | GET | 解析状态 |
| `/api/v1/documents/{id}/chunks` | GET | 文档片段 |
| `/api/v1/documents/{id}/chunks/preview` | POST | 分片预览 |
| `/api/v1/documents/search` | POST | RAG 检索调试（需登录，支持 document_ids / knowledge_base_ids 过滤）|
| `/api/v1/documents/{id}` | DELETE | 删除文档 |
| `/api/v1/documents/batch-delete` | POST | 批量删除 |
| `/api/v1/documents/{id}/versions` | GET | 版本历史 |
| `/api/v1/documents/{id}/rollback` | POST | 回滚版本 |
| `/api/v1/documents/batch-move` | POST | 批量移动分类 |

### 6.6 分类 (Categories)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/categories` | GET | 分类列表（树形）|
| `/api/v1/categories` | POST | 创建分类 |
| `/api/v1/categories/{id}` | PUT | 更新分类 |
| `/api/v1/categories/{id}` | DELETE | 删除分类 |
| `/api/v1/categories/{id}/documents` | GET | 分类下文档 |

### 6.7 上传 (Uploads)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/uploads/presign` | POST | 预签名上传 URL |
| `/api/v1/uploads/document` | POST | 服务端上传文档 |
| `/api/v1/uploads/avatar` | POST | 上传头像 |

### 6.8 解析策略 (Parse Strategies)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/parse-strategies` | GET | 策略列表 |
| `/api/v1/parse-strategies` | POST | 创建策略 |
| `/api/v1/parse-strategies/{id}` | PUT | 更新策略 |
| `/api/v1/parse-strategies/{id}/set-default` | POST | 设为默认 |
| `/api/v1/parse-strategies/{id}` | DELETE | 删除策略 |

### 6.9 角色权限 (Roles)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/roles` | GET | 角色列表 |
| `/api/v1/roles/{id}/permissions` | GET | 角色权限 |
| `/api/v1/roles/{id}/permissions` | PUT | 更新角色权限 |
| `/api/v1/roles/permissions/all` | GET | 所有权限 |
| `/api/v1/roles/permissions/tree` | GET | 权限树 |
| `/api/v1/roles/permissions` | POST | 创建权限 |
| `/api/v1/roles/permissions/{id}` | PUT | 更新权限 |
| `/api/v1/roles/permissions/{id}` | DELETE | 删除权限 |

### 6.10 数据分析 (BI / Data Agent)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/bi/schema` | GET | 数据库 Schema |
| `/api/v1/bi/query` | POST | 执行只读 SQL |
| `/api/v1/bi/chat` | POST | 对话式分析（非流式）|
| `/api/v1/bi/chat/stream` | POST | 对话式分析（SSE 流式）|
| `/api/v1/bi/export` | POST | 导出 HTML 报告 |
| `/api/v1/bi/data-sources` | GET | 数据源列表 |
| `/api/v1/bi/data-sources` | POST | 创建数据源 |
| `/api/v1/bi/query-logs` | GET | 查询历史 |
| `/api/v1/bi/reports` | GET | 报表列表 |
| `/api/v1/bi/reports` | POST | 保存报表 |

### 6.11 仪表盘 (Dashboard)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/dashboard/stats` | GET | 统计数据 |
| `/api/v1/dashboard/trends` | GET | 趋势数据（日/周）|

### 6.12 健康检查
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | 健康检查 |
| `/ready` | GET | 就绪检查 |

## 7. 模块依赖关系

```
app/api/*.py
    ├──► app/models/schemas.py (Pydantic Schema)
    ├──► app/db/models.py (ORM)
    ├──► app/db/repository.py (Repository)
    ├──► app/db/base.py (Session)
    ├──► app/core/agent/ (AgentService，包)
    ├──► app/core/data_agent.py (DataAgentService)
    ├──► app/services/*.py
    └──► app/api/auth.py (get_current_user)

app/core/agent/（2026-07 由 agent.py 拆分；__init__.py 再导出，对外契约不变）
    ├──► app/core/knowledge/rag_pipeline.py
    ├──► app/core/data_agent.py
    ├──► app/services/llm_service.py
    └──► app/services/memory_service.py

app/core/data_agent.py
    ├──► app/services/bi_service.py
    └──► app/services/llm_service.py

app/core/knowledge/rag_pipeline.py
    ├──► app/services/embedding_service.py
    ├──► app/core/knowledge/retrieval.py
    ├──► app/core/knowledge/reranker.py
    ├──► app/core/knowledge/graph/retriever.py  (enable_graph_rag 时融合 local/global 图检索)
    └──► app/services/llm_service.py

app/core/knowledge/graph/retriever.py
    ├──► app/core/knowledge/graph/extraction.py (复用 normalize_entity_name，与索引侧归一规则一致)
    ├──► app/services/llm_service.py
    ├──► app/services/embedding_service.py
    └──► app/db/base.py (AsyncSessionLocal, 直查 kg_* 表)

app/core/knowledge/graph/builder.py
    ├──► app/core/knowledge/graph/extraction.py (langextract 实体/关系抽取)
    └──► app/db/repository.py (KnowledgeGraphRepository, kg_* 幂等入库 + 社区)

app/core/knowledge/retrieval.py
    └──► app/services/embedding_service.py
    └──► app/storage/milvus_client.py

app/services/bi_service.py
    ├──► app/utils/cache.py (Redis)
    ├──► app/db/base.py (Engine)
    ├──► app/db/repository.py (bi_query_log_repo)
    └──► app/db/models.py (BIQueryLog)

app/services/indexer.py
    ├──► app/services/embedding_service.py
    └──► app/storage/milvus_client.py

app/services/document_parse_service.py（2026-07 新增，解析编排自 api/documents.py 下沉）
    ├──► app/services/document_parser.py
    ├──► app/services/indexer.py (index_document_sync)
    ├──► app/services/index_queue.py (trigger_parse_background 异步入队)
    ├──► app/services/retrieval_config_service.py (enable_graph_rag 开关)
    ├──► app/core/knowledge/graph/builder.py (build_graph_after_index，与 worker 共用，惰性 import)
    └──► app/db/repository.py (document_repo / chunk_repo / image_repo)

（app/api/uploads.py 与 scripts/reindex_documents.py 直接调用 document_parse_service，
  不再 import app/api/documents.py）

app/workers/index_worker.py
    ├──► app/services/index_queue.py (Redis Streams)
    ├──► app/services/indexer.py
    ├──► app/core/knowledge/graph/builder.py (enable_graph_rag 时构建图谱 + 社区)
    └──► app/db/repository.py (document_repo / chunk_repo)
```

## 8. 安全设计

### 8.1 SQL 安全（Data Agent）

```
用户输入 SQL
    │
    ▼
sqlparse.parse(sql) ──► AST 遍历
    │
    ├──► 检查第一个 token 必须是 SELECT (DML)
    ├──► 黑名单关键字匹配 (INSERT/UPDATE/DELETE/DROP/...)
    ├──► 禁止多语句 (; 后跟非空白)
    ├──► 禁止 UNION（通过 AST 检查）
    │
    ▼
注入 LIMIT（如果原始 SQL 没有）
    │
    ▼
SET TRANSACTION READ ONLY
SET statement_timeout = 30000ms
    │
    ▼
执行查询
```

### 8.2 API Key 加密

- 用户 API Key 使用 Fernet 对称加密存储在 `users.llm_config -> api_key`
- 加密密钥通过环境变量 `API_KEY_ENCRYPTION_KEY` 配置
- 生产环境必须配置，开发环境未配置时明文透传（仅开发）

### 8.3 JWT 认证

- Token 有效期 24 小时（`JWT_EXPIRATION_HOURS`）
- 使用 HS256 算法
- 每个请求通过 `Authorization: Bearer <token>` 传递

## 9. 部署

```bash
# 1. 复制环境变量模板
cp .env.example .env
# 编辑 .env 填入你的 OPENAI_API_KEY 等

# 2. 启动所有服务
docker-compose up -d

# 3. 初始化数据库
psql -h localhost -U aura -d aura_ai -f scripts/init_db.sql

# 4. 查看日志
docker-compose logs -f python-service

# 5. 访问 API 文档
# http://localhost:8000/docs
```

### 服务端口
| 服务 | 端口 |
|------|------|
| FastAPI | 8000 |
| PostgreSQL | 5432 |
| Milvus | 19530 |
| MinIO (OSS API) | 9000 |
| MinIO (OSS Console) | 9003 |
| Redis | 6379 |
