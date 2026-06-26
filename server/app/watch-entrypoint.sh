#!/bin/sh
# mail-watch 容器入口:跑 goimapnotify(IMAP IDLE 监听),崩溃自动重启。
#
# 配置来源有两处,启动/重载时合并渲染成 GEN:
#   - base:/config/imapnotify.yaml(手写监听账户,只读,兼容旧部署)
#   - webui:/data/accounts.json(管理后台增删的账户,push=true 的会进来)
# goimapnotify 自身支持单文件多账号(configurations 数组),每个账号的 onNewMail 触发 push-fcm.py;
# 账号名写死在配置的 onNewMail 命令参数里(goimapnotify 不传 sender/subject,push-fcm.py 抓最新一封补全)。
#
# 全新部署(无任何账户)也能正常起:渲染出 0 个账户时【不启动】goimapnotify,空转等后台添加,
# 不会崩溃/busy-loop。热重载:后台改账户后 touch RELOAD_FLAG,本脚本检测到 mtime 变化就重渲染、
# 必要时重启 goimapnotify —— 两容器解耦,无需 docker.sock。
set -u

BASE="${IMAPNOTIFY_CONFIG:-/config/imapnotify.yaml}"
GEN="${IMAPNOTIFY_GENERATED:-/data/imapnotify.generated.yaml}"
RELOAD_FLAG="${WATCH_RELOAD_FLAG:-/data/watch.reload}"

_mtime() { stat -c %Y "$1" 2>/dev/null || echo 0; }

# 空转直到 RELOAD_FLAG 的 mtime 变化(后台增删账户时会变)。
wait_for_reload() {
    base="$1"
    while [ "$(_mtime "$RELOAD_FLAG")" = "$base" ]; do
        sleep 3
    done
}

while true; do
    python /app/render_imapnotify.py "$BASE" "$GEN"
    rc=$?
    last="$(_mtime "$RELOAD_FLAG")"

    if [ "$rc" = "3" ]; then
        echo "[watch] 暂无推送账户(base 与 webui 都为空),等待后台添加…" >&2
        wait_for_reload "$last"
        continue
    fi
    if [ "$rc" != "0" ] || [ ! -s "$GEN" ]; then
        echo "[watch] 渲染失败(rc=$rc),5s 后重试" >&2
        sleep 5
        continue
    fi

    echo "[watch] 启动 goimapnotify -conf $GEN"
    goimapnotify -conf "$GEN" &
    pid=$!

    # goimapnotify 在跑就盯着重载标记;变了就 kill 它,外层循环重渲染+重启。
    while kill -0 "$pid" 2>/dev/null; do
        if [ "$(_mtime "$RELOAD_FLAG")" != "$last" ]; then
            echo "[watch] 检测到账户变更,重启 goimapnotify 以应用"
            kill "$pid" 2>/dev/null || true
            break
        fi
        sleep 2
    done
    wait "$pid" 2>/dev/null || true
    echo "[watch] goimapnotify 退出,1s 后重启" >&2
    sleep 1
done
