# -*- coding: utf-8 -*-
"""浏览器识别与来源页判定：只用标准库，不引第三方 UA 库。

两件事都必须先承认它的边界，否则统计出来的是假精确：

User-Agent
  完全由客户端自己写，想填什么填什么，所以它是"指示"不是"身份"。
  这里只取有把握的部分：主流浏览器内核标记 + 常见国产壳浏览器 + 爬虫/脚本客户端。
  认不出来就老实写"未知"，不猜。顺序很关键：Edge/Opera/微信/QQ 的 UA 里都同时带
  "Chrome/xxx"和"Safari/xxx"，先判 Chrome 就会把它们全认成 Chrome。

Referer（来源页）
  由浏览器按 Referrer-Policy 决定给多少，默认策略是 strict-origin-when-cross-origin：
    - 站内跳转（同源）  -> 给**完整 URL**，所以"上一页具体是哪一页"是能看到的
    - 跨站跳转          -> 只给 origin（协议+域名），路径被浏览器抹掉，拿不到也别编
    - https -> http     -> 干脆不发这个头
    - 直接输地址 / 书签 / 新标签页打开 -> 不发
  所以"直接访问"这一类里混着好几种情况，文案上分开不了就不硬分。
  这个头同样可伪造。
"""
from __future__ import annotations

import re
import urllib.parse

MAX_UA = 200
MAX_REF = 200

# 常见爬虫与脚本客户端：把它们和真人分开，否则"查询次数"会被搜索引擎抓取灌满
BOTS = (
    "googlebot", "bingbot", "yahoo", "yandexbot", "baiduspider", "sogou", "360spider",
    "bytespider", "petalbot", "applebot", "duckduckbot", "facebookexternalhit",
    "twitterbot", "weibo", "slackbot", "telegrambot", "whatsapp", "curl", "wget",
    "httpie", "python-requests", "python-urllib", "python-httpx", "httpx",
    "go-http-client", "java/",
    "okhttp", "axios", "node-fetch", "headlesschrome", "phantomjs", "postman",
    "insomnia", "lighthouse", "feedfetcher", "rss", "scrapy", "libwww",
    # Flask/Werkzeug 的 test_client 自带的 UA：离线工具一跑就往真实库里写一行
    # （实测 check_autoupdate 每跑一次留一条 Werkzeug/3.1.9），它当然不是浏览器
    "werkzeug",
)

# (匹配, 显示名)：按顺序命中，越靠前越特殊
BROWSERS = (
    (re.compile(r"MicroMessenger/([\d.]+)"), "微信", True),
    (re.compile(r"WeChat/([\d.]+)"), "微信", True),
    (re.compile(r"QQBrowser/([\d.]+)"), "QQ浏览器", True),
    (re.compile(r"MQQBrowser/([\d.]+)"), "QQ浏览器", True),
    (re.compile(r"Quark/([\d.]+)"), "夸克", True),
    (re.compile(r"UCBrowser/([\d.]+)"), "UC浏览器", True),
    (re.compile(r"baidubrowser/([\d.]+)"), "百度浏览器", True),
    (re.compile(r"(?:360SE|Qihoo 360)"), "360浏览器", False),
    (re.compile(r"MetaSr(?:/([\d.]+))?"), "搜狗浏览器", False),
    (re.compile(r"SamsungBrowser/([\d.]+)"), "三星浏览器", True),
    (re.compile(r"(?:Edg|EdgA|EdgIOS|Edge)/([\d.]+)"), "Edge", True),
    (re.compile(r"OPR(?:\/|/)([\d.]+)|Opera/([\d.]+)"), "Opera", True),
    (re.compile(r"Vivaldi/([\d.]+)"), "Vivaldi", True),
    (re.compile(r"Electron/([\d.]+)"), "Electron", True),
    (re.compile(r"Trident/.*?rv:([\d.]+)"), "IE", True),
    (re.compile(r"MSIE ([\d.]+)"), "IE", True),
    (re.compile(r"Firefox/([\d.]+)"), "Firefox", True),
    (re.compile(r"FxiOS/([\d.]+)"), "Firefox iOS", True),
    (re.compile(r"CriOS/([\d.]+)"), "Chrome iOS", True),
    (re.compile(r"Chrome(?:OS)?/([\d.]+)"), "Chrome", True),
    # Safari 必须放最后：上面那些 UA 里几乎都带 "Safari/604.1" 这个兼容标记
    (re.compile(r"Version/([\d.]+).*Safari"), "Safari", True),
    (re.compile(r"Safari/([\d.]+)"), "Safari", True),
)

# 系统同理：iPhone 的 UA 里也有 "like Mac OS X"，所以 iOS 要判在 macOS 之前
OS_RULES = (
    (re.compile(r"Windows NT (?:10\.0|11\.0)"), "Windows 10/11"),
    (re.compile(r"Windows NT 6\.3"), "Windows 8.1"),
    (re.compile(r"Windows NT 6\.2"), "Windows 8"),
    (re.compile(r"Windows NT 6\.1"), "Windows 7"),
    (re.compile(r"Windows NT (?:5\.1|5\.2)"), "Windows XP"),
    (re.compile(r"Windows"), "Windows"),
    (re.compile(r"(?:iPhone|iPad|iPod)(?:.*?CPU)? OS ([\d_]+) like Mac OS X"), None),   # 特殊处理
    (re.compile(r"Android ([\d.]+)"), None),                                            # 特殊处理
    (re.compile(r"(?:Macintosh|Mac OS X|MacPi|MacWk)"), "macOS"),
    (re.compile(r"CrOS"), "ChromeOS"),
    (re.compile(r"(?:Linux|X11)"), "Linux"),
    (re.compile(r"Ubuntu"), "Ubuntu"),
)

MOBILE = re.compile(r"Mobile|Android|iPhone|iPod|Windows Phone|IEMobile")
TABLET = re.compile(r"iPad|Android(?!.*Mobile)|Tablet|PlayBook")

# 搜索引擎的关键词参数名，各家不一样
SEARCH_ENGINES = {
    "google.com": "q", "google.com.hk": "q", "www.google.com": "q",
    "bing.com": "q", "www.bing.com": "q",
    "baidu.com": "wd", "www.baidu.com": "wd",
    "sogou.com": "query", "www.sogou.com": "query",
    "so.com": "q", "www.so.com": "q",
    "sm.cn": "q", "quark.sm.cn": "q",
    "duckduckgo.com": "q",
    "yandex.com": "text", "yandex.ru": "text",
    "search.yahoo.com": "p",
}
ENGINE_CN = {"google.com": "Google", "bing.com": "必应", "baidu.com": "百度",
             "sogou.com": "搜狗", "so.com": "360", "sm.cn": "神马",
             "duckduckgo.com": "DuckDuckGo", "yandex.com": "Yandex",
             "yandex.ru": "Yandex", "search.yahoo.com": "Yahoo"}


def _short(v: str) -> str:
    """版本号留主.次两位就够，124.0.6367.201 这种全长串在表格里太占位。"""
    parts = [p for p in (v or "").split(".") if p.isdigit()]
    return ".".join(parts[:2]) if parts else (v or "")[:10]


def parse_ua(ua: str | None) -> dict:
    """UA -> {browser, os, device, bot, label}。认不出的一律留空/未知。"""
    raw = (ua or "").strip()[:MAX_UA]
    out = {"browser": "", "os": "", "device": "", "bot": False, "label": "未知",
           "ua": raw}
    if not raw:
        return out
    low = raw.lower()
    for b in BOTS:
        if b in low:
            name = {"python-requests": "requests 脚本", "python-urllib": "urllib 脚本",
                    "python-httpx": "httpx 脚本", "werkzeug": "Werkzeug 测试客户端",
                    "curl": "curl", "wget": "wget", "headlesschrome": "无头浏览器",
                    "googlebot": "Google 爬虫", "bingbot": "必应爬虫",
                    "baiduspider": "百度爬虫", "sogou": "搜狗爬虫",
                    "bytespider": "头条爬虫", "applebot": "Apple 爬虫"}.get(
                        b, b.strip("/") + " 脚本/爬虫")
            out.update(bot=True, device="程序", browser=name, label=name + "（非真人）")
            return out

    browser, ver = "", ""
    for rx, name, has_ver in BROWSERS:
        m = rx.search(raw)
        if m:
            browser = name
            if has_ver and m.groups():
                ver = _short(next((g for g in m.groups() if g), ""))
            break
    if browser:
        out["browser"] = f"{browser} {ver}".strip()

    # iOS / Android 的版本藏在和 Mac/Windows 相同的字样里，单独拆出来
    m = re.search(r"(?:iPhone|iPad|iPod).*?OS ([\d_]+) like Mac OS X", raw)
    if m:
        plat = "iPadOS" if "iPad" in raw else "iOS"
        out["os"] = f"{plat} {m.group(1).replace('_', '.')}"
    else:
        m = re.search(r"Android ([\d.]+)", raw)
        if m:
            out["os"] = f"Android {_short(m.group(1))}"
        else:
            for rx, name in OS_RULES:
                if rx.search(raw):
                    if name:
                        out["os"] = name
                    break
    if not out["os"] and "Mac" in raw:
        out["os"] = "macOS"

    # iPad 的 UA 里也带 "Mobile/15E148"（苹果为了兼容老站点留的历史标记），
    # 所以不能靠有没有 Mobile 来分区手机和平板，iPad 要先单独认
    if "iPad" in raw:
        out["device"] = "平板"
    elif TABLET.search(raw) and "Mobile" not in raw:
        out["device"] = "平板"
    elif MOBILE.search(raw):
        out["device"] = "手机"
    elif re.search(r"Windows|Macintosh|X11|Linux", raw):
        out["device"] = "桌面"
    else:
        out["device"] = "未知"

    out["label"] = " · ".join(x for x in (out["browser"] or "未知浏览器",
                                        out["os"], out["device"]) if x)
    return out


def _host_root(host: str) -> str:
    """取注册域的最后两段，好把 www.google.com 归到 google.com 上。"""
    h = (host or "").lower().split(":")[0]
    parts = [p for p in h.split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else h


def parse_ref(referrer: str | None, own_hosts=()) -> dict:
    """Referer -> {kind, label, origin, path, q}。

    kind: direct=没有来源头 / site=站内上一页 / search=搜索引擎 / out=其它站点
    """
    raw = (referrer or "").strip()[:MAX_REF]
    out = {"ref": raw, "kind": "direct", "label": "直接访问 / 无来源",
           "origin": "", "path": "", "q": ""}
    if raw in ("", "-", "undefined", "null") or raw.lower() == "no-referrer":
        return out
    try:
        p = urllib.parse.urlsplit(raw)
    except ValueError:
        return out
    if not p.netloc:
        # 不是个像样的 URL（伪造或残缺）：原样留着但不参与分类，免得污染聚合
        out.update(kind="other", label="无法解析的来源")
        return out
    origin = f"{p.scheme}://{p.netloc}" if p.scheme else p.netloc
    host = p.netloc.lower()
    own = {h.lower() for h in own_hosts if h}
    own_roots = {_host_root(h) for h in own}
    # 端口也要能对上：本机跑的时候 host:5000 和 host 是同一个站
    is_own = host in own or _host_root(host) in own_roots or \
        (_host_root(host.split(":")[0]) in own_roots)
    if is_own:
        # 同源跳转浏览器会给完整路径，所以这里能看到"上一页是哪一页"
        path = ("/" + p.path.lstrip("/")) if p.path else "/"
        # 站内路径是 /s/%E5%BA%86%E4%BD%99%E5%B9%B4 这种转义形态，人读不出来，
        # 而"上一页是哪部剧"恰恰是这一列最有用的信息，label 里还原成中文
        try:
            nice = urllib.parse.unquote(path, errors="replace")
        except Exception:  # noqa: BLE001
            nice = path
        out.update(kind="site", origin=origin, path=path,
                   label="站内首页" if path == "/" else f"站内 {nice}")
        return out
    root = _host_root(host.split(":")[0])
    qkey = SEARCH_ENGINES.get(root) or SEARCH_ENGINES.get(host)
    if qkey:
        q = (urllib.parse.parse_qs(p.query).get(qkey) or [""])[0][:40]
        name = ENGINE_CN.get(root, root)
        out.update(kind="search", origin=origin, q=q,
                   label=f"{name} 搜索「{q}」进来" if q else f"{name} 搜索结果页")
        return out
    # 跨站：策略只放行 origin，路径本来就看不到，标清楚别让人以为是"整个上一页"
    out.update(kind="out", origin=origin,
               label=f"{p.scheme or 'http'}://{host}" if host else "外部站点")
    return out
