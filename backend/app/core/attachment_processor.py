"""附件处理器 — 下载 OSS 文件并提取内容供 LLM 使用。"""

import base64
import httpx
from typing import List, Optional

MAX_TEXT_LENGTH = 20000  # 文本附件最大字符数，超出截断


async def _fetch_url(url: str) -> bytes:
    """异步下载 URL 内容。"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


def _is_image(mime_type: Optional[str]) -> bool:
    if not mime_type:
        return False
    return mime_type.startswith("image/")


def _is_text(mime_type: Optional[str], filename: str) -> bool:
    if not mime_type:
        ext = filename.lower().split(".")[-1] if "." in filename else ""
        return ext in ("txt", "csv", "json", "md", "py", "js", "ts", "html", "css", "xml", "yaml", "yml")
    return mime_type.startswith("text/") or mime_type in (
        "application/json",
        "application/xml",
        "application/x-yaml",
        "application/csv",
    )


async def process_attachments(attachments: List[dict]) -> str:
    """
    下载附件并提取内容，返回可附加到 LLM prompt 的文本。

    支持：
    - 图片 → base64 data URL（Markdown 格式）
    - 文本文件 → 读取内容（截断到 MAX_TEXT_LENGTH）
    - 其他 → 提示有附件但无法解析
    """
    if not attachments:
        return ""

    parts = ["\n\n【用户上传的附件】"]
    for att in attachments:
        filename = att.get("filename", "未知文件")
        url = att.get("url", "")
        mime_type = att.get("mime_type", "")

        if not url:
            parts.append(f"- {filename}: URL 缺失，无法读取")
            continue

        try:
            data = await _fetch_url(url)
        except Exception as e:
            parts.append(f"- {filename}: 下载失败 ({e})")
            continue

        if _is_image(mime_type):
            b64 = base64.b64encode(data).decode("utf-8")
            mime = mime_type or "image/png"
            parts.append(f"\n![{filename}](data:{mime};base64,{b64})\n")
        elif _is_text(mime_type, filename):
            try:
                text = data.decode("utf-8", errors="replace")
            except Exception:
                text = data.decode("utf-8", errors="ignore")
            if len(text) > MAX_TEXT_LENGTH:
                text = text[:MAX_TEXT_LENGTH] + f"\n...（内容已截断，共 {len(text)} 字符）"
            parts.append(f"\n--- 文件: {filename} ---\n{text}\n---")
        else:
            parts.append(f"- {filename}: 非文本/图片文件，暂不支持自动解析内容")

    return "\n".join(parts)
