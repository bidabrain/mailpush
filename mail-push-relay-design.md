# 自建邮件推送 + 收发服务 — 设计文档

> **这份文档的用途**:这是一个个人项目的完整设计。下次新开 chat 时,把这份 MD 贴给 Claude 并说"继续这个项目",它就能完整理解上下文、已做的决策、被否决的方案,以及接下来要写什么。文档刻意写得自包含,不依赖任何之前的对话记忆。

---

## 1. 一句话目标

在自己的服务器上跑一个服务,它**监听多个 IMAP 邮箱(含 Gmail)**,新邮件到达时通过 **FCM 推送通知**到一个**自己写的安卓客户端**;安卓客户端**只与服务器的私有 API 通信**,所有"读正文 / 回信 / 发信"等 IMAP/SMTP 操作都在**服务器端**完成。手机上**不存任何邮箱凭据**,也**不维持任何持久 IMAP 连接**。

### 核心动机(为什么要这么做)
1. **省电**:现状用 Thunderbird 手机端,它为每个账户各维持一条后台 IMAP IDLE/轮询连接,耗电。把这些连接挪到服务器(插着电),手机只保留一条 FCM 连接(复用 Google Play Services 全局连接,零额外成本)。
2. **凭据安全**:邮箱密码只存在服务器,手机丢了也不泄露。
3. **完全掌控**:自己写客户端 + 自己定 API,不受现成软件限制。

---

## 2. 关键决策:为什么不用 JMAP / 不用现成方案

> 这一节很重要,**避免新对话重新讨论已经否决的路线**。

| 方案 | 结论 | 否决原因 |
|---|---|---|
| Webmail 聚合器(Cypht / Roundcube) | ❌ | 浏览器前端,无法原生推送到手机 app;且不满足"自写客户端"诉求 |
| goimapnotify / himalaya watch → ntfy/FCM(仅通知) | ⚠️ 部分采用 | 只解决"通知",不解决"读正文 + 回信"。但 watch 这一环最终保留(见下) |
| Fork K-9 / Thunderbird-Android + FCM 触发同步 | ❌ | 技术可行且优雅,但 fork 大型 Kotlin 工程、长期 rebase upstream 维护成本高 |
| **JMAP 瘦客户端架构**(Stalwart 服务器 + Ltt.rs/Twake 客户端) | ❌ **整条线否决** | ① Stalwart 是**完整邮件服务器(MTA)**,不是聚合器:不原生拉取外部 IMAP(需 fetchmail 胶水)、发信要配 relay、带全套 MTA 运维负担。② JMAP 手机客户端(Ltt.rs)是 proof-of-concept、"还没法日用",且与 Stalwart 兼容有坑。③ IMAP→JMAP 代理(jmap-perl、jmap-proxy-python)全是 PoC、官方警告勿用于敏感数据。**整个 JMAP 自托管栈不成熟。** |

### 最终决策
**完全砍掉 JMAP。** 推理:JMAP 的唯一价值是"标准协议让现成客户端能连",但现成 JMAP 客户端都不成熟;**既然客户端反正要自己写,就用自己设计的简单 JSON API 取代 JMAP**,两端都自己掌控,从而绕开"需要一台 JMAP 服务器"的全部麻烦。

服务器端的"邮件引擎"用 **Himalaya**(Pimalaya 项目的 Rust CLI 邮件客户端),它把 IMAP/SMTP 的脏活(尤其是**回信的正确性**)全包了。

> **关于 mirador(已排除)**:Pimalaya 还有个独立的 IMAP 监听 binary 叫 mirador。但 **Himalaya 自身已内置 `envelope watch` 命令**,功能完全覆盖(IDLE 监听 + notify/cmd hook),mirador 只是把同一能力抽成独立 binary。本项目**只用 Himalaya 一个 binary** 同时做监听和引擎,不引入 mirador,少一个组件/配置/进程。仅当你想把监听做成与引擎隔离的精简独立守护进程时,mirador 才有意义——本项目不需要。

---

## 3. 最终架构

```
                            ┌──────────────────── 服务器(自托管,常驻插电)─────────────────────┐
                            │                  ▌同一个 Himalaya binary▐                          │
  Gmail / 其他 IMAP  ◄──────┤  himalaya envelope watch (IMAP IDLE)  ──hook{sender}{subject}──► push-fcm.sh │──FCM HTTP v1──► 安卓 app(弹通知)
   (邮件始终在原 provider) │                                                                  │
                            │  himalaya (envelope list / message read / template reply / send) │
                            │      ▲                                                            │
                            │      └── 薄 HTTP API (FastAPI 或 Rust axum,鉴权 + 业务逻辑)       │◄──自定义 JSON API──► 安卓 app(读/写/回)
                            └──────────────────────────────────────────────────────────────────┘
```

**两条独立的数据线,但底层是同一个 Himalaya binary + 同一份 config**:
- **推送线**(`himalaya envelope watch` → hook → FCM):只负责"提醒有新邮件 + 谁 + 标题"。
- **API 线**(`himalaya` 各命令 ← 薄 HTTP API):负责"拉收件列表 / 读正文 / 写信 / 回信 / 发信"。

手机端永远只连服务器 API,**从不直接连 Gmail**。

---

## 4. 组件详细设计

### 4.1 服务器 · 推送线(Himalaya 自带 watch)

Himalaya(https://github.com/pimalaya/himalaya)内置 `himalaya envelope watch` 命令,IMAP IDLE 监听,hook 原生带 `{id}` / `{subject}` / `{sender}` 占位符,**无需回连 IMAP 抓 header**。事件有 `envelope.watch.received`(新邮件)和 `envelope.watch.any`(其他);hook 可叠加(同时 notify + cmd)。

配置示意(`~/.config/himalaya/config.toml` 的账户块内。**注意 Himalaya 重构频繁,确切 key/命令以当前版本 `himalaya envelope watch -h` 和 CHANGELOG 为准**):
```toml
[accounts.gmail]
backend.type = "imap"
backend.host = "imap.gmail.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "you@gmail.com"
backend.auth.type = "password"            # app password;或 OAuth2(xoauth2/oauthbearer + 外部 token helper 如 ortie)
backend.auth.cmd = "cat /etc/mailpush/gmail.pass"   # 或走 keyring / pass

# 发信后端(回信/发信用)
message.send.backend.type = "smtp"
message.send.backend.host = "smtp.gmail.com"
message.send.backend.port = 465
message.send.backend.login = "you@gmail.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "cat /etc/mailpush/gmail.pass"   # 与 IMAP 共用 app password
message.send.save-copy = true             # 发出的信自动存 Sent

# 推送触发(watch hook)
envelope.watch.received.notify.summary = "Gmail: {sender}"
envelope.watch.received.notify.body = "{subject}"
envelope.watch.received.cmd = "/etc/mailpush/push-fcm.sh '{sender}' '{subject}' gmail"

# 每个其他 IMAP 账户重复一个 [accounts.xxx] 块
```

**运行**:每个账户起一个 `himalaya envelope watch -a gmail`(只盯 INBOX)。在 ZimaOS 上跑在 `mail-watch` 容器里,由一个 entrypoint 脚本按 `ACCOUNTS` 给每个账户拉起一个 watch + 自动重启循环,容器 `restart: always`(不用 systemd,见第 11 节)。

**push-fcm.sh**(建议 Python + Firebase Admin SDK,自动处理 OAuth2 token):
```python
#!/usr/bin/env python3
import sys, firebase_admin
from firebase_admin import credentials, messaging

firebase_admin.initialize_app(credentials.Certificate("/etc/mailpush/service-account.json"))
sender, subject, account = sys.argv[1], sys.argv[2], sys.argv[3]
DEVICE_TOKEN = open("/etc/mailpush/device-token").read().strip()  # 单设备先写死

messaging.send(messaging.Message(
    token=DEVICE_TOKEN,
    data={"sender": sender, "subject": subject, "account": account},  # data message
    android=messaging.AndroidConfig(priority="high"),                 # 绕 Doze
))
```

### 4.2 服务器 · API 线

**同一个 Himalaya binary**当引擎,外面包一层**自己的薄 HTTP API**。Himalaya 每个命令都支持 `--output json` / `-o json`,适合脚本化。

端点 → himalaya 命令映射:

| 自定义 API | 底层 himalaya 命令 |
|---|---|
| `GET /accounts` | (读配置) |
| `GET /inbox?account=gmail` | `himalaya envelope list -a gmail -m INBOX -o json` |
| `GET /msg/{id}?account=gmail` | `himalaya message read {id} -a gmail -t html -s -o json` |
| `POST /reply/{id}` | `himalaya template reply {id} -a gmail` → 填正文 → `himalaya message send -a gmail`(或 `template send`) |
| `POST /send` | `himalaya message send -a gmail < message.eml` |

**Himalaya 替你解决的关键脏活**:内置 compose/reply/forward,`template reply/forward` 输出结构化模板/JSON,**自动处理 `In-Reply-To` / `References` / 引用原文 / 正确的 From / Cc** —— 这正是自己写最容易错的部分。

**性能**:himalaya 默认每次调用开新 TCP+TLS+SASL 会话。配合 **sirup**(把预认证 IMAP/SMTP 会话暴露成 Unix socket,himalaya 指过去复用握手)消除每次操作的延迟。

**两个引擎实现选择**:
- **方案 A(先做这个)**:Python FastAPI / Go,`subprocess` shell out 调 himalaya CLI。最快上手,个人用足够,配 sirup 解决延迟。
- **方案 B(想长期维护再升级)**:直接用 Pimalaya 的 `io-email` Rust 库写 axum 服务,无 subprocess、会话常驻、最干净。

### 4.3 安卓客户端(自己写)

**关键性质:客户端没有任何 IMAP/SMTP 逻辑**,只做两件事——调服务器 API + 收 FCM。

要写的部分:
- 收件列表 UI ← `GET /inbox`(Retrofit / OkHttp)
- **正文阅读:`WebView` 渲染 HTML 正文,默认禁远程图片**(防 tracking pixel)— 主要复杂点
- 写信 / 回复 UI → `POST /send` `/reply`
- `FirebaseMessagingService`:`onMessageReceived` 弹通知(data message,取 `sender`/`subject`);`onNewToken` 上报 token(单设备先写死)
- 通知点击 → deep-link 到 app 内对应邮件

凭据安全、HTML 渲染细节、threading 全在服务器,手机端纯前端消费。

---

## 5. 关键技术约束与坑(务必遵守,避免重新踩)

1. **Gmail 认证**:不能用普通账户密码(Less Secure Apps 已彻底关停)。只能:
   - **App Password**(推荐先用):需先开 2-Step Verification,生成 16 位码,当 IMAP **和** SMTP 密码用(两边共用一个)。
   - **OAuth2 / XOAUTH2**:更安全但要建 Google OAuth app + 维护 token 刷新(Himalaya 可用外部 token helper 如 ortie 提供 bearer)。
2. **发信走原账户的上游 SMTP**(如 `smtp.gmail.com`),让 From = 真实地址。**因此完全不需要自建发信信誉**(无 SPF/DKIM/DMARC/PTR、不碰 25 端口、不愁垃圾箱)。这是本方案相对"自建邮件服务器"的核心优势。
3. **发出的信要存到该账户的 `Sent` 文件夹**:Himalaya 用 `message.send.save-copy = true` 处理;确认实际生效。
4. **FCM 用 HTTP v1**:旧的 server-key API 已于 2024 年关停。必须用 service account + OAuth2(用 Firebase Admin SDK 自动换 token)。消息用 **data message + `priority: high`**(后台可靠触发 + 绕 Doze)。token 会轮换,`onNewToken` 要更新服务器。
5. **`envelope watch` 每 folder 一条 IDLE 连接** → 每账户只 watch `INBOX`,别挂一堆 label / `[Gmail]/All Mail`。
6. **Gmail 可以不进自建推送**:Gmail 官方 app 自带原生推送(零电量)。本套推送主要服务**其他 IMAP 账户**。是否让 Gmail 也走自建推送,看个人偏好(统一 vs 省事)。
7. **读正文不要误标已读**:确认 himalaya `message read` 的标记行为(`-s` sanitize、`-t html` 优先 HTML);必要时用只读方式。
8. **Gmail 搜索受限**:himalaya 的 `envelope search` 走服务器端 UID SORT,Gmail 不支持(见上游 issue #698)。本项目核心流程用 `envelope list`(分页)不受影响,但别依赖跨账户 search。
9. **API 安全(必须)**:这个 API 能读全部邮件 + 以你名义发信。**必须加鉴权(token / mTLS),不能裸奔。** 推荐放在 **Cloudflare Tunnel** 后面 + Access 策略,只允许自己的设备连(本人已在用 Cloudflare Tunnel)。
10. **WebView 禁远程图片**:`settings.blockNetworkImage = true` 类似设置,防 tracking pixel。

---

## 6. 待定参数(新对话时需要先确认)

1. **除 Gmail 外有几个 IMAP 账户、分别哪些 provider?**(决定 himalaya 配置规模)
2. **引擎走方案 A(Python 包 CLI)还是 B(Rust 库)?**(建议先 A)
3. **Gmail 用 app password 还是 OAuth2?**(建议先 app password 跑通)
4. **Gmail 是否也走自建推送,还是用 Gmail app?**

---

## 7. 实施计划(建议顺序)

- **Phase 0 · 验证引擎**:服务器装 himalaya,配 1 个 IMAP 账户,命令行确认能 `envelope list` / `message read` / `template reply` + `send`。
- **Phase 1 · 推送线**:构建 mailpush 镜像,起 `mail-watch` 容器(`himalaya envelope watch` + push-fcm.py);安卓写最小 `FirebaseMessagingService`。**实测锁屏/断网下推送是否及时、耗不耗电。** 这是省电目标的验证点。
- **Phase 2 · API 线**:薄 HTTP API(方案 A)over himalaya;加鉴权;挂 Cloudflare Tunnel。
- **Phase 3 · 安卓客户端**:收件列表 + WebView 正文(禁远程图)+ 写信/回复 UI。
- **Phase 4 · 打磨**:Sent 保存验证、多账户切换、错误处理、离线缓存、通知 deep-link。

> **范围现实提示**:加入"看正文 + 回信"后,这是一个**几周的真实项目**(服务器 API + 带 HTML 渲染和 compose 的安卓 app),不是周末玩具。但区别于被否决的 JMAP 路线:**这里每个零件(Himalaya、FCM)都是成熟稳定件,无实验性赌注**。是用工程量换确定性。

---

## 8. 技术栈速查

| 层 | 选型 | 说明 |
|---|---|---|
| IMAP 监听 + 邮件引擎 | **Himalaya**(Rust CLI, Pimalaya) | **一个 binary 全包**:`envelope watch` 监听(hook 带 {sender}/{subject})+ IMAP 读 / SMTP 发 / reply 正确性 |
| 会话复用 | **sirup**(Pimalaya) | 可选,消除 himalaya 每次握手延迟 |
| API 层 | FastAPI(A)或 axum + io-email(B) | 自定义 JSON API,需鉴权 |
| 推送 | **FCM HTTP v1** + Firebase Admin SDK | data message, priority high |
| 暴露/安全 | **Cloudflare Tunnel** + Access | API 不裸奔 |
| 客户端 | 自写 Android(Java/Kotlin) | Retrofit + WebView + FCM,无 IMAP 逻辑 |
| 常驻 | **Docker `restart: always`**(ZimaOS) | 不用 systemd —— 见第 11 节部署 |
| 宿主 | **ZimaOS**(Buildroot/不可变/无 apt) | 一切跑容器;数据在 `/DATA/AppData/` |

> **已排除**:mirador(Pimalaya 独立 watch binary)—— 功能被 Himalaya 内置 `envelope watch` 覆盖,本项目不用。

---

## 9. 参考链接

- Himalaya CLI(监听 + 引擎): https://github.com/pimalaya/himalaya
- Himalaya CHANGELOG(确认 `envelope watch` 当前用法): https://github.com/pimalaya/himalaya/blob/master/CHANGELOG.md
- Pimalaya 项目总览: https://github.com/pimalaya
- io-email 库(方案 B): https://github.com/pimalaya(io-email)
- sirup(会话复用): https://github.com/pimalaya
- FCM HTTP v1 / 迁移: https://firebase.google.com/docs/cloud-messaging/migrate-v1
- Firebase Admin SDK: https://firebase.google.com/docs/admin/setup

---

## 10. 开发者背景(供校准技术深度)

- 经验丰富的 Android 开发者(原生 Java、Material 3,已 ship 过 app)。
- 自托管基础设施完善:Cloudflare Tunnel、Tailscale、自建多种服务。
- 熟悉 Python;能上手 Rust。
- 沟通用简体中文 + 英文技术术语。

→ 文档与后续对话可假设高技术水平,直接给可运行的配置/代码,不必从基础概念讲起。

---

## 11. 部署(ZimaOS / Docker)

**宿主是 ZimaOS**:Buildroot 做的不可变系统,**无 apt/yum 包管理器**,官方模型是"一切跑容器"。因此:
- ❌ 不在宿主机装 himalaya(install.sh / cargo / nix 都不合适,宿主只读且无工具链)。
- ✅ 把 himalaya + 推送脚本 + API **打进一个自己的 Docker 镜像**,用 `restart: always` 常驻,数据放 `/DATA/AppData/`。

### 容器结构(随附脚手架 `mailpush/`)
- **镜像**:多阶段 Dockerfile —— stage1 `rust:slim` 用 `cargo install --git ... --features imap,smtp,rustls-ring` 编出 himalaya;stage2 `python:slim` 装 fastapi/firebase-admin,拷入 himalaya 二进制 + 脚本。
- **两个 service(同一镜像)**:
  - `mail-watch`:跑 `watch-entrypoint.sh`,按 `ACCOUNTS` env 给每个账户拉起 `himalaya envelope watch` + 自动重启循环。hook 调 `push-fcm.py` 发 FCM。
  - `mail-api`:跑 `uvicorn api:app`,暴露 `:8099`,给手机调。
  - 两者**不互相通信**,默认 bridge 即可(ZimaOS 默认 bridge 无容器间 DNS,但这里用不到)。
- **卷**:`/DATA/AppData/mailpush/config:/config:ro`(config.toml、service-account.json、device-token、api-token、secrets/gmail.pass)+ `/DATA/AppData/mailpush/data:/data`(himalaya 可写状态 sled id-map/cache,`XDG_DATA_HOME`/`XDG_CACHE_HOME` 指向它)。

### 部署方式
- **首选:SSH + `docker compose up -d --build`**(放 `/DATA/AppData/mailpush/src`)。ZimaOS 应用商店"自定义安装"只接受 `image:` 的 compose,不接受 `build:`,所以多文件自构建走 SSH 最省事;构建后容器照样出现在 ZimaOS 面板。
- 备选:本地/CI 构建镜像推到 GHCR,compose 里改用 `image: ghcr.io/...`,再走应用商店粘贴 compose。

### 暴露
`mail-api:8099` 用现有 **Cloudflare Tunnel** 指过去 + Access 策略,只允许本人设备。**严禁裸暴露公网**(能读全部邮件 + 以你名义发信)。

### 与 systemd 的取代关系
之前文档提到的"systemd 常驻"在 ZimaOS 上**不适用**,改由 **Docker `restart: always`** 承担常驻 + 崩溃重启。
