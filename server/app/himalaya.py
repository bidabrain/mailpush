"""himalaya CLI 的 subprocess 封装(方案A 的引擎层)。

所有调用统一 `himalaya -c $CONFIG_PATH ...`,需要结构化结果时加 `-o json`。
每次调用开一个新 himalaya 进程(默认无会话常驻,Gmail 每次握手 ~1s);
个人用足够,嫌慢以后接 sirup 复用会话即可。

⚠️ himalaya flag 随版本变。本文件基于 himalaya v1.2.0 核对:
    envelope list   : folder 是【位置参数】,账号 -a,分页 -p/--page、-s/--page-size
    message read    : id 位置参数,账号 -a,--preview(读取但【不标已读】)
    message send    : 从 stdin 读原始邮件,账号 -a(v1.2.0 发信后【无条件存 Sent】)
    template reply  : 见 reply_template();flag 需构建后再核对(见 README VERIFY)
升级 himalaya 后,用 `himalaya <子命令> --help` 复核。
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/config/config.toml")
HIMALAYA_BIN = os.environ.get("HIMALAYA_BIN", "himalaya")
TIMEOUT = float(os.environ.get("HIMALAYA_TIMEOUT", "30"))


class HimalayaError(RuntimeError):
    def __init__(self, args: list[str], returncode: int, stderr: str) -> None:
        self.args = args
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(
            f"himalaya {' '.join(args)} 失败(code={returncode}): {self.stderr}"
        )


async def _run(
    args: list[str],
    *,
    input_bytes: bytes | None = None,
    json_output: bool = True,
) -> Any:
    """执行 himalaya;json_output=True 时解析 -o json,否则返回 stdout 文本。"""
    cmd = [HIMALAYA_BIN, "-c", CONFIG_PATH, *args]
    if json_output:
        cmd += ["-o", "json"]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if input_bytes is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(input=input_bytes), timeout=TIMEOUT
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise HimalayaError(args, -1, f"超时(>{TIMEOUT}s)")

    if proc.returncode != 0:
        raise HimalayaError(args, proc.returncode or -1, err.decode(errors="replace"))

    if not json_output:
        return out.decode(errors="replace")

    text = out.decode(errors="replace").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise HimalayaError(args, 0, f"JSON 解析失败:{exc};原始输出:{text[:500]}")


# ---------- 端点用到的高层封装 ----------

async def list_envelopes(
    account: str, folder: str = "INBOX", page: int = 1, page_size: int = 50
) -> Any:
    """收件列表。folder 用 -f flag(v1.2.0 的位置参数是搜索 query,不是 folder)。"""
    return await _run(
        [
            "envelope", "list",
            "-a", account,
            "-f", folder,
            "-p", str(page),
            "-s", str(page_size),
        ]
    )


async def read_message(account: str, msg_id: str, preview: bool = True) -> Any:
    """读正文。preview=True 用 --preview 读取但不标已读(默认非破坏性,设计坑#7)。"""
    args = ["message", "read", "-a", account]
    if preview:
        args.append("--preview")
    args.append(str(msg_id))
    return await _run(args)


async def send_raw(account: str, raw_eml: bytes) -> str:
    """发送一封原始 RFC822 邮件(从 stdin 喂给 himalaya)。v1.2.0 会自动存 Sent。"""
    return await _run(
        ["message", "send", "-a", account],
        input_bytes=raw_eml,
        json_output=False,
    )


async def reply_template(
    account: str, msg_id: str, reply_all: bool = False, folder: str = "INBOX"
) -> str:
    """生成回复模板(含正确的 In-Reply-To/References/Re:/引用原文)。

    ⚠️ VERIFY:template reply 的 flag 需构建后核对:
        docker run --rm mailpush:latest himalaya template reply --help
    这里取纯文本模板(不加 -o json),便于把用户正文拼进去后再 template send。
    """
    args = ["template", "reply", "-a", account, "-f", folder]
    if reply_all:
        args.append("--all")  # ⚠️ VERIFY:reply-all 短/长 flag
    args.append(str(msg_id))
    return await _run(args, json_output=False)


async def list_folders(account: str) -> Any:
    """列出账号的所有文件夹(folder list -o json)。用于探测「已发」等特殊文件夹名。"""
    return await _run(["folder", "list", "-a", account])


async def export_full(account: str, msg_id: str, dest_dir: str, folder: str = "INBOX") -> str:
    """把整封原始邮件(.eml)导出到 dest_dir,用于解析 HTML 正文。"""
    return await _run(
        ["message", "export", "-F", "-a", account, "-f", folder, "-d", dest_dir, str(msg_id)],
        json_output=False,
    )


async def add_flag(account: str, msg_id: str, flag: str, folder: str = "INBOX") -> str:
    """给邮件加标记(如 seen 标已读)。flag add 的位置参数 id 与 flag 混排。"""
    return await _run(
        ["flag", "add", "-a", account, "-f", folder, str(msg_id), flag],
        json_output=False,
    )


async def forward_template(account: str, msg_id: str, folder: str = "INBOX") -> str:
    """生成转发模板(Fwd: 主题 + 引用原文;收件人由调用方另填)。"""
    return await _run(
        ["template", "forward", "-a", account, "-f", folder, str(msg_id)],
        json_output=False,
    )


async def delete_message(account: str, msg_id: str, folder: str = "INBOX") -> str:
    """删除(移到回收站;若 folder 已是回收站则打 deleted 标记)。"""
    return await _run(
        ["message", "delete", "-a", account, "-f", folder, str(msg_id)],
        json_output=False,
    )


async def download_attachments(account: str, msg_id: str, dest_dir: str, folder: str = "INBOX") -> str:
    """把某封邮件的全部附件下载到 dest_dir(himalaya 只支持整封下载)。"""
    return await _run(
        ["attachment", "download", "-a", account, "-f", folder, "-d", dest_dir, str(msg_id)],
        json_output=False,
    )


async def send_template(account: str, template: str) -> str:
    """把(填好正文的)模板编译成 MIME 并发送。

    ⚠️ VERIFY:template send 是否从 stdin 读模板:
        docker run --rm mailpush:latest himalaya template send --help
    """
    return await _run(
        ["template", "send", "-a", account],
        input_bytes=template.encode("utf-8"),
        json_output=False,
    )
