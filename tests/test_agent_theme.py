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

print("\n6) 主题：前后台共用一个 heroui-theme（壳里首帧脚本 + theme.js 的无框架三态）")
css = (BASE / "zhuiju" / "static" / "app.css").read_text(encoding="utf-8")
import re
root = css[css.index(":root {"):css.index("\n}", css.index(":root {"))]
# (b) 这一节原来读 static/app.css 的 MDUI 令牌桥、_theme.html 里的 mdui.css / mdui.global.js /
#     setColorScheme / localStorage('mdui-theme')，以及 theme.js 的 mdui-theme- 类与 mdui.snackbar。
#     MDUI 整个退出：_theme.html 换成 HeroUI 的 spa/app.css + heroui-theme 键，theme.js 是无框架版
#     useTheme；index.html、human.html 已不上屏、后台也走 admin_shell.html。原来那十几条按新机制合并重钉：
#     壳与首帧脚本共用同一个键/同一对 <html> 属性/装在样式前/不引外网，theme.js 三态 + 跟随系统直读 matchMedia。
sh = (BASE / "zhuiju" / "templates" / "shell.html").read_text(encoding="utf-8")
ash = (BASE / "zhuiju" / "templates" / "admin_shell.html").read_text(encoding="utf-8")
th = (BASE / "zhuiju" / "templates" / "_theme.html").read_text(encoding="utf-8")
tj = (BASE / "zhuiju" / "static" / "theme.js").read_text(encoding="utf-8")
# (a) 前后台共用一份偏好：两个壳 + 登录兜底页 include 的 _theme.html 都读同一个 localStorage 键。
check("前后台读同一个主题键（shell.html、admin_shell.html、_theme.html 都是 heroui-theme）",
      all("localStorage.getItem('heroui-theme')" in t for t in (sh, ash, th)), None)
# (a) 旧版写的是 mdui-theme- 那一串类；新机制三处都写同一对 <html> 属性（class + data-theme）。
check("三处都写同一对 <html> 属性（class 上加生效档、data-theme 同值），切一次两边一起翻面",
      all("d.classList.add(r);" in t and "d.setAttribute('data-theme', r);" in t
          for t in (sh, ash, th)), None)
check("首帧脚本装在页面样式之前（否则暗色用户刷新会先白一下）",
      sh.index("localStorage.getItem('heroui-theme')") < sh.index("filename='spa/app.css'")
      and ash.index("localStorage.getItem('heroui-theme')") < ash.index("filename='spa/app.css'")
      and th.index("localStorage.getItem('heroui-theme')") < th.index("filename='spa/app.css'"), None)
check("装载全在本地：不引外网、不 defer",
      'src="http' not in sh.split("</head>")[0] and "unpkg" not in th
      and "<script defer" not in th and "mdui" not in th, None)
# (a) theme.js 是无框架版三态：system/light/dark 循环，改的还是同一对 <html> 属性（不再是 mdui-theme-）。
check("theme.js 三态循环，改的是同一对 <html> 属性（不再是 mdui-theme- 那套）",
      all(k in tj for k in ('"system"', '"light"', '"dark"'))
      and "root.classList.add(r)" in tj and 'root.setAttribute("data-theme", r)' in tj
      and "mdui-theme-" not in tj, None)
check("选择记在 heroui-theme 键；写不了也不崩（无痕模式）",
      'KEY = "heroui-theme"' in tj and "setItem" in tj and "catch" in tj, None)
# 这条钉的是刚修的真 bug：解析"跟随系统"时必须直接问 matchMedia，不能经由 stored()/applied()。
# 旧写法在 write 里用 applied()（= resolve(stored())），而调用 write 时 localStorage 还是上一个选择，
# 于是"跟随系统"被解析成切换前的旧值 —— 现象就是按钮说"亮色"、页面还黑着。write 里留着这条注释与
# 正确写法 var r = resolve(mode)；判据钉"直接赋值 resolve(mode) + 绝不出现 var r = applied()"。
m_resolve = tj[tj.index("function resolve"):tj.index("function applied")]
check("跟随系统那档在写属性之前直接问 matchMedia，不绕 applied()/stored()（避免读到切换前的旧值）",
      "var r = resolve(mode);" in tj and "matchMedia(\"(prefers-color-scheme: dark)\")" in m_resolve
      and "不能用 applied()" in tj and "var r = applied()" not in tj, None)
check("系统偏好变了实时跟着改，但只动跟随系统那一档（手动锁了亮暗不许被翻面）",
      ('addEventListener("change"' in tj or "addListener" in tj)
      and 'stored() === "system"' in tj, None)

print("\n7) 后台页面真的把两列渲染出来了（后台已转 React：数据在 view，列在组件里）")
cfg = admin_mod.load()
admin_mod.save({"password": "ce-shi-mi-ma", "secret_key": cfg["secret_key"], "password_is_temp": False})
from zhuiju.app import create_app  # noqa: E402

# (a) 原来这一节 grep /admin 那页 HTML 的表头/面板/筛选控件。后台转 React 后：明细列由 Detail.tsx 的
#     表头数组定义、聚合面板由 Overview.tsx 的 Block 定义、筛选项在 Filters.tsx；数据在 /api/admin/view。
#     csrf 也从 view 的 401 body 拿，不再从 HTML 里正则抠。
AD = BASE / "web" / "src" / "admin"
detail_ts = (AD / "Detail.tsx").read_text(encoding="utf-8")
overview_ts = (AD / "Overview.tsx").read_text(encoding="utf-8")
filters_ts = (AD / "Filters.tsx").read_text(encoding="utf-8")
c = create_app().test_client()
tok = c.get("/api/admin/view").get_json()["csrf"]
c.post("/admin/login", data={"csrf": tok, "password": "ce-shi-mi-ma"})
dv = c.get("/api/admin/view?tab=detail").get_json()
check("明细表头有浏览器列", '"浏览器"' in detail_ts, None)
check("明细表头有来源页列", '"来源页"' in detail_ts, None)
check("有浏览器分布面板（那个块的标题就是「浏览器 / 设备」）",
      'id="agents" title="浏览器 / 设备"' in overview_ts, None)
# (c) 来源面板判据仍成立，锚点从旧标题「来源页（对方从哪来）」换成组件里实际的块标题「来源页」。
check("有来源分布面板（块标题是「来源页」，那段括注老文案没进 SPA）",
      'id="refs" title="来源页"' in overview_ts, None)
check("筛选表单有浏览器与来源控件（browser 是文本项、ref_kind/device 是下拉项）",
      '["browser", "浏览器", "text"]' in filters_ts and '["ref_kind", "来源类型"' in filters_ts
      and '["device", "设备"' in filters_ts, None)
# (b) 旧页脚那两句关于 Referer 与 UA 的散文本来只在退役的 admin.html 里；移植时确实丢了，
#     现在按原意补回活的那两处：Referer 的限制挂在「来源页」那一栏下面，UA 不可全信挂在行为特征那一栏。
check("来源页那一栏写明了 Referer 的限制（能给多少由 Referrer-Policy 决定，拿不到就不编）",
      "Referrer-Policy" in overview_ts and "拿不到就不编" in overview_ts
      and "直接访问" in overview_ts and "分不开" in overview_ts, None)
check("页脚说明了 UA 可伪造（明细/行为那块把 UA 只当提示、不当身份）",
      "判读只是提示，不是判决" in detail_ts
      and "UA 是客户端自由发挥" in detail_ts, None)
bv = c.get("/api/admin/view?browser=" + "Edge 124.0").get_json()
check("按浏览器筛选后仍 200，且回填到条件里",
      c.get("/api/admin/view?browser=" + "Edge 124.0").status_code == 200
      and bv["flt"]["browser"] == "Edge 124.0", bv["flt"].get("browser"))
rv = c.get("/api/admin/view?ref_kind=site").get_json()
check("按来源类型筛选正常", rv["flt"]["ref_kind"] == "site", rv["flt"].get("ref_kind"))
rv2 = c.get("/api/admin/view?ref_kind=bogus").get_json()
plain = c.get("/api/admin/view").get_json()
check("非法来源类型当没填（结果没被筛成空，与不填同一条 SQL 口径）",
      rv2["rows"]["total"] == plain["rows"]["total"] and rv2["rows"]["total"] >= 1,
      (rv2["rows"]["total"], plain["rows"]["total"]))

print("\n8) 令牌桥接体检：换主题只改主题令牌，站点这层不藏颜色（活的那份在 web/src/styles.css）")
# (a) 顺带：app.css 现在只剩登录兜底页在用，后台/前台主体配色已走 web/src/styles.css + HeroUI 令牌。
#     原来从 app.css 读调色板算对比来源的这套体检，一半按新令牌重钉（app.css 现在桥的是 HeroUI 令牌），
#     一半搬到真正活着的 styles.css（.who-* / .num / --foreground/--muted/--surface 配对）。
styles_css = (BASE / "web" / "src" / "styles.css").read_text(encoding="utf-8")
# 后台主体也搬进 React 了，这一节与后面的宽度一节都要照着它查（AdminApp.tsx）
adminapp_tsx = (BASE / "web" / "src" / "admin" / "AdminApp.tsx").read_text(encoding="utf-8")
bridge8 = dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", root))
# 这几对是页面上真实存在的搭配。查的不是对比度数值 —— 那由主题令牌在运行时决定、静态算不出来。
# 查的是来源：谁把某个 token 改回写死的十六进制，它就脱离主题系统，暗色下第一个坏掉的就是它。
# (c) 判据不变（成对语义 token 都从主题令牌派生、不各自写死），锚点从 --mdui- 换成 HeroUI：
#     app.css 现在把 --ink 等桥到 var(--foreground)/var(--muted)/var(--accent) 这串 HeroUI 令牌。
for fg, bg in (("--ink", "--surface"), ("--ink-2", "--surface-2"), ("--brand", "--brand-soft"),
               ("--ok", "--ok-bg"), ("--bad", "--bad-bg"), ("--warn", "--warn-bg"),
               ("--on-accent", "--brand"), ("--dim", "--surface")):
    check(f"{fg} / {bg} 都是从主题令牌派生的（不各自写死）",
          fg in bridge8 and bg in bridge8
          and "var(--" in bridge8[fg] and "var(--" in bridge8[bg],
          (bridge8.get(fg), bridge8.get(bg)))
# (c) 海报那层仍是仅有的例外、不跟主题翻；只是写死的值从 rgb(255..) 变成 #fff、scrim 从 mdui-color-scrim
#     变成写死的 rgba —— 判据"它不引主题令牌、是硬编码"原样成立，锚点换了。
check("海报上那层是例外：不跟主题翻（硬编码，不引 --foreground 那套令牌）",
      not bridge8["--poster-ink"].startswith("var(")
      and not bridge8["--poster-scrim"].startswith("var("),
      (bridge8.get("--poster-ink"), bridge8.get("--poster-scrim")))
# (b) 这一条原来钉的是"vendored 的 MDUI 在仓库里且不引 CDN"。MDUI 整个退出后，仓库里只剩几个
#     没人引用的死文件（见 docs/frontend.md 那份清单），继续钉它等于给死代码上保险 ——
#     判据反过来：所有还会上屏的表面（两个壳、_theme.html、两份 CSS、theme.js、React 源码）里
#     一处 mdui 都不许剩，否则说明有东西还在偷偷引它。
LIVE = [sh, ash, th, css, styles_css, tj] + [
    p.read_text(encoding="utf-8") for p in (BASE / "web" / "src").rglob("*.ts*")]
check("MDUI 在所有还会上屏的表面里一处不剩（不引它、也不给它留引用）",
      not [w for t in LIVE for w in re.findall(r"mdui[\w.-]*", t)],
      sorted({w for t in LIVE for w in re.findall(r"mdui[\w.-]*", t)})[:4])
check("--surface 这一档不在 app.css 里桥：HeroUI 自己就叫这个名字，写自引用会被判成循环、"
      "整个变量空掉（现象是后台卡片全透明）",
      not re.search(r"^\s*--surface\s*:", root, re.M)
      and "var(--surface-secondary)" in root and "var(--surface-tertiary)" in root,
      re.findall(r"--surface[a-z0-9-]*\s*:\s*[^;]+", root))
check("圆角写死 px：Tailwind v4 会把没用到的 --radius-* 从产物里剔掉，引用它得到空值（卡片角全变直角）",
      all(re.match(r"^\s*\d+px$", bridge8.get(k, "")) for k in ("--r-cover", "--r-m", "--r-l", "--r-pill"))
      and not re.findall(r"border-radius:\s*var\(--radius", css),
      {k: bridge8.get(k) for k in ("--r-cover", "--r-m", "--r-l", "--r-pill")})

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
# (a) "圆角/阴影/字号不各自写死" 的活体检搬到 styles.css：后台那几档真人/脚本徽章（.who-*）全部引
#     HeroUI 状态令牌、数字 .num 走 --font-mono、页面前景底色引 --foreground/--background —— 谁改回硬编码
#     颜色就脱离主题系统。（app.css 那份 radius 现在是登录兜底页的硬编码 999px，不再作为"取主题令牌"的判据。）
who_rules = re.findall(r"\.who-[a-z][^{]*\{([^}]*)\}", styles_css)
check("后台 .who-* 徽章全部从 HeroUI 状态令牌派生（不各自写死颜色）",
      who_rules and all(("var(--" in r or "color-mix" in r) for r in who_rules), who_rules)
check("数字 .num 走等宽令牌并 tabular-nums（一列数字对得齐）",
      "--font-mono" in styles_css and "tabular-nums" in styles_css
      and re.search(r"\.num \{[^}]*--font-mono", styles_css) is not None, None)
check("页面前景/底色都引 HeroUI 的 foreground/background 令牌",
      "var(--foreground)" in styles_css and "var(--background)" in styles_css, None)
# (a) 「胶囊合并成一处定义」原来钉的是 app.css 里那条联合选择器（.pbtn/.pager a/.jumpbtn…）。
#     那批类随旧前端一起不上屏了；React 这边药丸是 Tailwind 的 rounded-full，
#     判据换成"活表面上只允许这一种药丸写法"：既没有 rounded-[...] 那种临时半径，
#     app.css 里也只剩登录兜底页那一处在引 var(--r-pill)。
react_ts = "".join(p.read_text(encoding="utf-8")
                   for p in sorted((BASE / "web" / "src").rglob("*.tsx")))
check("药丸只有一种写法：React 侧一律 rounded-full，没有临时半径；app.css 的联合胶囊规则已退役",
      react_ts.count("rounded-full") > 10 and "rounded-[" not in react_ts
      and "border-radius: 99px" not in css and "border-radius: 999px" not in css,
      (react_ts.count("rounded-full"), re.findall(r"rounded-\[[^\]]*\]", react_ts)[:3]))
# (c) 主题切换只在那 0.3s 里过渡、reduced-motion 下停住 —— 判据不变；时长不再取 MDUI 的 motion 令牌，
#     改成 styles.css 里写死的 0.3s（活的那份），所以锚点从 --mdui-motion-… 搬到 styles.css 的 .theme-anim。
check("主题切换渐变只在切换期间生效、且 reduced-motion 下不拖慢",
      ".theme-anim" in styles_css and "prefers-reduced-motion" in styles_css
      and "0.3s" in styles_css, None)
# (b) :not(:defined) 是给 MDUI 那批自定义元素兜底（没注册的组件不露裸文本）；MDUI 整个退出、前台换成 React
#     组件树，没有自定义元素可"未注册" —— 这条在新架构没有原样载体。等价那半：活 CSS 里对 reduced-motion
#     的收口仍在（不再需要 :not(:defined)）。
check("没有自定义元素需要 :not(:defined) 兜底了（MDUI 退出；a11y 收口改由 reduced-motion 那条守）",
      ":not(:defined)" not in styles_css and "prefers-reduced-motion" in styles_css, None)
# (b) 这两条钉的是 static/app.js 里的回车提交与进度条喂 value。app.js 已不上屏：
#     「回车即查」在 React 是 SearchBar 的 onSubmit（禁 JS 时由壳里那张原生 GET 表单接手，
#     回车本来就是浏览器的行为）；进度条在 React 是 .bar-run（跑着的那道）与 HeroUI 的 ProgressBar。
sb = (BASE / "web" / "src" / "components" / "SearchBar.tsx").read_text(encoding="utf-8")
ah = (BASE / "zhuiju" / "templates" / "admin.html").read_text(encoding="utf-8")
check("回车仍然提交（React 走 form onSubmit，禁 JS 那份是原生 <form method=get>，都不靠脚本补）",
      "onSubmit={(e) => {" in sb and 'e.preventDefault()' in sb
      and '<form method="post" action="{{ url_for(\'admin_login\') }}" class="loginform">' in ah, None)
check("进度条不再靠 app.js 喂 value：跑着的那道是 CSS 的 .bar-run，定量那道是 HeroUI ProgressBar",
      ".bar-run" in styles_css and "bar-slide" in styles_css and "progbar" not in css
      and "<ProgressBar" in react_ts, None)
# 条外面那个 3px 槽位必须常驻。写成 {pending ? <div className="bar-run"/> : null} 的旧样子，
# 条一出现就把 sticky header 撑高 3px，下面整页跟着往下跳一格 —— 表格正读着的时候最明显。
check("后台进度条先占位再出现：3px 槽位常驻，pending 时只往槽里放条，页面不跟着跳",
      re.search(r'<div className="h-\[3px\]">\s*\{pending \? \(\s*'
                r'<div className="bar-run"', adminapp_tsx) is not None, None)

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
# (a) 这一段原来全在 grep app.css 的 .wrap / --measure / .hotgrid 那三条媒体查询。
#     前台转 React 后"内容宽度"落在 Tailwind 类上（App.tsx 的 max-w-[1440px] + px-4/sm:px-6），
#     猜你想搜的列数阶梯落在 HotSection 的 grid-cols-* 上；后台那张宽表吃的是另一档（1680px）。
#     判据按这三处重钉：随屏走、有上限、前后台不同档、宽屏补列数。
import pathlib as _pl
app_tsx = _pl.Path(BASE / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
hot_tsx = _pl.Path(BASE / "web" / "src" / "components" / "HotSection.tsx").read_text(encoding="utf-8")
check("内容宽度随屏走、有上限：前后台同一档 1680，边距随屏给（不再写死一个数）",
      app_tsx.count("max-w-[1680px]") == 3 and "max-w-[1680px]" in adminapp_tsx
      and "px-4 sm:px-6" in app_tsx, app_tsx.count("max-w-[1680px]"))
check("前后台不再各用一档宽度（统一 1680，后台那张宽表也放得下）",
      "max-w-[1440px]" not in app_tsx + adminapp_tsx, None)
# (b) 旧那条"box-sizing: border-box"是给 .wrap 手写内边距兜底的，Tailwind 的 preflight 全站统一给了。
#     等价的新坑是栅格项默认 min-width:auto 顶在长内容上把整页撑宽 —— 前台靠 minmax(0,1fr)，
#     后台靠 min-w-0，两处都要在
check("栅格项允许缩到 0（长内容不会把整页顶得能横着拖）：前台 minmax(0,1fr)、后台 min-w-0",
      "minmax(0,1fr)" in app_tsx and "min-w-0" in adminapp_tsx, None)
# (b) 原来"宽屏补列数"钉的是 HotSection 的 grid 阶梯。现在整行横着滚、不按断点重排：
#     一颗宽度 31%（手机三颗）且有 176px 上限，宽屏靠多露几颗而不是把海报摊成墙。
check("猜你想搜是一条横滚条，不按断点重排：每颗 31% 起、上限 176px，宽屏自然多露几颗",
      'className="scroll-thin snap-x flex gap-4 overflow-x-auto pb-1"' in hot_tsx
      and 'const CELL = "w-[31%] min-w-[104px] max-w-[176px] shrink-0 snap-start";' in hot_tsx
      and "const BATCH = 12;" in hot_tsx, None)
check("横滚条只看右侧哨兵（root 是条本身，rootMargin 只往右放 260px），左端不会误触发补数",
      'root: el, rootMargin: "0px 260px 0px 0px"' in hot_tsx
      and 'aria-label={`把${label}往回滚`}' in hot_tsx
      and 'aria-label={`把${label}往后滚`}' in hot_tsx, None)

# (a) 明细表的列、系统格筛选这些原来 grep /admin 渲染出的 <th>/<td>。转 React 后：列顺序在 Detail.tsx
#     的表头数组里、每一行的系统与归属地在 view 的 rows.items 上、可点筛选是 filterUrl({ os })。逐条搬。
heads = re.findall(r'head=\{\[(.*?)\]\}', detail_ts, re.S)
detail_head = next((hd for hd in heads if "浏览器" in hd and "系统" in hd), "")
cols = re.findall(r'"([^"]+)"', detail_head)
check("明细有独立的系统列", "系统" in cols, cols)
check("系统列排在浏览器之后", cols.index("系统") == cols.index("浏览器") + 1, cols)
dv9 = c.get("/api/admin/view?tab=detail").get_json()
check("系统格里有真实系统名或未知（数据在 rows.items 的 os 上）",
      any((it.get("os") or "") in ("Windows 10/11", "macOS", "iOS 17.4", "Linux", "未知")
          or not it.get("os") for it in dv9["rows"]["items"]),
      [it.get("os") for it in dv9["rows"]["items"]][:4])
# (b) 旧版把明细行里的系统格做成一个 /admin?os= 的可点链接；React 的系统列是随行渲染的纯文本，
#     筛系统改走筛栏的 os 输入框 / filterUrl 那套通用"点一下加一个条件"的机制（服务端 flt 认 os 这键）。
check("系统仍是可筛的一等条件（行里有这一列、服务端 flt 也认 os 这个键）",
      "系统" in cols and "os" in dv9["flt"], None)
check("筛选栏有系统输入框", '["os", "系统", "text"]' in filters_ts, None)
check("按系统筛选能用（结果里确实有 macOS 那一行）",
      any((it.get("os") or "") == "macOS" for it in
          c.get("/api/admin/view?os=macOS").get_json()["rows"]["items"]), None)
check("按系统前缀也能筛（输 Win 命中 Windows 10/11）",
      any((it.get("os") or "") == "Windows 10/11" for it in
          c.get("/api/admin/view?os=Win").get_json()["rows"]["items"]), None)
bogus9 = c.get("/api/admin/view?os=" + "x' OR 1=1").get_json()
check("填了不存在的系统值就给明确的空态，而不是假装没筛",
      bogus9["rows"]["items"] == [] and "这个条件下没有记录" in detail_ts, None)
check("注入串被当普通字符串比对，表还在",
      stats_mod.list_queries({})["total"] > 0 and c.get(
          "/api/admin/view?os=" + "x' OR 1=1").status_code == 200, None)
geo9 = c.get("/api/admin/view?tab=overview").get_json()["agg"]["by_geo"]
# (a) 归属地列表原来从 /admin 的 geotbl 抓 <a ...>国名</a>；转 React 后国家行来自 agg.by_geo 的 country，
#     两字 ISO 才出完整国名、省市只留在明细那一列。表头"国家 / 地区"是 Overview.tsx 里那张表的列名。
check("归属地列表只显示国家，不带省市运营商",
      all(("省" not in (g["country"] or "") and "市" not in (g["country"] or ""))
          for g in geo9 if g["iso"]), [(g["iso"], g["country"]) for g in geo9 if g["iso"]])
check("国家名取自库里那一列（中国 / Australia / Netherlands 原样）",
      {"中国", "Australia", "Netherlands"} <= {g["country"] for g in geo9 if g["iso"]},
      sorted(g["country"] for g in geo9 if g["iso"]))
check("表头写的是国家 / 地区而不是含糊的归属地", '"国家 / 地区"' in overview_ts, None)
check("明细那一列仍然是带省市的完整归属地", "浙江省杭州市" in
      stats_mod.list_queries({"geo": "CN"})["items"][0]["geo"])

print("\n10) 面板内联滚动：五行的五行，明细十行")
# (a) 这一节原来钉的是 admin.html 里那批 data-fold 容器 + app.css 的 .fold 规则 + 模板里那段内联脚本。
#     后台转 React 后三样合成：ui.tsx 的 Table（HeroUI Table 的表头吸顶）配 hooks/useClamp
#     （量第 N+1 行、补滚动条、首测同步跑），styles.css 的 .scroll-thin 收细滚动条。
#     前台那条同款（检索快照只给 6 行）共用同一个 useClamp —— 两处钉的是同一套量法。
adminui_ts = (AD / "ui.tsx").read_text(encoding="utf-8")
vod_ts = (BASE / "web" / "src" / "components" / "VodPanel.tsx").read_text(encoding="utf-8")
clamp_ts = (BASE / "web" / "src" / "hooks" / "useClamp.ts").read_text(encoding="utf-8")
counts = [5 if m.group(1) == "R5" else int(m.group(1))
          for f in sorted(AD.glob("*.tsx"))
          for m in re.finditer(r"<Table\b[^>]*?rows=\{(R5|\d+)\}", f.read_text(encoding="utf-8"), re.S)]
check("统计那几块表都传了行数（明细 10 行，其余 5 或 6 行）",
      len(counts) >= 8 and counts.count(10) == 1
      and all(5 <= n <= 6 for n in counts if n != 10), counts)
check("限高挂在 HeroUI 的滚动容器上，而且必须是定位元素：offsetTop 量的是相对最近那个定位祖先，"
      "不写 relative 就一路找到页面外层，算出来的高得离谱、限高等于没限",
      '<HeroTable.ScrollContainer ref={setBox} className="relative">' in adminui_ts,
      None)
check("框高不写死在 CSS 里：行高随折行变化，写死会露半行 —— 只有量出来的那个数才进 style",
      'node.style.maxHeight = next === null ? "" : `${next}px`;' in clamp_ts
      and "max-height" not in adminui_ts, None)
check("框高取第 N+1 行的 offsetTop（量出来的，不是猜的像素）；不足 N 行干脆不设高度",
      "const h = (trs[rows] as HTMLElement).offsetTop;" in adminui_ts
      and "if (trs.length <= rows) return null;" in adminui_ts
      and "if (next === last.current) return;" in clamp_ts, None)
check("横向滚动条占的那几像素高度要补回去，否则最后一行被它盖住",
      "return h + (el.offsetHeight - el.clientHeight);" in adminui_ts
      and "return h + (el.offsetHeight - el.clientHeight);" in vod_ts, None)

# 首测踩过同一个坑：rAF 在后台标签里压根不回调（实测），首帧没量就等于没限高；
# 而 HeroUI 的 Table 把行排在另一次提交里，还要一个 MutationObserver 盯 childList 才量得到。
check("首测同步跑、RO 与 MO 的回调里直接量（rAF 在后台标签不回调，量不到就等于没限高）",
      "ro.current = new ResizeObserver(measure);" in clamp_ts
      and "mo.current = new MutationObserver(measure);" in clamp_ts
      and "useLayoutEffect(measure);" in clamp_ts
      and "requestAnimationFrame(" not in clamp_ts, None)
check("框内滚动时表头吸顶、底色不透明、分隔线用 inset box-shadow"
      "（border-collapse 下 border 跟着单元格走，吸顶时那条线会留在原地）",
      'className="sticky top-0 z-10 text-start text-muted shadow-[inset_0_-1px_0_var(--border)] first:pl-0 last:pr-0"'
      in adminui_ts
      and "border-b border-separator" not in adminui_ts[adminui_ts.index("export function Table"):
                                                        adminui_ts.index("export function Row")], None)
check("滚动条收成细条、颜色引主题令牌（暗色下不许是一道白槽，也不能吃掉宽表的横向空间）",
      re.search(r"\.scroll-thin \{[^}]*scrollbar-width: thin", styles_css) is not None
      and re.search(r"\.scroll-thin \{[^}]*scrollbar-color: var\(--border\)", styles_css) is not None,
      re.findall(r"\.scroll-thin \{[^}]*\}", styles_css))
refs_block = overview_ts[overview_ts.index('id="refs"'):]
check("说明文字排在表格之外（不然注意事项也跟着一起滚，第一眼看不到）",
      refs_block.index("</Table>") < refs_block.index("Referrer-Policy")
      and detail_ts.index("</Table>") < detail_ts.index("「最快间隔」是同一 IP"), None)
check("没有残留的展开/收起按钮（要做的是内联滚动条，不是点击展开）",
      "foldbtn" not in adminui_ts + ah and "is-open" not in adminui_ts + ah,
      (ah.count("foldbtn"), adminui_ts.count("foldbtn")))
check("翻页不再把整页滚到明细顶部：只有侧边目录那一跳才用 scrollIntoView",
      "scrollIntoView" not in detail_ts + adminui_ts
      and 'scrollIntoView({ block: "start" })' in adminapp_tsx, None)
check("滚动避让只为目录锚点服务：每个正文块自带 scroll-mt，顶栏高度变了改一处",
      'className="scroll-mt-14 space-y-3"' in adminui_ts
      and "sticky top-0 z-30" in adminapp_tsx and "sticky top-20" in adminapp_tsx, None)
check("前台检索快照用的是同一个量法：超过 6 条才夹到第 7 条的 offsetTop，在框里自己滚",
      "const setBox = useClamp(" in vod_ts
      and 'const lis = el.querySelectorAll("li");' in vod_ts and "lis.length <= 6" in vod_ts
      and "(lis[6] as HTMLElement).offsetTop" in vod_ts
      and 'className="scroll-thin relative mt-3 overflow-y-auto"' in vod_ts, None)


print("\n11) 手机 / 平板：触摸目标、抽屉不压 home indicator、滑块不许变成滚页面")
# (a) 这一节每条断言原本都对着 app.css 的窄屏那一段 + index.html + app.js，而且都对应一次实测问题
#     （360px 上净宽只剩 249px、标签被挤成 98px 高、一片 11px 字、22 个控件够不上拇指）。
#     前台转 React 后这些活儿换了载体：尺寸与间距在 Tailwind 类里，抽屉归 HeroUI（placement 由
#     DetailDrawer 按屏宽选），躲 home indicator 与"没有 hover 就常驻"落在 styles.css。逐条搬。
CW = BASE / "web" / "src" / "components"
gate_ts = (CW / "Gate.tsx").read_text(encoding="utf-8")
sb_ts = (CW / "SearchBar.tsx").read_text(encoding="utf-8")
poster_ts = (CW / "Poster.tsx").read_text(encoding="utf-8")
drawer_ts = (CW / "DetailDrawer.tsx").read_text(encoding="utf-8")
check("viewport 带 viewport-fit=cover（不写这个，env(safe-area-inset-*) 恒为 0，下面那条等于没躲）",
      "viewport-fit=cover" in sh, None)
check("详情已换成居中弹框（不再贴边，home indicator 那条 env() 兜底随抽屉一起退役）",
      'Modal.Container size="md"' in drawer_ts and "placement" not in drawer_ts
      and "drawer__dialog" not in styles_css and "safe-area-inset-bottom" not in styles_css, None)
check("拖滑块不许变成滚页面：那颗按钮上写死 touch-none（旧 app.css 里是 touch-action: none）",
      "touch-none" in gate_ts and "onPointerDown={(e) => {" in gate_ts, None)
check("搜索框 16px —— iOS 聚焦时字号小于 16px 会把整页放大一次（旧版在后台口令框上踩过同一坑）",
      'px-2 text-base outline-none' in sb_ts and "text-[15px]" not in sb_ts, None)
check("禁用 JS 那份登录页的输入框也走 --fs-input（16px 那一档，同一个坑不在兜底页复发）",
      "--fs-input: var(--text-base);" in root
      and re.search(r"\.admfield input, \.admfield select \{[^}]*var\(--fs-input\)", css) is not None,
      re.findall(r"--fs-input[^;]*", css))
check("详情按钮在触屏上够按（32px 高、40px 宽起）",
      re.search(r'className="dbtn [^"]*min-h-8 min-w-10', poster_ts) is not None, None)
check("触屏没有 hover：详情按钮在这种情况下常驻可见",
      "@media (hover: none) {\n    .dbtn {\n      opacity: 1;" in styles_css, None)
check("整张海报在触屏上也是点击区，那一层是 <button>（键盘走得到），不是给封面挂 JS 监听",
      'className="cover-hit absolute inset-0"' in poster_ts and "contextmenu" not in react_ts, None)
check("窄屏两张折叠卡片各就各位：结果之后依次是接口状态、《xxx》的检索结果，都默认折起"
      "（order-first 会把接口状态顶到结果上面，手机上等于把结果推出半屏）",
      "max-xl:contents" in app_tsx and "order-first" not in app_tsx
      and app_tsx.index("<SourcesPanel") < app_tsx.index("<SnapshotCard")
      and 'useMediaQuery("(min-width: 1280px)")' in vod_ts and "const shown = open ?? wide;" in vod_ts,
      None)
check("全站自己画 hover/active，不要浏览器那点一下闪的灰底",
      "-webkit-tap-highlight-color: transparent" in styles_css, None)

print("\n13) 版式：药丸一档、卡片一档、数字一律等宽")
# (a) 这一节原来逐条 grep app.css 里那批联合选择器（.gobtn/.srcbtn/.eps a/.row .ct…）。
#     React 侧的等价规矩是：圆角只有三档 —— 卡片 rounded-2xl、海报 rounded-xl、胶囊 rounded-full，
#     没有第四种临时半径；数字与状态行一律 .num（等宽 + tabular-nums）；颜色一律引令牌。
#     登录兜底页那份 app.css 仍然守老规矩（药丸 = var(--r-pill)），两处一起钉着。
radii = re.findall(r"rounded-\[(?!\d)[^\]]*\]", react_ts)
check("圆角只有三档：rounded-2xl / rounded-xl / rounded-full，没有临时半径那种第四种写法",
      not radii and all(k in react_ts for k in ("rounded-2xl", "rounded-xl", "rounded-full")), radii[:4])
check("卡片写法前后台同一份：rounded-2xl + bg-surface + p-4 + ring-1 ring-border（不是各圆各的）",
      "rounded-2xl bg-surface p-4 text-surface-foreground shadow-surface ring-1 ring-border" in adminui_ts
      and "rounded-2xl bg-surface p-4 text-surface-foreground shadow-surface ring-1 ring-border" in vod_ts,
      None)
check("数字与状态行一律 .num：等宽字体族 + tabular-nums，一列数字才对得齐",
      re.search(r"\.num \{[^}]*var\(--font-mono\)", styles_css) is not None
      and re.search(r"\.num \{[^}]*font-variant-numeric: tabular-nums", styles_css) is not None, None)
check("字体只从令牌取：每一条 font-family 都引 var(--font-*)，@theme 里那两族是唯一写族名的地方",
      re.findall(r"font-family:\s*([^;}]+)", styles_css)
      and all(v.strip().startswith("var(--font-")
              for v in re.findall(r"font-family:\s*([^;}]+)", styles_css))
      and "--font-sans:" in styles_css and "--font-mono:" in styles_css,
      re.findall(r"font-family:\s*[^;}]+", styles_css))
check("唯一的硬编码颜色是那枚强调色（HeroUI 预设的靛蓝在白底上压不住白字，深一档才有对比度）",
      styles_css.count("--accent: oklch") == 1 and "oklch(0.578 0.186 262.1)" in styles_css,
      re.findall(r"--accent[^;]*", styles_css))
check("海报压暗走 filter，不透明度留给淡入（两者抢同一个属性就会闪）",
      ".dark .poster-img" in styles_css and "filter: brightness(0.94)" in styles_css
      and "opacity" not in styles_css[styles_css.index(".dark .poster-img"):
                                      styles_css.index(".dark .poster-img") + 60], None)
check("动画都能被 reduced-motion 收掉：淡入、行切换、抽屉进出、那道跑着的进度条",
      styles_css.count("@media (prefers-reduced-motion: reduce)") >= 4
      and "animation-duration: 2.4s" in styles_css, None)

print("\n14) 栅格：结果在左、资料栏在右（只在够宽且真有结果时）")
# (a) 原来这一节 grep index.html 的 body 类与 app.js 里那两句 classList.toggle。
#     转 React 后"要不要右栏"就是 JSX 的一个条件：vod 标签 + 有关键词才排两栏，
#     body 上那三个开关整个没有载体了 —— 判据换成条件本身、栅格定义与粘性跟随。
check("栅格只在影视检索 + 有关键词那一屏（落地页右边会空一大块，所以不排两栏）",
      '<Tabs.Panel id="vod" className="pt-5">' in app_tsx
      and "{kw ? (\n              <div className=\"grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]\">" in app_tsx,
      None)
check("左栏是 minmax(0,1fr)：一长串片名/命令能缩下去，不会把整页顶得能横着拖",
      "xl:grid-cols-[minmax(0,1fr)_320px]" in app_tsx and "minmax(0,1fr)" in drawer_ts, None)
check("够宽时资料栏粘性跟随（滚到结果中段，接口状态还在右手边）",
      "xl:sticky xl:top-20" in app_tsx and "xl:self-start" in app_tsx, None)
check("网盘 / 目录 / 直达三个标签没有右栏（它们要的是整幅宽度）",
      app_tsx.count('<div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">') == 1
      and 'Tabs.Panel id="cloud"' in app_tsx and 'Tabs.Panel id="deep"' in app_tsx, None)
check("接口状态与检索快照都没内容时整块不渲染（不留一张空卡片在页面上）",
      "if (!rows.length) return null;" in vod_ts and "if (!items.length) return null;" in vod_ts, None)
check("检索快照跟着当前这个词走：SPA 换词也从 /api/search 第一页拿到新的一份",
      "const hasSnap = !!snap && snap.kw === kw" in app_tsx
      and "if (d.snapshot) setSnap(d.snapshot);" in app_tsx
      and "setSnap((cur) => (cur && cur.kw === kw ? cur : null));" in app_tsx, None)
check("快照卡窄屏默认折叠、宽屏展开，且排在接口状态之后（桌面落在右栏最底下）",
      'useMediaQuery("(min-width: 1280px)")' in vod_ts
      and "const shown = open ?? wide;" in vod_ts
      and app_tsx.index("<SourcesPanel") < app_tsx.index("<SnapshotCard"), None)
check("前后台同一档 1680（顶栏、正文、页脚三处与后台共用同一条上限）",
      "max-w-[1680px]" in adminapp_tsx and app_tsx.count("max-w-[1680px]") == 3, None)

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
