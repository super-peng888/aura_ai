"""evals 评测基建测试：指标函数纯单测 + --mock 模式端到端。

不连接任何外部服务（Milvus/PG/Redis/LLM）。
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from evals.metrics import (  # noqa: E402
    aggregate,
    evaluate_item,
    hit_rate,
    keyword_recall,
    reciprocal_rank,
)
from evals.run_answer_eval import main as answer_main  # noqa: E402
from evals.run_answer_eval import parse_judge_scores  # noqa: E402
from evals.run_retrieval_eval import load_golden  # noqa: E402
from evals.run_retrieval_eval import main as retrieval_main  # noqa: E402

# ---------------------------------------------------------------------------
# hit_rate
# ---------------------------------------------------------------------------


def _results(*doc_ids):
    return [{"chunk_id": f"c{i}", "document_id": d, "content": f"内容 {i}", "score": 0.9 - i * 0.1}
           for i, d in enumerate(doc_ids)]


class TestHitRate:
    def test_hit_first(self):
        assert hit_rate(["doc_a"], _results("doc_a", "doc_b")) == 1.0

    def test_hit_later_rank(self):
        assert hit_rate(["doc_b"], _results("doc_x", "doc_b")) == 1.0

    def test_miss(self):
        assert hit_rate(["doc_a"], _results("doc_x", "doc_y")) == 0.0

    def test_multiple_expected_any_hit(self):
        assert hit_rate(["doc_a", "doc_b"], _results("doc_x", "doc_b")) == 1.0

    def test_empty_results(self):
        assert hit_rate(["doc_a"], []) == 0.0

    def test_no_expected_docs_treated_as_na(self):
        assert hit_rate([], _results("doc_x")) == 1.0


# ---------------------------------------------------------------------------
# reciprocal_rank
# ---------------------------------------------------------------------------


class TestReciprocalRank:
    def test_rank_1(self):
        assert reciprocal_rank(["doc_a"], _results("doc_a", "doc_b")) == 1.0

    def test_rank_2(self):
        assert reciprocal_rank(["doc_b"], _results("doc_x", "doc_b")) == 0.5

    def test_rank_4(self):
        assert reciprocal_rank(["doc_d"], _results("a", "b", "c", "doc_d")) == 0.25

    def test_miss(self):
        assert reciprocal_rank(["doc_a"], _results("doc_x")) == 0.0

    def test_first_of_multiple_expected(self):
        # doc_b 在 rank 2，doc_a 在 rank 3，取首个命中的 rank 2
        results = _results("doc_x", "doc_b", "doc_a")
        assert reciprocal_rank(["doc_a", "doc_b"], results) == 0.5

    def test_no_expected_docs_treated_as_na(self):
        assert reciprocal_rank([], _results("doc_x")) == 1.0


# ---------------------------------------------------------------------------
# keyword_recall
# ---------------------------------------------------------------------------


class TestKeywordRecall:
    def test_all_hit(self):
        results = [{"document_id": "d", "content": "年假为带薪假期"}]
        assert keyword_recall(["年假", "带薪"], results) == 1.0

    def test_partial_hit(self):
        results = [{"document_id": "d", "content": "年假规定"}]
        assert keyword_recall(["年假", "带薪"], results) == 0.5

    def test_no_hit(self):
        results = [{"document_id": "d", "content": "无关内容"}]
        assert keyword_recall(["年假"], results) == 0.0

    def test_case_insensitive(self):
        results = [{"document_id": "d", "content": "Use the API Gateway"}]
        assert keyword_recall(["api"], results) == 1.0

    def test_across_multiple_chunks(self):
        results = [
            {"document_id": "d1", "content": "包含年假"},
            {"document_id": "d2", "content": "包含带薪"},
        ]
        assert keyword_recall(["年假", "带薪"], results) == 1.0

    def test_no_keywords_treated_as_na(self):
        assert keyword_recall([], [{"content": "x"}]) == 1.0


# ---------------------------------------------------------------------------
# aggregate / evaluate_item
# ---------------------------------------------------------------------------


class TestAggregate:
    def test_means(self):
        items = [
            {"hit": 1.0, "rr": 1.0, "keyword_recall": 1.0},
            {"hit": 0.0, "rr": 0.0, "keyword_recall": 0.5},
        ]
        s = aggregate(items)
        assert s["hit_rate"] == 0.5
        assert s["mrr"] == 0.5
        assert s["keyword_recall"] == 0.75
        assert s["count"] == 2

    def test_empty(self):
        s = aggregate([])
        assert s["count"] == 0
        assert s["hit_rate"] == 0.0

    def test_evaluate_item_keys(self):
        scores = evaluate_item(["d1"], ["kw"], _results("d1"))
        assert set(scores) == {"hit", "rr", "keyword_recall"}


# ---------------------------------------------------------------------------
# judge 输出解析
# ---------------------------------------------------------------------------


class TestParseJudgeScores:
    def test_plain_json(self):
        assert parse_judge_scores('{"faithfulness": 4, "relevance": 5}') == (4.0, 5.0)

    def test_json_with_surrounding_text(self):
        raw = '评分如下:\n```json\n{"faithfulness": 3, "relevance": 4}\n```'
        assert parse_judge_scores(raw) == (3.0, 4.0)

    def test_out_of_range_rejected(self):
        with pytest.raises(ValueError):
            parse_judge_scores('{"faithfulness": 9, "relevance": 3}')

    def test_no_json_rejected(self):
        with pytest.raises(ValueError):
            parse_judge_scores("无法评分")


# ---------------------------------------------------------------------------
# golden 数据集加载
# ---------------------------------------------------------------------------


class TestGolden:
    def test_shipped_golden_loads_and_matches_schema(self):
        items = load_golden(BACKEND_DIR / "evals" / "golden.jsonl")
        assert len(items) >= 10
        required = {"id", "query", "expected_document_ids", "expected_keywords",
                    "reference_answer", "category"}
        for item in items:
            assert required <= set(item), f"{item.get('id')} 缺字段"
            assert item["category"] in {"single-hop", "multi-hop", "global"}
            assert isinstance(item["expected_document_ids"], list)
            assert isinstance(item["expected_keywords"], list)

    def test_bad_json_raises(self, tmp_path):
        p = tmp_path / "bad.jsonl"
        p.write_text("{not json}\n", encoding="utf-8")
        with pytest.raises(ValueError):
            load_golden(p)


# ---------------------------------------------------------------------------
# --mock 模式端到端
# ---------------------------------------------------------------------------


def test_retrieval_eval_mock_main(tmp_path):
    out = tmp_path / "report.json"
    rc = retrieval_main(["--mock", "--k", "5", "--output", str(out)])
    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["mode"] == "mock"
    assert report["k"] == 5
    summary = report["summary"]
    # mock 把期望文档插在 rank 2：hit=1.0, rr=0.5；关键词只覆盖第一个
    assert summary["hit_rate"] == 1.0
    assert summary["mrr"] == pytest.approx(0.5)
    assert 0.0 < summary["keyword_recall"] <= 1.0
    assert len(report["items"]) == summary["count"]


def test_answer_eval_mock_main(tmp_path):
    out = tmp_path / "answer_report.json"
    rc = answer_main(["--mock", "--k", "5", "--output", str(out)])
    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["mode"] == "mock"
    summary = report["summary"]
    assert 1.0 <= summary["faithfulness"] <= 5.0
    assert 1.0 <= summary["relevance"] <= 5.0


def test_retrieval_eval_mock_subprocess(tmp_path):
    """以子进程方式真实跑一遍脚本，验证独立运行能力。"""
    out = tmp_path / "sub_report.json"
    proc = subprocess.run(
        [sys.executable, "-m", "evals.run_retrieval_eval", "--mock", "--output", str(out)],
        cwd=BACKEND_DIR, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "hit_rate@5" in proc.stdout
    assert out.exists()
