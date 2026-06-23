"""mailpush 管理后台(mail-admin)—— 仅内网访问的图形化管理页。

⚠️ 安全:只在内网开放(compose 映射 8098,但【不要】经 Cloudflare/路由器把它暴露公网)。
用一个管理密码登录(默认 /config/secrets/admin.pass);会话用随机 cookie(内存态,重启需重登)。

功能:看版本/运行状态、管理安卓端 app token(新建/删除,免去手翻 config 文件)。
"""
from __future__ import annotations

import html
import hmac
import os
import secrets
import tomllib
import urllib.request

from fastapi import Cookie, FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

import apptokens
import devicetokens

try:
    import oauth  # 需要 msal;未装则后台隐藏 OAuth 区(不影响其他功能)
except Exception:  # noqa: BLE001
    oauth = None

VERSION = os.environ.get("MAILPUSH_VERSION", "dev")
ADMIN_PASS_FILE = os.environ.get("ADMIN_PASSWORD_FILE", "/config/secrets/admin.pass")
CONFIG_PATH = os.environ.get("CONFIG_PATH", "/config/config.toml")
API_HEALTH_URL = os.environ.get("API_HEALTH_URL", "http://mail-api:8099/healthz")
COOKIE = "mailadmin_session"

app = FastAPI(title="mailpush admin", docs_url=None, redoc_url=None, openapi_url=None)
_sessions: set[str] = set()


# ---------- 鉴权 ----------

def _admin_password() -> str | None:
    try:
        with open(ADMIN_PASS_FILE, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _authed(session: str | None) -> bool:
    return bool(session) and session in _sessions


# ---------- 数据 ----------

def _accounts() -> list[str]:
    try:
        with open(CONFIG_PATH, "rb") as f:
            return list(tomllib.load(f).get("accounts", {}).keys())
    except (OSError, tomllib.TOMLDecodeError):
        return []


def _api_health() -> str:
    try:
        with urllib.request.urlopen(API_HEALTH_URL, timeout=2) as r:
            return "运行中" if r.status == 200 else f"异常({r.status})"
    except Exception:  # noqa: BLE001
        return "连不上(mail-api 未运行?)"


# ---------- 页面 ----------

_STYLE = """
<style>
 body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:760px;margin:32px auto;padding:0 16px;color:#1a1a1a}
 h1{font-size:22px} h2{font-size:16px;margin-top:28px;border-bottom:1px solid #eee;padding-bottom:6px}
 .card{background:#f7f8fa;border-radius:12px;padding:16px;margin:12px 0}
 code{background:#eef;padding:2px 6px;border-radius:4px;font-size:13px;word-break:break-all}
 input[type=text],input[type=password]{padding:8px;border:1px solid #ccc;border-radius:8px;font-size:14px}
 button{padding:8px 14px;border:0;border-radius:8px;background:#3b6ef5;color:#fff;font-size:14px;cursor:pointer}
 button.danger{background:#e5484d}
 table{width:100%;border-collapse:collapse} td{padding:8px 6px;border-bottom:1px solid #eee;vertical-align:top;font-size:14px}
 .muted{color:#888;font-size:13px} .err{color:#e5484d}
 a{color:#3b6ef5;text-decoration:none}
</style>
"""


def _page(body: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><html><head><meta charset=utf-8>"
                        f"<meta name=viewport content='width=device-width,initial-scale=1'>"
                        f"<title>mailpush 管理</title>{_STYLE}</head><body>{body}</body></html>")


def _login_page(err: str) -> HTMLResponse:
    msg = ""
    if err == "bad":
        msg = "<p class=err>密码错误</p>"
    elif err == "nopass":
        msg = ("<p class=err>未设置管理密码。请在服务器创建 "
               f"<code>{html.escape(ADMIN_PASS_FILE)}</code> 并写入密码后重试。</p>")
    return _page(
        f"<h1>mailpush 管理后台</h1>{msg}"
        "<form method=post action=/login class=card>"
        "<input type=password name=password placeholder=管理密码 autofocus> "
        "<button type=submit>登录</button></form>"
        "<p class=muted>仅供内网管理使用,请勿将本端口暴露公网。</p>"
    )


def _mask(tok: str) -> str:
    return tok if len(tok) <= 22 else f"{tok[:12]}…{tok[-6:]}"


def _dashboard() -> HTMLResponse:
    accs = _accounts()
    toks = apptokens.load()
    devs = devicetokens.load_records()

    by_owner: dict = {}
    for d in devs:
        by_owner[d.get("app_token_id")] = by_owner.get(d.get("app_token_id"), 0) + 1
    label_of = {t.get("id"): t.get("label", "") for t in toks}

    # ---- token 表(含名下设备数)----
    trows = ""
    for t in toks:
        n = by_owner.get(t.get("id"), 0)
        trows += (
            "<tr>"
            f"<td>{html.escape(str(t.get('label','')))}</td>"
            f"<td><code>{html.escape(str(t.get('token','')))}</code><br>"
            f"<span class=muted>{html.escape(str(t.get('created','')))} · 推送设备 {n}</span></td>"
            f"<td><form method=post action=/tokens/delete "
            f"onsubmit=\"return confirm('删除此 token 及其 {n} 台推送设备?该设备将无法连接、也收不到推送')\">"
            f"<input type=hidden name=id value='{html.escape(str(t.get('id','')))}'>"
            f"<button class=danger type=submit>删除</button></form></td>"
            "</tr>"
        )
    if not trows:
        trows = "<tr><td colspan=3 class=muted>还没有 token,在下面新建一个。</td></tr>"

    # ---- 推送设备表(按归属 token)----
    drows = ""
    for d in devs:
        owner = d.get("app_token_id")
        oname = (label_of.get(owner)
                 or ("(未关联·旧)" if owner is None else f"(已删 token {owner})"))
        drows += (
            "<tr>"
            f"<td>{html.escape(str(oname))}</td>"
            f"<td><span class=muted>{html.escape(_mask(str(d.get('token',''))))}</span><br>"
            f"<span class=muted>{html.escape(str(d.get('created','') or ''))}</span></td>"
            f"<td><form method=post action=/devices/delete "
            f"onsubmit=\"return confirm('删除此推送设备?它将不再收到推送')\">"
            f"<input type=hidden name=token value='{html.escape(str(d.get('token','')))}'>"
            f"<button class=danger type=submit>删除</button></form></td>"
            "</tr>"
        )
    if not drows:
        drows = "<tr><td colspan=3 class=muted>暂无已注册推送设备。</td></tr>"

    # ---- OAuth(Outlook 等)----
    oauth_html = ""
    if oauth is not None:
        orows = ""
        for a in oauth.list_accounts():
            cid = a["client_id"]
            cidmask = cid if len(cid) <= 12 else f"{cid[:8]}…{cid[-4:]}"
            st = "已授权 ✅" if a["enrolled"] else "未授权"
            orows += (
                "<tr>"
                f"<td>{html.escape(a['account'])}</td>"
                f"<td><span class=muted>{html.escape(cidmask)}</span><br><span class=muted>{st}</span></td>"
                "<td>"
                "<form method=post action=/oauth/enroll style=display:inline>"
                f"<input type=hidden name=account value='{html.escape(a['account'])}'>"
                "<button type=submit>授权</button></form> "
                "<form method=post action=/oauth/delete style=display:inline "
                "onsubmit=\"return confirm('删除此 OAuth 账号配置?')\">"
                f"<input type=hidden name=account value='{html.escape(a['account'])}'>"
                "<button class=danger type=submit>删除</button></form>"
                "</td></tr>"
            )
        if not orows:
            orows = "<tr><td colspan=3 class=muted>还没有 OAuth 账号。下面填 client_id 添加。</td></tr>"
        oauth_html = (
            "<h2>OAuth(Outlook 等)</h2>"
            "<div class=card><table>"
            "<tr><td><b>账号</b></td><td><b>client_id / 状态</b></td><td></td></tr>"
            f"{orows}</table></div>"
            "<form method=post action=/oauth/save class=card>"
            "<input type=text name=account placeholder='账号名(同 config.toml,如 outlook)'> "
            "<input type=text name=client_id placeholder='Azure Application (client) ID' style=min-width:260px> "
            "<button type=submit>保存</button>"
            "<div class=muted style=margin-top:8px>保存后点该账号「授权」→ 按提示在浏览器登录同意。"
            "仍需在 config.toml / imapnotify.yaml 加该账号块(见 sample,auth.type=oauth2)。</div>"
            "</form>"
        )

    return _page(
        "<h1>mailpush 管理后台</h1>"
        "<p><a href=/logout>退出登录</a></p>"

        "<h2>状态</h2>"
        "<div class=card>"
        f"<div>服务端版本:<b>{html.escape(VERSION)}</b></div>"
        f"<div>mail-api:<b>{html.escape(_api_health())}</b></div>"
        f"<div>账户:{html.escape('、'.join(accs)) or '(无)'}</div>"
        f"<div>已注册推送设备:{len(devs)}</div>"
        "</div>"

        "<h2>App Token</h2>"
        "<div class=card><table>"
        "<tr><td><b>名称</b></td><td><b>Token / 创建 · 设备数</b></td><td></td></tr>"
        f"{trows}</table></div>"
        "<form method=post action=/tokens/new class=card>"
        "<input type=text name=label placeholder='名称(如:我的手机)'> "
        "<button type=submit>新建 Token</button>"
        "<div class=muted style=margin-top:8px>新建后把 Token 整串填进 app 的「API Token」。"
        "删除某 token 会连带删除它名下的推送设备(读信与推送一起断)。</div>"
        "</form>"

        "<h2>推送设备(FCM)</h2>"
        "<div class=card><table>"
        "<tr><td><b>归属 token</b></td><td><b>设备 / 注册时间</b></td><td></td></tr>"
        f"{drows}</table>"
        "<form method=post action=/devices/clear style=margin-top:10px "
        "onsubmit=\"return confirm('清空所有推送设备?有效设备下次打开 app 会自动重新注册')\">"
        "<button class=danger type=submit>清空所有推送设备</button></form>"
        "</div>"
        + oauth_html
    )


# ---------- 路由 ----------

@app.get("/", response_class=HTMLResponse)
def index(err: str = "", session: str | None = Cookie(default=None, alias=COOKIE)):
    if not _authed(session):
        return _login_page(err)
    return _dashboard()


@app.post("/login")
def login(password: str = Form("")):
    pw = _admin_password()
    if not pw:
        return RedirectResponse("/?err=nopass", status_code=303)
    if not hmac.compare_digest(password, pw):
        return RedirectResponse("/?err=bad", status_code=303)
    sid = secrets.token_hex(32)
    _sessions.add(sid)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(COOKIE, sid, httponly=True, samesite="lax", max_age=86400)
    return resp


@app.get("/logout")
def logout(session: str | None = Cookie(default=None, alias=COOKIE)):
    if session:
        _sessions.discard(session)
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


@app.post("/tokens/new")
def tokens_new(label: str = Form(""), session: str | None = Cookie(default=None, alias=COOKIE)):
    if not _authed(session):
        return RedirectResponse("/", status_code=303)
    apptokens.add(label)
    return RedirectResponse("/", status_code=303)


@app.post("/tokens/delete")
def tokens_delete(id: str = Form(""), session: str | None = Cookie(default=None, alias=COOKIE)):
    if not _authed(session):
        return RedirectResponse("/", status_code=303)
    apptokens.delete(id)
    devicetokens.remove_by_app_token(id)  # 连带删该 token 名下的推送设备(读信+推送一起断)
    return RedirectResponse("/", status_code=303)


@app.post("/devices/delete")
def devices_delete(token: str = Form(""), session: str | None = Cookie(default=None, alias=COOKIE)):
    if not _authed(session):
        return RedirectResponse("/", status_code=303)
    if token:
        devicetokens.remove([token])
    return RedirectResponse("/", status_code=303)


@app.post("/devices/clear")
def devices_clear(session: str | None = Cookie(default=None, alias=COOKIE)):
    if not _authed(session):
        return RedirectResponse("/", status_code=303)
    devicetokens.clear()
    return RedirectResponse("/", status_code=303)


# ---------- OAuth ----------

@app.post("/oauth/save")
def oauth_save(
    account: str = Form(""),
    client_id: str = Form(""),
    session: str | None = Cookie(default=None, alias=COOKIE),
):
    if not _authed(session):
        return RedirectResponse("/", status_code=303)
    if oauth is not None:
        try:
            oauth.save_config(account, client_id)
        except Exception:  # noqa: BLE001 — 输入不合法等,忽略后回首页
            pass
    return RedirectResponse("/", status_code=303)


@app.post("/oauth/delete")
def oauth_delete(account: str = Form(""), session: str | None = Cookie(default=None, alias=COOKIE)):
    if not _authed(session):
        return RedirectResponse("/", status_code=303)
    if oauth is not None and account:
        oauth.delete_account(account)
    return RedirectResponse("/", status_code=303)


@app.post("/oauth/enroll")
def oauth_enroll_start(account: str = Form(""), session: str | None = Cookie(default=None, alias=COOKIE)):
    if not _authed(session):
        return RedirectResponse("/", status_code=303)
    if oauth is not None and account:
        try:
            oauth.start_device_flow(account)
        except Exception as exc:  # noqa: BLE001
            oauth._set_flow(account, "error", str(exc))  # 让状态页显示原因
    return RedirectResponse(f"/oauth/enroll?account={account}", status_code=303)


@app.get("/oauth/enroll", response_class=HTMLResponse)
def oauth_enroll_status(account: str = "", session: str | None = Cookie(default=None, alias=COOKIE)):
    if not _authed(session):
        return _login_page("")
    st = oauth.flow_status(account) if oauth is not None else None
    if not st:
        return RedirectResponse("/", status_code=303)
    status = st.get("status")
    if status == "pending":
        body = (
            f"<h1>授权 {html.escape(account)}</h1>"
            "<div class=card>"
            f"<p>1. 浏览器打开:<a href='{html.escape(st['verification_uri'])}' target=_blank>{html.escape(st['verification_uri'])}</a></p>"
            f"<p>2. 输入代码:<code style=font-size:22px>{html.escape(st['user_code'])}</code></p>"
            "<p>3. 用要接入的 Outlook 账户登录并点「同意」。</p>"
            "<p class=muted>本页每 4 秒自动刷新检测结果…</p>"
            "</div>"
        )
        return HTMLResponse(
            "<!doctype html><html><head><meta charset=utf-8>"
            f"<meta http-equiv=refresh content='4; url=/oauth/enroll?account={html.escape(account)}'>"
            f"{_STYLE}</head><body>{body}</body></html>"
        )
    if status == "success":
        body = (
            f"<h1>✅ {html.escape(account)} 授权成功</h1>"
            "<div class=card>已拿到 refresh token。现在可在 config.toml 用 <code>auth.type=oauth2</code> 连这个账号。</div>"
            "<p><a href=/>返回</a></p>"
        )
    else:
        body = (
            "<h1>❌ 授权失败</h1>"
            f"<div class=card><span class=err>{html.escape(st.get('message', ''))}</span></div>"
            "<p><a href=/>返回</a> · 可重新点「授权」再试</p>"
        )
    return _page(body)
