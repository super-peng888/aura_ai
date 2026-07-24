# 检索评测基线记录

> **状态：待真实环境跑出基线后填写。**
> 填写前请先用真实业务问题替换 `golden.jsonl` 中的占位条目（扩充到 30-50 条），
> 然后在未改造的检索链路上运行：
> `.venv/Scripts/python -m evals.run_retrieval_eval --k 5 --output evals/reports/baseline.json`

## 基线信息

- 日期：_待填_
- 评测人：_待填_
- golden 数据集版本：_待填（条目数 / 最后修改日期）_
- 代码版本：_待填（分支 / commit）_

## 配置快照

记录评测时 `retrieval_config_service.resolve()` 的运行时配置与 `.env` 中的 `RAG_*` 项：

| 配置项 | 值 |
| --- | --- |
| enable_query_rewrite | _待填_ |
| enable_rerank | _待填_ |
| enable_vector_search | _待填_ |
| enable_keyword_search | _待填_ |
| rerank_top_k | _待填_ |
| similarity_threshold | _待填_ |
| embedding 模型 | _待填_ |
| reranker 模型 | _待填_ |
| LLM 模型（judge / 改写） | _待填_ |

## 检索指标（k = _待填_）

| 指标 | 基线值 | 改造后 | 变化 |
| --- | --- | --- | --- |
| hit rate@k | _待填_ | | |
| MRR | _待填_ | | |
| keyword recall | _待填_ | | |

## 答案质量指标

| 指标 | 基线值 | 改造后 | 变化 |
| --- | --- | --- | --- |
| faithfulness (1-5) | _待填_ | | |
| answer relevance (1-5) | _待填_ | | |

## 分 category 表现（可选）

| category | n | hit rate | MRR | keyword recall |
| --- | --- | --- | --- | --- |
| single-hop | _待填_ | | | |
| multi-hop | _待填_ | | | |
| global | _待填_ | | | |

## 结论

_待填：基线总体表现、明显短板（哪些 query / category 未命中）、下一步改造方向。_
