# -*- coding: utf-8 -*-
"""浏览器识别、来源页判定与主题（亮/暗）的离线测试（不联网）。

    python tests/test_agent_theme.py

统计库与口令配置都指到临时目录，不碰真实的 stats.db / admin.json。
"""
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from zhuiju import admin as admin_mod  # noqa: E402
from zhuiju import agent  # noqa: E402
from zhuiju import stats as stats_mod  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="zhuiju_agent_test_"))
admin_mod.CONFIG = TMP / "admin.json"
stats_mod.DB = TMP / "stats.db"
stats_mod.DATA = TMP
stats_mod._ready = False
stats_mod.ensure_schema()

FAILS = []


def check(name, cond, got=None):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  got={got!r}"))
    if not cond:
        FAILS.append(name)


def ua(who, s, expect, field="browser"):
    """expect 是要比对的字段值；传 of= 换字段（默认比 browser）。"""
    r = agent.parse_ua(s)
    check(f"UA→{who}", r[field] == expect, {"browser": r["browser"], "os": r["os"],
                                          "device": r["device"], "bot": r["bot"]})
    return r


WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "

print("1) 浏览器识别：谁包住谁，顺序错了就全认成 Chrome")
ua("Chrome", WIN + "Chrome/124.0.6367.201 Safari/537.36", "Chrome 124.0")
ua("Edge 不被 Chrome 抢走", WIN + "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.2478.82", "Edge 124.0")
ua("Opera 同理", WIN + "Chrome/108.0.0.0 Safari/537.36 OPR/94.0.0.0", "Opera 94.0")
ua("微信内置", WIN + "Chrome/109.0.0.0 Safari/537.36 MicroMessenger/8.0.40", "微信 8.0")
ua("QQ浏览器", WIN + "Chrome/100.0.0.0 Safari/537.36 QQBrowser/13.0.5068.400", "QQ浏览器 13.0")
ua("UC", "Mozilla/5.0 (Linux; U; Android 12; zh-CN) AppleWebKit/537.36 UCBrowser/15.5.1", "UC浏览器 15.5")
ua("360", WIN + "Chrome/69.0.3947.111 Safari/537.36 360SE", "360浏览器")
ua("Firefox", WIN + "rv:126.0) Gecko/20100101 Firefox/126.0", "Firefox 126.0")
ua("IE", "Mozilla/5.0 (compatible; MSIE 10.0; Windows NT 6.1; Trident/6.0)", "IE 10.0")
ua("Safari 放最后也认得出", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
   "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15", "Safari 16.5")

r = agent.parse_ua("Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
                   "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1")
check("iPhone 认成 Safari 17.4", r["browser"] == "Safari 17.4", r["browser"])
check("iPhone 判 iOS 而不是 macOS", r["os"] == "iOS 17.4", r["os"])
check("iPhone 判手机", r["device"] == "手机", r["device"])
r = agent.parse_ua("Mozilla/5.0 (iPad; CPU OS 16_1 like Mac OS X) AppleWebKit/605.1.15 "
                   "(KHTML, like Gecko) Version/16.1 Mobile/15E148 Safari/604.1")
check("iPad 判平板（它的 UA 里也带 Mobile/ 历史标记）", r["device"] == "平板", r["device"])
check("iPad 判 iPadOS", r["os"] == "iPadOS 16.1", r["os"])
r = agent.parse_ua("Mozilla/5.0 (Linux; Android 10; SM-T500) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36")
check("安卓不带 Mobile 判平板", r["device"] == "平板", r["device"])
# 注意别复用 WIN 常量：它是 NT 10.0 的前缀，拿它拼出来的 UA 断言 Win7 当然对不上
r = agent.parse_ua("Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/86.0.4240.198 Safari/537.36")
check("Windows NT 6.1 认成 Win7 而不是 10/11", r["os"] == "Windows 7", r["os"])

print("\n2) 爬虫与脚本要单独分出来，否则查询次数被抓取灌满")
for s, name in (("curl/8.5.0", "curl"), ("python-requests/2.34.2", "requests 脚本"),
                ("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", "Google 爬虫"),
                ("Mozilla/5.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)", "百度爬虫")):
    r = agent.parse_ua(s)
    check(f"{name} 标为 bot", r["bot"] and r["device"] == "程序", r)
r = agent.parse_ua("")
check("空 UA 不抛异常、算未知", r["browser"] == "" and r["label"] == "未知", r)
r = agent.parse_ua("瞎写的")
check("乱写的 UA 不猜品牌", r["browser"] == "", r)
r = agent.parse_ua("A" * 900)
check("超长 UA 被截断", len(r["ua"]) == 200, len(r["ua"]))

print("\n3) 来源页：站内给全路径、站外只给域名、没有头就是直接访问")
OWN = ("127.0.0.1:5000", "127.0.0.1", "localhost:5000", "localhost")
d = agent.parse_ref("", OWN)
check("没有 Referer -> direct", d["kind"] == "direct" and "直接访问" in d["label"], d)
d = agent.parse_ref(None, OWN)
check("None 也当直接访问", d["kind"] == "direct", d)
d = agent.parse_ref("no-referrer", OWN)
check("浏览器明说 no-referrer 也归直接访问", d["kind"] == "direct", d)
d = agent.parse_ref("http://127.0.0.1:5000/", OWN)
check("站内首页", d["kind"] == "site" and d["label"] == "站内首页", d)
d = agent.parse_ref("http://127.0.0.1:5000/s/%E5%BA%86%E4%BD%99%E5%B9%B4", OWN)
check("站内能看到具体上一页是哪部剧", d["kind"] == "site" and d["label"] == "站内 /s/庆余年", d)
check("原始 path 保留转义形态、label 才解码", d["path"] == "/s/%E5%BA%86%E4%BD%99%E5%B9%B4", d["path"])
d = agent.parse_ref("http://localhost:5000/s/x", OWN)
check("localhost 也算站内（生产里 own_hosts 两个都带）", d["kind"] == "site", d)
d = agent.parse_ref("http://localhost:5000/s/x", ("127.0.0.1:5000",))
check("只登记 127.0.0.1 时 localhost 判为外站——浏览器眼里本来就是两个 origin",
      d["kind"] == "out", d)
d = agent.parse_ref("https://www.baidu.com/s?wd=%E6%98%A5%E9%A3%8E%E7%83%88%E9%A9%AC", OWN)
check("百度搜索带出关键词", d["kind"] == "search" and d["q"] == "春风烈马", d)
check("搜索文案含引擎名", "百度" in d["label"], d["label"])
d = agent.parse_ref("https://www.google.com/search?q=kung+fu", OWN)
check("Google 用 q 参数", d["kind"] == "search" and d["q"] == "kung fu", d)
d = agent.parse_ref("https://www.bing.com/search", OWN)
check("搜索但没关键词也不崩", d["kind"] == "search" and "必应" in d["label"], d)
d = agent.parse_ref("https://movie.douban.com/subject/1234/?from=catalog", OWN)
check("跨站只到域名，不假装知道路径",
      d["kind"] == "out" and d["label"] == "https://movie.douban.com" and "?" not in d["label"], d)
d = agent.parse_ref("瞎写的", OWN)
check("解析不来的来源标 other", d["kind"] == "other" and "无法解析" in d["label"], d)
d = agent.parse_ref("javascript:alert(1)", OWN)
check("伪协议来源不会变成站内", d["kind"] in ("other", "out"), d)

print("\n4) 入库：浏览器/来源解析结果落成结构化列")
stats_mod.record("庆余年", "8.8.8.8", via="api", results=9, ua=WIN + "Chrome/124.0.0.0 Safari/537.36",
                 referrer="http://127.0.0.1:5000/", own_hosts=OWN)
stats_mod.record("庆余年", "8.8.8.8", via="api", results=9,
                 ua=WIN + "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.2478.82",
                 referrer="http://127.0.0.1:5000/s/%E6%98%A5%E9%A3%8E", own_hosts=OWN)
stats_mod.record("繁花", "1.1.1.1", via="api", results=3,
                 ua="Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) Version/17.4 Mobile/15E148 Safari/604.1",
                 referrer="https://www.baidu.com/s?wd=%E7%B9%81%E8%8A%B1", own_hosts=OWN)
stats_mod.record("奥本海默", "9.9.9.9", via="api", results=1, ua="curl/8.5.0", own_hosts=OWN)
row = stats_mod.list_queries({"kw": "庆余年"})["items"][0]
check("明细里能读到浏览器与系统", row["browser"].startswith("Edge") and row["os"] == "Windows 10/11", row)
check("明细里能读到来源文案", row["ref_label"] == "站内 /s/春风", row["ref_label"])
check("来源类型分得开", row["ref_kind"] == "site", row["ref_kind"])
row2 = stats_mod.list_queries({"kw": "奥本海默"})["items"][0]
check("脚本客户端 bot=1", row2["bot"] == 1 and row2["device"] == "程序", row2)
check("没有 Referer 的行 ref_kind 是 direct", row2["ref_kind"] == "direct", row2)

agg = stats_mod.summary({})
check("按浏览器聚合有 Chrome 和 Edge",
      {"Chrome 124.0", "Edge 124.0"} <= {b["browser"] for b in agg["by_browser"]},
      [b["browser"] for b in agg["by_browser"]])
check("聚合里 bot 数单独统计", any(b["bots"] >= 1 for b in agg["by_browser"]), agg["by_browser"])
check("按来源类型聚合", {r["kind"] for r in agg["by_ref"]} >= {"site", "search", "direct"},
      [r["kind"] for r in agg["by_ref"]])
check("来源页明细含解码后的站内路径",
      any(f["label"] == "站内 /s/春风" for f in agg["by_ref_src"]), agg["by_ref_src"])
check("按浏览器筛", stats_mod.list_queries({"browser": "Edge 124.0"})["total"] == 1)
check("按设备筛", all(r["device"] == "手机" for r in
      stats_mod.list_queries({"device": "手机"})["items"]))
check("按来源类型筛", stats_mod.list_queries({"ref_kind": "search"})["total"] == 1)
check("乱值当没填而不是筛出空",
      stats_mod.list_queries({"ref_kind": "x' OR 1=1"})["total"] == agg["count"])
check("非法 device 值同样被忽略", stats_mod.list_queries({"device": "冰箱"})["total"] == agg["count"])

print("\n5) 老库再加一批列：升级顺序不能反（iso 索引踩过）")
import sqlite3
old = TMP / "old.db"
oc = sqlite3.connect(str(old))
oc.execute("CREATE TABLE queries (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,"
           " day TEXT NOT NULL, ip TEXT NOT NULL, kw TEXT NOT NULL, via TEXT NOT NULL,"
           " results INTEGER, hits INTEGER, sources_ok INTEGER, sources_total INTEGER, ms REAL)")
oc.execute("INSERT INTO queries (ts, day, ip, kw, via, results) VALUES"
           " ('2026-10-15 09:00:00','2026-10-15','8.8.8.8','老记录','api',1)")
oc.commit()
oc.close()
real_db, stats_mod._ready = stats_mod.DB, False
stats_mod.DB = old
stats_mod.MIGRATE_ERROR = ""
try:
    stats_mod.ensure_schema()
    cols = [r[1] for r in sqlite3.connect(str(old)).execute("PRAGMA table_info(queries)")]
    need = {"iso", "geo", "browser", "os", "device", "bot", "ua", "ref", "ref_kind", "ref_label"}
    check("一次升级把两批列都补齐", need <= set(cols), sorted(need - set(cols)))
    check("升级没报错", stats_mod.MIGRATE_ERROR == "", stats_mod.MIGRATE_ERROR)
    old_row = stats_mod.list_queries({})["items"][0]
    check("老行浏览器为空而不是编一个", not old_row["browser"], old_row)
    check("老行仍能读出来（回填不了也不该丢数据）", old_row["kw"] == "老记录", old_row)
finally:
    stats_mod.DB, stats_mod._ready = real_db, False
    stats_mod.MIGRATE_ERROR = ""
    stats_mod.ensure_schema()

print("\n6) 主题：CSS 变量化 + 暗色板 + 页面接线")
css = (BASE / "zhuiju" / "static" / "app.css").read_text(encoding="utf-8")
import re
root = css[css.index(":root {"):css.index("\n}", css.index(":root {"))]
dark = css[css.index('[data-theme="dark"] {'):]
dark = dark[:dark.index("\n}") + 2]        # dark 本身已是子串，下标要从 0 算
light_vars = set(re.findall(r"(--[a-z0-9-]+)\s*:", root))
# 只比"颜色类"变量：圆角、阴影、间距这些本来就不需要暗色版本，硬要求覆盖是假规则
color_vars = lambda blk: {v for v, val in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", blk)
                           if re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", val)}
dark_vars = color_vars(dark)
body = css[css.index("\n}", css.index(":root {")):]
# 允许在变量定义里写死颜色（调色板本来就是定义处），不允许直接当属性值用在规则里
bad = [l.strip() for l in re.findall(r"[^\n]*#[0-9a-fA-F]{3,8}[^\n]*", body)
       if not l.strip().startswith("--")]
check(":root 与调色板之外没有写死的颜色", not bad, bad[:4])
check("暗色板把每一个亮色**颜色**变量都覆盖了（漏一个就串色）",
      color_vars(root) <= dark_vars, sorted(color_vars(root) - dark_vars))
check("暗色板里没混进笔误值", "#" in dark and " e5a css" not in dark)
check("暗色块带 color-scheme，表单控件跟随", "color-scheme: dark" in dark)
check("亮色也声明了 color-scheme", "color-scheme: light" in root)

for name in ("index.html", "admin.html"):
    t = (BASE / "zhuiju" / "templates" / name).read_text(encoding="utf-8")
    check(f"{name} 有主题预置", '_theme.html' in t)
    check(f"{name} 预置在样式表之前",
          t.index('_theme.html') < t.index("app.css") if "app.css" in t else False)
    check(f"{name} 有切换按钮", "data-theme-toggle" in t)
    check(f"{name} 挂了 theme.js", "theme.js" in t)
th = (BASE / "zhuiju" / "templates" / "_theme.html").read_text(encoding="utf-8")
# 注释里就写着"defer"这个词，所以只能查真正的属性写法，不能查子串
check("预置脚本用内联而非 defer（否则暗色刷新闪白）",
      "<script>" in th and "<script defer" not in th and "<script src" not in th)
check("预置脚本读 localStorage", "zhuiju_theme" in th and "prefers-color-scheme" in th)
tj = (BASE / "zhuiju" / "static" / "theme.js").read_text(encoding="utf-8")
check("theme.js 三态循环", all(k in tj for k in ('"auto"', '"light"', '"dark"')))
check("theme.js 写 localStorage", "setItem" in tj)
check("localStorage 写不了也不崩（无痕模式）", "catch" in tj)
check("跟随系统时监听系统切换", 'addEventListener("change"' in tj or "addListener" in tj)

print("\n7) 后台页面真的把两列渲染出来了")
cfg = admin_mod.load()
admin_mod.save({"password": "ce-shi-mi-ma", "secret_key": cfg["secret_key"], "password_is_temp": False})
from zhuiju.app import create_app  # noqa: E402

c = create_app().test_client()
h = c.get("/admin").get_data(as_text=True)
tok = re.search(r'name="csrf" value="([0-9a-f]+)"', h).group(1)
c.post("/admin/login", data={"csrf": tok, "password": "ce-shi-mi-ma"})
d = c.get("/admin").get_data(as_text=True)
check("明细表头有浏览器列", "<th>浏览器</th>" in d)
check("明细表头有来源页列", "<th>来源页</th>" in d)
check("有浏览器分布面板", "浏览器 / 设备" in d)
check("有来源分布面板", "来源页（对方从哪来）" in d)
check("筛选表单有浏览器与来源控件", 'name="browser"' in d and 'name="ref_kind"' in d and 'name="device"' in d)
check("页脚说明了 Referer 的限制", "Referrer-Policy" in d)
check("页脚说明了 UA 可伪造", "User-Agent" in d and "伪造" in d)
r = c.get("/admin?browser=" + "Edge 124.0").get_data(as_text=True)
check("按浏览器筛选后仍 200", "第 1 /" in r and 'name="browser" value="Edge 124.0"' in r)
r = c.get("/admin?ref_kind=site").get_data(as_text=True)
check("按来源类型筛选正常", r.count('name="ref_kind"') >= 1)
r = c.get("/admin?ref_kind=bogus").get_data(as_text=True)
check("非法来源类型当没填", "Edge 124.0" in r)      # 没被筛成空

print("\n8) 配色静态体检：把上次那种「蓝底红字」的替换事故钉住")
def palette(block):
    out = {}
    for name, val in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", block):
        v = val.strip()
        if re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", v):
            out[name] = v
    return out


def rgb(v):
    v = v.strip()
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    n = re.findall(r"[\d.]+", v)
    return [float(n[0]), float(n[1]), float(n[2])]


def contrast(a, b):
    def lum(c):
        f = lambda v: (v / 255) / 12.92 if v / 255 <= .03928 else ((v / 255 + .055) / 1.055) ** 2.4
        r, g, bl = rgb(c)
        return .2126 * f(r) + .7152 * f(g) + .0722 * f(bl)
    l1, l2 = lum(a), lum(b)
    return round((max(l1, l2) + .05) / (min(l1, l2) + .05), 2)


# 这些配对是从 CSS 里读出来的实际搭配，改任何一处配色都会在这里暴露
PAIRS = [("--ink", "--surface"), ("--ink-2", "--surface"), ("--ink-2", "--surface-2"),
         ("--dim", "--surface"), ("--on-accent", "--brand"), ("--brand-ink", "--brand-soft"),
         ("--ok", "--ok-bg"), ("--bad", "--bad-bg"), ("--warn", "--warn-bg")]
for label, blk in (("亮色", root), ("暗色", dark)):
    pal = palette(blk)
    for fg, bg in PAIRS:
        if fg not in pal or bg not in pal:
            check(f"{label} {fg}/{bg} 两色都在调色板里", False, sorted({fg, bg} - set(pal)))
            continue
        c_val = contrast(pal[fg], pal[bg])
        check(f"{label} {fg} on {bg} 对比度 {c_val} ≥ 4.5", c_val >= 4.5, c_val)

gobtn = dict(re.findall(r"([a-z-]+)\s*:\s*([^;]+);",
                        re.search(r"\.gobtn \{([^}]*)\}", css).group(1)))
check("主按钮前景是 --on-accent 而不是语义色", "var(--on-accent)" in gobtn.get("color", ""),
      gobtn.get("color"))
check("主按钮与输入框同一套圆角", gobtn.get("border-radius") == "8px", gobtn.get("border-radius"))
unified = re.search(r"\.pbtn, \.pager a, \.jumpbtn, \.themebtn, \.fbtn \{", css)
check("翻页/跳转/主题/筛选胶囊合并成一处定义", unified is not None)
check("旧的分立胶囊定义已删除", css.count(".pbtn {\n") == 0 and css.count(".pager a {\n") == 0)
check("主题切换渐变只在切换期间生效",
      ".theme-anim" in css and "prefers-reduced-motion" in css)
tj = (BASE / "zhuiju" / "static" / "theme.js").read_text(encoding="utf-8")
check("theme.js 切换时才加 theme-anim 并定时摘掉",
      'classList.add("theme-anim")' in tj and "classList.remove" in tj and "setTimeout" in tj)
check("首屏预置不走 apply，所以不会一进页面就闪一遍渐变",
      "apply(" not in th.split("<script>")[0] and "apply(\"auto\", true)" not in tj.split("sync();")[0])

print("\n9) 宽度、系统列、归属地只到国家")
# 这一节自带数据：不依赖前面留下的记录，否则改到别的节就会莫名其妙红
for ip, ua_ in (("223.5.5.5", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                 "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
                ("1.1.1.1", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                            "(KHTML, like Gecko) Version/16.5 Safari/605.1.15"),
                ("91.108.4.11", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")):
    stats_mod.record("宽度用例", ip, via="api", results=4, ua=ua_,
                     referrer="http://127.0.0.1:5000/", own_hosts=OWN)
d2 = c.get("/admin").get_data(as_text=True)
wrap = re.search(r"\.wrap \{([^}]*)\}", css).group(1)
check("内容宽度随屏走而不是固定 1000px", "min(1680px" in wrap and "100% - 48px" in wrap, wrap.strip())
check("超宽屏有上限，不把表格拉到没边", "1680px" in wrap)
check("边框算在宽度内（不会溢出横向滚动）", "box-sizing: border-box" in wrap)
ladder = [(int(m.group(2)), m.group(1), int(m.group(3))) for m in
          re.finditer(r"@media \((min|max)-width: (\d+)px\)[^{]*\{\s*\.hotgrid \{ --hot-cols: (\d+)", css)]
check("宽屏补了列数，不会一行 6 张右边空一大片",
      {c for _, _, c in ladder} >= {9, 7, 5}, ladder)
wide = {c for _, kind, c in ladder if kind == "min"}
check("两条 min-width 断点互不重叠且都大于基础 6 列", wide == {9, 7} and min(wide) > 6, wide)

d2 = c.get("/admin").get_data(as_text=True)
head = re.search(r"<thead><tr>(.*?)</tr>", d2[d2.index("<th>时间") - 40:], re.S).group(1)
cols = re.findall(r"<th>([^<]+)</th>", head)
check("明细有独立的系统列", "系统" in cols, cols)
check("系统列排在浏览器之后", cols.index("系统") == cols.index("浏览器") + 1, cols)
i_os = cols.index("系统")
row0 = re.search(r"<tbody>\s*<tr>(.*?)</tr>", d2[d2.index("<th>时间"):], re.S).group(1)
cells = [re.sub(r"<[^>]+>", " ", x).strip() for x in
         re.findall(r"<td[^>]*>(.*?)</td>", row0, re.S)]
check("系统格里有真实系统名或未知", any(k in cells[i_os] for k in
      ("Windows", "macOS", "iOS", "Android", "Linux", "未知")), cells[i_os])
check("系统格可点筛选", f'/admin?os=' in re.search(r"<td[^>]*>(.*?)</td>",
      re.findall(r"<td[^>]*>.*?</td>", row0, re.S)[i_os], re.S).group(1))
check("筛选栏有系统输入框", 'name="os"' in d2)
check("按系统筛选能用", "macOS" in c.get("/admin?os=macOS").get_data(as_text=True))
def detail_only(html):
    """只取 #detail 到 #geo 之间的片段。
    之前用 split("明细") 会被归属地那块注释里的"明细"两个字切到最后一段，取到的不是表格。"""
    return html[html.index('id="detail"'):html.index('id="geo"')]

check("按系统前缀也能筛（输 Win 命中 Windows 10/11）",
      "Windows 10/11" in detail_only(c.get("/admin?os=Win").get_data(as_text=True)))
bogus_html = c.get("/admin?os=" + "x' OR 1=1").get_data(as_text=True)
check("填了不存在的系统值就给明确的空态，而不是假装没筛",
      "这个条件下没有记录" in detail_only(bogus_html)
      # Jinja 会把 ' 转义成 &#39;，所以按转义后的形态比，别比原始串
      and 'name="os"' in bogus_html and "OR 1=1" in bogus_html)
check("注入串被当普通字符串比对，表还在",
      "这个条件下没有记录" in detail_only(bogus_html)
      and stats_mod.list_queries({})["total"] > 0)

geo = d2[d2.index("geotbl"):]
pairs = re.findall(r'\?geo=([A-Z]{2})">([^<]+)<', geo)
check("归属地列表只显示国家，不带省市运营商",
      all(("省" not in v and "市" not in v and "·" not in v) for _, v in pairs), pairs)
check("国家名取自库里那一列（中国 / Australia 原样）",
      {"中国", "Australia", "Netherlands"} <= {v for _, v in pairs}, pairs)
check("表头写的是国家 / 地区而不是含糊的归属地",
      "<th>国家 / 地区</th>" in geo)
check("明细那一列仍然是带省市的完整归属地", "浙江省杭州市" in
      stats_mod.list_queries({"geo": "CN"})["items"][0]["geo"])

print("\n10) 面板内联滚动：五行的五行，明细十行")
ah = (BASE / "zhuiju" / "templates" / "admin.html").read_text(encoding="utf-8")
# 认身份靠各表自己的第一个表头，不靠 <h2>：明细和归属地那两块的 h2 里带 <span>，
# 用 h2 配对着正则会直接漏掉这两块
folded = [(m.group(1), re.search(r"<th>([^<]+)</th>", m.group(2)).group(1))
          for m in re.finditer(r'<div class="fold" data-fold data-rows="(\d+)">\s*<table[^>]*>'
                               r'\s*<thead><tr>(.*?)</tr>', ah, re.S)]
check("六块表都包了滚动容器（关键词/IP/浏览器/来源/明细/归属地）", len(folded) == 6, folded)
check("每块包的都是预期那张表",
      [t for _, t in folded] == ["关键词", "IP", "浏览器", "来源", "时间", "国家 / 地区"],
      [t for _, t in folded])
check("前四块与归属地列表都是 5 行，明细 10 行",
      [n for n, _ in folded] == ["5", "5", "5", "5", "10", "5"], [n for n, _ in folded])
# 说明文字必须在容器外：不然注意事项也跟着一起滚，第一眼看不到
fold_spans = [(m.start(), ah.index("</table>", m.start())) for m in
              re.finditer(r'<div class="fold" data-fold', ah)]
check("说明文字在滚动容器外", all("atip" not in ah[s:e] for s, e in fold_spans),
      [ah[s:e].count("atip") for s, e in fold_spans])
check("没有残留的展开/收起按钮（要做的是内联滚动条，不是点击展开）",
      "foldbtn" not in ah and "foldbtn" not in css and "is-open" not in ah,
      (ah.count("foldbtn"), css.count("foldbtn"), ah.count("is-open")))

fold = dict(re.findall(r"([a-z-]+)\s*:\s*([^;]+);",
                       re.search(r"\.fold \{([^}]*)\}", css).group(1)))
check("容器自己就是滚动区，不在框内滚的写法（hidden）都算错",
      fold.get("overflow", "").strip() == "auto", fold)
check("框高不写死在 CSS 里：行高随折行变化，写死会露半行", "max-height" not in fold, fold)
check("滚动条收成细条，不吃掉表格宽度", fold.get("scrollbar-width", "").strip() == "thin", fold)
check("滚动条颜色跟着主题变量走，暗色下不会是一道白槽",
      "var(--" in fold.get("scrollbar-color", ""), fold.get("scrollbar-color"))
th = dict(re.findall(r"([a-z-]+)\s*:\s*([^;]+);",
                     re.search(r"\.fold thead th \{([^}]*)\}", css).group(1)))
check("框内滚动时表头吸顶", th.get("position", "").strip() == "sticky" and th.get("top", "").strip() == "0", th)
check("吸顶表头有不透明底色，否则行会从字底下透过去",
      "var(--surface)" in th.get("background", ""), th.get("background"))
check("吸顶表头的分隔线是 inset box-shadow 而不是 border-bottom",
      th.get("box-shadow", "").strip() == "inset 0 -1px 0 var(--line)", th.get("box-shadow"))
check("滚动条配色与表头配对用的都是同一套语义变量",
      {k for k in (fold.get("scrollbar-color", "") + th.get("background", "")).split()
       if k.startswith("var(")} <= {"var(--line)", "var(--surface)", "transparent"},
      (fold.get("scrollbar-color"), th.get("background")))

js = ah[ah.index("/* ---- 面板内联滚动"):]
check("框高取第 N+1 行的 offsetTop（量出来的，不是猜的像素）",
      "rows[n].offsetTop" in js and "rows.length <= n" in js)
check("不足 N 行时不设高度，免得下面留一截空白", "f.style.maxHeight = ''" in js)
check("设完高度再量一次：竖向滚动条占了宽度，行会重新折行",
      js.count("= foldH(f, n)") == 2, js.count("= foldH(f, n)"))
check("横向滚动条占的那几像素高度要补回去，否则最后一行被它盖住",
      "f.offsetHeight - f.clientHeight" in js)
check("明细局部换页后重算框高", "refold();" in ah[ah.index("function render"):ah.index("/* ---- 面板内联滚动")])
check("窗口变窄重算（折行变了会露半行），且做防抖",
      "resize" in js and "clearTimeout(foldT)" in js and "setTimeout(refold, 200)" in js)

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
