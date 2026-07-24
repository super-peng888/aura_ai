"""Document parser: PyMuPDF text + optional image extraction, VLM, PaddleOCR.

Simple, direct implementation. No abstract base classes or factories.
Parsing is synchronous; async operations (OSS upload, DB writes) are handled
caller-side after parse() returns.
"""

import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import fitz

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class ParsedPage:
    page_number: int
    text: str
    images: List[dict] = field(default_factory=list)
    tables: List[str] = field(default_factory=list)
    # 标题条目: {"text": str, "level": int, "pos": int（在 page.text 中的字符位置）}
    headings: List[dict] = field(default_factory=list)


@dataclass
class ParseStrategyConfig:
    """解析策略配置，由调用方（根据用户策略）提供。

    vlm_config 由 async 编排层（document_parse_service）在解析前从系统级
    ParseConfigService 解析注入（keys: model/base_url/api_key/detail/max_tokens），
    保证本模块解析函数保持同步、不触碰事件循环；为 None 时回落 settings.VLM_*。
    """

    parse_mode: str = "pymupdf"          # pymupdf | paddleocr | vlm（历史别名: pymupdf_rich | ocr）
    chunk_size: int = 800
    chunk_overlap: int = 100
    split_method: str = "sentence"       # sentence | token | structured
    extract_images: bool = False
    dimension: int = 1536
    vlm_config: Optional[dict] = None


@dataclass
class ParseResult:
    """同步解析结果。图片仅包含原始二进制数据，尚未上传 OSS。"""

    doc_id: str
    pages: List[ParsedPage]
    raw_images: List[dict] = field(default_factory=list)
    mode_used: str = "pymupdf"


# ---------------------------------------------------------------------------
# 公共工具
# ---------------------------------------------------------------------------

IMG_PLACEHOLDER_PATTERN = r"\[IMG:([a-zA-Z0-9_]+)\]"


def _simple_split(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    """兜底分片：按段落粗分，超过 chunk_size 时截断。"""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks = []
    current = []
    current_len = 0
    for para in paragraphs:
        if current_len + len(para) > chunk_size and current:
            chunks.append("\n".join(current))
            overlap = current[-1] if len(current[-1]) < chunk_overlap else current[-1][-chunk_overlap:]
            current = [overlap, para]
            current_len = len(overlap) + len(para)
        else:
            current.append(para)
            current_len += len(para) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks or [text]


def _sentence_split(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    """使用 llama_index SentenceSplitter 做句子级分片。"""
    try:
        from llama_index.core.node_parser import SentenceSplitter

        splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        return splitter.split_text(text)
    except ImportError:
        return _simple_split(text, chunk_size, chunk_overlap)


def _token_split(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    """按 token 估算分片（1 token ≈ 0.75 中文字符 或 4 英文字符）。"""
    # 简化实现：按字符长度分，假设平均每个 token 2 个字符
    token_size = max(chunk_size * 2, 1)
    # overlap >= size 时窗口不再前进会死循环，强制 clamp
    overlap_size = min(chunk_overlap * 2, token_size - 1)
    if len(text) <= token_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + token_size
        chunks.append(text[start:end])
        start = end - overlap_size
        if start >= len(text):
            break
    return chunks or [text]


def _structured_split(text: str, _chunk_size: int, _chunk_overlap: int) -> List[str]:
    """结构化分片：按标题/章节分割（简单实现：按 # 或 数字标题）。"""
    # 匹配 Markdown 标题或中文/数字章节标题
    pattern = r"(?:\n|^)(#{1,6}\s+|第[一二三四五六七八九十\d]+章[\s、]|\d+\.\s+\S|【.+?】)(?=\n)"
    parts = re.split(pattern, text)
    if len(parts) <= 2:
        return _simple_split(text, _chunk_size, _chunk_overlap)
    chunks = []
    current = parts[0] if parts[0] else ""
    i = 1
    while i < len(parts):
        header = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        candidate = current + "\n" + header + body
        if len(candidate) > _chunk_size and current:
            chunks.append(current.strip())
            current = header + body
        else:
            current = candidate
        i += 2
    if current.strip():
        chunks.append(current.strip())
    return chunks or [text]


SPLIT_HANDLERS = {
    "sentence": _sentence_split,
    "token": _token_split,
    "structured": _structured_split,
}


def _split_by_page_headings(text: str, page_headings: List[dict], strategy: ParseStrategyConfig) -> List[tuple]:
    """按提取到的真实标题位置切分页面文本。

    Returns:
        list of (start_pos, chunk_text)；超过 chunk_size 的节用 _simple_split 再细分。
    """
    positions = sorted({h.get("pos", 0) for h in page_headings if 0 < h.get("pos", 0) < len(text)})
    boundaries = [0] + positions + [len(text)]
    pieces = []
    for start, end in zip(boundaries, boundaries[1:]):
        section = text[start:end].strip()
        if not section:
            continue
        if len(section) <= strategy.chunk_size:
            pieces.append((start, section))
        else:
            offset = start
            for sub in _simple_split(section, strategy.chunk_size, strategy.chunk_overlap):
                pieces.append((offset, sub))
                offset += len(sub)
    return pieces


def split_pages_to_chunks(pages: List[ParsedPage], strategy: ParseStrategyConfig, doc_id: str) -> List[dict]:
    """将解析后的页面分片。

    chunk dict 既有字段（chunk_id/doc_id/page/content/image_ids）保持不变，
    新增可选字段：
    - heading: 当前 chunk 所属的标题路径（如 "第一章 > 1.2 节"），无标题为空串
    - chunk_type: "text"（默认）或 "table"（Markdown 表格独立成块）
    """
    splitter = SPLIT_HANDLERS.get(strategy.split_method, _sentence_split)
    chunks = []
    chunk_index = 0
    heading_stack: List[dict] = []  # 跨页维护的标题层级栈 [{"level": int, "text": str}]

    def heading_path() -> str:
        return " > ".join(h["text"] for h in heading_stack)

    for page in pages:
        text = page.text or ""
        page_headings = sorted(page.headings or [], key=lambda h: h.get("pos", 0))
        # 页面级图片（VLM 整页分析等无占位符模式）：整页文本中没有任何 IMG
        # 占位符时，将 page.images 作为页级引用附加到该页每个 chunk，
        # 供检索侧按页引用整页截图；有占位符时按占位符精确定位，不重复附加。
        page_image_ids = [img["image_id"] for img in (page.images or []) if img.get("image_id")]
        page_has_placeholders = bool(re.search(IMG_PLACEHOLDER_PATTERN, text))

        if strategy.split_method == "structured" and page_headings:
            # structured 模式优先使用真实标题切分
            pieces = _split_by_page_headings(text, page_headings, strategy)
        else:
            pieces = []
            cursor = 0
            for chunk_text in splitter(text, strategy.chunk_size, strategy.chunk_overlap):
                # 尽力定位 chunk 在页面文本中的起始位置，用于挂标题
                pos = text.find(chunk_text[:30], cursor) if chunk_text else -1
                if pos == -1:
                    pos = cursor
                pieces.append((pos, chunk_text))
                cursor = pos + max(len(chunk_text), 1)

        applied_idx = 0
        for pos, chunk_text in pieces:
            # 应用位于该 chunk 之前的标题，维护层级栈
            while applied_idx < len(page_headings) and page_headings[applied_idx].get("pos", 0) <= pos:
                h = page_headings[applied_idx]
                while heading_stack and heading_stack[-1]["level"] >= h["level"]:
                    heading_stack.pop()
                heading_stack.append(h)
                applied_idx += 1
            img_ids = re.findall(IMG_PLACEHOLDER_PATTERN, chunk_text)
            if page_image_ids and not page_has_placeholders:
                img_ids = list(dict.fromkeys([*img_ids, *page_image_ids]))
            chunks.append({
                "chunk_id": f"{doc_id}_chunk_{chunk_index:04d}",
                "doc_id": doc_id,
                "page": page.page_number,
                "content": chunk_text,
                "image_ids": img_ids,
                "heading": heading_path(),
                "chunk_type": "text",
            })
            chunk_index += 1

        # 应用页面剩余标题，作为表格 chunk 的上下文
        while applied_idx < len(page_headings):
            h = page_headings[applied_idx]
            while heading_stack and heading_stack[-1]["level"] >= h["level"]:
                heading_stack.pop()
            heading_stack.append(h)
            applied_idx += 1

        for table_md in page.tables or []:
            path = heading_path()
            content = f"{path}\n{table_md}" if path else table_md
            chunks.append({
                "chunk_id": f"{doc_id}_chunk_{chunk_index:04d}",
                "doc_id": doc_id,
                "page": page.page_number,
                "content": content,
                "image_ids": [],
                "heading": path,
                "chunk_type": "table",
            })
            chunk_index += 1
    return chunks


# ---------------------------------------------------------------------------
# 图片提取（纯同步，仅返回二进制数据，不调用异步 OSS 上传）
# ---------------------------------------------------------------------------

def _extract_images_raw(doc: fitz.Document, doc_id: str) -> List[dict]:
    """从 PDF 中提取图片原始数据。返回包含二进制数据和元数据的列表。

    每张图片附带 y_pos（在页面中的纵向坐标，供占位符按阅读顺序插入；
    定位失败为 None，由组装层决定兜底位置）。
    """
    raw_images = []
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_number = page_idx + 1
        image_list = page.get_images(full=True)
        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            base_image = doc.extract_image(xref)
            if not base_image:
                continue
            width = base_image.get("width", 0)
            height = base_image.get("height", 0)
            if width < 100 or height < 100:
                continue

            try:
                rects = page.get_image_rects(xref)
                y_pos = min((r.y0 for r in rects), default=None)
            except Exception:
                y_pos = None

            image_id = f"{doc_id}_p{page_number}_{img_idx + 1:02d}"
            ext = base_image.get("ext", "png")
            content_type = f"image/{ext}" if ext else "image/png"

            raw_images.append({
                "image_id": image_id,
                "data": base_image["image"],
                "content_type": content_type,
                "width": width,
                "height": height,
                "page_number": page_number,
                "seq": img_idx + 1,
                "y_pos": y_pos,
                "filename": f"{image_id}.png",
            })
    return raw_images


def _assemble_page_text(page: fitz.Page, text_blocks: list, images: List[dict], page_number: int) -> str:
    """组装页面文本：按 y 坐标排序，在图片真实位置插入占位符。

    图片取提取时记录的 y_pos；定位失败时追加到页尾（保持阅读顺序），
    不再像旧版那样全部堆到页首。
    """
    contents = []
    for block in text_blocks:
        if block[6] == 0:  # text block
            y_pos = block[1]
            text = block[4].strip()
            if text:
                contents.append({"type": "text", "y_pos": y_pos, "content": text})

    page_bottom = page.rect.height + 1 if page is not None else float("inf")
    for img in images:
        y_pos = img.get("y_pos")
        contents.append({
            "type": "image",
            "y_pos": y_pos if y_pos is not None else page_bottom,
            "content": f"\n[IMG:{img['image_id']}]\n",
        })

    contents.sort(key=lambda x: x["y_pos"])
    return "\n\n".join(c["content"] for c in contents)


def _extract_tables(page: fitz.Page) -> List[str]:
    """提取页面中的表格（Markdown 格式）。"""
    tables = []
    try:
        tab = page.find_tables()
        for t in tab.tables:
            tables.append(t.to_pandas().to_markdown())
    except Exception:
        pass
    return tables


_BOLD_FLAG = 16  # PyMuPDF span flags: 2**4 = bold
_HEADING_MAX_LEN = 60
_HEADING_MIN_RATIO = 1.15   # 字号 >= 正文 * 1.15 视为标题
_HEADING_LEVEL2_RATIO = 1.25
_HEADING_LEVEL1_RATIO = 1.40
# 以句读结尾的短行视为正文而非标题
_HEADING_EXCLUDE_ENDINGS = "。；，,.;!！?？"


def _extract_headings(page: fitz.Page) -> List[dict]:
    """从页面提取标题（启发式，纯 PyMuPDF span 样式）。

    规则：
    - 按字符数加权统计字号，出现最多的字号视为正文字号；
    - 短行（<=60 字符、不以句读结尾）满足以下任一条件视为标题：
      - 行内最大字号 >= 正文字号 * 1.15；
      - 行内全部 span 加粗且字号 >= 正文字号；
    - 层级按字号比例划分：>=1.40 -> 1，>=1.25 -> 2，否则 -> 3。

    无法判断（扫描件/无样式）时返回空列表，行为与旧版一致。
    """
    try:
        data = page.get_text("dict")
    except Exception:
        return []

    size_weights: dict = {}
    lines = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(s.get("text", "") for s in spans).strip()
            if not text:
                continue
            max_size = max((s.get("size", 0) for s in spans), default=0)
            all_bold = bool(spans) and all(
                (s.get("flags", 0) & _BOLD_FLAG) or "bold" in s.get("font", "").lower()
                for s in spans
            )
            lines.append({"text": text, "size": max_size, "bold": all_bold})
            for s in spans:
                sz = round(s.get("size", 0), 1)
                size_weights[sz] = size_weights.get(sz, 0) + len(s.get("text", ""))

    if not lines or not size_weights:
        return []

    body_size = max(size_weights, key=size_weights.get)
    if not body_size:
        return []

    headings = []
    for line in lines:
        text = line["text"]
        if len(text) > _HEADING_MAX_LEN or text.endswith(tuple(_HEADING_EXCLUDE_ENDINGS)):
            continue
        ratio = line["size"] / body_size
        if ratio >= _HEADING_MIN_RATIO or (line["bold"] and line["size"] >= body_size):
            if ratio >= _HEADING_LEVEL1_RATIO:
                level = 1
            elif ratio >= _HEADING_LEVEL2_RATIO:
                level = 2
            else:
                level = 3
            headings.append({"text": text, "level": level})
    return headings


def _locate_headings(headings: List[dict], page_text: str) -> List[dict]:
    """为标题条目标注其在 page.text 中的字符位置（pos 字段，尽力而为）。"""
    located = []
    search_from = 0
    for h in headings:
        pos = page_text.find(h["text"], search_from)
        if pos == -1:
            pos = page_text.find(h["text"])
        if pos == -1:
            continue
        located.append({**h, "pos": pos})
        search_from = pos + len(h["text"])
    return located


# ---------------------------------------------------------------------------
# 主解析器
# ---------------------------------------------------------------------------

# 纯文本资源扩展名：按扩展名自动路由到纯文本解析，无需选择解析模式
_TEXT_FILE_EXTS = {".txt", ".md", ".markdown", ".json", ".csv", ".log"}

_IMAGE_FILE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")


def _read_text_with_fallback(file_path: str) -> str:
    """读取纯文本文件：优先 UTF-8，失败回退 GBK，最后容错替换。"""
    with open(file_path, "rb") as f:
        data = f.read()
    for encoding in ("utf-8", "gbk"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _parse_text_file(file_path: str, doc_id: str, strategy: ParseStrategyConfig) -> ParseResult:
    """纯文本解析（txt/md/json/csv 等）：整篇读入为单页，交由分块器切分。"""
    text = _read_text_with_fallback(file_path)
    return ParseResult(
        doc_id=doc_id,
        pages=[ParsedPage(page_number=1, text=text)],
        raw_images=[],
        mode_used="text",
    )


def parse_document(file_path: str, doc_id: str, strategy: ParseStrategyConfig) -> ParseResult:
    """同步解析文档。不调用任何异步 I/O。

    路由规则：
    - 纯文本扩展名（txt/md/json/csv/log）：自动走纯文本解析，无视 parse_mode；
    - 图片扩展名：paddleocr/ocr 模式直接 OCR，其余模式走 VLM 描述；
    - 其余（PDF 等）：按 parse_mode 选择 pymupdf / paddleocr / vlm，
      历史别名 pymupdf_rich 归一为 pymupdf+extract_images，ocr 归一为 paddleocr。

    Returns:
        ParseResult: 包含解析后的页面、原始图片数据（未上传）、解析模式。
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext in _TEXT_FILE_EXTS:
        return _parse_text_file(file_path, doc_id, strategy)

    if ext in _IMAGE_FILE_EXTS:
        return _parse_image(file_path, doc_id, strategy)

    # 历史别名归一（直接改写 strategy，保证 mode_used 与落库 parse_mode 为规范值）
    if strategy.parse_mode == "pymupdf_rich":
        strategy.parse_mode = "pymupdf"
        strategy.extract_images = True

    if strategy.parse_mode == "vlm":
        return _parse_with_vlm(file_path, doc_id, strategy)

    if strategy.parse_mode in ("paddleocr", "ocr"):
        return _parse_with_paddleocr(file_path, doc_id, strategy)

    return _parse_with_pymupdf(file_path, doc_id, strategy)


def _parse_with_pymupdf(file_path: str, doc_id: str, strategy: ParseStrategyConfig) -> ParseResult:
    """PyMuPDF 解析：文本 + 可选图片提取。"""
    doc = fitz.open(file_path)
    pages = []
    raw_images = []
    try:
        # 一次性提取全文档图片（旧版在页循环内反复全量提取，复杂度 O(页数×图片数)）
        all_images = _extract_images_raw(doc, doc_id) if strategy.extract_images else []
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_number = page_idx + 1

            text_blocks = page.get_text("blocks", sort=True)
            # 只保留当前页的图片
            images = [img for img in all_images if img["page_number"] == page_number]
            raw_images.extend(images)

            page_text = _assemble_page_text(page, text_blocks, images, page_number)
            tables = _extract_tables(page)
            headings = _locate_headings(_extract_headings(page), page_text)

            pages.append(ParsedPage(
                page_number=page_number,
                text=page_text,
                images=[{"image_id": img["image_id"]} for img in images],
                tables=tables,
                headings=headings,
            ))
    finally:
        doc.close()

    return ParseResult(
        doc_id=doc_id,
        pages=pages,
        raw_images=raw_images,
        mode_used=strategy.parse_mode,
    )


def _resolve_vlm_config(strategy: ParseStrategyConfig) -> dict:
    """解析生效 VLM 配置：优先 strategy.vlm_config（编排层注入的系统级配置），
    缺失时回落 settings.VLM_*（env）。"""
    cfg = strategy.vlm_config or {}
    return {
        "model": cfg.get("model") or settings.VLM_MODEL,
        "base_url": cfg.get("base_url") or settings.VLM_API_BASE,
        "api_key": cfg.get("api_key") or settings.VLM_API_KEY,
        "detail": cfg.get("detail") or getattr(settings, "VLM_DETAIL_LEVEL", "high"),
        "max_tokens": int(cfg.get("max_tokens") or 4096),
    }


def _create_vlm_client(strategy: ParseStrategyConfig):
    """创建 VLM OpenAI 兼容客户端；未配置 API Key 时抛出带配置指引的错误。"""
    from openai import OpenAI

    vlm = _resolve_vlm_config(strategy)
    if not vlm["api_key"]:
        raise ValueError(
            "VLM 视觉解析未配置 API Key，请管理员在「配置中心 - 检索配置」页"
            "配置 VLM 视觉解析模型（默认 qwen3-vl-flash）"
        )
    client = OpenAI(api_key=vlm["api_key"], base_url=vlm["base_url"])
    return client, vlm


def _parse_with_vlm(file_path: str, doc_id: str, strategy: ParseStrategyConfig) -> ParseResult:
    """VLM 整页分析：每页截图后调用 VLM API。"""
    client, vlm = _create_vlm_client(strategy)
    doc = fitz.open(file_path)
    pages = []
    raw_images = []
    try:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_number = page_idx + 1

            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat)
            page_image_data = pix.tobytes("png")

            # 将页面图片作为 raw_image 返回（后续由调用方上传）
            image_id = f"{doc_id}_p{page_number}_page"
            raw_images.append({
                "image_id": image_id,
                "data": page_image_data,
                "content_type": "image/png",
                "width": pix.width,
                "height": pix.height,
                "page_number": page_number,
                "seq": 1,
                "filename": f"{image_id}.png",
            })

            import base64
            page_b64 = base64.b64encode(page_image_data).decode()
            prompt = f"请详细分析这个文档页面（第{page_number}页）的内容。完整提取文字、描述图表、识别表格并输出Markdown。"
            response = client.chat.completions.create(
                model=vlm["model"],
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{page_b64}", "detail": vlm["detail"]}},
                    ],
                }],
                max_tokens=vlm["max_tokens"],
            )
            analysis = response.choices[0].message.content or ""
            pages.append(ParsedPage(page_number=page_number, text=analysis, images=[{"image_id": image_id}], tables=[]))
    finally:
        doc.close()

    return ParseResult(
        doc_id=doc_id,
        pages=pages,
        raw_images=raw_images,
        mode_used="vlm",
    )


# ---------------------------------------------------------------------------
# PaddleOCR 解析（扫描件 / 位图文档）
# ---------------------------------------------------------------------------

_PADDLEOCR_ZOOM = 2.0  # PDF 页渲染位图的缩放倍数（~144 DPI）

# PaddleOCR 实例懒加载单例：模型大且初始化会触发模型下载，首次使用时才创建。
_paddle_ocr_instance = None


def _get_paddle_ocr():
    """返回懒加载的 PaddleOCR 单例。

    paddle/paddleocr 必须延迟导入：模块级导入会拖慢启动，且 Windows 上
    paddle 与 torch 存在 DLL 加载顺序冲突（先 paddle 后 torch 会导致 torch
    的 shm.dll 加载失败），因此这里固定先 import torch 再 import paddleocr。

    仅启用文本检测 + 识别（关闭文档方向分类/矫正/文本行方向分类），
    首次初始化时模型自动下载到 paddlex 默认缓存目录。
    """
    global _paddle_ocr_instance
    if _paddle_ocr_instance is None:
        import torch  # noqa: F401  # 必须先于 paddle 加载，规避 Windows DLL 冲突
        from paddleocr import PaddleOCR

        _paddle_ocr_instance = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            lang="ch",
        )
    return _paddle_ocr_instance


def _pixmap_to_bgr_array(pix: "fitz.Pixmap"):
    """PyMuPDF Pixmap -> BGR np.ndarray（PaddleOCR ndarray 输入约定为 BGR 序）。"""
    import numpy as np

    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 1:  # 灰度 -> 三通道
        arr = np.repeat(arr, 3, axis=2)
    elif pix.n >= 4:  # 去 alpha
        arr = arr[..., :3]
    return arr[..., ::-1]  # RGB -> BGR


def _ocr_result_to_text(ocr_result) -> str:
    """将单页 OCR 结果按阅读顺序（从上到下、从左到右）拼接为纯文本。

    ocr_result 为 dict 结构（paddlex OCRResult 或等价的 mock）：
    rec_texts: List[str]，rec_boxes: [x1, y1, x2, y2] 列表（可选，缺失时保持原顺序）。
    """
    rec_texts = list(ocr_result.get("rec_texts") or [])
    if not rec_texts:
        return ""
    rec_boxes = ocr_result.get("rec_boxes")
    lines = []
    for idx, text in enumerate(rec_texts):
        x = y = 0.0
        try:
            if rec_boxes is not None and idx < len(rec_boxes):
                box = rec_boxes[idx]
                x, y = float(box[0]), float(box[1])
        except Exception:
            x = y = 0.0
        lines.append((y, x, idx, str(text).strip()))
    lines.sort(key=lambda item: (item[0], item[1], item[2]))
    return "\n".join(item[3] for item in lines if item[3])


def _ocr_one_image(image) -> str:
    """对单张图像（BGR ndarray 或图片文件路径）执行 OCR，返回拼接文本。"""
    ocr = _get_paddle_ocr()
    results = ocr.predict([image]) or []
    if not results:
        return ""
    return _ocr_result_to_text(results[0])


def _parse_with_paddleocr(file_path: str, doc_id: str, strategy: ParseStrategyConfig) -> ParseResult:
    """PaddleOCR 解析 PDF：每页渲染为位图（zoom 2x）后 OCR，按阅读顺序拼接文本。

    单页 OCR 失败时记日志并保留空 text，不中断整篇。
    输出结构与 pymupdf 路径一致；基础 OCR 不含版面/表格分析，tables/headings 为空。
    """
    doc = fitz.open(file_path)
    pages = []
    raw_images = []
    try:
        all_images = _extract_images_raw(doc, doc_id) if strategy.extract_images else []
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_number = page_idx + 1

            page_text = ""
            try:
                mat = fitz.Matrix(_PADDLEOCR_ZOOM, _PADDLEOCR_ZOOM)
                pix = page.get_pixmap(matrix=mat)
                page_text = _ocr_one_image(_pixmap_to_bgr_array(pix))
            except Exception:
                logger.exception("PaddleOCR 解析失败: doc=%s page=%d", doc_id, page_number)

            images = [img for img in all_images if img["page_number"] == page_number]
            if images:
                placeholders = "\n".join(f"[IMG:{img['image_id']}]" for img in images)
                page_text = f"{page_text}\n\n{placeholders}" if page_text else placeholders
                raw_images.extend(images)

            pages.append(ParsedPage(
                page_number=page_number,
                text=page_text,
                images=[{"image_id": img["image_id"]} for img in images],
                tables=[],
                headings=[],
            ))
    finally:
        doc.close()

    return ParseResult(
        doc_id=doc_id,
        pages=pages,
        raw_images=raw_images,
        mode_used=strategy.parse_mode,
    )


def _parse_image_with_paddleocr(file_path: str, doc_id: str, strategy: ParseStrategyConfig) -> ParseResult:
    """单张图片直接 OCR（paddleocr/ocr 模式）。OCR 失败时记日志并返回空 text。"""
    try:
        text = _ocr_one_image(file_path)
    except Exception:
        logger.exception("PaddleOCR 解析图片失败: doc=%s file=%s", doc_id, file_path)
        text = ""

    with open(file_path, "rb") as f:
        image_data = f.read()
    ext = Path(file_path).suffix.lstrip(".") or "png"
    image_id = f"{doc_id}_img_01"
    raw_images = [{
        "image_id": image_id,
        "data": image_data,
        "content_type": f"image/{ext}",
        "width": 0,
        "height": 0,
        "page_number": 1,
        "seq": 1,
        "filename": f"{image_id}.{ext}",
    }]

    return ParseResult(
        doc_id=doc_id,
        pages=[ParsedPage(page_number=1, text=text, images=[{"image_id": image_id}])],
        raw_images=raw_images,
        mode_used=strategy.parse_mode,
    )


def _parse_image(file_path: str, doc_id: str, strategy: ParseStrategyConfig) -> ParseResult:
    """单张图片解析：paddleocr/ocr 模式直接 OCR，其余模式 fallback 到 VLM 描述。"""
    if strategy.parse_mode in ("paddleocr", "ocr"):
        return _parse_image_with_paddleocr(file_path, doc_id, strategy)
    # 当前实现：将图片作为一页，用 VLM 分析
    client, vlm = _create_vlm_client(strategy)
    with open(file_path, "rb") as f:
        image_data = f.read()

    import base64
    image_b64 = base64.b64encode(image_data).decode()
    ext = Path(file_path).suffix.lstrip(".") or "png"
    response = client.chat.completions.create(
        model=vlm["model"],
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "请详细描述这张图片的内容，提取所有可见文字。"},
                {"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{image_b64}", "detail": vlm["detail"]}},
            ],
        }],
        max_tokens=vlm["max_tokens"],
    )
    text = response.choices[0].message.content or ""

    image_id = f"{doc_id}_img_01"
    raw_images = [{
        "image_id": image_id,
        "data": image_data,
        "content_type": f"image/{ext}",
        "width": 0,
        "height": 0,
        "page_number": 1,
        "seq": 1,
        "filename": f"{image_id}.{ext}",
    }]

    return ParseResult(
        doc_id=doc_id,
        pages=[ParsedPage(page_number=1, text=text, images=[{"image_id": image_id}])],
        raw_images=raw_images,
        mode_used="vlm",
    )
