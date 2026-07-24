-- ============================================
-- Schema 迁移：检索配置新增 GraphRAG / RAG 模式字段
-- （rag_mode 默认 pipeline、enable_graph_rag 默认关闭 = 行为与旧版一致）
-- 幂等：可重复执行
-- ============================================

ALTER TABLE system_retrieval_config
    ADD COLUMN IF NOT EXISTS rag_mode VARCHAR(20);

ALTER TABLE system_retrieval_config
    ADD COLUMN IF NOT EXISTS enable_graph_rag BOOLEAN;

ALTER TABLE system_retrieval_config
    ADD COLUMN IF NOT EXISTS graph_search_mode VARCHAR(20);
