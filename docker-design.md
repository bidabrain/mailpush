# mailpush — 自建邮件推送 + 收发(ZimaOS / Docker)

服务器端:`himalaya envelope watch`(IMAP IDLE 监听)→ `push-fcm.py`(FCM HTTP v1)→ 自写安卓 app。
手机不存凭据、不维持持久 IMAP 连接。完整设计见 `mail-push-relay-design.md`。

## 为什么是 Docker

ZimaOS 是 Buildroot 做的**不可变系统、没有 apt/yum**,官方模型就是"一切跑容器"。所以
himalaya 不装宿主机,而是打进本镜像,用 `restart: always` 常驻,数据放 `/DATA/AppData/`。

## 目录布局(放在 ZimaOS 上)

```
/DATA/AppData/mailpush/
├── src/                       # 本仓库内容(Dockerfile、compose、脚本)
└── config/
    ├── config.toml            # 由 config.sample.toml 改名而来
    ├── service-account.json   # Firebase service account(发 FCM 用)
    ├── device-token           # 安卓 app 的 FCM token(单设备先手动填)
    ├── api-token              # 给 mail-api 的 bearer token(自己生成一串随机)
    └── secrets/
        └── gmail.pass         # Gmail app password(16 位,开 2FA 后生成)
data/  (= /DATA/AppData/mailpush/data，himalaya 可写状态，自动创建)
```

## 部署步骤(SSH + docker compose,最干净)

> ZimaOS 应用商店的"自定义安装"只接受 `image:` 的 compose,不接受 `build:`。
> 多文件自构建走 SSH 最省事;构建好后容器照样出现在 ZimaOS 面板里。

```bash
# 1. SSH 进 ZimaOS,放代码
mkdir -p /DATA/AppData/mailpush/config/secrets
cd /DATA/AppData/mailpush/src      # 把本目录文件传到这里

# 2. 准备 config 与密钥
cp config.sample.toml /DATA/AppData/mailpush/config/config.toml
vi /DATA/AppData/mailpush/config/config.toml          # 改成你的账户
printf '%s' '你的16位appcode' > /DATA/AppData/mailpush/config/secrets/gmail.pass
cp /path/to/firebase-service-account.json /DATA/AppData/mailpush/config/service-account.json
openssl rand -hex 32 > /DATA/AppData/mailpush/config/api-token
# device-token 等安卓 app 首次运行拿到 FCM token 后填:
#   echo '<fcm-device-token>' > /DATA/AppData/mailpush/config/device-token

# 3. 构建并起容器
docker compose up -d --build

# 4. 验证
docker logs -f mail-watch         # 应看到 envelope watch 启动;来新邮件时打印 [push] sent
curl -H "Authorization: Bearer $(cat /DATA/AppData/mailpush/config/api-token)" \
     "http://localhost:8099/inbox?account=gmail"
```

## 暴露给手机

`mail-api` 在 `:8099`。用你现有的 **Cloudflare Tunnel** 指向 `host:8099` + Access 策略,
只允许自己设备访问。**不要把 8099 裸暴露公网**——它能读全部邮件、以你名义发信。

## 关键验证点(Phase 1)

- 锁屏 + 断 WiFi 一段时间后发测试邮件,确认 FCM 推送**及时到达**且**手机不耗电**。
- 这一步通过,才继续做 Phase 2(API)和 Phase 3(安卓客户端读/写/回)。

## 待办 / 注意

- `himalaya envelope watch` 的确切 flag 用 `docker run --rm mailpush:latest himalaya envelope watch -h` 核对。
- 多账户:在 `config.toml` 加 `[accounts.xxx]` 块(各自带 watch hook),并把名字加进 compose 的 `ACCOUNTS`。
- Gmail 改 OAuth2:Dockerfile 的 features 加 `oauth2,keyring`,config 改 xoauth2 + token helper。
