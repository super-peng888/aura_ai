# evals — 检索评测基建（Phase 0）

独立于 `app/` 的评测脚本，不修改业务代码，通过 import 复用
`app.core.knowledge.rag_pipeline.search` 与 `app.services.llm_service.generate`。

## 文件

- `golden.jsonl` — golden 数据集（见下方标注规范）
- `metrics.py` — 指标计算纯函数（hit rate / MRR / keyword recall）
- `run_retrieval_eval.py` — 检索质量评测
- `run_answer_eval.py` — 答案质量评测（LLM-as-judge）
- `reports/` — 评测报告输出目录（JSON，按时间戳命名）
- `baseline.md` — 基线记录模板

## 用法

在 `backend/` 目录下运行（venv 位于 `backend/.venv`）：

```bash
# 检索质量评测（mock 模式：无需真实环境，验证脚本流程）
.venv/Scripts/python -m evals.run_retrieval_eval --mock

# 真实评测（需要 Milvus / PostgreSQL / Redis / .env 中的 LLM API Key）
.venv/Scripts/python -m evals.run_retrieval_eval --k 5

# 指定数据集与输出
.venv/Scripts/python -m evals.run_retrieval_eval --k 5 --golden evals/golden.jsonl --output evals/reports/baseline.json

# 答案质量评测（LLM-as-judge）
.venv/Scripts/python -m evals.run_answer_eval --mock
.venv/Scripts/python -m evals.run_answer_eval --k 5
```

也可以脚本方式运行：`python evals/run_retrieval_eval.py --mock`（脚本会自动把 backend 根目录加入 sys.path）。

## 指标定义（检索评测）

对每条 golden 样本，调用 `rag_pipeline.search(query, top_k=k)` 得到 top-k 结果后计算：

| 指标 | 定义 |
| --- | --- |
| hit@k | 期望文档（`expected_document_ids` 中任一）出现在 top-k 结果中记 1，否则 0 |
| RR | 首个期望文档的倒数排名：命中第 1 名 = 1，第 2 名 = 1/2，…，未命中 = 0 |
| keyword recall | `expected_keywords` 中出现在检索结果 chunk 内容里的比例（不区分大小写） |

汇总：**hit rate@k** = 各样本 hit@k 均值；**MRR** = 各样本 RR 均值；**keyword recall** = 各样本关键词召回均值。
样本未提供期望文档/关键词时，对应指标按 1.0 计（视为不适用，不惩罚）。

答案评测（`run_answer_eval.py`）：先用检索结果作为上下文让 LLM 生成答案，
再用 LLM-as-judge 打 **faithfulness**（答案是否忠于上下文）与 **answer relevance**（是否切题），各 1-5 分，取均值。

## Golden 标注规范

每行一个 JSON 对象（jsonl 不支持注释，规范写在这里）：

```json
{"id": "q001", "query": "...", "expected_document_ids": ["..."], "expected_keywords": ["..."], "reference_answer": "...", "category": "single-hop|multi-hop|global"}
```

- `id`：唯一编号，建议 `qNNN`。
- `query`：真实用户会问的业务问题。
- `expected_document_ids`：回答该问题应命中的文档 ID 列表，**从文档管理页复制真实 document_id**。
- `expected_keywords`：命中 chunk 内容里应包含的关键词（用于粗粒度内容校验）。
- `reference_answer`：参考答案，供人工核对与答案评测对照。
- `category`：`single-hop`（单文档可答）/ `multi-hop`（需多篇组合）/ `global`（制度类全局问题）。

**当前 `golden.jsonl` 中是 10 条通用占位条目（document_id 为 `doc_placeholder_*`）。
请用真实业务问题替换，并扩充到 30-50 条，使各 category 均衡分布。**

## 基线对比流程

1. 完成 golden 标注后，在当前未改造的检索链路上跑一遍真实评测：

   ```bash
   .venv/Scripts/python -m evals.run_retrieval_eval --k 5 --output evals/reports/baseline.json
   ```

2. 把汇总指标和当时的配置快照（`retrieval_config_service.resolve()` 的运行时配置、
   `.env` 中的 `RAG_*` 项）抄入 `baseline.md`。
3. 每次检索链路改造（换 embedding、调 top_k、改 rerank、加改写等）后重跑相同命令，
   与 `baseline.json` 逐项对比 hit rate / MRR / keyword recall 的升降，再决定是否合入。
4. 答案质量同理：先存 `run_answer_eval` 基线，改造后对比 faithfulness / relevance。

## 测试

```bash
.venv/Scripts/python -m pytest tests/test_evals.py -q
```

覆盖：指标函数的正确性（构造假检索结果，不连任何服务）+ `--mock` 模式脚本端到端跑通。
