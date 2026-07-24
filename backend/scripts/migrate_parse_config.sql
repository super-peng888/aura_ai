-- ============================================
-- 系统级解析配置表（VLM 视觉解析模型，单例表）
-- 幂等，可重复执行
-- ============================================

CREATE TABLE IF NOT EXISTS system_parse_config (
    id VARCHAR(36) PRIMARY KEY,
    -- VLM 视觉解析模型（默认 qwen3-vl-flash；api_key Fernet 加密存储）
    vlm_model VARCHAR(100),
    vlm_base_url VARCHAR(512),
    vlm_api_key TEXT,
    vlm_detail_level VARCHAR(10),
    vlm_max_tokens INTEGER,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
