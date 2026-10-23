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
import gate_off  # noqa: E402  门禁与本文件的测试对象无关，见 tests/gate_off.py
gate_off.off(TMP)
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
                # Werkzeug 是 Flask 的 test_client 自带的 UA：离线工具一跑就往真实库里
                # 写一行（实测 27 行），以前不在词表里，被算成"像真人"
                ("Werkzeug/3.1.9", "Werkzeug 测试客户端"),
                ("python-httpx/0.27.0", "httpx 脚本"),
                ("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", "Google 爬虫"),
                ("Mozilla/5.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)", "百度爬虫")):
    r = agent.parse_ua(s)
    check(f"{name} 标为 bot", r["bot"] and r["device"] == "程序" and r["browser"] == name, r)
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
    check("老行不编具体浏览器名，归到新写法「未知」（NULL 与 '未知' 混着会裂成两行）",
          old_row["browser"] == stats_mod.UNKNOWN and old_row["device"] == stats_mod.UNKNOWN
          and old_row["os"] == "", old_row)
    check("原始 UA 没被伪造：那批行本来就没存 UA，留 NULL/空",
          not old_row["ua"], repr(old_row["ua"]))
    check("老行仍能读出来（回填不了也不该丢数据）", old_row["kw"] == "老记录", old_row)
finally:
    stats_mod.DB, stats_mod._ready = real_db, False
    stats_mod.MIGRATE_ERROR = ""
    stats_mod.ensure_schema()

print("\n6) 主题：MDUI 2 装载顺序 + 三态切换 + 页面接线")
css = (BASE / "zhuiju" / "static" / "app.css").read_text(encoding="utf-8")
import re
root = css[css.index(":root {"):css.index("\n}", css.index(":root {"))]
body = css[css.index("\n}", css.index(":root {")):]
# 允许在变量定义里写死颜色（海报那一层就是不跟主题翻），不允许直接当属性值用在规则里
bad = [l.strip() for l in re.findall(r"[^\n]*#[0-9a-fA-F]{3,8}[^\n]*", body)
       if not l.strip().startswith("--")]
check("组件规则里没有写死的颜色（颜色一律从 MDUI 令牌来）", not bad, bad[:4])
check("三态各有选择器：亮 = 默认，暗 = 类，跟随系统 = 类 + 媒体查询",
      all(t in css for t in (":root, .mdui-theme-light {", ".mdui-theme-dark {",
                             "@media (prefers-color-scheme: dark) {", ".mdui-theme-auto {")), None)
# 桥接层：站点语义名（--surface…）全部指向 MDUI 令牌，只有海报那层例外（压在任意封面上）
bridge = dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", root))
off = {k for k, v in bridge.items()
       if re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", v) and "--mdui-" not in v}
check(":root 的颜色 token 全部桥到 --mdui-*（海报三层不跟主题翻是仅有的例外）",
      off <= {"--poster-ink", "--poster-line"}, sorted(off))
for pair in ("--mdui-color-success", "--mdui-color-warning"):
    check(f"补的语义色 {pair} 亮暗两边都有（MDUI 只规定了 error 这一组）",
          css.count(pair + "-light") >= 1 and css.count(pair + "-dark") >= 2, css.count(pair))
check("旧的手写主题属性没有残留（data-theme 属性、data-stage 舞台轴）",
      "[data-theme=" not in css and "data-stage" not in css, None)

for name in ("index.html", "admin.html", "human.html"):
    t = (BASE / "zhuiju" / "templates" / name).read_text(encoding="utf-8")
    check(f"{name} 用同一份主题装载（_theme.html），不各写一份", "_theme.html" in t)
    check(f"{name} 的主题装载在 app.css 之前（否则暗色用户刷新闪白）",
          t.index("_theme.html") < t.index("app.css"), None)
    if name != "human.html":
        check(f"{name} 有切换按钮并挂了 theme.js", "data-theme-toggle" in t and "theme.js" in t, None)
th = (BASE / "zhuiju" / "templates" / "_theme.html").read_text(encoding="utf-8")
# 注释里就写着 defer / CDN 这些词，所以只能查真正的属性写法与真正的引用写法
check("装载全在本地：不引外网、不 defer",
      "<script defer" not in th and 'src="http' not in th and 'href="http' not in th
      and "unpkg.com" not in th, None)
check("顺序：主题类 → mdui.css → mdui.global.js → 主色（页面的 app.css 排在后面）",
      # 注释里就把这几个名字提了一遍，所以只能比真正的标签写法
      th.index("classList.add('mdui-theme-'") < th.index("filename='vendor/mdui/mdui.css'")
      < th.index("filename='vendor/mdui/mdui.global.js'")
      < th.index("mdui.setColorScheme('#3566E6')"), None)
check("预置读 MDUI 那个键，非法值一律当跟随系统",
      "localStorage.getItem('mdui-theme')" in th
      and "if (t !== 'light' && t !== 'dark') t = 'auto';" in th, None)
check("主色在首帧生成（等加载完再改会先紫后蓝闪一下），bundle 没跑起来也不报错",
      "mdui.setColorScheme('#3566E6')" in th and "window.mdui &&" in th, None)
tj = (BASE / "zhuiju" / "static" / "theme.js").read_text(encoding="utf-8")
check("theme.js 三态循环，改的是 MDUI 的类",
      all(k in tj for k in ('"auto"', '"light"', '"dark"'))
      and 'classList.add("mdui-theme-"' in tj and 'classList.remove("mdui-theme-"' in tj, None)
check("选择记在 mdui-theme 键；写不了也不崩（无痕模式）",
      'KEY = "mdui-theme"' in tj and "setItem" in tj and "catch" in tj, None)
check("跟随系统那档实时跟着系统变（类名看不出来，必须问 matchMedia）",
      'addEventListener("change"' in tj or "addListener" in tj, None)
check("切换有回音：MDUI 的 snackbar；存不进去时不谎报已保存",
      "mdui.snackbar" in tj and "已保存 ·" in tj and "这台浏览器不给存" in tj, None)
check("首屏预置不走 apply，所以不会一进来就闪一遍渐变",
      "apply(" not in th.split("<script>")[0], None)

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

print("\n8) 令牌桥接体检：换主题只改 MDUI 的令牌，站点这层不藏颜色")
bridge8 = dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", root))
# 这几对是页面上真实存在的搭配。查的不是对比度数值 —— 那由 MDUI 加 setColorScheme 在运行时
# 决定，静态算不出来（实测在浏览器里量，数字记在 docs/theme.md）。这里查的是来源：
# 谁把某个 token 改回写死的十六进制，它就脱离主题系统，暗色下第一个坏掉的就是它
for fg, bg in (("--ink", "--surface"), ("--ink-2", "--surface-2"), ("--brand", "--brand-soft"),
               ("--ok", "--ok-bg"), ("--bad", "--bad-bg"), ("--warn", "--warn-bg"),
               ("--on-accent", "--brand"), ("--dim", "--surface")):
    check(f"{fg} / {bg} 都是从 MDUI 令牌派生的（不各自写死）",
          fg in bridge8 and bg in bridge8
          and "--mdui-" in bridge8[fg] and "--mdui-" in bridge8[bg],
          (bridge8.get(fg), bridge8.get(bg)))
check("海报上那层是例外：不跟主题翻（跟着 --on-accent 翻成近黑就成了黑压黑）",
      bridge8["--poster-ink"].startswith("rgb(255")
      and "mdui-color-scrim" in bridge8["--poster-scrim"],
      (bridge8.get("--poster-ink"), bridge8.get("--poster-scrim")))
VENDOR = BASE / "zhuiju" / "static" / "vendor" / "mdui"
check("vendored 的 MDUI 真的在仓库里（不引 CDN），并且记了版本号",
      (VENDOR / "mdui.css").stat().st_size > 1000
      and (VENDOR / "mdui.global.js").stat().st_size > 100000
      and re.match(r"^\d+\.\d+\.\d+$",
                   (VENDOR / "VERSION").read_text(encoding="utf-8").strip()) is not None, None)

gobtn = dict(re.findall(r"([a-z-]+)\s*:\s*([^;]+);",
                        re.search(r"\.gobtn \{([^}]*)\}", css).group(1)))
check("主按钮前景是 --on-accent 而不是语义色", "var(--on-accent)" in gobtn.get("color", ""),
      gobtn.get("color"))
field_input = dict(re.findall(r"([a-z-]+)\s*:\s*([^;]+);",
                              re.search(r"\.admfield input, \.admfield select \{([^}]*)\}",
                                        css).group(1)))
check("主按钮与输入框同一套圆角（都走 --r-pill，按钮一律药丸）",
      gobtn.get("border-radius") == field_input.get("border-radius") == "var(--r-pill)",
      (gobtn.get("border-radius"), field_input.get("border-radius")))
check("全站不再有第二种药丸写法（99px / 999px 那种硬编码已收干净）",
      "border-radius: 99px" not in css and "border-radius: 999px" not in css, None)
check("圆角与阴影取 MDUI 的 shape / elevation，不留自造的数",
      bridge8["--r-pill"].startswith("var(--mdui-shape")
      and bridge8["--r-l"].startswith("var(--mdui-shape")
      and bridge8["--shadow-s"].startswith("var(--mdui-elevation")
      and bridge8["--shadow-m"].startswith("var(--mdui-elevation"), None)
check("字号也走 MDUI 的 typescale（原来那套 11 / 11.5px 是自造的）",
      bridge8["--fs-min"].startswith("var(--mdui-typescale")
      and bridge8["--fs-sm"].startswith("var(--mdui-typescale")
      and bridge8["--fs-input"].startswith("var(--mdui-typescale"), None)
unified = re.search(r"\.pbtn, \.pager a, \.jumpbtn, \.themebtn, \.fbtn, \.frontbtn \{", css)
check("翻页/跳转/主题/筛选/回前台胶囊合并成一处定义", unified is not None)
check("主题切换渐变只在切换期间生效，时长取 MDUI 的 motion 令牌",
      ".theme-anim" in css and "prefers-reduced-motion" in css
      and "--mdui-motion-duration-medium2" in css, None)
check("没 JS 的浏览器上未注册的组件不露裸文本（:not(:defined) 那条）", ":not(:defined)" in css, None)
ajs3 = (BASE / "zhuiju" / "static" / "app.js").read_text(encoding="utf-8")
check("换成自定义元素后回车仍然提交表单（「回车即可」这句承诺不能落空）",
      "form.requestSubmit()" in ajs3 and "e.key !== 'Enter'" in ajs3, None)
check("进度条改喂 value（旧的 .progbar > i 百分比宽度随组件一起删了）",
      "setAttribute('value'" in ajs3 and "querySelector('.progbar" not in ajs3
      and "progbar" not in css, None)

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
check("内容宽度随屏走、有上限，上限走 --measure（不再写死一个数）",
      "min(var(--measure), 100% - 48px)" in wrap and "--measure: 1680px;" in root, wrap.strip())
check("前台收到阅读宽度，后台不吃这一档（数据表本来就要横向铺）",
      "body.home { --measure: 1280px; }" in css, None)
check("边框算在宽度内（不会溢出横向滚动）", "box-sizing: border-box" in wrap)
ladder = [(int(m.group(2)), m.group(1), int(m.group(3))) for m in
          re.finditer(r"@media \((min|max)-width: (\d+)px\)[^{]*\{\s*\.hotgrid \{ --hot-cols: (\d+)", css)]
check("宽屏补了列数，不会一行 6 张右边空一大片",
      {c for _, _, c in ladder} >= {9, 7, 5}, ladder)
wide = {c for _, kind, c in ladder if kind == "min"}
check("两条 min-width 断点互不重叠且都大于基础 6 列", wide == {9, 7} and min(wide) > 6, wide)

def detail_only(html):
    """只取 #detail 到 #geo 之间的片段。
    之前用 split("明细") 会被归属地那块注释里的"明细"两个字切到最后一段，取到的不是表格。
    按 <th>时间 定位也一样会跑偏：明细改了列，切过去可能量到归属地那张表的行。"""
    return html[html.index('id="detail"'):html.index('id="geo"')]


d2 = c.get("/admin").get_data(as_text=True)
dtail = detail_only(d2)
head = re.search(r"<thead><tr>(.*?)</tr>", dtail, re.S).group(1)
cols = re.findall(r"<th[^>]*>([^<]+)</th>", head)
check("明细有独立的系统列", "系统" in cols, cols)
check("系统列排在浏览器之后", cols.index("系统") == cols.index("浏览器") + 1, cols)
i_os = cols.index("系统")
row0 = re.search(r"<tbody>\s*<tr[^>]*>(.*?)</tr>", dtail, re.S).group(1)
cells = [re.sub(r"<[^>]+>", " ", x).strip() for x in
         re.findall(r"<td[^>]*>(.*?)</td>", row0, re.S)]
check("系统格里有真实系统名或未知", any(k in cells[i_os] for k in
      ("Windows", "macOS", "iOS", "Android", "Linux", "未知")), cells[i_os])
check("系统格可点筛选", f'/admin?os=' in re.search(r"<td[^>]*>(.*?)</td>",
      re.findall(r"<td[^>]*>.*?</td>", row0, re.S)[i_os], re.S).group(1))
check("筛选栏有系统输入框", 'name="os"' in d2)
check("按系统筛选能用", "macOS" in c.get("/admin?os=macOS").get_data(as_text=True))
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
# geo=CN 后面现在还会跟着 &tab=overview（页内链接都带当前标签），所以不能在参数末尾就要求 ">
pairs = re.findall(r'[?&]geo=([A-Z]{2})[^"]*">([^<]+)<', geo)
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
DATA_TABLES = ["日期", "关键词", "IP", "浏览器", "来源", "IP", "时间", "国家 / 地区"]
check("统计那八块表都包了滚动容器（按天/关键词/IP/浏览器/来源/行为特征/明细/归属地）",
      [t for _, t in folded][:8] == DATA_TABLES, [t for _, t in folded])
check("每块包的都是预期那张表（后面新增的区块排在它们之后，不参与这份对照）",
      [t for _, t in folded[:8]] == DATA_TABLES, [t for _, t in folded[:8]])
check("除了明细是 10 行，统计那八块都是 5 行（行为特征那节也折叠，别把首屏挤没）",
      [n for n, _ in folded[:8]] == ["5", "5", "5", "5", "5", "5", "10", "5"],
      [n for n, _ in folded])
check("后来加的任何一块（如 Emby STRM 那几块）也得照同一个规矩：包容器、写清 data-rows",
      len(folded) >= 8 and all(5 <= int(n) <= 10 for n, _ in folded),
      [(n, t) for n, t in folded[8:]])
# 表在滚动框里取自然宽度之后，行本身就不会被挤成竖排的字，不需要再逐列 nowrap
check("明细表没有残留的 .nw（那是被 width:100% 挤出来的补丁，现在从根上修了）",
      'class="nw"' not in ah and ".table .nw" not in css, ah.count('class="nw"'))
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
check("翻页不再把页面滚到明细顶部：整套 scrollIntoView 定位都删了",
      "scrollIntoView" not in ah and "scrollToDetail" not in ah, None)
# scroll-margin-top 又回来了，但服务对象不同：以前是给"翻页后把明细滚进视野"用的（那套已删），
# 现在是给侧边目录的锚点跳转用的 —— 没有它，点目录跳过去后标题会被顶部那排标签压住。
# 所以它必须只作用在正文块上（.adminmain [id]），不能又变成 #detail 的全局滚动避让
check("滚动避让只为目录锚点服务：写在正文块上，不给 #detail 单独留",
      ".adminmain [id] { scroll-margin-top: 56px; }" in css
      and "#detail { scroll-margin-top" not in css, None)
check("窗口变窄重算（折行变了会露半行），且做防抖",
      "resize" in js and "clearTimeout(foldT)" in js and "setTimeout(refold, 200)" in js)

print("\n11) 手机 / 平板：宽度还给内容、触摸目标、小字号 token")
# 这一节的每条断言都对应一次实测到的问题（360px 上净宽只剩 249px、标签被挤成 98px 高、
# 91 处文字小于 12px、22 个控件够不上拇指），别再退回去
idx_narrow = css.index("/* ---------------- 手机 / 平板")
tail = css[idx_narrow:]
check("窄屏覆盖排在文件最后（同优先度靠后者胜，写在中间等于没写）",
      idx_narrow > max(css.index(".themebtn {"), css.index(".dbtn {"),
                      css.index(".pbtn, .pager a"), css.index(".csite .ct")),
      idx_narrow)
check("小字号都走 MDUI 的 typescale，文件里不留硬编码的 11 / 11.5px",
      not re.search(r"font-size:\s*11(\.5)?px", css)
      and "--fs-min: var(--mdui-typescale-label-small-size)" in css
      and "--fs-sm: var(--mdui-typescale-label-medium-size)" in css,
      re.findall(r"font-size: 11[^;]*", css)[:3])
check("窄屏把两个小字号换成 body-small（仍然只引 typescale，不写死数）",
      "--fs-min: var(--mdui-typescale-body-small-size)" in tail
      and "--fs-sm: var(--mdui-typescale-body-small-size)" in tail, None)
check("桌面那份 .wrap 仍是 100% - 48px（窄屏是覆盖，不是改写）",
      "100% - 48px" in css[:idx_narrow])
check("窄屏 .wrap 整宽 + 只留 10px 内边距", "width: 100%; padding: 0 10px" in tail.replace("\n          ", " ")
      or ("width: 100%" in tail and "padding: 0 10px" in tail), re.findall(r"\.wrap \{[^}]*\}", tail))
check("标签条窄屏横滑，并且带 min-width:0",
      "overflow-x: auto" in tail and "min-width: 0" in tail, re.findall(r"\.tabs \{[^}]*\}", tail))
check("（这条是当初的坑）只写 overflow-x:auto 不够：flex 项默认 min-width:auto，"
      "四个不换行的标签会把文档顶宽，所以 max-width:100% 也得在",
      "max-width: 100%" in tail)
check("详情按钮在触屏上够按（32px 高、40px 宽起）",
      re.search(r"\.dbtn \{[^}]*min-height: 32px", tail) is not None
      and re.search(r"\.dbtn \{[^}]*min-width: 40px", tail) is not None,
      re.findall(r"\.dbtn \{[^}]*\}", tail))
check("片名是海报上唯一的进页面入口，给到 44px", ".hotlink { min-height: 44px; }" in tail)
check("剧集链接成块，不再是 19px 的行内链接",
      re.search(r"\.eps a \{[^}]*min-height: 34px", tail) is not None)
check("关掉点击灰底与双击缩放延迟", "-webkit-tap-highlight-color: transparent" in tail
      and "touch-action: manipulation" in tail)
# 输入框字号也必须走 token：媒体查询不加特异性，`.admfield input`（0,1,1）压着
# `input`（0,0,1），第一次只写了兜底那条，量出来后台口令框还是 12.5px —— iOS 一聚焦就放大整页
check("输入控件字号走 --fs-input，桌面就是 body-large（16px：iOS 聚焦不会放大整页）",
      "--fs-input: var(--mdui-typescale-body-large-size)" in css[:idx_narrow],
      re.findall(r"--fs-input[^;]*", css))
check("后台筛选框与翻页跳转框都吃这个 token",
      re.search(r"\.admfield input, \.admfield select \{[^}]*var\(--fs-input\)", css) is not None
      and re.search(r"\.jumpin \{[^}]*var\(--fs-input\)", css) is not None,
      re.findall(r"\.admfield input[^{]*\{[^}]*\}", css)[:1] + re.findall(r"\.jumpin \{[^}]*\}", css)[:1])
check("文件里不再有硬编码的 12.5px 输入框字号",
      not re.search(r"\.(admfield input|jumpin)[^}]*?font-size: 12\.5px", css, re.S))
# .cols 收成单列后，网格项默认 min-width:auto 会顶在长命令上不肯缩，撑宽的是整个文档
check("窄屏网格项允许缩到 0（否则一长串命令就把页面顶得能横着拖）",
      ".cols > * { min-width: 0; }" in tail and ".asect { min-width: 0; }" in tail,
      re.findall(r"\.(cols > \*|asect) \{[^}]*\}", tail))
check("长命令用 overflow-wrap:anywhere 断行（break-word 不参与 min-content，等于没断）",
      re.search(r"\.atip[^{]*code[^{]*\{[^}]*overflow-wrap: anywhere", tail) is not None
      or "overflow-wrap: anywhere" in tail, re.findall(r"[^}]*overflow-wrap: anywhere[^}]*\}", tail))
check("表格、翻页、说明文字与网盘站卡片里的链接都用「内边距 + 等量负外边距」撑高，不改变行高",
      re.search(r"\.table a, \.pager a, \.atip a, \.creason a \{"
                r" padding: (\d+)px 3px; margin: -\1px -3px; \}", tail) is not None,
      re.findall(r"\.table a[^;]*;[^;]*;", tail))
check("提交按钮的文字不许折行（320 上「进入」被 flex 压成 42×51 的两行）",
      re.search(r"\.gobtn[^{]*\{[^}]*white-space: nowrap", tail) is not None,
      re.findall(r"\.gobtn[^}]*\}", tail))
# 手机（≤560）登录改成各占一整行；平板与窄桌面窗口（561+）仍是横排 —— 360 上卡片内宽 293 本来就放得下
lg = re.search(r"@media \(max-width: 560px\) \{(.*?)\n\}", css[idx_narrow:], re.S)
check("≤560 登录各占一整行（输入框吃满、按钮 40px 高）",
      lg is not None and ".loginform { flex-wrap: wrap; }" in lg.group(1)
      and re.search(r"\.loginform \.gobtn \{ flex: 1 1 100%; min-height: 40px", lg.group(1)) is not None
      and re.search(r"\.loginform \.admfield input \{ width: 100%[^}]*box-sizing: border-box", lg.group(1)) is not None,
      lg.group(1) if lg else None)
check("登录整宽只写在 ≤560 这一段（561 以上卡片内宽够横排，不该竖着）",
      css.count(".loginform { flex-wrap: wrap; }") == 1
      and lg is not None and ".loginform { flex-wrap: wrap; }" in lg.group(1),
      css.count(".loginform { flex-wrap: wrap; }"))
check("它排在 .pwrow 那条之后、且在文件末尾（覆盖必须靠后）",
      lg is not None and css.index("@media (max-width: 560px) {\n  .loginform") > css.index(".pwrow { flex-wrap: wrap; }"))
check("结果没回来之前那份给爬虫的 SSR 列表也按得准（行内链接撑到 34px）",
      re.search(r"\.ssrlist a \{ display: inline-block; padding: (\d+)px 3px; margin: -\1px -3px; \}", tail) is not None,
      re.findall(r"\.ssrlist a[^}]*\}", tail))
sheet = re.search(r"@media \(max-width: 560px\) \{(.*?)\n\}", css, re.S).group(1)
check("手机上面板是底部抽屉（贴左右下 + 限高 + 从下面推上来）",
      "bottom: 0" in sheet and "left: 0" in sheet and "right: 0" in sheet
      and "translateY(" in sheet and "86vh" in sheet, sheet)
check("抽屉躲开 iPhone  home indicator", "env(safe-area-inset-bottom)" in css)
idxh = (BASE / "zhuiju" / "templates" / "index.html").read_text(encoding="utf-8")
check("viewport 带 viewport-fit=cover（不然 env() 恒为 0）", "viewport-fit=cover" in idxh)
ajs = (BASE / "zhuiju" / "static" / "app.js").read_text(encoding="utf-8")
check("触屏上整张海报都是命中区，桌面仍只认那颗按钮",
      "(hover: none)" in ajs and ".hcover, .cover, .dbtn" in ajs,
      re.findall(r".*hover: none.*", ajs))
check("点过的标签会被带进视野（横滑时不会点到看不见的标签）",
      "scrollIntoView({ block: 'nearest', inline: 'nearest' })" in ajs)
check("没有任何地方劫持右键", "contextmenu" not in ajs and "contextmenu" not in idxh)

print("\n13) 版式重构：药丸、留白节奏、终端化数据")
def _rule(head):
    i = css.find(head)
    if i < 0:
        return None
    return css[i:css.index("\n}", i) + 2]


# 按钮一律药丸：混着 8px / 5px / 99px 就是"每张卡片各圆各的"，看着像没设计过
PILL_HEADS = [".gobtn {", ".srcbtn {", ".eps a {",
              ".pbtn, .pager a, .jumpbtn, .themebtn, .fbtn, .frontbtn {",
              ".reset {", ".admintoc a {", ".row .ct {", ".csite .ct {",
              ".who {", ".behflag {", ".dbtn {", ".pstep {", ".ver {",
              '.admfield input, .admfield select {',
              '.loginform input[type="password"], .loginform input[type="text"] {',
              ".tab {", ".asec-fold > summary {"]
noPill = [h for h in PILL_HEADS if (h and "border-radius: var(--r-pill);" not in _rule(h))]
check("按钮/输入框/标签一律药丸（同一个圆角只有 --r-pill 一个来源）",
      not noPill and "border-radius: 99px" not in css and "border-radius: 999px" not in css,
      noPill[:4])
# 数据与状态是"机器说的话"：等宽才对齐，一列数字用比例字体会跳
MONO_HEADS = [".meta {", ".fresh {", ".stat b {", ".table .num {", ".pageof {",
              ".slip-msg {", ".cloudbar {", ".progsteps {", ".eps a {", "code {"]
noMono = [h for h in MONO_HEADS if h in css and "var(--mono)" not in _rule(h)]
check("数字与状态行走等宽（表格数字、进度步骤、滑块回话、meta 那一行）",
      not noMono and all(h in css for h in MONO_HEADS), noMono[:4])
lit_fonts = [l.strip() for l in css.splitlines()
             if l.strip().startswith("font-family:") and "var(--" not in l]
check("字体只从 token 取：规则里没有写死的字体族（材质归调色板，结构归组件）",
      not lit_fonts, lit_fonts[:3])
for tok in ("--font-display", "--font-body", "--mono", "--head-track", "--label-track",
            "--r-pill", "--r-cover", "--cover-frame", "--btn-glow", "--btn-edge", "--prog-fill"):
    check(f"{tok} 在 :root 里有默认值（不写也能跑，只有 MDUI 令牌是必须的）", f"  {tok}:" in root, None)
check("海报的镜框线走 --cover-frame，三处海报（结果卡、猜你想搜、详情面板）都吃同一个 token",
      bridge["--cover-frame"] == "var(--mdui-elevation-level1)"
      and all("box-shadow: var(--cover-frame);" in _rule(h)
              for h in (".cover {", ".hcover {", ".dpcover {")), None)
check("卡片留白与海报尺寸一起放大，手机端再收回来（360 屏上文字区不能被吃掉）",
      "padding: 18px 20px;" in _rule(".card {") and "gap: 20px;" in _rule(".card {")
      and "flex: 0 0 104px;" in _rule(".cover {")
      and ".card { padding: 14px 16px; gap: 14px; }" in css
      and ".cover { flex-basis: 96px; width: 96px; }" in css, None)
check("表头是拉开字距的栏目名，正文数字用 tabular-nums",
      "letter-spacing: var(--label-track);" in _rule(".table th {")
      and "font-variant-numeric: tabular-nums;" in _rule(".table {"), None)
check("跑着的状态行有一枚闪烁光标，且 reduced-motion 下停住",
      '.fresh[data-state="running"]::after {' in css and "@keyframes caret" in css
      and '.fresh[data-state="running"]::after { animation: none; }' in css, None)
check("口令框不再是浏览器默认方框（和旁边的药丸按钮穿帮）",
      _rule('.loginform input[type="password"], .loginform input[type="text"] {') is not None
      and "padding: 10px 18px;" in _rule('.loginform input[type="password"], .loginform input[type="text"] {'), None)

print("\n14) 栅格：舞台在左、资料栏在右（只在够宽且真有结果时）")
idx = (BASE / "zhuiju" / "templates" / "index.html").read_text(encoding="utf-8")
grid_css = css[css.index("@media (min-width: 1220px) {"):css.index(".railhead {")]
check("栅格只在前台 + 搜索过那一屏启用（落地页右边会空一大块，所以不用）",
      "body.home.searched main.wrap {" in grid_css
      and "grid-template-columns: minmax(0, 1fr) var(--rail);" in grid_css, None)
check("舞台入口与标签行横跨两栏，结果在左、资料栏在右并粘性跟随",
      "main.wrap > .searchbar,\n  body.home.searched main.wrap > .statline { grid-column: 1 / -1; }" in grid_css
      and "main.wrap > .panel { grid-column: 1; }" in grid_css
      and "main.wrap > .rail { grid-column: 2; position: sticky; top: 84px; }" in grid_css, None)
check("切到网盘 / 目录标签时资料栏收掉（写在媒体查询之外，任何宽度都成立）",
      css.index('body.home:not([data-tab="vod"]) .rail { display: none; }')
      < css.index("@media (min-width: 1220px) {")
      and 'body.home.searched:not([data-tab="vod"]) main.wrap > .panel { grid-column: 1 / -1; }' in css,
      None)
check("模板第一帧就写好 home / searched / data-tab，不靠 JS 补（否则 SSR 那一屏会先排错再跳）",
      '<body class="home{% if seo.kw %} searched{% endif %}" data-tab="vod">' in idx, None)
check("接口状态从 #panel-vod 搬到资料栏，摘要也在同一栏里（旧位置不留一份）",
      idx.index('<aside class="rail"') < idx.index('id="ssr"') < idx.index('id="sources"')
      and idx.count('id="sources"') == 1 and idx.count('id="ssr"') == 1, None)
ajs2 = (BASE / "zhuiju" / "static" / "app.js").read_text(encoding="utf-8")
check("搜索 / 回主页 / 切标签都跟着改 body 上的那两个开关",
      'document.body.classList.toggle("searched", !!kw)'.replace('"', "'") in ajs2
      or "document.body.classList.toggle('searched', !!kw)" in ajs2, None)
check("goHome 摘掉 searched，switchTab 把当前标签写到 body",
      "document.body.classList.remove('searched')" in ajs2
      and "document.body.dataset.tab = tab;" in ajs2, None)
check("接口状态一行一个源：名字 / 命中数 / 耗时 三段，数字右对齐走等宽",
      'grid-template-columns: 7px minmax(0, 1fr) auto 52px;' in css
      and "font-variant-numeric: tabular-nums;" in css
      and 'class="sb-name"' in ajs2 and 'class="sb-num"' in ajs2 and 'class="sb-ms"' in ajs2, None)
check("顶上给一句汇总（几个可用、最慢多少），一个源都没答话时整块收起",
      "可用 · 最慢" in ajs2 and "box.hidden = !st.length" in ajs2, None)
check("后台不吃前台的阅读宽度（body 上没有 home）",
      '<body data-tab="{{ tab or ' in (BASE / "zhuiju" / "templates" / "admin.html").read_text(encoding="utf-8"), None)

check("窄屏没有右栏时接口状态仍排在结果上面（翻完一百张卡片才看到它，等于没有）",
      "@media (max-width: 1219.98px) {" in css
      and "body.home main.wrap > .rail { display: contents; }" in css
      and "body.home main.wrap > .rail > .railcard { order: -1; }" in css, None)
check("接口状态那块默认 hidden：没搜过就不留一张空卡片在页面上",
      '<div class="railcard" id="rail-sources" hidden>' in idx
      and "box.hidden = !st.length" in ajs2, None)

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
