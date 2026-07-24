-- ============================================
-- Schema 迁移：系统级检索配置（DB 可配 + admin API）
-- ============================================

-- 1. 系统级检索配置表（单行，NULL 表示回落 .env 默认）
CREATE TABLE IF NOT EXISTS system_retrieval_config (
    id                  VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    reranker_provider   VARCHAR(20),
    reranker_model      VARCHAR(100),
    reranker_api_key    VARCHAR(500),
    reranker_base_url   VARCHAR(500),
    top_k_keyword       INTEGER,
    top_k_vector        INTEGER,
    rerank_top_k        INTEGER,
    similarity_threshold FLOAT,
    enable_query_rewrite    BOOLEAN,
    enable_keyword_search   BOOLEAN,
    enable_vector_search    BOOLEAN,
    enable_rerank           BOOLEAN,
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. 「检索配置」菜单权限
INSERT INTO permissions (id, code, name, type, path, icon, parent_id, sort_order, hidden) VALUES
    ('menu-retrieval-config', 'menu-retrieval-config', '检索配置', 'menu', '/retrieval-config', 'SlidersHorizontal', NULL, 15, FALSE)
ON CONFLICT (code) DO NOTHING;

-- 3. admin 角色授权（全部权限，含新菜单）
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
WHERE r.name = 'admin'
ON CONFLICT DO NOTHING;
