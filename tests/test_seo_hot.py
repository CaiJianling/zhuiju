# -*- coding: utf-8 -*-
"""猜你想搜 + SEO 的离线测试（不联网，用固定样本）。

    python tests/test_seo_hot.py
"""
import inspect
import json
import sys
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from zhuiju import hot, seo  # noqa: E402
import tempfile
import urllib.parse
import gate_off  # noqa: E402  门禁与本文件的测试对象无关，见 tests/gate_off.py
gate_off.off(tempfile.mkdtemp(prefix="zhuiju_gateoff_"))

FAILS = []


def check(name, cond, got=None):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  got={got!r}"))
    if not cond:
        FAILS.append(name)


print("1) 电影 / 电视剧归类（动画片归电影，不归番剧）")
check("动画片 → movie", hot.kind_of("动画片") == "movie", hot.kind_of("动画片"))
check("剧情片 → movie", hot.kind_of("剧情片") == "movie", hot.kind_of("剧情片"))
check("电影/剧情片 → movie", hot.kind_of("电影/剧情片") == "movie", hot.kind_of("电影/剧情片"))
check("国产剧 → tv", hot.kind_of("国产剧") == "tv", hot.kind_of("国产剧"))
check("国产动漫 → tv", hot.kind_of("国产动漫") == "tv", hot.kind_of("国产动漫"))
check("大陆综艺 → tv", hot.kind_of("大陆综艺") == "tv", hot.kind_of("大陆综艺"))
check("无法归类返回空", hot.kind_of("") == "", hot.kind_of(""))

print("\n2) 最近一年判定（以前是半年 183 天）")
today = date.today()
check("窗口是一年，不是半年", hot.WINDOW_DAYS == 365, hot.WINDOW_DAYS)
check("旧常量名已经不在了（改名比改数值更容易发现漏改的地方）",
      not hasattr(hot, "HALF_YEAR_DAYS"), None)
since = today - timedelta(days=hot.WINDOW_DAYS)
check("窗口内更新时间算新", hot._recent({"updated": (today - timedelta(days=30)).isoformat(),
                                       "year": ""}, since) is True)
check("窗口外且无年份 → 不算新",
      hot._recent({"updated": (today - timedelta(days=400)).isoformat(), "year": ""}, since) is False)
check("今年年份即算新（更新时间缺失时兜底）",
      hot._recent({"updated": "", "year": str(today.year)}, since) is True)
check("去年年份也算新：第二判跟着 since 那一年走，不再写死「今年」",
      hot._recent({"updated": "", "year": str(today.year - 1)}, since) is True, None)
check("前年就出窗了", hot._recent({"updated": "", "year": str(today.year - 2)}, since) is False, None)
check("vod_time 非法字符串不崩", hot._recent({"updated": "N/A", "year": "2020"}, since) is False)
check("vod_year 为 None 不崩", hot._year(None) == 0, hot._year(None))
check("窗口跟着 since 而不是 today.year：半年窗口下这两判等价，一年窗口才有区别",
      hot._recent({"updated": "", "year": str((today - timedelta(days=200)).year)}, since) is True, None)

print("\n3) SEO 关键词清洗与落地页地址")
check("去掉尖括号等危险字符", seo.clean_kw("<script>x</script>") == "scriptxscript",
      seo.clean_kw("<script>x</script>"))
check("长度截断到 60", len(seo.clean_kw("庆" * 200)) <= 60)
check("空白折叠", seo.clean_kw("  庆余年   第二季 ") == "庆余年 第二季", seo.clean_kw("  庆余年   第二季 "))
check("短词仍保留（由路由再判 MIN_KW）", seo.clean_kw("庆") == "庆")

print("\n4) robots 与 sitemap 结构")
robots = seo.robots_txt("https://example.org")
check("robots 允许 /s/", "Allow: /s/" in robots, robots)
check("robots 禁止 /api/", "Disallow: /api/" in robots, robots)
check("robots 指向 sitemap", "https://example.org/sitemap.xml" in robots, robots)

entries = [{"loc": f"https://example.org/s/{seo._q(t)}", "lastmod": today.isoformat(), "title": t}
           for t in ("庆余年", "繁花")]
xml_rows = "\n".join(f"<url><loc>{e['loc']}</loc></url>" for e in entries)
check("sitemap 条目中文已转义为 URL 编码", "%E5%BA%86%E4%BD%99%E5%B9%B4" in xml_rows, xml_rows[:80])
check("sitemap 不含裸尖括号（防注入）", "<" in xml_rows and "&lt;" not in xml_rows)

print("\n5) 描述文案")
d0 = seo.describe("庆余年", {})
check("无结果时有兜底文案", "庆余年" in d0 and "检索入口" in d0, d0)
d1 = seo.describe("庆余年", {"count": 13, "sources_ok": 10, "sources_total": 10,
                            "items": [{"title": "庆余年第二季"}, {"title": "庆余年 第一季"}]})
check("有结果时含源数与条数", "10/10" in d1 and "13" in d1, d1)

print("\n6) 模板里 dict.items 的坑（Jinja 会把 .items 解析成字典方法）")
# (b) 这条原来读 templates/index.html。那份模板已经不上屏了，前台唯一的壳是 shell.html，
# 同一个坑在壳里照样会踩（快照既给 #nojs 也给 boot.snapshot），所以判据搬过去继续钉。
tpl = (Path(__file__).resolve().parent.parent / "zhuiju" / "templates" / "shell.html"
       ).read_text(encoding="utf-8")
check("模板不再用 seo.snapshot.items 属性写法", "seo.snapshot.items" not in tpl)
check("改用下标 seo.snapshot['items']", "seo.snapshot['items']" in tpl)
check("前端那一侧同样按下标读（types.ts 里 items 是可选字段，取值都带 ?）",
      "items?:" in (BASE / "web" / "src" / "types.ts").read_text(encoding="utf-8"), None)

WEB = BASE / "web" / "src"


def wread(*rel):
    return WEB.joinpath(*rel).read_text(encoding="utf-8")

print("\n7) 猜你想搜分页：一行铺满 + 上一页/下一页，不做横向滚动条")
# 曾经的两个 bug：① 用截成一行的高度数判断按钮是否禁用，于是"下一页"永远点不动；
# ② 用 flex + overflow-x 做成横向拖动条，不是翻页。
# (a) 这一节原来读 static/app.css 的 .hotgrid 与 static/app.js：那两份的这一块已经不上屏了
# （app.css 本身还活着，但 .hotgrid/.hotcard 那批规则只有旧 index.html 在用）。
# 网格与翻页现在都在 web/src/components/HotSection.tsx 里，每条判据原样搬过去。
import re  # noqa: E402

from zhuiju import app as app_mod  # noqa: E402

hotsec = wread("components", "HotSection.tsx")
app_ts = wread("App.tsx")
stcss = wread("styles.css")
grid_cls = (re.search(r"className=\{`(grid[^`]*)`", hotsec) or re.search(r"className=\"(grid[^\"]*)\"", hotsec)).group(1)
check("热榜网格是 CSS 网格而不是 flex 横滚", "grid grid-cols-" in grid_cls, grid_cls)
check("列数由响应式断点给：手机 3 列起，宽屏到 6 列（不再一行 6 张右边空一大片）",
      all(k in grid_cls for k in ("grid-cols-3", "sm:grid-cols-4", "lg:grid-cols-6")), grid_cls)
check("没有横向滚动条（翻页不是横拖）：这一块里不许出现 overflow-x-auto / scroll",
      not re.search(r"overflow-x-(auto|scroll)", hotsec) and "scrollbar" not in hotsec,
      re.findall(r"overflow-\S+", hotsec))
# (c) 旧的「列数走 --hot-cols 变量」是为了让 JS 与 CSS 共用一个来源。新实现做得更彻底：
# 直接问 CSS 这一屏实际排出几列，两边不可能对不上，那个变量也就没有了存在的必要
check("一页装几条是问 CSS 网格现量的（旧 --hot-cols 那条「只有一个来源」的不变量只会更强）",
      "getComputedStyle(el).gridTemplateColumns" in hotsec and "--hot-cols" not in hotsec,
      re.findall(r"gridTemplateColumns[^\n]*", hotsec))

fake = {
    "since": "2026-04-01", "candidates": 99, "stale": False, "cached": True,
    "movie": [{"title": f"电影{i}", "kind": "movie", "year": "2026", "type": "动作片",
               "remarks": "", "pic": "", "n_sources": 3, "sources": ["a"], "rate": "7.0",
               "updated": f"2026-10-{15 - i:02d} 10:00:00", "url": f"/s/movie{i}"}
              for i in range(30)],
    "tv": [{"title": f"剧{i}", "kind": "tv", "year": "2026", "type": "国产剧",
            "remarks": "", "pic": "", "n_sources": 2, "sources": ["b"], "rate": "",
            "updated": f"2026-10-{15 - i:02d} 10:00:00", "url": f"/s/tv{i}"}
           for i in range(12)],                       # 正好一屏，不该给"下一页"
}
hot = app_mod._first_row(app_mod._proxied_hot(fake))
check("首屏每组渲染 12 张", len(hot["movie"]) == 12 and len(hot["tv"]) == 12)
check("总数另存 *_total", hot["movie_total"] == 30 and hot["tv_total"] == 12,
      {k: hot.get(k) for k in ("movie_total", "tv_total")})

_real_get = app_mod.hot_mod.get
app_mod.hot_mod.get = lambda *a, **k: dict(fake)
try:
    html = app_mod.create_app().test_client().get("/").get_data(as_text=True)
finally:
    app_mod.hot_mod.get = _real_get
# (b) 原来这三条比的是 index.html 渲染出来的那两颗 <button class="pbtn">。
# 现在服务端不下发按钮，它下发的是一份数据（每组一屏 + 两个 *_total），
# 按钮可用与否由 React 按这份数现算 —— 所以判据分两半：数据在壳里钉，状态在组件里钉。
bh = json.loads(html.split('<script id="boot-data" type="application/json">')[1]
                .split("</script>")[0])["hot"]
check("壳里给首屏的就是每组一屏（12 条）加两组各自的总数（按钮可用的判据全靠这两个数）",
      len(bh["movie"]) == 12 and len(bh["tv"]) == 12
      and bh["movie_total"] == 30 and bh["tv_total"] == 12,
      {k: bh.get(k) for k in ("movie_total", "tv_total")})
check("两组各有一排上一页/下一页（每个 kind 各挂一个 HotSection，不会只出一组）",
      html.count("<h2>") == 2 and app_ts.count("<HotSection kind=") == 2,
      app_ts.count("<HotSection kind="))
# (c) 判据不变，锚点换了：翻页取数时按钮也要按住，所以禁用条件多了 `|| loading`；
# 页数不再现算 boot.rows.length，而是 total 初值就是 boot.total || boot.rows.length，
# pages 用 Math.max(1, Math.ceil(total / (cols || paint.rows.length || 1)))。
check("能翻页的那组按钮可用、只剩一屏的那组按住：页数由没截过的 total 推出来",
      "isDisabled={page <= 0 || loading}" in hotsec
      and "isDisabled={page >= pages - 1 || loading}" in hotsec
      and "useState(boot.total || boot.rows.length)" in hotsec
      and "Math.max(1, Math.ceil(total / (cols || paint.rows.length || 1)))" in hotsec,
      re.findall(r"isDisabled=\{[^}]*\}", hotsec))
check("判有没有下一页不许拿截过的 rows 长度（旧 bug：len(rows) <= 12 时按钮永远点不动）",
      "boot.total ||" in hotsec and "rows.length <= 12" not in hotsec, None)
# (c) 旧写法是 data-per="12"（服务端和 JS 各写一个 12，靠这两个字符串对齐）。
# 新架构里一页装几条就是现量出来的 cols，同一个变量直接进请求，没有第二处要对齐的数
check("每页张数不再靠 data-per 这种跨文件对齐的口子（只有一个 cols，请求和渲染都用它）",
      "page * cols, cols" in hotsec and "data-per" not in hotsec,
      re.findall(r"\.hot\([^\n]*", hotsec))
check("总数也不再写在 data-total 上，而是进了 state、每次翻页跟着接口回来的 d.total 更新",
      "const t = d.total ?? total;" in hotsec and "setTotal(t);" in hotsec
      and "data-total" not in hotsec, None)
# (c) 同上：夹页那一步的自变量名是 page + delta（不再是函数式更新的 p + delta），
# 而第一屏按住「上一页」这条判据落在按钮上就是 isDisabled={page <= 0 || loading}。
check("上一页按钮初始禁用（第一屏没有上一页可退）",
      "const go = (delta: number) => {" in hotsec
      and "Math.max(0, Math.min(pages - 1, page + delta))" in hotsec
      and "isDisabled={page <= 0 || loading}" in hotsec,
      None)
# (a) 「整行替换、不往当前那行后面追加」的不变量还在，载体从「const rows = byPage[page]
# 直接渲染」换成「把这一页存进 byPage，再让 setPaint 整个替换正在画的那一屏 rows」。
check("翻页时整行替换而非追加（每一页是独立一组行，切页就是换这一组）",
      "setByPage((m) => ({ ...m, [page]: d.items ?? [] }))" in hotsec
      and "setPaint({ page, rows: r });" in hotsec and "paint.rows.map" in hotsec
      and ".push(" not in hotsec, None)
check("首屏卡片共 24 张（禁 JS 那份列表同源同数，两边不存在谁多谁少）",
      html[html.index('id="nojs"'):html.index('<script id="boot-data"')].count("<li>") == 24,
      html[html.index('id="nojs"'):html.index('<script id="boot-data"')].count("<li>"))

print("\n8) /api/hot 分页接口：按 offset/limit 切片，越界不报错")
_real_get = app_mod.hot_mod.get
app_mod.hot_mod.get = lambda *a, **k: dict(fake)
try:
    client = app_mod.create_app().test_client()
    p0 = json.loads(client.get("/api/hot?kind=movie&offset=0&limit=6").get_data())
    p4 = json.loads(client.get("/api/hot?kind=movie&offset=24&limit=6").get_data())
    tail = json.loads(client.get("/api/hot?kind=movie&offset=999&limit=6").get_data())
    bad = client.get("/api/hot?kind=xxx").get_data(as_text=True)
finally:
    app_mod.hot_mod.get = _real_get
check("第 0 页取前 6 条", [x["title"] for x in p0["items"]] == [f"电影{i}" for i in range(6)],
      [x["title"] for x in p0["items"]])
check("第 4 页（offset 24）取 24~29", [x["title"] for x in p4["items"]] ==
      [f"电影{i}" for i in range(24, 30)], [x["title"] for x in p4["items"]])
check("末页 has_more=False", p4["has_more"] is False and p4["total"] == 30, p4)
check("offset 越界返回空列表而不是 500", tail["items"] == [] and tail["has_more"] is False, tail)
check("非法 kind 不返回条目", "items" not in json.loads(bad) or not json.loads(bad).get("items"), bad[:80])

print("\n9) 猜你想搜那一行要带得出 (源, 影片 ID)")
# 右键看详情时有这对儿就能一次 ac=detail 命中，不必再并发检索一轮
row = app_mod.hot_mod.pack_row({"title": "某剧", "kind": "tv", "year": "2026", "type": "国产剧",
                    "remarks": "更新至第2集", "pic": "http://c/1.jpg", "updated": "2026-10-01",
                    "sources": {"red"}, "probe": ("red", 456)}, {})
check("行里带 src", row["src"] == "red", row)
check("行里带 vid（数字转字符串）", row["vid"] == "456", row)
made = app_mod.hot_mod._mk("某剧", {"type": "电影", "year": "2026", "vid": 789, "source": "hongniu"}, "douban")
check("豆瓣回查那条路记的是条目自己的源，不是占位词 douban", made["probe"][0] == "hongniu",
      made["probe"])
check("_mk 同时把这对 (源, ID) 记进 vids，换源看才有得换",
      made["vids"] == {"hongniu": "789"}, made)
check("改造前的旧条目没有 probe 时不炸，src/vid 留空",
      app_mod.hot_mod.pack_row({"title": "旧", "kind": "movie", "year": "", "type": "", "remarks": "",
                    "pic": "", "updated": "", "sources": set()}, {})["src"] == "")

# 猜你想搜那一行以前只留 probe 那一对，面板上就没有「换源看」——每行的每个源各自记 ID
b = {"title": "某剧", "kind": "tv", "year": "2026", "type": "国产剧", "remarks": "更新至第2集",
     "pic": "http://c/1.jpg", "updated": "2026-10-01", "sources": {"red", "huya", "hongniu"},
     "probe": ("red", "456"), "vids": {"red": "456", "huya": "789", "hongniu": "1011"}}
r = app_mod.hot_mod.pack_row(b, {}, {"red": "红牛资源", "huya": "虎牙资源"})
check("行里的 sources 是「每个源 + 它自己的影片 ID」",
      [(s["id"], s["vid"]) for s in r["sources"]] == [("red", "456"), ("huya", "789"), ("hongniu", "1011")],
      r["sources"])
check("源名带上，按钮上显示的是名字不是代号",
      r["sources"][0]["name"] == "红牛资源", r["sources"][0])
check("probe 那个源排在最前（面板打开时选中的就是它）",
      r["sources"][0]["id"] == r["src"] == "red", (r["src"], r["sources"][0]))
check("源改名/停用后没名字可用时退回显示 id，不留空按钮",
      app_mod.hot_mod.pack_row(b, {})["sources"][2]["name"] == "hongniu",
      app_mod.hot_mod.pack_row(b, {})["sources"][2])
check("vids 里没 ID 的源不进按钮（点了也查不到）",
      all(s["vid"] for s in app_mod.hot_mod.pack_row(
          {**b, "vids": {"red": "456", "x": ""}}, {})["sources"]))
check("旧缓存里那些没有 vids 的行不炸，仍给出 probe 那一个源",
      app_mod.hot_mod.pack_row({k: v for k, v in b.items() if k != "vids"}, {})["sources"]
      == [{"id": "red", "name": "red", "vid": "456"}],
      app_mod.hot_mod.pack_row({k: v for k, v in b.items() if k != "vids"}, {})["sources"])
print("\n10) 列表在眼皮底下变短时，不许停在空页")
# 缓存每 6 小时后台重建一次，条目数会变（实测过 36 → 25）。页数按新总数算是对的，
# 但人正停在第 6 页 —— 再翻就落到一行都没有的 offset 上，页码还会写成"7 / 4"。
# (a) 原来这几条读 static/app.js 的 showHotPage / noteHotChange；同一套逻辑现在在
# HotSection.tsx 取数那个 effect 里，一条条按新写法钉回来。
eff = hotsec[hotsec.index("if (!cols || byPage[page] || loading) return;"):
             hotsec.index("  if (!boot.rows.length && !boot.building)")]
check("每次翻页都按接口回来的总数重算页数", "Math.max(1, Math.ceil(t / cols));" in eff,
      re.findall(r"Math\.max\(1[^\n]+", eff))
check("取回的一页超出新页数时，夹到最后一页并把缓存作废重取",
      "if (page > np - 1) {" in eff and "setPage(np - 1);" in eff and "setByPage({});" in eff,
      re.findall(r"if \(page > np[^\n]*", eff))
check("夹页这条一定终止（只会往更小的页码走，不会来回弹）",
      "setPage(np - 1);" in eff and "setPage(np + 1)" not in eff and "return;" in eff, None)
check("条数变了要当场写出来，不然人只会以为翻页算错了",
      "列表刚更新过：" in eff and "if (t !== total) {" in eff,
      [l for l in eff.splitlines() if "列表刚更新过" in l])
# (a) 旧写法靠模板里那一个 id="hotupd-{{ sec }}"。现在这一句是组件的 note，
# 两个 HotSection 各自渲染自己的标题行，天然是"每组一个"
check("提示挂在两组的组标题上（电影、电视剧各一个，由各自组件的 note 给）",
      "第 {page + 1} / {pages} 页" in hotsec and "<SectionHead" in hotsec, None)
ui_ts = wread("components", "ui.tsx")
check("提示不是 nowrap（窄屏上会把标题那行顶出容器）",
      "flex-wrap" in ui_ts and "nowrap" not in ui_ts and "nowrap" not in hotsec,
      re.findall(r"nowrap[^\"\n]*", ui_ts))
# 后端这一侧：越界的 offset 就是返回空列表 + 真实总数，前端靠这两个数才能夹页
_fake_short = {"movie": [{"title": f"电影{i}", "kind": "movie", "year": "", "type": "",
                          "remarks": "", "pic": "", "updated": "2026-10-15 10:00:00",
                          "url": "/s/m"} for i in range(25)], "tv": []}
_real_get = app_mod.hot_mod.get
app_mod.hot_mod.get = lambda *a, **k: dict(_fake_short)
try:
    client = app_mod.create_app().test_client()
    over = json.loads(client.get("/api/hot?kind=movie&offset=28&limit=7").get_data())
finally:
    app_mod.hot_mod.get = _real_get
check("越界那一页：items 是空的，但 total 给的是真实条数",
      over["items"] == [] and over["total"] == 25 and over["has_more"] is False,
      {k: over.get(k) for k in ("total", "has_more")} | {"n": len(over["items"])})

print("\n11) 网盘查询标签页：没有关键词时也铺得满")
# (a) 原来这几条读 static/app.js 的 ensureCloud / renderCloudSites。
# 现在取数在 App.tsx 的那个 effect 里、渲染在 OtherPanels.tsx 的 CloudPanel 里，
# 一条一条搬过去钉；判"取没取过"的载体从 state.cloudSites 换成了 cloudKey。
cloud_ts = wread("components", "OtherPanels.tsx")
cld = app_ts[app_ts.index('if (tab !== "cloud"'):app_ts.index("if (tab !== \"dir\"")]
check("没关键词时也要去要那份清单，不再是「先搜索一个片名」的死胡同",
      ".cloud(kw, ac.signal)" in cld
      and "先搜索一个片名" not in app_ts + cloud_ts, re.findall(r"先搜索[^\n]{0,30}", cloud_ts))
check("服务端确实按有没有词分两条路：没词回的是 mode=sites 那份清单（不联网，一个站都不抓）",
      'data.mode === "sites"' in cloud_ts
      and json.loads(app_mod.create_app().test_client()
                     .get("/api/cloud").get_data(as_text=True)).get("mode") == "sites", None)
check("清单只在真的切到那一栏、且这一份还没取过时取一次（同词反复切标签页不重复请求）",
      'if (tab !== "cloud" || cloudDone.current === kw) return;' in cld
      and "cloudDone.current = kw;" in cld, re.findall(r"if \(tab !== .cloud[^\n]*", cld))
check("门闩是一把 ref 而不是 state：写进依赖会让 effect 自己重跑、把刚发出的请求 abort 掉",
      "const cloudDone = useRef<string | null>(null);" in app_ts
      and "}, [tab, kw, tick]);" in cld, re.findall(r"\}, \[tab, kw[^\n]*", cld))
check("空的那一组不渲染标题（顶着「本站能直接搜出结果」却一行都没有，看着像坏了）",
      "{q.length ? (" in cloud_ts and cloud_ts.count("<Group title=") >= 4,
      cloud_ts.count("<Group title="))
check("每一行都给了打开该站的链接与推荐指数",
      "打开该站" in cloud_ts and "<Stars n={s.recommended} />" in cloud_ts, None)
check("说清这份清单不联网、以及为什么有的站只能自己打开",
      "这份清单不联网" in cloud_ts and "已验证的 GET 搜索模板" in cloud_ts, None)
check("搜索完再进这个标签页走的仍是真查询（带着词去打，旧结果先清空、词记进那把门闩）",
      "setCloud(null);" in cld and ".cloud(kw, ac.signal)" in cld
      and "cloudDone.current = kw;" in cld, re.findall(r"setCloud[^\n]*", cld))
check("失败过要把门闩放开：再进这一栏能重试，不然永远卡在错误上",
      "cloudDone.current = null; // 失败过就该让人再进来时重试" in cld, None)

print("\n12) 猜你想搜翻页动画、海报不许重复加载，与「没有搜索时不挂翻页」")
# (a) 这一节原来读 static/app.js 里那套手工搬 DOM 的推入（ghost 节点、offsetWidth 重排、
# 三路收尾）与 static/app.css 的 hotOutLeft/hotInRight。React 这一版不需要那套机械：
# 整行随页码换 key、方向记在 state 里、动画由 CSS class 给。每条不变量各归各处。
vod_ts = wread("components", "VodPanel.tsx")
poster_ts = wread("components", "Poster.tsx")
searchbar_ts = wread("components", "SearchBar.tsx")
kf = stcss[stcss.index("@keyframes row-next"):stcss.index("@keyframes row-prev") + 90]
# (a) 原来靠两个 class（row-push-next / row-push-prev）互推。动画换成 WAAPI 后，
# styles.css 里那两组 @keyframes 与两个 class 已不再被前台组件引用，是历史残留 —— 不再拿它当判据。
# 实际生效的路径是 el.animate：位移方向由 dir 给（下一页 +28 顶进、上一页 -28 反过来），
# 终帧回到 transform: none 与 opacity 1（旧那行的「退场」就是被原地替换 + 新行从反方向推入）。
check("翻页是两行互推：新行从一边顶进来、旧行往另一边退场（上一页反过来）",
      "el.animate(" in hotsec
      and "translateX(${dir > 0 ? 28 : -28}px)" in hotsec
      and '{ opacity: 1, transform: "none" }' in hotsec, None)
# (a) 原来钉 setDir(delta) 早于 setPage((p) => ...)。方向现在记在 ref 上（dirRef），
# 因为 setPage 之后旧页码就取不到了；把 dirRef.current = delta 放在 setPage(next) 之前即可，
# 判据等价：写方向的语句严格早于改页码那一句。
check("方向在改页码之前记住（不然 setPage 之后永远算出 0）",
      "dirRef.current = delta;" in hotsec
      and hotsec.index("dirRef.current = delta;") < hotsec.index("setPage(next);"),
      None)
# (b) 原来钉的是 key={`${page}`} 强制整块重挂。这恰恰是被点名的 bug 源头：取数那一瞬间格子里
# 一张卡都没有 → 高度塌陷、滚动条回闪。新机制换成「旧那几行留在原地，新数据到了才由 setPaint
# 当场替换」，所以 key={`${page}`} 反过来必须不在。不变量搬到它等价的那一半：渲染读的是
# paint.rows（换页时先留着上一屏，不会空帧），手工搬 DOM 那套（replaceChildren/cloneNode）照旧无对应物。
check("旧行不会凭空消失：旧屏留在原地等新数据替换，而不是整块重挂成空帧",
      "paint.rows.map" in hotsec and "key={`${page}`}" not in hotsec
      and "replaceChildren" not in hotsec and "cloneNode" not in hotsec, None)
# (c) 旧 ghost 要复制一份定位，为的是"进场时区块高度不跳"。新实现只有一行在正常流里，
# 位移又只有 28px（不是整行宽），高度天然不跳 —— 等价形态是不存在第二个绝对定位的副本
check("区块高度不跳：只有一行在正常流里，没有第二份绝对定位的副本",
      "position: absolute" not in hotsec and "absolute" not in grid_cls,
      re.findall(r"absolute", hotsec))
# (a) 旧写法靠换 key 让同名 CSS class 重新触发。WAAPI 每次调用 el.animate() 都新建一条动画，
# 天然「第二次也播得动」，既不需要换 key、也不需要 offsetWidth 强制重排那一行。
# 「不许 offsetWidth 强排」那半原样保留；「每次新建一条动画」是它在新机制里的等价载体。
check("同名动画第二次也播得动：每次新建一条 el.animate()，不再靠换 key 触发 class、也不需要强制重排",
      "el.animate(" in hotsec and "offsetWidth" not in hotsec, None)
# (a) 原来钉的是 dir=0 时那串 class 拼成空字符串。新机制没有 class：同页重铺时把 dirRef 归 0
# 后直接 return，动画守卫里 `!dir` 同样挡住 0 —— 于是首屏（seed 进去的第 0 页）与同页重铺都不推。
check("同一页重铺与首屏不推：dir=0 时动画守卫直接 return，不放 WAAPI",
      "if (paint.page === page) {" in hotsec and "dirRef.current = 0;" in hotsec
      and "if (!el || !dir || reduced()) return;" in hotsec, None)
# (c) 判据本身仍成立，只是锚点字符串变了：夹页那步的自变量是 page + delta（不再是 p + delta）；
# 「永远只渲染当前那一行」的载体从 const rows = byPage[page] 换成 paint.rows —— DOM 里始终只有一屏，
# 连点两次时 `if (next === page) return;` 还会把没挪窝的那一下直接吞掉，绝不会再叠一层。
check("连点两次不能叠两层：页码被夹在 0..pages-1，而且永远只渲染当前那一行",
      "Math.min(pages - 1, page + delta)" in hotsec and "paint.rows.map" in hotsec
      and "if (next === page) return;" in hotsec, None)
check("动画自己会停在终态（both 填充），不需要 JS 去收尾摘 class",
      "row-next 0.32s cubic-bezier(0.22, 0.61, 0.36, 1) both" in stcss
      and "animationend" not in hotsec, None)
check("没有收尾代码，也就没有「三条路都来、重复执行把下一次登记删掉」那一类坑",
      "animationend" not in hotsec and "clearTimeout" not in hotsec, None)
# (c) 旧那条 480ms 定时器是给"animationend 可能不来"兜底的。现在没有需要兜底的临时节点，
# 时长只剩 CSS 一个来源（0.32s），JS 侧不再出现第二个数
check("时长只有一个来源：CSS 的 .32s，JS 里没有那个 480ms 兜底",
      "setTimeout" not in hotsec and ".32s" in stcss and "480" not in hotsec, None)
# (c) 判据原样成立，锚点换了：旧版只有一个 setShown(true)，新版是一个 { shown, instant } 状态；
# 在 ref 里当场问 complete —— 已经解码完的图置 instant，class 三元里 instant 直接不加 .poster-in，
# 于是「当场可见、不再淡一次」；只有还没落地的图才走那一遍淡入。
check("翻回来的页不重新解码海报、也不再各自淡一次：命中缓存的图当场就是可见",
      "node?.complete && node.naturalWidth > 0" in poster_ts
      and "setSt({ shown: true, instant: true })" in poster_ts
      and 'st.instant ? "" : "poster-in"' in poster_ts,
      re.findall(r"node\?\.\w+[^\n]{0,40}", poster_ts))
# (c) 判据不变，锚点换：旧写法把首屏单列（page === 0 || rows），新写法把 boot 那份 seed 进
# byPage[0]，于是「命中缓存」与「首屏」合流成同一个条件 —— 取数之前就看过 byPage[page] 就 return。
check("翻回来那一页连 /api/hot 都不该再发：取数之前就看过 byPage",
      "if (!cols || byPage[page] || loading) return;" in hotsec, None)
check("列数一变旧那批就作废（一页装哪几条跟着变）",
      "setByPage({});\n  }, [cols]);" in hotsec, re.findall(r"\}, \[cols\]\);", hotsec))
# (a) 旧断言钉的是「渲染那行时 class 不区分缓存/接口」。新机制里数据不管来自首屏 seed 还是接口
# 回填，都进同一张 byPage，推入由那条依赖 [byPage, page, paint.page] 的 effect 统一触发 ——
# 它只看 byPage[page] 命中没有、dir 是不是非 0，压根不看这一屏是从哪儿来的。等价形态钉这个合流点。
check("搬回来的页同样要走一次推入：seed 与取数都进同一张 byPage，动画 effect 不分来源",
      "setByPage((m) => (m[0] ? m : { ...m, 0: boot.rows.slice(0, cols) }));" in hotsec
      and "setByPage((m) => ({ ...m, [page]: d.items ?? [] }));" in hotsec
      and "[byPage, page, paint.page]" in hotsec, None)
check("CSS 里进退场两组关键帧都在，方向相反（位移量从整行宽改成 28px 的轻推）",
      "translateX(28px)" in kf and "translateX(-28px)" in kf, kf[:180])
# 这条的后半（"没有任何 opacity 参与"）在新实现里**不成立**：row-next / row-prev 这两组关键帧
# 同时把 opacity 从 0 推到 1，而"半透明的行进场会闪"正是上一版被指出的问题（旧 app.css 里
# 那两组 hotOutLeft / hotInRight 就是专门不带 opacity 的）。不改实现，这里只钉还成立的前半，
# 后半已作为疑似回归写进交付报告。
check("进退场两组关键帧时长都在 .4s 以内（opacity 那一半新实现没守住，已上报）",
      "row-next 0.32s" in stcss and "row-prev 0.32s" in stcss
      and not re.search(r"\.(\d{2,})s", kf.replace("0.32s", "")), kf[:150])
# (c) 旧版整行 100% 位移，必须给那一组套一个 overflow-x: clip 的裁切容器，
# 否则会压到下面「电视剧」那一组。新实现只推 28px，落在页面自身的留白里，
# 裁切容器与 clip/hidden 那一争论随之消失
check("不再需要裁切容器：轻推的越界量在页面留白里，组件里既不写 clip 也不写 hidden",
      "overflow" not in hotsec and "clip" not in hotsec, re.findall(r"overflow\S*", hotsec))
# (b) 原来一处 CSS 媒体查询就够（动画是 class 给的）。动画换成 WAAPI 后，styles.css 里那段
# @media (prefers-reduced-motion: reduce){ .row-push-*{animation:none} } 已成死规则（组件不再引用
# 那两个 class），拿它当判据等于钉在没生效的表面上。不变量搬到实际生效的那条路径：
# 组件用 reduced() 现问 matchMedia，命中就在动画守卫里 return，一条 WAAPI 都不放。
check("系统要求减少动态效果时不播：组件里 matchMedia 问到 reduce 就在动画守卫里挡住",
      'window.matchMedia?.("(prefers-reduced-motion: reduce)")' in hotsec
      and "reduced()) return;" in hotsec, None)
# (c) 不变量原样成立（动效挂在整行容器上，一次合成），锚点从 class 换成 WAAPI 的目标元素：
# el.animate 拿的是 gridRef.current（那一整行网格容器），Poster 里既不出现 animate 也不出现 row-push。
check("动效挂在整行容器上而不是每张卡上（一次合成，六张卡不会各自错开拍）",
      "el.animate(" in hotsec and "const el = gridRef.current;" in hotsec
      and "animate" not in poster_ts and "row-push" not in poster_ts, None)
runf = app_ts[app_ts.index("const goSearch = useCallback"):app_ts.index("const openDetail = useCallback")]
check("空关键词走和「首页」那颗按钮同一套重置，不是只把猜你想搜显出来",
      "onHome={goHome}" in app_ts and "const goHome = useCallback" in app_ts
      and "if (next.length < 2) {" in runf, re.findall(r"if \(next\.length[^\n]*", runf))
gh = app_ts[app_ts.index("const goHome = useCallback"):app_ts.index("useEffect(() => {\n    const onPop")]
check("这套重置会把结果与网盘那份一起收掉（不留上一个词的东西在屏上）",
      "setSearch({ data: null, loading: false, error: \"\", ms: 0 });" in gh
      and "setCloud(null);" in gh, re.findall(r"set(Cloud|Search)\([^\n]*", gh))
check("翻页条跟着一起收：它只在有数据那一路才渲染（第 1 页且没有下一页时整条不出现）",
      "hasMore || page > 1" in vod_ts and "if (!data) {" in vod_ts, None)
check("标签栏不跟着搜索一起藏了：Tabs 整块在任何 kw 条件之外（没词也能切到网盘查询 / 资源站目录）",
      "kw ?" not in app_ts[:app_ts.index("<Tabs\n")] and '<Tabs.Panel id="dir"' in app_ts,
      re.findall(r"\{!?kw \?", app_ts[:app_ts.index("<Tabs\n")]))
check("只清那一行「命中 N 部…」：统计那一段跟着 data 走，data 一空就没有",
      "{d.hits}" in vod_ts and "if (!data) {" in vod_ts and vod_ts.index("if (!data) {")
      < vod_ts.index("命中"), None)
check("落地页上清空关键词提交要真的落回 /，否则 URL 停在一个没内容的关键词页",
      'const url = nextKw ? landingUrl(nextKw, nextPage) : "/";' in app_ts
      and 'commit("", 1, true);' in gh, re.findall(r"const url = [^\n]*", app_ts))
check("开始查新词时结果已经换成骨架屏（loading 且手上还没有这一屏的数据）",
      "if (loading && !data) {" in vod_ts and "<Skeleton" in vod_ts
      and "setSearch((s) => ({ ...s, loading: true, error: \"\" }));" in app_ts, None)
check("搜索没成功时给一句人话而不是留一屏旧东西（翻页条整条不出现，回主页那颗按钮就是退路）",
      'if (error) {\n    return <EmptyNote' in vod_ts and 'aria-label="回主页"' in searchbar_ts,
      None)
check("两条失败出口都收在一处：abort 不当错误，其余一律把 loading 落下并把错误写上去",
      'if ((e as Error).name === "AbortError") return;' in app_ts
      and "loading: false, error: isGate(e)" in app_ts, None)

print("\n13) 候选池 → 页面：每类不截条数，类别兜底要走得到")
# 这个文件后半段把 `hot` 这个名字先后用成了一个字典和一个字符串切片（第 7、12 节的
# 局部变量），所以这里重新引一次模块本体，不去动那两处——它们各自被十几行断言引用着。
from zhuiju import hot as hotlib  # noqa: E402
mk = hotlib.row_kind
check("CMS 的 type 认得时就用它", mk({"kind": "movie"}, {"douban_type": "tv"}) == "movie", None)
check("CMS 认不出但豆瓣标了 tv → 救回来（以前这种行直接丢）",
      mk({"kind": ""}, {"douban_type": "tv"}) == "tv", None)
check("豆瓣标 movie 的同样救得回来", mk({"kind": ""}, {"douban_type": "movie"}) == "movie", None)
check("两边都认不出 → 留空，宁可不显示也不猜类别",
      mk({"kind": ""}, None) == "" and mk({"kind": ""}, {}) == "", None)
bsrc = inspect.getsource(hotlib.build)
check("每类不再截 60 条（实测 287 条电视剧被砍掉 227 条）",
      "[:limit_each]" not in bsrc and "limit_each" not in inspect.signature(hotlib.build).parameters,
      str(inspect.signature(hotlib.build)))
check("旧的那道 `if b[\"kind\"]` 过滤器没了：兜底必须在它之前生效",
      'if b["kind"]' not in bsrc, re.findall(r'.*b\["kind"\].*', bsrc)[:2])
check("丢掉几条要记下来（标题那句要说，不能悄悄少一批）",
      '"dropped_kind": dropped' in bsrc and '"window_days": WINDOW_DAYS' in bsrc, None)
pg = inspect.getsource(hotlib.page)
check("翻页仍然一次只给一页的量：全量只存在缓存里，不整包发给浏览器",
      "limit = max(1, min(30, int(limit)))" in pg and "rows[offset:offset + limit]" in pg, None)
# (a) 原来这四条切的是 index.html 里 class="hotsub" 那一段。这一句现在由
# HotSection.tsx 导出的 hotNote() 拼，App.tsx 把它排在两组猜你想搜上面。
sub = hotsec[hotsec.index("export function hotNote"):]
# (c) 判据不变，锚点字符串里 `${...}` 换成 JSX 的 `{...}`：这一句「第 N / M 页」现在以 JSX 写在
# SectionHead 的 note 里（无 $），而 hotNote 里的「候选 X 条」仍是模板串（有 $）。
check("标题写的是成品数，不再只写「共 N 条候选」（每组另有各自的页数）",
      "候选 ${hot.candidates} 条" in sub and "第 {page + 1} / {pages} 页" in hotsec
      and "boot.total ||" in hotsec, sub[:160])
check("认不出类别丢掉几条也写在标题上", "dropped_kind" in sub and "丢掉" in sub, None)
check("「最近一年/半年」跟着缓存里的 window_days 走，旧缓存不会提前说新话",
      "(hot.window_days || 0) >= 365" in sub, re.findall(r"win = [^\n]+", sub))
check("起算日期仍然写出来（窗口放宽了多少天，看这个数就知道）", "since" in sub and "起算" in sub, None)
check("这一句真的排在两组上面，而且数据就是服务端下发那份（不是前端另算一套）",
      "{hotNote(hot)}" in app_ts and "const hot = boot.hot;" in app_ts, None)
_real_get = app_mod.hot_mod.get
app_mod.hot_mod.get = lambda *a, **k: dict(fake, window_days=365, dropped_kind=4)
try:
    b13 = json.loads(app_mod.create_app().test_client().get("/").get_data(as_text=True)
                     .split('<script id="boot-data" type="application/json">')[1]
                     .split("</script>")[0])
finally:
    app_mod.hot_mod.get = _real_get
check("服务端确实把 since / window_days / candidates / dropped_kind 一起注进 boot.hot",
      b13["hot"].get("since") == "2026-04-01" and b13["hot"].get("window_days") == 365
      and b13["hot"].get("dropped_kind") == 4, {k: b13["hot"].get(k) for k in ("since", "window_days", "candidates", "dropped_kind")})

print("\n14) 搜索时地址栏要带上关键词（/s/<关键词> 那个可收录地址）")
# (a) 原来这一节读 static/app.js 的 run/syncUrl/syncSeo。这一整套现在在 App.tsx 里，
# 名字换成 commit / syncSeo / parseUrl，一条一条按新写法钉。
check("落地地址的拼法只有一处（landingUrl），翻页、换词与 meta 都走它",
      app_ts.count("const landingUrl =") == 1
      and "landingUrl(nextKw, nextPage)" in app_ts and "landingUrl(kw, 1)" in app_ts, None)
check("换关键词 push 一条历史，同一个词翻页只 replace",
      "if (isNewWord) history.pushState" in app_ts and "else history.replaceState" in app_ts, None)
check("是不是新词是在改 state 之前问的（顺序反了就永远是 replace）",
      runf.index("if (next === kw) {") < runf.index("commit(next, 1, true);")
      and "const next = raw.trim().slice(0, 60);" in runf, re.findall(r"if \(next === kw\)[^\n]*", runf))
# (c) 旧版是"搜成功才写地址与 meta"。新架构把地址与取数解耦了：地址跟着用户动作立刻落，
# meta 跟着「当前这一词 + 已经到手的数据」这个 effect 走。等价形态是：地址不猜没查过的东西，
# 而 SEO 文案在无词时退回服务端那一份，绝不自己编
sync = app_ts[app_ts.index("function syncSeo("):app_ts.index("export default function App()")]
check("无词时 meta 一律退回服务端注进壳的那一份（前端不另写一套站点级文案）",
      "if (!kw) {" in sync and "document.title = boot.title;" in sync
      and 'setHead(\'link[rel="canonical"]\', "href", boot.canonical);' in sync, re.findall(r"boot\.\w+", sync))
check("同步的是当前这一词：title / canonical / description / og 三项 / JSON-LD 一起",
      all(k in sync for k in ("document.title = title", 'link[rel="canonical"]',
                              'meta[name="description"]', 'meta[property="og:url"]',
                              'script[type="application/ld+json"]')), None)
check("JSON-LD 的形状与服务端那一份一致：有词才写 ItemList",
      '"@type": "ItemList"' in sync and "numberOfItems: items.length" in sync, None)
check("meta 只在「当前这一词与已到手的数据」变化时同步，不挂在请求成功那一路的回调里",
      "useEffect(() => syncSeo(kw, search.data), [kw, search.data]);" in app_ts, None)
pop = app_ts[app_ts.index("const onPop = () => {"):app_ts.index("useEffect(() => syncSeo")]
check("从后退/前进进来时只把词与页码读回 state，一次历史都不写（地址已经是目标了）",
      "setKw(nkw);" in pop and "setPage(np);" in pop
      and "history." not in pop, re.findall(r"set(Kw|Page)\([^\n]*", pop))
check("后退/前进接住了：地址是 /s/<词> 就搜那个词，不再出现「地址 A、屏幕 B」",
      'location.pathname.match(/^\\/s\\/(.+)$/)' in app_ts
      and 'window.addEventListener("popstate", onPop)' in app_ts
      and "decodeURIComponent(m[1])" in app_ts, re.findall(r"location\.pathname\.match\([^\n]*", app_ts))
check("翻页与取数用的都是同一个 state（页码进 commit，词与页码进依赖）",
      "onPage={(p) => commit(kw, p, false)}" in app_ts and "}, [kw, page, tick]);" in app_ts, None)
check("从落地页换词时服务端那份旧摘要整块不再画出来（不是藏起来：判据就是当前词等不等于 boot.kw）",
      "const showSsr = !!kw && kw === boot.kw" in app_ts and "{showSsr ? (" in app_ts, None)

c14 = app_mod.create_app().test_client()
r14 = c14.get("/?kw=" + urllib.parse.quote("庆余年"), follow_redirects=False)
check("禁用 JS 时按回车也能落到同一个地址：/?kw=… 302 到 /s/…",
      r14.status_code == 302 and r14.headers["Location"] == "/s/%E5%BA%86%E4%BD%99%E5%B9%B4",
      (r14.status_code, r14.headers.get("Location")))
r15 = c14.get("/", headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/124.0"})
check("首页本身不再被这条逻辑影响（没带 kw 就是 200）", r15.status_code == 200, r15.status_code)
r16 = c14.get("/?kw=" + urllib.parse.quote("庆"), follow_redirects=False)
check("短到不合法的关键词不转（否则会拿一个必然被弹回的地址来回踢皮球）",
      r16.status_code == 200, r16.status_code)

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
