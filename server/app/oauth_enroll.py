#!/usr/bin/env python3
"""一次性设备码授权:python oauth_enroll.py <account>。

终端会打印验证 URL + 用户码,用任意设备浏览器打开同意后,refresh token 存进
/data/oauth/<account>.cache.bin。之后 oauth_token.py 会自动静默刷新。
前提:/config/oauth/<account>.json 里已填好 client_id(见 oauth.py 头部说明)。
"""
import sys

import oauth


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: oauth_enroll.py <account>", file=sys.stderr)
        return 2
    try:
        oauth.enroll(sys.argv[1])
    except oauth.OAuthError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
