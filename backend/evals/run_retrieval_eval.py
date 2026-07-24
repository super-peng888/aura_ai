"""检索质量评测脚本。

用法：
    .venv/Scripts/python -m evals.run_retrieval_eval --mock
    .venv/Scripts/python evals/run_retrieval_eval.py --k 5 --golden evals/golden.jsonl

指标：hit rate@k / MRR / keyword recall（定义见 evals/metrics.py 与 README.md）。
输出：终端表格 + evals/reports/<timestamp>.json。
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# 保证无论从哪个目录、以脚本还是 -m 方式运行，都能 import app 与 evals 包
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from evals.metrics import aggregate, evaluate_item  # noqa: E402

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
DEFAULT_GOLDEN = Path(__file__).resolve().parent / "golden.jsonl"


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------

def load_golden(path: Path) -> List[dict]:
    """加载 golden 数据集（jsonl，每行一条）。"""
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{lineno} JSON 解析失败: {e}") from e
    return items


# ---------------------------------------------------------------------------
# 检索后端：真实 / mock
# ---------------------------------------------------------------------------

async def real_search(query: str, top_k: int) -> List[dict]:
    """调用真实 rag_pipeline.search。依赖 Milvus / PG / Redis / LLM key。"""
    try:
        from app.core.knowledge.rag_pipeline import rag_pipeline
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"无法加载 app.core.knowledge.rag_pipeline: {e}\n"
            "真实评测需要完整运行环境：Milvus、PostgreSQL、Redis 及 .env 中的 LLM API Key。\n"
            "请确认 backend/.env 配置齐全、相关服务已启动；或用 --mock 模式验证脚本本身。"
        ) from e
    result = await rag_pipeline.search(query=query, top_k=top_k)
    return result["results"]


def mock_search(query: str, top_k: int, item: Optional[dict] = None) -> List[dict]:
    """构造确定性假检索结果，用于无环境时演示流程。

    规则：若提供了 golden 条目，则把期望文档以变化的排名插入结果，
    并让内容覆盖部分期望关键词，使三项指标都有非平凡的数值。
    """
    results = []
    expected_docs = (item or {}).get("expected_document_ids", [])
    expected_kws = (item or {}).get("expected_keywords", [])

    for i in range(top_k):
        results.append({
            "chunk_id": f"mock_chunk_{i}",
            "document_id": f"mock_doc_{i}",
            "content": f"与「{query}」相关的模拟内容片段 {i}",
            "score": round(0.9 - i * 0.1, 2),
        })

    if expected_docs:
        # 期望文档插在 rank 2（索引 1），越界则追加
        pos = min(1, len(results))
        hit_content = " ".join(expected_kws[:1]) + " 命中片段" if expected_kws else "命中片段"
        hit_chunk = {
            "chunk_id": "mock_chunk_hit",
            "document_id": expected_docs[0],
            "content": hit_content,
            "score": 0.85,
        }
        if pos < len(results):
            results[pos] = hit_chunk
        else:
            results.append(hit_chunk)
    return results


# ---------------------------------------------------------------------------
# 评测主流程
# ---------------------------------------------------------------------------

async def run_eval(golden_path: Path, k: int, use_mock: bool) -> dict:
    items = load_golden(golden_path)
    if not items:
        raise ValueError(f"golden 数据集为空: {golden_path}")

    per_item = []
    for item in items:
        query = item["query"]
        if use_mock:
            results = mock_search(query, k, item)
        else:
            results = await real_search(query, k)
        scores = evaluate_item(
            expected_document_ids=item.get("expected_document_ids", []),
            expected_keywords=item.get("expected_keywords", []),
            results=results,
        )
        per_item.append({
            "id": item.get("id"),
            "query": query,
            "category": item.get("category"),
            "num_results": len(results),
            **scores,
        })

    summary = aggregate(per_item)
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "mode": "mock" if use_mock else "real",
        "golden": str(golden_path),
        "k": k,
        "summary": summary,
        "items": per_item,
    }


def print_report(report: dict) -> None:
    s = report["summary"]
    print(f"\n=== 检索评测报告 ({report['mode']} mode, k={report['k']}) ===")
    print(f"{'id':<8}{'hit':>6}{'rr':>8}{'kw_rec':>8}  query")
    print("-" * 70)
    for it in report["items"]:
        print(f"{str(it['id']):<8}{it['hit']:>6.2f}{it['rr']:>8.2f}{it['keyword_recall']:>8.2f}  {it['query'][:30]}")
    print("-" * 70)
    print(f"汇总: hit_rate@{report['k']} = {s['hit_rate']:.3f} | "
          f"MRR = {s['mrr']:.3f} | keyword_recall = {s['keyword_recall']:.3f} | "
          f"n = {s['count']}")


def save_report(report: dict, output: Optional[Path]) -> Path:
    if output is None:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = REPORTS_DIR / f"{ts}.json"
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return output


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="检索质量评测 (hit rate@k / MRR / keyword recall)")
    parser.add_argument("--k", type=int, default=5, help="top_k，默认 5")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN, help="golden jsonl 路径")
    parser.add_argument("--output", type=Path, default=None, help="报告输出路径（默认 evals/reports/<timestamp>.json）")
    parser.add_argument("--mock", action="store_true", help="使用假检索结果演示流程（无需真实环境）")
    args = parser.parse_args(argv)

    try:
        report = asyncio.run(run_eval(args.golden, args.k, args.mock))
    except (RuntimeError, ValueError) as e:
        print(f"[评测失败] {e}", file=sys.stderr)
        return 1

    print_report(report)
    out = save_report(report, args.output)
    print(f"报告已写入: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
