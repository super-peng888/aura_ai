-- ============================================
-- Schema 迁移：检索配置新增 Agentic 修正循环字段
-- （enable_corrective_loop 默认关闭 = 行为与旧版一致）
-- 幂等：可重复执行
-- ============================================

ALTER TABLE system_retrieval_config
    ADD COLUMN IF NOT EXISTS enable_corrective_loop BOOLEAN;

ALTER TABLE system_retrieval_config
    ADD COLUMN IF NOT EXISTS max_retries INTEGER;
