-- 为已存在的 data_permissions 表增加 row_filters 字段
ALTER TABLE data_permissions ADD COLUMN IF NOT EXISTS row_filters JSONB DEFAULT '{}';
