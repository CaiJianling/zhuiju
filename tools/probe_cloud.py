# -*- coding: utf-8 -*-
"""探测目录里 4 家网盘站：有没有能拿到结构化结果的搜索端点。

判据不看"页面里出现关键词"（首页也常有热门剧名），而是看结果区里
是否出现指向单条资源的链接 / 卡片。
"""
import json
import re
from urllib.parse import quote, urlparse

import requests

requests.packages.urllib3.disable_warnings()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
KW = "庆余年"

SITES = {
    "PanSou": "https://pansou.de",
    "夸克搜": "https://kkso.net",
    "追剧吧": "https://www.zhuiju.us",
    "谷哥搜": "https://gugeso.com",
}

GET_TPL = ["/?s={kw}", "/?q={kw}", "/search/{kw}", "/search?q={kw}",
           "/?m=vod-search&wd={kw}", "/api/search?q={kw}", "/api/search/{kw}",
           "/?keyword={kw}", "/so/{kw}.html", "/index.php/search/{kw}.html"]
POST_AS = ["q", "s", "keyword", "wd", "searchword", "query"]

TITLE_RE = re.compile(r"(庆余年[^<>'\"]{0,30})")
CARD_RE = re.compile(r"<a[^>]{20,400}?>(?:(?!</a>)[\s\S]){0,300}庆余年(?:(?!</a>)[\s\S]){0,200}</a>", re.I)


def probe(name, root):
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA, "Referer": root + "/",
                         "Accept-Language": "zh-CN,zh;q=0.9"})
    tried = []
    # 先拿首页，顺带找 JS 里的 API 线索
    try:
        home = sess.get(root + "/", timeout=12, verify=False).text
    except Exception as e:
        return {"name": name, "root": root, "ok": False, "why": f"首页不可达 {type(e).__name__}",
                "tried": []}
    api_hints = sorted(set(re.findall(r"""["'`](/api/[A-Za-z0-9_/\-.{}]+)["'`]""", home)))[:8]

    def check(label, text, url):
        hits = CARD_RE.findall(text or "")
        titles = TITLE_RE.findall(text or "")
        good = len(hits) >= 2 or len(set(titles)) >= 3
        tried.append({"way": label, "url": url[:90], "bytes": len(text or ""),
                      "cards": len(hits), "titles": len(set(titles))})
        return good, list(dict.fromkeys(t[:40] for t in titles))[:5], hits[:2]

    for tpl in GET_TPL:
        u = root + tpl.replace("{kw}", quote(KW))
        try:
            r = sess.get(u, timeout=12, verify=False)
        except Exception:
            continue
        if r.status_code == 200:
            ok, titles, _ = check("GET " + tpl, r.text, r.url)
            if ok:
                return {"name": name, "root": root, "ok": True, "way": "GET",
                        "template": tpl, "titles": titles, "api_hints": api_hints,
                        "tried": tried}
    for field in POST_AS:
        try:
            r = sess.post(root + "/", data={field: KW}, timeout=12, verify=False,
                          allow_redirects=True)
        except Exception:
            continue
        if r.status_code == 200 and KW in (r.url + (r.text or "")):
            ok, titles, _ = check("POST / " + field, r.text, r.url)
            if ok:
                return {"name": name, "root": root, "ok": True, "way": "POST",
                        "field": field, "url": r.url, "titles": titles,
                        "api_hints": api_hints, "tried": tried}
    for path in api_hints:
        u = root + path
        for meth in ("get", "post"):
            try:
                r = (sess.get(u, timeout=10, verify=False) if meth == "get"
                     else sess.post(u, json={"q": KW}, timeout=10, verify=False))
            except Exception:
                continue
            body = (r.text or "")
            if r.status_code == 200 and body[:1] in "{[" and KW in body:
                tried.append({"way": f"{meth.upper()} {path}", "url": r.url[:90],
                              "bytes": len(body), "json": True})
                return {"name": name, "root": root, "ok": True, "way": meth.upper(),
                        "api": path, "sample": body[:300], "tried": tried}
    return {"name": name, "root": root, "ok": False, "why": "GET/POST/API 端点均未出结果",
            "api_hints": api_hints, "tried": tried}


out = [probe(n, r) for n, r in SITES.items()]
open(".probe/cloud_probe.json", "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=2))
for o in out:
    print(("OK   " if o["ok"] else "--   ") + o["name"],
          o.get("way", ""), o.get("template") or o.get("api") or o.get("why"),
          "| titles:", (o.get("titles") or o.get("sample", ""))and str(o.get("titles", o.get("sample",""))[:80]))
