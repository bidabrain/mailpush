#!/bin/sh
# mail-watch 容器入口:跑 goimapnotify(IMAP IDLE 监听),崩溃自动重启。
# goimapnotify 自身支持单配置文件多账号(configurations 数组),每个账号/文件夹的
# onNewMail 触发 push-fcm.py;账号名写死在配置的 onNewMail 命令参数里(goimapnotify
# 不向钩子传 sender/subject,push-fcm.py 再用 imap_client 抓最新一封补全)。
set -eu

IMAPNOTIFY_CONFIG="${IMAPNOTIFY_CONFIG:-/config/imapnotify.yaml}"

if [ ! -f "$IMAPNOTIFY_CONFIG" ]; then
    echo "[watch] FATAL: 找不到 goimapnotify 配置 $IMAPNOTIFY_CONFIG(请把 imapnotify.yaml 挂到 /config)" >&2
    exit 1
fi

while true; do
    echo "[watch] 启动 goimapnotify -conf $IMAPNOTIFY_CONFIG"
    goimapnotify -conf "$IMAPNOTIFY_CONFIG" || true
    echo "[watch] goimapnotify 退出,5s 后重启" >&2
    sleep 5
done
