# -*- coding: utf-8 -*-
"""慢速采集近一年的电影/电视剧：先更新数据库，再合并导出 strm 目录树和分卷 zip。

为什么是"翻更新流"而不是"按分类翻"（实测出来的）
  苹果CMS 的 `ac=list&t=分类ID` 这条路在各站都不成样子：火狐 t=2 只给 1 条、
  t=1 直接 0 条，另几个站要么空要么和总列表一样。而全局更新流 `ac=videolist&pg=N`
  严格按 `vod_time` 倒序、能稳定深翻（实测翻到 4800 页仍有数据），
  并且**一次请求就把元数据和全部播放线路一起带回**（vod_play_url 在 videolist 里有，
  ac=list 里没有）—— 采一遍只要 N 次请求，不用先取 ID 再逐条 ac=detail。

  顺带一件事：索尼、闪电那两个源"关键词搜索被站点关了"（见 zhuiju/sources.py 的
  searchable），但它们的不流是好的 —— 本脚本只翻更新流，所以这两个源照样收得到。

慢速与断点
  窗口一年时，17 个源加起来要翻两三万页。一轮跑不完是设计内的：每个源的页码游标
  写在 strm.db 的 cur 表里，预算用完就停，下次访问触发时接着这一页翻。
  每次请求之间 sleep（默认 400ms）再并发 3 个源，既不给第三方站压力，
  也让这边随时能停。

增量
  某个源只要完整翻出过一次窗口（cur.backfill=1），之后的轮次就从第 1 页往下翻，
  连续几页"全是老片且一条地址都没变"就提前收 —— 上游每天新增的量很小，
  天天把一整年重翻一遍纯属白费。提前收**不做清库**：只有真翻到窗口外才敢删
  "这一轮没再见到的条目"，否则会把几天前采的正常数据当成下架清空。

用法
    python tools/collect_strm.py                  跑一轮（预算取后台设置）
    python tools/collect_strm.py --budget 120     只跑 2 分钟（排查用）
    python tools/collect_strm.py --sources huya   只采指定几个源
    python tools/collect_strm.py --export-only    不采集，只把库里的东西导出+打包
    python tools/collect_strm.py --full           连着 --export-only 用，全量重建
    python tools/collect_strm.py --check          只看库和游标现在什么样

Linux/宝塔上用站点自己的解释器跑（判据见 zhuiju/autoupdate.py），别直接敲 python3。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
# 控制台是 GBK 的 Windows 上，不打这行下面那些中文 print 会当场编码报错
os.environ.setdefault("PYTHONUTF8", "1")

import requests  # noqa: E402

from zhuiju import strm  # noqa: E402
from zhuiju.autoupdate import logical_day  # noqa: E402
from zhuiju.search import _session as source_session  # noqa: E402
from zhuiju.sources import load_sources  # noqa: E402

requests.packages.urllib3.disable_warnings()

STATE = strm.DATA / "strm_state.json"
PROGRESS = strm.DATA / "strm_progress.json"
PAGE_LIMIT = 20        # 上游硬限：实测 limit=50 被裁回 20、limit=100 直接超时
KNOWN_STOP = 3         # 增量轮里连续几页"全认识"就收
BATCH_PAGES = 8        # 每批每个源翻几页就换手（轮转调度的粒度，见 crawl_src 的说明）
WAVE_SECONDS = 90      # 一批最多待多久：某个源卡住也不能把整批拖死，到点就换手
FLUSH_REQUESTS = 150   # 每发这么多请求就合并导出一次（"到一定时间合并 strm"）
FLUSH_SECONDS = 240    # 或者每过这么多秒一次
TIMEOUT = 12
MAX_FAILS = 3          # 同一个源连续失败几次就这一轮先放弃它
BACKFILL_CHUNK = 20    # 回填元数据时一次问多少个 ID（实测上游接受批量 ids）
BACKFILL_SHARE = 0.35  # 回填最多占一轮预算的三成五：补老数据不该把"采新片"挤掉

# 各线程共用的计数器。导出要写几千个文件，所以用非阻塞锁：谁有空谁做，别人不等。
_shared = {"requests": 0, "pages": 0, "new": 0, "changed": 0,
           "since_flush": 0, "last_flush": 0.0,
           "flushing": threading.Lock(), "lock": threading.Lock()}


def bump(**kw) -> None:
    with _shared["lock"]:
        for k, v in kw.items():
            _shared[k] = _shared.get(k, 0) + v


def snap() -> dict:
    with _shared["lock"]:
        return {k: v for k, v in _shared.items()
                if k in ("requests", "pages", "new", "changed")}


def write_json(path: Path, data: dict) -> None:
    """先写临时文件再换过去：站点进程随时在读这两个文件，半截 JSON 会直接抛。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def progress(**over) -> dict:
    p = {}
    try:
        p = json.loads(PROGRESS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        p = {}
    # per_src 是各线程分别汇报的，必须合并而不是整块覆盖（覆盖一次就只剩一个源了）。
    # 但一轮开始时要明确清掉上一轮的：上一轮翻到第 800 页、这一轮从第 1 页重新开始，
    # 留着旧页码会让后台那一行看起来"还在很后面"。
    reset = bool(over.pop("reset_per_src", False))
    per = {} if reset else dict(p.get("per_src") or {})
    if "per_src" in over:
        per.update(over.pop("per_src") or {})
    p.update(over)
    p["per_src"] = per
    p.update(snap())
    p["updated_at"] = strm.now()
    write_json(PROGRESS, p)
    return p


def unwrap(payload) -> dict:
    """有的站把内容套在 data 里（淘片），苹果CMS 规范本身是平铺的。"""
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload if isinstance(payload, dict) else {}


def fetch_page(src, pg: int) -> dict:
    """取一页 videolist -> {ok, items, error}。出错不抛：单个源不该把整轮带崩。"""
    params = {"ac": "videolist", "pg": pg, "limit": PAGE_LIMIT}
    params.update(src.params or {})
    try:
        r = source_session(src).get(src.api, params=params, timeout=TIMEOUT, verify=False)
        body = (r.text or "").strip()
        if r.status_code != 200:
            return {"ok": False, "items": [], "error": f"HTTP {r.status_code}"}
        if body[:1] not in "{[":
            return {"ok": False, "items": [], "error": "返回非 JSON（可能被拦截/需白名单）"}
        payload = unwrap(r.json())
        items = payload.get("list") or []
        return {"ok": True, "items": [x for x in items if isinstance(x, dict)],
                "pagecount": payload.get("pagecount"), "error": None}
    except requests.exceptions.Timeout:
        return {"ok": False, "items": [], "error": "超时"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"[:80]}
    finally:
        bump(requests=1)


def maybe_flush(label: str = "") -> None:
    """到量了就导出一次：采集几小时不出文件没意义，边采边能看到库在长。"""
    with _shared["lock"]:
        due = (_shared["since_flush"] >= FLUSH_REQUESTS
               or time.time() - _shared["last_flush"] >= FLUSH_SECONDS)
        if due:
            _shared["since_flush"] = 0
            _shared["last_flush"] = time.time()
    if not due:
        return
    if not _shared["flushing"].acquire(blocking=False):
        return
    try:
        out = run_export(f"轮内合并（{label}）")
        print(f"  · 合并导出：写 {out['written']} / 未变 {out['skipped']} / 删 {out['removed']}"
              f" · 打包 {out['zips']['made']} 卷 · {out['seconds']}s", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"  · 轮内导出失败：{type(exc).__name__}: {exc}", flush=True)
    finally:
        _shared["flushing"].release()


def fetch_ids(src, vids: list[str]) -> dict:
    """按一批 ID 取条目：`ac=videolist&ids=a,b,c` 实测一次能带回 20 条完整条目。

    比逐条 `ac=detail` 省一个数量级请求，也比"重新翻一遍整年"便宜得多 ——
    回填老数据的字段就靠它。
    """
    params = {"ac": "videolist", "ids": ",".join(str(v) for v in vids), "limit": PAGE_LIMIT}
    params.update(src.params or {})
    try:
        r = source_session(src).get(src.api, params=params, timeout=TIMEOUT, verify=False)
        body = (r.text or "").strip()
        if r.status_code != 200 or body[:1] not in "{[":
            return {"ok": False, "items": [], "error": f"HTTP {r.status_code}" if r.status_code != 200 else "非 JSON"}
        payload = unwrap(r.json())
        return {"ok": True, "items": [x for x in (payload.get("list") or [])
                                      if isinstance(x, dict)], "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}"[:60]}
    finally:
        bump(requests=1)


def backfill_meta(cfg: dict, pass_id: int, since, end_at: float, delay: float,
                  by_id: dict, limit_rows: int = 0) -> dict:
    """给库里"只存了名字和地址、没存元数据"的旧行补 NFO 要用的那几个字段。

    为什么单独要这条路：那些行是补字段之前采进来的，翻页游标早就走到它们后面去了，
    不回填的话 NFO 里就只有片名和年份 —— 而 NFO 值钱的部分恰恰是简介、演员、上映日、
    豆瓣号。按 (源, ID) 批量取一次就能补齐，不用重翻整年。

    上游已经不认的这个 ID（下架/改ID）会被判成 skip：那里给 msig 写一个 'gone' 哨兵，
    否则每次跑都把它当"还没补"重问一遍，白敲上游也永远补不上。
    """
    out = {"chunks": 0, "asked": 0, "filled": 0, "skipped": 0, "left": 0}
    con = strm.connect()
    try:
        sql = ("SELECT src, vid FROM vod WHERE (msig IS NULL OR msig='')"
               " ORDER BY src, vid" + (f" LIMIT {int(limit_rows)}" if limit_rows else ""))
        todo = [(r["src"], r["vid"]) for r in con.execute(sql)]
        out["left"] = len(todo)
        groups: dict[str, list[str]] = {}
        for s, v in todo:
            groups.setdefault(s, []).append(v)
        for sid, vids in groups.items():
            src = by_id.get(sid)
            if src is None:          # 源被停用了：这些行补不了，标哨兵别再每轮重问
                con.executemany("UPDATE vod SET msig='gone' WHERE src=? AND vid=?",
                                [(sid, v) for v in vids])
                con.commit()
                continue
            for i in range(0, len(vids), BACKFILL_CHUNK):
                if time.time() >= end_at:
                    return out
                chunk = vids[i:i + BACKFILL_CHUNK]
                out["chunks"] += 1
                out["asked"] += len(chunk)
                page = fetch_ids(src, chunk)
                if not page["ok"]:
                    break            # 这个源今天不通就算了，下一轮再补
                got = {}
                for it in page["items"]:
                    got[str(it.get("vod_id"))] = it
                for v in chunk:
                    it = got.get(v)
                    if it is None:
                        con.execute("UPDATE vod SET msig='gone' WHERE src=? AND vid=?",
                                    (sid, v))
                        out["skipped"] += 1
                        continue
                    if strm.record_vod(con, sid, src.name, it, cfg, pass_id, since) == "skip":
                        con.execute("UPDATE vod SET msig='gone' WHERE src=? AND vid=?",
                                    (sid, v))
                        out["skipped"] += 1
                    else:
                        out["filled"] += 1
                con.commit()
                progress(note=f"回填元数据：{src.name} 已补 {out['filled']} 条")
                if delay:
                    time.sleep(delay)
        return out
    finally:
        con.close()


def crawl_src(src, cfg: dict, pass_id: int, since, end_at: float, delay: float,
              max_pages: int) -> dict:
    """一个源翻一小批（最多 max_pages 页）就换手。游标每翻完一页就落库，进程被杀最多丢一页。

    为什么要限制"一次只翻几页"：把所有源一次性交给 3 个 worker 的话，
    每个 worker 抱住一个源翻到预算结束 —— 实测 17 个源跑 10 分钟只有 4 个源有数据，
    排在后面的 13 个源一整轮都没被碰到。近一年的量要跨天续采，
    公平比深度重要：先让每个源都往前挪几页，用户才谈得上"多个源都能选线路"。
    """
    res = {"src": src.id, "name": src.name, "pages": 0, "new": 0, "changed": 0,
           "same": 0, "skip": 0, "stop": "", "error": "", "last_pg": 0,
           "last_time": "", "pruned": 0}
    con = strm.connect()
    try:
        cur = con.execute("SELECT * FROM cur WHERE src=?", (src.id,)).fetchone()
        same_pass = bool(cur) and int(cur["pass"] or 0) == pass_id
        if same_pass and int(cur["done"] or 0):
            # 这一轮这个源已经翻到头了（上一轮预算里做完了）：别再翻第二遍
            res["stop"] = str(cur["stop"] or "done")
            res.update(last_pg=int(cur["pg"]), last_time=cur["last_time"] or "")
            return res
        pg = int(cur["pg"]) if same_pass and cur["pg"] else 1
        known = int(cur["known"]) if same_pass else 0
        backfill = int(cur["backfill"]) if cur else 0
        # 本轮累计已翻页数的起点：翻页途中那次保存也必须写这个累计值，
        # 以前它写的是"这一批几页"，于是后台那一列被反复覆盖成 1、2 ——
        # 实测出现过"翻到第 128 页，已翻页数 2"
        base_req = int(cur["requests"]) if same_pass and cur and cur["requests"] else 0
        fails = 0
        while res["pages"] < max_pages:
            if time.time() >= end_at:
                res["stop"] = "budget"
                break
            page = fetch_page(src, pg)
            if not page["ok"]:
                fails += 1
                res["error"] = page["error"] or "取不到"
                if fails >= MAX_FAILS:
                    res["stop"] = "error"
                    break
                time.sleep(min(6.0, delay * 3 + fails))
                continue
            fails = 0
            items = page["items"]
            if not items:
                res["stop"] = "empty"
                strm.save_cursor(con, src.id, pg, True, pass_id, res["last_time"],
                                 known, base_req + res["pages"], stop="empty",
                                 backfill=1)
                con.commit()
                break
            fresh = False
            for it in items:
                state = strm.record_vod(con, src.id, src.name, it, cfg, pass_id, since)
                res[state] = res.get(state, 0) + 1
                if state == "new":
                    bump(new=1)
                elif state == "changed":
                    bump(changed=1)
                if state in ("new", "changed"):
                    fresh = True
            newest = max((str(x.get("vod_time") or "") for x in items), default="")
            res.update(pages=res["pages"] + 1, last_pg=pg, last_time=newest)
            # since_flush 也走 bump：轮内合并的节奏由"发出去多少页"决定，不是墙上时间
            bump(pages=1, since_flush=1)
            known = 0 if fresh else known + 1
            strm.save_cursor(con, src.id, pg + 1, False, pass_id, newest, known,
                             base_req + res["pages"], stop="", backfill=backfill)
            con.commit()
            progress(per_src={src.id: {"name": src.name, "pg": pg, "last_time": newest,
                                       "known": known, "pages": res["pages"],
                                       "new": res["new"], "changed": res["changed"]}},
                     note=f"翻到 {src.name} 第 {pg} 页")
            # 窗口判据：这一页**最新**的更新时间都已经早于窗口起点，后面只会更旧
            if newest[:10] < since.isoformat():
                res["stop"] = "cutoff"
                strm.save_cursor(con, src.id, pg + 1, True, pass_id, newest, known,
                                 base_req + res["pages"], stop="cutoff", backfill=1)
                res["pruned"] = strm.prune_source(con, src.id, pass_id)
                con.commit()
                if res["pruned"]:
                    print(f"  · {src.name} 清掉窗口外/已下架 {res['pruned']} 条", flush=True)
                break
            if backfill and known >= KNOWN_STOP:
                res["stop"] = "known"
                # 这里刻意不调 prune_source：这一轮只翻了开头几页，
                # 后面那些是几天前采的正常数据，不是下架
                strm.save_cursor(con, src.id, pg + 1, True, pass_id, newest, known,
                                 base_req + res["pages"], stop="known", backfill=1)
                con.commit()
                break
            pg += 1
            if delay:
                # 抖一点点（按源 id 定值，可复现）：几个源整齐划一地同时敲同一家不礼貌
                time.sleep(delay + (abs(hash(src.id)) % 100) / 25000.0)
            maybe_flush(src.name)
        if not res["stop"]:
            res["stop"] = "slice"           # 这一批翻满了 max_pages 页，还没到头，下批再来
        if res["stop"] not in ("cutoff", "known", "empty"):
            # 没翻到头（这一批满了 / 预算用完 / 连续失败）：游标停在下一处，done=0，下批接着翻
            strm.save_cursor(con, src.id, pg, False, pass_id, res["last_time"], known,
                             base_req + res["pages"], stop=res["stop"], backfill=backfill)
            con.commit()
        return res
    finally:
        con.close()


def decide_pass(con) -> tuple[int, list[str]]:
    """这一轮该用哪个轮次号、哪些源的游标要复位到第 1 页。

    还有没翻完的游标 -> 接着那一轮（慢速采集的本意：跨进程续采，别把一轮拆成两轮）。
    全都翻完了     -> 起新的一轮，所有游标复位，从最新那一页往下做增量重扫。
    """
    rows = list(con.execute("SELECT src, pass, done FROM cur"))
    unfinished = [int(r["pass"]) for r in rows if not int(r["done"] or 0)]
    if unfinished:
        return max(unfinished), []
    highest = max([int(r["pass"] or 0) for r in rows], default=0)
    return highest + 1, [r["src"] for r in rows]


def show_check(cfg: dict) -> int:
    c = strm.db_counts()
    print(f"库：{c['vods']} 条 vod / {c['titles']} 部（电影 {c['movies']}·剧集 {c['shows']}）"
          f" · {c['sources']} 个源 · 待导出 {c['dirty']}")
    print(f"文件：{c['files']} 个 strm   窗口 {cfg['window_days']} 天（{strm.cutoff(cfg)} 起）"
          f"   每卷上限 {cfg['part_files']} 个文件   启用采集={cfg['enabled']}")
    last = strm.last_run("collect")
    print(f"上次采集：{json.dumps(last, ensure_ascii=False)[:320] if last else '没跑过'}")
    print("游标：")
    for src, cur in sorted(strm.cursors().items()):
        print(f"  {cur['src']:<10} pg={cur['pg']:<6} done={cur['done']} "
              f"stop={cur['stop'] or '-':<8} backfill={cur['backfill']} "
              f"last={cur['last_time'] or '-'}")
    return 0


def run_export(note: str, full: bool = False) -> dict:
    """导出 + 打包，抢不到写锁就重试几次。

    这一步真的可能被"后台正在保存设置"或另一轮导出顶住（WAL 只允许一个写者）。
    不能让它把整轮采集带走：那些没合并的行在库里仍然是 dirty=1，
    下一轮或下一次访问会补上，采集到的数据一条不丢。
    """
    last = ""
    for attempt in range(4):
        try:
            return strm.export(full=full, note=note)
        except sqlite3.OperationalError as exc:
            last = f"{type(exc).__name__}: {exc}"[:120]
            time.sleep(2 + attempt * 3)
        except Exception as exc:  # noqa: BLE001 - 导出炸了也不能把已采到的数据丢掉
            last = f"{type(exc).__name__}: {exc}"[:120]
            break
    c = strm.db_counts()
    print(f"  · 导出没做成（{last}）：{c['dirty']} 条还留在库里等下一次合并", flush=True)
    return {"ok": False, "written": 0, "skipped": 0, "removed": 0, "keys": 0,
            "seconds": 0, "dir": str(strm.ROOT), "zip_dir": str(strm.ZIPS),
            "zips": {"made": 0, "skipped": 0, "removed": 0}, "error": last,
            "note": note}


def main() -> int:
    ap = argparse.ArgumentParser(description="采集近一年影视资源并导出 Emby strm")
    ap.add_argument("--budget", type=int, default=0,
                    help="本轮最多跑多少秒（默认取后台设置里的 budget_seconds）")
    ap.add_argument("--sources", default="", help="只采这几个源 id，逗号分隔")
    ap.add_argument("--export-only", action="store_true", help="不采集，只导出+打包")
    ap.add_argument("--full", action="store_true", help="导出走全量重建")
    ap.add_argument("--check", action="store_true", help="只打印库与游标状态")
    ap.add_argument("--backfill-only", action="store_true",
                    help="只回填老条目的元数据（简介/演员/上映日/豆瓣号），不翻页")
    args = ap.parse_args()

    strm.ensure_schema()
    cfg = strm.settings()
    if args.check:
        return show_check(cfg)

    if args.export_only:
        out = run_export("手动导出（全量重建）" if args.full else "手动导出", full=args.full)
        write_json(STATE, {"at": strm.now(), "ok": out["ok"], "mode": "export-only",
                          **{k: out[k] for k in ("keys", "written", "skipped", "removed",
                                                  "seconds")}, "zips": out["zips"]})
        print(f"导出：写 {out['written']} / 未变 {out['skipped']} / 删 {out['removed']}"
              f" · 打包 {out['zips']['made']} 卷（沿用 {out['zips']['skipped']}）"
              f" · {out['seconds']}s")
        print(f"目录：{out['dir']}\n分卷包：{out['zip_dir']}")
        return 0

    if not cfg["enabled"] and not args.backfill_only:
        print("后台里「启用每日采集」是关的：要跑就把它打开；"
              "只导出用 --export-only、只补老条目的元数据用 --backfill-only —— "
              "这两个是手动点名的动作，不受这个开关拦")
        return 0

    delay = max(0.0, int(cfg["delay_ms"]) / 1000.0)
    budget = max(30, args.budget or int(cfg["budget_seconds"]))
    since = strm.cutoff(cfg)
    only = {x.strip() for x in args.sources.split(",") if x.strip()}
    excluded = strm.excluded(cfg)
    srcs = [s for s in load_sources()
            if s.enabled and s.api and not s.id.startswith("_")
            and (not only or s.id in only) and s.id not in excluded]
    if not srcs:
        print("没有可采的源（都被停了、被设置排除了，或 --sources 写错了）")
        return 1
    if only:
        missing = only - {s.id for s in srcs}
        if missing:
            print(f"这几个 id 不在启用列表里，已忽略：{'、'.join(sorted(missing))}")

    con = strm.connect()
    try:
        pass_id, reset = decide_pass(con)
        active = {s.id for s in srcs}
        for sid in [x for x in reset if x in active]:
            con.execute("UPDATE cur SET pg=1, done=0, known=0, stop='', pass=?"
                        " WHERE src=?", (pass_id, sid))
        con.commit()
    finally:
        con.close()

    started = time.time()
    end_at = started + budget
    _shared["last_flush"] = started
    print(f"采集开始：{len(srcs)} 个源 · 窗口 {since} 起（{cfg['window_days']} 天）· "
          f"预算 {budget}s · 间隔 {cfg['delay_ms']}ms · 并发 {cfg['workers']} · 轮次 {pass_id}")
    progress(running=True, started_at=strm.now(), finished_at="", pass_id=pass_id,
             budget=budget, per_src={}, reset_per_src=True, note="准备中",
             counts=strm.db_counts(), result="", seconds=0,
             window_days=cfg["window_days"], since=since.isoformat())
    # 轮转调度：每批只让 workers 个源各翻 BATCH_PAGES 页，翻完就换手。
    # 以前是一次把所有源交给线程池 —— 实测 10 分钟只有 4 个源有数据，
    # 其余 13 个源整轮都在排队（每个 worker 抱住一个源翻到预算结束）。
    # 先补老条目的元数据（NFO 要用），再翻新页；自动那档只吃一小段预算，
    # 手动 --backfill-only 才用满整轮
    by_id = {s.id: s for s in load_sources()}
    bf_end = end_at if args.backfill_only else started + budget * BACKFILL_SHARE
    pending_bf = strm.connect()
    try:
        n_todo = pending_bf.execute(
            "SELECT COUNT(*) FROM vod WHERE msig IS NULL OR msig=''").fetchone()[0]
    finally:
        pending_bf.close()
    if n_todo:
        print(f"回填元数据：库里还有 {n_todo} 条没有简介/演员/上映日，"
              f"先按 ID 批量补（最多 {int((bf_end - time.time()) / 60)} 分钟）")
        b = backfill_meta(cfg, pass_id, since, bf_end, delay, by_id)
        print(f"  · 问 {b['chunks']} 批 / {b['asked']} 条：补上 {b['filled']}，"
              f"上游已不认 {b['skipped']}，还剩约 {max(0, n_todo - b['asked'])} 条")
    if args.backfill_only:
        out = run_export("回填元数据后合并")
        c = strm.db_counts()
        print(f"库里：{c['vods']} 条 vod / {c['titles']} 部   "
              f"导出：写 {out['written']} / 未变 {out['skipped']} · 打包 {out['zips']['made']} 卷")
        return 0 if out["ok"] else 1
    agg: dict[str, dict] = {sr.id: {"src": sr.id, "name": sr.name, "pages": 0, "new": 0,
                                    "changed": 0, "same": 0, "skip": 0, "stop": "",
                                    "error": "", "last_pg": 0, "last_time": "",
                                    "pruned": 0} for sr in srcs}
    pending = list(srcs)
    waves = 0
    while pending and time.time() < end_at:
        take = min(int(cfg["workers"]), len(pending))
        wave, pending = pending[:take], pending[take:]
        waves += 1
        wave_end = min(end_at, time.time() + WAVE_SECONDS)
        with ThreadPoolExecutor(max_workers=take) as ex:
            futs = [(sr, ex.submit(crawl_src, sr, cfg, pass_id, since, wave_end,
                                   delay, BATCH_PAGES)) for sr in wave]
            for sr, f in futs:
                try:
                    r = f.result()
                except Exception as exc:  # noqa: BLE001
                    r = {**agg[sr.id], "stop": "error",
                         "error": f"{type(exc).__name__}: {exc}"[:80]}
                a = agg[sr.id]
                for k in ("pages", "new", "changed", "same", "skip", "pruned"):
                    a[k] += r.get(k, 0)
                a["stop"] = r["stop"]
                a["error"] = r.get("error", "")
                a["last_pg"] = r.get("last_pg", a["last_pg"])
                a["last_time"] = r.get("last_time") or a["last_time"]
                if r["stop"] not in ("cutoff", "known", "empty", "done"):
                    pending.append(sr)        # 没翻到头的排到队尾，等下一批换手
        progress(per_src={sr.id: {"name": sr.name, "pg": agg[sr.id]["last_pg"],
                                  "last_time": agg[sr.id]["last_time"],
                                  "pages": agg[sr.id]["pages"], "new": agg[sr.id]["new"],
                                  "changed": agg[sr.id]["changed"],
                                  "stop": agg[sr.id]["stop"]} for sr in wave},
                 note=f"第 {waves} 批：{'、'.join(sr.name for sr in wave)}",
                 waves=waves, sources_left=len(pending))
    results = list(agg.values())
    tot = snap()
    out = run_export(f"本轮采集后合并（轮次 {pass_id}）")
    c = strm.db_counts()
    stop_cn = {"cutoff": "翻到窗口外", "known": "全是老片，提前收", "empty": "没有更多页",
               "budget": "预算用完，下轮接着", "error": "取不到", "done": "本轮已翻完",
               "slice": "这批翻满，已换手", "": "预算用完前没轮到，下轮先来"}
    ok = sum(1 for r in results if r["stop"] != "error")
    note = " · ".join(f"{r['name']}:{stop_cn.get(r['stop'], r['stop'])}"
                      for r in results)
    con = strm.connect()
    try:
        strm.log_run(con, "collect", started, srcs=len(results), requests=tot["requests"],
                     pages=tot["pages"], rows_new=tot["new"], rows_changed=tot["changed"],
                     files_written=out["written"], files_skipped=out["skipped"],
                     files_removed=out["removed"], note=note[:400])
        con.commit()
    finally:
        con.close()
    write_json(STATE, {
        "date": logical_day().isoformat(), "at": strm.now(), "ok": ok == len(results),
        "pass": pass_id, "seconds": round(time.time() - started, 1), "waves": waves,
        "requests": tot["requests"], "pages": tot["pages"],
        "rows_new": tot["new"], "rows_changed": tot["changed"],
        "sources_ok": ok, "sources_total": len(results),
        "window_days": cfg["window_days"], "since": since.isoformat(),
        "counts": c, "export": {k: out[k] for k in ("written", "skipped", "removed")},
        "zips": out["zips"], "note": note, "per_src": results})
    progress(running=False, finished_at=strm.now(), result="ok" if out["ok"] else "fail",
             note=note[:200], counts=c, seconds=round(time.time() - started, 1))
    for r in results:
        print(f"  [{'OK' if r['stop'] != 'error' else 'FAIL'}] {r['name']:<10} "
              f"翻 {r['pages']} 页（到第 {r['last_pg']} 页，{r['last_time'] or '—'}）"
              f" 新 {r['new']} 改 {r['changed']} 同 {r['same']} 跳 {r['skip']}"
              f" -> {stop_cn.get(r['stop'], r['stop'])}"
              + (f"  {r['error']}" if r["stop"] == "error" else "")
              + (f"  清 {r['pruned']} 条" if r.get("pruned") else ""))
    print(f"\n换手 {waves} 批 · 请求 {tot['requests']} 次 · 翻 {tot['pages']} 页 · "
          f"新增 {tot['new']} 条 · 变更 {tot['changed']} 条")
    print(f"库里：{c['vods']} 条 vod / {c['titles']} 部   "
          f"导出：写 {out['written']} / 未变 {out['skipped']} / 删 {out['removed']} · "
          f"打包 {out['zips']['made']} 卷（沿用 {out['zips']['skipped']}）")
    print(f"目录 {out['dir']}   分卷包 {out['zip_dir']}")
    left = [r["name"] for r in results if r["stop"] in ("budget", "slice", "error", "")]
    if left:
        print(f"下一轮接着翻：{'、'.join(left)}（访问网站会自动继续，"
              f"或跑 python tools/collect_strm.py --budget {budget}）")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
