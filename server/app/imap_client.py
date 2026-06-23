"""IMAP 操作层(替代 himalaya.py),经 imap_pool 复用长连接。

函数名/签名与原 himalaya.py 保持一致 —— api.py 仅需把 `import himalaya` 换成
`import imap_client`(并把 himalaya.HimalayaError 换成 imap_client.ImapError)。

返回数据形状严格对齐 himalaya `-o json`,保证 Android app 零改动(见 imap-pool-design.md
「兼容性契约 A」):
  envelope = {id(=IMAP UID, str), subject, from:{name,addr}, to:{name,addr},
              date(ISO 8601), flags:[...], has_attachment:bool}

排序不依赖服务器端 SORT(Gmail 不支持):UID 升序代表到达先后,反转即「最新在前」。
"""
from __future__ import annotations

import asyncio
import base64
import email
import email.policy
import email.utils
import os
import re
import tomllib

from imap_pool import CONFIG_PATH, ImapError, pool

__all__ = [
    "ImapError", "list_envelopes", "export_full", "add_flag", "delete_message",
    "list_folders", "download_attachments", "reply_template", "forward_template",
    "unread_count",
]

_UID_RE = re.compile(rb"UID (\d+)")
_FLAGS_RE = re.compile(rb"FLAGS \(([^)]*)\)")
_LIST_RE = re.compile(rb'^\([^)]*\) (?:"[^"]*"|NIL) (?P<name>.*)$')

_FLAG_MAP = {
    "seen": "\\Seen", "answered": "\\Answered", "flagged": "\\Flagged",
    "deleted": "\\Deleted", "draft": "\\Draft",
}

_SENT_TRASH_PREFERRED = [
    "[Gmail]/Trash", "Trash", "Deleted", "Deleted Items", "Deleted Messages",
    "INBOX.Trash", "垃圾邮件", "已删除", "已删除邮件",
]


# ---------- IMAP modified UTF-7(RFC 3501 §5.1.3)----------
# 文件夹名在 IMAP 线上用 modified UTF-7 传(中文「已发送」等),不是 UTF-8。
# himalaya 之前替我们做了编解码;换 imaplib 后需自己处理,否则中文文件夹认不出/选不中。

def imap_utf7_encode(name: str) -> str:
    """Unicode 文件夹名 → modified UTF-7(ASCII)。ASCII 名原样返回。"""
    res: list[str] = []
    i, n = 0, len(name)
    while i < n:
        ch = name[i]
        o = ord(ch)
        if 0x20 <= o <= 0x7e:
            res.append("&-" if ch == "&" else ch)
            i += 1
        else:
            j = i
            while j < n and not (0x20 <= ord(name[j]) <= 0x7e):
                j += 1
            b = name[i:j].encode("utf-16-be")
            enc = base64.b64encode(b).decode("ascii").rstrip("=").replace("/", ",")
            res.append("&" + enc + "-")
            i = j
    return "".join(res)


def imap_utf7_decode(raw) -> str:
    """modified UTF-7 → Unicode。"""
    s = bytes(raw).decode("ascii", "replace") if isinstance(raw, (bytes, bytearray)) else raw
    res: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "&":
            j = s.find("-", i)
            if j == -1:
                res.append(s[i:])
                break
            seg = s[i + 1:j]
            if seg == "":
                res.append("&")  # "&-" → "&"
            else:
                b64 = seg.replace(",", "/")
                b64 += "=" * (-len(b64) % 4)
                try:
                    res.append(base64.b64decode(b64).decode("utf-16-be"))
                except Exception:  # noqa: BLE001 — 解不了就原样保留
                    res.append(s[i:j + 1])
            i = j + 1
        else:
            res.append(s[i])
            i += 1
    return "".join(res)


# ---------- 小工具 ----------

def _quote(name: str) -> str:
    """SELECT/COPY 用:Unicode 名 → modified UTF-7 → 加引号。"""
    return '"' + imap_utf7_encode(name).replace('"', '\\"') + '"'


def _addr(headerval: str) -> dict:
    name, addr = email.utils.parseaddr(headerval or "")
    return {"name": name, "addr": addr}


def _hdr(msg, key: str) -> str:
    v = msg[key]
    return str(v) if v is not None else ""


def _select(conn, folder: str, readonly: bool) -> None:
    typ, _ = conn.select(_quote(folder), readonly=readonly)
    if typ != "OK":
        raise ImapError(f"SELECT {folder} 失败")


def _fetch_raw(conn, msg_id: str) -> bytes:
    """取整封原始 RFC822(BODY.PEEK[],不标已读)。调用方需先 SELECT。"""
    typ, data = conn.uid("FETCH", str(msg_id), "(BODY.PEEK[])")
    if typ != "OK" or not data or not isinstance(data[0], tuple):
        raise ImapError(f"取邮件 {msg_id} 失败")
    return data[0][1]


def _acct_addr(account: str) -> str:
    """账号发件地址:email 优先,退回 backend.login(回复/转发的 From)。"""
    try:
        with open(CONFIG_PATH, "rb") as f:
            cfg = tomllib.load(f)
    except OSError:
        return ""
    acc = cfg.get("accounts", {}).get(account, {})
    return acc.get("email") or acc.get("backend", {}).get("login") or ""


def _text_body(msg) -> str:
    """取纯文本正文用于引用;无 text/plain 时退化为去标签的 html。"""
    parts = msg.walk() if msg.is_multipart() else [msg]
    html_fallback = ""
    for part in parts:
        if part.is_multipart():
            continue
        if (part.get_content_disposition() or "") == "attachment":
            continue
        ctype = part.get_content_type()
        try:
            content = part.get_content()
        except Exception:  # noqa: BLE001
            continue
        if ctype == "text/plain":
            return content
        if ctype == "text/html" and not html_fallback:
            html_fallback = re.sub(r"<[^>]+>", "", content)
    return html_fallback


# ---------- 列表 ----------

def _list(conn, folder: str, page: int, page_size: int) -> list:
    _select(conn, folder, True)
    typ, data = conn.uid("SEARCH", "ALL")
    if typ != "OK":
        raise ImapError("SEARCH 失败")
    uids = data[0].split() if data and data[0] else []
    uids.reverse()  # UID 升序 = 到达先后;反转 → 最新在前
    start = (page - 1) * page_size
    chunk = uids[start:start + page_size]
    if not chunk:
        return []
    setarg = ",".join(u.decode() for u in chunk)
    typ, data = conn.uid(
        "FETCH", setarg,
        "(UID FLAGS BODYSTRUCTURE BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)])",
    )
    if typ != "OK":
        raise ImapError("FETCH 失败")

    by_uid: dict[str, dict] = {}
    for item in data:
        if not isinstance(item, tuple):
            continue
        meta, hdr = item[0], item[1] or b""
        m = _UID_RE.search(meta)
        if not m:
            continue
        uid = m.group(1).decode()
        flags: list[str] = []
        fm = _FLAGS_RE.search(meta)
        if fm:
            flags = [f.lstrip("\\") for f in fm.group(1).decode().split() if f]
        # BODYSTRUCTURE 启发式:显式 attachment 处置,或 multipart/mixed(附件邮件几乎都是
        # mixed;inline 图片走 related/alternative,故不误判)。app 不强依赖此字段。
        ml = meta.lower()
        has_att = b"attachment" in ml or b'"mixed"' in ml
        msg = email.message_from_bytes(hdr, policy=email.policy.default)
        date = ""
        if msg["Date"]:
            try:
                date = email.utils.parsedate_to_datetime(_hdr(msg, "Date")).isoformat()
            except (TypeError, ValueError):
                date = ""
        by_uid[uid] = {
            "id": uid,
            "subject": _hdr(msg, "Subject"),
            "from": _addr(_hdr(msg, "From")),
            "to": _addr(_hdr(msg, "To")),
            "date": date,
            "flags": flags,
            "has_attachment": has_att,
        }
    # 按 chunk(已最新在前)顺序输出
    return [by_uid[u.decode()] for u in chunk if u.decode() in by_uid]


async def list_envelopes(account: str, folder: str = "INBOX", page: int = 1, page_size: int = 50):
    return await asyncio.to_thread(pool.run, account, lambda c: _list(c, folder, page, page_size))


# ---------- 未读数 ----------

def _unread(conn, folder: str) -> int:
    _select(conn, folder, True)
    typ, data = conn.uid("SEARCH", "UNSEEN")
    if typ != "OK":
        raise ImapError("SEARCH UNSEEN 失败")
    ids = data[0].split() if data and data[0] else []
    return len(ids)


async def unread_count(account: str, folder: str = "INBOX") -> int:
    return await asyncio.to_thread(pool.run, account, lambda c: _unread(c, folder))


# ---------- 导出原始邮件(供 api.py 解析正文)----------

def _export(conn, msg_id: str, dest_dir: str, folder: str) -> str:
    _select(conn, folder, True)
    raw = _fetch_raw(conn, msg_id)
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, f"{msg_id}.eml")
    with open(path, "wb") as f:
        f.write(raw)
    return path


async def export_full(account: str, msg_id: str, dest_dir: str, folder: str = "INBOX"):
    return await asyncio.to_thread(pool.run, account, lambda c: _export(c, msg_id, dest_dir, folder))


# ---------- 标记 ----------

def _add_flag(conn, msg_id: str, flag: str, folder: str) -> str:
    _select(conn, folder, False)
    fl = _FLAG_MAP.get(flag.lower().lstrip("\\"), flag)
    typ, _ = conn.uid("STORE", str(msg_id), "+FLAGS", f"({fl})")
    if typ != "OK":
        raise ImapError(f"STORE {flag} 失败")
    return "ok"


async def add_flag(account: str, msg_id: str, flag: str, folder: str = "INBOX"):
    return await asyncio.to_thread(pool.run, account, lambda c: _add_flag(c, msg_id, flag, folder))


# ---------- 文件夹 ----------

def _parse_folder_names(data) -> list:
    names: list[str] = []
    for line in data or []:
        if isinstance(line, tuple):
            line = line[0]
        if not isinstance(line, (bytes, bytearray)):
            continue
        m = _LIST_RE.search(bytes(line))
        if not m:
            continue
        name = m.group("name").strip()
        if name.startswith(b'"') and name.endswith(b'"'):
            name = name[1:-1]
        if name:
            # 线上是 modified UTF-7,解成 Unicode(中文文件夹才显示/可探测「已发送」)
            names.append(imap_utf7_decode(name.replace(b'\\"', b'"')))
    return names


def _folders(conn) -> list:
    typ, data = conn.list()
    if typ != "OK":
        raise ImapError("LIST 失败")
    return _parse_folder_names(data)


async def list_folders(account: str):
    return await asyncio.to_thread(pool.run, account, _folders)


def _detect_trash(names: list) -> str | None:
    lower = {n.lower(): n for n in names}
    for p in _SENT_TRASH_PREFERRED:
        if p.lower() in lower:
            return lower[p.lower()]
    for n in names:
        nl = n.lower()
        if "trash" in nl or "deleted" in nl or "已删除" in n or "垃圾" in n:
            return n
    return None


# ---------- 删除(移到回收站)----------

def _delete(conn, msg_id: str, folder: str) -> str:
    trash = _detect_trash(_folders(conn))
    _select(conn, folder, False)
    uid = str(msg_id)
    if trash and trash.lower() != folder.lower():
        try:
            conn.uid("COPY", uid, _quote(trash))  # 复制到回收站;失败则退化为直接删
        except Exception:  # noqa: BLE001
            pass
    conn.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
    conn.expunge()
    return "ok"


async def delete_message(account: str, msg_id: str, folder: str = "INBOX"):
    return await asyncio.to_thread(pool.run, account, lambda c: _delete(c, msg_id, folder))


# ---------- 附件 ----------

def _download(conn, msg_id: str, dest_dir: str, folder: str) -> str:
    _select(conn, folder, True)
    msg = email.message_from_bytes(_fetch_raw(conn, msg_id), policy=email.policy.default)
    os.makedirs(dest_dir, exist_ok=True)
    n = 0
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        disp = part.get_content_disposition() or ""
        if not filename and disp != "attachment":
            continue
        try:
            payload = part.get_payload(decode=True)
        except Exception:  # noqa: BLE001
            continue
        if payload is None:
            continue
        safe = os.path.basename(filename or f"attachment-{n + 1}")
        with open(os.path.join(dest_dir, safe), "wb") as f:
            f.write(payload)
        n += 1
    return f"downloaded {n}"


async def download_attachments(account: str, msg_id: str, dest_dir: str, folder: str = "INBOX"):
    return await asyncio.to_thread(pool.run, account, lambda c: _download(c, msg_id, dest_dir, folder))


# ---------- 回复/转发模板(输出与 himalaya 一致的 "Key: value\n\n引用") ----------

def _quote_block(orig) -> str:
    name_addr = email.utils.parseaddr(_hdr(orig, "From"))
    who = name_addr[0] or name_addr[1] or "someone"
    date = _hdr(orig, "Date")
    head = f"On {date}, {who} wrote:" if date else f"{who} wrote:"
    body = _text_body(orig)
    quoted = "\n".join("> " + ln for ln in body.splitlines())
    return f"{head}\n{quoted}"


def _reply(conn, account: str, msg_id: str, reply_all: bool, folder: str) -> str:
    _select(conn, folder, True)
    orig = email.message_from_bytes(_fetch_raw(conn, msg_id), policy=email.policy.default)
    me = _acct_addr(account)
    to = _hdr(orig, "Reply-To") or _hdr(orig, "From")
    subject = _hdr(orig, "Subject")
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject
    in_reply_to = _hdr(orig, "Message-ID")
    refs = (_hdr(orig, "References") + " " + in_reply_to).strip()

    lines = [f"From: {me}", f"To: {to}"]
    if reply_all:
        seen = {a.lower() for _, a in email.utils.getaddresses([to]) if a}
        if me:
            seen.add(me.lower())
        cc_addrs = []
        for _, a in email.utils.getaddresses([_hdr(orig, "To"), _hdr(orig, "Cc")]):
            if a and a.lower() not in seen:
                cc_addrs.append(a)
                seen.add(a.lower())
        if cc_addrs:
            lines.append("Cc: " + ", ".join(cc_addrs))
    lines.append(f"Subject: {subject}")
    if in_reply_to:
        lines.append(f"In-Reply-To: {in_reply_to}")
    if refs:
        lines.append(f"References: {refs}")
    return "\n".join(lines) + "\n\n" + _quote_block(orig)


async def reply_template(account: str, msg_id: str, reply_all: bool = False, folder: str = "INBOX"):
    return await asyncio.to_thread(
        pool.run, account, lambda c: _reply(c, account, msg_id, reply_all, folder)
    )


def _forward(conn, msg_id: str, folder: str) -> str:
    _select(conn, folder, True)
    orig = email.message_from_bytes(_fetch_raw(conn, msg_id), policy=email.policy.default)
    subject = _hdr(orig, "Subject")
    low = subject.lower()
    if not low.startswith("fwd:") and not low.startswith("fw:"):
        subject = "Fwd: " + subject
    fwd_head = (
        "---------- Forwarded message ----------\n"
        f"From: {_hdr(orig, 'From')}\n"
        f"Date: {_hdr(orig, 'Date')}\n"
        f"Subject: {_hdr(orig, 'Subject')}\n"
        f"To: {_hdr(orig, 'To')}\n"
    )
    return f"Subject: {subject}\n\n{fwd_head}\n{_text_body(orig)}"


async def forward_template(account: str, msg_id: str, folder: str = "INBOX"):
    return await asyncio.to_thread(pool.run, account, lambda c: _forward(c, msg_id, folder))
