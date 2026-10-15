# -*- coding: utf-8 -*-
"""第二轮：带 Referer 重试失败接口 + 测试常见公开采集接口。只保留能返回片名的。"""
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlparse

import requests

requests.packages.urllib3.disable_warnings()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

KW = "庆余年"

EXTRA = [
    ("红牛采集", "https://www.hongniuzy2.com/api.php/provide/vod/"),
    ("极速资源", "https://jszyapi.com/api.php/provide/vod/"),
    ("光速采集", "https://api.guangsuapi.com/api.php/provide/vod/"),
    ("天空资源", "https://m3u8.tiankongapi.com/api.php/provide/vod/"),
    ("鱼乐采集", "https://api.ylzy1.com/api.php/provide/vod/"),
    ("悟空资源", "https://wokongzy.com/api.php/provide/vod/"),
    ("金库资源", "https://jiku.vip/api.php/provide/vod/"),
    ("CK资源", "https://www.ckzy1.com/api.php/provide/vod/"),
    ("天猫资源", "https://api.tmallw.com/api.php/provide/vod/"),
    ("索尼资源", "https://suoniapi.com/api.php/provide/vod/"),
    ("飘花资源", "https://sh观yingshi.com/api.php/provide/vod/"),
    ("猛虎资源", "https://daaozy.com/api.php/provide/vod/"),
    ("备番资源", "https://bfzyapi.com/api.php/provide/vod/"),
    ("量子资源", "https://lzizy1.com/api.php/provide/vod/"),
    ("非凡资源", "https://ffzy1.tv/api.php/provide/vod/"),
    ("四九资源", "https://49zy1.com/api.php/provide/vod/"),
    ("飞速资源", "https://www.feisuzyapi.com/api.php/provide/vod/"),
    ("奇虎资源", "https://caiji.qhzyapi.com/api.php/provide/vod/"),
    ("可可资源", "https://kekezy1.com/api.php/provide/vod/"),
    ("小胡资源", "http://c.xiaohu.icu/api.php/provide/vod/"),
]

prev_bad = json.load(open(".probe/candidates.json", encoding="utf-8"))


def headers_for(api):
    host = urlparse(api).scheme + "://" + urlparse(api).netloc
    return {
        "User-Agent": UA,
        "Referer": host + "/",
        "Origin": host,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


def probe(item):
    name, api = item
    tried = []
    for url in (api.rstrip("/") + "/?ac=list&wd=" + quote(KW),
                api + "?ac=list&wd=" + quote(KW)):
        if url in [t[0] for t in tried]:
            continue
        tried.append((url, None))
        try:
            r = requests.get(url, headers=headers_for(api), timeout=12, verify=False)
        except Exception as e:
            tried[-1] = (url, f"ERR {type(e).__name__}")
            continue
        body = (r.text or "").strip()
        if body[:1] in "{[":
            try:
                data = r.json()
            except Exception:
                data = None
            if isinstance(data, dict):
                lst = data.get("list") or []
                if lst and isinstance(lst[0], dict) and lst[0].get("vod_name"):
                    return {"ok": True, "name": name, "api": api, "url": url,
                            "total": data.get("total"), "count": len(lst),
                            "names": [x.get("vod_name", "").strip() for x in lst[:3]]}
        tried[-1] = (url, f"status={r.status_code} head={body[:60]!r}")
    return {"ok": False, "name": name, "api": api,
            "reason": " | ".join(t[1] or "" for t in tried)}


items = [(c["name"], c["api"]) for c in prev_bad] + EXTRA
with ThreadPoolExecutor(max_workers=10) as ex:
    results = list(ex.map(probe, items))

ok = [r for r in results if r["ok"]]
bad = [r for r in results if not r["ok"]]
json.dump(ok, open(".probe/working_round2.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
with open(".probe/round2.txt", "w", encoding="utf-8") as f:
    f.write(f"=== WORKING ({len(ok)}) ===\n")
    for r in ok:
        f.write(f"{r['name']} | api={r['api']} | total={r['total']} got={r['count']} | {r['names']}\n")
    f.write(f"\n=== FAILED ({len(bad)}) ===\n")
    for r in bad:
        f.write(f"{r['name']} | {r['api']}\n   {r['reason']}\n")
print(f"ok={len(ok)} failed={len(bad)}")
