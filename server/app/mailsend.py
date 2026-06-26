"""直连 SMTP 发信(替代 himalaya send,避免它无条件做 IMAP APPEND 存副本——
Gmail 会串进收件箱、某些自建/机构 IMAP 会 APPENDUID 报错/超时)。

从 config.toml 读账号的 message.send.backend.*(host/port/encryption/login/auth.cmd),
只发原始 MIME,不碰 IMAP。"已发送"交给上游 SMTP 自动归档(Gmail/Outlook 会;
不自动归档的 provider 暂无"已发送"记录)。
"""
from __future__ import annotations

import base64
import os
import smtplib
import ssl
import subprocess
import tomllib

import accounts  # webui 管理的账户(/data),叠加在 config.toml 之上

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/config/config.toml")


class SmtpError(RuntimeError):
    pass


def _load() -> dict:
    try:
        with open(CONFIG_PATH, "rb") as f:
            cfg = tomllib.load(f)
    except OSError:
        cfg = {}  # 没有 config.toml 也行:账户可能全由 webui 管理
    return accounts.overlay_config(cfg)


def account_from(account: str) -> str | None:
    """账号发件地址:email 优先,退回 send.backend.login / backend.login。"""
    acc = _load().get("accounts", {}).get(account, {})
    send_login = acc.get("message", {}).get("send", {}).get("backend", {}).get("login")
    return acc.get("email") or send_login or acc.get("backend", {}).get("login")


def _smtp_conf(account: str):
    acc = _load().get("accounts", {}).get(account)
    if not acc:
        raise SmtpError(f"账号 {account} 不存在于 config")
    b = acc.get("message", {}).get("send", {}).get("backend", {})
    host = b.get("host")
    port = int(b.get("port", 465))
    enc = (b.get("encryption", {}) or {}).get("type", "tls")
    login = b.get("login")
    auth = b.get("auth", {}) or {}
    auth_type = (auth.get("type") or "password").lower()
    if auth.get("cmd"):
        out = subprocess.run(auth["cmd"], shell=True, capture_output=True, text=True, timeout=15)
        secret = out.stdout.strip()  # oauth2 时这是 access token,否则是密码
        if not secret:
            # auth.cmd 无输出(oauth2 刷新失败常走到这):暴露退出码 + stderr,别吞真因。
            err = (out.stderr or "").strip()
            raise SmtpError(f"auth.cmd 无输出(exit={out.returncode}): {err or '(stderr 为空)'}")
    else:
        secret = auth.get("passwd") or auth.get("password") or auth.get("raw")
    if not (host and login and secret):
        raise SmtpError("SMTP 配置不完整(需要 host / login / 密码或 token)")
    return host, port, enc, login, secret, auth_type


def _auth(s: smtplib.SMTP, auth_type: str, login: str, secret: str) -> None:
    """认证(调用方已 ehlo)。oauth2 走 SASL XOAUTH2,否则普通 login。"""
    if auth_type == "oauth2":
        blob = f"user={login}\x01auth=Bearer {secret}\x01\x01"
        code, resp = s.docmd("AUTH", "XOAUTH2 " + base64.b64encode(blob.encode()).decode())
        if code != 235:
            raise SmtpError(f"SMTP XOAUTH2 认证失败: {code} {resp!r}")
    else:
        s.login(login, secret)


def send(account: str, recipients: list[str], raw_bytes: bytes) -> None:
    """把原始 MIME 发给 recipients(信封收件人 = to+cc+bcc)。"""
    if not recipients:
        raise SmtpError("收件人为空")
    host, port, enc, login, secret, auth_type = _smtp_conf(account)
    from_addr = account_from(account) or login
    ctx = ssl.create_default_context()
    try:
        if enc == "tls":  # 隐式 TLS(一般 465)
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
                s.ehlo()
                _auth(s, auth_type, login, secret)
                s.sendmail(from_addr, recipients, raw_bytes)
        else:  # starttls / none(一般 587 / 25)
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.ehlo()
                if enc in ("starttls", "start-tls", "start_tls"):
                    s.starttls(context=ctx)
                    s.ehlo()
                _auth(s, auth_type, login, secret)
                s.sendmail(from_addr, recipients, raw_bytes)
    except (smtplib.SMTPException, OSError) as exc:
        raise SmtpError(f"SMTP 发送失败: {exc}")
