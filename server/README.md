# mailpush · server 端

自建邮件推送 + 收发服务的**服务端**。两条数据线、两个容器,共用一个镜像:

- **推送线** `mail-watch`:`goimapnotify`(IMAP IDLE 监听)→ `onNewMail` → `push-fcm.py`(用 himalaya 抓最新一封补 sender/subject,再发 FCM HTTP v1)→ 安卓 app 弹通知。
- **API 线** `mail-api`:`FastAPI`(`api.py`)用 subprocess 包 `himalaya` CLI,供手机读列表 / 读正文 / 发信 / 回信。

手机不存任何邮箱凭据、不维持持久 IMAP 连接。整体设计见仓库根的 `mail-push-relay-design.md` 与 `docker-design.md`,已锁定决策与进度见 `PROJECT-MEMORY.md`。

> **与设计文档的两处偏差(重要)**:
> 1. 设计假设"himalaya 自带 `envelope watch`",但 **himalaya v1.x 已移除 watch**。
> 2. Pimalaya 的替代 watch 件 **mirador 硬要求 IMAP QRESYNC,Gmail 不支持 → mirador 监听不了 Gmail**。
>
> 因此监听改用 **goimapnotify**(纯 RFC2177 IDLE,兼容 Gmail);`himalaya` v1.2.0 仅作 API 引擎。
> himalaya 与 goimapnotify **各用一份配置**(`config.toml` / `imapnotify.yaml`),引用同一密钥文件。

## 技术选型(已锁定)

| 件 | 选型 | 锁定方式 |
|---|---|---|
| 引擎 | himalaya **1.2.0**(crates.io,features `imap,smtp`,rustls 内置) | Dockerfile `ARG HIMALAYA_VERSION` |
| 监听 | goimapnotify(Go,无 semver tag) | Dockerfile `ARG GOIMAPNOTIFY_VERSION`(伪版本含 commit) |
| API | Python FastAPI 包 himalaya CLI(方案A) | — |
| 认证 | Gmail App Password | 两份 config 各自 `cmd` 读 `/config/secrets/*.pass` |
| 推送 | FCM HTTP v1 + Firebase Admin SDK,data message + priority high | `push-fcm.py` |

## 目录布局(ZimaOS)

```
/DATA/AppData/mailpush/
├── src/                      # 本目录(server/)内容,compose 在这里跑
├── config/
│   ├── config.toml           # himalaya 配置(由 config.sample.toml 改名)
│   ├── imapnotify.yaml       # goimapnotify 配置(由 imapnotify.sample.yaml 改名)
│   ├── service-account.json  # Firebase service account(发 FCM)
│   ├── device-token          # 安卓 app 的 FCM token(单设备先手填)
│   ├── api-token             # mail-api 的 bearer token(openssl rand -hex 32)
│   └── secrets/
│       └── gmail.pass        # Gmail App Password(16 位,两份 config 共用)
└── data/                     # himalaya id-map/cache + push 去重的 last-seen(自动创建)
```

compose 的卷用相对路径 `../config`、`../data`(相对 `src/`),正好对应上面布局。

## 部署(SSH + docker compose)

```bash
# 1. 放代码
mkdir -p /DATA/AppData/mailpush/config/secrets
cd /DATA/AppData/mailpush/src        # 把 server/ 内容传到这里

# 2. 准备 config 与密钥
cp config.sample.toml      /DATA/AppData/mailpush/config/config.toml      # himalaya
cp imapnotify.sample.yaml  /DATA/AppData/mailpush/config/imapnotify.yaml  # goimapnotify
vi /DATA/AppData/mailpush/config/config.toml         # 改成你的账号
vi /DATA/AppData/mailpush/config/imapnotify.yaml     # 同样的账号(username/onNewMail 参数)
printf '%s' '你的16位appcode' > /DATA/AppData/mailpush/config/secrets/gmail.pass
cp /path/to/firebase-service-account.json /DATA/AppData/mailpush/config/service-account.json
openssl rand -hex 32 > /DATA/AppData/mailpush/config/api-token
cp .env.sample .env                                  # 一般无需改(默认 ZimaOS 布局)
# device-token 等安卓 app 首次拿到 FCM token 后再填:
#   echo '<fcm-device-token>' > /DATA/AppData/mailpush/config/device-token

# 3. 构建并起容器(APP_VERSION 注入版本号;ZimaOS 上没有 VERSION 文件时退化为 dev,
#    正式版本建议走下方「发布到 Docker Hub」的镜像模式)
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
#   service-account.json / device-token 可暂不放(没有时 push-fcm.py 会优雅跳过)

# 3. 构建并起容器(首次编译 himalaya+goimapnotify,约几分钟)
#    APP_VERSION 从仓库根 VERSION 注入版本号(漏了会显示 dev)
APP_VERSION=$(cat ../VERSION) docker compose up -d --build

# 4. 冒烟测试
curl http://localhost:8099/healthz                                  # {"ok":true},无需鉴权
TOKEN=$(cat config/api-token)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8099/accounts
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8099/inbox?account=gmail"

# 5. 看监听日志(需真实 Gmail 凭据才能连上 IMAP)
docker compose logs -f mail-watch        # 应看到 "启动 goimapnotify";来新邮件打印 [push] sent

# 收尾
docker compose down
```

分层验证建议:
- **不填任何凭据**:只有 `/healthz` 能过,足以确认镜像构建成功、服务起得来。
- **填 Gmail App Password 后**:`/accounts`、`/inbox` 能返回;`mail-watch` 的 goimapnotify 能连上 Gmail IDLE。
- **再填 service-account.json + device-token**:发测试邮件能看到 `[push] sent`(完整 P1)。
  注意 push-fcm 首次触发只记录基线不推送(去重,见 push-fcm.py),之后的新信才推。

> macOS 上端口直接 `localhost:8099` 即可。要真机收推送仍需 Firebase + 安卓端(P3)。

## 构建后核对(已在本机验证一轮)

下列已实测确认(himalaya v1.2.0):`envelope list` folder 是 `-f`(位置参数是搜索 query);
`message read` 用 `--preview` 读取不标已读;`message send`/`template send` 从 stdin 读;
`template reply` 是 `<ID>` + `-A/--all`。himalaya 账号必须有 `email` 字段。

仍建议升级版本后复跑一遍:

```bash
docker run --rm mailpush:latest himalaya --version
docker run --rm mailpush:latest goimapnotify -h
docker run --rm mailpush:latest himalaya envelope list  --help   # -f folder / -p / -s
docker run --rm mailpush:latest himalaya template reply --help   # ★ /reply 端点的模板逻辑(代码里标了 VERIFY)

# config 能被各自二进制解析(需放好 config/):
docker run --rm -v "$PWD/config:/config:ro" mailpush:latest himalaya -c /config/config.toml account list
```

> **关于 /reply 与正文 HTML**:`template reply` 输出格式、以及 `/msg` 返回的正文是否为 HTML
> (安卓 WebView 需要)仍需用真实账号验证,代码里已标 `VERIFY`,属 P4 打磨项。

## 发布到 Docker Hub + 异机部署(image 模式)

本机 build 推到 Docker Hub,目标机(如 ZimaOS)用 `docker-compose.dist.yml` 拉取安装,不在目标机 build。

> ⚠️ **架构必须匹配**:开发机若是 Apple Silicon(arm64),而目标机是 x86(amd64),
> 必须用 `buildx` 跨架构构建。amd64 在 arm64 上是 QEMU 模拟编译(himalaya/Rust + goimapnotify/Go),
> **会很慢(十几~几十分钟),属正常**。
>
> 🔒 **密钥永不进镜像/Git**:`gmail.pass` / `service-account.json` / `api-token` / `device-token`
> 单独传到目标机的 `config/`。镜像里只有程序。

### 1) Mac 上构建并推送(在 `server/` 目录,把 YOURUSER 换成你的 Docker Hub 用户名)

```bash
docker login
# 多架构 push 需要 container 驱动的 builder(只需建一次):
docker buildx create --name mp --driver docker-container --use --bootstrap

cd server
# 版本号:--build-arg APP_VERSION 从仓库根 VERSION 注入镜像(漏了服务端 /version 会显示 dev);
#         镜像 tag 也用同一个版本号。
# 目标机是 x86 ZimaOS → 只构 amd64(最快):
docker buildx build --platform linux/amd64 \
    --build-arg APP_VERSION=$(cat ../VERSION) \
    -t YOURUSER/mailpush:latest -t YOURUSER/mailpush:$(cat ../VERSION) --push .
# 两个架构都要(更通用、更慢):
# docker buildx build --platform linux/amd64,linux/arm64 \
#     --build-arg APP_VERSION=$(cat ../VERSION) \
#     -t YOURUSER/mailpush:latest --push .

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
# (CONFIG_PATH / IMAPNOTIFY_CONFIG 已在镜像 ENV 里有默认值,无需重复)

# 配置与密钥放到 ../config(= /DATA/AppData/mailpush/config)
cp config.sample.toml     ../config/config.toml         # 改账号(注意 backend.login 填真邮箱)
cp imapnotify.sample.yaml ../config/imapnotify.yaml     # 改账号
printf '%s' '16位AppPassword' > ../config/secrets/gmail.pass
cp /path/to/service-account.json ../config/service-account.json
openssl rand -hex 32 > ../config/api-token
# device-token 等安卓拿到 FCM token 后填

docker compose -f docker-compose.dist.yml up -d
docker compose -f docker-compose.dist.yml logs -f mail-watch
```

### 3) 更新版本

版本号唯一来源是**仓库根的 `VERSION` 文件**(server 与 app 共用)。升版本:改 `VERSION` → 按下面重建。

```bash
# Mac:改完 ../VERSION 后,重新 buildx build(务必带 --build-arg APP_VERSION,见上一步),--push
#      漏了 --build-arg → 服务端 /version 会显示 dev。
# 目标机:
docker compose -f docker-compose.dist.yml pull
docker compose -f docker-compose.dist.yml up -d
# 验证:curl -s http://localhost:8099/version   # 应为 {"version":"<VERSION 内容>"}
```

## 暴露给手机

`mail-api` 在 `:8099`。用现有 **Cloudflare Tunnel** 指向 `host:8099` + Access 策略,只允许本人设备。
**严禁把 8099 裸暴露公网**——它能读全部邮件、以你名义发信。

## API 速查

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` | 存活探针(无需鉴权) |
| GET | `/accounts` | 账号名列表 |
| GET | `/inbox?account=&folder=INBOX&page=1&page_size=50` | 收件列表 |
| GET | `/msg/{id}?account=&mark_read=false` | 读正文(默认不标已读) |
| POST | `/send` | 发信,body 见 `models.SendRequest` |
| POST | `/reply/{id}` | 回信,body 见 `models.ReplyRequest` |

除 `/healthz` 外都需 `Authorization: Bearer <api-token>`。

## 已知待打磨(P4)

- `/reply` 的 `template reply/send` flag 与模板注入需按实际输出微调(代码里已标 VERIFY)。
- `/msg` 返回的正文格式(HTML vs 纯文本)取决于 himalaya 默认;安卓 WebView 需要 HTML,可能要加 config `message.read.*` 或后处理。
- 多设备 device-token(现单设备写死一个文件)。
