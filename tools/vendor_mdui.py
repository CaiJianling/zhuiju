# -*- coding: utf-8 -*-
"""把 MDUI 2 的运行时文件取回本地：zhuiju/static/vendor/mdui/。

为什么要 vendor，而不是按 MDUI 文档那样从 CDN 引
  这站点是跑在 127.0.0.1 / 科室局域网里的本地工具，装机环境经常没有外网出口，
  或者只有国内能连上的镜像。`unpkg.com` 一旦拿不到，页面里的 mdui-* 组件全部退化成
  裸文本（组件样式在 JS 注册的 shadow DOM 里，mdui.css 只有设计令牌），
  等于整站没有界面。把两个文件放进 static/ 就没这个依赖了：本地一条 HTTP 请求搞定。

为什么用 npm 的 tarball 而不是 npm install
  装机的机器上未必要有 Node。这里只做一件事：从国内可达的 registry 拉 mdui 的 .tgz，
  从里面挑三个文件出来 —— 用标准库（urllib + tarfile）就够，不需要 node/npm。
  要换版本只改下面的 MDUI_VERSION。

用法
    python tools/vendor_mdui.py            # 取回（已存在且版本一致则跳过）
    python tools/vendor_mdui.py --force    # 强制重新取
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "zhuiju" / "static" / "vendor" / "mdui"
VERSION_FILE = OUT / "VERSION"

# 只带这三样：样式令牌 + 全量组件 + 许可证。包里的 components/ functions/ *.d.ts
# 是给打包器按需导入用的，本项目直接吃 mdui.global.js 这个自包含 bundle。
WANT = ("mdui.css", "mdui.global.js", "LICENSE")

# 国内可达的镜像源；上游 registry.npmjs.org 在这里经常连不上（与 pip 用清华源同理）
REGISTRIES = ("https://registry.npmmirror.com", "https://registry.npmjs.org")

# 钉版本，不跟 latest：这一版是量过界面才用的，自动升级等于让某次跑脚本悄悄换掉全站配色
MDUI_VERSION = "2.1.5"


def current_version() -> str:
    """已经 vendor 下来的版本，没有就读不到。"""
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def latest(reg: str) -> str:
    """问 registry 要 latest —— 只在 MDUI_VERSION 被留空、且本地也还没 vendor 过时用。"""
    req = urllib.request.Request(f"{reg}/mdui", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))["dist-tags"]["latest"]


def tarball_url(reg: str, version: str) -> str:
    """优先问 registry 要 dist.tarball（镜像上的路径不一定按通用规则），拿不到就按 npm 的通用形式拼。"""
    try:
        req = urllib.request.Request(f"{reg}/mdui/{version}", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))["dist"]["tarball"]
    except Exception:  # noqa: BLE001 - 拿不到元数据不算失败，通用 URL 够用
        return f"{reg}/mdui/-/mdui-{version}.tgz"


def extract(tarball_url: str) -> dict[str, bytes]:
    with urllib.request.urlopen(tarball_url, timeout=60) as r:
        raw = r.read()
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            name = m.name.split("/", 1)[-1]          # npm 的包一律装在 package/ 下
            if name in WANT:
                out[name] = tf.extractfile(m).read()  # type: ignore[union-attr]
    missing = [w for w in WANT if w not in out]
    if missing:
        raise SystemExit(f"tarball 里没找到这些文件：{missing}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="取回本地版 MDUI 2 运行时文件")
    ap.add_argument("--force", action="store_true", help="已存在也重新取")
    ap.add_argument("--version", default="", help="指定 mdui 版本，默认取 registry 的 latest")
    a = ap.parse_args()

    have = current_version()
    # 优先级：命令行 > 已经 vendor 的那份 > 脚本里钉的版本。留空 MDUI_VERSION 才去问 latest
    want = a.version or have or MDUI_VERSION
    if not want:
        for reg in REGISTRIES:
            try:
                want = latest(reg)
                break
            except Exception as exc:  # noqa: BLE001
                print(f"  {reg} 问版本失败：{exc}")
    if not want:
        print("拿不到 mdui 的版本（两个 registry 都连不上？），把 MDUI_VERSION 写死在脚本里再跑。")
        return 2
    if have == want and not a.force:
        print(f"已经是 mdui {want}，不用重取（要重来加 --force）")
        return 0

    errs = []
    files = None
    for reg in REGISTRIES:
        try:
            url = tarball_url(reg, want)
            print(f"  从 {reg} 取 mdui@{want} 的 tarball…")
            files = extract(url)
            break
        except Exception as exc:  # noqa: BLE001
            errs.append(f"{reg}: {type(exc).__name__}: {exc}")
    if files is None:
        print("取失败：\n  " + "\n  ".join(errs))
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    for name, blob in files.items():
        (OUT / name).write_bytes(blob)
        print(f"  写入 {name}（{len(blob) // 1024} KB）")
    VERSION_FILE.write_text(want + "\n", encoding="utf-8")
    print(f"完成：mdui {want} → {OUT}")
    print("页面里的引用（必须在 app.css 之前）：\n"
          '  <link rel="stylesheet" href="/static/vendor/mdui/mdui.css">\n'
          '  <script src="/static/vendor/mdui/mdui.global.js"></script>')
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    raise SystemExit(main())
