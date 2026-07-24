# 企业 Agent 架构优化：将知识检索抽取为微服务

> ⚠️ 已废弃：该微服务于 2026-07 合并回主后端单体，本文档仅作历史记录。

> 基于当前 Aura AI Enterprise 代码现状（FastAPI 单体后端 + Milvus/PG + MinIO）的落地方案。

---

## 1. 当前架构的痛点

从 `ARCHITECTURE.md` 与后端代码可以看出，知识检索链路目前已经高度内聚在单体后端中：

```
api/chat.py / api/documents.py
    └── core/agent.py / core/rag_pipeline.py
            ├── services/llm_service.py        # 查询改写
            ├── services/embedding_service.py  # dense/sparse embedding
            ├── core/retrieval.py              # Milvus 召回
            ├── core/reranker.py               # Cohere/Local rerank
            ├── storage/milvus_client.py       # Milvus 连接
            └── db/repository.py               # 图片元数据解析
```

**主要问题：**

- **资源竞争**：Embedding 模型（尤其是 local）与 Reranker 模型会占用大量 CPU/GPU，和对话 API、Data Agent 跑在同一个进程里，容易相互影响。
- **扩缩容粒度粗**：一旦检索成为瓶颈，只能整体扩容整个后端，成本高。
- **部署耦合**：Milvus 集合初始化、向量索引、模型加载都与 FastAPI 启动强绑定。
- **团队边界模糊**：文档解析、索引、检索、生成都堆在一个仓库里，后续知识库团队与对话团队容易互相阻塞。

---

## 2. 结论：能不能抽成微服务？

**可以，而且建议按“读”和“写”两条链路一起抽出。**

知识检索不仅是 `/documents/search` 那个搜索接口，它还包括：

- **读链路**：query rewrite → embedding → retrieve（Milvus hybrid）→ rerank。
- **写链路**：文档解析后的 chunk → embedding → Milvus/PG 索引。

把这两条线整体封装成独立的 **Retrieval Service**，让原后端只保留：

- Agent 编排（意图分类、记忆、调用生成）
- 业务元数据管理（documents/chunks/images 等）
- Data Agent（BI）
- 用户/权限/审计

这是最干净的边界。

---

## 3. 目标架构

```
                         ┌─────────────────────────────────────┐
                         │         Frontend (React)            │
                         └──────────────┬──────────────────────┘
                                        │
                         ┌──────────────▼──────────────────────┐
                         │   API Gateway / Backend (FastAPI)   │
                         │  - Auth / Users / Roles             │
                         │  - Chat / Agent orchestration       │
                         │  - Data Agent (BI)                  │
                         │  - Documents metadata (PG)          │
                         │  - Audit / Dashboard                │
                         └──────┬───────────────────────┬──────┘
                                │                       │
              ┌─────────────────▼─────┐    ┌────────────▼────────────┐
              │   Retrieval Service   │    │   Async Index Worker    │
              │   (FastAPI / gRPC)    │◄───┤   (Celery / RQ / Redis  │
              │                       │    │    Streams)             │
              │  - Query rewrite      │    │                         │
              │  - Embedding          │    │  - Parse result queue   │
              │  - Retrieve (Milvus)  │    │  - Chunk embedding      │
              │  - Rerank             │    │  - Milvus insert        │
              └──────────┬────────────┘    └─────────────────────────┘
                         │
              ┌──────────▼──────────┐
              │      Milvus         │
              │   (dense/sparse)    │
              └─────────────────────┘
```

### 3.1 服务边界

| 职责 | 留在 Backend | 抽到 Retrieval Service |
|------|--------------|------------------------|
| 用户认证/权限 | ✅ | ❌ |
| Agent 编排、记忆 | ✅ | ❌ |
| LLM 生成最终回答 | ✅ | ❌ |
| Data Agent（SQL） | ✅ | ❌ |
| Document 元数据 CRUD | ✅ | ❌ |
| 图片 URL 解析（`image_repo`） | ✅ | ❌ |
| Query rewrite | 可选 | 推荐 |
| Embedding | ❌ | ✅ |
| Milvus 召回 | ❌ | ✅ |
| Rerank | ❌ | ✅ |
| 文档 chunk 索引 | ❌ | ✅ |

> **为什么把图片 URL 解析留在后端？**
> 当前 `rag_pipeline._resolve_images()` 需要去 PG 查 `document_images` 表拿到 `oss_url`。图片元数据是业务数据，Retrieval Service 只返回 `image_ids`，Backend 再做一次轻量 PG 查询拼接即可。这样 PG 的写/读主路径仍归后端，向量库归检索服务。

---

## 4. 服务接口设计

下面给出最小可用（MVP）的 REST 接口。如果后续吞吐量变大，可再引入 gRPC。

### 4.1 搜索接口

```http
POST /v1/retrieval/search
Content-Type: application/json
X-Internal-Key: ${INTERNAL_API_KEY}
```

请求体：

```json
{
  "query": "如何配置 SSO",
  "document_ids": ["doc-001", "doc-002"],
  "knowledge_base_ids": ["kb-01"],
  "top_k": 10,
  "filters": {"category": "security"},
  "user_model_config": {
    "provider": "qwen",
    "model": "qwen3.6-plus",
    "api_key": "sk-xxxx"
  },
  "enable_rewrite": true,
  "enable_rerank": true
}
```

响应：

```json
{
  "query": "如何配置 SSO",
  "rewritten_query": "单点登录 SSO 配置步骤与注意事项",
  "results": [
    {
      "chunk_id": "chunk-xxx",
      "document_id": "doc-001",
      "content": "在系统设置中打开 SSO...",
      "page_number": 12,
      "score": 0.91,
      "search_type": "rerank",
      "image_ids": ["img-001"]
    }
  ]
}
```

### 4.2 索引接口（同步/异步）

```http
POST /v1/retrieval/index
Content-Type: application/json
```

请求体：

```json
{
  "document_id": "doc-001",
  "chunks": [
    {
      "chunk_id": "chunk-001",
      "content": "...",
      "page_number": 1,
      "image_ids": ["img-001"]
    }
  ],
  "dense_vectors": [[0.1, ...]],
  "sparse_vectors": [{"token_id": 0.5}]
}
```

> 实际落地时更推荐 **异步索引**：Backend 解析完文档后把 chunk 发到队列，Worker 消费后调用 Retrieval Service。这样可以削峰，避免大文件解析拖垮检索服务。

### 4.3 删除接口

```http
DELETE /v1/retrieval/documents/{document_id}
```

---

## 5. 后端改造示意

### 5.1 抽象 Retrieval Client

新增 `app/services/retrieval_client.py`：

```python
from abc import ABC, abstractmethod
from typing import List, Optional

class BaseRetrievalClient(ABC):
    @abstractmethod
    async def search(
        self,
        query: str,
        document_ids: Optional[List[str]] = None,
        knowledge_base_ids: Optional[List[str]] = None,
        top_k: int = 10,
        filters: Optional[dict] = None,
        user_model_config: Optional[dict] = None,
    ) -> dict:
        ...

    @abstractmethod
    async def index_document(self, document_id: str, chunks: list, **kwargs) -> dict:
        ...

    @abstractmethod
    async def delete_document(self, document_id: str) -> None:
        ...
```

实现两个子类：

- `LocalRetrievalClient`：复用现有 `rag_pipeline.search()` / `indexer.index_document()`，零行为变化。
- `RemoteRetrievalClient`：通过 `httpx.AsyncClient` 调用 Retrieval Service。

在 `app/config.py` 增加开关：

```python
RETRIEVAL_SERVICE_URL: str = ""  # 为空则走本地实现
RETRIEVAL_SERVICE_API_KEY: str = ""
```

### 5.2 改造调用点

当前需要替换的地方：

1. `core/agent.py::retrieve_context_node()` 中的 `rag_pipeline.search(...)` → `retrieval_client.search(...)`
2. `api/documents.py::search_documents()` 中的 `rag_pipeline.search(...)` → `retrieval_client.search(...)`
3. `api/documents.py` 删除/批量删除中的 `milvus_client.delete_by_document(...)` → `retrieval_client.delete_document(...)`
4. `services/indexer.py::index_document()` 中的 Milvus insert → `retrieval_client.index_document(...)`

### 5.3 保留的本地逻辑

`rag_pipeline.to_content_blocks()`、`agent.py` 的流式生成、`image_repo` 查询都留在后端。

---

## 6. Retrieval Service 最小结构

建议新建目录：

```
services/
└── retrieval-service/
    ├── app/
    │   ├── main.py              # FastAPI 入口
    │   ├── config.py            # Pydantic Settings
    │   ├── api/
    │   │   └── retrieval.py     # 路由
    │   ├── core/
    │   │   ├── retrieval.py     # Milvus 召回
    │   │   ├── rag_pipeline.py  # query rewrite + retrieve + rerank
    │   │   └── reranker.py      # Cohere/Local
    │   └── services/
    │       ├── embedding_service.py
    │       └── llm_service.py   # 仅用于 query rewrite
    ├── Dockerfile
    ├── requirements.txt
    └── pyproject.toml
```

> 复用现有 `embedding_service.py`、`retrieval.py`、`reranker.py`、`milvus_client.py` 的代码，只做少量接口适配即可，迁移成本很低。

---

## 7. 部署变更

当前 `backend/docker-compose.yml` 已经注释掉了一个 `python-service` 模板，可以重命名为 `retrieval-service` 并启用：

```yaml
services:
  retrieval-service:
    build:
      context: ./../services/retrieval-service
      dockerfile: Dockerfile
    container_name: aura-retrieval-service
    restart: unless-stopped
    environment:
      - MILVUS_HOST=milvus-standalone
      - MILVUS_PORT=19530
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - OPENAI_BASE_URL=${OPENAI_BASE_URL}
      - COHERE_API_KEY=${COHERE_API_KEY}
      - INTERNAL_API_KEY=${INTERNAL_API_KEY}
    ports:
      - "8001:8000"
    depends_on:
      - milvus-standalone
    networks:
      - aura-network
```

后端增加环境变量：

```env
RETRIEVAL_SERVICE_URL=http://retrieval-service:8000
RETRIEVAL_SERVICE_API_KEY=${INTERNAL_API_KEY}
```

---

## 8. 实施路线图（渐进式，可控风险）

### 阶段 1：接口抽象（无行为变化）

- 创建 `BaseRetrievalClient` / `LocalRetrievalClient`。
- 把 `rag_pipeline.search()`、`indexer.index_document()`、`milvus_client.delete_by_document()` 的调用全部收敛到 `LocalRetrievalClient`。
- 跑通现有测试。

### 阶段 2：独立服务（双跑）

- 新建 `services/retrieval-service/`，把 `embedding_service`、`retrieval`、`reranker`、`milvus_client` 迁移过去。
- 实现 `RemoteRetrievalClient`。
- 增加 feature flag，仅对非核心流量开启远程调用，观察延迟与稳定性。

### 阶段 3：索引异步化

- 解析完成后不再同步调用索引，而是把 chunk 推入 Redis/RabbitMQ。
- Worker 消费并调用 Retrieval Service。
- 文档状态机增加 `indexing` / `indexed` 状态。

### 阶段 4：灰度切流与下线本地实现

- 全部流量走 Retrieval Service。
- 删除 `LocalRetrievalClient` 与后端冗余的 Milvus 直接调用。

---

## 9. 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| 多一次网络调用，检索延迟增加 | 中等 | 同机房内网通常 <10ms；保留 `LocalRetrievalClient` 作为 fallback。 |
| Retrieval Service 宕机影响对话 | 高 | Backend 对远程调用加超时/重试；失败时 fallback 到本地实现或返回“检索不可用”。 |
| 索引与 PG 元数据不一致 | 高 | 异步任务加幂等（按 chunk_id 去重）；文档状态机暴露 `indexing` 状态；失败可重试。 |
| Embedding 模型占资源 | 中 | 单独为 Retrieval Service 配置 GPU/大内存节点，避免和 Backend 争抢。 |
| 多实例部署时模型重复加载 | 中 | 小规模接受；大规模可用外部 Embedding Server（如 vLLM/TEI/Triton）。 |

---

## 10. 什么时候拆？建议

| 场景 | 建议 |
|------|------|
| 当前只是 PoC / 少量用户 | **先不要拆**，但按阶段 1 做好接口抽象，预留微服务切换能力。 |
| 检索慢、embedding/rerank 拖累整体 | **拆 Retrieval Service**，独立扩容。 |
| 团队 > 5 人，知识库与对话由不同人维护 | **拆**，减少代码冲突和发布互相阻塞。 |
| 需要多租户隔离、不同知识库不同模型 | **拆**，Retrieval Service 可按租户独立部署实例。 |

---

## 11. 一句话总结

> **把 Embedding、Milvus 召回、Rerank 以及文档索引整体抽成 `Retrieval Service`，原后端只保留 Agent 编排、业务元数据和 LLM 生成。通过 `RetrievalClient` 抽象层 + feature flag 渐进式切换，是目前最稳妥、最可落地的微服务化路径。**
