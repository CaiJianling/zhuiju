# -*- coding: utf-8 -*-
"""实测候选采集接口：能否用剧名返回 JSON 结果。"""
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urljoin, urlparse

import requests

requests.packages.urllib3.disable_warnings()

HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "http://localhost/",
}

cands = json.load(open(".probe/candidates.json", encoding="utf-8"))
KW = "庆余年"


def build_urls(api):
    """生成几种常见调用形式。"""
    base = api.split("?")[0]
    out = []
    if urlparse(base).path.endswith("/"):
        out.append(base + "?ac=list&wd=" + quote(KW))
    out.append(base.rstrip("/") + "/?ac=list&wd=" + quote(KW))
    if "provide/vod" in base and not base.rstrip("/").endswith(".php"):
        out.append(base.rstrip("/") + "/at/0.json?ac=list&wd=" + quote(KW))
    seen, res = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            res.append(u)
    return res


def probe(c):
    for url in build_urls(c["api"]):
        try:
            r = requests.get(url, headers=HDRS, timeout=12, verify=False)
        except Exception as e:
            continue
        ct = (r.headers.get("Content-Type") or "").lower()
        body = r.text.strip()
        if not body:
            continue
        data = None
        if "json" in ct or body[:1] in "{[":
            try:
                data = r.json()
            except Exception:
                data = None
        if isinstance(data, dict):
            lst = data.get("list") or []
            if lst and isinstance(lst[0], dict) and "vod_name" in lst[0]:
                names = [x.get("vod_name", "").strip() for x in lst[:3]]
                return {
                    "ok": True, "url": url, "source": c["source"], "site": c["name"],
                    "api": c["api"], "total": data.get("total"), "count": len(lst),
                    "names": names,
                    "keys": sorted(lst[0].keys())[:14],
                }
        return {"ok": False, "url": url, "source": c["source"], "site": c["name"],
                "api": c["api"], "reason": f"status={r.status_code} ct={ct[:20]} head={body[:80]!r}"}
    return {"ok": False, "source": c["source"], "site": c["name"], "api": c["api"],
            "reason": "all urls failed (network/blocked)"}


with ThreadPoolExecutor(max_workers=8) as ex:
    results = list(ex.map(probe, cands))

ok = [r for r in results if r["ok"]]
bad = [r for r in results if not r["ok"]]

with open(".probe/api_test.txt", "w", encoding="utf-8") as f:
    f.write(f"=== WORKING ({len(ok)}) ===\n")
    for r in ok:
        f.write(f"{r['source']} | {r['site']}\n  api={r['api']}\n  total={r['total']} got={r['count']}\n"
                f"  names={r['names']}\n  keys={r['keys']}\n\n")
    f.write(f"=== FAILED ({len(bad)}) ===\n")
    for r in bad:
        f.write(f"{r['source']} | {r['site']} | {r['api']}\n  {r.get('reason','')}\n\n")
print(f"ok={len(ok)} failed={len(bad)}")
