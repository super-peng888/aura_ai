-- ============================================
-- Schema 迁移：GraphRAG 知识图谱表
-- （kg_entities / kg_relations / kg_chunk_entities / kg_communities）
-- 幂等：可重复执行
-- ============================================

CREATE TABLE IF NOT EXISTS kg_entities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    entity_type     TEXT,
    description     TEXT,
    name_normalized TEXT NOT NULL UNIQUE,
    chunk_count     INTEGER DEFAULT 0,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS kg_relations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_entity_id UUID NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
    target_entity_id UUID NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
    relation_type    TEXT,
    description      TEXT,
    weight           FLOAT DEFAULT 1.0,
    chunk_id         TEXT,
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kg_relations_source ON kg_relations(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_kg_relations_target ON kg_relations(target_entity_id);

CREATE TABLE IF NOT EXISTS kg_chunk_entities (
    chunk_id  TEXT NOT NULL,
    entity_id UUID NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
    doc_id    TEXT,
    PRIMARY KEY (chunk_id, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_kg_chunk_entities_entity ON kg_chunk_entities(entity_id);
CREATE INDEX IF NOT EXISTS idx_kg_chunk_entities_doc ON kg_chunk_entities(doc_id);

CREATE TABLE IF NOT EXISTS kg_communities (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    level         INTEGER NOT NULL,
    community_key TEXT,
    title         TEXT,
    summary       TEXT,
    entity_count  INTEGER,
    entity_ids    JSONB,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
