# -*- coding: utf-8 -*-
"""探测各站点的搜索 URL 模板，并用真实关键词验证返回页是否含该关键词。"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urljoin, urlparse

import requests

requests.packages.urllib3.disable_warnings()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HDRS = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
KW = "庆余年"
SENT = "\u0001KW\u0001"

FORM_RE = re.compile(r"<form[^>]*action=[\"']([^\"']+)[\"'][^>]*>(.*?)</form>",
                     re.I | re.S)
NAME_RE = re.compile(r"<input[^>]*name=[\"']([^\"']+)[\"']", re.I)
PATH_RE = re.compile(r"""["'](/[A-Za-z0-9_\-./]*(?:search|so|vodsearch|qs)[A-Za-z0-9_\-./]*)["']""", re.I)

# 常见 maccms 搜索路径模板（按命中率排序，逐个验证）
COMMON_TPL = [
    "/index.php/vod/search/wd/{kw}.html",
    "/index.php/vod/search.html?wd={kw}",
    "/vodsearch/{kw}----------1---",
    "/vodsearch/-------------.html?wd={kw}",
    "/search/{kw}.html",
    "/search.html?wd={kw}",
    "/search?wd={kw}",
    "/search/{kw}",
    "/?m=vod-search-wd-{kw}",
    "/modules/article/search.php?searchword={kw}",
    "/?s={kw}",
    "/?q={kw}",
    "/so/{kw}.html",
]


def root_of(url):
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def candidates(root, html):
    out = []
    for action, inner in FORM_RE.findall(html or "")[:6]:
        names = NAME_RE.findall(inner)
        key = next((n for n in names if n.lower() in
                    ("wd", "q", "keyword", "searchword", "kw", "s", "search", "query")), None)
        if not key:
            continue
        if "{kw}" in action:
            out.append(urljoin(root, action))
        elif "?" in action:
            out.append(urljoin(root, action) + f"&{key}=" + SENT)
        else:
            out.append(urljoin(root, action) + f"?{key}=" + SENT)
    for path in list(dict.fromkeys(PATH_RE.findall(html or "")))[:6]:
        low = path.lower()
        if low.endswith(".html") or low.endswith(".php") or "/search" in low:
            sep = "&" if "?" in path else "?"
            out.append(root + path + sep + "wd=" + SENT)
    out.extend(root + t for t in COMMON_TPL)
    seen, res = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            res.append(u)
    return res[:20]


def looks_good(r, kw):
    if r.status_code not in (200, 301, 302):
        return False
    body = r.text or ""
    if len(body) < 800:
        return False
    if kw in body:
        return True
    # 结果页可能因编码问题匹配不到，用"有结果条数"作弱信号
    return bool(re.search(r"(共找到|搜索结果|共页|vodlist|listpage|myui-vodlist|search-item)", body, re.I))


def probe(item):
    name, url = item
    root = root_of(url)
    html = ""
    try:
        rr = requests.get(root, headers=HDRS, timeout=12, verify=False)
        if rr.ok:
            html = rr.text
    except Exception:
        pass
    for tpl in candidates(root, html):
        test = tpl.replace(SENT, quote(KW))
        try:
            r = requests.get(test, headers=HDRS, timeout=12, verify=False,
                             allow_redirects=True)
        except Exception:
            continue
        if looks_good(r, KW):
            tmpl = r.url.replace(quote(KW), "{kw}").replace(KW, "{kw}")
            return {"name": name, "site": url, "ok": True, "template": tmpl,
                    "status": r.status_code, "bytes": len(r.text),
                    "form_derived": SENT in tpl or "wd=" not in tpl}
    return {"name": name, "site": url, "ok": False, "template": None}


API_HOSTS = [
    ("虎牙采集", "https://www.huyaapi.com/"),
    ("火狐资源", "https://hhzyapi.com/"),
    ("百度资源", "https://api.apibdzy.com/"),
    ("红牛资源", "https://www.hongniuzy2.com/"),
    ("极速资源", "https://jszyapi.com/"),
    ("光速资源", "https://api.guangsuapi.com/"),
    ("备番资源", "https://bfzyapi.com/"),
    ("淘片资源", "https://taopianapi.com/"),
]
CLOUD = [("PanSou", "https://pansou.de"), ("夸克搜", "https://kkso.net"),
         ("追剧吧", "https://www.zhuiju.us/"), ("谷哥搜", "https://gugeso.com/")]
MAGNET = [("BD影视聚合", "https://www.juhebd.com/"), ("爱努努", "https://video.ainunu.com/"),
          ("BD电影首发", "https://www.bdflixs.com/"), ("美剧粉", "https://www.mjf2020.com"),
          ("磁力熊", "https://www.cilixiong.org"), ("磁力狗", "https://ciligou.net"),
          ("磁力帝", "https://www.cld123.com"), ("BT影视", "https://www.btbtla.com"),
          ("电影港网", "https://www.dyg22.com"), ("BT世界网", "https://www.btsj6.com"),
          ("高清MP4", "https://www.mp4ba.vip"), ("高清族", "https://hdzu.org"),
          ("SeedHub", "https://sidhub.cc/"), ("ACG.RIP", "https://acg.rip/")]
ONLINE = [("创享影视", "https://ys.cxkjg.cn/"), ("洛雪TV", "https://tv.lxyy.club/"),
          ("西瓜影视", "https://www.kanmovie.com/"), ("剧OK", "https://juok3.top/"),
          ("剧踪影院", "https://www.juzong01.me/"), ("简云影视", "https://jianyunys.com/"),
          ("片库", "https://4k01.pianku.online/"), ("66大片网", "https://www.77dpw.vip/"),
          ("追影", "https://zhuiying3.cc/"), ("开心影院", "https://www.kxyy1.cc/"),
          ("豆花电影网", "https://dhvideo.cc/"), ("饭搭子影视", "https://fdzys.com"),
          ("SA视频", "https://www.lsjys11.com/"), ("APP影院", "https://www.appmovie.art"),
          ("Auete影视", "https://www.aeete.com"), ("电影人生", "https://dyrs.tv"),
          ("PPnix", "https://www.ppnix.com/cn/"), ("独播库", "https://www.dbku.tv"),
          ("搜TV啦", "https://www.sotvla.cc/"), ("爱盼", "https://www.aipan.me/"),
          ("布布追剧", "https://bubuzhuiju.com"), ("宅男影视", "https://zndy.top/")]

groups = {"api_host": API_HOSTS, "cloud": CLOUD, "magnet": MAGNET, "online": ONLINE}
allitems = [(g, n, u) for g, lst in groups.items() for n, u in lst]

with ThreadPoolExecutor(max_workers=12) as ex:
    results = list(ex.map(lambda t: dict(probe((t[1], t[2])), group=t[0]), allitems))

json.dump(results, open(".probe/url_templates.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
ok = [r for r in results if r["ok"]]
print(f"total={len(results)} ok={len(ok)}")
with open(".probe/templates.txt", "w", encoding="utf-8") as f:
    for g in groups:
        f.write(f"##### {g} #####\n")
        for r in [x for x in results if x["group"] == g]:
            f.write(f"{'OK ' if r['ok'] else '-- '} {r['name']}: {r['template']}\n")
print("written")
