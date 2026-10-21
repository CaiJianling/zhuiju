# -*- coding: utf-8 -*-
"""每日自动更新：刷新资源站目录、体检检索源、必要时补抽新接口。

设计要点
  - 每天最多真正执行一次：成功执行后写 data/refresh_state.json；定时任务在 06:00-14:00
    每 30 分钟触发一次，开机晚了的会在下一次触发时补上，已经更新过的直接跳过。
  - 所有步骤都在本机跑，失败只记录原因不中断其它步骤，日志留在 logs/。
  - 只读第三方公开接口，不下载任何影视内容。

用法：
    python tools/refresh.py                # 正常执行（当天已更新则跳过）
    python tools/refresh.py --force        # 忽略当天标记，强制重跑
    python tools/refresh.py --skip-deep    # 跳过较慢的"补抽新接口"步骤
    python tools/refresh.py --check-env    # 只报告会用哪个解释器、依赖齐不齐（部署排查）

Linux 上别直接敲 python3：用站点根目录的 refresh.sh，它会按 zhuiju.env / ZHUIJU_PYTHON
找到宝塔那个建在站点外面的 venv。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from zhuiju.autoupdate import (LOCK, PROGRESS, STEPS, has_deps, logical_day,  # noqa: E402
                               python_bin, python_info)
# 步骤清单与"当天"口径都取自站点同一处，避免两边各写一份对不上

# 解释器现找：venv 在站点里面（.venv/venv，Windows 是 Scripts、Linux 是 bin）还是在
# 站点外面（宝塔的 /www/server/python_project/virtualenv_env/xxx），都由 autoupdate 那套
# 候选顺序判定；这里再写死 .venv/Scripts/python.exe 就是这次 Linux 上六步全挂的原因。
PY = python_bin()
STATE = BASE / "zhuiju" / "data" / "refresh_state.json"
LOG_DIR = BASE / "logs"
KEEP_LOGS = 14


def preflight() -> str:
    """跑之前先确认解释器能用：早失败、说人话，比六步各报一遍同一句强。"""
    exe, why = python_info()
    if not Path(exe).is_file():
        return f"找不到解释器 {exe}（{why}）"
    if not has_deps(exe):
        return (f"{exe} 里没装 flask/requests（{why}）：\n"
                f"  {exe} -m pip install -r requirements.txt "
                f"-i https://pypi.tuna.tsinghua.edu.cn/simple")
    return ""

def run(script: str, args: list[str] = (), timeout: int = 600) -> tuple[bool, str]:
    cmd = [str(PY), script, *args]
    try:
        p = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"超过 {timeout}s 未完成，已终止"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    out = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
    tail = "\n".join(out.splitlines()[-8:])
    return p.returncode == 0, (f"exit={p.returncode}\n{tail}" if p.returncode else tail)


def write_progress(**over) -> dict:
    """把进度写出去，页面横幅据此显示"第几步 / 共几步 / 当前在做什么"。"""
    p = {}
    try:
        p = json.loads(PROGRESS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        p = {}
    p.update(over)
    p["updated_epoch"] = time.time()
    p["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        PROGRESS.parent.mkdir(parents=True, exist_ok=True)
        tmp = PROGRESS.with_suffix(".tmp")
        tmp.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
        tmp.replace(PROGRESS)
    except OSError:
        pass
    return p


def mirror_note() -> str:
    """显示上游 GitHub 数据这次实际走了哪个加速源（国内直连常不通）。"""
    try:
        m = json.loads((BASE / "data" / "cache" / "mirror_used.json")
                       .read_text(encoding="utf-8"))
        return f"上游数据源：{m.get('mirror') or '直连 GitHub'}（{m.get('bytes', 0)} 字节）"
    except Exception:  # noqa: BLE001
        return ""


def read_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def sources_summary() -> dict:
    try:
        data = json.loads((BASE / "zhuiju" / "data" / "sources.json").read_text(encoding="utf-8"))
        srcs = data.get("sources", [])
        return {"sources_total": len(srcs),
                "sources_enabled": sum(1 for s in srcs if s.get("enabled", True)),
                # enabled 里有两类：能按关键词搜的，和站点把搜索关了、只喂猜你想搜的
                # （searchable=False）。日志只报 enabled 就把"并发检索到底打几个源"糊掉了
                "sources_searchable": sum(1 for s in srcs
                                          if s.get("enabled", True) and s.get("searchable", True))}
    except Exception:  # noqa: BLE001
        return {}


def catalog_updated() -> str:
    try:
        return json.loads((BASE / "zhuiju" / "data" / "catalog.json")
                          .read_text(encoding="utf-8")).get("updated_at", "")
    except Exception:  # noqa: BLE001
        return ""


def prune_logs() -> None:
    logs = sorted(LOG_DIR.glob("refresh-*.log"))
    for old in logs[:-KEEP_LOGS]:
        try:
            old.unlink()
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略当天已更新的标记")
    ap.add_argument("--skip-deep", action="store_true", help="跳过补抽新接口与模板验证")
    ap.add_argument("--check-env", action="store_true",
                    help="只报告会用哪个解释器、依赖齐不齐，然后退出（部署排查用）")
    args = ap.parse_args()

    exe, why = python_info()
    if args.check_env:
        bad = preflight()
        print(f"外层解释器    {sys.executable}")
        print(f"跑步骤的解释器 {exe}（{why}）")
        print(f"站点目录      {BASE}")
        print(f"venv 指定     ZHUIJU_PYTHON={os.environ.get('ZHUIJU_PYTHON', '(未设)')} "
              f"ZHUIJU_VENV={os.environ.get('ZHUIJU_VENV', '(未设)')} "
              f"配置文件={Path(__file__).resolve().parent.parent / 'zhuiju.env'}")
        print("环境检查      " + ("通过" if not bad else "不通过：\n" + bad))
        return 0 if not bad else 1

    LOG_DIR.mkdir(exist_ok=True)
    now = datetime.now()
    today = logical_day(now).isoformat()      # 以凌晨 2 点为界的逻辑日期
    prev = read_state()

    bad = preflight()
    if bad:
        # 解释器不对/依赖没装：直接把话说清楚写进状态和日志，页面横幅就能显示出来，
        # 而不是六个步骤各抛一遍 Exec format error
        print(f"[FAIL] 环境不对，没开始跑：\n{bad}", flush=True)
        note = bad.splitlines()[0]
        try:
            # 目录没权限时（服务器上 www 写不了 logs）别把唯一一句人话也弄丢了
            LOG_DIR.mkdir(exist_ok=True)
            (LOG_DIR / f"refresh-{now.strftime('%Y%m%d-%H%M%S')}.log").write_text(
                f"追剧资源搜索 每日更新  {now:%Y-%m-%d %H:%M:%S}\n"
                f"解释器： {PY}（{python_info()[1]}）\n\n{bad}\n", encoding="utf-8")
        except OSError as exc:
            print(f"日志写不出去：{type(exc).__name__}: {exc}", flush=True)
        write_progress(running=False, result="env", note=note,
                       done=0, total=len(STEPS),
                       steps=[{"key": s["key"], "label": s["label"], "state": "fail",
                               "error": note[:90]} for s in STEPS])
        try:
            STATE.write_text(json.dumps({**prev, "date": today, "ok": False,
                                         "failed_steps": ["env"], "partial": False,
                                         "finished_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                                         "python": PY}, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        except OSError as exc:
            print(f"状态文件写不出去：{type(exc).__name__}: {exc}", flush=True)
        try:
            LOCK.unlink()
        except OSError:
            pass
        return 1

    # 只有"完整跑完的一轮"才算这个周期已经更新过（判据与站点自动触发共用 _cycle_done）。
    # 之前 --skip-deep 也写 ok=true，结果手动跑个快版就把当天真正的全量更新挡掉了。
    from zhuiju.autoupdate import _cycle_done
    if prev.get("date") == today and _cycle_done(prev) and not args.force:
        print(f"本更新周期（{today}）已跑过，跳过。上次 {prev.get('finished_at')}")
        return 0

    started = time.time()
    log_path = LOG_DIR / f"refresh-{now.strftime('%Y%m%d-%H%M%S')}.log"
    lines = [f"追剧资源搜索 每日更新  {now:%Y-%m-%d %H:%M:%S}",
             f"force={args.force} skip_deep={args.skip_deep}",
             f"解释器： {PY}（{python_info()[1]}）· 站点进程 {sys.executable}", ""]

    def save_log(extra: str = "") -> None:
        """逐步落盘：更新要跑几分钟，中途看日志才能知道卡在哪一步。"""
        body = "\n".join(lines)
        if extra:
            body += "\n" + extra
        log_path.write_text(body, encoding="utf-8")

    save_log("(进行中)")

    results, failed, skipped = {}, [], []
    steps_state = [{"key": s["key"], "label": s["label"], "state": "pending"} for s in STEPS]
    write_progress(running=True, started_at=now.strftime("%Y-%m-%d %H:%M:%S"),
                   finished_at="", done=0, total=len(STEPS), step_key="", step_label="",
                   steps=steps_state, result="", note="", seconds=0)

    for idx, spec in enumerate(STEPS):
        name, script, timeout, desc = spec["key"], spec["script"], spec["timeout"], spec["label"]
        if args.skip_deep and name in ("deep", "merge", "verify", "templates"):
            results[name] = {"skipped": True}
            skipped.append(name)
            steps_state[idx]["state"] = "skipped"
            lines.append(f"--- [{name}] 跳过 ---")
            write_progress(done=idx + 1, steps=steps_state, step_key="", step_label="")
            continue
        script_args = list(spec.get("args") or [])
        if name == "health" and len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
            script_args = [sys.argv[1]]       # 允许命令行换关键词
        lines.append(f"--- [{name}] {desc} :: {script} {' '.join(script_args)} ---")
        save_log()
        write_progress(done=idx, steps=steps_state, step_key=name, step_label=desc,
                       seconds=round(time.time() - started))
        ok, out = run(script, script_args, timeout)
        steps_state[idx]["state"] = "ok" if ok else "fail"
        if not ok:
            steps_state[idx]["error"] = (out.splitlines() or [""])[0][:90]
        lines.append(out or "(无输出)")
        lines.append("")
        results[name] = {"ok": ok, "output": out[-800:]}
        if not ok:
            failed.append(name)
        write_progress(done=idx + 1, steps=steps_state, note=mirror_note(),
                       seconds=round(time.time() - started))
        print(f"[{'OK ' if ok else 'FAIL'}] {name}  {desc}", flush=True)

    # 注意：上游 resources.json 里的 updated_at 是"数据版本号"，可能落后于今天
    # （上游仓库自己每天不一定改这个字段），所以"是否当天更新过"以本机运行日期为准。
    upd = catalog_updated()
    fetched_today = today
    ok = not failed
    state = {
        "date": today,
        "ok": ok,
        "failed_steps": failed,
        # 跳步的快版不算"这个周期跑完了"：否则 --skip-deep 会把当天的全量更新挡掉，
        # 需要更新时得把 full 也一起判掉
        "partial": bool(skipped),
        "skipped_steps": skipped,
        "started_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "seconds": round(time.time() - started, 1),
        "upstream_updated_at": upd,
        "fetched_at": now.strftime("%Y-%m-%d"),
        "fetched_today": True,
        "log": log_path.name,
        "python": PY,
        "steps": {k: v for k, v in results.items()},
        **sources_summary(),
    }
    lines.append("=== 汇总 ===")
    lines.append(json.dumps({k: state[k] for k in
                             ("date", "ok", "failed_steps", "seconds",
                              "upstream_updated_at", "fetched_at",
                              "sources_enabled", "sources_searchable", "sources_total")
                             if k in state}, ensure_ascii=False, indent=2))
    save_log()
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    write_progress(running=False, finished_at=state["finished_at"],
                   done=len(STEPS), step_key="", step_label="", result=state["finished_at"] and (
                       "ok" if ok else "failed:" + ",".join(failed)),
                   seconds=state["seconds"], note=mirror_note())
    prune_logs()
    # 主动释放访问触发的锁，让页面立刻从"正在更新"变成真实状态
    try:
        LOCK.unlink()
    except OSError:
        pass

    print(f"\n{'完成' if ok else '部分步骤失败: ' + ','.join(failed)}"
          f"  用时 {state['seconds']}s  检索源 {state.get('sources_searchable')}/{state.get('sources_total')}"
          f"（可搜 {state.get('sources_searchable')}、启用 {state.get('sources_enabled')}）"
          f"  目录日期 {upd or '未知'}")
    print(f"日志： {log_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
