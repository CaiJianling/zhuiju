# -*- coding: utf-8 -*-
"""访问网站时触发的后台自动更新（不使用系统计划任务）。

规则
  - 判断依据是 zhuiju/data/refresh_state.json：**当天**没有成功更新过 -> 需要更新。
    "当天"以凌晨 ZHUIJU_REFRESH_HOUR（默认 2 点）为界：2 点前访问不触发新一天，
    2 点后只要当天跑过就不再跑。
  - 需要更新时拉起一个独立进程跑 tools/refresh.py，请求线程不等待，
    所以页面照常返回**旧数据**，更新完成后文件被替换，刷新即拿到新数据
    （catalog.py 按文件 mtime 缓存，无需重启服务）。
  - 用锁文件避免反复访问把更新任务排队重复启动；锁超过 25 分钟视为上次进程已死，自动放行。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
STATE = BASE / "zhuiju" / "data" / "refresh_state.json"
PROGRESS = BASE / "zhuiju" / "data" / "refresh_progress.json"
LOCK = BASE / "logs" / "autoupdate.lock"
LOG = BASE / "logs" / "autoupdate.log"
REFRESH = BASE / "tools" / "refresh.py"
LOCK_TTL = 25 * 60          # 锁的有效期，超过认为上次进程已死
CHECK_TTL = 60              # 同一进程内多久才重新看一次状态文件，避免每次请求都读盘
# "一天"以凌晨几点为界：2 点前访问不算新的一天，不触发；2 点后当天没跑过才触发
REFRESH_HOUR = int(os.environ.get("ZHUIJU_REFRESH_HOUR", "2"))

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
    """以 REFRESH_HOUR 为界的逻辑日期。

    直接用自然日会有两个毛病：凌晨 1 点访问就把"今天"更新跑掉了，2 点后又会再跑一次；
    反过来 23 点跑过的，第二天 00:30 访问会被判成"没更新"而白跑一趟。
    """
    now = now or datetime.now()
    return (now - timedelta(hours=REFRESH_HOUR)).date()


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


def _lock_age() -> float:
    try:
        return time.time() - LOCK.stat().st_mtime
    except OSError:
        return 1e9


def _lock_pid_alive() -> bool:
    """锁里记了发起进程的 PID：进程已经不在了就不能再算"正在更新"，
    否则一次崩溃会让页面最长 TTL 时间内谎报进度。"""
    try:
        pid = int(LOCK.read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return False
    if os.name == "nt":
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
        os.kill(pid, 0)     # 只是探活，不发信号
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True         # 存在但不属于我，仍算在运行


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
    """当天（以凌晨 REFRESH_HOUR 为界）没有完整成功更新过，才需要再跑。"""
    if running():
        return False
    s = _read_state()
    return not (s.get("date") == logical_day(now).isoformat() and _cycle_done(s))


def _spawn() -> None:
    LOCK.parent.mkdir(exist_ok=True)
    with open(LOG, "a", encoding="utf-8", buffering=1) as fh:
        fh.write(f"\n=== 访问触发后台更新 {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        flags = 0
        if os.name == "nt":
            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP：不跟随控制台的生死
            flags = 0x00000008 | 0x00000200
        child = subprocess.Popen([sys.executable, "-u", str(REFRESH)], cwd=str(BASE),
                                 stdout=fh, stderr=fh, creationflags=flags,
                                 close_fds=True)
        # 锁里必须记子进程 PID：记服务端自己的 PID 的话，探活永远为真，
        # 子进程崩了页面还会一直显示"正在更新"
        LOCK.write_text(f"{child.pid} {time.time()}", encoding="utf-8")


def maybe_trigger() -> str:
    """给请求线程调用：只做文件判断，需要时丢一个后台进程，绝不阻塞响应。"""
    now = time.time()
    if _last_check[0] and now - _last_check[0] < CHECK_TTL:
        return "running" if running() else ("stale" if _last_check[1] else "fresh")
    _last_check[0] = now
    need = needs_update()
    _last_check[1] = need
    if need:
        try:
            _spawn()
            return "started"
        except Exception as exc:  # noqa: BLE001 - 起不来也不能影响页面
            _last_check[1] = False
            return f"error: {type(exc).__name__}"
    return "running" if running() else "fresh"


def status() -> dict:
    s = _read_state()
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
    }


def _lock_pid() -> int | None:
    try:
        return int(LOCK.read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return None
