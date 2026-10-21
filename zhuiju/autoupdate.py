# -*- coding: utf-8 -*-
"""访问网站时触发的后台自动更新（不使用系统计划任务）。

规则
  - 判断依据是 zhuiju/data/refresh_state.json：**当天**没有成功更新过 -> 需要更新。
    "当天"以几点为界是**设置项**（后台可改，存在 zhuiju/data/settings.json，默认凌晨 2 点，
    `ZHUIJU_REFRESH_HOUR` 环境变量再盖一层）：那点之前访问不触发新一天，之后当天没跑过才触发。
  - 需要更新时拉起一个独立进程跑 tools/refresh.py，请求线程不等待，
    所以页面照常返回**旧数据**，更新完成后文件被替换，刷新即拿到新数据
    （catalog.py 按文件 mtime 缓存，无需重启服务）。
  - 用锁文件避免反复访问把更新任务排队重复启动；锁超过 25 分钟视为上次进程已死，自动放行。
  - 一轮失败后进入 ZHUIJU_RETRY_MINUTES（默认 15 分钟）冷却：否则服务器上只要有人访问，
    就会每分钟重跑一遍注定失败的六步，既刷爆 logs 也白敲第三方接口。

跨平台
  解释器一律现找（python_bin()），不写死 .venv/Scripts/python.exe ——那是 Windows 的
  venv 布局，Linux（含宝塔面板建的 venv）在 bin/ 下面，写死就会 [Errno 8] Exec format error
  把六个步骤一起挂在同一行上。判活/终止也按平台分叉。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from . import settings

BASE = Path(__file__).resolve().parent.parent
STATE = BASE / "zhuiju" / "data" / "refresh_state.json"
PROGRESS = BASE / "zhuiju" / "data" / "refresh_progress.json"
LOCK = BASE / "logs" / "autoupdate.lock"
LOG = BASE / "logs" / "autoupdate.log"
REFRESH = BASE / "tools" / "refresh.py"
LOCK_TTL = 25 * 60          # 锁的有效期，超过认为上次进程已死
CHECK_TTL = 60              # 同一进程内多久才重新看一次状态文件，避免每次请求都读盘
# 一轮失败后多久才允许再自动重试；设 0 就是每次访问都重试
RETRY_MINUTES = int(os.environ.get("ZHUIJU_RETRY_MINUTES", "15"))

# 站点自己 + 各步骤子进程都要用到的依赖，用来判断某个解释器"是不是这个项目的 venv"
DEPS = ("flask", "requests")
# 常见 venv 目录名：本项目文档用 .venv，宝塔面板建的是 venv
VENV_NAMES = (".venv", "venv", "env")
_py_cache: list = []            # [(解释器路径, 说明)]，进程内只算一次
LAST_TRIGGER: list = []         # 最近一次 maybe_trigger 的结论，供 /api/refresh 排查

# 更新步骤的唯一清单：refresh.py 与页面进度都从这里取，避免两处各写一份对不上
STEPS = [
    {"key": "catalog", "label": "拉上游目录（gh-proxy 加速）",
     "script": "tools/build_catalog.py", "timeout": 300},
    {"key": "health", "label": "体检检索源",
     "script": "tools/probe_sources.py", "timeout": 420, "args": ["庆余年"]},
    {"key": "deep", "label": "从 TVBox 配置补抽接口",
     "script": "tools/harvest_more_apis.py", "timeout": 900},
    {"key": "merge", "label": "并入实测可用的新接口",
     "script": "tools/add_sources.py", "timeout": 120},
    {"key": "verify", "label": "验证各站搜索路径",
     "script": "tools/verify_get_templates.py", "timeout": 600},
    {"key": "templates", "label": "写入站内搜索模板",
     "script": "tools/build_templates.py", "timeout": 600},
]

_last_check = [0.0, False]  # (时间戳, 是否需要更新)


def logical_day(now: datetime | None = None) -> date:
    """以设置里那个小时为界的逻辑日期（后台可改，默认凌晨 2 点）。

    直接用自然日会有两个毛病：凌晨 1 点访问就把"今天"更新跑掉了，设定时间后又跑一次；
    反过来 23 点跑过的，第二天 00:30 访问会被判成"没更新"而白跑一趟。
    几点为界这件事现在是**每次现读设置**（settings 按文件 mtime 缓存，改了立刻生效），
    不是 import 时算死的常量 —— 后台里改完还要重启服务才会变，是最好查不出来的一类"设置没生效"。
    """
    now = now or datetime.now()
    return (now - timedelta(hours=settings.refresh_hour())).date()


# --------------------------------------------------------------------------- 解释器在哪
def is_windows() -> bool:
    """平台判定单独包一层：测试里要能模拟 Linux，不然跨平台这段永远没被验证过。"""
    return os.name == "nt"


def _usable(p: Path) -> bool:
    """文件在、且（非 Windows 下）真有执行位。软链接照常跟。"""
    try:
        if not p.is_file():
            return False
    except OSError:
        return False
    return True if is_windows() else os.access(str(p), os.X_OK)


def has_deps(exe: str) -> bool:
    """这个解释器里装没装本站依赖。说不清装没装，跑一句 import 最省事。

    探的就是自己（sys.executable）时用 importlib 就地查，省一次进程启动。
    """
    exe = str(exe or "")
    if not exe:
        return False
    try:
        # 只是"这是不是我自己"的比较，所以两边都 resolve；
        # 返回给调用方的路径一律不 resolve（见 python_info 里那条软链接的注释）
        same = Path(exe).resolve() == Path(sys.executable).resolve()
    except OSError:
        same = False
    if same:
        return all(importlib.util.find_spec(m) for m in DEPS)
    try:
        return subprocess.run([exe, "-c", "import " + ", ".join(DEPS)],
                              capture_output=True, timeout=25).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def venv_dir() -> str:
    """venv 建在站点外面（宝塔就是这样）时指到这里，不用改代码。"""
    return os.environ.get("ZHUIJU_VENV", "").strip()


def _candidates() -> list:
    """按"最可能是本站解释器"排序的候选：环境变量 > 正在跑站点的 > 站点目录里的 venv。"""
    out = []
    env = os.environ.get("ZHUIJU_PYTHON", "").strip()
    if env:
        out.append((env, "ZHUIJU_PYTHON 指定"))
    out.append((sys.executable, "当前跑站点的解释器"))
    roots = ([Path(venv_dir())] if venv_dir() else []) + [BASE / n for n in VENV_NAMES]
    for base in roots:
        if is_windows():
            out.append((str(base / "Scripts" / "python.exe"), f"{base.name} 虚拟环境"))
        else:
            for name in ("python", "python3"):
                out.append((str(base / "bin" / name), f"{base.name} 虚拟环境"))
    return [(str(p), why) for p, why in out if p]


def python_info() -> tuple:
    """选出来的解释器和选它的理由。进程内只算一次——探依赖要起子进程，不能每请求都探。

    这里以前写死 .venv/Scripts/python.exe，那是 Windows 的 venv 布局：Linux 在 bin/python，
    宝塔更把 venv 建到站点目录外面（/www/server/python_project/virtualenv_env/<名字>/）。
    写死的结果是要么路径不存在，要么 exec 到从 Windows 拷上来的 PE 文件，
    报 [Errno 8] Exec format error，六个步骤全挂在同一行上。
    """
    if _py_cache:
        return _py_cache[0]
    seen, chosen, first_usable = set(), None, None
    for exe, why in _candidates():
        if exe in seen or not _usable(Path(exe)):
            continue
        seen.add(exe)
        first_usable = first_usable or (exe, why)
        if has_deps(exe):
            # 原样留着这个路径，**不要 resolve()**：宝塔 venv 里的 bin/python 是指向真
            # 解释器的软链接，解析到真身之后就离开 venv 了，site-packages 跟着就没了，
            # 探依赖时明明齐全、跑起来却说 import 不到 flask
            chosen = (exe, f"{why} · 依赖齐全")
            break
    if chosen is None:
        chosen = first_usable or (sys.executable or "python3", "没找到可执行的解释器")
    _py_cache.clear()
    _py_cache.append(chosen)
    return chosen


def python_bin() -> str:
    """跑更新步骤该用的解释器路径。"""
    return python_info()[0]


def py_exe(script: str, args: str = "") -> str:
    """给页面/文档用的一行命令，粘了就能跑（venv 在外面时尤其重要）。"""
    return f"{python_bin()} {script} {args}".strip()


def retry_hint() -> str:
    """横幅里"怎么手动催更"。写死"双击 refresh.bat"在 Linux 上是句做不到的指引。"""
    if is_windows():
        return "双击 refresh.bat 立即更新"
    return f"跑 {py_exe('tools/refresh.py', '--force')} 可立即更新"


def next_retry_in(s: dict) -> int:
    """上一轮失败后的冷却还剩几秒；0 = 现在访问就该重试。

    读不出 finished_at（老状态文件、手动写的）就当不知道，不猜，直接允许重试。
    """
    if s.get("ok") or RETRY_MINUTES <= 0:
        return 0
    try:
        done = datetime.strptime(str(s.get("finished_at", "")), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return 0
    left = RETRY_MINUTES * 60 - (time.time() - done.timestamp())
    return max(0, int(left))


def progress() -> dict:
    """读后台更新写出的进度。

    "是否在跑"以锁文件里的子进程 PID 为准：子进程刚被拉起、还没来得及写进度文件时，
    页头也要能说"正在后台更新"；反过来子进程崩了、进度文件还停在 running=true，
    也不能一直谎报进行中。
    """
    p = {}
    try:
        p = json.loads(PROGRESS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        p = {}
    alive = running()
    if not alive:
        p["running"] = False
    total = max(1, int(p.get("total", len(STEPS))))
    return {
        "running": bool(alive),
        "pct": max(4, min(100, round(int(p.get("done", 0)) / total * 100))),
        "done": int(p.get("done", 0)),
        "total": int(p.get("total", len(STEPS))),
        "step_key": p.get("step_key", ""),
        "step_label": p.get("step_label", ""),
        "note": p.get("note", ""),
        "steps": p.get("steps", []),
        "seconds": p.get("seconds", 0),
        "started_at": p.get("started_at", ""),
        "finished_at": p.get("finished_at", ""),
        "result": p.get("result", ""),
    }


def _read_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _lock_age(lock: Path = LOCK) -> float:
    try:
        return time.time() - lock.stat().st_mtime
    except OSError:
        return 1e9


def pid_alive(pid: int) -> bool:
    """进程还在不在 —— 只探活，不发信号。

    单独包一层是给 strmjob 用的：它有自己的锁文件，但"这个 PID 还活着吗"的判据
    不该在两个模块各写一遍。Windows 上不能拿 os.kill(pid, 0) 探活
    （那在 Windows 语义里是"杀掉它"），只能开句柄读退出码；
    PROCESS_QUERY_LIMITED_INFORMATION 是 Vista 之后有的，科室那些 Win7 机器够用。
    """
    if is_windows():
        import ctypes

        STILL_ACTIVE = 259
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True         # 存在但不属于我，仍算在运行


def _lock_pid_alive(lock: Path = LOCK) -> bool:
    """锁里记了发起进程的 PID：进程已经不在了就不能再算"正在更新"，
    否则一次崩溃会让页面最长 TTL 时间内谎报进度。"""
    pid = _lock_pid(lock)
    return pid is not None and pid_alive(pid)


def detach_kwargs() -> dict:
    """脱离当前控制台的启动参数（两个平台都得处理，但理由不一样）。

      - Windows：不加 DETACHED_PROCESS，关掉那个 .bat 窗口时子进程跟着死，
        更新跑到一半就没声音了；
      - Linux/宝塔：不加 start_new_session，重启站点时面板发的 SIGTERM 会顺着
        进程组把正在跑一半的更新一起带走。
    """
    if is_windows():
        return {"creationflags": 0x00000008 | 0x00000200}   # DETACHED | NEW_PROCESS_GROUP
    return {"start_new_session": True}


def spawn(script: Path, log: Path, lock: Path, args=()) -> int:
    """脱离当前进程起一个子进程跑 script，把它的 PID 写进 lock，返回 PID。"""
    log.parent.mkdir(exist_ok=True)
    with open(log, "a", encoding="utf-8", buffering=1) as fh:
        fh.write(f"\n=== 访问触发后台任务 {script.name} "
                 f"{time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        # 用站点自己的解释器拉起：它在站点进程里跑起来，sys.executable 就是那个 venv
        # 里的 python，后面各步骤再按 python_bin() 现找
        child = subprocess.Popen([sys.executable, "-u", str(script), *args],
                                 cwd=str(BASE), stdout=fh, stderr=fh,
                                 close_fds=True, **detach_kwargs())
    # 锁里必须记**子进程** PID：记服务端自己的 PID 的话探活永远为真，
    # 子进程崩了页面还会一直显示"正在更新"
    lock.write_text(f"{child.pid} {time.time()}", encoding="utf-8")
    return child.pid


def running() -> bool:
    """有没有更新进程在跑。

    锁里的 PID 活着就是"在跑"，这一点优先于 LOCK_TTL：单个步骤最坏能到 15 分钟，
    整轮跑完也可能超过 25 分钟，用超时去推翻"进程明明还在"就会多起一个更新进程。
    TTL 只在读不出 PID 时（旧格式锁、权限问题）兜底。
    """
    if not LOCK.exists():
        return False
    if _lock_pid_alive():
        return True
    if _lock_pid() is None and _lock_age() < LOCK_TTL:
        return True                 # 锁里没有 PID 信息，只能按时间猜
    _clear_lock()
    return False


def _clear_lock() -> None:
    try:
        LOCK.unlink()
    except OSError:
        pass


def is_partial(s: dict) -> bool:
    """这一轮是不是"只跑了快版"（refresh.py --skip-deep）。"""
    if not s.get("ok"):
        return False
    if s.get("partial"):
        return True
    steps = s.get("steps") or {}
    return any((v or {}).get("skipped") for v in steps.values())


def _cycle_done(s: dict) -> bool:
    """状态文件里这一轮到底算不算"本周期完整跑完"。

    只跳步的快版（refresh.py --skip-deep，手动催更用）不能把当天的全量更新挡掉：
    老的状态文件没写 partial，就从 steps 里的 skipped 反推。
    """
    if not (s.get("ok") and not s.get("failed_steps")):
        return False
    return not is_partial(s)


def needs_update(now: datetime | None = None) -> bool:
    """当天（以设置里那个小时为界）没有完整成功更新过，才需要再跑。

    上一轮是失败的，还要看冷却：失败往往是环境性的（解释器不对、依赖没装、出网被挡），
    这种时候只要有人访问就重跑一遍注定失败的六步，等于每分钟敲一次第三方接口、
    往 logs 里灌一堆同样的 refresh-*.log。冷却过了 ZHUIJU_RETRY_MINUTES 自然又会试。
    """
    if running():
        return False
    s = _read_state()
    if s.get("date") == logical_day(now).isoformat() and _cycle_done(s):
        return False
    return next_retry_in(s) <= 0


def _spawn() -> None:
    spawn(REFRESH, LOG, LOCK)


def maybe_trigger() -> str:
    """给请求线程调用：只做文件判断，需要时丢一个后台进程，绝不阻塞响应。"""
    now = time.time()
    if _last_check[0] and now - _last_check[0] < CHECK_TTL:
        r = "running" if running() else ("stale" if _last_check[1] else "fresh")
    else:
        _last_check[0] = now
        need = needs_update()
        _last_check[1] = need
        if need:
            try:
                _spawn()
                r = "started"
            except Exception as exc:  # noqa: BLE001 - 起不来也不能影响页面
                _last_check[1] = False
                # 把解释器和目录权限带上：服务器上"更新没动静"八成是这两件事
                r = f"error: {type(exc).__name__}: {exc} (python={python_bin()})"
        else:
            r = "running" if running() else ("cooldown" if next_retry_in(_read_state()) > 0 else "fresh")
    LAST_TRIGGER.clear()
    LAST_TRIGGER.extend([r, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))])
    return r



def status() -> dict:
    s = _read_state()
    exe, why = python_info()
    return {
        "running": running(),
        "need_update": needs_update(),
        "server_pid": os.getpid(),
        "lock_pid": _lock_pid(),
        "date": s.get("date"),
        "ok": bool(s.get("ok")),
        "finished_at": s.get("finished_at"),
        "failed_steps": s.get("failed_steps") or [],
        "sources_enabled": s.get("sources_enabled"),
        "sources_total": s.get("sources_total"),
        "upstream_updated_at": s.get("upstream_updated_at"),
        "progress": progress(),
        # 这三项是为"服务器上更新没动静"准备的：用哪个解释器、为什么是它、
        # 失败冷却还剩多久、最近一次触发的结论。没有它们只能猜。
        "python": exe,
        "python_why": why,
        "retry_cmd": py_exe("tools/refresh.py", "--force"),
        "retry_in": next_retry_in(s),
        "retry_minutes": RETRY_MINUTES,
        "last_trigger": " ".join(map(str, LAST_TRIGGER)),
    }


def _lock_pid(lock: Path = LOCK) -> int | None:
    try:
        return int(lock.read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return None
