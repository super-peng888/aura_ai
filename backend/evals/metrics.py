"""检索评测指标计算（纯函数，无外部服务依赖）。

指标定义：
- hit@k        : 期望文档是否出现在 top-k 结果中（任一命中即 1）
- rr (MRR 分量): 首个期望文档的倒数排名（1/rank，未命中为 0）
- keyword recall: 期望关键词在命中 chunk 内容中出现的比例
"""

from typing import Dict, List


def hit_rate(expected_document_ids: List[str], results: List[dict]) -> float:
    """期望文档是否出现在检索结果中。无期望文档时返回 1.0（视为不适用，不惩罚）。"""
    if not expected_document_ids:
        return 1.0
    retrieved_ids = {str(r.get("document_id")) for r in results}
    return 1.0 if any(str(d) in retrieved_ids for d in expected_document_ids) else 0.0


def reciprocal_rank(expected_document_ids: List[str], results: List[dict]) -> float:
    """首个期望文档的倒数排名。无期望文档时返回 1.0（同 hit_rate 约定）。"""
    if not expected_document_ids:
        return 1.0
    expected = {str(d) for d in expected_document_ids}
    for rank, r in enumerate(results, start=1):
        if str(r.get("document_id")) in expected:
            return 1.0 / rank
    return 0.0


def keyword_recall(expected_keywords: List[str], results: List[dict]) -> float:
    """期望关键词在检索结果 chunk 内容中被覆盖的比例。无关键词时返回 1.0。"""
    if not expected_keywords:
        return 1.0
    content = "\n".join(str(r.get("content", "")) for r in results).lower()
    hits = sum(1 for kw in expected_keywords if str(kw).lower() in content)
    return hits / len(expected_keywords)


def evaluate_item(expected_document_ids: List[str], expected_keywords: List[str],
                  results: List[dict]) -> Dict[str, float]:
    """单条样本的三项指标。"""
    return {
        "hit": hit_rate(expected_document_ids, results),
        "rr": reciprocal_rank(expected_document_ids, results),
        "keyword_recall": keyword_recall(expected_keywords, results),
    }


def aggregate(items: List[Dict[str, float]]) -> Dict[str, float]:
    """汇总均值：hit_rate@k、MRR、keyword_recall。"""
    n = len(items)
    if n == 0:
        return {"hit_rate": 0.0, "mrr": 0.0, "keyword_recall": 0.0, "count": 0}
    return {
        "hit_rate": sum(i["hit"] for i in items) / n,
        "mrr": sum(i["rr"] for i in items) / n,
        "keyword_recall": sum(i["keyword_recall"] for i in items) / n,
        "count": n,
    }
