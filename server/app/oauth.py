"""OAuth2(XOAUTH2)token 助手 —— 目前用于 Outlook(微软,MSAL)。

- 客户端配置(client_id / authority / scopes)放【只读】的 /config/oauth/<account>.json;
- token 缓存(含 refresh token,会轮换)放【可写、两容器共享】的 /data/oauth/<account>.cache.bin;
- 刷新/写缓存时用 flock,避免 mail-api 与 mail-watch 并发写坏。

用法:
  oauth_enroll.py <account>   一次性设备码授权(终端给 URL+码 → 浏览器同意)
  oauth_token.py  <account>   输出裸 access token(供 config 的 auth.cmd / imapnotify 的 passwordCmd)

config/oauth/<account>.json 示例:
  { "client_id": "你的-azure-app-client-id" }
  (authority / scopes 不填则用下面的微软默认值;接谷歌等再按需覆盖)
"""
from __future__ import annotations

import fcntl
import json
import os
import threading

import msal

# 配置(client_id 等)与 token 缓存都放可写的 /data/oauth:管理后台(mail-admin,只读挂 /config)
# 才能写 client_id。client_id 不是机密,放 /data 安全模型 OK。
CONFIG_DIR = os.environ.get("OAUTH_CONFIG_DIR", "/data/oauth")
CACHE_DIR = os.environ.get("OAUTH_CACHE_DIR", "/data/oauth")

DEFAULT_AUTHORITY = "https://login.microsoftonline.com/common"
# 只列资源 scope;openid/profile/offline_access 由 MSAL 自动追加(显式写会报错)。
DEFAULT_SCOPES = [
    "https://outlook.office.com/IMAP.AccessAsUser.All",
    "https://outlook.office.com/SMTP.Send",
]


class OAuthError(RuntimeError):
    pass


def _conf(account: str) -> dict:
    path = os.path.join(CONFIG_DIR, f"{account}.json")
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
    except OSError as exc:
        raise OAuthError(f"读不到 OAuth 配置 {path}: {exc}")
    except json.JSONDecodeError as exc:
        raise OAuthError(f"OAuth 配置 {path} 不是合法 JSON: {exc}")
    if not c.get("client_id"):
        raise OAuthError(f"{path} 缺少 client_id")
    return {
        "client_id": c["client_id"],
        "authority": c.get("authority", DEFAULT_AUTHORITY),
        "scopes": c.get("scopes", DEFAULT_SCOPES),
    }


def config_path(account: str) -> str:
    return os.path.join(CONFIG_DIR, f"{account}.json")


def _cache_path(account: str) -> str:
    return os.path.join(CACHE_DIR, f"{account}.cache.bin")


def _lock(account: str):
    os.makedirs(CACHE_DIR, exist_ok=True)
    fd = open(os.path.join(CACHE_DIR, f"{account}.lock"), "w")
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _load_cache(account: str) -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    p = _cache_path(account)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            cache.deserialize(f.read())
    return cache


def _save_cache(account: str, cache: msal.SerializableTokenCache) -> None:
    if not cache.has_state_changed:
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = _cache_path(account) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(cache.serialize())
    os.replace(tmp, _cache_path(account))


def get_token(account: str) -> str:
    """静默拿(必要时用 refresh token 刷新)access token。未授权则报错提示先 enroll。"""
    conf = _conf(account)
    lock = _lock(account)
    try:
        cache = _load_cache(account)
        app = msal.PublicClientApplication(
            conf["client_id"], authority=conf["authority"], token_cache=cache
        )
        accounts = app.get_accounts()
        if not accounts:
            raise OAuthError(f"账号 {account} 未授权,请先运行:python /app/oauth_enroll.py {account}")
        result = app.acquire_token_silent(conf["scopes"], account=accounts[0])
        _save_cache(account, cache)
        if not result or "access_token" not in result:
            err = (result or {}).get("error_description") or (result or {}).get("error") or "无结果"
            raise OAuthError(f"刷新 {account} 的 token 失败({err});可能需重新 enroll")
        return result["access_token"]
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def enroll(account: str) -> None:
    """设备码流授权:终端打印 URL+码,用户浏览器同意后把 refresh token 存进缓存。"""
    conf = _conf(account)
    lock = _lock(account)
    try:
        cache = _load_cache(account)
        app = msal.PublicClientApplication(
            conf["client_id"], authority=conf["authority"], token_cache=cache
        )
        flow = app.initiate_device_flow(scopes=conf["scopes"])
        if "user_code" not in flow:
            raise OAuthError(f"发起设备码流失败: {json.dumps(flow, ensure_ascii=False)}")
        print(flow["message"], flush=True)  # 含验证 URL + 用户码
        result = app.acquire_token_by_device_flow(flow)  # 阻塞直到用户在浏览器完成
        _save_cache(account, cache)
        if "access_token" not in result:
            raise OAuthError(f"授权失败: {result.get('error_description', result)}")
        print(f"\n✓ {account} 授权成功,凭据已存 {_cache_path(account)}", flush=True)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


# ===================== 管理后台(mail-admin)用 =====================

def is_enrolled(account: str) -> bool:
    """有 token 缓存 ≈ 已授权(拿到过 refresh token)。"""
    return os.path.exists(_cache_path(account))


def list_accounts() -> list[dict]:
    """列出已配置的 OAuth 账号:{account, client_id, enrolled}。"""
    out: list[dict] = []
    if not os.path.isdir(CONFIG_DIR):
        return out
    for fn in sorted(os.listdir(CONFIG_DIR)):
        if not fn.endswith(".json"):
            continue
        acc = fn[:-5]
        try:
            with open(os.path.join(CONFIG_DIR, fn), encoding="utf-8") as f:
                c = json.load(f)
        except (OSError, json.JSONDecodeError):
            c = {}
        out.append({"account": acc, "client_id": c.get("client_id", ""), "enrolled": is_enrolled(acc)})
    return out


def save_config(account: str, client_id: str, authority: str = "", scopes: list | None = None) -> None:
    account = (account or "").strip()
    client_id = (client_id or "").strip()
    if not account or not client_id:
        raise OAuthError("账号名与 client_id 都不能为空")
    os.makedirs(CONFIG_DIR, exist_ok=True)
    data: dict = {"client_id": client_id}
    if authority.strip():
        data["authority"] = authority.strip()
    if scopes:
        data["scopes"] = scopes
    tmp = config_path(account) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, config_path(account))


def delete_account(account: str) -> None:
    for p in (config_path(account), _cache_path(account)):
        try:
            os.remove(p)
        except OSError:
            pass


# 后台设备码授权:start_device_flow 立刻返回 code+URL,后台线程轮询直到完成。
_flows: dict[str, dict] = {}
_flows_lock = threading.Lock()


def _set_flow(account: str, status: str, message: str) -> None:
    with _flows_lock:
        f = _flows.get(account, {})
        f["status"] = status
        f["message"] = message
        _flows[account] = f


def start_device_flow(account: str) -> dict:
    """发起设备码流并返回 {user_code, verification_uri, ...};后台线程完成授权并存缓存。"""
    conf = _conf(account)
    cache = _load_cache(account)
    app = msal.PublicClientApplication(
        conf["client_id"], authority=conf["authority"], token_cache=cache
    )
    flow = app.initiate_device_flow(scopes=conf["scopes"])
    if "user_code" not in flow:
        raise OAuthError(f"发起设备码流失败: {json.dumps(flow, ensure_ascii=False)}")
    with _flows_lock:
        _flows[account] = {
            "status": "pending",
            "message": "",
            "user_code": flow["user_code"],
            "verification_uri": flow.get("verification_uri", "https://microsoft.com/devicelogin"),
        }
    threading.Thread(target=_run_flow, args=(account, app, cache, flow), daemon=True).start()
    return _flows[account]


def _run_flow(account: str, app, cache, flow) -> None:
    try:
        result = app.acquire_token_by_device_flow(flow)  # 阻塞直到用户完成 / 超时
        if "access_token" in result:
            lock = _lock(account)
            try:
                _save_cache(account, cache)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
                lock.close()
            _set_flow(account, "success", "授权成功")
        else:
            _set_flow(account, "error", result.get("error_description") or result.get("error") or "授权失败")
    except Exception as exc:  # noqa: BLE001
        _set_flow(account, "error", str(exc))


def flow_status(account: str) -> dict | None:
    with _flows_lock:
        return dict(_flows[account]) if account in _flows else None
