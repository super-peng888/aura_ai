"""连接配置加密工具。"""

from __future__ import annotations

from typing import Optional

from app.config import get_settings

settings = get_settings()


def _encrypt_connection_config(config: Optional[dict]) -> dict:
    """对连接配置中的 password 字段进行 Fernet 加密。"""
    if not config:
        return {}
    cfg = dict(config)
    password = cfg.get("password")
    if password and isinstance(password, str):
        fernet = settings.get_fernet()
        if fernet:
            cfg["password"] = fernet.encrypt(password.encode()).decode()
    return cfg


def _decrypt_connection_config(config: Optional[dict]) -> dict:
    """解密连接配置中的 password 字段；失败则按明文透传。"""
    if not config:
        return {}
    cfg = dict(config)
    password = cfg.get("password")
    if password and isinstance(password, str):
        fernet = settings.get_fernet()
        if fernet:
            try:
                cfg["password"] = fernet.decrypt(password.encode()).decode()
            except Exception:
                # 解密失败可能是明文旧数据，直接透传
                pass
    return cfg


def _mask_connection_config(config: Optional[dict]) -> dict:
    """返回给前端时掩码 password 字段。"""
    if not config:
        return {}
    cfg = dict(config)
    if cfg.get("password"):
        cfg["password"] = "********"
    return cfg
