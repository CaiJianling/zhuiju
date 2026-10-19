# -*- coding: utf-8 -*-
"""网盘 / 磁力站的服务端查询：抓各站搜索结果页并解析出条目。

现实约束（tools/probe_cloud.py 实测）：目录里 4 家网盘站的搜索是 POST 表单或纯 JS 提交，
服务端抓不到结果；能解析的是那些搜索页直接返回 HTML 的站点。因此这里对每个站分别记录状态，
拿不到结果的站如实标注，不做"假装搜到了"的降级。
"""
from __future__ import annotations

import concurrent.futures as cf
import re
from urllib.parse import quote, urljoin, urlparse

import requests

from . import catalog as catalog_mod
from .search import clean_text, title_key

requests.packages.urllib3.disable_warnings()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

SOURCE_CATS = ("网盘搜索", "磁力 & BT")
SITE_TIMEOUT = 10.0
BUDGET = 14.0
MAX_PER_SITE = 12

A_RE = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
BAD_HREF = re.compile(r"(javascript:|mailto:|\.js$|\.css$|\.png$|\.jpg$|#)", re.I)
# 结果条目应指向内容页；导航链接用这些前缀排除掉
NAV_TEXT = re.compile(r"^(首页|登录|注册|更多|下一页|上一页|分类|搜索|下载APP|APP)$")


def one_line(s: str) -> str:
    """把锚点里的多行文本压成一行：不少站点把标题、外文名、分类写在相邻标签里。"""
    return re.sub(r"\s+", " ", s or "").strip()


NAV_LABELS = re.compile(r"^(更多|下一页|上一页|首页|登录|注册|分类|搜索|"
                        r".{0,20}(搜索|剧集|专区|列表))$")


def _entry_ok(kw_key: str, text: str, href: str) -> bool:
    """结果条目判定：文本要有实质内容、不是导航词，且与关键词有字符重叠。"""
    if not text or NAV_TEXT.match(text) or NAV_LABELS.match(text):
        return False
    if BAD_HREF.search(href):
        return False
    tkey = title_key(text)
    if not tkey or len(tkey) < 2:
        return False
    if not kw_key:
        return False
    return kw_key in tkey or tkey in kw_key or any(
        chunk in tkey for chunk in re.findall(r"\w{2,}", kw_key))


def parse_results(html: str, base_url: str, kw: str) -> list[dict]:
    """从搜索结果页里挑条目。只收同域链接：结果页上的跨域链接基本都是广告/跳转。"""
    kw_key = title_key(kw)
    host = urlparse(base_url).netloc.lower()
    out, seen = [], set()
    for href, raw in A_RE.findall(html or ""):
        text = one_line(clean_text(raw))
        if not _entry_ok(kw_key, text, href):
            continue
        link = urljoin(base_url, href.strip())
        p = urlparse(link)
        if p.netloc.lower() != host or p.scheme not in ("http", "https"):
            continue
        if link in seen:
            continue
        seen.add(link)
        out.append({"title": text[:80], "link": link, "host": p.netloc})
        if len(out) >= MAX_PER_SITE:
            break
    return out


def query_site(item: dict, kw: str) -> dict:
    """item 来自目录；有已验证模板才真的去抓，否则如实标记。"""
    deep = item.get("deep") or {}
    url = deep.get("url", "")
    row = {"id": item["id"], "name": item["name"], "category": item["category_cn"],
           "status": item["status"], "search_url": url, "kind": deep.get("kind"),
           "items": [], "count": 0, "ok": False, "error": None}
    if deep.get("kind") != "site_search":
        row["error"] = "该站搜索是 POST 表单或 JS 提交，服务端抓不到结果，只能打开首页自行搜索"
        return row
    try:
        r = requests.get(url.replace("{kw}", quote(kw)), timeout=SITE_TIMEOUT, verify=False,
                         headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9",
                                  "Referer": f"{urlparse(url).scheme}://{urlparse(url).netloc}/"})
        if r.status_code != 200:
            row["error"] = f"HTTP {r.status_code}"
            return row
        rows = parse_results(r.text, r.url, kw)
        row["items"] = rows
        row["count"] = len(rows)
        row["ok"] = bool(rows)
        if not rows:
            row["error"] = "页面已取到，但没解析出结果条目（可能是 JS 渲染或结构变了）"
    except requests.exceptions.Timeout:
        row["error"] = "超时"
    except Exception as exc:  # noqa: BLE001 - 单站失败不影响其它站
        row["error"] = f"{type(exc).__name__}"
    return row


def site_rows(kw: str = "") -> list[dict]:
    """这个标签页覆盖的站点清单：只读目录与已验证模板，**一个请求都不发**。

    没有关键词时页面不该空着让人"先搜索"，也不该顺手去并发抓 20 个站；这里给的就是
    "这一页会用到哪些站、各自能不能在本站直接搜出结果"。`can_query` 的判据和
    `query_site()` 完全一致（只有目录里有已验证的 GET 搜索模板才算），所以清单和
    真搜起来的行为不会两张皮。
    """
    items = [it for it in catalog_mod.catalog().get("items", [])
             if it["category_cn"] in SOURCE_CATS]
    items.sort(key=lambda x: (-x["recommended"], x["category_cn"], x["name"]))
    rows = []
    for it in items:
        deep = catalog_mod.link_for(it, kw)
        can = deep.get("kind") == "site_search"
        # 没关键词时摊出来的是模板本身（留着 {kw}），不是"把空串填进去"的那种地址：
        # `https://x/s/` 看着像个能开的页面，其实是个搜了空词的废链接
        shown = ((deep.get("url") or "") if kw
                 else (catalog_mod._entry_template(it) or ""))
        rows.append({"id": it["id"], "name": it["name"], "category": it["category_cn"],
                     "status": it["status"], "recommended": it["recommended"],
                     "home": it.get("url") or "", "kind": deep.get("kind"),
                     "search_url": shown, "can_query": can})
    return rows


def search(kw: str, budget: float = BUDGET) -> dict:
    items = [it for it in catalog_mod.catalog().get("items", [])
             if it["category_cn"] in SOURCE_CATS]
    # 推荐指数高的先出
    items.sort(key=lambda x: (-x["recommended"], x["category_cn"], x["name"]))
    for it in items:
        it["deep"] = catalog_mod.link_for(it, kw)

    rows, done = [], set()
    with cf.ThreadPoolExecutor(max_workers=min(8, len(items) or 1)) as ex:
        futs = {ex.submit(query_site, it, kw): it["id"] for it in items}
        try:
            for f in cf.as_completed(futs, timeout=budget):
                done.add(futs[f])
                rows.append(f.result())
        except cf.TimeoutError:
            for f, ident in futs.items():
                if ident in done:
                    continue
                it = next(x for x in items if x["id"] == ident)
                rows.append({"id": ident, "name": it["name"],
                             "category": it["category_cn"], "status": it["status"],
                             "search_url": (it["deep"] or {}).get("url", ""),
                             "kind": (it["deep"] or {}).get("kind"), "items": [],
                             "count": 0, "ok": False, "error": f"超过 {budget:.0f}s 未响应"})
    order = {it["id"]: n for n, it in enumerate(items)}
    rows.sort(key=lambda r: order.get(r["id"], 99))
    return {"keyword": kw, "sites": rows,
            "with_results": sum(1 for r in rows if r["ok"]),
            "total_sites": len(rows),
            "entries": sum(r["count"] for r in rows)}
