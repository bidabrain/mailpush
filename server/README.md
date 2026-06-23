# mailpush · server 端

自建邮件推送 + 收发服务的**服务端**。三个容器,共用一个镜像:

- **推送线** `mail-watch`:`goimapnotify`(IMAP IDLE 监听)→ `onNewMail` → `push-fcm.py`(用 `imap_client` 抓最新一封补 sender/subject,再发 FCM HTTP v1)→ 安卓 app 弹通知。
- **API 线** `mail-api`(:8099):`FastAPI`(`api.py`)收/读走 **Python `imaplib` 持久连接池**(`imap_pool.py` + `imap_client.py`),发信走 **`smtplib`**(`mailsend.py`),供手机读列表 / 读正文 / 发信 / 回信 / 转发 / 删除。
- **管理后台** `mail-admin`(:8098,**仅内网**):`admin.py`,密码登录,图形化管理 app token(新建/删除)+ 看版本/状态。

手机不存任何邮箱凭据、不维持持久 IMAP 连接。整体设计见仓库根 `mail-push-relay-design.md` 与 `docker-design.md`。

> ⚠️ **两个端口安全要求不同**:
> - **mail-api(8099)能读全部邮件+发信,且是明文 HTTP → 必须置于 HTTPS(Cloudflare Tunnel)之后**,严禁路由器端口转发裸暴露公网。
> - **mail-admin(8098)是 token 管理入口 → 只能内网,绝不可暴露公网**(不要给它配 Tunnel/端口转发;只想本机访问写 `127.0.0.1:8098:8098`)。

> **0.2.0 起:收信引擎从 himalaya(Rust CLI)改为 Python `imaplib` 持久连接池。**
> 收益:连接复用免去每次握手(对会做反向 DNS、新连接要等数十秒的 IMAP 服务器尤其明显);
> 代码层登录后发 IMAP ID(RFC 2971)→ **解锁网易 163/126 读信**(himalaya v1.2.0 不支持 ID);
> 去掉 Rust 编译,镜像 build 从 ~20min 降到 ~1min。`config.toml` 等用户配置不变。
>
> **监听**始终用 `goimapnotify`(纯 RFC2177 IDLE,兼容 Gmail):Pimalaya 的 watch 件 mirador
> 硬要求 IMAP QRESYNC,而 Gmail 不支持 → mirador 监听不了 Gmail。

## 技术选型

| 件 | 选型 | 锁定方式 |
|---|---|---|
| 收信引擎 | Python **`imaplib` 持久连接池**(标准库,无外部依赖) | `app/imap_pool.py` + `imap_client.py` |
| 发信 | Python **`smtplib`**(直连 SMTP,不碰 IMAP) | `app/mailsend.py` |
| 监听 | goimapnotify(Go,无 semver tag) | Dockerfile `ARG GOIMAPNOTIFY_VERSION`(伪版本含 commit) |
| API | Python FastAPI(bearer 鉴权) | `app/api.py` |
| 认证 | Gmail App Password 等(各 provider 的应用专用密码/授权码) | config 的 `auth.cmd` 读 `/config/secrets/*.pass` |
| 推送 | FCM HTTP v1 + Firebase Admin SDK,data message + priority high | `push-fcm.py` |

> `config.toml` 仍沿用 himalaya v1 的 schema(`accounts.<name>.backend.*` 收信 / `message.send.backend.*` 发信);
> `imap_pool` 与 `mailsend` 都直接读它,因此从 0.1.x 升级**无需改配置**。

## 目录布局(ZimaOS)

```
/DATA/AppData/mailpush/
├── src/                      # 本目录(server/)内容,compose 在这里跑
├── config/
│   ├── config.toml           # 账号/收发配置(由 config.sample.toml 改名)
│   ├── imapnotify.yaml       # goimapnotify 配置(由 imapnotify.sample.yaml 改名)
│   ├── service-account.json  # Firebase service account(发 FCM)
│   ├── api-token             # mail-api 的 bearer token(openssl rand -hex 32)
│   └── secrets/
│       └── gmail.pass        # Gmail App Password(16 位,收发共用)
└── data/                     # 可写状态:附件缓存 / push 去重 last-seen / device-tokens.json(自动创建)
```

compose 的卷用相对路径 `../config`、`../data`(相对 `src/`),正好对应上面布局。

## 直接用预构建镜像(最快,免构建)

官方已发布镜像 **[`bidabrain/mailpush:latest`](https://hub.docker.com/r/bidabrain/mailpush)**(`linux/amd64`)。
`docker-compose.dist.yml` 默认就指向它,所以**不用 build、不用设 `MAILPUSH_IMAGE`**,准备好配置直接拉:

```bash
mkdir -p /DATA/AppData/mailpush/{src,config/secrets,data}
cd /DATA/AppData/mailpush/src
# 传 docker-compose.dist.yml、.env.sample、config.sample.toml、imapnotify.sample.yaml 到这里
cp .env.sample .env
cp config.sample.toml     ../config/config.toml         # 改账号
cp imapnotify.sample.yaml ../config/imapnotify.yaml     # 改账号
printf '16位AppPassword' > ../config/secrets/gmail.pass
cp /path/to/service-account.json ../config/service-account.json
printf '管理后台密码'    > ../config/secrets/admin.pass    # 后台登录用

docker compose -f docker-compose.dist.yml pull
docker compose -f docker-compose.dist.yml up -d
# 内网开 http://<内网IP>:8098 登录后台,给每台设备建 app token → 填进 app
```

> 非 amd64 机器(arm64 等)默认镜像跑不了,需按下方「发布到 Docker Hub」自己 `buildx` 构建,
> 并在 `.env` 设 `MAILPUSH_IMAGE=youruser/mailpush:latest`。

## 部署(SSH + docker compose,自己 build)

```bash
# 1. 放代码
mkdir -p /DATA/AppData/mailpush/config/secrets
cd /DATA/AppData/mailpush/src        # 把 server/ 内容传到这里

# 2. 准备 config 与密钥
cp config.sample.toml      /DATA/AppData/mailpush/config/config.toml
cp imapnotify.sample.yaml  /DATA/AppData/mailpush/config/imapnotify.yaml
vi /DATA/AppData/mailpush/config/config.toml         # 改成你的账号(backend.login 填真邮箱)
vi /DATA/AppData/mailpush/config/imapnotify.yaml     # 同样的账号(username/onNewMail 参数)
printf '%s' '你的16位appcode' > /DATA/AppData/mailpush/config/secrets/gmail.pass
cp /path/to/firebase-service-account.json /DATA/AppData/mailpush/config/service-account.json
printf '管理后台密码' > /DATA/AppData/mailpush/config/secrets/admin.pass   # 后台登录用
cp .env.sample .env                                  # dist 部署记得设 MAILPUSH_IMAGE
# app token 不用在这里建:起服务后内网开 http://<内网IP>:8098 登录后台新建(每台设备一个)。
# (可选·向后兼容:也可仍用单 token 文件 openssl rand -hex 32 > .../config/api-token)

# 3. 构建并起容器(只编译 goimapnotify/Go,约 1 分钟;APP_VERSION 注入版本号)
APP_VERSION=$(cat ../VERSION 2>/dev/null || echo dev) docker compose up -d --build

# 4. 验证
docker logs -f mail-watch        # 应看到 "启动 goimapnotify";来新邮件打印 [push] sent
curl -H "Authorization: Bearer $(cat /DATA/AppData/mailpush/config/api-token)" \
     "http://localhost:8099/inbox?account=gmail"
```

## 本机测试(本地 docker,不依赖 ZimaOS)

在 `server/` 目录内操作,数据放 `server/config`、`server/data`(已被根 `.gitignore` 忽略,不会 push)。

```bash
cd server

# 1. 切到本机布局
cp .env.sample .env
#   编辑 .env:取消注释 CONFIG_DIR=./config / DATA_DIR=./data

# 2. 准备配置与密钥
mkdir -p config/secrets data
cp config.sample.toml     config/config.toml      # 改 login 为你的 Gmail
cp imapnotify.sample.yaml config/imapnotify.yaml  # 改 username 为你的 Gmail
printf '%s' '你的16位AppPassword' > config/secrets/gmail.pass
openssl rand -hex 32 > config/api-token
#   service-account.json 可暂不放(没有时 push-fcm.py 会优雅跳过)

# 3. 构建并起容器(只编译 goimapnotify,约 1 分钟)
APP_VERSION=$(cat ../VERSION) docker compose up -d --build

# 4. 冒烟测试
curl http://localhost:8099/healthz                                  # {"ok":true},无需鉴权
TOKEN=$(cat config/api-token)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8099/accounts
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8099/inbox?account=gmail"

# 5. 看监听日志(需真实凭据才能连上 IMAP)
docker compose logs -f mail-watch        # 应看到 "启动 goimapnotify";来新邮件打印 [push] sent

# 收尾
docker compose down
```

分层验证建议:
- **不填任何凭据**:只有 `/healthz` 能过,足以确认镜像构建成功、服务起得来。
- **填密码后**:`/accounts`、`/inbox` 能返回;`mail-watch` 的 goimapnotify 能连上 IMAP IDLE。
- **再填 service-account.json + 安卓上报 device-token**:发测试邮件能看到 `[push] sent`。
  注意 push-fcm 首次触发只记录基线不推送(去重,见 push-fcm.py),之后的新信才推。

## 构建后核对

容器内无 curl,用自带的 python 发请求(三账号逐个验证收读):

```bash
# 账号列表
docker exec -it mail-api python3 -c "import urllib.request as u; t=open('/config/api-token').read().strip(); print(u.urlopen(u.Request('http://localhost:8099/accounts',headers={'Authorization':'Bearer '+t})).read().decode())"

# 收件列表 / 文件夹(含探测到的「已发」;中文文件夹应正常显示)
docker exec -it mail-api python3 -c "import urllib.request as u; t=open('/config/api-token').read().strip(); print(u.urlopen(u.Request('http://localhost:8099/folders?account=gmail',headers={'Authorization':'Bearer '+t})).read().decode())"
```

重点验证项:
- **复用提速**:对建连昂贵的账号(如某些做反向 DNS 的企业邮箱),第一次刷新慢、**第二次秒回**(连接池生效)。
- **网易 163/126 读信**:能正常读正文(代码层发 IMAP ID 解锁;himalaya 时代此处 502)。
- **中文文件夹**:`/folders` 返回的「已发送/已删除」等为正常中文(modified UTF-7 已解码);打开已发箱、删除邮件(移到回收站)均可用。

连接池调参(可选,见 `app/imap_pool.py` 或 `.env.sample`):`IMAP_CONNECT_TIMEOUT`(默认 90s)/ `IMAP_OP_TIMEOUT`(30s)/ `IMAP_KEEPALIVE`(240s)。

## 发布到 Docker Hub + 异机部署(image 模式)

本机 build 推到 Docker Hub,目标机(如 ZimaOS)用 `docker-compose.dist.yml` 拉取安装,不在目标机 build。

> ⚠️ **架构必须匹配**:开发机若是 Apple Silicon(arm64),而目标机是 x86(amd64),
> 必须用 `buildx` 跨架构构建。0.2.0 起只编译 goimapnotify(Go),即便 QEMU 模拟也很快(~1 分钟)。
>
> 🔒 **密钥永不进镜像/Git**:`gmail.pass` / `service-account.json` / `api-token`
> 单独传到目标机的 `config/`。镜像里只有程序。

### 1) Mac 上构建并推送(在 `server/` 目录,把 YOURUSER 换成你的 Docker Hub 用户名)

```bash
docker login
# 多架构 push 需要 container 驱动的 builder(只需建一次):
docker buildx create --name mp --driver docker-container --use --bootstrap

cd server
# 版本号:--build-arg APP_VERSION 从仓库根 VERSION 注入镜像(漏了服务端 /version 会显示 dev)。
# 目标机是 x86 ZimaOS → 只构 amd64(最快):
docker buildx build --platform linux/amd64 \
    --build-arg APP_VERSION=$(cat ../VERSION) \
    -t YOURUSER/mailpush:latest -t YOURUSER/mailpush:$(cat ../VERSION) --push .

# 确认架构正确:
docker buildx imagetools inspect YOURUSER/mailpush:latest   # 看 Platform 含 linux/amd64
```

`--push` 直接推到 Docker Hub(多架构镜像无法 `--load` 到本地,只能 push)。

### 2) 目标机上安装

```bash
mkdir -p /DATA/AppData/mailpush/{src,config/secrets,data}
cd /DATA/AppData/mailpush/src
# 传这几个文件到 src/:docker-compose.dist.yml、.env.sample、config.sample.toml、imapnotify.sample.yaml

cp .env.sample .env
# 编辑 .env,至少加一行指定镜像:
#   MAILPUSH_IMAGE=YOURUSER/mailpush:latest

# 配置与密钥放到 ../config(= /DATA/AppData/mailpush/config)
cp config.sample.toml     ../config/config.toml         # 改账号(backend.login 填真邮箱)
cp imapnotify.sample.yaml ../config/imapnotify.yaml     # 改账号
printf '%s' '16位AppPassword' > ../config/secrets/gmail.pass
cp /path/to/service-account.json ../config/service-account.json
openssl rand -hex 32 > ../config/api-token

docker compose -f docker-compose.dist.yml up -d
docker compose -f docker-compose.dist.yml logs -f mail-watch
```

### 3) 更新版本

版本号唯一来源是**仓库根的 `VERSION` 文件**(server 与 app 共用)。升版本:改 `VERSION` → 重建。

```bash
# Mac:改完 ../VERSION 后,重新 buildx build(务必带 --build-arg APP_VERSION),--push
# 目标机:
docker compose -f docker-compose.dist.yml pull
docker compose -f docker-compose.dist.yml up -d
# 验证:curl -s http://localhost:8099/version   # 应为 {"version":"<VERSION 内容>"}
```

## 管理后台(mail-admin)

内网图形化管理 app token + 看状态,免去手翻 config。

```bash
# 1. 设管理密码(放 secrets,不进 git;没设的话后台登录页会提示创建)
printf '管理后台密码' > <config>/secrets/admin.pass
# 2. 起服务后,内网浏览器打开
http://<服务器内网IP>:8098      # 用管理密码登录
# 3. 给每台设备「新建 Token」→ 复制整串填进 app 的「API Token」
```

- **多 token + 吊销**:每台设备一个 token;**丢设备就在后台删掉它的 token**(即时生效、不影响其他设备),无需全量轮换。
- **推送设备绑定**:FCM 推送 token 记录其注册所用的 app token;**删 app token 会连带删除其名下推送设备** → 丢设备一键同时断「读信 + 推送」(否则旧 FCM token 仍会把发件人/主题推过去)。后台「推送设备」区也可单删/清空;首次从旧版升级时,旧的无归属设备显示「未关联·旧」,点「清空所有推送设备」一次,有效设备下次开 app 会带归属重新注册。
- 鉴权来源:`require_auth` 接受后台管理的多 token(`/data/app-tokens.json`),并**兼容**旧的单 `/config/api-token`。默认不再预设固定 token。
- ⚠️ **mail-admin 只能内网**:别给它配 Cloudflare Tunnel、别在路由器转发 8098。只想本机访问:compose 端口写 `127.0.0.1:8098:8098`。

## 暴露给手机(mail-api)

`mail-api` 在 `:8099`,**跑的是明文 HTTP**。

- ✅ **必须置于 HTTPS 之后**:用 **Cloudflare Tunnel** 指向 `host:8099`(Tunnel 提供 HTTPS + 出站连接,无需开端口)。
- 🚫 **严禁把 8099 经路由器端口转发裸暴露公网**——明文 HTTP 直连公网会让 **token 与邮件被嗅探**;且它能读全部邮件、以你名义发信。
- 可选再加 **Cloudflare Access(Service Token)** 作边缘第二道闸,但不是必须;最低要求是"走 HTTPS + 强 token"。

## API 速查

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` | 存活探针(无需鉴权) |
| GET | `/version` | 服务端版本(无需鉴权) |
| GET | `/accounts` | 账号名列表 |
| GET | `/folders?account=` | 文件夹名 + 探测到的「已发」 |
| GET | `/unread?account=&folder=INBOX` | 单账户未读数(SEARCH UNSEEN) |
| GET | `/unread-all` | 各账户 INBOX 未读数 + 总数 `{counts, total}` |
| GET | `/inbox?account=&folder=INBOX&page=1&page_size=50` | 收件列表 |
| GET | `/msg/{id}?account=&folder=&mark_read=false` | 读正文(导出 .eml 解析 HTML/纯文本,默认不标已读) |
| DELETE | `/msg/{id}?account=&folder=` | 删除(移到回收站) |
| GET | `/attachments/{id}?account=&folder=` / `/attachment/{id}?account=&name=` | 列附件 / 下载附件 |
| POST | `/send` | 发信(multipart:字段 + 可选附件) |
| POST | `/reply/{id}` | 回信(multipart;保线程) |
| POST | `/forward/{id}` | 转发(multipart;自动带原附件) |
| POST | `/register-token` | 安卓自动上报 FCM token(多设备) |

除 `/healthz`、`/version` 外都需 `Authorization: Bearer <api-token>`。

## 已知待打磨(P4)

- `/msg` 优先返回 HTML 正文(无 HTML 时回退纯文本);极少数畸形 MIME 可能解析不全。
- 不自动归档「已发送」的 provider(如部分企业邮箱,SMTP 发信不自动存 Sent):smtplib 只发不存,
  这类账号的 app 发信暂无「已发送」记录(可后续加可选的 IMAP APPEND 存副本)。
- 统一收件箱跨账号按 `date` 字符串近似排序(跨时区非严格时序)。
