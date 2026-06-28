#!/usr/bin/env bash
# melonmail 管理后台 CLI —— 用 curl 驱动 mail-admin 的 webui,无需浏览器/图形界面。
#
# 适用场景:VPS 部署、管理端口只绑 127.0.0.1 不暴露公网,只能在本机命令行操作。
#
# 用法:
#   ./admin-cli.sh                       # 不带参数 = 进入交互式菜单(数字选择,逐层操作)
#   ./admin-cli.sh menu                  # 同上,显式进入菜单
#   ./admin-cli.sh login                 # 登录(交互输入密码或读 ADMIN_PASS / admin.pass 文件)
#   ./admin-cli.sh status                # 看版本/运行状态/账户/设备(纯文本)
#   ./admin-cli.sh accounts              # 列邮箱账户
#   ./admin-cli.sh add-account ...       # 新增/编辑账户(见下方 add-account -h)
#   ./admin-cli.sh del-account <name>
#   ./admin-cli.sh tokens                # 列 app token
#   ./admin-cli.sh new-token "<label>"
#   ./admin-cli.sh del-token <id>
#   ./admin-cli.sh devices               # 列推送设备
#   ./admin-cli.sh del-device <token>
#   ./admin-cli.sh clear-devices
#   ./admin-cli.sh oauth-save <account> <client_id>
#   ./admin-cli.sh oauth-enroll <account>   # 发起授权并打印代码+链接
#   ./admin-cli.sh oauth-status <account>   # 轮询授权结果
#   ./admin-cli.sh oauth-del <account>
#   ./admin-cli.sh logout
#   ./admin-cli.sh raw GET|POST <path> [k=v ...]   # 兜底:任意请求
#
# 环境变量:
#   ADMIN_URL        默认 http://127.0.0.1:8098
#   ADMIN_COOKIE     cookie 文件,默认 ~/.melonmail-admin.cookies
#   ADMIN_PASS       登录密码(非交互/脚本化时用);或
#   ADMIN_PASS_FILE  从文件读密码(如服务器上的 /config/secrets/admin.pass)
set -euo pipefail

ADMIN_URL="${ADMIN_URL:-http://127.0.0.1:8098}"
COOKIE="${ADMIN_COOKIE:-$HOME/.melonmail-admin.cookies}"

# ---- 工具 ----
die() { echo "错误: $*" >&2; exit 1; }

# 去 HTML 标签,把页面渲染成可读文本(只为人看,不解析)。
# 块级结束标签 / <br> 转换行,表格单元格用 " · " 分隔,避免整页挤成一行。
strip_html() {
  sed -E -e 's#<br ?/?>#\n#g' \
         -e 's#</(p|div|h1|h2|h3|tr|li|form|table)>#\n#g' \
         -e 's#</td># · #g' \
         -e 's/<[^>]*>//g' \
         -e 's/&amp;/\&/g' -e 's/&lt;/</g' -e 's/&gt;/>/g' \
         -e 's/&middot;/·/g' -e 's/&nbsp;/ /g' \
    | sed -E -e 's/[[:space:]]+/ /g' \
             -e 's/^ //' -e 's/ $//' \
             -e 's/ ?· $//' -e '/^$/d' -e '/^ *· *$/d'
}

need_login() {
  [ -s "$COOKIE" ] || die "未登录,先运行: $0 login"
}

# 带 cookie 的 POST(表单)。回 303 视为成功;若返回 200 HTML 通常是出错页,打印出来。
post() {
  local path="$1"; shift
  local args=()
  for kv in "$@"; do args+=(--data-urlencode "$kv"); done
  local out
  out="$(curl -sS -b "$COOKIE" -c "$COOKIE" -w $'\n%{http_code}' "${args[@]}" "$ADMIN_URL$path")"
  local code="${out##*$'\n'}"
  local body="${out%$'\n'*}"
  case "$code" in
    303|302) return 0 ;;                       # 正常:重定向回首页
    200) echo "$body" | strip_html ;;          # 多半是错误页(如保存失败)
    401|403) die "未授权,cookie 可能失效(后台重启会清会话),重新 login" ;;
    *) die "HTTP $code: $(echo "$body" | strip_html | head -3)" ;;
  esac
}

get() {
  need_login
  curl -sS -b "$COOKIE" "$ADMIN_URL$1"
}

# ---- 子命令 ----

cmd_login() {
  local pass=""
  if [ -n "${ADMIN_PASS:-}" ]; then
    pass="$ADMIN_PASS"
  elif [ -n "${ADMIN_PASS_FILE:-}" ]; then
    [ -r "$ADMIN_PASS_FILE" ] || die "读不到 ADMIN_PASS_FILE: $ADMIN_PASS_FILE"
    pass="$(tr -d '\r\n' < "$ADMIN_PASS_FILE")"
  else
    read -rsp "管理密码: " pass; echo
  fi
  [ -n "$pass" ] || die "密码为空"
  # 登录成功会 set-cookie 并 303 回 /;失败也 303(带 ?err=bad)。用拿到首页是否含登录框判断。
  curl -sS -c "$COOKIE" --data-urlencode "password=$pass" "$ADMIN_URL/login" >/dev/null
  chmod 600 "$COOKIE" 2>/dev/null || true
  # 登录页独有 action=/login;仪表盘没有(它有 /logout、/accounts/save 等),据此区分成功/失败
  if get / | grep -q 'action=/login'; then
    rm -f "$COOKIE"
    die "登录失败(密码错误,或服务端未设置 admin.pass)"
  fi
  echo "登录成功,会话已存到 $COOKIE"
}

cmd_logout() {
  [ -s "$COOKIE" ] || { echo "本就未登录"; return 0; }
  curl -sS -b "$COOKIE" "$ADMIN_URL/logout" >/dev/null || true
  rm -f "$COOKIE"
  echo "已退出"
}

cmd_status()   { get / | strip_html; }
cmd_accounts() { get / | strip_html | sed -n '/邮箱账户/,/App Token/p'; }
cmd_tokens()   { get / | strip_html | sed -n '/App Token/,/推送设备/p'; }
cmd_devices()  { get / | strip_html | sed -n '/推送设备/,$p'; }

cmd_new_token()  { need_login; post /tokens/new "label=${1:-}"; echo "已新建 token: ${1:-(无名)}"; cmd_tokens; }
cmd_del_token()  { need_login; [ -n "${1:-}" ] || die "用法: $0 del-token <id>"; post /tokens/delete "id=$1"; echo "已删除 token $1(及其名下推送设备)"; }
cmd_del_device() { need_login; [ -n "${1:-}" ] || die "用法: $0 del-device <token>"; post /devices/delete "token=$1"; echo "已删除设备"; }
cmd_clear_devices(){ need_login; post /devices/clear; echo "已清空所有推送设备"; }

cmd_del_account(){ need_login; [ -n "${1:-}" ] || die "用法: $0 del-account <name>"; post /accounts/delete "name=$1"; echo "已删除账户 $1(含密码文件,停止其推送)"; }

cmd_oauth_save()  { need_login; [ $# -ge 2 ] || die "用法: $0 oauth-save <account> <client_id>"; post /oauth/save "account=$1" "client_id=$2"; echo "已保存 OAuth 配置: $1"; }
cmd_oauth_del()   { need_login; [ -n "${1:-}" ] || die "用法: $0 oauth-del <account>"; post /oauth/delete "account=$1"; echo "已删除 OAuth 账号 $1"; }
cmd_oauth_enroll(){
  need_login; [ -n "${1:-}" ] || die "用法: $0 oauth-enroll <account>"
  post /oauth/enroll "account=$1"
  echo "已发起设备码授权,按下面提示在【任意能上网的浏览器】完成微软登录同意:"
  echo "----------------------------------------"
  get "/oauth/enroll?account=$1" | strip_html | grep -iE 'http|代码|输入|授权|失败' || true
  echo "----------------------------------------"
  echo "完成后运行: $0 oauth-status $1   查看结果"
}
cmd_oauth_status(){
  need_login; [ -n "${1:-}" ] || die "用法: $0 oauth-status <account>"
  get "/oauth/enroll?account=$1" | strip_html
}

cmd_add_account() {
  case "${1:-}" in -h|--help) add_account_help; return 0;; esac
  need_login
  # 默认值:push 勾选(与图形界面预勾一致),其余空走 preset/默认
  local name="" email="" preset="custom" auth="password" password=""
  local imap_host="" imap_port="" imap_enc="" smtp_host="" smtp_port="" smtp_enc=""
  local push=1 default=0 save_copy=0 enable_id=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --name)        name="$2"; shift 2;;
      --email)       email="$2"; shift 2;;
      --preset)      preset="$2"; shift 2;;        # custom|gmail|outlook|yahoo|netease126|netease163|fastmail
      --auth)        auth="$2"; shift 2;;          # password|oauth2
      --password)    password="$2"; shift 2;;
      --imap-host)   imap_host="$2"; shift 2;;
      --imap-port)   imap_port="$2"; shift 2;;
      --imap-enc)    imap_enc="$2"; shift 2;;      # tls|starttls|none
      --smtp-host)   smtp_host="$2"; shift 2;;
      --smtp-port)   smtp_port="$2"; shift 2;;
      --smtp-enc)    smtp_enc="$2"; shift 2;;
      --save-copy)   save_copy=1; shift;;
      --default)     default=1; shift;;
      --enable-id)   enable_id=1; shift;;
      --no-push)     push=0; shift;;
      -h|--help)     add_account_help; return 0;;
      *) die "未知参数: $1 (看 $0 add-account -h)";;
    esac
  done
  [ -n "$name" ]  || die "缺 --name"
  [ -n "$email" ] || die "缺 --email"

  # checkbox:勾=传任意非空值,不勾=【完全不传该字段】
  local f=(name="$name" email="$email" preset="$preset" auth="$auth" password="$password"
           imap_host="$imap_host" imap_port="$imap_port" imap_encryption="$imap_enc"
           smtp_host="$smtp_host" smtp_port="$smtp_port" smtp_encryption="$smtp_enc")
  [ "$push" = 1 ]      && f+=(push=on)
  [ "$default" = 1 ]   && f+=(default=on)
  [ "$save_copy" = 1 ] && f+=(save_copy=on)
  [ "$enable_id" = 1 ] && f+=(enable_id_command=on)

  post /accounts/save "${f[@]}"
  echo "已保存账户 $name"
  cmd_accounts
}

add_account_help() {
  cat <<'EOF'
add-account —— 新增或编辑邮箱账户(同名=编辑覆盖)

必填:
  --name <账号名>        只能字母/数字/.-_(如 gmail)
  --email <地址>         you@example.com

常用:
  --preset <p>           custom(默认)|gmail|outlook|yahoo|netease126|netease163|fastmail
                         选预设会自动填 IMAP/SMTP 主机端口加密,只需再给 --password
  --auth <a>             password(默认)|oauth2(Outlook 用 oauth2,密码留空,之后用 oauth-* 授权)
  --password <pw>        应用专用密码/授权码;编辑时留空=不改密码
  --default              设为默认账户
  --no-push              关闭推送监听(默认开启,与界面预勾一致)

自定义服务器(preset=custom 时必填 host):
  --imap-host --imap-port --imap-enc   (enc: tls|starttls|none)
  --smtp-host --smtp-port --smtp-enc
  --save-copy            发信后自存「已发送」(Gmail 勿用,会重复)
  --enable-id            发 IMAP ID 指令(网易 126/163 必须;选对应 preset 已自动开)

例:
  添加 Gmail:
    add-account --name gmail --email me@gmail.com --preset gmail --password 'xxxx yyyy zzzz wwww' --default
  添加网易163:
    add-account --name mail163 --email me@163.com --preset netease163 --password '授权码'
  添加 Outlook(OAuth2):
    add-account --name outlook --email me@outlook.com --preset outlook --auth oauth2
    然后: oauth-save outlook <client_id> ;  oauth-enroll outlook ;  oauth-status outlook
  自定义服务器:
    add-account --name work --email me@corp.com --preset custom \
      --imap-host imap.corp.com --imap-port 993 --imap-enc tls \
      --smtp-host smtp.corp.com --smtp-port 587 --smtp-enc starttls --password 'pw'
EOF
}

cmd_raw() {
  need_login
  local method="${1:-GET}"; local path="${2:-/}"; shift 2 || true
  if [ "$method" = "GET" ]; then
    curl -sS -b "$COOKIE" "$ADMIN_URL$path"
  else
    local args=(); for kv in "$@"; do args+=(--data-urlencode "$kv"); done
    curl -sS -b "$COOKIE" -c "$COOKIE" "${args[@]}" "$ADMIN_URL$path"
  fi
}

# ---- 交互式菜单 ----

_fetch() { curl -sS -b "$COOKIE" "$ADMIN_URL$1" 2>/dev/null; }

is_authed() { [ -s "$COOKIE" ] || return 1; ! _fetch / | grep -q 'action=/login'; }

# 从页面提取「删除」表单里的隐藏值 + 同行标签 -> 每行 "VALUE<TAB>LABEL"
_parse() {
  awk -v act="$1" -v fld="$2" '
    BEGIN{ RS="<tr>"; q="\047" }
    index($0,"action=" act){
      row=$0
      if(match(row,/<td>[^<]*/)) lab=substr(row,RSTART+4,RLENGTH-4); else lab="?"
      re="name=" fld " value=" q "[^" q "]*" q
      if(match(row,re)){ v=substr(row,RSTART,RLENGTH); sub("name=" fld " value=" q,"",v); sub(q "$","",v); print v "\t" lab }
    }'
}

# 编号选择。$1 = "VALUE<TAB>LABEL" 多行列表(用参数传,不能用管道——否则 read 会读到管道而非键盘)。
# 选中的 VALUE 打到 stdout,菜单/提示打到 stderr。
_pick() {
  local -a vals=() labs=(); local v l
  while IFS=$'\t' read -r v l; do [ -n "$v" ] && { vals+=("$v"); labs+=("$l"); }; done <<< "$1"
  if [ ${#vals[@]} -eq 0 ]; then echo "(没有可选项)" >&2; return 1; fi
  local i; for i in "${!vals[@]}"; do printf '  %d) %s\n' $((i+1)) "${labs[$i]}" >&2; done
  local n; read -rp "选序号(0 取消): " n
  [[ "$n" =~ ^[0-9]+$ ]] && [ "$n" -ge 1 ] && [ "$n" -le ${#vals[@]} ] || { echo "已取消" >&2; return 1; }
  printf '%s' "${vals[$((n-1))]}"
}

# 取列表 + 选择二合一:$1=action片段 $2=隐藏字段名;选中 VALUE -> stdout
_pick_from() { _pick "$(_fetch / | _parse "$1" "$2")"; }

_pause()  { read -rp $'\n回车继续…' _ || true; }
_clear()  { clear 2>/dev/null || true; }
_yn()     { local a; read -rp "$1 ($2): " a || true; a=${a:-$2}; [[ "$a" =~ ^[Yy] ]]; }
# 提示可带默认值(回车留空即取默认);不用 read -e/-i,兼容老 bash 与管道输入
_ask() {
  local __v __d="${3:-}"
  if [ -n "$__d" ]; then read -rp "$2 [$__d]: " __v || true; else read -rp "$2: " __v || true; fi
  [ -n "$__v" ] || __v="$__d"
  printf -v "$1" '%s' "$__v"
}

iadd_account() {
  echo "—— 新增/编辑账户(账号名相同即为编辑覆盖)——"
  local name email preset auth pass=""
  _ask name  "账号名(字母数字.-_)" ""
  [ -n "$name" ] || { echo "已取消"; return; }
  _ask email "邮箱地址" ""
  echo "预设: custom gmail outlook yahoo netease126 netease163 fastmail"
  _ask preset "provider 预设" "custom"
  _ask auth   "鉴权 password/oauth2" "password"
  local args=(--name "$name" --email "$email" --preset "$preset" --auth "$auth")
  if [ "$auth" = password ]; then
    read -rsp "密码/授权码(留空=不改): " pass; echo
    [ -n "$pass" ] && args+=(--password "$pass")
  fi
  if [ "$preset" = custom ]; then
    local ih ip ie sh sp se
    _ask ih "IMAP host" "";  _ask ip "IMAP port" "993";  _ask ie "IMAP 加密 tls/starttls/none" "tls"
    _ask sh "SMTP host" "";  _ask sp "SMTP port" "465";  _ask se "SMTP 加密 tls/starttls/none" "tls"
    args+=(--imap-host "$ih" --imap-port "$ip" --imap-enc "$ie" --smtp-host "$sh" --smtp-port "$sp" --smtp-enc "$se")
  fi
  _yn "设为默认账户?" "N"           && args+=(--default)
  _yn "开启推送监听?" "Y"           || args+=(--no-push)
  _yn "发 IMAP ID(网易必须)?" "N"  && args+=(--enable-id)
  _yn "SMTP 发信后自存已发送?" "N"  && args+=(--save-copy)
  echo; cmd_add_account "${args[@]}"
}

idel_account() {
  local v; v="$(_pick_from /accounts/delete name)" || return
  _yn "确认删除账户「${v}」(含密码,停其推送)?" "N" || { echo 已取消; return; }
  cmd_del_account "$v"
}

menu_accounts() {
  while true; do
    _clear; echo "===== 邮箱账户 ====="
    echo " 1) 查看列表   2) 新增/编辑   3) 删除   0) 返回"
    local c; read -rp "选择: " c
    case "$c" in
      1) cmd_accounts; _pause;;
      2) iadd_account; _pause;;
      3) idel_account; _pause;;
      0|"") return;;
      *) echo 无效;sleep 1;;
    esac
  done
}

menu_tokens() {
  while true; do
    _clear; echo "===== App Token ====="
    echo " 1) 查看列表   2) 新建   3) 删除   0) 返回"
    local c; read -rp "选择: " c
    case "$c" in
      1) cmd_tokens; _pause;;
      2) local l; _ask l "Token 名称(如:我的手机)" ""; cmd_new_token "$l"; _pause;;
      3) local v; v="$(_pick_from /tokens/delete id)" || { _pause; continue; }
         _yn "删除该 token(连带其推送设备)?" "N" && cmd_del_token "$v"; _pause;;
      0|"") return;;
      *) echo 无效;sleep 1;;
    esac
  done
}

menu_devices() {
  while true; do
    _clear; echo "===== 推送设备(FCM)====="
    echo " 1) 查看列表   2) 删除单个   3) 清空全部   0) 返回"
    local c; read -rp "选择: " c
    case "$c" in
      1) cmd_devices; _pause;;
      2) local v; v="$(_pick_from /devices/delete token)" || { _pause; continue; }
         cmd_del_device "$v"; _pause;;
      3) _yn "确认清空所有推送设备?" "N" && cmd_clear_devices; _pause;;
      0|"") return;;
      *) echo 无效;sleep 1;;
    esac
  done
}

menu_oauth() {
  while true; do
    _clear; echo "===== OAuth(Outlook 等)====="
    echo " 1) 查看列表   2) 保存配置   3) 发起授权   4) 查授权结果   5) 删除   0) 返回"
    local c; read -rp "选择: " c
    case "$c" in
      1) _fetch / | strip_html | sed -n '/OAuth/,$p'; _pause;;
      2) local a i; _ask a "账号名(同 config,如 outlook)" ""; _ask i "Azure client_id" ""
         [ -n "$a" ] && cmd_oauth_save "$a" "$i"; _pause;;
      3) local v; v="$(_pick_from /oauth/delete account)" || { _ask v "账号名" ""; }
         [ -n "$v" ] && cmd_oauth_enroll "$v"; _pause;;
      4) local v; v="$(_pick_from /oauth/delete account)" || { _ask v "账号名" ""; }
         [ -n "$v" ] && cmd_oauth_status "$v"; _pause;;
      5) local v; v="$(_pick_from /oauth/delete account)" || { _pause; continue; }
         _yn "删除 OAuth 账号「${v}」?" "N" && cmd_oauth_del "$v"; _pause;;
      0|"") return;;
      *) echo 无效;sleep 1;;
    esac
  done
}

cmd_menu() {
  while ! is_authed; do
    echo "未登录,请先登录($ADMIN_URL)"
    cmd_login || true
    is_authed && break
    _yn "重试登录?" "Y" || return 1
  done
  while true; do
    _clear
    echo "================================"
    echo " melonmail 管理后台 · 命令行菜单"
    echo " $ADMIN_URL"
    echo "================================"
    echo " 1) 状态总览"
    echo " 2) 邮箱账户"
    echo " 3) App Token"
    echo " 4) 推送设备(FCM)"
    echo " 5) OAuth(Outlook 等)"
    echo " 9) 退出登录并离开"
    echo " 0) 离开(保留登录)"
    local c; read -rp "请选择: " c
    case "$c" in
      1) _clear; cmd_status; _pause;;
      2) menu_accounts;;
      3) menu_tokens;;
      4) menu_devices;;
      5) menu_oauth;;
      9) cmd_logout; return 0;;
      0|q|"") echo "再见"; return 0;;
      *) echo 无效;sleep 1;;
    esac
  done
}

usage() {
  sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
}

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    login)         cmd_login "$@";;
    logout)        cmd_logout "$@";;
    status)        need_login; cmd_status;;
    accounts)      need_login; cmd_accounts;;
    add-account)   cmd_add_account "$@";;
    del-account)   cmd_del_account "$@";;
    tokens)        need_login; cmd_tokens;;
    new-token)     cmd_new_token "$@";;
    del-token)     cmd_del_token "$@";;
    devices)       need_login; cmd_devices;;
    del-device)    cmd_del_device "$@";;
    clear-devices) cmd_clear_devices "$@";;
    oauth-save)    cmd_oauth_save "$@";;
    oauth-enroll)  cmd_oauth_enroll "$@";;
    oauth-status)  cmd_oauth_status "$@";;
    oauth-del)     cmd_oauth_del "$@";;
    raw)           cmd_raw "$@";;
    menu|"")       cmd_menu;;
    -h|--help|help) usage;;
    *) die "未知命令: $cmd (看 $0 --help)";;
  esac
}

main "$@"
