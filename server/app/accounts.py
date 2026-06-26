"""WebUI 管理的邮箱账户(收/发 + 推送监听)—— 存可写的 /data,/config 保持只读。

一个账户端到端要同步三处:config.toml 的收发块、imapnotify.yaml 的监听块、secrets/*.pass。
本模块把这三者收敛成【单一可写源】/data/accounts.json + /data/secrets/<name>.pass:

- mail-api(收/发):imap_pool / mailsend 读 config.toml 后调 overlay_config() 把这里的账户
  合成 himalaya v1 schema 的账户块叠加进去 —— 现读现生效,无需重启。
- mail-watch(推送):render_imapnotify.py 把这里的账户渲染成 imapnotify 块,与 /config 里
  手写的 base 合并 → /data/imapnotify.generated.yaml;改动后 signal_reload() 触发 goimapnotify 重启。

兼容:accounts.json 不存在时 overlay 为空操作,行为与改造前完全一致;config.toml / imapnotify.yaml
里手写的账户作为 base 原样保留,只有【同名】才被 webui 账户覆盖。

accounts.json 记录字段:
  {name, email, login?, default?, push?, auth: "password"|"oauth2",
   enable_id_command?, imap:{host,port,encryption}, smtp:{host,port,encryption,save_copy},
   created}
encryption ∈ {"tls","starttls","none"}。oauth2 账户的凭据走现成的 oauth 模块(/data/oauth/<name>)。
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone

ACCOUNTS_FILE = os.environ.get("ACCOUNTS_FILE", "/data/accounts.json")
SECRETS_DIR = os.environ.get("DATA_SECRETS_DIR", "/data/secrets")
RELOAD_FLAG = os.environ.get("WATCH_RELOAD_FLAG", "/data/watch.reload")

_lock = threading.Lock()

# provider 预设:选了就自动填 host/port/encryption 等,用户只需填邮箱+密码。
# encryption: tls=隐式 TLS(993/465),starttls=明文起步再升级(587)。
PRESETS: dict[str, dict] = {
    "gmail": {
        "imap": {"host": "imap.gmail.com", "port": 993, "encryption": "tls"},
        "smtp": {"host": "smtp.gmail.com", "port": 465, "encryption": "tls", "save_copy": False},
        "auth": "password",
    },
    "outlook": {
        "imap": {"host": "outlook.office365.com", "port": 993, "encryption": "tls"},
        "smtp": {"host": "smtp.office365.com", "port": 587, "encryption": "starttls", "save_copy": False},
        "auth": "oauth2",
    },
    "yahoo": {
        "imap": {"host": "imap.mail.yahoo.com", "port": 993, "encryption": "tls"},
        "smtp": {"host": "smtp.mail.yahoo.com", "port": 465, "encryption": "tls", "save_copy": True},
        "auth": "password",
    },
    "netease126": {
        "imap": {"host": "imap.126.com", "port": 993, "encryption": "tls"},
        "smtp": {"host": "smtp.126.com", "port": 465, "encryption": "tls", "save_copy": True},
        "auth": "password", "enable_id_command": True,
    },
    "netease163": {
        "imap": {"host": "imap.163.com", "port": 993, "encryption": "tls"},
        "smtp": {"host": "smtp.163.com", "port": 465, "encryption": "tls", "save_copy": True},
        "auth": "password", "enable_id_command": True,
    },
    "fastmail": {
        "imap": {"host": "imap.fastmail.com", "port": 993, "encryption": "tls"},
        "smtp": {"host": "smtp.fastmail.com", "port": 465, "encryption": "tls", "save_copy": True},
        "auth": "password",
    },
    "custom": {},  # 全部手填
}

_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class AccountError(ValueError):
    pass


# ---------- 存取 ----------

def _read() -> list[dict]:
    try:
        with open(ACCOUNTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return [a for a in data if isinstance(a, dict) and a.get("name")]
    except (OSError, json.JSONDecodeError):
        pass
    return []


def _write(items: list[dict]) -> None:
    os.makedirs(os.path.dirname(ACCOUNTS_FILE), exist_ok=True)
    tmp = ACCOUNTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ACCOUNTS_FILE)  # 原子替换,避免另一容器读到半截


def load() -> list[dict]:
    return _read()


def get(name: str) -> dict | None:
    for a in _read():
        if a.get("name") == name:
            return a
    return None


def secret_path(name: str) -> str:
    return os.path.join(SECRETS_DIR, f"{name}.pass")


# ---------- 增删改 ----------

def upsert(form: dict, password: str | None = None) -> dict:
    """新增或更新一个账户。form 见模块 docstring 字段;preset 命中则补全 host/port 等。
    password 非空时写入 /data/secrets/<name>.pass(password 鉴权用;oauth2 忽略)。"""
    name = (form.get("name") or "").strip()
    if not name or not _NAME_RE.match(name):
        raise AccountError("账号名只能含字母/数字/.-_,且不能为空")

    preset = (form.get("preset") or "custom").strip()
    base = PRESETS.get(preset, {})

    def _sec(group: str, key: str, default):
        # 表单值优先,空则用 preset,再空用默认
        v = (form.get(group, {}) or {}).get(key)
        if v in (None, ""):
            v = (base.get(group, {}) or {}).get(key, default)
        return v

    auth = (form.get("auth") or base.get("auth") or "password").strip()
    rec = {
        "name": name,
        "email": (form.get("email") or "").strip(),
        "login": (form.get("login") or form.get("email") or "").strip(),
        "default": bool(form.get("default")),
        "push": bool(form.get("push", True)),
        "auth": "oauth2" if auth == "oauth2" else "password",
        "enable_id_command": bool(form.get("enable_id_command", base.get("enable_id_command", False))),
        "imap": {
            "host": (_sec("imap", "host", "") or "").strip(),
            "port": int(_sec("imap", "port", 993) or 993),
            "encryption": _sec("imap", "encryption", "tls"),
        },
        "smtp": {
            "host": (_sec("smtp", "host", "") or "").strip(),
            "port": int(_sec("smtp", "port", 465) or 465),
            "encryption": _sec("smtp", "encryption", "tls"),
            "save_copy": bool(_sec("smtp", "save_copy", False)),
        },
    }
    if not rec["email"]:
        raise AccountError("邮箱地址不能为空")
    if not rec["imap"]["host"] or not rec["smtp"]["host"]:
        raise AccountError("IMAP/SMTP host 不能为空(选一个 provider 预设可自动填)")

    with _lock:
        items = _read()
        old = next((a for a in items if a.get("name") == name), None)
        if old is None:
            rec["created"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            items.append(rec)
        else:
            rec["created"] = old.get("created", "")
            items[items.index(old)] = rec
        _write(items)

    if rec["auth"] == "password" and password:
        _write_secret(name, password)
    signal_reload()
    return rec


def delete(name: str) -> bool:
    with _lock:
        items = _read()
        new = [a for a in items if a.get("name") != name]
        if len(new) == len(items):
            return False
        _write(new)
    try:
        os.remove(secret_path(name))
    except OSError:
        pass
    signal_reload()
    return True


def _write_secret(name: str, password: str) -> None:
    os.makedirs(SECRETS_DIR, exist_ok=True)
    tmp = secret_path(name) + ".tmp"
    # goimapnotify / auth.cmd 用 `cat` 读,末尾换行无所谓;去掉首尾空白更稳。
    with open(tmp, "w", encoding="utf-8") as f:
        f.write((password or "").strip())
    os.replace(tmp, secret_path(name))
    os.chmod(secret_path(name), 0o600)


def has_secret(name: str) -> bool:
    return os.path.exists(secret_path(name))


def signal_reload() -> None:
    """碰一下重载标记文件;mail-watch 的 entrypoint 监听到 mtime 变化就重启 goimapnotify。"""
    try:
        os.makedirs(os.path.dirname(RELOAD_FLAG), exist_ok=True)
        with open(RELOAD_FLAG, "w", encoding="utf-8") as f:
            f.write(datetime.now(timezone.utc).isoformat())
    except OSError:
        pass


# ---------- 渲染:mail-api 侧(himalaya v1 schema) ----------

def _enc_toml(enc: str) -> dict:
    return {"type": {"starttls": "start-tls"}.get(enc, enc or "tls")}


def _auth_block(rec: dict) -> dict:
    name = rec["name"]
    if rec.get("auth") == "oauth2":
        return {"type": "oauth2", "cmd": f"python /app/oauth_token.py {name}"}
    return {"type": "password", "cmd": f"cat {secret_path(name)}"}


def _to_himalaya(rec: dict) -> dict:
    login = rec.get("login") or rec.get("email")
    imap = rec.get("imap", {}) or {}
    smtp = rec.get("smtp", {}) or {}
    auth = _auth_block(rec)
    block = {
        "email": rec.get("email") or login,
        "backend": {
            "type": "imap",
            "host": imap.get("host"),
            "port": int(imap.get("port", 993)),
            "encryption": _enc_toml(imap.get("encryption", "tls")),
            "login": login,
            "auth": auth,
        },
        "message": {"send": {"backend": {
            "type": "smtp",
            "host": smtp.get("host"),
            "port": int(smtp.get("port", 465)),
            "encryption": _enc_toml(smtp.get("encryption", "tls")),
            "login": login,
            "auth": auth,
        }, "save-copy": bool(smtp.get("save_copy", False))}},
    }
    if rec.get("default"):
        block["default"] = True
    return block


def overlay_config(cfg: dict) -> dict:
    """把 webui 账户合并进 config.toml 解析结果(himalaya schema)。同名覆盖,异名新增。
    cfg 为 None / 缺 accounts 时也安全。"""
    merged = dict(cfg or {})
    accs = dict(merged.get("accounts", {}) or {})
    for rec in _read():
        try:
            accs[rec["name"]] = _to_himalaya(rec)
        except Exception:  # noqa: BLE001 — 单条坏账户不拖垮整体
            continue
    merged["accounts"] = accs
    return merged


# ---------- 渲染:mail-watch 侧(goimapnotify 块) ----------

def to_imapnotify(rec: dict) -> dict:
    name = rec["name"]
    imap = rec.get("imap", {}) or {}
    enc = imap.get("encryption", "tls")
    block = {
        "host": imap.get("host"),
        "port": int(imap.get("port", 993)),
        "tls": enc == "tls",
        "tlsOptions": {"starttls": enc == "starttls"},
        "alias": name,
        "username": rec.get("login") or rec.get("email"),
        "onNewMail": f"/app/push-fcm.py {name}",
        "onNewMailPost": "SKIP",
        "boxes": [{
            "mailbox": "INBOX",
            "onNewMail": f"/app/push-fcm.py {name}",
            "onNewMailPost": "SKIP",
        }],
    }
    if rec.get("auth") == "oauth2":
        block["xoauth2"] = True
        block["passwordCMD"] = f"python /app/oauth_token.py {name}"
    else:
        block["passwordCMD"] = f"cat {secret_path(name)}"
    if rec.get("enable_id_command"):
        block["enableIDCommand"] = True
    return block
