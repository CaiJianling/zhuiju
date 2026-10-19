# -*- coding: utf-8 -*-
"""猜你想搜：空搜索框时展示的「电影 / 电视剧」近期条目（最近半年）。

为什么是两个池子（都是实测出来的约束）：
  - 采集接口的全局"最近更新"流里 limit 被硬限 20 条，内容又被 中国动漫/内地剧 占满
    （虎牙 20 条里 11 条是中国动漫），电影在这里天然稀少；而带 t=分类ID 只返回 0~2 条，
    所以"按分类列最新"这条路不通。
  - 因此：电视剧走 CMS 最新流（能拿到多源覆盖度），电影再补一批豆瓣「热门/新片」候选。
  - "最近半年"一律用 CMS 的 vod_time / vod_year 判定：豆瓣的 j/search_subjects 不返回
    上映日期，只用来出候选、评分和海报；豆瓣候选还要回查 CMS 命中才算数，
    这样点进去一定有结果。

缓存 data/cache/hot.json，默认 6 小时重建；重建失败沿用旧缓存并标注 stale。
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
import threading
import time
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

import requests

from .imgproxy import register as imgproxy_register
from .search import clean_text, fetch_one, load_sources, title_key
from .sources import Source

requests.packages.urllib3.disable_warnings()

CACHE = Path(__file__).resolve().parent / "data" / "cache" / "hot.json"
TTL = 6 * 3600
HALF_YEAR_DAYS = 183
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# 电影类先判：'动画片' 既含"片"又含"动漫"，应归电影而不是番剧
MOVIE_WORDS = re.compile(r"(电影|影片|动作片|喜剧片|爱情片|科幻片|恐怖片|剧情片|战争片|"
                         r"动画片|记录片|纪录片|邵氏|伦理片|电影解说)")
TV_WORDS = re.compile(r"(剧|综艺|动漫|番|真人秀|脱口秀)")

DOUBAN_LISTS = [("movie", "热门"), ("movie", "新片"), ("tv", "热门"), ("tv", "国产剧")]
FEED_PAGES = 3          # 每个源取几页最新（每页实际上限 20 条）
VERIFY_SOURCES = 3      # 豆瓣候选回查 CMS 时用几个源


def _year(v) -> int:
    m = re.search(r"(19|20)\d{2}", str(v or ""))
    return int(m.group(0)) if m else 0


def _date(v: str):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def kind_of(type_name: str) -> str:
    t = clean_text(type_name)
    if MOVIE_WORDS.search(t):
        return "movie"
    if TV_WORDS.search(t):
        return "tv"
    return ""


def _recent(item: dict, since: date) -> bool:
    """最近半年：更新时间在窗口内，或年份是今年。"""
    d = _date(item.get("updated"))
    return bool(d and d >= since) or _year(item.get("year")) >= date.today().year


def _mk(title: str, item: dict, src_id: str) -> dict:
    # 条目自己带的 source 才是真的采集源 id（豆瓣候选回查那条路传进来的 src_id 是占位词 "douban"）
    sid = str(item.get("source") or src_id or "")
    vid = str(item.get("vid") or "")
    return {
        "title": title, "kind": kind_of(item.get("type", "")),
        "year": str(item.get("year") or ""), "type": item.get("type", ""),
        "remarks": item.get("remarks", ""), "pic": item.get("pic", ""),
        "updated": str(item.get("updated") or ""), "sources": {src_id},
        # 记下"哪个源的哪个 ID"：列表模式不给海报时用它补图，
        # 点开详情时用它直接 ac=detail，省掉一次全源并发检索。
        "probe": (sid, vid),
        # 每个源各自的影片 ID 都要留着：面板上「换源看」的每一颗按钮就是这里的一项。
        # 只留 probe 那一对的话，猜你想搜那些片就没有源可换。
        "vids": ({sid: vid} if vid else {}),
    }


def fill_pics(buckets: dict, sources: list[Source], limit: int = 300) -> int:
    """列表接口(ac=list)常常不带 vod_pic，用 ac=detail 再查一次把海报补上。"""
    from .search import detail as fetch_detail

    by_id = {s.id: s for s in sources}
    todo = [(b, b["probe"]) for b in buckets.values()
            if not b["pic"] and b["probe"][0] in by_id and b["probe"][1]][:limit]
    if not todo:
        return 0

    def one(b, probe):
        src = by_id[probe[0]]
        d = fetch_detail(src, probe[1], b["title"])
        return b, (d.get("pic") or "") if d.get("ok") else ""

    filled = 0
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for b, pic in ex.map(lambda t: one(*t), todo):
            if pic:
                b["pic"] = pic
                filled += 1
    return filled


def feed_pool(sources: list[Source], since: date) -> dict:
    """CMS 最近更新流：按片名合并，记录覆盖到的源数。"""
    buckets: dict[str, dict] = {}

    def one(s: Source, pg: int):
        return s, fetch_one(s, "", page=pg, limit=20)

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        jobs = [ex.submit(one, s, pg) for s in sources for pg in range(1, FEED_PAGES + 1)]
        for f in cf.as_completed(jobs):
            try:
                s, res = f.result()
            except Exception:  # noqa: BLE001
                continue
            if not res["ok"]:
                continue
            for it in res["items"]:
                title = clean_text(it.get("title", ""))
                key = title_key(title)
                if not key or len(key) < 2 or not _recent(it, since):
                    continue
                b = buckets.get(key)
                if b is None:
                    b = buckets[key] = _mk(title, it, s.id)
                b["sources"].add(s.id)
                # 同名片在别的源也有各自的 ID，一并留着给面板上的「换源看」
                sid = str(it.get("source") or s.id)
                if it.get("vid"):
                    b["vids"].setdefault(sid, str(it["vid"]))
                if str(it.get("updated") or "") > b["updated"]:
                    b["updated"] = str(it.get("updated") or "")
                if not b["kind"]:
                    b["kind"] = kind_of(it.get("type", ""))
                if not b["pic"] and it.get("pic"):
                    b["pic"] = it["pic"]
                if not b["year"] and it.get("year"):
                    b["year"] = str(it["year"])
    return buckets


def douban_lists(timeout: float = 8.0) -> dict:
    """豆瓣榜单：出候选片名 + 评分 + 海报。拿不到就返回空，不影响主流程。"""
    out: dict[str, dict] = {}
    for stype, tag in DOUBAN_LISTS:
        url = ("https://movie.douban.com/j/search_subjects?"
               + urllib.parse.urlencode({"type": stype, "tag": tag,
                                         "page_limit": 30, "page_start": 0}))
        try:
            r = requests.get(url, timeout=timeout,
                             headers={"User-Agent": UA, "Referer": "https://movie.douban.com/"})
            subjects = (r.json() or {}).get("subjects") or []
        except Exception:  # noqa: BLE001
            continue
        for s in subjects:
            if not isinstance(s, dict):
                continue
            title = clean_text(s.get("title", ""))
            key = title_key(title)
            if not key:
                continue
            out.setdefault(key, {
                "title": title, "douban_type": stype,
                "rate": clean_text(s.get("rate", "")),
                "cover": clean_text(s.get("cover", "")),
                "douban_url": clean_text(s.get("url", "")),
            })
    return out


def verify_pool(cands: list[dict], sources: list[Source], since: date) -> dict:
    """豆瓣候选回查采集源：既确认点进去搜得到，也从返回的 vod_year/vod_time 落实最近半年。"""
    if not cands:
        return {}
    probes = sources[:VERIFY_SOURCES]

    def one(title: str):
        hits = []
        for s in probes:
            res = fetch_one(s, title, limit=10)
            if res["ok"]:
                hits.extend(res["items"])
        return title, hits

    found: dict[str, dict] = {}
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for title, hits in ex.map(one, [c["title"] for c in cands]):
            key = title_key(title)
            best = None
            vids: dict[str, str] = {}
            for it in hits:
                if title_key(it.get("title", "")) != key:
                    continue          # 只认同名，不接受模糊带出来的别的片
                if not _recent(it, since):
                    continue
                if it.get("vid"):
                    # 探了好几个源，把每个源给的那对 ID 都留下：换源看不只要有得换，
                    # 还得知道"换成哪个源的哪个 ID"
                    vids[str(it.get("source") or "")] = str(it["vid"])
                if best is None or (it.get("pic") and not best.get("pic")):
                    best = it
            if best:
                b = _mk(title, best, "douban")
                for sid, vid in vids.items():
                    if sid:
                        b["vids"].setdefault(sid, vid)
                found[key] = b
    return found


def pack_row(b: dict, d: dict, names: dict | None = None) -> dict:
    """一个候选条目 -> 页面/缓存里的那一行。

    单独拆出来是为了能被测试直接调用（以前它是 build() 里的闭包，
    想验一行里少了哪些字段就得真跑一遍 build，那要几分钟网络）。
    """
    # 豆瓣封面优先：CMS 的图挂在非标端口/自签证书上的比例高得多（浏览器会静默加载失败）
    pic = d.get("cover") or b["pic"]
    src, vid = b.get("probe") or ("", None)
    names = names or {}
    # 「换源看」的每一颗按钮就是这些 (源, 该源里的影片 ID)：probe 那个排在最前，
    # 面板打开时选中的就是它
    srcs = []
    if src and vid:
        srcs.append({"id": str(src), "name": names.get(str(src), str(src)), "vid": str(vid)})
    for sid, svid in (b.get("vids") or {}).items():
        if svid and not any(sid == x["id"] for x in srcs):
            srcs.append({"id": sid, "name": names.get(sid, sid), "vid": str(svid)})
    return {
        "title": b["title"],
        "kind": b["kind"] or ("movie" if d.get("douban_type") == "movie" else "tv"),
        "year": b["year"], "type": b["type"], "remarks": b["remarks"],
        "pic": pic, "rate": d.get("rate", ""),
        "douban": bool(d), "updated": b["updated"], "n_sources": len(b["sources"]),
        "from_douban": "douban" in b["sources"],
        # 带上这对儿就能直接 ac=detail；缓存可能比源列表旧（源改名/停用），
        # 取不到详情时前端会退回按片名查，所以这里带着空值也没关系
        "src": str(src or ""), "vid": str(vid or ""), "sources": srcs,
        "url": "/s/" + urllib.parse.quote(b["title"]),
    }


def build(limit_each: int = 60) -> dict:
    today = date.today()
    since = today - timedelta(days=HALF_YEAR_DAYS)
    sources = [s for s in load_sources() if s.enabled]

    buckets = feed_pool(sources, since)
    douban = douban_lists()
    cands = [v for k, v in douban.items() if k not in buckets]
    verified = verify_pool(cands, sources, since)
    buckets.update(verified)
    # 列表模式不给海报的，用详情补一遍（实测 36 条里有 15 条没图）
    filled = fill_pics(buckets, sources)

    # 源改名或停用了，缓存里那行仍显示当时那个名字：名字在这里就定好写进缓存
    names = {s.id: s.name for s in sources}

    def pack(key: str, b: dict) -> dict:
        return pack_row(b, douban.get(key, {}), names)

    def sort_key(x):
        """猜你想搜按"最新在前"排：更新时间倒序，其次年份，再按覆盖源数与豆瓣评分。"""
        updated = str(x.get("updated") or "")
        y = re.search(r"(19|20)\d{2}", str(x.get("year") or ""))
        return (updated, y.group(0) if y else "0", x["n_sources"],
                float(x["rate"] or 0))

    rows = [pack(k, b) for k, b in buckets.items() if b["kind"]]
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "since": since.isoformat(),
        "sources_ok": len(sources), "sources_total": len(load_sources()),
        "douban_candidates": len(douban), "douban_added": len(verified),
        "pics_filled": filled,
        "candidates": len(buckets),
        "movie": sorted([r for r in rows if r["kind"] == "movie"], key=sort_key,
                        reverse=True)[:limit_each],
        "tv": sorted([r for r in rows if r["kind"] == "tv"], key=sort_key,
                     reverse=True)[:limit_each],
    }


def page(kind: str, offset: int = 0, limit: int = 12) -> dict:
    """从缓存里按页取，供前端"往右翻页"用；海报在这里登记+改走代理。"""
    from urllib.parse import quote

    data = get()
    rows = data.get(kind) or []
    total = len(rows)
    offset = max(0, int(offset))
    limit = max(1, min(30, int(limit)))
    chunk = rows[offset:offset + limit]
    out = []
    for x in chunk:
        pic = x.get("pic", "")
        if pic.startswith("http"):
            imgproxy_register(pic)
            pic = f"/img?url={quote(pic, safe='')}"
        out.append({**x, "pic": pic})
    return {"kind": kind, "offset": offset, "limit": limit, "total": total,
            "items": out, "has_more": offset + limit < total,
            "next": offset + limit}


def _write_cache(data: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CACHE)


def get(force: bool = False) -> dict:
    """读缓存；过期则**后台**重建，请求本身不等待（build 要 100 秒左右）。

    没有缓存时先返回空列表并触发重建，前端据此显示"正在准备"，
    下一次访问就有了——绝不让首屏卡在重建上。
    """
    cached = _read_cache()
    fresh = cached and (time.time() - CACHE.stat().st_mtime) < TTL
    if fresh and not force:
        return {**cached, "stale": False, "cached": True, "building": False}
    if cached:
        _rebuild_async()
        return {**cached, "stale": True, "cached": True, "building": True}
    _rebuild_async()
    return {"movie": [], "tv": [], "candidates": 0, "since": _since().isoformat(),
            "stale": True, "cached": False, "building": True}


_lock = threading.Lock()
_building = {"at": 0.0}


def _since() -> date:
    return date.today() - timedelta(days=HALF_YEAR_DAYS)


def _read_cache():
    if not CACHE.exists():
        return None
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _rebuild_async() -> None:
    """同一进程内只允许一个重建线程，且两次启动间隔至少 5 分钟。"""
    now = time.time()
    with _lock:
        if now - _building["at"] < 300:
            return
        _building["at"] = now
    threading.Thread(target=rebuild, daemon=True).start()


def rebuild() -> dict | None:
    """真正重建；失败时保留旧缓存。"""
    try:
        data = build()
    except Exception as exc:  # noqa: BLE001
        cached = _read_cache()
        if cached:
            cached["error"] = f"{type(exc).__name__}: {exc}"[:120]
            return cached
        return None
    if data["movie"] or data["tv"]:
        _write_cache(data)
        return data
    return None
