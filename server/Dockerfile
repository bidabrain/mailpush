# syntax=docker/dockerfile:1
#
# mailpush 服务端镜像(多阶段)
#   stage rustbuild : 编 himalaya 1.2.0(引擎:envelope list / message read / template reply / send)
#   stage gobuild   : 编 goimapnotify(监听:纯 RFC2177 IDLE,兼容 Gmail,无 QRESYNC)
#   stage runtime   : python + FastAPI,拷入两个二进制
#
# 为什么是 goimapnotify 而不是 mirador:himalaya v1.x 移除了 envelope watch;Pimalaya 唯一的
# watch 件 mirador 硬要求 IMAP QRESYNC,而 Gmail 不支持 QRESYNC → mirador 监听不了 Gmail。
# goimapnotify 走纯 IDLE,成熟且明确兼容 Gmail。详见 PROJECT-MEMORY.md。
#
# 版本锁定:
#   - himalaya:git tag v1.2.0 + --locked(默认 features;裁剪会触发与 pimalaya-tui 不匹配的编译错误)
#   - goimapnotify:无 semver tag,锁伪版本(含 commit)

# ---------- stage: build himalaya (Rust) ----------
FROM rust:1-slim-bookworm AS rustbuild
ARG HIMALAYA_TAG=v1.2.0
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake pkg-config git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN cargo install --git https://github.com/pimalaya/himalaya --tag "${HIMALAYA_TAG}" --locked

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

COPY --from=rustbuild /usr/local/cargo/bin/himalaya /usr/local/bin/himalaya
COPY --from=gobuild   /go/bin/goimapnotify          /usr/local/bin/goimapnotify

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY app/ /app/
RUN chmod +x /app/watch-entrypoint.sh /app/push-fcm.py

# 版本号:由构建命令从仓库根的 VERSION 文件读入(--build-arg APP_VERSION=$(cat ../VERSION))。
ARG APP_VERSION=dev
ENV MAILPUSH_VERSION=${APP_VERSION}

# himalaya 配置 + goimapnotify 配置;可写状态(id-map / cache / last-seen)落在 /data。
ENV CONFIG_PATH=/config/config.toml \
    IMAPNOTIFY_CONFIG=/config/imapnotify.yaml \
    XDG_DATA_HOME=/data \
    XDG_CACHE_HOME=/data/cache \
    XDG_STATE_HOME=/data/state \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 默认跑 API;mail-watch 在 compose 里用 command 覆盖成 watch-entrypoint.sh
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8099"]
