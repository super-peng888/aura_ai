"""答案质量评测脚本（LLM-as-judge，轻量版）。

对每条 golden 样本：检索 -> 基于 contexts 生成答案 -> 用 LLM 评
faithfulness（答案是否忠于检索内容）与 answer relevance（答案是否切题），各 1-5 分。

用法：
    .venv/Scripts/python -m evals.run_answer_eval --mock
    .venv/Scripts/python evals/run_answer_eval.py --k 5
"""

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from evals.run_retrieval_eval import (  # noqa: E402
    DEFAULT_GOLDEN,
    REPORTS_DIR,
    load_golden,
    mock_search,
    real_search,
)

JUDGE_PROMPT = """你是一个严格的评测员。请根据检索到的上下文，对下面这个问题的答案打分。

问题: {query}

检索上下文:
{contexts}

待评答案:
{answer}

请输出 JSON（不要输出其他内容），包含两个字段：
- faithfulness: 1-5 分，答案中的陈述是否有上下文依据（5 = 完全有据可依）
- relevance: 1-5 分，答案是否回答了问题（5 = 完全切题）
"""


# ---------------------------------------------------------------------------
# 生成与评分
# ---------------------------------------------------------------------------

def build_answer_prompt(query: str, contexts: List[dict]) -> List[dict]:
    context_str = "\n\n".join(
        f"[{i + 1}] {c.get('content', '')}" for i, c in enumerate(contexts)
    )
    return [
        {"role": "system", "content": "你是企业知识库助手，仅根据给定上下文回答问题，不知道就说不知道。"},
        {"role": "user", "content": f"上下文:\n{context_str}\n\n问题: {query}"},
    ]


async def real_generate_answer(query: str, contexts: List[dict]) -> str:
    """用 llm_service.generate 基于检索内容生成答案。"""
    from app.services.llm_service import llm_service
    return await llm_service.generate(build_answer_prompt(query, contexts))


async def real_judge(query: str, contexts: List[dict], answer: str) -> Tuple[float, float]:
    """用 llm_service.generate 做 LLM-as-judge 打分。"""
    from app.services.llm_service import llm_service
    context_str = "\n\n".join(c.get("content", "") for c in contexts)
    prompt = JUDGE_PROMPT.format(query=query, contexts=context_str, answer=answer)
    raw = await llm_service.generate([{"role": "user", "content": prompt}], temperature=0.0)
    return parse_judge_scores(raw)


def parse_judge_scores(raw: str) -> Tuple[float, float]:
    """从 judge 输出解析 (faithfulness, relevance)。解析失败抛 ValueError。"""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"judge 输出中未找到 JSON: {raw[:200]}")
    data = json.loads(m.group(0))
    faith = float(data["faithfulness"])
    rel = float(data["relevance"])
    for name, v in (("faithfulness", faith), ("relevance", rel)):
        if not 1.0 <= v <= 5.0:
            raise ValueError(f"{name} 超出 1-5 范围: {v}")
    return faith, rel


def mock_generate_answer(query: str, contexts: List[dict]) -> str:
    joined = " ".join(c.get("content", "") for c in contexts[:2])
    return f"根据检索内容：{joined}（模拟答案）"


def mock_judge(query: str, contexts: List[dict], answer: str) -> Tuple[float, float]:
    return 4.0, 4.5


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

async def run_eval(golden_path: Path, k: int, use_mock: bool) -> dict:
    items = load_golden(golden_path)
    if not items:
        raise ValueError(f"golden 数据集为空: {golden_path}")

    per_item = []
    for item in items:
        query = item["query"]
        if use_mock:
            contexts = mock_search(query, k, item)
            answer = mock_generate_answer(query, contexts)
            faith, rel = mock_judge(query, contexts, answer)
        else:
            contexts = await real_search(query, k)
            answer = await real_generate_answer(query, contexts)
            faith, rel = await real_judge(query, contexts, answer)
        per_item.append({
            "id": item.get("id"),
            "query": query,
            "category": item.get("category"),
            "answer": answer,
            "faithfulness": faith,
            "relevance": rel,
        })

    n = len(per_item)
    summary = {
        "faithfulness": sum(i["faithfulness"] for i in per_item) / n,
        "relevance": sum(i["relevance"] for i in per_item) / n,
        "count": n,
    }
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
    print(f"\n=== 答案质量评测报告 ({report['mode']} mode, k={report['k']}) ===")
    print(f"{'id':<8}{'faith':>8}{'relev':>8}  query")
    print("-" * 64)
    for it in report["items"]:
        print(f"{str(it['id']):<8}{it['faithfulness']:>8.1f}{it['relevance']:>8.1f}  {it['query'][:30]}")
    print("-" * 64)
    print(f"汇总: faithfulness = {s['faithfulness']:.2f} | relevance = {s['relevance']:.2f} | n = {s['count']}")


def save_report(report: dict, output: Optional[Path]) -> Path:
    if output is None:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = REPORTS_DIR / f"answer_{ts}.json"
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return output


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="答案质量评测 (LLM-as-judge: faithfulness / relevance)")
    parser.add_argument("--k", type=int, default=5, help="检索 top_k，默认 5")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN, help="golden jsonl 路径")
    parser.add_argument("--output", type=Path, default=None, help="报告输出路径（默认 evals/reports/answer_<timestamp>.json）")
    parser.add_argument("--mock", action="store_true", help="模拟生成与评分（无需真实环境）")
    args = parser.parse_args(argv)

    try:
        report = asyncio.run(run_eval(args.golden, args.k, args.mock))
    except ImportError as e:
        print(
            f"[评测失败] 无法加载 LLM 服务: {e}\n"
            "真实评测需要 .env 中的 LLM API Key 及检索依赖（Milvus/PG/Redis）；或用 --mock 验证脚本。",
            file=sys.stderr,
        )
        return 1
    except (RuntimeError, ValueError) as e:
        print(f"[评测失败] {e}", file=sys.stderr)
        return 1

    print_report(report)
    out = save_report(report, args.output)
    print(f"报告已写入: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
