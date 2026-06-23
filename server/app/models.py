"""API 请求/响应模型(Pydantic v2)。"""
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class SendRequest(BaseModel):
    account: str = Field(..., description="config.toml 里的账号名,如 gmail")
    to: list[EmailStr] = Field(..., min_length=1)
    subject: str = ""
    body: str = ""
    cc: list[EmailStr] = Field(default_factory=list)
    bcc: list[EmailStr] = Field(default_factory=list)
    html: bool = Field(False, description="body 是否按 text/html 发送")


class ReplyRequest(BaseModel):
    account: str
    body: str = Field(..., description="回复正文,会拼到引用原文之前")
    reply_all: bool = False


class OkResponse(BaseModel):
    ok: bool = True
    detail: str = ""


class TokenRegister(BaseModel):
    token: str
