# -*- coding: utf-8 -*-
"""离线测试用的一个开关：把真人门禁关掉。

这些文件测的是 SEO 渲染、图片代理、明细合流、STRM 采集……不是"能不能过滑块"。
门禁开着时它们每个 HTTP 请求都会先被 423 挡住，测试红了还把人往错的方向引
（"是不是我搜索逻辑写坏了"）。唯一测门禁本身的是 tests/test_human.py。

必须在各文件已经把 settings.PATH / stats.DB 指到临时目录之后再调用，
不然这一行会把真实那台机器上的 data/settings.json 改掉。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zhuiju import settings as settings_mod  # noqa: E402


def off(tmp_dir) -> Path:
    p = Path(tmp_dir)
    p.mkdir(parents=True, exist_ok=True)
    settings_mod.PATH = p / "settings.json"
    settings_mod._cached.update(mtime=None, vals={})
    ok, err = settings_mod.set_value("human_gate", 0)
    assert ok, f"临时设置目录写不进去：{err}"
    settings_mod._cached.update(mtime=None, vals={})
    return settings_mod.PATH
