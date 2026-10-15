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

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
