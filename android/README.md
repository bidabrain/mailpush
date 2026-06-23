# Melon Mail · Android 客户端

自写安卓客户端:**只与 server 的私有 API 通信 + 收 FCM 推送**,不存任何邮箱凭据、不连 IMAP。
对应设计 Phase 3。UI 参照仓库根 `UI.png` 设计稿(蓝色平面化、卡片、底部导航)。

## 技术栈

- **Kotlin + Jetpack Compose + Material 3**
- Navigation Compose(账户列表 → 收件箱 → 详情 → 回复/撰写 / 设置)
- Retrofit + kotlinx.serialization(调 server API)
- DataStore(存 server 地址 / API token / FCM token)
- Firebase Cloud Messaging(收 data message 弹通知)
- 锁定版本:AGP 8.7.3 / Gradle 8.11.1 / Kotlin 2.0.21 / Compose BOM 2024.12.01 / Firebase BOM 33.7.0
- minSdk 26,targetSdk/compileSdk 35,applicationId `com.melonmail.app`

## 屏幕(对照 UI.png)

| 设计稿 | 实现 |
|---|---|
| 01 账户列表 | `AccountsScreen` — 账户卡片(头像/名称)+ 底部导航(账户/设置)。来自 `GET /accounts` |
| 02 邮件列表 | `InboxScreen` — 搜索框(本地过滤)+ 头像行。来自 `GET /inbox` |
| 03 邮件详情 | `MessageScreen` — 主题/发件人/正文 + 底部「回复 / 回复全部」。来自 `GET /msg/{id}` |
| 04/05 回复/撰写 | `ComposeScreen` — 字段 + 右上发送。`POST /reply/{id}` / `POST /send` |
| 08 设置 | `SettingsScreen` — 服务器地址/Token + FCM token 展示(复制/刷新) |

> 说明:设计稿里的未读数、正文预览、附件、抄送/密送等依赖服务端暂未提供的数据,已做降级
> (服务端 `/msg` 当前返回纯文本,见 server 端 P4)。视觉风格、布局、按键样式按设计稿还原。

## 必做:配置 Firebase(否则收不到推送)

1. 到 [Firebase 控制台](https://console.firebase.google.com) 新建项目(或用与 server 同一个项目)。
2. 添加 Android 应用,**包名填 `com.melonmail.app`**。
3. 下载 `google-services.json`,替换 `app/google-services.json`(仓库里现有的是**占位文件**,
   能让工程编译/运行,但拿不到真实 FCM token,推送不会送达)。
4. server 端用的 `service-account.json` 要来自**同一个** Firebase 项目。

> `app/google-services.json` 已在仓库根 `.gitignore` 忽略,不会被 push。

## 构建运行

用 Android Studio 打开 `android/` 目录直接构建运行,或命令行:

```bash
cd android
export ANDROID_HOME=$HOME/Library/Android/sdk   # 若未设
./gradlew assembleDebug                          # 产物 app/build/outputs/apk/debug/
# 安装到已连接设备:
./gradlew installDebug
```

首次构建会下载 Gradle 8.11.1 + AGP/Compose/Firebase 依赖;若缺 SDK 组件,Android Studio 会提示安装
(或 `sdkmanager "platforms;android-35" "build-tools;35.0.0" "platform-tools"`)。

## 首次使用流程

1. 打开 app → 右下/底部进「设置」,填 **服务器地址**(Cloudflare Tunnel 的 https 地址)和 **API Token**
   (server 的 `/config/api-token` 内容)。
2. 回到账户列表,应能看到账户;点进去看收件箱、读信、回复/写信。
3. 在「设置」复制 **FCM Device Token**,填到 server 的 `/config/device-token`(单设备),推送即可送达。

## 已知 / 待打磨

- 正文为纯文本渲染(server `/msg` 暂无 HTML);后续可在服务端出 HTML 后用 WebView(禁远程图)。
- 未读数 / 预览 / 附件 / 抄送密送:待服务端补数据后再加。
- 单设备 device-token 先手动同步;多设备后续做服务端注册接口。
- launcher 图标用 `icon.png` 切的各密度 PNG;如需自适应/主题图标,可用 Studio 的 Image Asset 重做。
