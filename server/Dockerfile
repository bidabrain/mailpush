# syntax=docker/dockerfile:1
#
# mailpush 服务端镜像(多阶段)
#   stage gobuild  : 编 goimapnotify(监听:纯 RFC2177 IDLE,兼容 Gmail,无 QRESYNC)
#   stage runtime  : python + FastAPI,收/读/发全部走 Python(imaplib 连接池 + smtplib)
#
# 引擎演进:原本用 himalaya(Rust CLI)做收信引擎,已替换为 app/imap_pool.py + imap_client.py
# (标准库 imaplib 持久连接池)。好处:复用连接,免去对做反向 DNS 的邮箱每次新连接等数十秒;代码层发 IMAP ID 解锁
# 网易 163/126 读信(himalaya v1.2.0 不支持,issue #656);去掉 Rust 编译,build ~20min → ~1min。
# 详见仓库根 imap-pool-design.md 与 PROJECT-MEMORY.md。
#
# 为什么是 goimapnotify 而不是 mirador:Pimalaya 的 watch 件 mirador 硬要求 IMAP QRESYNC,
# 而 Gmail 不支持 QRESYNC → 监听不了 Gmail。goimapnotify 走纯 IDLE,成熟且明确兼容 Gmail。
#
# 版本锁定:goimapnotify 无 semver tag,锁伪版本(含 commit)。

# ---------- stage: build goimapnotify (Go) ----------
FROM golang:1-bookworm AS gobuild
ARG GOIMAPNOTIFY_VERSION=v0.0.0-20260609005658-058f06d033c3
# 主包在模块的 cmd/goimapnotify 子目录(模块根没有 package main)。
RUN go install gitlab.com/shackra/goimapnotify/cmd/goimapnotify@${GOIMAPNOTIFY_VERSION}
# 二进制落在 /go/bin/goimapnotify

# ---------- stage: python runtime ----------
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=gobuild /go/bin/goimapnotify /usr/local/bin/goimapnotify

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY app/ /app/
RUN chmod +x /app/watch-entrypoint.sh /app/push-fcm.py

# 版本号:由构建命令从仓库根的 VERSION 文件读入(--build-arg APP_VERSION=$(cat ../VERSION))。
ARG APP_VERSION=dev
ENV MAILPUSH_VERSION=${APP_VERSION}

# config.toml(账号/收发) + goimapnotify 配置;可写状态(cache / last-seen)落在 /data。
ENV CONFIG_PATH=/config/config.toml \
    IMAPNOTIFY_CONFIG=/config/imapnotify.yaml \
    XDG_DATA_HOME=/data \
    XDG_CACHE_HOME=/data/cache \
    XDG_STATE_HOME=/data/state \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 默认跑 API;mail-watch 在 compose 里用 command 覆盖成 watch-entrypoint.sh
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8099"]
