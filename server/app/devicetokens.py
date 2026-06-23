"""多设备 FCM token 存储。

存在 /data(mail-api 与 mail-watch 都以 rw 挂载;/config 是只读挂载,写不了)。
- mail-api 的 /register-token 写入(安卓端自动上报)。
- push-fcm.py 读取并群发;发现失效 token(卸载/重置)时移除。
兼容旧的单文件 /config/device-token(只读,只读取不删除)。
"""
from __future__ import annotations

import json
import os
import threading

TOKENS_FILE = os.environ.get("DEVICE_TOKENS_FILE", "/data/device-tokens.json")
LEGACY_FILE = os.environ.get("DEVICE_TOKEN_FILE", "/config/device-token")

_lock = threading.Lock()


def load() -> list[str]:
    """返回去重后的全部 token(含旧单文件)。"""
    tokens: set[str] = set()
    try:
        with open(TOKENS_FILE, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                tokens.update(str(t).strip() for t in data if str(t).strip())
    except (OSError, json.JSONDecodeError):
        pass
    try:
        with open(LEGACY_FILE, encoding="utf-8") as f:
            t = f.read().strip()
            if t:
                tokens.add(t)
    except OSError:
        pass
    return sorted(tokens)


def _save(tokens: set[str]) -> None:
    os.makedirs(os.path.dirname(TOKENS_FILE), exist_ok=True)
    tmp = TOKENS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(tokens), f)
    os.replace(tmp, TOKENS_FILE)  # 原子替换,避免另一容器读到半截


def add(token: str) -> bool:
    """新增 token,返回是否是新加入的。"""
    token = token.strip()
    if not token:
        return False
    with _lock:
        current = set(load())
        if token in current:
            return False
        current.add(token)
        _save(current)
        return True


def remove(tokens_to_remove) -> None:
    """移除失效 token(只能移除 /data 里的;旧单文件在只读 /config 不动)。"""
    with _lock:
        # 只对 TOKENS_FILE 里的集合做差集(不含 legacy,避免试图写只读文件)
        current: set[str] = set()
        try:
            with open(TOKENS_FILE, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    current.update(str(t).strip() for t in data if str(t).strip())
        except (OSError, json.JSONDecodeError):
            pass
        current.difference_update(tokens_to_remove)
        _save(current)
