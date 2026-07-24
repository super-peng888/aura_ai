"""GraphRAG 实体/关系抽取服务（基于 langextract + OpenAI 兼容端点）。

- 每 chunk 一次 LLM 调用，串行执行；单 chunk 失败仅记日志，不阻断整体
- LLM 客户端懒加载：首次抽取时才按 app.services.llm_service 的系统默认配置构建
- 实体按 name_normalized 归一并合并（大小写折叠 / 去空白 / 全半角统一）
"""

from __future__ import annotations

import asyncio
import logging
import unicodedata
from dataclasses import dataclass, field

import langextract as lx

logger = logging.getLogger(__name__)

# 实体类型（中文企业文档场景）
ENTITY_TYPES = ["人物", "组织", "产品", "技术", "概念", "地点", "事件"]

ENTITY_EXTRACTION_CLASS = "entity"
RELATION_EXTRACTION_CLASS = "relation"

PROMPT_DESCRIPTION = (
    "从中文企业文档文本中抽取知识图谱要素，共两类：\n"
    "1. entity（实体）：文本中出现的命名实体。extraction_text 为原文中出现的实体名称，"
    "attributes 包含 entity_type（人物/组织/产品/技术/概念/地点/事件）与 description（一句话描述）。\n"
    "2. relation（关系）：实体之间明确存在的语义关系。extraction_text 为体现该关系的原文片段，"
    "attributes 包含 source（源实体名称）、target（目标实体名称）、"
    "relation_type（关系类型，如 隶属于/研发/发布/应用于/合作/位于）与 description（一句话描述）。\n"
    "要求：仅抽取文本中明确陈述的信息，不要推测；实体名称必须与原文一致。"
)

_EXAMPLES = [
    lx.data.ExampleData(
        text="阿里巴巴集团于2023年发布了通义千问大模型，该模型由达摩院研发，已在钉钉中集成应用。",
        extractions=[
            lx.data.Extraction(
                extraction_class="entity",
                extraction_text="阿里巴巴集团",
                attributes={"entity_type": "组织", "description": "中国科技公司"},
            ),
            lx.data.Extraction(
                extraction_class="entity",
                extraction_text="通义千问大模型",
                attributes={"entity_type": "产品", "description": "阿里巴巴发布的大语言模型"},
            ),
            lx.data.Extraction(
                extraction_class="entity",
                extraction_text="达摩院",
                attributes={"entity_type": "组织", "description": "阿里巴巴旗下研究机构"},
            ),
            lx.data.Extraction(
                extraction_class="entity",
                extraction_text="钉钉",
                attributes={"entity_type": "产品", "description": "企业协同办公平台"},
            ),
            lx.data.Extraction(
                extraction_class="relation",
                extraction_text="阿里巴巴集团于2023年发布了通义千问大模型",
                attributes={
                    "source": "阿里巴巴集团",
                    "target": "通义千问大模型",
                    "relation_type": "发布",
                    "description": "阿里巴巴集团于2023年发布通义千问大模型",
                },
            ),
            lx.data.Extraction(
                extraction_class="relation",
                extraction_text="该模型由达摩院研发",
                attributes={
                    "source": "达摩院",
                    "target": "通义千问大模型",
                    "relation_type": "研发",
                    "description": "通义千问大模型由达摩院研发",
                },
            ),
            lx.data.Extraction(
                extraction_class="relation",
                extraction_text="已在钉钉中集成应用",
                attributes={
                    "source": "通义千问大模型",
                    "target": "钉钉",
                    "relation_type": "应用于",
                    "description": "通义千问大模型已在钉钉中集成应用",
                },
            ),
        ],
    )
]


@dataclass
class Entity:
    """抽取出的实体（跨 chunk 合并后 chunk_ids 可含多个）。"""

    name: str
    entity_type: str = "概念"
    description: str = ""
    name_normalized: str = ""
    chunk_ids: list[str] = field(default_factory=list)


@dataclass
class Relation:
    """抽取出的实体间关系。"""

    source_name: str
    target_name: str
    relation_type: str = "相关"
    description: str = ""
    weight: float = 1.0
    chunk_id: str = ""
    source_normalized: str = ""
    target_normalized: str = ""


def normalize_entity_name(name: str) -> str:
    """实体名归一：NFKC（全半角统一）→ casefold（大小写折叠）→ 去除所有空白字符。"""
    if not name:
        return ""
    text = unicodedata.normalize("NFKC", name)
    text = text.casefold()
    return "".join(text.split())


# ---------------------------------------------------------------------------
# LLM 模型配置（懒加载）
# ---------------------------------------------------------------------------

_model_config = None


def _build_model_config():
    """按系统默认 LLM（settings）构建 langextract ModelConfig。

    系统默认 deepseek 与用户自定义端点均为 OpenAI 兼容协议，
    复用 LLMFactory 的配置解析（api_key / base_url / model）。
    """
    from app.services.llm_service import LLMFactory

    llm = LLMFactory.create()
    return lx.factory.ModelConfig(
        model_id=llm.model,
        provider="openai",
        provider_kwargs={"api_key": llm.api_key, "base_url": llm.base_url},
    )


def _get_model_config():
    global _model_config
    if _model_config is None:
        _model_config = _build_model_config()
    return _model_config


# ---------------------------------------------------------------------------
# 单 chunk 抽取与结果解析
# ---------------------------------------------------------------------------

def _extract_chunk_sync(text: str) -> list:
    """同步调用 langextract 抽取单个 chunk，返回 Extraction 列表。"""
    result = lx.extract(
        text,
        prompt_description=PROMPT_DESCRIPTION,
        examples=_EXAMPLES,
        config=_get_model_config(),
        fence_output=True,             # OpenAI 兼容端点统一走 ```json 围栏输出
        use_schema_constraints=False,  # 不依赖 response_format，兼容性最好
        max_char_buffer=4000,
        show_progress=False,
    )
    docs = result if isinstance(result, list) else [result]
    extractions: list = []
    for doc in docs:
        extractions.extend(getattr(doc, "extractions", None) or [])
    return extractions


def _attr_str(value) -> str:
    """attributes 值可能是 str 或 list[str]，统一取 str。"""
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value) if value is not None else ""


def _parse_extractions(extractions: list, chunk_id: str) -> tuple[list[Entity], list[Relation]]:
    """把 langextract Extraction 列表解析为 Entity / Relation。"""
    entities: list[Entity] = []
    relations: list[Relation] = []
    for ext in extractions:
        attrs = getattr(ext, "attributes", None) or {}
        ext_class = getattr(ext, "extraction_class", "") or ""
        ext_text = (getattr(ext, "extraction_text", "") or "").strip()

        if ext_class == ENTITY_EXTRACTION_CLASS:
            if not ext_text:
                continue
            entities.append(
                Entity(
                    name=ext_text,
                    entity_type=_attr_str(attrs.get("entity_type")) or "概念",
                    description=_attr_str(attrs.get("description")),
                    name_normalized=normalize_entity_name(ext_text),
                    chunk_ids=[chunk_id] if chunk_id else [],
                )
            )
        elif ext_class == RELATION_EXTRACTION_CLASS:
            source = _attr_str(attrs.get("source")).strip()
            target = _attr_str(attrs.get("target")).strip()
            if not source or not target:
                continue
            relations.append(
                Relation(
                    source_name=source,
                    target_name=target,
                    relation_type=_attr_str(attrs.get("relation_type")) or "相关",
                    description=_attr_str(attrs.get("description")),
                    chunk_id=chunk_id,
                    source_normalized=normalize_entity_name(source),
                    target_normalized=normalize_entity_name(target),
                )
            )
    return entities, relations


def _merge_entities(entities: list[Entity]) -> list[Entity]:
    """按 name_normalized 合并同名实体：描述取最长，类型优先非“概念”，chunk_ids 去重合并。"""
    merged: dict[str, Entity] = {}
    for ent in entities:
        key = ent.name_normalized
        if not key:
            continue
        existing = merged.get(key)
        if existing is None:
            merged[key] = ent
            continue
        if len(ent.description) > len(existing.description):
            existing.description = ent.description
        if existing.entity_type == "概念" and ent.entity_type != "概念":
            existing.entity_type = ent.entity_type
        for cid in ent.chunk_ids:
            if cid not in existing.chunk_ids:
                existing.chunk_ids.append(cid)
    return list(merged.values())


def _merge_relations(relations: list[Relation]) -> list[Relation]:
    """按 (source, target, relation_type) 归一合并：重复出现则权重累加。"""
    merged: dict[tuple, Relation] = {}
    for rel in relations:
        if not rel.source_normalized or not rel.target_normalized:
            continue
        key = (
            rel.source_normalized,
            rel.target_normalized,
            normalize_entity_name(rel.relation_type),
        )
        existing = merged.get(key)
        if existing is None:
            merged[key] = rel
            continue
        existing.weight += 1.0
        if len(rel.description) > len(existing.description):
            existing.description = rel.description
    return list(merged.values())


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

async def extract_entities_relations(chunks: list[dict]) -> tuple[list[Entity], list[Relation]]:
    """对 chunk 列表抽取实体与关系（串行，每 chunk 一次 LLM 调用，单 chunk 失败不阻断）。

    chunks: [{"chunk_id": str, "content": str, ...}, ...]
    返回按 name_normalized 合并后的 (entities, relations)。
    """
    all_entities: list[Entity] = []
    all_relations: list[Relation] = []
    for chunk in chunks:
        text = (chunk.get("content") or "").strip()
        chunk_id = str(chunk.get("chunk_id") or "")
        if not text:
            continue
        try:
            extractions = await asyncio.to_thread(_extract_chunk_sync, text)
        except Exception as e:
            logger.warning("GraphRAG extraction failed for chunk %s: %s", chunk_id, e)
            continue
        try:
            entities, relations = _parse_extractions(extractions, chunk_id)
            all_entities.extend(entities)
            all_relations.extend(relations)
        except Exception as e:
            logger.warning("GraphRAG extraction parse failed for chunk %s: %s", chunk_id, e)
            continue
    return _merge_entities(all_entities), _merge_relations(all_relations)
