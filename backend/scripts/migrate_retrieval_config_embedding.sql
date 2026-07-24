-- ============================================
-- Schema 迁移：检索配置新增 Embedding 模型配置字段
-- （模型类配置从 .env 迁到页面配置中心；NULL = 未配置，embedding 能力不可用）
-- 幂等：可重复执行
-- ============================================

ALTER TABLE system_retrieval_config
    ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(100);

ALTER TABLE system_retrieval_config
    ADD COLUMN IF NOT EXISTS embedding_base_url VARCHAR(500);

ALTER TABLE system_retrieval_config
    ADD COLUMN IF NOT EXISTS embedding_api_key VARCHAR(500);

ALTER TABLE system_retrieval_config
    ADD COLUMN IF NOT EXISTS embedding_dim INTEGER;
