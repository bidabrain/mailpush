<p align="center">
  <img src="icon.png" alt="Melon Mail" width="128" height="128" />
</p>

<h1 align="center">Melon Mail 🍉</h1>

自建**邮件推送 + 收发**系统:服务器盯着多个 IMAP 邮箱,新邮件经 **FCM 推送**到自写的安卓客户端;
客户端只跟服务器的私有 API 通信,读正文 / 回信 / 发信等 IMAP/SMTP 操作全在服务器完成。
**手机不存任何邮箱凭据、不维持持久 IMAP 连接**(只靠系统级 FCM 连接,省电)。

## 架构

```
                    ┌──────────── 服务器(Docker,常驻插电)────────────┐
 Gmail / 其他 IMAP ◄┤ goimapnotify(IMAP IDLE 监听)─新邮件─► push-fcm ──FCM──► 安卓 app(弹通知)
  (邮件留在原 provider)│ imaplib 连接池(读列表/正文/附件/回复模板) ◄ FastAPI ─┐                          │
                    │ smtplib(发信/回信)                              │◄── 私有 JSON/multipart API ──► 安卓 app(读/写/回)
                    └──────────────────────────────────────────────────┘
```

- **监听**:goimapnotify(纯 RFC2177 IDLE,兼容 Gmail)
- **引擎**:Python `imaplib` **持久连接池**(读列表/正文/附件 + 生成回复转发模板)
  —— **0.2.0 起**取代原 himalaya CLI 后端(见下「变更日志」)
- **发信**:Python smtplib(直连 SMTP,不碰 IMAP)
- **API**:FastAPI(bearer 鉴权;**须置于 HTTPS 之后**)
- **管理后台**:独立的内网 web 界面(密码登录,管理 app token + 看状态),**独立端口、仅限局域网**
- **推送**:FCM HTTP v1 + Firebase Admin SDK(data message,多设备)
- **客户端**:Kotlin + Jetpack Compose + Material 3

## 目录

| 路径 | 内容 |
|---|---|
| [`server/`](server/) | 服务端(Docker 镜像:goimapnotify + FastAPI + Python imaplib/smtplib)。部署见 `server/README.md` |
| [`android/`](android/) | 安卓客户端(Compose)。构建见 `android/README.md` |
| `mail-push-relay-design.md` | 整体设计文档 |
| `docker-design.md` | Docker / ZimaOS 部署设计 |

## 功能

- 多账号收件箱 + **统一收件箱**(跨账号合并,各账户**并发拉取**)
- **未读数**:统一收件箱顶部显示总未读;账户列表每个账户显示各自未读(服务端 IMAP `SEARCH UNSEEN` 全量统计)
- **查看已发邮件**(自动探测各账号的「已发」文件夹,收件箱顶部一键切换)
- **置顶(pin)邮件**:右滑置顶,固定在收件箱与统一收件箱顶部;置顶内容单独缓存,不被自动清理;邮件在服务器端被删或取消置顶时自动移除
- 下拉刷新 + 上拉无限加载;未读/已读区分(打开即标已读)
- **HTML 正文**用 WebView 渲染(默认禁远程图防跟踪,可一键显示);**跟随系统暗色主题**
- 查看 / 下载附件(保存到设备)
- 写信 / 回复 / 回复全部 / **转发**,均**支持附件**(转发自动带原附件);收件人可从手机通讯录选
- 删除邮件(列表左滑 / 详情页,带确认,同步服务器移回收站)
- 详情页可展开看完整发件人/收件人地址
- **离线缓存**:无网时可看已加载的收件箱与读过的正文;正文缓存有容量上限自动回收(置顶豁免)
- FCM 推送,多设备自动注册(token 自动上报);点通知直达对应邮件
- **内网管理后台**(独立端口):图形化**管理多个 app token**(每台设备一个);**删某 token 连带切断其推送设备**,丢设备一键同时断「读信 + 推送」;查看版本/运行状态、管理推送设备;app 端 token 输入框掩码显示

## 快速上手(从零跑起来)

> 服务端用**官方预构建镜像**免构建直接拉;只有安卓 app 需要你本地编译(因为要放你自己的 Firebase 配置)。

**前置**:Docker + docker compose;编译 app 需 Android Studio 或 Android SDK(`./gradlew`);一个免费 **Firebase 项目**,从中拿两个文件——服务端发 FCM 用的 `service-account.json`、安卓 app 用的 `google-services.json`(**两者必须同一个 Firebase 项目**)。

```bash
# 1) 克隆
git clone https://github.com/bidabrain/mailpush && cd mailpush

# 2) 编译安卓 app(放入你自己的 google-services.json 覆盖占位文件)
cp /path/to/google-services.json android/app/google-services.json
( cd android && ./gradlew assembleDebug )      # 产物:android/app/build/outputs/apk/debug/app-debug.apk → 装到手机

# 3) 服务端:准备配置 + 密钥(都放 server/config,已被 .gitignore 忽略)
cd server
mkdir -p config/secrets data
cp .env.sample .env
#   编辑 .env:取消注释 CONFIG_DIR=./config 与 DATA_DIR=./data(让配置落在 server/config、server/data)
cp config.sample.toml     config/config.toml          # 改成你的账号(host/login/email)
cp imapnotify.sample.yaml config/imapnotify.yaml      # 同样的账号(监听用)
printf '邮箱应用专用密码' > config/secrets/gmail.pass   # 每个账号一个 .pass(名字与 config 里 auth.cmd 对应)
printf '管理后台密码'    > config/secrets/admin.pass    # 内网管理后台登录用
cp /path/to/service-account.json config/service-account.json   # Firebase 服务端密钥

# 4) 拉官方镜像并运行(docker-compose.dist.yml 默认就指向 bidabrain/mailpush:latest)
docker compose -f docker-compose.dist.yml pull
docker compose -f docker-compose.dist.yml up -d

# 5) 建 token → 连 app
#   内网浏览器开 http://<服务器内网IP>:8098,用管理密码登录 → 给手机「新建 Token」
#   app 设置里填:服务器地址 + 该 Token(地址生产环境务必走 HTTPS,见「安全」)
```

完成后:发封测试邮件,手机应收到 FCM 推送;点开能读正文、回信、发信。

- **架构匹配**:官方镜像是 `linux/amd64`。arm64 机器(树莓派等)需自行 `buildx` 构建,详见 [`server/README.md`](server/README.md)。
- **自己构建服务端**:`docker compose up -d --build`,或 `buildx --push` 发到自己的 Docker Hub,见 `server/README.md`。
- ⚠️ **上线前务必读「安全」**:API(8099)要放 HTTPS 之后,管理后台(8098)只能内网。

详细说明见 [`server/README.md`](server/README.md) 与 [`android/README.md`](android/README.md)。

## 版本控制

仓库根的 **[`VERSION`](VERSION)** 文件是**唯一版本号来源**,server 和 app 构建时都从它读取,二者版本号保持一致。

- **安卓 app**:`android/app/build.gradle.kts` 在构建时读 `VERSION` → 自动设为 `versionName`,并由 `x.y.z` 推导出 `versionCode`(`x*10000 + y*100 + z`)。正常 `./gradlew assembleDebug` / `installDebug` 即可,无需手改。
- **服务端**:版本经 Docker **build-arg** 注入镜像(环境变量 `MAILPUSH_VERSION`),并由 `GET /version`、`GET /healthz` 暴露。构建时带上 build-arg:
  ```bash
  # buildx 发布镜像
  docker buildx build --platform linux/amd64 \
      --build-arg APP_VERSION=$(cat ../VERSION) \
      -t <user>/mailpush:latest --push .
  # 本地 compose 构建
  export APP_VERSION=$(cat ../VERSION) && docker compose up -d --build
  ```
  (不传 build-arg 时默认 `dev`,不影响运行。)
- **app 设置页**会显示**当前 app 版本**与**所连服务器的版本**,方便核对两端是否一致。

**升版本**:改 `VERSION` 一个文件 → 重新构建 app 与镜像即可。

## 变更日志

### 0.2.0
- **收信引擎从 himalaya(Rust CLI)切换为 Python `imaplib` 持久连接池**(`server/app/imap_pool.py` + `imap_client.py`)。动机与收益:
  - **提速**:连接复用,免去每次新建连接的握手开销(对会做反向 DNS、新连接要等数十秒的 IMAP 服务器尤其明显)。
  - **解锁网易 163/126 读信**:在代码层登录后发 IMAP ID(RFC 2971),解决 himalaya v1.2.0 不支持 ID 导致的读信失败。
  - **构建更快更小**:去掉 Rust 编译阶段,Docker 镜像构建从约 20 分钟降到约 1 分钟。
  - **零迁移**:`config.toml` 等用户配置与 API 形状不变,无需改配置、安卓端无需改动。
- 安卓端体验:
  - 统一收件箱**并发拉取**各账户(整轮耗时≈最慢账户,而非各账户之和);
  - **未读数**:统一收件箱顶部总未读 + 账户列表各账户未读(新增 `/unread`、`/unread-all` 端点);
  - 统一/单账户**共享新鲜度**:统一刷过的账户点进去不再重复拉;`loadUnified` 防并发 + 新鲜度跳过;
  - 双击底部「统一」图标回到列表顶部;根页连按两次返回彻底退出;
  - 「已发」文件夹探测失败可自愈(不缓存 null,下次重试)。
- **内网管理后台(mail-admin)+ 多 app token**:
  - 新增独立容器 `mail-admin`(默认端口 8098,**仅限内网**),密码登录后可**新建/删除多个 app token**(每台设备一个,丢设备直接吊销该 token,无需改配置/全量轮换),并显示版本与运行状态;
  - **推送设备与 app token 绑定**:FCM 推送 token 记录其注册时所用的 app token;后台**删 app token 会连带删除其名下推送设备** → 丢设备一键同时切断「读信」和「推送」(否则旧 FCM token 仍会把发件人/主题推到丢失设备);后台也可单删/清空推送设备;
  - `require_auth` 接受后台管理的多 token,**兼容**旧的单 `/config/api-token`;**默认不再预设固定 token**(走后台管理);
  - 关闭 FastAPI 自动文档(`/docs`、`/redoc`、`/openapi.json`),减少接口结构泄露;
  - app 端「API Token」输入框改为掩码显示。
- **himalaya 已从代码与镜像中移除。**

### 0.1.0
- 首个 beta:goimapnotify 监听 + himalaya 引擎 + smtplib 发信 + FCM 推送 + 安卓客户端。

## 安全

凭据(邮箱密码、token、Firebase 私钥、管理密码)只存服务器/本机,**不进 Git**(见 `.gitignore`)。

两个端口,安全要求**完全不同**,务必分清:

- 🔒 **API(mail-api,默认 8099)必须放在 HTTPS 之后**。它能读全部邮件、以你名义发信,且 uvicorn 跑的是**明文 HTTP**——直接裸暴露公网会让 **bearer token 和邮件内容被明文嗅探**。用 **Cloudflare Tunnel**(提供 HTTPS + 出站连接)对外暴露,**严禁把 8099 经路由器端口转发直连公网**。token 用强随机值(后台生成的即是),走 HTTPS 传输。
- 🚫 **管理后台(mail-admin,默认 8098)只能内网访问,绝不可暴露公网**。它能增删 token、看状态,是你的"钥匙串管理处"。**不要**给它配 Cloudflare Tunnel、**不要**在路由器上转发 8098。只想本机访问可在 compose 把端口写成 `127.0.0.1:8098:8098`。

**多 token + 吊销**:给每台设备建独立 token;设备丢失时**内网登录后台删除该 token 即可**(即时生效,不影响其他设备),无需全量轮换。
注意:后台仅内网 → 人在外面丢手机需回到局域网(或 VPN 回家)才能吊销。

## 状态

服务端 + 安卓主体功能均已实现并跑通(本地编译 / 真机验证)。

## 致谢

本项目站在这两个优秀开源项目的肩膀上,在此致谢:

- **[goimapnotify](https://gitlab.com/shackra/goimapnotify)** —— 纯 RFC 2177 IMAP IDLE 监听,新邮件实时触发;兼容 Gmail,无 QRESYNC 依赖。本项目用它做推送监听端。
- **[himalaya](https://github.com/pimalaya/himalaya)**(Pimalaya)—— 命令行 IMAP/SMTP 客户端。本项目 **0.1.x 的邮件引擎**(读列表 / 读正文 / 列附件 / 生成回复转发模板);**0.2.0 起改用 Python `imaplib` 自实现连接池**,不再依赖 himalaya。感谢它在早期阶段让项目快速跑通。

感谢以上项目的作者与维护者。

## Star History

<a href="https://www.star-history.com/?type=date&repos=bidabrain%2Fmailpush">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=bidabrain/mailpush&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=bidabrain/mailpush&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=bidabrain/mailpush&type=date&legend=top-left" />
 </picture>
</a>
