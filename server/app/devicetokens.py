"""多设备 FCM 推送 token 存储。存 /data(mail-api 与 mail-watch 都 rw 挂载)。

记录格式(每条):{token, app_token_id, created}
  - token:        FCM 设备 token
  - app_token_id: 注册它的 app-token 的 id(来自 apptokens;后台据此「删 app-token 连带删推送设备」)
  - created:      注册时间

- mail-api 的 /register-token 写入(安卓端自动上报,带当前 app-token 的归属)。
- push-fcm.py 读取并群发;发现失效 token(卸载/重置)时移除。
- mail-admin 后台:按归属显示、删 app-token 时移除其设备、可单删/清空。

兼容:旧格式是 list[str](无归属),读取时当作 app_token_id=None;旧单文件 /config/device-token 仍只读合并。
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

TOKENS_FILE = os.environ.get("DEVICE_TOKENS_FILE", "/data/device-tokens.json")
LEGACY_FILE = os.environ.get("DEVICE_TOKEN_FILE", "/config/device-token")

_lock = threading.Lock()


def _read_records() -> list[dict]:
    """读 /data 里的设备记录;容忍旧的 list[str] 格式。"""
    out: list[dict] = []
    try:
        with open(TOKENS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return out
    if isinstance(data, list):
        for it in data:
            if isinstance(it, str) and it.strip():
                out.append({"token": it.strip(), "app_token_id": None})
            elif isinstance(it, dict) and str(it.get("token", "")).strip():
                out.append(it)
    return out


def _write_records(records: list[dict]) -> None:
    os.makedirs(os.path.dirname(TOKENS_FILE), exist_ok=True)
    tmp = TOKENS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)
    os.replace(tmp, TOKENS_FILE)  # 原子替换,避免另一容器读到半截


# ---------- push-fcm 用(保持原签名)----------

def load() -> list[str]:
    """全部 FCM token(去重,含旧单文件)。push-fcm 群发用。"""
    tokens = {r["token"] for r in _read_records() if r.get("token")}
    try:
        with open(LEGACY_FILE, encoding="utf-8") as f:
            t = f.read().strip()
            if t:
                tokens.add(t)
    except OSError:
        pass
    return sorted(tokens)


def remove(tokens_to_remove) -> None:
    """按 FCM token 移除(push-fcm 清理失效 token 用)。旧单文件在只读 /config 不动。"""
    rm = {str(t).strip() for t in tokens_to_remove}
    with _lock:
        recs = [r for r in _read_records() if r.get("token") not in rm]
        _write_records(recs)


# ---------- 注册 / 后台管理 ----------

def add(token: str, app_token_id: str | None = None) -> bool:
    """新增/更新一条设备记录。已存在则更新归属;返回是否新加入。"""
    token = (token or "").strip()
    if not token:
        return False
    with _lock:
        recs = _read_records()
        for r in recs:
            if r.get("token") == token:
                if app_token_id and r.get("app_token_id") != app_token_id:
                    r["app_token_id"] = app_token_id
                    _write_records(recs)
                return False
        recs.append({
            "token": token,
            "app_token_id": app_token_id,
            "created": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        })
        _write_records(recs)
        return True


def load_records() -> list[dict]:
    """后台显示用:全部设备记录(只来自 /data,不含只读旧单文件)。"""
    return _read_records()


def remove_by_app_token(app_token_id: str) -> int:
    """删除某 app-token 名下的全部设备记录,返回删除条数(后台删 token 时连带调用)。"""
    with _lock:
        recs = _read_records()
        new = [r for r in recs if r.get("app_token_id") != app_token_id]
        _write_records(new)
        return len(recs) - len(new)


def clear() -> None:
    """清空全部设备记录(/data)。有效设备下次打开 app 会自动重新上报。"""
    with _lock:
        _write_records([])
