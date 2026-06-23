#!/usr/bin/env python3
"""goimapnotify onNewMail 钩子 → FCM 推送(多设备)。

被 imapnotify.yaml 的 onNewMail 调用,只带一个参数:账号名(goimapnotify 不传
sender/subject)。本脚本用 imap_client 抓该账号 INBOX 最新一封取 sender/subject。

设备 token 由安卓端自动上报到 mail-api 的 /register-token,存 /data(见 devicetokens.py);
本脚本群发到全部已注册设备,并自动清理失效 token。

去重:用 /data 里的 last-seen,只有"最新一封 id 与上次不同"才推送;首次只记基线不推
(避免 goimapnotify 启动时把已存在的旧信当新信)。

注:本脚本是 goimapnotify 每来新信 fork 的短命进程,imap_pool 在此无法跨调用复用连接
(每次推送新建一次连接;Gmail ~1s,做 rDNS 的邮箱首连可能数十秒,属后台行为可接受)。
"""
import asyncio
import os
import sys

import firebase_admin
from firebase_admin import credentials, messaging

import devicetokens
import imap_client

SA_PATH = os.environ.get("FIREBASE_SA", "/config/service-account.json")
STATE_DIR = os.environ.get("MAILPUSH_STATE_DIR", "/data/state/mailpush")


def log(msg: str) -> None:
    print(f"[push] {msg}", file=sys.stderr, flush=True)


def fetch_latest(account: str):
    """用 imap_client 抓 INBOX 最新一封,返回 (id, sender, subject) 或 None。"""
    try:
        envs = asyncio.run(imap_client.list_envelopes(account, "INBOX", 1, 1))
    except imap_client.ImapError as exc:
        log(f"取最新信失败(account={account}): {exc}")
        return None
    except Exception as exc:  # noqa: BLE001 — 钩子里别让 goimapnotify 崩
        log(f"取最新信异常(account={account}): {exc!r}")
        return None
    if not envs:
        log("返回空列表")
        return None
    env = envs[0]
    msg_id = str(env.get("id", "")) if isinstance(env, dict) else ""
    subject = env.get("subject", "") if isinstance(env, dict) else ""
    sender = _extract_sender(env.get("from")) if isinstance(env, dict) else ""
    return msg_id, sender, subject


def _extract_sender(frm) -> str:
    if isinstance(frm, dict):
        return frm.get("name") or frm.get("addr") or frm.get("address") or ""
    if isinstance(frm, str):
        return frm
    return ""


def _state_file(account: str) -> str:
    return os.path.join(STATE_DIR, f"last-{account}")


def _read_last(account: str):
    try:
        with open(_state_file(account), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _write_last(account: str, msg_id: str) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(_state_file(account), "w", encoding="utf-8") as f:
        f.write(msg_id)


def send_fcm(tokens: list[str], sender: str, subject: str, account: str, msg_id: str = "") -> None:
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(SA_PATH))

    message = messaging.MulticastMessage(
        tokens=tokens,
        data={"sender": sender, "subject": subject, "account": account, "id": msg_id},
        android=messaging.AndroidConfig(priority="high"),
    )
    try:
        resp = messaging.send_each_for_multicast(message)
    except Exception as exc:  # noqa: BLE001 — 钩子里失败不应让 goimapnotify 崩
        log(f"FCM 群发失败:{exc!r}")
        return

    stale: list[str] = []
    for token, r in zip(tokens, resp.responses):
        if not r.success:
            exc = r.exception
            if isinstance(exc, messaging.UnregisteredError):
                stale.append(token)
            else:
                log(f"发送失败(token…{token[-6:]}):{exc}")
    if stale:
        devicetokens.remove(stale)
        log(f"清理 {len(stale)} 个失效 token")
    log(f"sent ok={resp.success_count} fail={resp.failure_count} account={account} sender={sender!r} subject={subject!r}")


def main() -> int:
    account = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MAILPUSH_ACCOUNT", "")
    if not account:
        log("未提供账号名(onNewMail 应写成:/app/push-fcm.py <account>)")
        return 0

    tokens = devicetokens.load()

    latest = fetch_latest(account)
    if latest is None:
        if tokens:
            send_fcm(tokens, "", "(有新邮件)", account)
        else:
            log("取不到最新信且无已注册设备,跳过")
        return 0

    msg_id, sender, subject = latest
    last = _read_last(account)

    if last is None:
        _write_last(account, msg_id or "")
        log(f"建立去重基线 account={account} id={msg_id!r},不推送")
        return 0
    if msg_id and msg_id == last:
        log(f"无新信(account={account} id={msg_id} 未变),跳过")
        return 0

    if not tokens:
        log(f"有新信(account={account} id={msg_id})但无已注册设备,暂不推送、不更新基线")
        return 0

    send_fcm(tokens, sender, subject or "(有新邮件)", account, msg_id)
    if msg_id:
        _write_last(account, msg_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
