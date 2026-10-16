# -*- coding: utf-8 -*-
"""追剧资源搜索本地站点。

导入这个包就会顺手读站点根目录的 zhuiju.env（如果存在）。放这儿而不是各模块里，
是因为 admin/app/autoupdate 都会在 import 阶段读环境变量（口令、secret_key、端口、
"当天"几点为界），谁先被导入谁就得先看到这些值。
"""
from __future__ import annotations

import os
from pathlib import Path

__version__ = "1.0"

BASE = Path(__file__).resolve().parent.parent
ENV_FILE = BASE / "zhuiju.env"
# 只认这几个键，别的行一律忽略；已经设了的环境变量优先，不被文件里的值覆盖
ENV_KEYS = ("ZHUIJU_PYTHON", "ZHUIJU_VENV", "ZHUIJU_PORT", "ZHUIJU_HOST",
            "ZHUIJU_REFRESH_HOUR", "ZHUIJU_RETRY_MINUTES", "ZHUIJU_NO_BROWSER",
            "ZHUIJU_ADMIN_PASSWORD", "ZHUIJU_SECRET_KEY")


def load_env_file() -> dict:
    """读 zhuiju.env：KEY=VALUE 一行一个，# 开头是注释，值两边的引号会被去掉。

    为什么要这个文件：宝塔把 venv 建在站点外面（例如
    /www/server/pyporject_evn/zhuiju/bin/python），而面板里给每个脚本单独设环境变量很麻烦。
    有了它就只需要改这一个文件 —— 站点进程、refresh.sh、手动跑的 tools/*.py 全都认它。
    必须早于各模块读 os.environ 之前调用，所以放在包导入时。
    """
    got: dict[str, str] = {}
    try:
        raw = ENV_FILE.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return got
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k in ENV_KEYS and v:
            got[k] = v
            os.environ.setdefault(k, v)
    return got


load_env_file()
