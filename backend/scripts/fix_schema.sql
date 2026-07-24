-- 修复 Schema：将 UUID 类型改为 VARCHAR(36)，与 ORM 模型保持一致
-- 注意：这会删除所有数据，仅用于测试环境重建

DROP TABLE IF EXISTS parse_tasks CASCADE;
DROP TABLE IF EXISTS messages CASCADE;
DROP TABLE IF EXISTS conversations CASCADE;
DROP TABLE IF EXISTS document_chunks CASCADE;
DROP TABLE IF EXISTS images CASCADE;
DROP TABLE IF EXISTS documents CASCADE;
DROP TABLE IF EXISTS knowledge_bases CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- 重新执行初始化脚本
\i init_db.sql
