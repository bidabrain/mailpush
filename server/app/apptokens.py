"""WebUI 管理的多个 app token(安卓端鉴权用)。存 /data(可写、与 mail-api 共享)。

- mail-admin(管理后台)增删;
- mail-api 的 require_auth 校验(常量时间比对)。
旧的单文件 /config/api-token 仍兼容,不在这里管(见 api.py)。
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
from datetime import datetime, timezone

TOKENS_FILE = os.environ.get("APP_TOKENS_FILE", "/data/app-tokens.json")
_lock = threading.Lock()


def _read() -> list[dict]:
    try:
        with open(TOKENS_FILE, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return [t for t in data if isinstance(t, dict) and t.get("token")]
    except (OSError, json.JSONDecodeError):
        pass
    return []


def _write(items: list[dict]) -> None:
    os.makedirs(os.path.dirname(TOKENS_FILE), exist_ok=True)
    tmp = TOKENS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)
    os.replace(tmp, TOKENS_FILE)  # 原子替换,避免另一容器读到半截


def load() -> list[dict]:
    """token 记录列表:{id, label, token, created}。"""
    return _read()


def add(label: str) -> dict:
    """新建一个随机 token,返回记录(含完整 token)。"""
    rec = {
        "id": secrets.token_hex(4),
        "label": (label or "").strip() or "未命名",
        "token": secrets.token_hex(32),
        "created": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    with _lock:
        items = _read()
        items.append(rec)
        _write(items)
    return rec


def delete(token_id: str) -> bool:
    with _lock:
        items = _read()
        new = [t for t in items if t.get("id") != token_id]
        if len(new) == len(items):
            return False
        _write(new)
        return True


def match(token: str) -> str | None:
    """常量时间比对;命中则返回该 token 的 id,否则 None。"""
    token = (token or "").strip()
    if not token:
        return None
    found: str | None = None
    for t in _read():
        if hmac.compare_digest(token, str(t.get("token", ""))):
            found = str(t.get("id") or "")  # 不提前 return,尽量减少时序差异
    return found


def verify(token: str) -> bool:
    return match(token) is not None
