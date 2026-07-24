"""纯文本文件解析路由（txt/md/json/csv 自动 text 模式）与 _token_split 防死循环测试。"""

from pathlib import Path

import fitz
import pytest

from app.services.document_parser import (
    ParseStrategyConfig,
    _token_split,
    parse_document,
)


def _write(tmp_path: Path, name: str, content: bytes) -> str:
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


class TestTextFileRouting:
    @pytest.mark.parametrize(
        "name", ["a.txt", "b.md", "c.markdown", "d.json", "e.csv", "f.log"]
    )
    def test_text_extensions_route_to_text_mode(self, tmp_path, name):
        """文本扩展名自动走纯文本解析（单页、mode_used=text、无图片）。"""
        path = _write(tmp_path, name, "你好，世界\n第二行".encode("utf-8"))
        result = parse_document(path, "doc-t", ParseStrategyConfig(parse_mode="pymupdf"))

        assert result.mode_used == "text"
        assert len(result.pages) == 1
        assert result.pages[0].page_number == 1
        assert "你好，世界" in result.pages[0].text
        assert result.raw_images == []

    def test_text_ext_ignores_vlm_mode(self, tmp_path):
        """即使策略是 vlm，txt 文件仍走纯文本（不创建 VLM client、不要求 API Key）。"""
        path = _write(tmp_path, "note.txt", b"plain text content")
        result = parse_document(path, "doc-t2", ParseStrategyConfig(parse_mode="vlm"))
        assert result.mode_used == "text"
        assert "plain text content" in result.pages[0].text

    def test_gbk_fallback_decoding(self, tmp_path):
        """UTF-8 解码失败时回退 GBK。"""
        path = _write(tmp_path, "gbk.txt", "中文内容测试".encode("gbk"))
        result = parse_document(path, "doc-t3", ParseStrategyConfig())
        assert "中文内容测试" in result.pages[0].text

    def test_pdf_still_routes_by_parse_mode(self, tmp_path):
        """非文本扩展名不受文本路由影响，仍按 parse_mode 分发。"""
        pdf_path = tmp_path / "x.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "pdf text")
        doc.save(str(pdf_path))
        doc.close()

        result = parse_document(
            str(pdf_path), "doc-t4", ParseStrategyConfig(parse_mode="pymupdf")
        )
        assert result.mode_used == "pymupdf"
        assert "pdf text" in result.pages[0].text


class TestTokenSplitClamp:
    def test_overlap_ge_size_terminates(self):
        """overlap >= size 时窗口强制前进，不死循环且完整覆盖文本。"""
        text = "abcdef" * 200  # 1200 字符
        chunks = _token_split(text, chunk_size=10, chunk_overlap=100)
        assert len(chunks) > 1
        assert chunks[0] == text[:20]  # token_size = 10 * 2
        # 所有分块拼接应覆盖全文（有重叠）
        assert chunks[-1].endswith(text[-1])

    def test_normal_overlap(self):
        text = "x" * 100
        chunks = _token_split(text, chunk_size=10, chunk_overlap=5)
        assert len(chunks) > 1
        assert chunks[0] == "x" * 20
