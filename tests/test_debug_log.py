# -*- coding: utf-8 -*-
"""控制台日志的开关：默认静默，--debug 入参重开并可定等级。

    python tests/test_debug_log.py

钉的是三件事：
  - create_app 之后 werkzeug 必须在 WARNING：访问行是 INFO，不抬上去的话一次搜索
    （十几个接口 + 轮询 + 海报代理）几秒就把启动窗口滚过一屏，真正的报错反而被淹没；
  - run.py 那条 --debug 入参的接线：等级表、入参默认接 ZHUIJU_DEBUG、开了才 setLevel，
    而且必须排在 import app 之后（不然会被 create_app 里那份默认值盖回去）；
  - 等级表只认 debug/info/warning/error（warn 是别名），认不出来要报人话，不是 traceback。
"""
import logging
import re
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tests"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 先把配置指到临时目录再 import（zhuiju.app 在模块级就 create_app 了一次），
# 不然这一跑会往真实那台机器的 data/ 里写东西。
TMP = Path(tempfile.mkdtemp(prefix="zhuiju_log_test_"))
from zhuiju import admin as admin_mod    # noqa: E402
from zhuiju import settings as settings_mod  # noqa: E402
from zhuiju import stats as stats_mod    # noqa: E402
admin_mod.CONFIG = TMP / "admin.json"
settings_mod.PATH = TMP / "settings.json"
stats_mod.DB = TMP / "stats.db"
stats_mod.DATA = TMP
stats_mod._ready = False

import gate_off      # noqa: E402
from zhuiju import app as app_mod  # noqa: E402

FAILS = []


def check(name, cond, got=None):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  got={got!r}"))
    if not cond:
        FAILS.append(name)


run_py = (BASE / "run.py").read_text(encoding="utf-8")
app_py = (BASE / "zhuiju" / "app.py").read_text(encoding="utf-8")

try:
    print("1) 默认静默：create_app 之后 werkzeug 在 WARNING，访问行（INFO）不再上控制台")
    gate_off.off(TMP / "gate")
    app_mod.create_app()
    check("werkzeug 的级别是 WARNING（访问行是 INFO，ERROR 的堆栈照样出）",
          logging.getLogger("werkzeug").level == logging.WARNING,
          logging.getLevelName(logging.getLogger("werkzeug").level))
    check("这份默认值写在 create_app 里（flask CLI / run.py / 测试哪个入口进来都安静）",
          'logging.getLogger("werkzeug").setLevel(logging.WARNING)' in app_py
          and app_py.index("setLevel(logging.WARNING)") > app_py.index("def create_app"), None)

    print("\n2) --debug 入参：开了才重开日志，等级由入参给")
    check("入参是可选值的那种（--debug 等于 --debug info；--debug debug 才是细档）",
          'add_argument("--debug", nargs="?", const="info"' in run_py
          and "ZHUIJU_DEBUG" in run_py, None)
    check("等级表就四档（warn 是 warning 的别名），与 logging 对齐",
          '"debug": logging.DEBUG' in run_py and '"info": logging.INFO' in run_py
          and '"warning": logging.WARNING' in run_py and '"error": logging.ERROR' in run_py, None)
    check("开了才 setLevel/basicConfig，且排在 import app 之后（否则被默认值盖回去）",
          re.search(r"if args\.debug:\s*\n\s*level = LOG_LEVELS", run_py) is not None
          and run_py.index("logging.getLogger(\"werkzeug\").setLevel(level)") >
          run_py.index("from zhuiju.app import app"), None)
    check("认不出的等级直接说人话退出，不是 traceback",
          "不认识的日志等级" in run_py, None)
    check("关着的时候启动行会说一句去哪儿开（不然这开关等于没写）",
          "控制台日志：{log_note}" in run_py and "log_note" in run_py, None)

    print("\n3) 等级表自检：LOG_LEVELS 里每一档都能对回 logging 的常量")
    levels = dict(re.findall(r'"(\w+)": (logging\.\w+)', run_py))
    ok = True
    for name, const in levels.items():
        val = getattr(logging, const.split(".")[1])
        if name == "warn":
            ok = ok and val == logging.WARNING
        else:
            ok = ok and val == getattr(logging, name.upper())
    check("每一档的名字与常量一致", ok and "debug" in levels and "error" in levels, levels)

finally:
    print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
