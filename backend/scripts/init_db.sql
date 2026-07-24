-- ============================================
-- Aura AI PostgreSQL Database Schema
-- ============================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";      -- 用于模糊搜索

-- ============================================
-- 1. 用户表（无外部依赖，最先创建）
-- ============================================
CREATE TABLE IF NOT EXISTS users (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    username        VARCHAR(50) NOT NULL UNIQUE,
    email           VARCHAR(100) UNIQUE,
    phone           VARCHAR(20) UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    avatar_url      VARCHAR(500),
    role            VARCHAR(20) DEFAULT 'user',  -- user / admin
    status          VARCHAR(20) DEFAULT 'active', -- active / inactive / banned
    llm_config      JSONB DEFAULT '{}',
    token_quota_monthly INTEGER DEFAULT 1000000,
    token_used_monthly  INTEGER DEFAULT 0,
    token_reset_at      TIMESTAMP WITH TIME ZONE,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 1.5 解析策略表（依赖 users）
-- ============================================
CREATE TABLE IF NOT EXISTS parse_strategies (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    name            VARCHAR(100) NOT NULL,
    user_id         VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE,
    is_default      BOOLEAN DEFAULT FALSE,
    parse_mode      VARCHAR(32) DEFAULT 'pymupdf',
    chunk_size      INTEGER DEFAULT 800,
    chunk_overlap   INTEGER DEFAULT 100,
    dimension       INTEGER DEFAULT 1536,
    split_method    VARCHAR(32) DEFAULT 'sentence',
    extract_images  BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_parse_strategies_user_id ON parse_strategies(user_id);

-- users 添加默认策略外键
ALTER TABLE users ADD COLUMN IF NOT EXISTS default_strategy_id VARCHAR(36) REFERENCES parse_strategies(id) ON DELETE SET NULL;

-- users 添加默认模型绑定字段
ALTER TABLE users ADD COLUMN IF NOT EXISTS default_model_id VARCHAR(50);

-- ============================================
-- 用户自定义模型配置表
-- ============================================
CREATE TABLE IF NOT EXISTS user_model_configs (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    user_id         VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider        VARCHAR(50) NOT NULL DEFAULT 'custom',
    model           VARCHAR(100),
    api_key         VARCHAR(500),
    base_url        VARCHAR(500),
    max_tokens      INTEGER DEFAULT 4096,
    temperature     FLOAT DEFAULT 0.7,
    top_p           FLOAT DEFAULT 0.9,
    timeout         INTEGER DEFAULT 60,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_model_configs_user_id ON user_model_configs(user_id);

-- ============================================
-- 系统级检索配置表（单行，NULL 表示回落 .env 默认）
-- ============================================
CREATE TABLE IF NOT EXISTS system_retrieval_config (
    id                  VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    reranker_provider   VARCHAR(20),
    reranker_model      VARCHAR(100),
    reranker_api_key    VARCHAR(500),
    reranker_base_url   VARCHAR(500),
    embedding_model     VARCHAR(100),
    embedding_base_url  VARCHAR(500),
    embedding_api_key   VARCHAR(500),
    embedding_dim       INTEGER,
    top_k_keyword       INTEGER,
    top_k_vector        INTEGER,
    rerank_top_k        INTEGER,
    similarity_threshold FLOAT,
    enable_query_rewrite    BOOLEAN,
    enable_keyword_search   BOOLEAN,
    enable_vector_search    BOOLEAN,
    enable_rerank           BOOLEAN,
    enable_corrective_loop  BOOLEAN,
    max_retries             INTEGER,
    rag_mode            VARCHAR(20),
    enable_graph_rag    BOOLEAN,
    graph_search_mode   VARCHAR(20),
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 2. 角色表（无外部依赖）
-- ============================================
CREATE TABLE IF NOT EXISTS roles (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    name            VARCHAR(50) NOT NULL UNIQUE,
    description     TEXT,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 3. 权限表（无外部依赖，包含菜单/按钮/API 权限）
-- ============================================
CREATE TABLE IF NOT EXISTS permissions (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    code            VARCHAR(100) NOT NULL UNIQUE,
    name            VARCHAR(100) NOT NULL,
    description     TEXT,
    type            VARCHAR(20) DEFAULT 'api',
    path            VARCHAR(200),
    icon            VARCHAR(50),
    parent_id       VARCHAR(36) REFERENCES permissions(id) ON DELETE CASCADE,
    sort_order      INTEGER DEFAULT 0,
    hidden          BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 4. 角色权限关联表（依赖 roles, permissions）
-- ============================================
CREATE TABLE IF NOT EXISTS role_permissions (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    role_id         VARCHAR(36) NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id   VARCHAR(36) NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    UNIQUE(role_id, permission_id)
);

-- ============================================
-- 5. 用户角色关联表（多对多，users ↔ roles）
-- ============================================
CREATE TABLE IF NOT EXISTS user_roles (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    user_id         VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id         VARCHAR(36) NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    UNIQUE(user_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_user_roles_user_id ON user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_role_id ON user_roles(role_id);

-- ============================================
-- 6. 分类表（依赖 users，自引用 parent_id）
-- ============================================
CREATE TABLE IF NOT EXISTS categories (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    name            VARCHAR(100) NOT NULL,
    description     TEXT,
    parent_id       VARCHAR(36) REFERENCES categories(id) ON DELETE CASCADE,
    user_id         VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    sort_order      INTEGER DEFAULT 0,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 6. 对话会话表（依赖 users）
-- ============================================
CREATE TABLE IF NOT EXISTS conversations (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    user_id         VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title           VARCHAR(200) NOT NULL DEFAULT '新对话',
    model_id        VARCHAR(50) DEFAULT 'gpt-4o',
    status          VARCHAR(20) DEFAULT 'active',
    is_shared       BOOLEAN DEFAULT FALSE,
    share_token     VARCHAR(36) UNIQUE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 7. 消息表（依赖 conversations）
-- ============================================
CREATE TABLE IF NOT EXISTS messages (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    conversation_id VARCHAR(36) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            VARCHAR(20) NOT NULL,  -- user / assistant / system
    content         TEXT NOT NULL,
    citation_ids    JSONB DEFAULT '[]',
    image_ids       JSONB DEFAULT '[]',
    tokens_used     INTEGER DEFAULT 0,
    model_id        VARCHAR(50),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 8. 文档表（依赖 users, categories）
-- ============================================
CREATE TABLE IF NOT EXISTS documents (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    user_id         VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    filename        VARCHAR(255) NOT NULL,
    original_name   VARCHAR(255) NOT NULL,
    file_size       BIGINT,
    mime_type       VARCHAR(100),
    oss_url         VARCHAR(1000) NOT NULL,
    parse_status    VARCHAR(20) DEFAULT 'pending',
    parse_error     TEXT,
    parse_mode      VARCHAR(32),
    chunk_size      INTEGER,
    chunk_overlap   INTEGER,
    dimension       INTEGER,
    strategy_id     VARCHAR(36) REFERENCES parse_strategies(id) ON DELETE SET NULL,
    page_count      INTEGER,
    category_id     VARCHAR(36) REFERENCES categories(id) ON DELETE SET NULL,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 9. 文档片段表（依赖 documents）
-- ============================================
CREATE TABLE IF NOT EXISTS document_chunks (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    document_id     VARCHAR(36) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    milvus_id       VARCHAR(64) UNIQUE,
    content         TEXT NOT NULL,
    page_number     INTEGER,
    chunk_index     INTEGER NOT NULL DEFAULT 0,
    image_ids       JSONB DEFAULT '[]',
    chunk_metadata  JSONB DEFAULT '{}',
    search_vector   TSVECTOR,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 10. 图片表（依赖 documents）
-- ============================================
CREATE TABLE IF NOT EXISTS images (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    document_id     VARCHAR(36) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number     INTEGER,
    oss_url         VARCHAR(1000) NOT NULL,
    thumbnail_url   VARCHAR(1000),
    width           INTEGER,
    height          INTEGER,
    format          VARCHAR(20),
    caption         TEXT,
    image_ref_id    VARCHAR(64) NOT NULL UNIQUE,
    ocr_text        TEXT,
    description     TEXT,
    image_type      VARCHAR(32),
    alt_text        VARCHAR(512),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 11. 知识库/文档集合表（依赖 users）
-- ============================================
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    name            VARCHAR(100) NOT NULL,
    description     TEXT,
    owner_id        VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    document_ids    JSONB DEFAULT '[]',
    retrieval_config JSONB DEFAULT '{
        "top_k": 10,
        "rerank_top_k": 5,
        "similarity_threshold": 0.7,
        "enable_keyword_search": true,
        "enable_vector_search": true
    }',
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 12. 审计日志表（依赖 users）
-- ============================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    user_id         VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    action          VARCHAR(100) NOT NULL,
    resource_type   VARCHAR(50),
    resource_id     VARCHAR(36),
    details         JSONB DEFAULT '{}',
    ip_address      VARCHAR(45),
    user_agent      VARCHAR(500),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 13. 文档版本表（依赖 documents）
-- ============================================
CREATE TABLE IF NOT EXISTS document_versions (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    document_id     VARCHAR(36) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version         INTEGER NOT NULL DEFAULT 1,
    oss_url         VARCHAR(1000) NOT NULL,
    file_size       BIGINT,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(document_id, version)
);

-- ============================================
-- 14. 解析任务队列表（依赖 documents）
-- ============================================
CREATE TABLE IF NOT EXISTS parse_tasks (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    document_id     VARCHAR(36) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    status          VARCHAR(20) DEFAULT 'pending',
    progress        INTEGER DEFAULT 0,
    result_data     JSONB DEFAULT '{}',
    error_message   TEXT,
    started_at      TIMESTAMP WITH TIME ZONE,
    completed_at    TIMESTAMP WITH TIME ZONE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 15. 文档质量评分表（依赖 documents）
-- ============================================
CREATE TABLE IF NOT EXISTS document_quality_scores (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    document_id     VARCHAR(36) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    parse_score     INTEGER CHECK (parse_score >= 0 AND parse_score <= 100),
    chunk_score     INTEGER CHECK (chunk_score >= 0 AND chunk_score <= 100),
    retrieval_score INTEGER CHECK (retrieval_score >= 0 AND retrieval_score <= 100),
    overall_score   INTEGER CHECK (overall_score >= 0 AND overall_score <= 100),
    details         JSONB DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 16. 对话模板表（依赖 users）
-- ============================================
CREATE TABLE IF NOT EXISTS prompt_templates (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    name            VARCHAR(100) NOT NULL,
    content         TEXT NOT NULL,
    category        VARCHAR(50),
    is_system       BOOLEAN DEFAULT FALSE,
    user_id         VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- （菜单权限已合并入 permissions 表，通过 type='menu' 区分）
-- ============================================

-- ============================================
-- 触发器：自动更新 document_chunks 的 tsvector
-- ============================================
CREATE OR REPLACE FUNCTION update_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := to_tsvector('chinese', COALESCE(NEW.content, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_search_vector ON document_chunks;
CREATE TRIGGER trigger_update_search_vector
    BEFORE INSERT OR UPDATE ON document_chunks
    FOR EACH ROW
    EXECUTE FUNCTION update_search_vector();

-- ============================================
-- 所有索引（在表创建完成后统一创建）
-- ============================================

-- users 索引
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- conversations 索引
CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_updated_at ON conversations(updated_at DESC);

-- messages 索引
CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);

-- documents 索引
CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(parse_status);
CREATE INDEX IF NOT EXISTS idx_documents_category_id ON documents(category_id);

-- document_chunks 索引
CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_milvus_id ON document_chunks(milvus_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_fts ON document_chunks USING GIN(search_vector);

-- images 索引
CREATE INDEX IF NOT EXISTS idx_images_document_id ON images(document_id);
CREATE INDEX IF NOT EXISTS idx_images_image_ref_id ON images(image_ref_id);

-- role_permissions 索引
CREATE INDEX IF NOT EXISTS idx_role_permissions_role_id ON role_permissions(role_id);
CREATE INDEX IF NOT EXISTS idx_role_permissions_permission_id ON role_permissions(permission_id);

-- audit_logs 索引
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at DESC);

-- document_versions 索引
CREATE INDEX IF NOT EXISTS idx_document_versions_document_id ON document_versions(document_id);

-- parse_tasks 索引
CREATE INDEX IF NOT EXISTS idx_parse_tasks_document_id ON parse_tasks(document_id);
CREATE INDEX IF NOT EXISTS idx_parse_tasks_status ON parse_tasks(status);

-- document_quality_scores 索引
CREATE INDEX IF NOT EXISTS idx_document_quality_scores_document_id ON document_quality_scores(document_id);
CREATE INDEX IF NOT EXISTS idx_document_quality_scores_created_at ON document_quality_scores(created_at DESC);

-- prompt_templates 索引
CREATE INDEX IF NOT EXISTS idx_prompt_templates_category ON prompt_templates(category);
CREATE INDEX IF NOT EXISTS idx_prompt_templates_user_id ON prompt_templates(user_id);

-- categories 索引
CREATE INDEX IF NOT EXISTS idx_categories_parent_id ON categories(parent_id);
CREATE INDEX IF NOT EXISTS idx_categories_user_id ON categories(user_id);

-- ============================================
-- 种子数据
-- ============================================

-- 预置角色
INSERT INTO roles (id, name, description) VALUES
    ('role-admin', 'admin', '系统管理员，拥有全部权限'),
    ('role-user', 'user', '普通用户，拥有基础操作权限')
ON CONFLICT (name) DO NOTHING;

-- 预置权限
INSERT INTO permissions (id, code, name, description) VALUES
    ('perm-admin-all', 'admin:all', '全部权限', '管理员特权，绕过所有权限检查'),
    ('perm-doc-read', 'document:read', '查看文档', '查看文档列表和详情'),
    ('perm-doc-write', 'document:write', '上传文档', '上传新文档到知识库'),
    ('perm-doc-delete', 'document:delete', '删除文档', '删除知识库中的文档'),
    ('perm-cat-manage', 'category:manage', '管理分类', '创建、编辑、删除分类'),
    ('perm-chat-use', 'chat:use', '使用对话', '创建对话和发送消息'),
    ('perm-user-manage', 'user:manage', '管理用户', '查看和修改其他用户信息')
ON CONFLICT (code) DO NOTHING;

-- 分配权限
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
WHERE r.name = 'admin'
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
WHERE r.name = 'user' AND p.code IN ('document:read', 'document:write', 'document:delete', 'category:manage', 'chat:use')
ON CONFLICT DO NOTHING;

-- 预置系统菜单（以 type='menu' 存入 permissions 表）
INSERT INTO permissions (id, code, name, type, path, icon, parent_id, sort_order, hidden) VALUES
    ('menu-dashboard', 'dashboard', '仪表盘', 'menu', '/', 'LayoutDashboard', NULL, 1, FALSE),
    ('menu-kb', 'knowledge_base', '文档中心', 'menu', '/knowledge-base', 'FolderOpen', NULL, 2, FALSE),
    ('menu-chat', 'chat', '智能对话', 'menu', '/chat', 'MessageSquare', NULL, 3, FALSE),
    ('menu-category', 'category', '分类管理', 'menu', '/category', 'Tags', NULL, 4, FALSE),
    ('menu-prompt', 'prompt_market', 'Prompt 市场', 'menu', '/prompt-market', 'Sparkles', NULL, 5, FALSE),
    ('menu-data-analysis', 'data_analysis', '数据分析', 'menu', '/data-analysis', 'BarChart3', NULL, 7, FALSE),
    ('menu-profile', 'profile', '个人设置', 'menu', '/profile', 'Settings', NULL, 10, FALSE),
    ('menu-audit', 'audit_log', '审计日志', 'menu', '/audit-log', 'Shield', NULL, 11, FALSE),
    ('menu-users', 'user_manage', '用户管理', 'menu', '/users', 'Users', NULL, 12, FALSE),
    ('menu-roles', 'role_manage', '角色权限', 'menu', '/roles', 'ShieldCheck', NULL, 13, FALSE),
    ('menu-manage', 'menu_manage', '菜单管理', 'menu', '/menu-manage', 'BookOpen', NULL, 14, FALSE),
    ('menu-config-center', 'menu-config-center', '配置中心', 'menu', NULL, 'Settings', NULL, 15, FALSE),
    ('menu-model-config', 'menu-model-config', '模型配置', 'menu', '/model-config', 'Bot', 'menu-config-center', 1, FALSE),
    ('menu-parse-strategies', 'parse_strategies', '解析策略', 'menu', '/parse-strategies', 'BookOpen', 'menu-config-center', 2, FALSE),
    ('menu-retrieval-config', 'menu-retrieval-config', '检索配置', 'menu', '/retrieval-config', 'SlidersHorizontal', 'menu-config-center', 3, FALSE)
ON CONFLICT (code) DO NOTHING;

-- admin 分配全部权限（菜单 + API）
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
WHERE r.name = 'admin'
ON CONFLICT DO NOTHING;

-- user 分配工作区菜单 + 基础 API 权限
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
WHERE r.name = 'user' AND (
    p.code IN ('document:read', 'document:write', 'document:delete', 'category:manage', 'chat:use')
    OR p.type = 'menu' AND p.code IN ('dashboard', 'knowledge_base', 'chat', 'category', 'prompt_market', 'parse_strategies', 'profile')
)
ON CONFLICT DO NOTHING;

-- 预置系统模板
INSERT INTO prompt_templates (id, name, content, category, is_system) VALUES
    ('tpl-summary', '文档总结', '请对以下文档进行详细总结，提取关键要点和结论：\n\n{content}', '文档分析', TRUE),
    ('tpl-compare', '竞品分析', '请对以下产品进行竞品分析，从功能、价格、用户体验等维度对比：\n\n{content}', '市场分析', TRUE),
    ('tpl-code', '代码审查', '请审查以下代码，指出潜在问题、优化建议和安全风险：\n\n{content}', '开发', TRUE),
    ('tpl-explain', '概念解释', '请用通俗易懂的语言解释以下概念，适合非技术背景的人理解：\n\n{content}', '学习', TRUE)
ON CONFLICT (id) DO NOTHING;

-- 预置系统管理员（密码: admin123，使用 pbkdf2_sha256 哈希）
INSERT INTO users (id, username, email, password_hash, role, status, token_quota_monthly)
VALUES (
    'admin-sys-0000-0000-000000000001',
    'admin',
    'admin@aura-ai.local',
    '$pbkdf2-sha256$29000$GYPQeo9x7h0DgBDCOKdUKg$Rrgd06Vvkqs5zHRm/iUw7CoVwPyWbeYoK3GucLq.q.U',
    'admin',
    'active',
    10000000
)
ON CONFLICT (username) DO NOTHING;

-- 为预置 admin 分配 admin 角色（user_roles 多对多关联）
INSERT INTO user_roles (user_id, role_id)
SELECT u.id, r.id FROM users u, roles r
WHERE u.username = 'admin' AND r.name = 'admin'
ON CONFLICT DO NOTHING;

-- ============================================
-- 17. 数据源配置表（BI 多数据源支持）
-- ============================================
CREATE TABLE IF NOT EXISTS data_sources (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    name            VARCHAR(100) NOT NULL,
    type            VARCHAR(32) DEFAULT 'postgresql',  -- postgresql / mysql / clickhouse / csv
    connection_config JSONB DEFAULT '{}',
    schema_metadata JSONB DEFAULT '{}',  -- 人工维护的表/字段别名、注释、枚举、关系、指标
    is_active       BOOLEAN DEFAULT TRUE,
    user_id         VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_data_sources_user_id ON data_sources(user_id);

-- ============================================
-- 18. BI 查询日志表（审计与历史）
-- ============================================
CREATE TABLE IF NOT EXISTS bi_query_logs (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    user_id         VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    data_source_id  VARCHAR(36) REFERENCES data_sources(id) ON DELETE SET NULL,
    natural_language_query TEXT,
    generated_sql   TEXT,
    query_result_summary JSONB DEFAULT '{}',
    execution_time_ms INTEGER DEFAULT 0,
    row_count       INTEGER DEFAULT 0,
    status          VARCHAR(20) DEFAULT 'success',  -- success / error / timeout
    error_message   TEXT,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bi_query_logs_user_id ON bi_query_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_bi_query_logs_created_at ON bi_query_logs(created_at DESC);

-- ============================================
-- 19. BI 报表表（保存与分享）
-- ============================================
CREATE TABLE IF NOT EXISTS bi_reports (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    user_id         VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE,
    title           VARCHAR(200) NOT NULL DEFAULT '未命名报表',
    description     TEXT,
    query_log_id    VARCHAR(36) REFERENCES bi_query_logs(id) ON DELETE SET NULL,
    chart_configs   JSONB DEFAULT '[]',
    is_shared       BOOLEAN DEFAULT FALSE,
    share_token     VARCHAR(36) UNIQUE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bi_reports_user_id ON bi_reports(user_id);
CREATE INDEX IF NOT EXISTS idx_bi_reports_share_token ON bi_reports(share_token);

-- ============================================
-- 20. 数据权限表（表级/字段级权限控制）
-- ============================================
CREATE TABLE IF NOT EXISTS data_permissions (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    user_id         VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE,
    data_source_id  VARCHAR(36) REFERENCES data_sources(id) ON DELETE CASCADE,
    allowed_tables  JSONB DEFAULT '[]',
    allowed_columns JSONB DEFAULT '{}',
    row_filters     JSONB DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, data_source_id)
);

CREATE INDEX IF NOT EXISTS idx_data_permissions_user_id ON data_permissions(user_id);

-- ============================================
-- 21. GraphRAG 知识图谱表（实体/关系/chunk 关联/社区）
-- ============================================
CREATE TABLE IF NOT EXISTS kg_entities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    entity_type     TEXT,
    description     TEXT,
    name_normalized TEXT NOT NULL UNIQUE,
    chunk_count     INTEGER DEFAULT 0,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS kg_relations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_entity_id UUID NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
    target_entity_id UUID NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
    relation_type    TEXT,
    description      TEXT,
    weight           FLOAT DEFAULT 1.0,
    chunk_id         TEXT,
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kg_relations_source ON kg_relations(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_kg_relations_target ON kg_relations(target_entity_id);

CREATE TABLE IF NOT EXISTS kg_chunk_entities (
    chunk_id  TEXT NOT NULL,
    entity_id UUID NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
    doc_id    TEXT,
    PRIMARY KEY (chunk_id, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_kg_chunk_entities_entity ON kg_chunk_entities(entity_id);
CREATE INDEX IF NOT EXISTS idx_kg_chunk_entities_doc ON kg_chunk_entities(doc_id);

CREATE TABLE IF NOT EXISTS kg_communities (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    level         INTEGER NOT NULL,
    community_key TEXT,
    title         TEXT,
    summary       TEXT,
    entity_count  INTEGER,
    entity_ids    JSONB,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
