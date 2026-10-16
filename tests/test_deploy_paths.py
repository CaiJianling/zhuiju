# -*- coding: utf-8 -*-
"""跨平台部署路径的离线测试（不联网、不起服务）。

    python tests/test_deploy_paths.py

覆盖的都是"在 Windows 上写、到 Linux/宝塔上才炸"的那类问题：解释器怎么找、
提示语该给哪条命令、shell 脚本的行尾与取值、Linux 下怎么找到监听端口的进程。
"""
import os
import re
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import zhuiju  # noqa: E402
from zhuiju import autoupdate as au, load_env_file  # noqa: E402

FAILS = []


def check(name, cond, got=None):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  got={got!r}"))
    if not cond:
        FAILS.append(name)


def clean_env():
    for k in ("ZHUIJU_PYTHON", "ZHUIJU_VENV"):
        os.environ.pop(k, None)
    au._py_cache.clear()


print("1) 解释器是现找的：Linux 的 venv 在 bin/，宝塔的 venv 甚至在站点外面")
exe, why = au.python_info()
check("选出来的解释器确实存在", Path(exe).is_file(), exe)
check("选出来的解释器装得齐本站依赖", au.has_deps(exe), {"exe": exe, "why": why})
check("理由不是空串", len(why) > 3, why)
check("python_bin() 与 python_info() 是同一个", au.python_bin() == exe)
check("sys.executable 在候选里（跑站点的那个）",
      any(p == sys.executable for p, _ in au._candidates()), [p for p, _ in au._candidates()])

real_win = au.is_windows
try:
    au.is_windows = lambda: False            # 在 Windows 上按 Linux 的目录布局看候选
    au._py_cache.clear()
    venv_c = [p for p, w in au._candidates() if "虚拟环境" in w]
    check("当成 Linux 时 venv 候选是 bin/python 与 bin/python3",
          bool(venv_c) and all(Path(p).parent.name == "bin" for p in venv_c), venv_c[:6])
    check("当成 Linux 时候选里不再有 Scripts/python.exe",
          not any("Scripts" in p for p in venv_c), venv_c[:6])
    check("催更提示给的是能直接粘的命令，而不是 refresh.bat",
          "refresh.bat" not in au.retry_hint() and "tools/refresh.py" in au.retry_hint(),
          au.retry_hint())
    outside = Path(tempfile.mkdtemp(prefix="zhuiju_env_out_"))
    os.environ["ZHUIJU_VENV"] = str(outside)  # 宝塔：venv 建在站点外面
    au._py_cache.clear()
    cands = [p for p, _ in au._candidates()]
    check("ZHUIJU_VENV 指的站点外 venv 进了候选",
          any(p.startswith(str(outside)) for p in cands), cands[:8])
    check("那个目录里没有可用解释器时退回跑站点的那个，而不是硬选它",
          au.python_bin() == sys.executable, au.python_bin())
    clean_env()
    os.environ["ZHUIJU_PYTHON"] = sys.executable
    au._py_cache.clear()
    check("ZHUIJU_PYTHON 指哪儿用哪儿", au.python_bin() == sys.executable, au.python_bin())
    # 关键：不能 resolve()。venv 里的 bin/python 常常是指向真解释器的软链接
    # （宝塔就是这样），解析到真身之后就离开 venv 了，site-packages 跟着丢，
    # 探依赖时明明齐全、真跑起来却说 import 不到 flask
    indirect = str((BASE / ".venv" / ".." / ".venv" / "Scripts" / "python.exe")
                   if real_win() else
                   BASE / ".venv" / ".." / ".venv" / "bin" / "python")
    if Path(indirect).is_file():
        os.environ["ZHUIJU_PYTHON"] = indirect
        au._py_cache.clear()
        check("带 .. 的路径原样保留，不做 resolve()", au.python_bin() == indirect, au.python_bin())
    else:
        os.environ["ZHUIJU_PYTHON"] = sys.executable + "."
        au._py_cache.clear()
        check("指错时也不会把路径解析成别的什么东西",
              au.python_bin() != str(Path(sys.executable + ".").resolve()), au.python_bin())
    au._py_cache.clear()
    os.environ["ZHUIJU_PYTHON"] = str(Path("Z:\\没有这个\\python.exe"))
    au._py_cache.clear()
    check("ZHUIJU_PYTHON 指错了也不崩，退回现找", Path(au.python_bin()).is_file(), au.python_bin())
finally:
    au.is_windows = real_win
    clean_env()
check("回到 Windows 后提示又变成 refresh.bat",
      ("refresh.bat" in au.retry_hint()) if real_win() else True, au.retry_hint())

print("\n2) 站点代码里不能再留 Windows 专属的写死路径")


def code_lines(text):
    """去掉整行注释，只比真正的代码 —— 注释里提一句"以前写死过什么"是允许的。"""
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))


names = ("tools/refresh.py", "zhuiju/app.py", "zhuiju/autoupdate.py", "run.py",
         "zhuiju/templates/admin.html", "zhuiju/templates/index.html")
src = {n: (BASE / n).read_text(encoding="utf-8") for n in names}
# 只抓真的"写死"：引号里的 .venv/Scripts 字面量、".venv" / "Scripts" 这种拼接、
# 或者直接 BASE / ".venv"。注释与文档字符串里提旧写法不算。
HARD = re.compile(r'["\']\.venv[/\\\\]Scripts|\.venv["\']\s*/\s*["\']Scripts|BASE\s*/\s*["\']\.venv')
for n in names:
    bad = HARD.findall(code_lines(src[n]))
    check(f"{n} 的代码里没有写死的 .venv 路径", not bad, bad)
check("refresh.py 的解释器来自 python_bin()",
      re.search(r"^PY = python_bin\(\)", src["tools/refresh.py"], re.M) is not None,
      re.findall(r"^PY = .*", src["tools/refresh.py"], re.M))
ad = src["zhuiju/autoupdate.py"]
check("autoupdate 两种 venv 布局都认：Windows 的 Scripts 与 Linux 的 bin，"
      "目录名也含宝塔常用的 venv",
      'base / "Scripts" / "python.exe"' in ad and 'base / "bin" / name' in ad
      and 'VENV_NAMES = (".venv", "venv", "env")' in ad)
check("admin.html 的归属地库命令用模板变量而不是写死路径", "{{ fetch_cmd }}" in src["zhuiju/templates/admin.html"])
check("app.py 的催更提示走 retry_hint()，源码里不再出现 refresh.bat",
      "autoupdate.retry_hint()" in src["zhuiju/app.py"] and "refresh.bat" not in src["zhuiju/app.py"],
      re.findall(r".*refresh\.bat.*", src["zhuiju/app.py"]))
check("run.py 早于端口默认值导入包（zhuiju.env 里的 ZHUIJU_PORT 才来得及生效）",
      src["run.py"].index("import zhuiju") < src["run.py"].index('os.environ.get("ZHUIJU_PORT"'))
check("run.py 在无图形界面的服务器上不去白折腾一次开浏览器",
      'os.environ.get("DISPLAY")' in src["run.py"])
check("失败冷却有开关，且默认不是 0",
      au.RETRY_MINUTES > 0 and "ZHUIJU_RETRY_MINUTES" in src["zhuiju/autoupdate.py"])

print("\n3) zhuiju.env 的读法：引号、注释、CRLF、未知键、已设环境变量优先")
tmp = Path(tempfile.mkdtemp(prefix="zhuiju_env_test_"))
p = tmp / "zhuiju.env"
p.write_bytes(b'# comment\r\nZHUIJU_PYTHON="D:\\x\\python.exe"\r\n'
              b"ZHUIJU_VENV = '/opt/venv'\nNOT_A_KEY=1\nZHUIJU_HOST=\n")
old_file = zhuiju.ENV_FILE
zhuiju.ENV_FILE = p
try:
    got = load_env_file()
    check("只认列出的键，未知键忽略", set(got) == {"ZHUIJU_PYTHON", "ZHUIJU_VENV"}, got)
    check("双引号被去掉", got.get("ZHUIJU_PYTHON") == "D:\\x\\python.exe", got)
    check("单引号与等号两侧空格都能读", got.get("ZHUIJU_VENV") == "/opt/venv", got)
    check("值为空的行忽略", "ZHUIJU_HOST" not in got, got)
    check("CRLF 文件不会把 \\r 带进值里", all("\r" not in v for v in got.values()), got)
    check("读进来的值确实进了 os.environ",
          os.environ.get("ZHUIJU_PYTHON") == "D:\\x\\python.exe", os.environ.get("ZHUIJU_PYTHON"))
    os.environ["ZHUIJU_PYTHON"] = "already-set"
    load_env_file()
    check("已设的环境变量优先，不被文件覆盖",
          os.environ["ZHUIJU_PYTHON"] == "already-set", os.environ["ZHUIJU_PYTHON"])
    zhuiju.ENV_FILE = tmp / "根本没有这个文件.env"
    check("没有 zhuiju.env 时返回空表而不是抛异常", load_env_file() == {})
finally:
    zhuiju.ENV_FILE = old_file
    clean_env()
check("清完临时设置后仍能选出可用解释器", Path(au.python_bin()).is_file(), au.python_bin())

print("\n4) refresh.sh：必须 LF、有 shebang、取值会剥掉引号与 \\r")
raw = (BASE / "refresh.sh").read_bytes()
sh = raw.decode("utf-8")
check("行尾是 LF（CRLF 传上服务器会得到 bad interpreter: /bin/sh^M）", b"\r\n" not in raw)
check("有 shebang", raw.startswith(b"#!/bin/sh"))
check("把 --force / --check-env 这些参数透传给 refresh.py", '"$@"' in sh)
check("先试 ZHUIJU_PYTHON，再退到 .venv|venv，再退到 python3",
      (lambda loop: loop.index("$ZHUIJU_PYTHON") < loop.index(".venv/bin/python")
       < loop.index("python3"))(
          [l for l in sh.splitlines() if l.startswith("for c in ")][0]))
check("候选要空跑一句 -c \"\" 验真能用（Windows 的 python3 是商店占位别名，command -v 也找得到）",
      '"$c" -c ""' in sh)
check("从 zhuiju.env 抠值时剥掉了引号和回车（CRLF 文件会让 exec 失败）",
      "tr -d" in sh and "\\r" in sh and "\\\"" in sh,
      [l.strip() for l in sh.splitlines() if "tr -d" in l])
check("找不到解释器时给的是可照做的提示", "ZHUIJU_PYTHON=" in sh)
check("示例配置写了宝塔那种站点外 venv",
      "ZHUIJU_PYTHON" in (BASE / "zhuiju.env.example").read_text(encoding="utf-8"))
check("zhuiju.env 被 git 忽略（里面可能写口令）",
      re.search(r"^zhuiju\.env$", (BASE / ".gitignore").read_text(encoding="utf-8"), re.M) is not None)
check(".gitattributes 强制 .sh 用 LF、.bat 用 CRLF",
      "*.sh text eol=lf" in (BASE / ".gitattributes").read_text(encoding="utf-8")
      and "*.bat text eol=crlf" in (BASE / ".gitattributes").read_text(encoding="utf-8"))

print("\n5) Linux 下按 /proc 找监听端口的进程（在 Windows 上造一棵假 /proc 验证解析）")
sys.path.insert(0, str(BASE / "tools"))
import restart  # noqa: E402

fake = Path(tempfile.mkdtemp(prefix="zhuiju_proc_"))
(fake / "net").mkdir()
HEX = format(5000, "04X")                 # 5000 = 0x1388，/proc 里地址与端口都是 16 进制
# 表头 12 个名字，数据行只有 10 个字段（tx_queue:rx_queue 与 tr:tm->when 各自合成一个），
# 所以 inode 落在 f[9]：照表头数列位会取到 uid/timeout，端口永远匹配不上
HDR = ("  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  "
       "timeout inode\n")
(fake / "net" / "tcp").write_text(HDR +
    f"   0: 0100007F:{HEX} 00000000:0000 0A 00000000:00000000 00:00000000 00000000"
    "     0        0 111 1 0000000000000000 100 0 0 10 0\n"
    f"   1: 0100007F:{HEX} 0100007F:9999 01 00000000:00000000 00:00000000 00000000"
    "     0        0 222 1 0000000000000000 100 0 0 10 0\n"
    "   2: 00000000:0050 00000000:0000 0A 00000000:00000000 00:00000000 00000000"
    "     0        0 333 1 0000000000000000 100 0 0 10 0\n", encoding="ascii")
(fake / "net" / "tcp6").write_text(HDR +
    "   0: 00000000000000000000000001000000:" + HEX +
    " 00000000000000000000000000000000:0000 0A 00000000:00000000 00:00000000 00000000"
    "     0        0 444 1 0000000000000000 100 0 0 10 0\n", encoding="ascii")
links = {"1234": "socket:[111]", "5678": "socket:[222]", "99": "socket:[444]"}
for pid in links:
    d = fake / pid / "fd"
    d.mkdir(parents=True)
    (d / "0").write_text("", encoding="ascii")


def fake_readlink(path):
    return links.get(Path(path).parent.parent.name, "pipe:[1]")


pids = restart._proc_listen_pids(5000, proc=fake, readlink=fake_readlink)
check("找到 v4 与 v6 上监听 5000 的两个 PID", pids == [99, 1234], pids)
check("同端口的 ESTABLISHED 行没被误当成监听", 5678 not in pids, pids)
check("别的端口的 LISTEN 不算",
      restart._proc_listen_pids(80, proc=fake, readlink=fake_readlink) == [])
check("没有 /proc 时返回空表而不是抛（拿不到就老实说拿不到）",
      restart._proc_listen_pids(5000, proc=fake / "没有", readlink=fake_readlink) == [])
check("判活/终止按平台分叉，Linux 用 os.kill 而不是 windll",
      "os.kill" in (BASE / "tools" / "restart.py").read_text(encoding="utf-8")
      and "signal.SIGKILL" in (BASE / "tools" / "restart.py").read_text(encoding="utf-8"))
check("站点自己的判活也分叉，Linux 不碰 kernel32",
      "is_windows()" in (BASE / "zhuiju" / "autoupdate.py").read_text(encoding="utf-8"))

print("\n6) 环境不对时要一次说清，而不是六个步骤各抛一遍")
sys.path.insert(0, str(BASE / "tools"))
import refresh  # noqa: E402  只是 import，不会开跑（真跑在 main() 里）

real_hd, real_pi = refresh.has_deps, refresh.python_info
try:
    refresh.has_deps = lambda exe: False
    msg = refresh.preflight()
    check("依赖不齐时给的是能照做的 pip 命令（带上清华源）",
          "pip install -r requirements.txt" in msg and "tsinghua" in msg, msg)
    check("顺带把要装到哪个解释器上写清楚了", refresh.python_info()[0] in msg, msg)
    refresh.python_info = lambda: ("Z:\\不存在\\python.exe", "测试造的坏路径")
    check("解释器根本不存在时也报得出来", "找不到解释器" in refresh.preflight(), refresh.preflight())
    refresh.python_info = real_pi
    refresh.has_deps = lambda exe: True
    check("环境正常时 preflight 返回空串（不打扰正常流程）", refresh.preflight() == "")
finally:
    refresh.has_deps, refresh.python_info = real_hd, real_pi
check("refresh.py 里有 --check-env 这个只看不跑的开关",
      "--check-env" in (BASE / "tools" / "refresh.py").read_text(encoding="utf-8"))

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
