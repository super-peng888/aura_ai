-- ============================================
-- Schema 迁移：补充缺失的列
-- 用于已有数据库的增量更新（不删除数据）
-- ============================================

-- documents 表补充 strategy_id
ALTER TABLE documents ADD COLUMN IF NOT EXISTS strategy_id VARCHAR(36) REFERENCES parse_strategies(id) ON DELETE SET NULL;

-- users 表补充 default_strategy_id（如果缺失）
ALTER TABLE users ADD COLUMN IF NOT EXISTS default_strategy_id VARCHAR(36) REFERENCES parse_strategies(id) ON DELETE SET NULL;

-- users 表补充 default_model_id（如果缺失）
ALTER TABLE users ADD COLUMN IF NOT EXISTS default_model_id VARCHAR(50);

-- ============================================
-- 用户自定义模型配置表（新增）
-- ============================================
CREATE TABLE IF NOT EXISTS user_model_configs (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    user_id         VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    model           VARCHAR(100),
    api_key         VARCHAR(500),
    base_url        VARCHAR(500),
    max_tokens      INTEGER DEFAULT 4096,
    temperature     FLOAT DEFAULT 0.7,
    top_p           FLOAT DEFAULT 0.9,
    timeout         INTEGER DEFAULT 60,
    is_current      BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_model_configs_user_id ON user_model_configs(user_id);

-- documents 表其他可能缺失的列（兼容旧 schema）
ALTER TABLE documents ADD COLUMN IF NOT EXISTS original_name VARCHAR(256);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS parse_mode VARCHAR(32);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_size INTEGER;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_overlap INTEGER;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS dimension INTEGER;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS page_count INTEGER;

-- 为已存在的记录填充默认值，避免 NULL 约束问题
UPDATE documents SET original_name = filename WHERE original_name IS NULL;
