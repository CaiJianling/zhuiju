# -*- coding: utf-8 -*-
"""前端架构转向（Jinja + 手写 app.js + MDUI -> React 19 + HeroUI v3 + Tailwind v4）的契约测试。

    python tests/test_frontend_react.py

这里钉的是**活的表面**：
  - 服务端那一份壳 zhuiju/templates/shell.html（Flask 唯一还在渲染的前台 HTML）
  - 前台真正的源码 web/src/**（构建产物 zhuiju/static/spa/ 只判存在与非空）
后台 /admin 那一套 MDUI 页面不在本文件的射程里，见 tests/test_agent_theme.py。

规矩：压缩过的 spa/app.js 里做源码级字符串比对没有意义，所以所有「怎么写的」
都读 web/src；对 spa 只允许断「在不在、空不空」。
"""
import json
import re
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tests"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import gate_off                                          # noqa: E402
from zhuiju import admin as admin_mod                    # noqa: E402
from zhuiju import app as app_mod                        # noqa: E402
from zhuiju import hot as hot_mod                        # noqa: E402
from zhuiju import human as human_mod                    # noqa: E402
from zhuiju import seo as seo_mod                        # noqa: E402
from zhuiju import settings as settings_mod              # noqa: E402
from zhuiju import stats as stats_mod                    # noqa: E402

WEB = BASE / "web"
SRC = WEB / "src"
SHELL = (BASE / "zhuiju" / "templates" / "shell.html").read_text(encoding="utf-8")

FAILS = []


def check(name, cond, got=None):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  got={got!r}"))
    if not cond:
        FAILS.append(name)


def read(*rel):
    return (SRC.joinpath(*rel)).read_text(encoding="utf-8")


def rule(text, head):
    """取 CSS 里从 head 开始到这一块结束的那一段（到下一个空行/换行缩进回到 0 为止）。
    Tailwind 那份源文件里有大量嵌套，所以只按「这一条声明块」切，不整块扫。"""
    i = text.find(head)
    return None if i < 0 else text[i:text.index("}", i) + 1]


# 这一份数据既喂 #nojs 也喂 boot.hot / boot.snapshot：两边都从它来，判据只用它
HOT = {
    "since": "2026-04-01", "candidates": 99, "stale": False, "cached": True,
    "movie": [{"title": f"电影{i}", "kind": "movie", "year": "2026", "type": "动作片",
               "remarks": "", "pic": "", "n_sources": 3, "sources": [{"id": "a", "name": "A", "vid": "1"}],
               "url": f"/s/电影{i}"} for i in range(30)],
    "tv": [{"title": f"剧{i}", "kind": "tv", "year": "2026", "type": "国产剧",
            "remarks": "", "pic": "", "n_sources": 2, "sources": [],
            "url": f"/s/剧{i}"} for i in range(12)],
}
SNAP = {
    "keyword": "庆余年", "count": 3, "from_cache": True,
    "sources_ok": 7, "sources_total": 9,
    "items": [{"title": f"庆余年{i}", "year": "2024", "type": "国产剧", "remarks": "完结",
               "n_sources": 4 - i, "url": f"/s/庆余年{i}"} for i in range(3)],
}

TMP = Path(tempfile.mkdtemp(prefix="zhuiju_react_test_"))
admin_mod.CONFIG = TMP / "admin.json"
settings_mod.PATH = TMP / "settings.json"
stats_mod.DB = TMP / "stats.db"
stats_mod.DATA = TMP
stats_mod._ready = False
admin_mod.load()
gate_off.off(TMP / "gate")          # 默认把门禁关掉：下面按节各自开关

_real_hot, _real_snap, _real_cached = hot_mod.get, seo_mod.snapshot, seo_mod.cached_snapshot
_real_enabled = human_mod.enabled
hot_mod.get = lambda *a, **k: dict(HOT)
# snapshot 套上记录器：门禁页一次构建都不许有（构建 = 敲上游）
_builds: list = []
seo_mod.snapshot = lambda kw, force=False: (_builds.append(kw), dict(SNAP, keyword=kw, kw=kw))[1]
# 门禁页读的是 cached_snapshot（只读盘）；"庆余年"当作缓存里已有，其余词当作没有
seo_mod.cached_snapshot = lambda kw: dict(SNAP, keyword=kw, kw=kw) if kw == "庆余年" else {}
seo_mod.CACHE = TMP / "cache"

APP = app_mod.create_app()
GATE = [False]                                   # 当前这一发请求让不让门禁开着


def html_of(path, gate=False, client=None, **kw):
    """同一个 app 上发一次请求，并按 gate 决定门禁开不开。
    门禁的开关是 human_mod.enabled 这个全局，两份 test_client 共用同一个 app，
    所以必须**每次请求前**现设，不能建好客户端就以为它带着当初那个设置。"""
    GATE[0] = bool(gate)
    human_mod.enabled = lambda: bool(GATE[0])
    c = client if client is not None else APP.test_client()
    return c.get(path, **kw)


def body_of(path, gate=False, client=None, **kw):
    return html_of(path, gate, client, **kw).get_data(as_text=True)


def boot_of(html):
    """把壳里那份 <script id="boot-data"> 读回成字典。"""
    tag = '<script id="boot-data" type="application/json">'
    return json.loads(html.split(tag)[1].split("</script>")[0])


try:
    print("1) 壳的形状：一个挂载点、一份 boot、一个 bundle")
    for path, label in (("/", "首页"), ("/s/" + "庆余年", "关键词落地页")):
        r = html_of(path)
        h = r.get_data(as_text=True)
        check(f"{label}：200 且返回的是 HTML 壳", r.status_code == 200
              and h.lstrip().startswith("<!DOCTYPE html>"), r.status_code)
        check(f"{label}：有且只有一个 React 挂载点 #app", h.count('id="app"') == 1,
              h.count('id="app"'))
        check(f"{label}：有且只有一个 #boot-data", h.count('id="boot-data"') == 1,
              h.count('id="boot-data"'))
        mods = re.findall(r'<script type="module" src="([^"]+)"', h)
        check(f"{label}：只有一个 module script，指向 spa/app.js",
              len(mods) == 1 and mods[0].startswith("/static/spa/app.js"), mods)
        css = re.findall(r'<link rel="stylesheet" href="([^"]+)"', h)
        check(f"{label}：样式也只引 spa/app.css 这一份",
              len(css) == 1 and css[0].startswith("/static/spa/app.css"), css)
        # (c) 「slider.js 必须在 app.js 之前加载」这条旧不变量的等价形态：
        # 前台只有一个 bundle，两份脚本谁先谁后这个问题在新架构里不存在了
        check(f"{label}：壳里不再引第二份手写脚本（旧的两条 bundle 先后问题已不存在）",
              not re.search(r'<script src="/static/(?!spa/)', h)
              and "slider.js" not in h and "vendor/mdui" not in h,
              re.findall(r"<script[^>]*src=[^>]*>", h))
        check(f"{label}：HTML 里没有 index.html 那一套 MDUI 组件标签",
              "<mdui-" not in h and "app.js" not in h.replace("spa/app.js", ""), None)

    print("\n2) SEO 跟着词走，且只在真有词时换形状")
    home = body_of("/")
    kwpage = body_of("/s/庆余年")
    check("无词那一份是 WebSite + SearchAction",
          '"@type":"WebSite"' in home and '"@type":"SearchAction"' in home
          and '"@type":"ItemList"' not in home, None)
    check("有词那一份是 ItemList，条目取的是快照里的成品数",
          '"@type":"ItemList"' in kwpage and '"@type":"ListItem"' in kwpage
          and '"numberOfItems": 3' in kwpage, re.findall(r'"numberOfItems":[^,]*', kwpage))
    check("有词那一份不再是 WebSite（两种形状不同时出现，搜索引擎才不会被绕糊）",
          '"@type":"WebSite"' not in kwpage, None)
    check("canonical 跟着词走：/ 指向站点根，/s/<词> 指向那条词",
          'href="http://localhost/"' in home
          and 'rel="canonical" href="http://localhost/s/%E5%BA%86%E4%BD%99%E5%B9%B4"' in kwpage,
          (re.findall(r'<link rel="canonical" href="([^"]+)"', home),
           re.findall(r'<link rel="canonical" href="([^"]+)"', kwpage)))
    check("og:type 也跟着分：有词是 video.movie，没词是 website",
          'property="og:type" content="video.movie"' in kwpage
          and 'property="og:type" content="website"' in home, None)
    check("标题与描述用的是那一条词的形状（不是站级文案复制一份）",
          "<title>《庆余年》影视资源怎么找" in kwpage and "检索" in kwpage
          and "<title>追剧资源搜索 - " in home, None)
    check("robots 仍然是 index,follow（门禁不是靠 noindex 实现的）",
          'name="robots" content="index,follow"' in kwpage and 'name="robots" content="index,follow"' in home,
          None)

    print("\n3) 门禁页的口径：锁住的是接口，不是「别人搜过的词」")
    _builds.clear()
    for path, label in (("/", "未验证的首页"), ("/s/" + "庆余年", "未验证的落地页")):
        r = html_of(path, gate=True)
        h = r.get_data(as_text=True)
        check(f"{label}：照样是 200 的壳（不是 403、不是另渲染一张验证页）",
              r.status_code == 200 and 'id="app"' in h, r.status_code)
        check(f"{label}：boot.locked 为 true", boot_of(h)["locked"] is True, boot_of(h)["locked"])
        b = boot_of(h)
        check(f"{label}：榜单与更新状态一个字段不下发",
              b["hot"] == {} and b["refresh"] is None,
              {k: bool(b[k]) for k in ("hot", "refresh")})
        if path == "/":
            check("未验证的首页：站级门面照旧（站点标题 / canonical 指根 / SearchAction）",
                  "<title>追剧资源搜索" in h and 'rel="canonical" href="http://localhost/"' in h
                  and "SearchAction" in h, None)
            check("未验证的首页：没有 #nojs，boot.snapshot 是空的（首页没有当前词可言）",
                  'id="nojs"' not in h and b["snapshot"] == {}, None)
        else:
            # 门禁页也带 SEO，而且跟着地址里那一条词走：同一条 URL 不能因为门禁开着
            # 就换一套标题与 canonical（那等于给搜索引擎两条互相打架的门面）
            check("未验证的落地页：SEO 跟着词走（标题 / canonical / og:type 都不退回站级）",
                  "<title>《庆余年》影视资源怎么找" in h
                  and 'rel="canonical" href="http://localhost/s/%E5%BA%86%E4%BD%99%E5%B9%B4"' in h
                  and 'property="og:type" content="video.movie"' in h, None)
            # 缓存里已有的结果跟着出去：分享与收录出去的链接不能只有一块滑块
            check("未验证的落地页：缓存里已有的结果照样下发（boot.snapshot 带条目，kw 对得上）",
                  b["snapshot"].get("items") and b["snapshot"]["kw"] == "庆余年", b["snapshot"])
            check("未验证的落地页：#nojs 与 ItemList 也跟着回来（禁 JS 与没匹配上豁免的爬虫都看得到）",
                  'id="nojs"' in h and '"@type":"ItemList"' in h, None)
        check(f"{label}：back 记的是用户本来要点开的那一页（验完回得来）",
              b["back"] == (path if path != "/" else "/"), b["back"])
    check("缓存里没有的词仍然只有门面（没有 #nojs、没有 ItemList，boot.snapshot 是空的）",
          (lambda h2: 'id="nojs"' not in h2 and '"@type":"ItemList"' not in h2
           and boot_of(h2)["snapshot"] == {})(body_of("/s/无此缓存", gate=True)),
          None)
    check("整段门禁页的请求一次快照构建都没触发（seo_mod.snapshot 一次都没被调用）",
          _builds == [], _builds)
    check("未验证时的接口那条路仍然是 423 + human 标记（壳给 200，数据给 423）",
          html_of("/api/search?kw=%E5%BA%86%E4%BD%99%E5%B9%B4", gate=True).status_code == 423
          and html_of("/api/search?kw=%E5%BA%86%E4%BD%99%E5%B9%B4", gate=True).get_json().get("human") == 1,
          None)
    locked_html = body_of("/", gate=True)
    check("门禁开与关给出的是同一个壳（差别只在 boot.locked 这一个布尔）",
          boot_of(body_of("/"))["locked"] is False
          and set(boot_of(locked_html)) == set(boot_of(body_of("/"))), None)

    print("\n4) 放行后 #nojs 那一块：禁 JS 的人也得有出口")
    h = body_of("/")
    nojs = h[h.index('id="nojs"'):h.index('<script id="boot-data"')]
    check("未渲染时那一块整段不存在（不是藏起来，是没生成）",
          'id="nojs"' not in locked_html, None)
    check("放行后的壳里 #nojs 有且只有一块", h.count('id="nojs"') == 1, h.count('id="nojs"'))
    m = re.search(r'<form method="get" action="([^"]+)">.*?<input name="(\w+)"', nojs, re.S)
    check("里面有 method=get 的表单，字段名就是 kw（回车的出口走 /?kw=）",
          m is not None and m.group(1).endswith("/") and m.group(2) == "kw",
          m.groups() if m else None)
    r = html_of("/?kw=" + "庆余年", follow_redirects=False)
    check("那条出口服务端接得住：/?kw=<词> 302 到 /s/<词>，和 JS 写的是同一个地址",
          r.status_code == 302 and r.headers["Location"] == "/s/%E5%BA%86%E4%BD%99%E5%B9%B4",
          (r.status_code, r.headers.get("Location")))
    check("首页那一屏给的是「猜你想搜」两组列表（电影、电视剧各一排）",
          nojs.count("<h2>") == 2 and nojs.count("<li>") == 24,
          (nojs.count("<h2>"), nojs.count("<li>")))
    kw_nojs = body_of("/s/庆余年")
    kw_list = kw_nojs[kw_nojs.index('id="nojs"'):kw_nojs.index('<script id="boot-data"')]
    check("落地页那一屏给的是这条词的结果列表，条数跟快照一致",
          kw_list.count("<li>") == SNAP["count"] and "《庆余年》的检索结果" in kw_list,
          kw_list.count("<li>"))
    check("列表里每一条都指向能点的地址（不是纯文本）",
          kw_list.count("<a href=") == SNAP["count"], kw_list.count("<a href="))
    check("JS 在跑时这一整块让位：壳打 html.js，样式表把 #nojs 收掉、把 #app 放出",
          "classList.add('js')" in SHELL and "html.js #nojs" in read("styles.css")
          and "html:not(.js) #app" in read("styles.css"), None)

    print("\n5) boot 契约：服务端注出的字段名必须和前端读的那一份一模一样")
    ts_boot = read("boot.ts")
    iface = ts_boot[ts_boot.index("export interface Boot {"):ts_boot.index("\n}", ts_boot.index("export interface Boot {"))]
    ts_keys = set(re.findall(r"^\s\s([A-Za-z_]\w*)\??\s*:", iface, re.M))
    py_keys = set(boot_of(body_of("/s/庆余年")).keys())
    check("壳里确实是一整份 boot 直出（不是逐字段白名单，少写一个字段就静默丢掉）",
          "boot | tojson" in SHELL, None)
    check("两边字段名集合相等（少一个前端读不到，多一个白占流量）",
          py_keys == ts_keys, {"只在服务端有": sorted(py_keys - ts_keys),
                               "只在前端有": sorted(ts_keys - py_keys)})
    empty_blk = ts_boot[ts_boot.index("const EMPTY: Boot = {"):ts_boot.index("\n};", ts_boot.index("const EMPTY: Boot = {"))]
    check("boot.ts 里那份兜底 EMPTY 也覆盖同样的键（读不到某个字段时不会拿到 undefined 继续算）",
          set(re.findall(r"^\s\s([a-z_]\w*)\s*:", empty_blk, re.M)) == ts_keys,
          sorted(ts_keys - set(re.findall(r"^\s\s([a-z_]\w*)\s*:", empty_blk, re.M))))
    check("前端按 #boot-data 这个 id 取，且取不到时退回 EMPTY 而不是抛",
          'getElementById("boot-data")' in ts_boot and "return EMPTY" in ts_boot, None)
    b = boot_of(body_of("/s/庆余年"))
    check("落地页的 boot 里 kw/page/canonical 是这一条词的（首屏不用再等接口）",
          b["kw"] == "庆余年" and b["canonical"].endswith("/s/%E5%BA%86%E4%BD%99%E5%B9%B4"),
          (b["kw"], b["canonical"]))
    check("翻页数从地址栏带进来（?page=3 时首屏就是第 3 页）",
          boot_of(body_of("/s/庆余年?page=3"))["page"] == 3, None)
    check("page 被夹在 1..20（不给一个 ?page=99999 就跟着写多大的数）",
          boot_of(body_of("/s/庆余年?page=99999"))["page"] == 20
          and boot_of(body_of("/s/庆余年?page=abc"))["page"] == 1, None)

    print("\n6) 主题契约：壳里那段内联脚本和 React 用的是同一套")
    inline = SHELL[SHELL.index("<script>"):SHELL.index("</script>")]
    check("内联脚本读的 localStorage 键就是 heroui-theme（HeroUI useTheme 那一个）",
          "localStorage.getItem('heroui-theme')" in inline
          and "mdui-theme" not in inline, re.findall(r"localStorage\.getItem\('[^']+'\)", inline))
    check("写的是 <html> 的 class 与 data-theme（useTheme 认的就是这两处）",
          "documentElement" in inline and "classList.add(r)" in inline
          and "setAttribute('data-theme', r)" in inline, None)
    check("非法值一律退回 system，system 再问 matchMedia（不会把别处写的脏值当真）",
          "t = 'system'" in inline and "prefers-color-scheme: dark" in inline, None)
    check("这段脚本排在样式表之前（首帧就是对的色，不等 React）",
          SHELL.index("heroui-theme") < SHELL.index("spa/app.css"), None)
    st = read("styles.css")
    check("@import tailwindcss 必须排在 @heroui/styles 之前（令牌覆盖顺序反了整站配色就错）",
          st.index('@import "tailwindcss"') < st.index('@import "@heroui/styles"'),
          (st.index('@import "tailwindcss"'), st.index('@import "@heroui/styles"')))
    check("有 @custom-variant dark 且认的是 .dark（和壳写的 class、HeroUI 的令牌同一个来源）",
          '@custom-variant dark (&:where(.dark, .dark *));' in st, None)
    check("暗色下压海报亮度用的是 .dark .poster-img（跟着同一个 class，不再跟着 MDUI 的主题类）",
          ".dark .poster-img" in st and "brightness(0.94)" in st
          and "mdui-theme" not in st, None)
    check("切换按钮走 useTheme，三态里 system 是默认档",
          'useTheme("system")' in read("components", "ThemeToggle.tsx")
          and 'const ORDER = ["system", "light", "dark"]' in read("components", "ThemeToggle.tsx"),
          None)

    print("\n7) 门禁接线：423 只有一处入口，界面由 boot.locked 决定")
    apijs = read("api.ts")
    check("接口回 423 时唯一出口是 markDenied（不各自拼一遍「是不是被挡了」）",
          "r.status === 423" in apijs and apijs.count("markDenied()") == 1,
          re.findall(r"423|markDenied\(\)", apijs))
    check("挡下时抛的是单独的 GateBlocked，调用点能把它和网络错误分开",
          "class GateBlocked extends Error" in apijs and "export function isGate" in apijs, None)
    authjs = read("auth.ts")
    check("前端 denied 的初值来自 boot.locked（首屏被挡时第一眼就是滑块，不闪空列表）",
          "let denied = boot.locked;" in authjs, re.findall(r"let denied[^\n]*", authjs))
    check("过了验证是「放行 + tick 加一」，所有取数 effect 靠 tick 自动补上刚才那次",
          "denied = false;" in authjs and "tick += 1;" in authjs
          and "export function useAuthTick" in authjs, None)
    appjs = read("App.tsx")
    check("locked 且 boot.locked 时整页只渲染 LockedView（此时服务端本来也没给数据）",
          "if (locked && boot.locked) {" in appjs and "<LockedView" in appjs, None)
    check("否则渲染就地补验的 GateModal，open 条件是 locked 且 !boot.locked",
          "<GateModal open={locked && !boot.locked}" in appjs, re.findall(r"<GateModal[^>]*", appjs))
    check("取数 effect 把 tick 放进依赖（不然验完不会自动重查，得人再点一次搜索）",
          appjs.count(", tick]") >= 3, appjs.count(", tick]"))
    check("被挡时界面给一句人话，不是一串错误码",
          'isGate(e) ? "等你验证完自动重查。"' in appjs, None)
    gate_ts = read("components", "Gate.tsx")
    check("滑块仍是一条挑战只准用一次：失败后必须重新拿一块",
          "window.setTimeout(ask, 700)" in gate_ts, None)
    check("拖多久是先记时长再清起点（旧写法每次都上报 0ms，永远被判太快）",
          "c.spent = performance.now() - c.down;\n            c.down = 0;" in gate_ts
          and "ms: Math.round(c.spent)" in gate_ts, re.findall(r"spent = [^\n]+", gate_ts))
    check("轨道宽度是现量的，窄屏加宽不会把缺口画偏",
          "getBoundingClientRect().width - w" in gate_ts and "ResizeObserver" in gate_ts, None)
    check("键盘那条路停手 0.6 秒自动提交，不要求再按一次回车",
          "}, 600);" in gate_ts and '"ArrowRight"' in gate_ts, None)

    print("\n8) 图片必须走代理，外链不许原样进 src")
    check("posterOf 只在 ^https?:// 时改写成 /img?url=（已经代理过的不重复包）",
          "/^https?:\\/\\//i.test(pic)" in apijs and '`/img?url=${encodeURIComponent(pic)}`' in apijs,
          re.findall(r"return /.*\n", apijs))
    check("空值直接给空串，不发一个 src=\"\" 的请求",
          'if (!pic) return "";' in apijs, None)
    poster_ts = read("components", "Poster.tsx")
    check("海报卡里的 <img> 用的是 posterOf 的结果，不是 r.pic 本体",
          "const src = posterOf(pic);" in poster_ts and "src={src}" in poster_ts,
          re.findall(r"src=\{[^}]*\}", poster_ts))
    check("详情抽屉里那张也走同一个 PosterImage（posterOf 因此只有一处调用，漏不掉）",
          "<PosterImage pic={spec.pic} title={spec.title} />" in read("components", "DetailDrawer.tsx")
          and "posterOf" not in read("components", "DetailDrawer.tsx"), None)
    imgs = re.findall(r"<img[^>]*", " ".join(
        (p.read_text(encoding="utf-8") for p in SRC.rglob("*.tsx"))))
    check("web/src 里每一个 <img> 的 src 都来自 posterOf",
          imgs and all("posterOf" in t or "src={src}" in t for t in imgs), imgs)
    check("没有任何地方把 .pic 原样塞进 src 或 href",
          not re.search(r"src=\{[^}]*\.pic\}", " ".join(
              p.read_text(encoding="utf-8") for p in SRC.rglob("*.tsx"))), None)

    print("\n9) 埋点用 sendBeacon：不能因为统计把人卡在跳转前")
    check("优先 navigator.sendBeacon，发完直接 return（不等响应）",
          "if (navigator.sendBeacon)" in apijs and "navigator.sendBeacon(\"/api/click\"" in apijs
          and "return;" in apijs[apijs.index("if (navigator.sendBeacon)"):apijs.index("void fetch(")],
          None)
    check("没有 sendBeacon 才退到 fetch + keepalive（同一条不能被发两遍）",
          "keepalive: true" in apijs and "void fetch(" in apijs, None)
    check("整段包在 try 里，统计丢了就丢了，绝不抛到人脸上",
          "try {" in apijs[apijs.index("export function sendClick"):]
          and "/* 统计丢了就丢了 */" in apijs, None)

    print("\n10) 分页判据只看服务端那一句 has_more（翻页按钮换成滚到底自动追加）")
    vod = read("components", "VodPanel.tsx")
    stack = read("stack.ts")
    check("判据是 d.has_more 且这一页真的合出了东西",
          "hasMore: d.has_more && d.results.length > 0," in stack,
          re.findall(r"hasMore:[^\n]+", stack))
    check("没有重新出现「拿 hits 当页数」的算术（hits 只在统计那一行被读出来看）",
          "d.hits >=" not in vod and "hits >=" not in vod and "hits /" not in vod,
          re.findall(r"hits[^\n]{0,30}", vod))
    check("hits 仍然显示，但只当「接口返回多少条」这个信息用",
          "{d.hits}" in vod, None)
    check("并完一部新片都没加也算到头（stalled），别把同一批片反复要",
          "const stalled = fresh === 0 && items.length > 0;" in stack
          and "hasMore: d.has_more && !stalled," in stack, None)
    check("自动追加卡着「还有下一页、此刻没在取、上一轮没出错」，不是见底就发",
          "const canAuto = !!stack && stack.hasMore && !loading && !appending && !error && ioOk;"
          in vod and "rootMargin: \"200px 0px\"" in vod, None)
    check("没有 IntersectionObserver 的老浏览器留一条手动出口，不闷着",
          ") : d.hasMore ? (" in vod and "onPress={onLoadMore}" in vod, None)

    print("\n11) 构建产物与依赖版本")
    for f in ("app.js", "app.css"):
        p = BASE / "zhuiju" / "static" / "spa" / f
        check(f"产物 spa/{f} 存在且非空（不是占位的空文件）",
              p.is_file() and p.stat().st_size > 10000, p.stat().st_size if p.is_file() else None)
    pkg = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
    check("react 是 19 这一代（这次转向的前提，掉回 18 就说明装的是旧的东西）",
          pkg["dependencies"]["react"].split(".")[0] == "19"
          and pkg["dependencies"]["react-dom"].split(".")[0] == "19", pkg["dependencies"])
    check("@heroui/react 与 @heroui/styles 版本一致（差一个补丁号就会拿到对不上的令牌）",
          pkg["dependencies"]["@heroui/react"] == pkg["dependencies"]["@heroui/styles"],
          (pkg["dependencies"]["@heroui/react"], pkg["dependencies"]["@heroui/styles"]))
    check("tailwind 是 v4（@import 「tailwindcss」这种写法只在 v4 成立）",
          pkg["devDependencies"]["tailwindcss"].split(".")[0] == "4"
          and pkg["devDependencies"]["@tailwindcss/vite"].split(".")[0] == "4", pkg["devDependencies"])
    check("没有把 MDUI 留在依赖里（后台那份走 vendor，不该混进前台的构建）",
          not any("mdui" in k for k in {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}),
          list(pkg.get("dependencies", {})) + list(pkg.get("devDependencies", {})))

    print("\n12) 不引外网：这站点常年跑在没外网的机器上")
    ALLOW = ("https://schema.org", "http://www.w3.org/2000/svg")

    def extern(text):
        """只抓真正的地址；schema.org（JSON-LD 的 @context）与 SVG 的 XML 命名空间
        都不是「去外网拿东西」，明确放行。"""
        hits = re.findall(r"""https?://[^\s"'<>\\\])]+""", text)
        return [u for u in hits if not any(u == a or u.startswith(a + "/") for a in ALLOW)]

    check("shell.html 里没有外站资源地址（只有 schema.org 与 SVG 命名空间这两个例外）",
          not extern(SHELL), extern(SHELL))
    bad = {}
    for p in list(SRC.rglob("*.ts")) + list(SRC.rglob("*.tsx")) + [SRC / "styles.css"]:
        e = extern(p.read_text(encoding="utf-8"))
        if e:
            bad[str(p.relative_to(WEB))] = e
    check("web/src 全部源码里没有外站资源地址", not bad, bad)
    check("没有 cdn / jsdelivr / unpkg / googleapis 这类字样的引用",
          not re.search(r"cdn\.|jsdelivr|unpkg|googleapis", SHELL
                        + " ".join(p.read_text(encoding="utf-8") for p in SRC.rglob("*.ts*"))), None)
    check("字体也明确不引外网：--font-sans 全是系统族",
          "--font-sans:" in st and "url(" not in st[st.index("@theme"):st.index("@layer")], None)

    print("\n13) 详情弹框的环形揭示：以点击处为圆心荡开，海报不参与过渡")
    check("弹框本体常驻 detail-sheet（关着的弹框整个不挂载，平时不占名字）",
          re.search(r"\.detail-sheet\s*\{[^}]*view-transition-name: detail-sheet", st) is not None,
          None)
    check("海报不再参与过渡：cover-active 这个名字与 .vt-hero 挂点都已删干净",
          "cover-active" not in st and "vt-hero" not in st
          and "cover-active" not in appjs and "vt-hero" not in read("components", "DetailDrawer.tsx"),
          re.findall(r"cover-active|vt-hero", st + appjs))
    check("开与缩是同一对关键帧的正反放：clip-path 的圆以点击点为圆心（弹框本地坐标"
          "--vt-lx/--vt-ly/--vt-r），没有位移与缩放，也没有暗幕层（detail-dim/dim-open 全删）",
          "clip-path: circle(0px at var(--vt-lx, 50%) var(--vt-ly, 50%))" in st
          and "circle(var(--vt-r, 150%) at var(--vt-lx, 50%) var(--vt-ly, 50%))" in st
          and "@keyframes sheet-open" in st and "@keyframes sheet-close" in st
          and "detail-dim" not in st and "dim-open" not in st and "dim-close" not in st
          and "transform: translate(var(--vt-dx" not in st, None)
    check("遮罩走透明档：不暗、不糊（variant=transparent），页面原样露着",
          'variant="transparent"' in read("components", "DetailDrawer.tsx")
          and 'variant="blur"' not in read("components", "DetailDrawer.tsx"), None)
    check("弹框外缘不再甩 accent 色高光：sheet-ripple 与水纹那两圈 box-shadow 已删",
          "sheet-ripple" not in st
          and "::view-transition-new(detail-sheet)" in st
          and "sheet-open 0.42s" in st, None)
    check("弹框层盖在 root 快照之上（z-index），没有暗幕层、没有第三层海报",
          re.search(r"::view-transition-group\(detail-sheet\)\s*\{[^}]*z-index: 2", st) is not None
          and "::view-transition-group(detail-dim)" not in st
          and "::view-transition-group(cover-active)" not in st, None)
    check("没有 VT 的浏览器给弹框一个就地淡入，有 VT 的关掉它（两个动画叠着就是抖）",
          "html:not(.vt-ok) .detail-sheet" in st and "html.vt-ok .detail-sheet {\n    animation: none;\n  }" in st,
          None)
    appjs = read("App.tsx")
    check("圆心与半径在被点的海报上现算（不写死像素），只写弹框本地这三组变量",
          "function setVtOrigin" in appjs
          and 'root.setProperty("--vt-lx"' in appjs
          and 'root.setProperty("--vt-r"' in appjs
          and 'root.setProperty("--vt-dr"' not in appjs, None)
    check("开：先同步挂上弹框再写圆心（捕获在回调返回后那一帧，量完才赶得上）",
          appjs.index("flushSync(() => setSpec(s));") < appjs.index("setVtOrigin(cx, cy,"), None)
    check("缩：在 startViewTransition 之前先写圆心（弹框还挂着，矩形是准的）",
          (lambda c: c.index("setVtOrigin(hr.left") < c.index("document.startViewTransition"))(
              appjs[appjs.index("const closeDetail = useCallback"):]), None)
    check("关闭时把透明遮罩整块从绘制里拿掉（钩子换到 .detail-backdrop）",
          '.detail-backdrop' in appjs and '.detail-dim' not in appjs, None)

    print("\n14) 窄屏的排序：结果之后依次是接口状态、《xxx》的检索结果")
    check("接口状态不再用 order-first 顶到结果上面（手机上它把结果顶出半屏）",
          "order-first" not in appjs and "xl:order-none" not in appjs, None)
    check("aside 两块的 DOM 顺序就是窄屏的视觉顺序：接口状态在前、检索快照在后",
          appjs.index("<SourcesPanel") < appjs.index("<SnapshotCard"), None)

finally:
    hot_mod.get, seo_mod.snapshot, seo_mod.cached_snapshot = _real_hot, _real_snap, _real_cached
    human_mod.enabled = _real_enabled

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
