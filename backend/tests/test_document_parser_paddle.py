"""PaddleOCR 解析模式测试（全部 mock，不加载真实 paddle/torch/模型）。"""

import builtins
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
import pytest

from app.services import document_parser
from app.services.document_parser import (
    ParseStrategyConfig,
    parse_document,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_pdf(tmp_path: Path, num_pages: int = 2) -> str:
    """生成一个带文本的测试 PDF。"""
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"page {i + 1} content")
    doc.save(str(pdf_path))
    doc.close()
    return str(pdf_path)


def _make_png(tmp_path: Path) -> str:
    """生成一张测试 PNG。"""
    png_path = tmp_path / "sample.png"
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 64, 64))
    pix.save(str(png_path))
    return str(png_path)


def _ocr_result(texts, boxes=None):
    """构造与 paddlex OCRResult 等价的 dict。"""
    if boxes is None:
        boxes = [[0, i * 20, 100, i * 20 + 10] for i in range(len(texts))]
    return {"rec_texts": list(texts), "rec_scores": [0.99] * len(texts), "rec_boxes": boxes}


def _mock_ocr(predict_return=None, predict_side_effect=None):
    mock = MagicMock(name="PaddleOCRInstance")
    if predict_side_effect is not None:
        mock.predict.side_effect = predict_side_effect
    else:
        mock.predict.return_value = predict_return
    return mock


# ---------------------------------------------------------------------------
# 模块导入约束：import document_parser 不得加载 paddle/paddleocr/torch
# ---------------------------------------------------------------------------

def test_module_import_does_not_load_paddle_or_torch():
    code = (
        "import sys; "
        "import app.services.document_parser; "
        "assert 'paddle' not in sys.modules, 'paddle loaded at import time'; "
        "assert 'paddleocr' not in sys.modules, 'paddleocr loaded at import time'; "
        "assert 'torch' not in sys.modules, 'torch loaded at import time'; "
        "print('ok')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_DIR),
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


def test_lazy_loader_imports_torch_before_paddleocr(monkeypatch):
    """_get_paddle_ocr 内部必须先 import torch 再 import paddleocr，且单例只建一次。"""
    order = []
    real_import = builtins.__import__

    fake_torch = types.ModuleType("torch")
    fake_paddleocr = types.ModuleType("paddleocr")
    constructed = []

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            constructed.append(kwargs)

    fake_paddleocr.PaddleOCR = FakePaddleOCR

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "torch":
            order.append("torch")
            return fake_torch
        if name == "paddleocr":
            order.append("paddleocr")
            return fake_paddleocr
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(document_parser, "_paddle_ocr_instance", None)

    inst = document_parser._get_paddle_ocr()
    assert isinstance(inst, FakePaddleOCR)
    assert order[:2] == ["torch", "paddleocr"]
    # 关闭方向分类/矫正/文本行方向，仅检测+识别
    assert constructed[0]["use_doc_orientation_classify"] is False
    assert constructed[0]["use_doc_unwarping"] is False
    assert constructed[0]["use_textline_orientation"] is False

    # 单例：第二次调用不再重建
    document_parser._get_paddle_ocr()
    assert len(constructed) == 1


# ---------------------------------------------------------------------------
# OCR 结果组装
# ---------------------------------------------------------------------------

class TestOcrResultToText:
    def test_reading_order_sorted_by_box(self):
        # 故意打乱顺序，验证按 (y, x) 重排
        result = _ocr_result(
            ["右栏", "左上", "左下"],
            boxes=[[200, 0, 300, 10], [0, 0, 100, 10], [0, 30, 100, 40]],
        )
        assert document_parser._ocr_result_to_text(result) == "左上\n右栏\n左下"

    def test_empty_result(self):
        assert document_parser._ocr_result_to_text({}) == ""
        assert document_parser._ocr_result_to_text({"rec_texts": []}) == ""

    def test_missing_boxes_keeps_original_order(self):
        result = {"rec_texts": ["a", "b", "c"]}
        assert document_parser._ocr_result_to_text(result) == "a\nb\nc"

    def test_blank_texts_filtered(self):
        result = _ocr_result(["hello", "  ", "world"])
        assert document_parser._ocr_result_to_text(result) == "hello\nworld"


# ---------------------------------------------------------------------------
# parse_document 模式分发
# ---------------------------------------------------------------------------

class TestPaddleocrDispatch:
    def test_paddleocr_mode_routes_to_paddleocr(self, tmp_path):
        pdf_path = _make_pdf(tmp_path, num_pages=2)
        mock = _mock_ocr(predict_return=[_ocr_result(["识别文本"])] * 2)
        strategy = ParseStrategyConfig(parse_mode="paddleocr")

        with patch.object(document_parser, "_get_paddle_ocr", return_value=mock):
            result = parse_document(pdf_path, "doc1", strategy)

        assert result.mode_used == "paddleocr"
        assert len(result.pages) == 2
        assert mock.predict.call_count == 2
        for i, page in enumerate(result.pages):
            assert page.page_number == i + 1
            assert page.text == "识别文本"
            assert page.tables == []
            assert page.headings == []

    def test_ocr_mode_aliases_to_paddleocr(self, tmp_path):
        pdf_path = _make_pdf(tmp_path, num_pages=1)
        mock = _mock_ocr(predict_return=[_ocr_result(["alias ok"])])
        strategy = ParseStrategyConfig(parse_mode="ocr")

        with patch.object(document_parser, "_get_paddle_ocr", return_value=mock):
            result = parse_document(pdf_path, "doc2", strategy)

        assert result.mode_used == "ocr"
        assert mock.predict.call_count == 1
        assert result.pages[0].text == "alias ok"

    def test_pymupdf_mode_not_affected(self, tmp_path):
        pdf_path = _make_pdf(tmp_path, num_pages=1)
        strategy = ParseStrategyConfig(parse_mode="pymupdf")

        with patch.object(document_parser, "_get_paddle_ocr") as getter:
            result = parse_document(pdf_path, "doc3", strategy)

        getter.assert_not_called()
        assert result.mode_used == "pymupdf"
        assert "page 1 content" in result.pages[0].text

    def test_image_file_with_paddleocr_mode(self, tmp_path):
        png_path = _make_png(tmp_path)
        mock = _mock_ocr(predict_return=[_ocr_result(["图中文字"])])
        strategy = ParseStrategyConfig(parse_mode="paddleocr")

        with patch.object(document_parser, "_get_paddle_ocr", return_value=mock):
            result = parse_document(png_path, "doc4", strategy)

        assert result.mode_used == "paddleocr"
        assert len(result.pages) == 1
        assert result.pages[0].text == "图中文字"
        # 图片文件按路径直接传入 OCR
        args, _ = mock.predict.call_args
        assert args[0] == [png_path]
        # 原图仍作为 raw_image 返回，供调用方上传
        assert result.raw_images[0]["image_id"] == "doc4_img_01"
        assert result.pages[0].images == [{"image_id": "doc4_img_01"}]


# ---------------------------------------------------------------------------
# PDF 位图渲染 + 容错
# ---------------------------------------------------------------------------

class TestPdfRendering:
    def test_page_rendered_as_bgr_ndarray(self, tmp_path):
        """predict 收到的是与页面尺寸 * zoom 匹配的 BGR ndarray。"""
        pdf_path = _make_pdf(tmp_path, num_pages=1)
        mock = _mock_ocr(predict_return=[_ocr_result(["x"])])
        strategy = ParseStrategyConfig(parse_mode="paddleocr")

        with patch.object(document_parser, "_get_paddle_ocr", return_value=mock):
            parse_document(pdf_path, "doc5", strategy)

        (call_args,), _ = mock.predict.call_args
        arr = call_args[0]
        assert arr.shape[2] == 3  # 三通道
        # A4 页 595x842 pt，zoom 2x
        assert arr.shape[0] == pytest.approx(842 * 2, abs=2)
        assert arr.shape[1] == pytest.approx(595 * 2, abs=2)

    def test_page_ocr_failure_keeps_empty_text_and_continues(self, tmp_path):
        pdf_path = _make_pdf(tmp_path, num_pages=2)
        mock = _mock_ocr(predict_side_effect=[
            [_ocr_result(["第一页"])],
            RuntimeError("ocr boom"),
        ])
        strategy = ParseStrategyConfig(parse_mode="paddleocr")

        with patch.object(document_parser, "_get_paddle_ocr", return_value=mock):
            result = parse_document(pdf_path, "doc6", strategy)

        assert len(result.pages) == 2
        assert result.pages[0].text == "第一页"
        assert result.pages[1].text == ""  # 失败页空 text，不中断

    def test_empty_ocr_result_gives_empty_text(self, tmp_path):
        pdf_path = _make_pdf(tmp_path, num_pages=1)
        mock = _mock_ocr(predict_return=[])
        strategy = ParseStrategyConfig(parse_mode="paddleocr")

        with patch.object(document_parser, "_get_paddle_ocr", return_value=mock):
            result = parse_document(pdf_path, "doc7", strategy)

        assert result.pages[0].text == ""

    def test_extract_images_inserts_placeholders(self, tmp_path):
        """extract_images=True 时，页面图片按 [IMG:xxx] 约定占位并进入 raw_images。"""
        # 造一个内嵌图片的 PDF（100x100 以上才会被提取）
        pdf_path = tmp_path / "with_img.pdf"
        img_pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 120))
        img_path = tmp_path / "embedded.png"
        img_pix.save(str(img_path))
        doc = fitz.open()
        page = doc.new_page()
        page.insert_image(fitz.Rect(50, 50, 170, 170), filename=str(img_path))
        doc.save(str(pdf_path))
        doc.close()

        mock = _mock_ocr(predict_return=[_ocr_result(["正文"])])
        strategy = ParseStrategyConfig(parse_mode="paddleocr", extract_images=True)

        with patch.object(document_parser, "_get_paddle_ocr", return_value=mock):
            result = parse_document(str(pdf_path), "doc8", strategy)

        assert len(result.raw_images) == 1
        image_id = result.raw_images[0]["image_id"]
        assert f"[IMG:{image_id}]" in result.pages[0].text
        assert result.pages[0].images == [{"image_id": image_id}]
