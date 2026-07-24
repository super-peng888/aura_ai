# Aura AI Enterprise Engine

> **企业级 AI 智能体平台** — Liquid Glass 设计风格 | Vue 3 + Spring Boot + Python RAG

## 📁 项目结构

```
aura-ai-enterprise/
├── frontend/              # Vue 3 + Vite 前端 (端口 3000)
│   ├── src/
│   │   ├── views/         # 5 个核心页面
│   │   ├── components/    # 布局组件 + 通用组件
│   │   ├── api/           # Axios 封装
│   │   └── styles/        # Liquid Glass Design Tokens
│   └── package.json
│
├── backend/               # Spring Boot 3.x 后端 (端口 8088)
│   ├── pom.xml            # Maven 依赖配置
│   └── src/main/java/com/aura/ai/
│       ├── common/        # Result, Exception, GlobalHandler
│       ├── config/        # CORS 配置
│       ├── security/      # JWT 认证, SecurityFilter
│       ├── entity/        # 5 个数据库实体类
│       ├── mapper/        # MyBatis-Plus Mapper
│       └── controller/    # REST API 控制器
│   └── src/main/resources/
│       ├── application.yml
│       └── schema.sql     # 数据库建表 SQL（含种子数据）
│
└── vector-service/        # 已移除：检索/向量化能力已合并回 backend 单体（进程内调用）
```

## ✅ 已完成的模块

### 前端 (5 页面全部可运行)
| 页面 | 路由 | 功能亮点 |
|------|------|----------|
| **Dashboard** | `/` | 统计卡片、ECharts 柱状图、基础设施状态、Agent 排行、日志终端 |
| **Knowledge Base** | `/knowledge-base` | 文档表格、Tab 切换、Chunk 配置滑块、向量化面板、分页 |
| **Category Mgmt** | `/category` | 树形类目列表、增删改弹窗、文档关联展示 |
| **API Keys** | `/api-keys` | 密钥列表、Create 弹窗(一次性复制)、权限标签、用量图表 |
| **Chat (三段式)** | `/chat` | 左侧历史、中间聊天(SSE流式模拟)、右侧输出成果+产物文件 |

### 后端 (框架搭建完毕)
- ✅ 统一响应体 `Result<T>` 封装
- ✅ 全局异常处理 (`GlobalExceptionHandler`)
- ✅ JWT 无状态认证 (`JwtUtil` + `SecurityConfig`)
- ✅ CORS 跨域配置
- ✅ 5 张核心表实体类 + MyBatis-Plus Mapper
- ✅ Dashboard API Controller (Mock 数据)
- ✅ Health Check + Login API

### 检索与向量化
- 原独立 vector-service / retrieval-service 微服务已合并回后端单体
- 检索链路：`rag_pipeline.search()` → `embedding_service` → `retrieval` → `reranker`（进程内直连）
- 入库链路：`index_queue` → `index_worker` → `indexer.index_document()` → Milvus

## 🚀 启动方式

```bash
# 1. 启动前端 (已运行在 http://localhost:3001/)
cd frontend && npm install && npm run dev

# 2. 启动后端 (需 JDK 17+ 和 MySQL)
cd backend && mvn spring-boot:run
# → http://localhost:8088/api/v1/health
# 注：原独立向量化/检索微服务已合并回后端单体，无需单独启动
```

## 🎨 设计系统

- **风格**: Liquid Glass 毛玻璃效果
- **主色**: Sky Blue (#0058bc) + Mint Green (#006a60)
- **字体**: Plus Jakarta Sans + JetBrains Mono
- **图标**: Material Symbols Outlined
- **圆角**: 卡片 24px, 按钮 16px, 输入框 16px
- **毛玻璃**: `rgba(255,255,255,0.65)` + `backdrop-filter: blur(20px)`

## 🗄️ 数据库

运行 `backend/src/main/resources/schema.sql` 初始化 MySQL 数据库：
- `kb_category` — 知识库类目树（含 5 条种子分类）
- `kb_document` — 知识库文档
- `api_key` — API 密钥管理
- `chat_session` — 对话会话
- `chat_message` — 对话消息
- `sys_user` — 系统用户（默认管理员 admin/admin123）

## 🔧 技术栈总览

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端框架 | Vue 3 + Vite | Composition API + TypeScript |
| UI 方案 | Tailwind CSS 4 | Liquid Glass 自定义主题 |
| 图表 | ECharts | Dashboard 统计图表 |
| 后端框架 | Spring Boot 3.3.6 | Java 17 |
| ORM | MyBatis-Plus 3.5.9 | 自动 CRUD + 分页 |
| 安全 | Spring Security + JWT | 无状态 Token 认证 |
| 缓存 | Redis | 会话 / 限流 |
| 存储 | MinIO (S3 兼容) | 文件对象存储 |
| 检索/向量化 | Python FastAPI（进程内） | 已合并入后端单体：RAG 检索 + Embedding |
| LLM 集成 | Spring AI | 多模型统一接入层 |
