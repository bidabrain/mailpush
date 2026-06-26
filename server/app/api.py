"""mail-api —— 手机端调用的薄 HTTP API(FastAPI)。

收/读走 imap_client(imaplib 持久连接池),发信走 mailsend(smtplib)。

鉴权:所有业务端点要求 `Authorization: Bearer <api-token 文件内容>`。
暴露:务必放在 Cloudflare Tunnel + Access 后,严禁裸暴露公网
      (它能读全部邮件 + 以你名义发信)。

端点:
    GET    /healthz           无需鉴权,存活探针
    GET    /accounts          读 config.toml 里的账号名列表
    GET    /inbox             列表(imap_client.list_envelopes)
    GET    /folders           文件夹名 + 探测到的「已发」
    GET    /msg/{id}          导出 .eml 解析正文(默认不标已读)
    DELETE /msg/{id}          删除(移到回收站)
    POST   /send              拼 MIME → smtplib 发送
    POST   /reply/{id}        回复模板 → 拼 MIME → smtplib
    POST   /forward/{id}      转发模板(带原附件)→ smtplib
"""
from __future__ import annotations

import email
import email.policy
import email.utils
import mimetypes
import os
import shutil
import tempfile
import time
import tomllib
from email.message import EmailMessage
from functools import lru_cache

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import hmac

import accounts as account_store  # 别名:避免与下方 @app.get("/accounts") 的 def accounts 撞名遮蔽
import apptokens
import devicetokens
import imap_client
import mailsend
from models import OkResponse, TokenRegister

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/config/config.toml")
API_TOKEN_FILE = os.environ.get("API_TOKEN_FILE", "/config/api-token")
ATTACH_DIR = os.environ.get("ATTACH_DIR", "/data/attachments")
ATTACH_TTL_DAYS = float(os.environ.get("ATTACH_TTL_DAYS", "7"))  # 附件缓存保留天数
# 版本号:Dockerfile 由仓库根 VERSION 文件经 build-arg 注入 MAILPUSH_VERSION。
VERSION = os.environ.get("MAILPUSH_VERSION", "dev")

# 默认关闭自动文档(/docs、/redoc、/openapi.json),避免接口结构对公网泄露。
# 本地调试想用时,设环境变量 MAILPUSH_ENABLE_DOCS=1 再启动即可。
_enable_docs = os.environ.get("MAILPUSH_ENABLE_DOCS", "").lower() in ("1", "true", "yes")
app = FastAPI(
    title="mailpush API",
    version=VERSION,
    docs_url="/docs" if _enable_docs else None,
    redoc_url="/redoc" if _enable_docs else None,
    openapi_url="/openapi.json" if _enable_docs else None,
)
_bearer = HTTPBearer(auto_error=True)


@lru_cache(maxsize=1)
def _legacy_token() -> str | None:
    """旧的单 token 文件 /config/api-token(可选;没有就返回 None)。
    新方式是 mail-admin 后台管理的多 token(apptokens,存 /data)。"""
    try:
        with open(API_TOKEN_FILE, encoding="utf-8") as f:
            token = f.read().strip()
    except OSError:
        return None
    return token or None


LEGACY_TOKEN_ID = "legacy"


def require_auth(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    """校验 bearer token;返回命中的 app-token id(旧单 token 返回 "legacy")。
    用作 dependencies=[] 时返回值被忽略;/register-token 用它的返回值记设备归属。"""
    tok = creds.credentials
    tid = apptokens.match(tok)
    if tid:
        return tid
    legacy = _legacy_token()
    if legacy and hmac.compare_digest(tok, legacy):
        return LEGACY_TOKEN_ID
    raise HTTPException(status_code=401, detail="invalid token")


def _load_accounts() -> list[str]:
    try:
        with open(CONFIG_PATH, "rb") as f:
            cfg = tomllib.load(f)
    except OSError:
        cfg = {}  # 没有 config.toml 也行:账户可能全由 webui(/data/accounts.json)管理
    cfg = account_store.overlay_config(cfg)  # 叠加 webui 账户
    return list(cfg.get("accounts", {}).keys())


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "version": VERSION}


@app.get("/version")
async def version() -> dict:
    """服务端版本号(供 app 设置页显示)。无需鉴权。"""
    return {"version": VERSION}


@app.get("/accounts", dependencies=[Depends(require_auth)])
async def accounts() -> dict:
    return {"accounts": _load_accounts()}


@app.post("/register-token")
async def register_token(req: TokenRegister, token_id: str = Depends(require_auth)) -> dict:
    """安卓端自动上报本机 FCM token(多设备)。写入 /data(/config 是只读挂载)。
    记录该设备归属于当前 app-token(token_id),后台删 token 时连带删它的推送设备。"""
    token = req.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="empty token")
    added = devicetokens.add(token, token_id)
    return {"ok": True, "added": added, "count": len(devicetokens.load())}


@app.get("/inbox", dependencies=[Depends(require_auth)])
async def inbox(
    account: str,
    folder: str = "INBOX",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    try:
        return await imap_client.list_envelopes(account, folder, page, page_size)
    except imap_client.ImapError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# 「已发」文件夹各家叫法不同;按常见名探测。优先精确匹配,再退化为含 sent/已发 的。
_SENT_PREFERRED = [
    "[Gmail]/Sent Mail", "Sent", "Sent Items", "Sent Messages", "Sent Mail",
    "INBOX.Sent", "已发送", "已发邮件", "已发送邮件",
]


def _detect_sent(names: list[str]) -> str | None:
    lower = {n.lower(): n for n in names}
    for p in _SENT_PREFERRED:
        if p.lower() in lower:
            return lower[p.lower()]
    for n in names:
        if "sent" in n.lower() or "已发" in n:
            return n
    return None


@app.get("/unread", dependencies=[Depends(require_auth)])
async def unread(account: str, folder: str = "INBOX") -> dict:
    """单账户某文件夹未读数(IMAP SEARCH UNSEEN)。"""
    try:
        n = await imap_client.unread_count(account, folder)
    except imap_client.ImapError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"account": account, "unread": n}


@app.get("/unread-all", dependencies=[Depends(require_auth)])
async def unread_all() -> dict:
    """各账户 INBOX 未读数 + 总数(供统一收件箱总未读、账户列表各自未读)。
    某账户取不到则该项为 null,不计入 total,不影响其他账户。"""
    counts: dict[str, int | None] = {}
    total = 0
    for acc in _load_accounts():
        try:
            n = await imap_client.unread_count(acc, "INBOX")
            counts[acc] = n
            total += n
        except Exception:  # noqa: BLE001 — 单账户失败不拖累整体
            counts[acc] = None
    return {"counts": counts, "total": total}


@app.get("/folders", dependencies=[Depends(require_auth)])
async def folders(account: str) -> dict:
    """列出文件夹名,并给出探测到的「已发」文件夹(供 app 显示已发件箱)。"""
    try:
        raw = await imap_client.list_folders(account)
    except imap_client.ImapError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    names: list[str] = []
    for f in raw or []:
        if isinstance(f, str):
            names.append(f)
        elif isinstance(f, dict):
            n = f.get("name") or f.get("Name")
            if n:
                names.append(n)
    return {"folders": names, "sent": _detect_sent(names)}


def _extract_bodies(raw: bytes) -> tuple[str, str]:
    """从原始 MIME 取 (html, text) 正文。优先 text/html;跳过附件部分。"""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    html = ""
    text = ""
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.is_multipart():
            continue
        if (part.get_content_disposition() or "") == "attachment":
            continue
        ctype = part.get_content_type()
        if ctype not in ("text/html", "text/plain"):
            continue
        try:
            content = part.get_content()
        except Exception:  # noqa: BLE001
            continue
        if ctype == "text/html" and not html:
            html = content
        elif ctype == "text/plain" and not text:
            text = content
    return html, text


@app.get("/msg/{msg_id}", dependencies=[Depends(require_auth)])
async def read_msg(
    msg_id: str,
    account: str,
    folder: str = "INBOX",
    mark_read: bool = Query(False, description="True 则标记已读"),
) -> dict:
    """导出原始邮件解析出 HTML/纯文本正文,返回 {html, text}。"""
    workdir = tempfile.mkdtemp(prefix="msg-")
    try:
        try:
            await imap_client.export_full(account, msg_id, workdir, folder)
        except imap_client.ImapError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        files = [os.path.join(workdir, f) for f in os.listdir(workdir)
                 if os.path.isfile(os.path.join(workdir, f))]
        eml = next((f for f in files if f.endswith(".eml")), files[0] if files else None)
        if not eml:
            raise HTTPException(status_code=502, detail="导出邮件失败(无文件)")
        with open(eml, "rb") as f:
            raw = f.read()
        html, text = _extract_bodies(raw)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if mark_read:
        try:
            await imap_client.add_flag(account, msg_id, "seen", folder)
        except imap_client.ImapError:
            pass  # 标已读失败不影响读信

    return {"html": html, "text": text}


@app.delete("/msg/{msg_id}", dependencies=[Depends(require_auth)])
async def delete_msg(msg_id: str, account: str, folder: str = "INBOX") -> dict:
    """删除邮件(移到回收站)。"""
    try:
        await imap_client.delete_message(account, msg_id, folder)
    except imap_client.ImapError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"ok": True}


def _split_addrs(s: str) -> list[str]:
    return [x.strip() for x in s.replace(";", ",").split(",") if x.strip()]


def _parse_headers(head: str) -> dict:
    """解析 himalaya 回复模板的头部块(每行 Key: value)。"""
    out: dict[str, str] = {}
    for line in head.splitlines():
        if ":" in line and not line[:1].isspace():
            key, _, value = line.partition(":")
            out[key.strip().lower()] = value.strip()
    return out


def _addr_list(s: str) -> list[str]:
    return [addr for _, addr in email.utils.getaddresses([s]) if addr]


def _account_email(account: str) -> str | None:
    """从 config.toml 取账号的发件地址(himalaya v1 的 email 字段;退回 backend.login)。"""
    try:
        with open(CONFIG_PATH, "rb") as f:
            cfg = tomllib.load(f)
    except OSError:
        cfg = {}
    cfg = account_store.overlay_config(cfg)  # 叠加 webui 账户
    acc = cfg.get("accounts", {}).get(account, {})
    return acc.get("email") or acc.get("backend", {}).get("login")


def _build_eml(from_addr, to, cc, subject, body, html, attachments, extra_headers=None) -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    # Bcc 不写进邮件头(只作信封收件人);其他线程头(In-Reply-To/References)走 extra_headers。
    for key, value in (extra_headers or {}).items():
        if value:
            msg[key] = value
    if html:
        msg.set_content("(此客户端需 HTML 渲染)")
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(body)
    for filename, data, ctype in attachments:
        maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
        msg.add_attachment(
            data,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=filename or "attachment",
        )
    return msg.as_bytes()


@app.post("/send", dependencies=[Depends(require_auth)], response_model=OkResponse)
async def send(
    account: str = Form(...),
    to: str = Form(...),
    subject: str = Form(""),
    body: str = Form(""),
    cc: str = Form(""),
    bcc: str = Form(""),
    html: bool = Form(False),
    files: list[UploadFile] = File(default=[]),
) -> OkResponse:
    """multipart/form-data:文字字段 + 可选附件文件(字段名 files,可多个)。"""
    to_list = _split_addrs(to)
    if not to_list:
        raise HTTPException(status_code=400, detail="收件人不能为空")
    from_addr = _account_email(account)
    if not from_addr:
        raise HTTPException(status_code=400, detail=f"账号 {account} 在 config.toml 缺少 email/login,无法确定发件人")
    cc_list = _split_addrs(cc)
    bcc_list = _split_addrs(bcc)
    attachments = [(f.filename, await f.read(), f.content_type) for f in files]
    eml = _build_eml(from_addr, to_list, cc_list, subject, body, html, attachments)
    try:
        mailsend.send(account, to_list + cc_list + bcc_list, eml)  # smtplib,不碰 IMAP
    except mailsend.SmtpError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return OkResponse(detail="sent")


def _prune_attachments() -> None:
    """删除超过 ATTACH_TTL_DAYS 没动过的附件缓存目录(防 /data 无限增长)。"""
    if ATTACH_TTL_DAYS <= 0 or not os.path.isdir(ATTACH_DIR):
        return
    cutoff = time.time() - ATTACH_TTL_DAYS * 86400
    for account in os.listdir(ATTACH_DIR):
        apath = os.path.join(ATTACH_DIR, account)
        if not os.path.isdir(apath):
            continue
        for folder in os.listdir(apath):
            fpath = os.path.join(apath, folder)
            if not os.path.isdir(fpath):
                continue
            for mid in os.listdir(fpath):
                d = os.path.join(fpath, mid)
                try:
                    if os.path.isdir(d) and os.path.getmtime(d) < cutoff:
                        shutil.rmtree(d, ignore_errors=True)
                except OSError:
                    pass


async def _ensure_attachments(account: str, folder: str, msg_id: str) -> str:
    """把某封邮件的附件下到 /data 缓存(已下过就复用),返回目录。"""
    _prune_attachments()  # 顺手清理过期缓存
    dest = os.path.join(ATTACH_DIR, account, folder, str(msg_id))
    if os.path.isdir(dest) and os.listdir(dest):
        return dest
    os.makedirs(dest, exist_ok=True)
    await imap_client.download_attachments(account, msg_id, dest, folder)
    return dest


@app.get("/attachments/{msg_id}", dependencies=[Depends(require_auth)])
async def list_attachments(msg_id: str, account: str, folder: str = "INBOX") -> dict:
    try:
        dest = await _ensure_attachments(account, folder, msg_id)
    except imap_client.ImapError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    items = [
        {"name": name, "size": os.path.getsize(os.path.join(dest, name))}
        for name in sorted(os.listdir(dest))
        if os.path.isfile(os.path.join(dest, name))
    ]
    return {"attachments": items}


@app.get("/attachment/{msg_id}", dependencies=[Depends(require_auth)])
async def get_attachment(msg_id: str, account: str, name: str, folder: str = "INBOX"):
    safe = os.path.basename(name)  # 防路径穿越
    try:
        dest = await _ensure_attachments(account, folder, msg_id)
    except imap_client.ImapError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    path = os.path.join(dest, safe)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="attachment not found")
    return FileResponse(path, filename=safe)


@app.post("/reply/{msg_id}", dependencies=[Depends(require_auth)], response_model=OkResponse)
async def reply(
    msg_id: str,
    account: str = Form(...),
    body: str = Form(""),
    reply_all: bool = Form(False),
    folder: str = Form("INBOX"),
    files: list[UploadFile] = File(default=[]),
) -> OkResponse:
    """回复(multipart):用 himalaya 回复模板拿到收件人/主题/引用/In-Reply-To,
    自己拼 MIME,经 smtplib 发送(不走 himalaya 发送,避免 IMAP APPEND 问题)。"""
    try:
        template = await imap_client.reply_template(account, msg_id, reply_all, folder)
    except imap_client.ImapError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    head, _, quoted = template.partition("\n\n")
    headers = _parse_headers(head)
    to_list = _addr_list(headers.get("to", ""))
    cc_list = _addr_list(headers.get("cc", ""))
    if not to_list:
        raise HTTPException(status_code=502, detail="无法从回复模板解析收件人")

    in_reply_to = headers.get("in-reply-to")
    extra = {
        "In-Reply-To": in_reply_to,
        "References": headers.get("references") or in_reply_to,  # 保线程
    }
    from_addr = headers.get("from") or _account_email(account)
    full_body = f"{body}\n\n{quoted.lstrip()}" if quoted.strip() else body
    attachments = [(f.filename, await f.read(), f.content_type) for f in files]
    eml = _build_eml(from_addr, to_list, cc_list, headers.get("subject", ""), full_body, False, attachments, extra)
    try:
        mailsend.send(account, to_list + cc_list, eml)
    except mailsend.SmtpError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return OkResponse(detail="sent")


@app.post("/forward/{msg_id}", dependencies=[Depends(require_auth)], response_model=OkResponse)
async def forward(
    msg_id: str,
    account: str = Form(...),
    to: str = Form(...),
    body: str = Form(""),
    folder: str = Form("INBOX"),
    files: list[UploadFile] = File(default=[]),
) -> OkResponse:
    """转发(multipart):himalaya 生成转发模板(Fwd: 主题 + 引用原文),收件人由用户指定;
    自动带上原邮件的附件;经 smtplib 发送。"""
    to_list = _split_addrs(to)
    if not to_list:
        raise HTTPException(status_code=400, detail="收件人不能为空")
    from_addr = _account_email(account)
    if not from_addr:
        raise HTTPException(status_code=400, detail=f"账号 {account} 在 config.toml 缺少 email/login")
    try:
        template = await imap_client.forward_template(account, msg_id, folder)
    except imap_client.ImapError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    head, _, quoted = template.partition("\n\n")
    subject = _parse_headers(head).get("subject", "")
    full_body = f"{body}\n\n{quoted.lstrip()}" if quoted.strip() else body

    # 附件 = 用户新加的 + 原邮件的(转发应带上原附件)
    attachments = [(f.filename, await f.read(), f.content_type) for f in files]
    try:
        dest = await _ensure_attachments(account, folder, msg_id)
        for name in sorted(os.listdir(dest)):
            path = os.path.join(dest, name)
            if os.path.isfile(path):
                ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
                with open(path, "rb") as fh:
                    attachments.append((name, fh.read(), ctype))
    except imap_client.ImapError:
        pass  # 原附件取不到就只转发正文,不阻断

    eml = _build_eml(from_addr, to_list, [], subject, full_body, False, attachments)
    try:
        mailsend.send(account, to_list, eml)
    except mailsend.SmtpError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return OkResponse(detail="sent")
