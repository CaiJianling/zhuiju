# -*- coding: utf-8 -*-
"""验收"访问时异步触发更新"：全程只用 Python，不依赖 shell 命令，也不依赖后台进程长期存活。

    python tools/check_autoupdate.py

用 Flask 的 test_client 直接走真实代码路径，并把要拉起的更新脚本换成一个可控的桩
（睡 90 秒，保证测试期间一直算"正在更新"），因此锁文件、子进程 PID、触发/跳过/重试
都能确定性验证。进程判活与终止按平台分叉：Windows 用 kernel32，Linux 用 os.kill + SIGKILL，
两边都不解析命令输出。
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import signal
import sys
import tempfile
import time
import urllib.parse
from datetime import date, datetime, timedelta
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
WIN = os.name == "nt"

FAILS = []


def check(name, cond, got=None):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  got={got!r}"))
    if not cond:
        FAILS.append(name)


def pid_alive(pid: int) -> bool:
    if not WIN:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True
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
    if not WIN:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            return
        return
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

    print("\nE) 今天更新失败且冷却期已过 -> 再次访问要重试（不能只挂着旧的“正在更新”）")
    reset()
    # finished_at 必须显式写：write_state 是合并写的，留着 A 段那个"刚刚"的时间，
    # 这里会被 H 段的失败冷却挡掉，看起来像守卫失效
    wrote = (datetime.now() - timedelta(minutes=autoupdate.RETRY_MINUTES + 5))
    write_state(date=autoupdate.logical_day().isoformat(), ok=False, failed_steps=["health"],
                finished_at=wrote.strftime("%Y-%m-%d %H:%M:%S"),
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

    print("\nH) 刚失败过一轮 -> 冷却期内访问不该再重跑（服务器上门坏了别每分钟敲一次）")
    reset()
    write_state(date=autoupdate.logical_day().isoformat(), ok=False, failed_steps=["health"],
                finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    before = spawn_count()
    page()
    time.sleep(1.0)
    check("冷却中不启动", not LOCK.exists(), LOCK.exists())
    check("冷却中启动次数没变", spawn_count() == before, {"before": before, "now": spawn_count()})
    check("need_update=False（因为在冷却）", api("/api/refresh")["need_update"] is False)
    check("状态里给出还剩多少秒", api("/api/refresh")["retry_in"] > 0,
          api("/api/refresh")["retry_in"])
    info = refresh_info()
    check("失败横幅仍然标着失败", info["state"] == "failed", info)
    check("失败横幅把解释器也带上（Linux 上一眼能看出是不是 python 选错了）",
          "解释器" in info["hint"] and "refresh-*.log" in info["hint"], info["hint"])
    check("冷却没过时横幅讲清还要等多久", "分钟内不再自动重试" in info["hint"], info["hint"])
    autoupdate.RETRY_MINUTES = 0          # 设 0 就是"每次访问都可以重试"，用来验证开关有效
    check("ZHUIJU_RETRY_MINUTES=0 时不冷却", autoupdate.needs_update() is True,
          autoupdate.next_retry_in(autoupdate._read_state()))
    autoupdate.RETRY_MINUTES = 15
    old = (datetime.now() - timedelta(minutes=autoupdate.RETRY_MINUTES + 5))
    write_state(finished_at=old.strftime("%Y-%m-%d %H:%M:%S"))
    check("冷却期过了就重新允许更新",
          autoupdate.needs_update() is True, autoupdate.next_retry_in(autoupdate._read_state()))
    reset()

    print("\nI) 解释器是现找的，不是写死的 .venv/Scripts/python.exe")
    exe, why = autoupdate.python_info()
    check("选出来的解释器文件存在", Path(exe).is_file(), exe)
    check("选出来的解释器能 import flask/requests", autoupdate.has_deps(exe), {"exe": exe, "why": why})
    check("理由里说清了为什么是它", bool(why) and "·" in why, why)
    rp = (BASE / "tools" / "refresh.py").read_text(encoding="utf-8")
    check("refresh.py 的解释器来自现找，不是写死的 .venv 路径",
          bool(re.search(r"^PY = python_bin\(\)", rp, re.M))
          and 'BASE / ".venv"' not in rp and '".venv"' not in rp,
          re.findall(r"^PY = .*", rp, re.M))
    fake = str(Path(exe))
    autoupdate._py_cache.clear()
    os.environ["ZHUIJU_PYTHON"] = fake
    check("ZHUIJU_PYTHON 指哪儿用哪儿（原样保留，不解析软链接）",
          autoupdate.python_bin() == fake,
          {"got": autoupdate.python_bin(), "want": fake})
    autoupdate._py_cache.clear()
    os.environ.pop("ZHUIJU_PYTHON")
    outside = Path(tempfile.mkdtemp(prefix="zhuiju_bt_env_"))      # 宝塔：venv 在站点外面
    os.environ["ZHUIJU_VENV"] = str(outside)
    cands = [p for p, _ in autoupdate._candidates()]
    own = [p for p in cands if p.startswith(str(outside))]
    proj = [p for p in cands if p.startswith(str(BASE / ".venv")) and p != sys.executable]
    check("ZHUIJU_VENV 指的目录进了候选，且排在项目内 .venv 之前",
          bool(own) and (not proj or cands.index(own[0]) < cands.index(proj[0])), cands[:6])
    check("外面那个 venv 没有可用解释器时不会选它，而是退回跑站点的那个",
          autoupdate.python_bin() == sys.executable, autoupdate.python_bin())
    shutil.rmtree(outside, ignore_errors=True)
    autoupdate._py_cache.clear()
    os.environ.pop("ZHUIJU_VENV")
    real_win = autoupdate.is_windows
    try:
        autoupdate.is_windows = lambda: False          # 在 Windows 上模拟 Linux 的目录布局
        venv_c = [p for p, why in autoupdate._candidates() if "虚拟环境" in why]
        check("当成 Linux 时 venv 候选换成 bin/python、bin/python3（不再是 Scripts/python.exe）",
              venv_c and all(Path(x).parent.name == "bin" for x in venv_c), venv_c[:6])
        check("Linux 下手动催更给的是命令而不是 refresh.bat",
              "refresh.bat" not in autoupdate.retry_hint(), autoupdate.retry_hint())
    finally:
        autoupdate.is_windows = real_win
        autoupdate._py_cache.clear()
    check("Windows 下仍然提示 refresh.bat",
          autoupdate.retry_hint().count("refresh.bat") == 1 if real_win() else True)
    st = api("/api/refresh")
    check("状态里带了解释器与最近触发结论，页面能直接看出问题",
          {"python", "python_why", "retry_cmd", "last_trigger"} <= set(st), sorted(st))

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
