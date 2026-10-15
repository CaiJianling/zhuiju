# -*- coding: utf-8 -*-
"""聚合检索：并发调用多个公开采集接口，按片名归并去重。"""
from __future__ import annotations

import concurrent.futures as cf
import re
import time
from urllib.parse import quote, urljoin, urlparse

import requests

from .sources import Source, load_sources

requests.packages.urllib3.disable_warnings()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

TAG_RE = re.compile(r"<[^>]+>")
SEP_RE = re.compile(r"[ 　 \t]+")
NOISE_RE = re.compile(
    r"(HD|BD|TC|TS|4K|8K|1080P|720P|BluRay|WEB-DL|HDMid|未删减|加长版|完整版|正片)\s*$",
    re.I,
)

# 单源超时与整体预算：宁可少几个源，也不让页面卡住
SOURCE_TIMEOUT = 6.0
BUDGET = 7.0


def clean_text(s) -> str:
    if not isinstance(s, str):
        return ""
    s = TAG_RE.sub(" ", s)
    s = (s.replace("&amp;", "&").replace("&nbsp;", " ")
           .replace("\u3000", " ").replace("\xa0", " "))
    return SEP_RE.sub(" ", s).strip()


def title_key(name: str) -> str:
    """归一化片名用于跨源合并：去空格/标点/大小写与尾部长宽标识。"""
    s = NOISE_RE.sub("", clean_text(name))
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", s)
    return s.lower()


def display_title(name: str) -> str:
    return NOISE_RE.sub("", clean_text(name)).strip()


def site_search_url(src: Source, kw: str) -> str:
    """该源可浏览时的站内搜索链接；纯 API 站（首页 403/500）返回空串，避免跳到拦截页。"""
    if src.search_template:
        return src.search_template.replace("{kw}", quote(kw))
    if src.browsable and src.root:
        return src.root
    return ""


def _session(src: Source) -> requests.Session:
    s = requests.Session()
    host = f"{urlparse(src.api).scheme}://{urlparse(src.api).netloc}"
    s.headers.update({
        "User-Agent": UA,
        "Referer": host + "/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    return s


def parse_maccms(payload: dict) -> list[dict]:
    """苹果CMS provide/vod 规范：list[] 内为影片概要字段。"""
    out = []
    for v in payload.get("list") or []:
        if not isinstance(v, dict):
            continue
        name = display_title(v.get("vod_name", ""))
        if not name:
            continue
        out.append({
            "vid": v.get("vod_id"),
            "title": name,
            "type": clean_text(v.get("type_name", "")),
            "year": clean_text(v.get("vod_year", "")),
            "area": clean_text(v.get("vod_area", "")),
            "remarks": clean_text(v.get("vod_remarks", "")),
            "actor": clean_text(v.get("vod_actor", ""))[:60],
            "director": clean_text(v.get("vod_director", ""))[:40],
            "pic": clean_text(v.get("vod_pic", "")),
            "notes": clean_text(v.get("vod_note", "")),
            "updated": clean_text(v.get("vod_time", ""))[:10],
            "slug": clean_text(v.get("vod_en", "")),
        })
    return out


PARSERS = {"maccms": parse_maccms}


def fetch_one(src: Source, kw: str, page: int = 1, limit: int = 20,
              type_id=None) -> dict:
    """返回 {source, ok, count, items, ms, error}

    kw 为空时是"最近更新列表"；给 type_id 则按该源的类型 ID 取分类最新，
    用于猜你想搜区分电影 / 电视剧（只取全局最新会被动漫、短剧占满）。
    """
    t0 = time.time()
    params = {"ac": "list", "pg": page, "limit": limit}
    if kw:
        params["wd"] = kw
    if type_id is not None:
        params["t"] = type_id
    params.update(src.params or {})
    try:
        r = _session(src).get(src.api, params=params, timeout=SOURCE_TIMEOUT, verify=False)
        ct = (r.headers.get("Content-Type") or "").lower()
        body = (r.text or "").strip()
        if r.status_code != 200:
            return _fail(src, f"HTTP {r.status_code}", t0)
        if body[:1] not in "{[":
            hint = "接口返回非 JSON（可能被拦截/需白名单）" if "html" in ct else "接口返回格式不支持"
            return _fail(src, hint, t0)
        payload = r.json()
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            payload = payload["data"]
        parser = PARSERS.get(src.kind)
        if parser is None or not isinstance(payload, dict):
            return _fail(src, f"未支持的接口类型: {src.kind}", t0)
        items = parser(payload)
        total = payload.get("total")
        for it in items:
            it["source"] = src.id
            it["source_name"] = src.name
            it["link"] = site_search_url(src, kw)
        return {"source": src.id, "source_name": src.name, "ok": True,
                "count": len(items), "total": total, "items": items,
                "ms": int((time.time() - t0) * 1000), "error": None}
    except requests.exceptions.Timeout:
        return _fail(src, "超时", t0)
    except requests.exceptions.ConnectionError:
        return _fail(src, "无法连接", t0)
    except Exception as exc:  # noqa: BLE001 - 单源异常不应影响整体
        return _fail(src, f"{type(exc).__name__}: {exc}"[:80], t0)


def split_play_from(raw: str, nblocks: int) -> list[str]:
    """vod_play_from 的分隔符不统一：多线接口用 '$$$'，也有用 '+' 的。
    取与线路块数一致的那一种，都对不上时退回"线路N"。"""
    raw = raw or ""
    for sep in ("$$$", "+"):
        parts = [clean_text(p) for p in raw.split(sep) if p.strip()]
        if len(parts) == nblocks and parts:
            return parts
    one = clean_text(raw)
    if one and nblocks == 1:
        return [one]
    return []


def parse_maccms_detail(payload: dict) -> dict:
    """ac=detail 返回带播放地址的完整条目，拆成 线路 -> 剧集 列表。"""
    lst = payload.get("list") or []
    if not lst or not isinstance(lst[0], dict):
        return {"lines": []}
    v = lst[0]
    blocks = [b for b in str(v.get("vod_play_url", "")).split("$$$") if b.strip()]
    froms = split_play_from(str(v.get("vod_play_from", "")), len(blocks))
    lines = []
    for i, block in enumerate(blocks):
        eps = []
        for piece in block.split("#"):
            if not piece:
                continue
            name, _, addr = piece.partition("$")
            if addr.strip():
                eps.append({"name": clean_text(name) or f"第{i + 1}条", "url": addr.strip()})
        if eps:
            lines.append({"from": froms[i] if i < len(froms) else f"线路{i + 1}",
                          "episodes": eps})
    return {
        "title": display_title(v.get("vod_name", "")),
        "type": clean_text(v.get("type_name", "")),
        "year": clean_text(v.get("vod_year", "")),
        "area": clean_text(v.get("vod_area", "")),
        "actor": clean_text(v.get("vod_actor", "")),
        "director": clean_text(v.get("vod_director", "")),
        "pic": clean_text(v.get("vod_pic", "")),
        "blurb": clean_text(v.get("vod_blurb", "")) or clean_text(v.get("vod_content", ""))[:300],
        "notes": clean_text(v.get("vod_remarks", "")),
        "lines": lines,
    }


def detail(src: Source, vid, expect_title: str = "") -> dict:
    """按影片 ID 取该源的播放线路。

    注意：maccms 的 ac=detail 只认 ids 参数；传错参数名时接口不会报错，
    而是安静地返回"最新上架"列表，所以这里必须校验返回结果确实是所请求的那部。
    """
    try:
        r = _session(src).get(src.api, params={"ac": "detail", "ids": vid},
                              timeout=SOURCE_TIMEOUT, verify=False)
        if r.status_code != 200:
            return {"ok": False, "error": f"HTTP {r.status_code}",
                    "source": src.id, "source_name": src.name}
        payload = r.json()
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            payload = payload["data"]
        if not isinstance(payload, dict):
            payload = {}
        d = parse_maccms_detail(payload)
        first = (payload.get("list") or [{}])[0]
        same_id = str(first.get("vod_id")) == str(vid)
        want = title_key(expect_title or "")
        got = title_key(d.get("title") or "")
        same_title = bool(want) and want == got

        error = None
        if not d.get("lines"):
            error = "该源没有返回可播放的线路"
        elif not (same_id or same_title):
            # 参数被忽略、返回了默认列表 —— 不能拿别人的线路给用户
            error = "该源不支持按 ID 取线路（返回了其它影片）"
            d = {"lines": []}
        return {**d, "ok": error is None, "error": error,
                "source": src.id, "source_name": src.name}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}"[:60],
                "source": src.id, "source_name": src.name}


def _fail(src: Source, msg: str, t0: float) -> dict:
    return {"source": src.id, "source_name": src.name, "ok": False, "count": 0,
            "total": None, "items": [], "ms": int((time.time() - t0) * 1000),
            "error": msg}


def merge(per_source: list[dict], kw: str) -> list[dict]:
    """按归一化片名跨源合并，返回按"覆盖源数 + 年份"排序的结果。"""
    buckets: dict[str, dict] = {}
    order: list[str] = []
    for res in per_source:
        if not res["ok"]:
            continue
        for it in res["items"]:
            key = title_key(it["title"]) or it["title"]
            b = buckets.get(key)
            if b is None:
                b = {**it, "sources": [], "source_ids": set(), "exact": False}
                buckets[key] = b
                order.append(key)
            if it["source"] not in b["source_ids"]:
                b["source_ids"].add(it["source"])
                b["sources"].append({
                    "id": it["source"], "name": it["source_name"],
                    "link": it["link"], "remarks": it["remarks"],
                    "year": it["year"], "vid": it["vid"],
                })
            # 保留信息更完整的一条（有海报/年份/演员优先）
            if _richness(it) > _richness({k: b[k] for k in ("year", "pic", "actor", "remarks")}):
                for k in ("year", "area", "type", "pic", "actor", "director",
                          "remarks", "updated", "title"):
                    if it.get(k):
                        b[k] = it[k]

    kw_key = title_key(kw)
    results = []
    dropped = 0
    for key in order:
        b = buckets[key]
        b["source_ids"] = sorted(b["source_ids"])
        b["tier"] = match_tier(kw_key, key)
        b["exact"] = b["tier"] == 0
        b["match"] = {0: "exact", 1: "series", 2: "contains", 3: "other"}[b["tier"]]
        b["key_len"] = len(key)
        # 归一化后与关键词零重叠：是接口自身模糊匹配吐出来的噪声（英文片名时尤其多），丢掉
        if b["tier"] == 3:
            dropped += 1
            continue
        results.append(b)

    results.sort(key=lambda b: (b["tier"], -len(b["sources"]),
                                -_year_num(b.get("year")),
                                abs(b["key_len"] - len(kw_key)),
                                b["title"]))
    return results, dropped


def match_tier(kw_key: str, key: str) -> int:
    """匹配强度：0 完全同名，1 前缀/被前缀（续集、特别版），2 包含，3 其它。

    只用"包含"会把《灌篮高手的契约》当成《灌篮高手》的精确命中，
    蹭名短剧因此排到正片前面，所以要分层。
    """
    if not kw_key or not key:
        return 3
    if key == kw_key:
        return 0
    if key.startswith(kw_key) or kw_key.startswith(key):
        return 1
    if kw_key in key or key in kw_key:
        return 2
    return 3


def _richness(d) -> tuple:
    return (bool(d.get("pic")), bool(d.get("year")), bool(d.get("actor")),
            bool(d.get("remarks")))


def _year_num(y) -> int:
    m = re.search(r"(19|20)\d{2}", str(y or ""))
    return int(m.group(0)) if m else 0


def search(kw: str, sources: list[Source] | None = None,
           page: int = 1, budget: float = BUDGET) -> dict:
    sources = [s for s in (sources or load_sources()) if s.enabled]
    # extra 必须是 list：超时分支要往里 append，写成 dict 会在"某源超预算"时抛
    # AttributeError 直接 500，而这条路径平时不触发，很容易漏掉
    per, extra = [], []
    with cf.ThreadPoolExecutor(max_workers=min(12, max(1, len(sources)))) as ex:
        futs = {ex.submit(fetch_one, s, kw, page): s for s in sources}
        try:
            for f in cf.as_completed(futs, timeout=budget):
                per.append(f.result())
        except cf.TimeoutError:
            for f, s in futs.items():
                if not f.done():
                    extra.append(_fail(s, f"超过 {budget:.0f}s 未响应", time.time()))
                    f.cancel()
    per.sort(key=lambda r: [s.id for s in sources].index(r["source"])
             if r["source"] in [s.id for s in sources] else 99)
    ok = [r for r in per if r["ok"]]
    merged, dropped = merge(per, kw)
    return {
        "keyword": kw,
        "page": page,
        "results": merged,
        "dropped_noise": dropped,
        "status": [{k: r[k] for k in ("source", "source_name", "ok", "count", "ms", "error")}
                   for r in per + [e for e in extra if e["source"] not in
                                   {p["source"] for p in per}]],
        "sources_ok": len(ok),
        "sources_total": len(sources),
        "hits": sum(r["count"] for r in per),
    }
