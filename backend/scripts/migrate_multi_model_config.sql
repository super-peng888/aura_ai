-- ============================================
-- Schema 迁移：user_model_configs 支持多模型
-- ============================================

-- 1. 添加 is_current 列（先允许 NULL，后面填充）
ALTER TABLE user_model_configs ADD COLUMN IF NOT EXISTS is_current BOOLEAN DEFAULT FALSE;

-- 2. 将现有单条记录的 is_current 设为 TRUE（兼容已有数据）
UPDATE user_model_configs SET is_current = TRUE WHERE is_current IS NULL OR is_current = FALSE;

-- 3. 删除 provider 列（所有自定义模型都走 OpenAI 兼容接口，无需区分 provider）
ALTER TABLE user_model_configs DROP COLUMN IF EXISTS provider;

-- 4. 确保 user_id 外键有 CASCADE（如果不存在则添加，PostgreSQL 需要检查）
-- 注：已有外键不会重复创建，此处仅做记录
-- ALTER TABLE user_model_configs DROP CONSTRAINT IF EXISTS fk_user_model_configs_user_id;
-- ALTER TABLE user_model_configs ADD CONSTRAINT fk_user_model_configs_user_id
--     FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
