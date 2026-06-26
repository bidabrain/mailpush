#!/usr/bin/env python3
"""把 webui 账户(/data/accounts.json)渲染成 goimapnotify 配置,与 /config 的手写 base 合并。

用法: render_imapnotify.py [base.yaml] [out.yaml]   (默认 /config/imapnotify.yaml → /data/imapnotify.generated.yaml)
  - base 里手写的 configurations[] 原样保留(兼容现有);
  - webui 账户(push=true)追加;同名 alias 时 webui 覆盖手写块;
  - 输出到 out(原子替换)。base 不存在则只有 webui 账户。

YAML 不可用时退化输出 JSON —— JSON 是合法 YAML,goimapnotify 照样能读。
"""
from __future__ import annotations

import json
import os
import sys

import accounts

try:
    import yaml  # PyYAML
except Exception:  # noqa: BLE001
    yaml = None


def _load_base(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    if yaml is None:
        sys.stderr.write(f"[render] 警告:无 PyYAML,无法解析 base {path},手写监听账户将被忽略\n")
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[render] 警告:解析 base {path} 失败({exc}),忽略\n")
        return {}


def render(base_path: str, out_path: str) -> int:
    base = _load_base(base_path)
    confs = list((base.get("configurations") or []))
    webui = [r for r in accounts.load() if r.get("push", True)]
    names = {r["name"] for r in webui}
    # 同名:webui 覆盖手写块(去掉 base 里 alias 撞名的)
    confs = [c for c in confs if c.get("alias") not in names]
    confs.extend(accounts.to_imapnotify(r) for r in webui)

    out = {"configurations": confs}
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if yaml is not None:
            yaml.safe_dump(out, f, allow_unicode=True, sort_keys=False)
        else:
            json.dump(out, f, ensure_ascii=False)  # 合法 YAML
    os.replace(tmp, out_path)
    return len(confs)


def main() -> int:
    """退出码:0=有监听账户;3=渲染成功但 0 个账户(调用方应空转等待,别启动 goimapnotify);1=错误。"""
    base_path = sys.argv[1] if len(sys.argv) > 1 else "/config/imapnotify.yaml"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "/data/imapnotify.generated.yaml"
    try:
        n = render(base_path, out_path)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[render] 渲染失败: {exc}\n")
        return 1
    print(f"[render] 写出 {out_path}:{n} 个监听账户", flush=True)
    return 0 if n > 0 else 3


if __name__ == "__main__":
    sys.exit(main())
