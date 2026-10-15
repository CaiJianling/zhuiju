# -*- coding: utf-8 -*-
"""扩充检索源：从全部 TVBox 配置（含中文域名 IDN 转换）里抽采集接口并逐个实测。

之前 饭太硬 / 肥猫 / 摸鱼儿 / 王二小 这几个配置报 UnicodeEncodeError 并不是站点挂了，
而是 requests 对中文域名没做 punycode 转换，这里补上后能多拿到两个大配置。

产出 .probe/more_sources.json：[{name, api, host, ok, count, titles, error}]
"""
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse, urlunparse

import requests

requests.packages.urllib3.disable_warnings()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zhuiju.sources import load_sources  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HDRS = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
JAR_HINT = re.compile(r"csp_|\.jar|drpy|/js/", re.I)
KWS = ["庆余年", "流浪地球"]

CONFIGS = [
    "http://www.饭太硬.net/tv", "http://肥猫.net/", "https://raw.liucn.cc/box/m.json",
    "https://szyyds.cn/tv/x.json", "http://摸鱼儿.cc", "http://new.王二小放牛娃.top",
    "http://xhztv.top/4k.json", "http://xhztv.top/xhz", "http://rihou.cc:88/demo.php",
    "http://itv666.cc/aowu/config.webp", "https://6800.kstore.vip/fish.json",
    "http://xhztv.top/dc", "http://xmbjm.fh4u.org/dc.txt", "http://ztha.top/TVBox/GYCK.json",
    "https://fangggg.com/tv/", "https://leemeier.com/tv.txt", "https://bfqp.dnspod.cn/prod_yjh.js",
]

# 不只匹配 .json/.txt：饭太硬这类页面的配置地址后缀五花八门，先广抓再逐个试解析
LINK_RE = re.compile(r"""["'(]?((?:https?:)?//[^"'()<>\s,;]+)""", re.I)


def idn(url: str) -> str:
    """中文域名转 punycode，否则 requests 直接抛 UnicodeEncodeError。"""
    p = urlparse(url)
    try:
        host = p.netloc.encode("idna").decode("ascii")
    except Exception:  # noqa: BLE001
        host = p.netloc
    return urlunparse((p.scheme, host, p.path, p.params, p.query, p.fragment))


def get(url, depth=0):
    for cand in (idn(url), idn(url).replace("http://", "https://")):
        try:
            r = requests.get(cand, headers=HDRS, timeout=7, verify=False)
            if r.ok and r.text.strip():
                return r.text
        except Exception:  # noqa: BLE001
            continue
    return None


def parse_json(text):
    if not text:
        return None
    for cand in (text.strip(), "\n".join(ln for ln in text.splitlines()
                                          if not ln.strip().startswith("//"))):
        try:
            return json.loads(cand)
        except Exception:  # noqa: BLE001
            continue
    return None


def harvest(obj, acc, seen_hosts, depth=0):
    if not isinstance(obj, dict) or depth > 3:
        return
    for s in obj.get("sites", []) or []:
        api = s.get("api", "") if isinstance(s, dict) else ""
        if not isinstance(api, str) or not api.lower().startswith("http"):
            continue
        if JAR_HINT.search(api):
            continue
        host = urlparse(idn(api)).netloc.lower()
        if not host or host in seen_hosts:
            continue
        seen_hosts.add(host)
        acc.append({"name": (s.get("name") or "").strip()[:30], "api": idn(api),
                   "host": host})
    for u in obj.get("urls", []) or []:      # 多仓：再下探一层
        url = u.get("url", "") if isinstance(u, dict) else ""
        if url.lower().startswith("http") and not url.endswith((".jar", ".png", ".webp")):
            sub = parse_json(get(url))
            if sub:
                harvest(sub, acc, seen_hosts, depth + 1)


def expand_html_configs(text):
    """配置页是 HTML 时（如 饭太硬 /tv），从页面里找下层 json/txt 配置地址。"""
    out, seen = [], set()
    # 只排掉静态资源；GitHub raw 是 TVBox 子配置的常见存放处，不能排
    skip = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".css",
            ".woff", ".woff2", ".mp4", ".apk", ".jar")
    for m in LINK_RE.findall(text or ""):
        u = m if m.lower().startswith("http") else ("https:" + m if m.startswith("//") else None)
        if not u:
            continue
        low = u.lower()
        if any(low.endswith(x) or x in low for x in skip):
            continue
        if low.endswith((".js", ".png", ".ico", ".css")):
            continue
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:20]


def test_api(cand):
    api = cand["api"].split("?")[0]
    scheme = urlparse(cand["api"]).scheme or "https"
    hdrs = {**HDRS, "Referer": f"{scheme}://{cand['host']}/"}
    got = []
    for kw in KWS:
        try:
            r = requests.get(api, params={"ac": "list", "wd": kw, "limit": 8},
                             headers=hdrs, timeout=7, verify=False)
            body = (r.text or "").strip()
            if r.status_code != 200 or body[:1] not in "{[":
                return {**cand, "ok": False, "count": 0, "titles": [],
                        "error": f"HTTP{r.status_code} 非JSON"}
            d = r.json()
            if isinstance(d, dict) and isinstance(d.get("data"), dict):
                d = d["data"]
            lst = (d or {}).get("list") or []
            names = [re.sub(r"<[^>]+>", "", str(x.get("vod_name", ""))).strip()
                     for x in lst if isinstance(x, dict) and x.get("vod_name")]
            if not names:
                return {**cand, "ok": False, "count": 0, "titles": [],
                        "error": "无 vod_name 字段"}
            got.append((kw, names[:2]))
        except Exception as exc:  # noqa: BLE001
            return {**cand, "ok": False, "count": 0, "titles": [],
                    "error": type(exc).__name__}
    return {**cand, "ok": True, "count": sum(len(n) for _, n in got),
            "titles": [n for _, ns in got for n in ns], "error": None}


def main():
    base = Path(__file__).resolve().parent.parent
    (base / ".probe").mkdir(exist_ok=True)
    existing = {urlparse(s.api).netloc.lower() for s in load_sources()}

    acc, seen_hosts = [], set(existing)
    logs = []
    lock = threading.Lock()

    def do_config(url):
        text = get(url)
        if not text:
            return f"[拉取失败] {url}", []
        obj = parse_json(text)
        if obj:
            return f"[JSON] {url} 配置体 {len(text)}B", [obj]
        objs = []
        for s in expand_html_configs(text)[:8]:
            sub = parse_json(get(s))
            if sub:
                objs.append(sub)
        return f"[HTML] {url} 下探得到 {len(objs)}/8 个子配置", objs

    with ThreadPoolExecutor(max_workers=6) as ex:
        for label, objs in ex.map(do_config, CONFIGS):
            logs.append(label)
            print(label, flush=True)
            for o in objs:
                with lock:
                    harvest(o, acc, seen_hosts)
    print(f"抽取到候选接口 {len(acc)} 个", flush=True)

    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(test_api, c) for c in acc]
        results = [f.result() for f in as_completed(futs)]
    results.sort(key=lambda r: (not r["ok"], r["host"]))

    (base / ".probe" / "more_sources.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    (base / ".probe" / "more_log.txt").write_text("\n".join(logs), encoding="utf-8")
    ok = [r for r in results if r["ok"]]
    print(f"候选 {len(acc)} 个，实测可用 {len(ok)} 个（当前已用 {len(existing)} 个 host）")
    for r in ok:
        print(f"  + {r['host']:<28} {r['name'][:16]:<18} {r['titles'][:2]}")


if __name__ == "__main__":
    main()
