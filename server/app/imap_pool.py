"""持久 IMAP 连接池(替代 himalaya 每次 fork 子进程 + 新建连接)。

每个账号维护一条长连的 imaplib.IMAP4(_SSL),按账号加锁【串行】复用:
  - 首连昂贵的账号(某些企业/机构邮箱对来访 IP 做反向 DNS,家庭宽带无 PTR 记录,
    新连接 greeting 要等数十秒)只在首连付一次,之后操作毫秒级;
  - 连接被服务器/路由器掐掉后【自动重连】(操作失败 → 丢弃 → 重连重试一次);
  - 后台 daemon 保活线程定时 NOOP,把昂贵账号的连接焐热,避免空闲被回收后又重付建连。

配置直接读 himalaya v1.2.0 的 config.toml(accounts.<name>.backend.*),与 mailsend.py
读 message.send.backend.* 同源,用户【无需改配置】。

登录后【无条件发 IMAP ID(RFC 2971)】:网易 163/126 要求登录后报家门,himalaya v1.2.0
不支持(issue #656)→ 本池在代码层统一发,顺带解锁 163/126 读信。
"""
from __future__ import annotations

import imaplib
import os
import ssl
import sys
import subprocess
import threading
import time
import tomllib
from dataclasses import dataclass

import accounts  # webui 管理的账户(/data),叠加在 config.toml 之上

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/config/config.toml")
# 做反向 DNS 的邮箱首连可能数十秒,建连超时留余量;连上后命令超时收紧,半死连接快速失败。
CONNECT_TIMEOUT = float(os.environ.get("IMAP_CONNECT_TIMEOUT", "90"))
OP_TIMEOUT = float(os.environ.get("IMAP_OP_TIMEOUT", "30"))
# 保活心跳间隔:压在常见 NAT/路由器 ~5min 空闲回收线以内、远低于服务器 ≥30min 自动登出。
KEEPALIVE = float(os.environ.get("IMAP_KEEPALIVE", "240"))
ID_ARGS = '("name" "melonmail" "version" "1.0")'

# imaplib 的命令白名单里没有 RFC 2971 的 ID;不注册的话 _simple_command("ID", ...)
# 会被 imaplib 当非法命令拒发 → 网易 163/126 收不到报家门 → 拒登/拒读。各状态都允许发。
imaplib.Commands.setdefault("ID", ("NONAUTH", "AUTH", "SELECTED", "LOGOUT"))


class ImapError(RuntimeError):
    pass


@dataclass
class ImapConfig:
    host: str
    port: int
    encryption: str  # tls / starttls / none
    login: str
    auth_cmd: str | None
    auth_passwd: str | None
    auth_type: str = "password"  # password / oauth2;oauth2 时 secret() 返回的是 access token

    def password(self) -> str:
        if self.auth_cmd:
            try:
                out = subprocess.run(
                    self.auth_cmd, shell=True, capture_output=True, text=True, timeout=15
                )
            except subprocess.SubprocessError as exc:
                raise ImapError(f"运行 auth.cmd 失败: {exc}")
            pw = out.stdout.strip()
            if pw:
                return pw
            if self.auth_passwd:
                return self.auth_passwd
            # auth.cmd 无输出(oauth2 刷新失败常走到这):把退出码 + stderr 抛出来,
            # 否则真实原因被吞,只剩"连不上"。OAuth 的真因(未授权/scope/网络)都在 stderr。
            err = (out.stderr or "").strip()
            raise ImapError(
                f"auth.cmd 无输出(exit={out.returncode}): {err or '(stderr 为空)'}"
            )
        if self.auth_passwd:
            return self.auth_passwd
        raise ImapError("缺少密码(无 auth.cmd 也无 auth.passwd)")


def load_config(account: str) -> ImapConfig:
    """从 config.toml 读账号收信侧配置(himalaya v1 schema 的 accounts.<name>.backend.*)。"""
    try:
        with open(CONFIG_PATH, "rb") as f:
            cfg = tomllib.load(f)
    except OSError:
        cfg = {}  # 没有 config.toml 也行:可能账户全由 webui(/data/accounts.json)管理
    cfg = accounts.overlay_config(cfg)  # 叠加 webui 账户(同名覆盖)
    acc = cfg.get("accounts", {}).get(account)
    if not acc:
        raise ImapError(f"账号 {account} 不在 config")
    b = acc.get("backend", {}) or {}
    if (b.get("type") or "imap") != "imap":
        raise ImapError(f"账号 {account} backend.type 非 imap")
    host = b.get("host")
    login = b.get("login")
    if not host or not login:
        raise ImapError(f"账号 {account} 缺少 backend.host/login")
    enc = (b.get("encryption", {}) or {}).get("type", "tls").lower().replace("_", "-")
    if enc in ("start-tls", "starttls"):
        encryption = "starttls"
    elif enc == "none":
        encryption = "none"
    else:
        encryption = "tls"
    auth = b.get("auth", {}) or {}
    return ImapConfig(
        host=host,
        port=int(b.get("port", 993)),
        encryption=encryption,
        login=login,
        auth_cmd=auth.get("cmd"),
        auth_passwd=auth.get("passwd") or auth.get("password") or auth.get("raw"),
        auth_type=(auth.get("type") or "password").lower(),
    )


class _Pool:
    def __init__(self) -> None:
        self._conns: dict[str, imaplib.IMAP4] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._master = threading.Lock()
        self._ka_started = False

    # ---- 锁 ----
    def _lock(self, account: str) -> threading.Lock:
        with self._master:
            lk = self._locks.get(account)
            if lk is None:
                lk = threading.Lock()
                self._locks[account] = lk
            return lk

    # ---- 连接 ----
    def _connect(self, account: str) -> imaplib.IMAP4:
        cfg = load_config(account)
        ctx = ssl.create_default_context()
        if cfg.encryption == "tls":
            conn = imaplib.IMAP4_SSL(
                cfg.host, cfg.port, ssl_context=ctx, timeout=CONNECT_TIMEOUT
            )
        else:
            conn = imaplib.IMAP4(cfg.host, cfg.port, timeout=CONNECT_TIMEOUT)
            if cfg.encryption == "starttls":
                conn.starttls(ssl_context=ctx)
        # greeting 已收到(rDNS 已付);后续命令收紧超时,半死连接快速失败 → 触发重连。
        try:
            conn.sock.settimeout(OP_TIMEOUT)
        except OSError:
            pass
        if cfg.auth_type == "oauth2":
            self._xoauth2(conn, cfg.login, cfg.password())  # password() 此时返回 access token
        else:
            conn.login(cfg.login, cfg.password())
        self._send_id(conn)
        return conn

    @staticmethod
    def _xoauth2(conn: imaplib.IMAP4, user: str, token: str) -> None:
        """用 OAuth2 access token 走 SASL XOAUTH2 登录(imaplib 自己 base64)。"""
        auth = f"user={user}\x01auth=Bearer {token}\x01\x01"
        conn.authenticate("XOAUTH2", lambda _challenge=None: auth.encode())

    @staticmethod
    def _send_id(conn: imaplib.IMAP4) -> None:
        """登录后发 IMAP ID(RFC 2971);服务器不支持就忽略。解锁网易 163/126 的关键。"""
        try:
            typ, dat = conn._simple_command("ID", ID_ARGS)
            conn._untagged_response(typ, dat, "ID")
        except Exception as exc:  # noqa: BLE001 — 不支持 ID 的服务器照常用,只记一行不阻断
            print(f"[imap] IMAP ID 发送失败(忽略): {exc!r}", file=sys.stderr, flush=True)

    def _get(self, account: str) -> imaplib.IMAP4:
        conn = self._conns.get(account)
        if conn is not None:
            return conn
        conn = self._connect(account)
        self._conns[account] = conn
        self._start_keepalive()
        return conn

    def _drop(self, account: str) -> None:
        conn = self._conns.pop(account, None)
        if conn is not None:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass

    # ---- 执行(串行 + 断线重连)----
    def run(self, account: str, fn):
        """按账号锁串行执行 fn(conn);连接半死/被掐时重连重试一次。"""
        with self._lock(account):
            try:
                return fn(self._get(account))
            except imaplib.IMAP4.abort as exc:  # 连接丢失 → 重连重试
                self._drop(account)
                return self._retry(account, fn, exc)
            except (OSError, EOFError) as exc:  # 含 socket.timeout
                self._drop(account)
                return self._retry(account, fn, exc)
            except imaplib.IMAP4.error as exc:  # 命令被拒,重试无意义
                raise ImapError(f"IMAP 命令失败(account={account}): {exc}") from exc

    def _retry(self, account: str, fn, exc):
        try:
            return fn(self._get(account))
        except Exception as exc2:  # noqa: BLE001
            self._drop(account)
            raise ImapError(f"IMAP 操作失败(account={account}): {exc2}") from exc2

    # ---- 保活 ----
    def _start_keepalive(self) -> None:
        if self._ka_started:
            return
        self._ka_started = True
        threading.Thread(
            target=self._keepalive_loop, name="imap-keepalive", daemon=True
        ).start()

    def _keepalive_loop(self) -> None:
        while True:
            time.sleep(KEEPALIVE)
            for account in list(self._conns.keys()):
                lk = self._lock(account)
                if not lk.acquire(blocking=False):
                    continue  # 正被业务使用,跳过这轮(不和请求抢锁)
                try:
                    conn = self._conns.get(account)
                    if conn is None:
                        continue
                    try:
                        conn.noop()
                    except Exception:  # noqa: BLE001
                        self._drop(account)  # 掐了就丢,下次请求重连
                finally:
                    lk.release()


pool = _Pool()
