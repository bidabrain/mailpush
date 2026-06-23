#!/usr/bin/env python3
"""输出某账号的裸 access token(给 config.toml 的 auth.cmd / imapnotify.yaml 的 passwordCmd 调)。

只打印 token 本身(无多余换行),失败则非 0 退出、错误进 stderr。
"""
import sys

import oauth


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: oauth_token.py <account>", file=sys.stderr)
        return 2
    try:
        sys.stdout.write(oauth.get_token(sys.argv[1]))
    except oauth.OAuthError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
