# -*- coding: utf-8 -*-
"""搜索页 SEO：稳定 URL、服务端渲染快照、查询记录、robots 与 sitemap。

思路
  - 每个关键词一个固定地址 /s/<关键词>，可被搜索引擎收录；页面带 title / description /
    canonical / Open Graph / JSON-LD(SearchAction + ItemList)。
  - 结果做**服务端快照**（data/cache/seo-*.json，默认 6 小时），爬虫不必等并发检索，
    也不会每次抓取都去敲上游接口；快照不存在时同步建一次（有预算上限，超时就用已渲染部分）。
  - 用户搜过的关键词记进 data/queries.jsonl，sitemap.xml 由「猜你想搜 + 历史搜索」生成，
    这样别人搜过的剧，其 /s/ 地址会被搜索引擎发现。
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from datetime import date
from pathlib import Path

from . import hot as hot_mod
from .search import search as agg_search

DATA = Path(__file__).resolve().parent / "data"
CACHE = DATA / "cache"
QUERIES = DATA / "queries.jsonl"
SNAP_TTL = 6 * 3600
SNAP_BUDGET = 5.0            # 快照里每个源的等待上限，别把爬虫挂住
MAX_QUERY_LINES = 4000
SAFE = re.compile(r"[^\w\u4e00-\u9fff·:：\- ]+")


def clean_kw(raw: str) -> str:
    kw = SAFE.sub("", (raw or "").strip())[:60]
    return re.sub(r"\s+", " ", kw).strip()


def _key(kw: str) -> str:
    return hashlib.md5(kw.encode("utf-8")).hexdigest()[:16]


def log_query(kw: str) -> None:
    """记录一次搜索，供 sitemap 生成；写失败不影响搜索本身。"""
    kw = clean_kw(kw)
    if len(kw) < 2:
        return
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        with open(QUERIES, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"kw": kw, "at": date.today().isoformat()},
                                ensure_ascii=False) + "\n")
        if QUERIES.stat().st_size > 400_000:          # 粗略轮转，只留最近的部分
            lines = QUERIES.read_text(encoding="utf-8", errors="replace").splitlines()
            QUERIES.write_text("\n".join(lines[-MAX_QUERY_LINES:]) + "\n", encoding="utf-8")
    except OSError:
        return


def recent_queries(limit: int = 300) -> list[str]:
    if not QUERIES.exists():
        return []
    seen, out = set(), []
    try:
        lines = QUERIES.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in reversed(lines):
        try:
            kw = json.loads(line).get("kw")
        except Exception:  # noqa: BLE001
            continue
        if kw and kw not in seen:
            seen.add(kw)
            out.append(kw)
        if len(out) >= limit:
            break
    return out


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _kw_lock(kw: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(_key(kw), threading.Lock())


def snapshot(kw: str, force: bool = False) -> dict:
    """某关键词的服务端结果快照：标题列表 + 命中源数，供 SSR 与 sitemap 用。"""
    kw = clean_kw(kw)
    path = CACHE / f"seo-{_key(kw)}.json"
    if not force and path.exists() and (time.time() - path.stat().st_mtime) < SNAP_TTL:
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            d["from_cache"] = True
            return d
        except Exception:  # noqa: BLE001
            pass
    with _kw_lock(kw):
        # 拿锁后先看一眼，避免同一关键词被并发重复构建；但 force 必须真的重build，
        # 否则会一直返回崩溃时留下的空快照
        if not force and path.exists() and (time.time() - path.stat().st_mtime) < SNAP_TTL:
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
                d["from_cache"] = True
                return d
            except Exception:  # noqa: BLE001
                pass
        err = None
        try:
            res = agg_search(kw, budget=SNAP_BUDGET)
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"[:160]
            res = {"results": [], "sources_ok": 0, "sources_total": 0}
        data = _pack(kw, res, err)
        _save(path, data)
        return data


def _pack(kw: str, res: dict, err: str | None = None) -> dict:
    """一次检索结果 -> 快照要的那几个字段（直开 /s/ 与 SPA 搜索共用这一份形状）。"""
    results = res.get("results") or []
    items = [{"title": r["title"], "year": r.get("year", ""), "type": r.get("type", ""),
              "remarks": r.get("remarks", ""), "n_sources": len(r.get("sources") or []),
              "url": "/s/" + _q(r["title"])}
             for r in results[:24]]
    data = {"kw": kw, "made_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "sources_ok": res.get("sources_ok", 0),
            "sources_total": res.get("sources_total", 0),
            "count": len(results), "items": items,
            "error": err, "from_cache": False}
    # 摘要跟着快照一起走：SPA 换词时 boot.description 还是上一个词的，不能用
    data["description"] = describe(kw, data)
    return data


def _save(path: Path, data: dict) -> None:
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def snapshot_from(kw: str, res: dict) -> dict:
    """用一次已经跑完的搜索结果落一份快照（/api/search 第一页顺手调用）。

    SPA 换词不刷新整页，右栏那块「《X》的检索结果」原本只在直开 /s/<kw> 时才有数据。
    再为同一个词并发敲一遍所有源是白花一轮：手里这份就是同一页的合并结果，
    按快照的字段裁一份写盘，面板立刻有内容，下一次直开 /s/<kw> 也能命中。
    """
    kw = clean_kw(kw)
    data = _pack(kw, res)
    lock = _kw_lock(kw)
    # 不排队等：可能是 /s/ 那条路正在为同一个词建快照。面板要的是手里这份数据，
    # 写盘只是顺手（让下一次直开直接命中），谁先写完算谁的，别为它把这轮响应拖住
    if lock.acquire(blocking=False):
        try:
            _save(CACHE / f"seo-{_key(kw)}.json", data)
        finally:
            lock.release()
    return data


def _q(s: str) -> str:
    from urllib.parse import quote
    return quote(s)


def sitemap_entries(site: str = "") -> list[dict]:
    """sitemap 条目：猜你想搜的片名 + 历史搜索过的关键词。"""
    out, seen = [], set()
    today = date.today().isoformat()
    h = hot_mod.get()
    for sec in ("movie", "tv"):
        for x in h.get(sec) or []:
            t = clean_kw(x["title"])
            if t and t not in seen:
                seen.add(t)
                out.append({"loc": f"{site}/s/{_q(t)}", "lastmod": today, "title": t})
    for t in recent_queries():
        if t and t not in seen:
            seen.add(t)
            out.append({"loc": f"{site}/s/{_q(t)}", "lastmod": today, "title": t})
    out.insert(0, {"loc": site + "/", "lastmod": today, "title": "追剧资源搜索"})
    return out


def robots_txt(site: str = "") -> str:
    return ("User-agent: *\n"
            "Allow: /$\n"
            "Allow: /s/\n"
            "Disallow: /api/\n"
            "Disallow: /admin\n"
            f"Sitemap: {site}/sitemap.xml\n")


def describe(kw: str, snap: dict) -> str:
    """给搜索引擎看的摘要（也用于 og:description）。"""
    n = snap.get("count", 0)
    if not n:
        return f"《{kw}》的影视资源检索入口"
    names = "、".join(x["title"] for x in (snap.get("items") or [])[:4])
    return (f"《{kw}》在 {snap.get('sources_ok', 0)}/{snap.get('sources_total', 0)} "
            f"个影视资源站共检索到 {n} 条相关结果：{names} 等")
