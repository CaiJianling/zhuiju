# -*- coding: utf-8 -*-
"""Emby STRM 采集的"访问时触发"层（不注册系统计划任务）。

和 zhuiju/autoupdate.py 是同一套路数，理由也一样：
  - 科室这边不能依赖计划任务，也不能要求管理员权限；
  - 请求线程绝不等待采集：需要跑就丢一个脱离控制台的子进程，本次访问照常返回旧数据；
  - 用锁文件 + 里面记的子进程 PID 判活，避免反复刷新页面把同一轮采集排队跑好几遍；
  - 一轮跑完之前不重复起：采集一轮本来就可能几十分钟（预算用满即停，跨天续采）。

和 autoupdate 不一样的地方只有一处判据：
  每日更新"当天成功一次就够了"，而采集近一年的量一轮跑不完，
  所以这里看的是**离上次结束有没有满 min_interval_minutes**（默认 30 分钟）：
  没采完就接着采，采完了就当天再来一轮增量的。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import autoupdate
from . import strm

BASE = strm.BASE
LOCK = BASE / "logs" / "strm.lock"
LOG = BASE / "logs" / "strm.log"
STATE = strm.DATA / "strm_state.json"
PROGRESS = strm.DATA / "strm_progress.json"
SCRIPT = BASE / "tools" / "collect_strm.py"
CHECK_TTL = 30          # 同一进程内多久重新看一次状态文件，别每个请求都读盘

_last = [0.0, ""]       # (时间戳, 最近一次 maybe_trigger 的结论)


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def running() -> bool:
    """采集子进程还在不在。判据和 autoupdate.running() 一样：锁里的 PID 优先于 TTL。"""
    if not LOCK.exists():
        return False
    pid = autoupdate._lock_pid(LOCK)
    if pid is not None:
        if autoupdate.pid_alive(pid):
            return True
        _clear()
        return False
    # 锁里读不出 PID（写坏过、权限问题）才退回按时间猜：一轮预算最长 2 小时
    cfg = strm.settings()
    if time.time() - LOCK.stat().st_mtime < max(1800, cfg["budget_seconds"] * 3):
        return True
    _clear()
    return False


def _clear() -> None:
    try:
        LOCK.unlink()
    except OSError:
        pass


def next_in(cfg: dict | None = None) -> int:
    """离下一次允许自动触发还剩多少秒；0 = 现在访问就该跑。"""
    cfg = cfg or strm.settings()
    s = _read(STATE)
    if not s:
        return 0
    try:
        done = time.mktime(time.strptime(str(s.get("at", "")), "%Y-%m-%d %H:%M:%S"))
    except (ValueError, TypeError, OSError):
        return 0
    return max(0, int(cfg["min_interval_minutes"] * 60 - (time.time() - done)))


def needs_trigger(cfg: dict | None = None) -> bool:
    """这一次访问该不该拉起采集。单独拆出来是因为后台页也要显示这个结论，
    而 maybe_trigger() 有 30 秒缓存、还会真的起进程。"""
    cfg = cfg or strm.settings()
    if not cfg["enabled"]:
        return False
    if running():
        return False
    return next_in(cfg) <= 0


def start_now(cfg: dict | None = None) -> dict:
    """拉起一轮采集（脱离控制台）。返回 {ok, pid | error}。"""
    cfg = cfg or strm.settings()
    if running():
        return {"ok": False, "error": "已经有一轮在跑了", "running": True}
    try:
        pid = autoupdate.spawn(SCRIPT, LOG, LOCK,
                               args=["--budget", str(int(cfg["budget_seconds"]))])
        return {"ok": True, "pid": pid}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:160]}


def maybe_trigger() -> str:
    """给请求线程调用：只做文件判断和（必要时）起进程，绝不阻塞响应。"""
    now = time.time()
    if _last[0] and now - _last[0] < CHECK_TTL:
        return _last[1]
    cfg = strm.settings()
    if not cfg["enabled"]:
        r = "disabled"
    elif running():
        r = "running"
    elif next_in(cfg) > 0:
        r = "cooldown"
    else:
        out = start_now(cfg)
        r = "started" if out.get("ok") else f"error: {out.get('error')}"
    _last[0] = now
    _last[1] = r
    return r


def status() -> dict:
    """后台页与 /api/strm/status 要的那一坨：在不在跑、跑到哪、库多大、设置是什么。"""
    cfg = strm.settings()
    s = _read(STATE)
    p = _read(PROGRESS)
    alive = running()
    counts = {}
    try:
        counts = strm.db_counts()
    except Exception:  # noqa: BLE001
        counts = {"error": "统计库读不出来"}
    # 那两句话（ID 标签 / NFO）在这里拼一次就好：模板渲染和 JS 刷新读的是同一份。
    # 写在模板里再在 JS 里拼一遍，迟早会一个说"没配 key"一个说"已配"。
    # 传状态文件里那一轮 ids 进去：开关开着却一个号都没查到是哪一种情况，
    # 只有跑过之后才知道，而这句话正是给人看"为什么没动静"的。
    try:
        lines = strm.status_lines(cfg, (s or {}).get("ids") if isinstance(s, dict) else None)
    except Exception:  # noqa: BLE001 - 说不清状态不该让整页读不出别的东西
        lines = {"ids": "ID 标签：读不出来", "nfo": "NFO：读不出来"}
    return {
        "running": bool(alive),
        "settings": cfg,
        "lines": lines,
        "next_in": 0 if alive else next_in(cfg),
        "last_trigger": _last[1],
        "state": {k: s.get(k) for k in ("at", "date", "ok", "pass", "seconds", "requests",
                                        "pages", "rows_new", "rows_changed", "sources_ok",
                                        "sources_total", "window_days", "note", "mode",
                                        # 上一轮查 ID 查到什么程度、为什么没收：页面那一行
                                        # 要说清"开关开了却一个号都没查到"是哪一种情况
                                        "ids")} if s else {},
        "progress": {k: p.get(k) for k in ("started_at", "updated_at", "requests", "pages",
                                           "rows_new", "rows_changed", "note", "per_src",
                                           "pass_id", "budget", "window_days", "since")} if p else {},
        "counts": counts,
        # 游标也带上：后台那张表在模板里是从 manifest 渲的，页面不整页重载时
        # 要靠这份数据把"每个源翻到第几页了"就地更新（口径必须和模板一致，
        # 所以这里用 cur 表，不用采集进程自己汇报的 per_src —— 那个是"刚翻的那一页"，
        # 游标是"下一次要从哪一页接"）
        "cursor": strm.cursors(),
        "has_data": bool(counts.get("files")),
        "script": str(SCRIPT),
        "python": autoupdate.python_bin(),
        "run_cmd": autoupdate.py_exe("tools/collect_strm.py"),
        "export_cmd": autoupdate.py_exe("tools/collect_strm.py", "--export-only"),
        "check_cmd": autoupdate.py_exe("tools/collect_strm.py", "--check"),
        "log": str(LOG),
    }
