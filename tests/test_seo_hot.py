# -*- coding: utf-8 -*-
"""猜你想搜 + SEO 的离线测试（不联网，用固定样本）。

    python tests/test_seo_hot.py
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from zhuiju import hot, seo  # noqa: E402

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

print("\n2) 最近半年判定")
today = date.today()
since = today - timedelta(days=hot.HALF_YEAR_DAYS)
check("窗口内更新时间算新", hot._recent({"updated": (today - timedelta(days=30)).isoformat(),
                                       "year": ""}, since) is True)
check("窗口外且无年份 → 不算新",
      hot._recent({"updated": (today - timedelta(days=400)).isoformat(), "year": ""}, since) is False)
check("今年年份即算新（更新时间缺失时兜底）",
      hot._recent({"updated": "", "year": str(today.year)}, since) is True)
check("vod_time 非法字符串不崩", hot._recent({"updated": "N/A", "year": "2020"}, since) is False)
check("vod_year 为 None 不崩", hot._year(None) == 0, hot._year(None))

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
tpl = (Path(__file__).resolve().parent.parent / "zhuiju" / "templates" / "index.html"
       ).read_text(encoding="utf-8")
check("模板不再用 seo.snapshot.items 属性写法", "seo.snapshot.items" not in tpl)
check("改用下标 seo.snapshot['items']", "seo.snapshot['items']" in tpl)

print("\n7) 猜你想搜分页：一行铺满 + 上一页/下一页，不做横向滚动条")
# 曾经的两个 bug：① 模板用 len(rows) <= 12 判断按钮是否禁用，而 rows 已被截成一行，
# 于是"下一行"永远点不动；② 用 flex + overflow-x 做成横向拖动条，不是翻页。
# 现在网格是 repeat(var(--hot-cols), 1fr) 且没有 overflow-x，JS 按实际列数整行换页。
import re  # noqa: E402

from zhuiju import app as app_mod  # noqa: E402

css = (BASE / "zhuiju" / "static" / "app.css").read_text(encoding="utf-8")
grid_css = css[css.index(".hotgrid {"):css.index(".hotcard {")]
check("热榜网格改成网格布局而非 flex 横滚", "display: grid" in grid_css, grid_css)
check("列数走 --hot-cols 变量", "--hot-cols" in grid_css and "repeat(var(--hot-cols" in grid_css)
check("没有横向滚动条", "overflow-x" not in grid_css and "scrollbar-width" not in grid_css, grid_css)

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
nxt = {m.group(1): m.group(0) for m in
       re.finditer(r'<button class="pbtn next" type="button" data-kind="(\w+)"([^>]*)>', html)}
check("两组各有一个「下一页」按钮", set(nxt) == {"movie", "tv"}, list(nxt))
check("能翻页的那组按钮可用", "disabled" not in nxt.get("movie", ""), nxt.get("movie"))
check("只剩一屏的那组按钮禁用", "disabled" in nxt.get("tv", ""), nxt.get("tv"))
check("每页张数写在 data-per 上供 JS 对齐", 'data-per="12"' in html)
check("总数写在 data-total 上", 'data-total="30"' in html and 'data-total="12"' in html)
check("上一页按钮初始禁用",
        all('class="pbtn prev" type="button" data-kind="%s" data-dir="-1" disabled' % k in html
            for k in ("movie", "tv")))
check("翻页时整行替换而非追加", "innerHTML = items.map(hotCard)" in
      (BASE / "zhuiju" / "static" / "app.js").read_text(encoding="utf-8"))
check("首屏卡片共 24 张", html.count('class="hotcard"') == 24, html.count('class="hotcard"'))

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
js = (BASE / "zhuiju" / "static" / "app.js").read_text(encoding="utf-8")
page_js = js[js.index("async function showHotPage"):js.index("function noteHotChange")]
check("每次翻页都按接口回来的总数重算页数", "Math.ceil((d.total || 0) / cols)" in page_js,
      re.findall(r"Math\.ceil\([^\n]+", page_js))
check("取回空的一页且已经超出页数时，夹到最后一页重取一次",
      "if (!items.length && st.page >= pages)" in page_js
      and "return showHotPage(kind, pages - 1)" in page_js,
      re.findall(r"if \(!items\.length[^\n]*\n[^\n]*\n[^\n]*", page_js))
check("夹页这条一定终止（st.page 只会变小，不会来回弹）",
      page_js.count("return showHotPage(") == 1)
check("条数变了要当场写出来，不然人只会以为翻页算错了",
      "列表刚更新过：" in js and re.search(r"if \(to && from && to !== from\)", js) is not None,
      re.findall(r"列表刚更新过[^\n]*", js))
check("提示挂在两组的组标题上（电影、电视剧各一个）",
      'id="hotupd-{{ sec }}"' in (BASE / "zhuiju" / "templates" / "index.html").read_text(encoding="utf-8"),
      None)
check("提示不是 nowrap（窄屏上会把标题那行顶出容器）",
      ".hotupd { font-size: var(--fs-sm); color: var(--warn); }" in css and
      "white-space: nowrap" not in css[css.index(".hotupd {"):css.index(".hotupd {") + 90],
      css[css.index(".hotupd"):css.index(".hotupd") + 160])
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
js = (BASE / "zhuiju" / "static" / "app.js").read_text(encoding="utf-8")
ec = js[js.index("function ensureCloud"):js.index("function renderCloudSites")]
check("没关键词时去要那份清单，不再是「先搜索一个片名」的死胡同",
      "if (!state.kw)" in ec and "getJSON('/api/cloud')" in ec
      and "先搜索一个片名" not in js, re.findall(r"先搜索[^\n]{0,30}", js))
check("清单只在没关键词时取，取到就复用（切标签页不重复请求）",
      "if (state.cloudSites) { renderCloudSites(state.cloudSites); return; }" in ec)
rs = js[js.index("function renderCloudSites"):js.index("function renderCloud(")]
check("空的那一组不渲染标题（顶着「本站能直接搜出结果」却一行都没有，看着像坏了）",
      "q.length ? " in rs and rs.count("grouphead") == 2, re.findall(r"grouphead", rs))
check("每一行都给了打开该站的链接与推荐指数",
      "打开该站 ↗" in rs and "stars(s.recommended)" in rs)
check("说清这份清单不联网、以及为什么有的站只能自己打开",
      "这份清单不联网" in rs and "已验证的 GET 搜索模板" in rs)
check("搜索完再进这个标签页走的仍是真查询",
      "fetch('/api/cloud?kw='" in js and "state.cloudKw = state.kw" in js)

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
