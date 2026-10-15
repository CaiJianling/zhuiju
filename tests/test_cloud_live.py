# -*- coding: utf-8 -*-
"""网盘查询的活体集成测试：自己起服务、跑断言、再关掉，不依赖外部进程存活。

    python tests/test_cloud_live.py

用单独端口，避免和开发用的 5000 抢；测试进程退出时服务一定被关闭。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
PORT = os.environ.get("ZJ_TEST_PORT", "5055")
ROOT = f"http://127.0.0.1:{PORT}"
FAILS = []


def check(name, cond, got=None):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  got={got!r}"))
    if not cond:
        FAILS.append(name)


def free_port() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return str(s.getsockname()[1])


def get(path, timeout=60):
    try:
        with urllib.request.urlopen(ROOT + path, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}"


def main() -> int:
    global PORT, ROOT
    PORT = free_port()
    ROOT = f"http://127.0.0.1:{PORT}"

    env = {**os.environ, "ZHUIJU_PORT": PORT, "PYTHONUTF8": "1",
           "ZHUIJU_NO_BROWSER": "1"}
    proc = subprocess.Popen([sys.executable, "-u", str(BASE / "run.py")], cwd=str(BASE),
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(45):
            time.sleep(1)
            if get("/api/cloud?kw=x", timeout=3)[0] in (200, 400):
                break
        else:
            print("服务没能在 45 秒内起来")
            return 1

        print("1) 路由与页面")
        st, body = get("/api/cloud?kw=x")
        check("新路由 /api/cloud 已注册（不是 404）", st != 404, st)
        check("过短关键词返回 400", st == 400, st)
        st, html = get("/")
        check("首页 200", st == 200, st)
        check("标签页里有『网盘查询』", 'data-tab="cloud"' in html)
        check("面板容器 cloudlist 存在", 'id="cloudlist"' in html)
        check("页头有数据新鲜度提示", 'class="fresh' in html)

        print("\n2) 网盘 / 磁力查询")
        kw = "庆余年"
        st, body = get("/api/cloud?kw=" + urllib.parse.quote(kw))
        check("查询返回 200", st == 200, st)
        d = json.loads(body)
        check("覆盖网盘与磁力两类站点", d["total_sites"] >= 15, d["total_sites"])
        check("确有站点解析出结果", d["with_results"] >= 1,
              {"with_results": d["with_results"], "entries": d["entries"]})
        ok_sites = [s for s in d["sites"] if s["ok"]]
        bad_sites = [s for s in d["sites"] if not s["ok"]]
        for s in ok_sites:
            check(f"{s['name']} 的结果同域",
                  all(s["search_url"].split("/")[2].replace("www.", "") in
                      it["link"] or it["host"] in s["search_url"] for it in s["items"]),
                  [it["host"] for it in s["items"]][:3])
        check("解析出的条目都带链接与标题",
              all(it["link"].startswith("http") and it["title"] for s in ok_sites
                  for it in s["items"]))
        check("标题是单行（无换行残留）",
              all("\n" not in it["title"] for s in ok_sites for it in s["items"]))
        check("拿不到结果的站都给了原因",
              all(s["error"] for s in bad_sites),
              [s["name"] for s in bad_sites if not s["error"]])
        print(f"     {d['with_results']}/{d['total_sites']} 站解析出结果，共 {d['entries']} 条；"
              f"{len(bad_sites)} 站标注了原因")

        print("\n3) 影视聚合与目录未受影响")
        d2 = json.loads(get("/api/search?kw=" + urllib.parse.quote(kw))[1])
        check("影视聚合仍正常", len(d2["results"]) > 0 and d2["sources_ok"] > 0,
              {"titles": len(d2["results"]), "ok": d2["sources_ok"]})
        d3 = json.loads(get("/api/catalog?kw=" + urllib.parse.quote("网盘"))[1])
        check("目录检索仍正常", d3["total"] > 0, d3["total"])
        check("接口在更新触发状态下可用", get("/api/refresh")[0] == 200)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("\n测试服务已关闭")

    print("结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
