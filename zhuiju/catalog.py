# -*- coding: utf-8 -*-
"""资源站目录检索与跨站直达链接。

目录数据来自上游 awesome-zhuiju-free 的结构化清单（名称/地址/分类/评分/可用状态等事实字段）。
直达链接模板由 tools/probe_templates.py 实测生成，未通过验证的站点只给首页。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

DATA = Path(__file__).resolve().parent / "data"

CATEGORY_ORDER = ["在线影视", "影视APP", "网盘搜索", "磁力 & BT",
                  "TVBox 配置", "TVBox 空壳", "字幕资源", "直播源", "开源项目"]

STATUS_DOT = {"reachable": "🟢", "ok": "🟢", "restricted": "🟡",
              "unreachable": "🔴", "failed": "🔴", "unchecked": "⚪"}

SEP = re.compile(r"[ 　 \t]+")


_cache: dict[str, tuple[float, object]] = {}


def _load_cached(name: str, default):
    """按文件修改时间缓存：定时任务刷新数据后，站点不用重启就能读到新内容。"""
    path = DATA / name
    if not path.exists():
        return default
    mtime = path.stat().st_mtime
    hit = _cache.get(name)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 刷新写一半时先沿用旧数据
        if hit:
            return hit[1]
        return default
    _cache[name] = (mtime, data)
    return data


def catalog() -> dict:
    return _load_cached("catalog.json", {"items": [], "updated_at": ""}) or {}


def templates() -> dict:
    """{站点url或id: 站内搜索模板}"""
    t = _load_cached("templates.json", {})
    return t.get("templates", {}) if isinstance(t, dict) else {}


def reload_data():
    _cache.clear()


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (s or "").lower())


def _entry_template(item: dict) -> str | None:
    t = templates()
    return t.get(item["id"]) or t.get(item["url"]) or t.get(item["url"].rstrip("/"))


def link_for(item: dict, kw: str) -> dict:
    tpl = _entry_template(item)
    if tpl:
        return {"url": tpl.replace("{kw}", quote(kw)), "kind": "site_search"}
    return {"url": item["url"], "kind": "homepage"}


def search(kw: str, category: str | None = None,
           only_working: bool = False, limit: int = 60) -> list[dict]:
    nkw = _norm(kw)
    out = []
    for it in catalog().get("items", []):
        if category and it["category_cn"] != category:
            continue
        if only_working and it["status_key"] not in ("reachable", "ok"):
            continue
        nname, ncat = _norm(it["name"]), _norm(it["category_cn"])
        tags = "".join(_norm(t) for t in it.get("tags", []))
        if not nkw:
            score = 2 if it["featured"] else 1
        elif nname and (nkw == nname):
            score = 100
        elif nkw and nkw in nname:
            score = 70
        elif nkw and nname in nkw:
            score = 55
        elif nkw and ncat and nkw in ncat:
            score = 40
        elif nkw and tags and nkw in tags:
            score = 30
        elif nkw and nkw in _norm(it["url"]):
            score = 20
        elif nkw and (nkw in tags or any(t in kw for t in it.get("tags", []))):
            score = 15
        else:
            continue
        if score < 15 and nkw:
            continue
        row = dict(it)
        row["dot"] = STATUS_DOT.get(it["status_key"], "⚪")
        row["score"] = score + it["recommended"] / 10
        row["deep"] = link_for(it, kw) if kw else None
        out.append(row)
    out.sort(key=lambda r: (-r["score"], r["category_cn"], r["name"]))
    return out[:limit]


def categories() -> list[dict]:
    counts: dict[str, dict] = {}
    for it in catalog().get("items", []):
        c = counts.setdefault(it["category_cn"], {"name": it["category_cn"],
                                                  "total": 0, "working": 0})
        c["total"] += 1
        if it["status_key"] in ("reachable", "ok"):
            c["working"] += 1
    ordered = [counts[k] for k in CATEGORY_ORDER if k in counts]
    ordered += [v for k, v in counts.items() if k not in CATEGORY_ORDER]
    return ordered


def deeplinks(kw: str, categories: tuple[str, ...] = ("网盘搜索", "磁力 & BT",
                                                       "在线影视", "字幕资源")) -> list[dict]:
    """把片名送到各网盘/磁力/在线站。

    kw 为空时也要有内容可看：返回这些站的首页入口，前端据此提示"搜索后自动带关键词"，
    而不是空着一块。
    """
    res = []
    for cat in categories:
        rows = [it for it in catalog().get("items", []) if it["category_cn"] == cat]
        rows.sort(key=lambda r: (-r["recommended"], r["name"]))
        for it in rows:
            d = link_for(it, kw) if kw else {"url": it["url"], "kind": "homepage"}
            res.append({
                "name": it["name"], "category": cat, "dot": d and STATUS_DOT.get(
                    it["status_key"], "⚪"),
                "status": it["status"], "recommended": it["recommended"],
                "url": d["url"], "kind": d["kind"], "featured": it["featured"],
                "home": it["url"],
            })
    res.sort(key=lambda r: (CATEGORY_ORDER.index(r["category"])
                            if r["category"] in CATEGORY_ORDER else 99,
                            -r["recommended"]))
    return res
