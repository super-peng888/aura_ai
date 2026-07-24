# Aura AI Enterprise — 数据分析（BI）模块企业落地评估与修复计划

> 生成时间：2026-07-03
> 评估范围：RAG、对话式 BI、数据源管理、Schema 治理、权限、部署

---

## 一、当前能力概览

| 模块 | 当前状态 |
|---|---|
| **RAG 知识库** | 完整：PDF 解析 → 文本/图片分块 → Embedding → Milvus + PostgreSQL 全文检索 → ReRank → 引用溯源 |
| **对话 Agent** | LangGraph 工作流，支持 RAG / 直接回答 / 澄清 / 数据分析四种意图 |
| **对话式 BI（Data Agent）** | 已实现 NL2SQL → 只读执行 → ECharts 图表 → HTML 报告导出 |
| **数据源管理** | 表结构与基础 API 已存在，但功能不完整 |
| **RBAC** | 角色、权限、菜单已打通 |
| **审计** | 操作审计、BI 查询日志已具备 |

---

## 二、企业落地结论

**可作为 PoC 或部门级试点，但直接大规模企业生产落地仍有明显缺口。**

### 2.1 关键阻塞问题（已在本轮修复）

1. **多数据源未真正贯通**
   - 前端选择了数据源，但请求走 `/chat/stream`，未携带 `data_source_id`。
   - 后端 `DataAgent.load_context_node` 未按 `data_source_id` 加载对应数据源，所有查询实际落在默认主库。

2. **数据源管理功能残缺**
   - 后端只有列表/创建，缺少测试连接、编辑、删除、同步 Schema。
   - 前端只有下拉框，没有管理页面。

3. **数据权限未生效**
   - `data_permissions` 表存在但代码未使用，存在越权访问风险。
   - 已补充表级/字段级/行级过滤，并在 Data Agent 中应用。

4. **连接配置明文存储**
   - 数据源密码以明文保存在 `connection_config` 中，不符合企业安全规范。
   - 已增加 Fernet 加密存储与解密使用，前端返回时掩码。

5. **SQL 资源未隔离**
   - 所有数据源共用默认连接池，查询无统一超时保护，存在单点拖垮风险。
   - 已实现按数据源独立连接池、按数据源超时、Python 层兜底超时。

### 2.2 其他重要缺口（后续迭代）

- **Schema 治理**：仅有自动 introspection，缺少表/字段别名、枚举说明、关系定义、指标口径。
- **数据权限**：`data_permissions` 表存在但代码未使用，缺少表级/字段级/行级过滤。
- **指标层/语义层**：缺少统一指标定义，完全依赖 LLM 拼 SQL。
- **自助看板**：仅有对话式分析，缺少拖拽看板与定时刷新。
- **企业集成**：缺少 SSO/LDAP、多租户、API 限流、生产级部署。
- **测试覆盖**：缺少 BI/Data Agent 相关测试。

---

## 三、本轮修复内容

### 3.1 后端修复

| 文件 | 修复点 |
|---|---|
| `app/core/data_agent.py` | `load_context_node` 按 `data_source_id` 加载数据源 Schema；`validate_and_execute_node` 按数据源执行查询；`analyze` 支持并透传 `llm_config` |
| `app/services/bi_service.py` | 增加 `get_data_source()`、`test_connection()`；Fernet 加密/解密/掩码连接配置；按数据源独立连接池与超时；Python 层兜底超时 |
| `app/api/bi.py` | `bi_chat` / `bi_chat_stream` / `query` 使用 `request.data_source_id`；新增数据源测试/编辑/删除/同步 Schema 端点；新增数据权限 CRUD；修复 `BIReport` 导入 |
| `app/db/models.py` | 确认 `data_permissions` 表结构支持表级/字段级/行级权限 |
| `app/models/schemas.py` | 增加 `DataPermissionCreate/Update/Response` 等数据权限 Schema |
| `app/db/repository.py` | 增加 `DataPermissionRepository` |
| `app/config.py` | 增加 BI 连接池默认配置与最大超时上限 |

### 3.2 前端修复

| 文件 | 修复点 |
|---|---|
| `src/views/DataAnalysis.tsx` | 调用 `/bi/chat/stream` 并传入 `data_source_id` |

---

## 四、后续扩展路线图

| 阶段 | 任务 | 优先级 |
|---|---|---|
| **P0** | 多数据源路由贯通、数据源 CRUD + 测试连接、Schema 自动同步 | 已修复 |
| **P1** | 数据权限（表级/字段级/行级）、连接加密、SQL 资源隔离 | 已修复 |
| **P1** | Schema 元数据编辑（别名、注释、枚举、关系） | 高 |
| **P2** | 指标层/语义层、自助看板、报表定时刷新与分享 | 中 |
| **P2** | SSO/LDAP、审计增强、多租户 | 中 |
| **P3** | 数据血缘、智能归因、AI 异常检测 | 低 |

---

## 五、本轮验证结果

- `app.api.bi` 路由导入：通过
- 修改文件 `py_compile`：通过
- 前端 `npx tsc --noEmit`：通过
- 完整应用导入/测试：受本地 MinIO 未启动影响，需启动 `docker-compose` 后重试

---

*报告由代码分析自动生成，后续迭代应结合业务需求与安全合规要求细化。*
