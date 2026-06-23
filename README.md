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
- **API**:FastAPI(bearer 鉴权)
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

## 快速开始

1. **服务端**:见 [`server/README.md`](server/README.md) —— 准备 `config.toml` + 密钥,`docker compose up -d --build`;发布到 Docker Hub 后可在 ZimaOS 等机器 `image` 模式部署。
2. **安卓端**:见 [`android/README.md`](android/README.md) —— 放 `google-services.json`(Firebase),Android Studio 构建;app 内填服务器地址 + API token。
3. **Firebase**:服务端 `service-account.json` 与 安卓 `google-services.json` 须来自**同一个** Firebase 项目。

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
- **himalaya 已从代码与镜像中移除。**

### 0.1.0
- 首个 beta:goimapnotify 监听 + himalaya 引擎 + smtplib 发信 + FCM 推送 + 安卓客户端。

## 安全

API 能读全部邮件、以你名义发信。**务必放在 Cloudflare Tunnel 之后 + 强 bearer token**,
严禁裸暴露公网。凭据(邮箱密码、token、Firebase 私钥)只存服务器/本机,**不进 Git**(见 `.gitignore`)。

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
