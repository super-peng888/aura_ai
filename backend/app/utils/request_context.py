"""请求级用户上下文（contextvars）。

user_id 不再沿调用链一层层透传，而是在 FastAPI 认证依赖
（app.api.auth.get_current_user，JWT 校验通过处）写入本模块的 ContextVar，
下游需要用户身份做配置解析（如 UserModelConfigService.resolve）时直接读取。

正确性说明：
- FastAPI 每个请求在独立的 asyncio task / context 中运行，整条 await 链
  （LangGraph astream、service 调用）都能读到写入时的 context；
  asyncio.to_thread 会拷贝 context。因此请求内任意深度读取都能拿到值，无需 reset。
- index_worker / CLI / evals 脚本等无请求上下文，get_current_user_id() 返回 None，
  LLM 配置解析回落系统默认（deepseek）——与改造前语义一致。
"""

from contextvars import ContextVar
from typing import Optional

current_user_id: ContextVar[Optional[str]] = ContextVar("current_user_id", default=None)


def set_current_user_id(user_id: Optional[str]) -> None:
    """写入当前请求的用户 ID（认证依赖在 JWT 校验通过后调用）。"""
    current_user_id.set(user_id)


def get_current_user_id() -> Optional[str]:
    """读取当前上下文的用户 ID；无请求上下文（worker/脚本）时返回 None。"""
    return current_user_id.get()
