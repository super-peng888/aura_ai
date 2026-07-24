-- ============================================
-- Schema 迁移：数据源新增 schema_metadata 字段
-- 用于已有数据库的增量更新（不删除数据）
-- ============================================

ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS schema_metadata JSONB DEFAULT '{}';

-- 为已存在记录填充空对象，避免前端拿到 NULL
UPDATE data_sources SET schema_metadata = '{}' WHERE schema_metadata IS NULL;
