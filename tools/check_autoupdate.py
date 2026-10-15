# -*- coding: utf-8 -*-
"""验收"访问时异步触发更新"：全程只用 Python，不依赖 shell 命令，也不依赖后台进程长期存活。

    python tools/check_autoupdate.py

用 Flask 的 test_client 直接走真实代码路径，并把要拉起的更新脚本换成一个可控的桩
（睡 90 秒，保证测试期间一直算"正在更新"），因此锁文件、子进程 PID、触发/跳过/重试
都能确定性验证。进程判活与终止走 WinAPI（kernel32），不解析任何命令输出。
"""
from __future__ import annotations

import ctypes
import json
import shutil
import sys
import time
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

STATE = BASE / "zhuiju" / "data" / "refresh_state.json"
LOCK = BASE / "logs" / "autoupdate.lock"
LOGF = BASE / "logs" / "autoupdate.log"
BAK = BASE / ".probe" / "state.bak.json"
STUB = BASE / ".probe" / "refresh_stub.py"
STUB_SLEEP = 90
MARK = "访问触发后台更新"

FAILS = []


def check(name, cond, got=None):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  got={got!r}"))
    if not cond:
        FAILS.append(name)


def pid_alive(pid: int) -> bool:
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)          # QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        return bool(ok) and code.value == 259        # STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def kill_pid(pid: int) -> None:
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x0001, False, pid)          # PROCESS_TERMINATE
    if h:
        k32.TerminateProcess(h, 1)
        k32.CloseHandle(h)


def write_state(**over):
    s = {}
    if STATE.exists():
        try:
            s = json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            s = {}
    s.update(over)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")


def spawn_count() -> int:
    """更新被真正启动了几次：数日志里的触发标记。"""
    if not LOGF.exists():
        return 0
    return LOGF.read_text(encoding="utf-8", errors="replace").count(MARK)


def main() -> int:
    from zhuiju import autoupdate
    from zhuiju.app import create_app, refresh_info

    STUB.parent.mkdir(exist_ok=True)
    STUB.write_text(
        f"import time\nprint('stub start', flush=True)\ntime.sleep({STUB_SLEEP})\n"
        "print('stub done', flush=True)\n", encoding="utf-8")

    autoupdate.REFRESH = STUB
    autoupdate.CHECK_TTL = 0          # 关掉节流：每次访问都重新判断，更能证明守卫有效
    autoupdate.LOCK_TTL = STUB_SLEEP * 4
    # 关键：把状态/进度/锁全指向临时文件。之前直接写真实 refresh_state.json，
    # 站点进程同时在读，用户界面上就出现了"上次 10-15 / 6 步全失败"这种测试造的假状态
    tmp = BASE / ".probe" / "autoupdate_test"
    tmp.mkdir(parents=True, exist_ok=True)
    autoupdate.STATE = tmp / "state.json"
    autoupdate.PROGRESS = tmp / "progress.json"
    autoupdate.LOCK = tmp / "autoupdate.lock"
    autoupdate.LOG = tmp / "autoupdate.log"
    global STATE, LOCK, LOGF, BAK
    STATE, LOCK, LOGF = autoupdate.STATE, autoupdate.LOCK, autoupdate.LOG
    BAK = tmp / "state.bak.json"


    client = create_app().test_client()

    def page():
        r = client.get("/")
        return r.status_code, r.get_data(as_text=True)

    def api(path):
        return json.loads(client.get(path).get_data())

    def reset():
        LOCK.unlink(missing_ok=True)
        autoupdate._last_check[:] = [0.0, False]

    if STATE.exists():
        BAK.parent.mkdir(exist_ok=True)
        shutil.copy2(STATE, BAK)
    LOGF.unlink(missing_ok=True)

    print("A) 今天已成功更新 -> 访问不应触发")
    reset()
    write_state(date=autoupdate.logical_day().isoformat(), ok=True,
                finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                sources_enabled=10, sources_total=10)
    code, _ = page()
    time.sleep(1)
    check("首页 200", code == 200, code)
    check("未产生锁（没触发）", not LOCK.exists(), LOCK.exists())
    check("启动次数为 0", spawn_count() == 0, spawn_count())
    s = api("/api/refresh")
    check("need_update=False", s["need_update"] is False, s["need_update"])
    check("running=False", s["running"] is False, s["running"])

    print("\nB) 状态陈旧 -> 访问触发后台更新")
    reset()
    write_state(date="2020-01-01", ok=True)
    page()
    time.sleep(1.5)
    s = api("/api/refresh")
    check("锁已产生", LOCK.exists())
    check("running=True", s["running"] is True, s["running"])
    child, server = s.get("lock_pid"), s.get("server_pid")
    check("锁里记录了子进程 PID", bool(child), child)
    check("子进程 PID 不等于本进程 PID", child != server, {"child": child, "server": server})
    check("该子进程确实存活", child is not None and pid_alive(child), child)
    check("只启动了 1 次", spawn_count() == 1, spawn_count())

    _, html = page()
    check("页头标明正在后台更新", "正在后台更新" in html)
    r = api("/api/search?kw=" + urllib.parse.quote("庆余年"))
    check("更新期间仍能搜索（返回旧数据）",
          len(r["results"]) > 0 and r["sources_ok"] > 0,
          {"titles": len(r["results"]), "sources_ok": r["sources_ok"]})

    print("\nC) 更新进行中反复访问，不应再启动第二个")
    for _ in range(5):
        page()
        time.sleep(0.3)
    s2 = api("/api/refresh")
    check("锁内 PID 未变化", s2.get("lock_pid") == child,
          {"before": child, "after": s2.get("lock_pid")})
    check("启动次数仍为 1", spawn_count() == 1, spawn_count())

    print("\nD) 更新进程结束后必须识破，不能一直谎报进行中")
    kill_pid(child)
    for _ in range(20):
        if not pid_alive(child):
            break
        time.sleep(0.5)
    check("桩进程已结束", not pid_alive(child), child)
    check("running() 变回 False", autoupdate.running() is False)
    check("死 PID 的锁被自动清掉", not LOCK.exists(), LOCK.exists())

    print("\nE) 今天更新失败 -> 再次访问要重试（不能只挂着旧的“正在更新”）")
    reset()
    write_state(date=autoupdate.logical_day().isoformat(), ok=False, failed_steps=["health"],
                sources_enabled=8, sources_total=10)
    before = spawn_count()
    page()
    time.sleep(1.5)
    check("失败后重新触发（锁再次出现）", LOCK.exists(), LOCK.exists())
    check("启动次数 +1", spawn_count() == before + 1, {"before": before, "now": spawn_count()})
    pid2 = api("/api/refresh").get("lock_pid")
    if pid2:
        kill_pid(pid2)
        time.sleep(0.5)

    print("\nF) 空闲且不是本周期更新时，横幅要讲清楚")
    LOCK.unlink(missing_ok=True)
    write_state(date=(date.today() - timedelta(days=3)).isoformat(),
                ok=True, failed_steps=[], sources_enabled=9, sources_total=10)
    info = refresh_info()
    check("横幅说明已过当天周期", "已过当天周期" in info["text"], info)
    check("带上上次日期", (date.today() - timedelta(days=3)).isoformat() in info["text"], info)
    check("不再把陈旧说成失败", info["state"] == "stale", info["state"])

    print("\nG) 进度以锁里的子进程为准，不能只信进度文件")
    stale_prog = tmp / "progress.json"
    stale_prog.write_text(json.dumps({"running": True, "done": 2, "total": 6,
                                      "step_label": "假装有进度", "steps": []}),
                          encoding="utf-8")
    LOCK.unlink(missing_ok=True)
    check("没有活着的子进程时 running=False", autoupdate.progress()["running"] is False)
    autoupdate.REFRESH = STUB
    autoupdate.maybe_trigger()
    time.sleep(1.0)
    check("子进程刚起来、还没写进度文件也能显示正在更新",
          autoupdate.progress()["running"] is True, autoupdate._lock_pid())
    pid3 = autoupdate._lock_pid()
    if pid3:
        kill_pid(pid3)
        time.sleep(0.5)
    check("进程消失后进度状态跟着变 False", autoupdate.progress()["running"] is False)

    print()
    if BAK.exists():
        shutil.copy2(BAK, STATE)
        print("已恢复原状态文件")
    else:
        STATE.unlink(missing_ok=True)
    STUB.unlink(missing_ok=True)
    LOCK.unlink(missing_ok=True)

    print("结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
