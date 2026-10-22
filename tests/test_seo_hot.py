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
# 注释里会出现 "auto" 这类词（解释为什么用 clip 不用 hidden），要看的是声明不是散文
grid_rules = re.sub(r"/\*.*?\*/", "", grid_css, flags=re.S)
check("没有横向滚动条（翻页不是横拖）：这一带只许 clip，不许 auto/scroll",
      not re.search(r"overflow[^:]*:\s*[^;}]*(auto|scroll)", grid_rules)
      and "scrollbar-width" not in grid_rules
      and "overflow-x: clip" in grid_rules,      # 推入时进场那一行裁在这组里，不外溢
      re.findall(r"overflow[^;}]{0,26}", grid_rules))

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
js7 = (BASE / "zhuiju" / "static" / "app.js").read_text(encoding="utf-8")
check("翻页时整行替换而非追加", "const html = items.map(hotCard).join('');" in js7
      and "(g) => { g.innerHTML = html; }" in js7,
      re.findall(r"items\.map\(hotCard\)[^\n]{0,40}", js7)[:2])
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

print("\n12) 猜你想搜翻页动画、海报不许重复加载，与「没有搜索时不挂翻页」")
hot = js[js.index("const hotCache = {};"):js.index("function noteHotChange")]
check("翻页是两行互推：新行从右边顶进来、旧行往左边退场（上一页反过来）",
      "const moving = st.page - prev;" in hot
      and "dir > 0 ? 'out-left' : 'out-right'" in hot
      and "dir > 0 ? 'in-right' : 'in-left'" in hot,
      re.findall(r"'(out-\w+|in-\w+)'", hot))
check("方向在改 st.page 之前记住（不然永远算出 0）",
      hot.index("const prev = st.page;") < hot.index("st.page = Math.max(0, page)"), None)
check("旧行是搬进 ghost 而不是直接消失（凭空插进来就是从这里来的）",
      "const old = Array.prototype.slice.call(grid.children);" in hot
      and "ghost.replaceChildren.apply(ghost, old);" in hot, None)
check("ghost 定位在 grid 原来的位置上，新行留在正常流里占高度（进场时区块高度不跳）",
      "ghost.className = 'hotgrid ghost'" in hot
      and "ghost.style.top = grid.offsetTop" in hot, None)
check("强制重排一次，同名 class 第二次才播得动", "void ghost.offsetWidth;" in hot, None)
check("同一页重铺（窗口变宽）与首屏不推：dir=0 或系统要求减少动效时直接换",
      "if (!dir || noMotion() || !old.length) return;" in hot, None)
check("连点两次不能叠两层 ghost：新的推入先把上一次收尾",
      "if (pushing[kind]) pushing[kind]();" in hot and "pushing[kind] = done;" in hot, None)
check("animationend 不一定来，所以三路收尾（两边的 animationend + onfinish + 定时器兜底）",
      "ghost.addEventListener('animationend', done, { once: true });" in hot
      and "grid.addEventListener('animationend', done, { once: true });" in hot
      and "an.onfinish = done;" in hot and "timer = setTimeout(done, 480);" in hot, None)
check("收尾只认第一次（三条路都会来，重复执行会把下一次推入的登记删掉）",
      "if (gone) return;" in hot and "let timer = 0, gone = false;" in hot, None)
check("兜底时间比动画本身长一点但不拖太久（动画 .32s → 480ms 收尾）",
      ".32s ease-out both" in css and "setTimeout(done, 480)" in hot, None)
check("铺过的页留着那批 DOM 节点，翻回来直接搬回去：不重新解码海报、也不再各自淡一次",
      "(g) => g.replaceChildren.apply(g, seen)" in hot
      and "cache[st.page] = Array.prototype.slice.call(grid.children);" in hot, None)
check("翻回来那一页连 /api/hot 都不该再发：缓存在取数之前就判",
      hot.index("if (seen) {") < hot.index("const offset = st.page * cols;"),
      (hot.index("if (seen) {"), hot.index("const offset = st.page * cols;")))
check("列数一变旧节点就作废（一页装哪几条跟着变）",
      "if (!box || box.cols !== cols) box = hotCache[kind]" in hot, None)
check("搬回来的页同样要走一次推入（不然看着像没反应）",
      hot.count("swapRow(grid, kind, (g)") == 2, re.findall(r"swapRow\([^\n]{0,40}", hot))
css = (BASE / "zhuiju" / "static" / "app.css").read_text(encoding="utf-8")
kf = css[css.index("@keyframes hotOutLeft"):css.index(".hotcard {")]
check("CSS 里进退场两组关键帧都在，位移量是一整行宽（100%）",
      "@keyframes hotOutLeft" in kf and "@keyframes hotInRight" in kf
      and "translate3d(-100%, 0, 0)" in kf and "translate3d(100%, 0, 0)" in kf, kf[:140])
check("时长 .4s 以内，且没有任何 opacity 参与（半透明的行进场就是上一版被说闪的原因）",
      ".32s ease-out both" in kf and "opacity" not in kf, None)
check("进场的那一行要被裁在组里，不能压到下面「电视剧」那一组",
      ".hotgroup { position: relative; overflow-x: clip; }" in css,
      re.findall(r"\.hotgroup \{[^}]*\}", css)[:2])
check("用 clip 而不是 hidden：hidden 会把纵向也强行变成 auto，聚焦框会被裁",
      "overflow-x: clip" in css and ".hotgroup { position: relative; overflow: hidden" not in css, None)
check("系统要求减少动态效果时不播（CSS 与 JS 各挡一次）",
      "@media (prefers-reduced-motion: reduce)" in kf
      and "prefers-reduced-motion: reduce" in js, None)
check("动效挂在整行容器上而不是每张卡上（一次合成，九张卡不会各自错开拍）",
      ".hotgrid.in-right" in kf and ".hotcard.in-" not in kf, None)
runf = js[js.index("async function run("):js.index("async function getJSON(")]
check("空关键词走和「首页」那颗按钮同一套重置，不是只把猜你想搜显出来",
      "if (!kw) {" in runf and "goHome();" in runf.split("if (!kw) {")[1][:200],
      re.findall(r"if \(!kw\) \{.{0,120}", runf, re.S)[:1])
gh = js[js.index("function goHome()"):js.index("$('examples')")]
check("这套重置会把结果与上一页/下一页一起收掉",
      "pager.hidden = true" in gh and "resultsEl.innerHTML = ''" in gh, None)
check("标签栏不跟着搜索一起藏了：只清那一行「命中 N 部…」",
      "statline.hidden" not in js and "meta.textContent = '';" in gh, None)
html_tabs = (BASE / "zhuiju" / "templates" / "index.html").read_text(encoding="utf-8")
check("模板里 #statline 不再有 hidden（没有关键词也要能切到网盘查询 / 资源站目录）",
      'id="statline"' in html_tabs and 'id="statline" hidden' not in html_tabs
      and '<section class="statline" id="statline">' in html_tabs,
      re.findall(r'<section class="statline"[^>]*>', html_tabs))
check("落地页上清空关键词提交要真的跳回 /，否则 URL 停在一个没内容的关键词页",
      "if (boot.kw) { location.href = '/'; return; }" in gh, None)
check("开始查新词时结果已经换成骨架屏，上一个词的翻页条同时收掉",
      "pager.hidden = true;" in runf.split("class=\"skel\"")[1][:220],
      re.findall(r"class=\"skel\".{0,160}", runf, re.S)[:1])
pf = js[js.index("function pagerOnFail(page)"):js.index("function linesHTML")]
check("搜索没成功时翻页条自己收：第 1 页整条没了，深层页只留「上一页」这条退路",
      "pager.hidden = page <= 1;" in pf and "nextBtn.disabled = true;" in pf
      and "prevBtn.disabled = page <= 1;" in pf, pf[:200])
check("两条失败出口都调了它（接口无响应与抛异常），不靠 renderPager 兜",
      js.count("pagerOnFail(page);") == 2 and "AbortError" in runf, js.count("pagerOnFail(page);"))

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
head_html = (BASE / "zhuiju" / "templates" / "index.html").read_text(encoding="utf-8")
sub = head_html[head_html.index('class="hotsub"'):head_html.index("</h2>", head_html.index('class="hotsub"'))]
check("标题写的是成品数，不再只写「共 N 条候选」",
      "候选 {{ seo.hot.candidates }} 条 →" in sub and "seo.hot.movie_total" in sub
      and "seo.hot.tv_total" in sub, sub)
check("认不出类别丢掉几条也写在标题上", "dropped_kind" in sub and "丢掉" in sub, None)
check("「最近一年/半年」跟着缓存里的 window_days 走，旧缓存不会提前说新话",
      "seo.hot.window_days or 0" in sub and ">= 365" in sub, None)
check("起算日期仍然写出来（窗口放宽了多少天，看这个数就知道）", "seo.hot.since" in sub, None)

print("\n14) 搜索时地址栏要带上关键词（/s/<关键词> 那个可收录地址）")
js14 = (BASE / "zhuiju" / "static" / "app.js").read_text(encoding="utf-8")
run14 = js14[js14.index("async function run("):js14.index("/* ---------------- 真人门禁")]
check("落地地址的拼法只有一处（landingUrl），翻页与换词都走它",
      js14.count("function landingUrl(") == 1 and "landingUrl(kw, page)" in js14, None)
check("换关键词 push 一条历史，同一个词翻页只 replace",
      "if (isNewWord) history.pushState" in js14 and "else history.replaceState" in js14, None)
check("isNewWord 是在改 state.kw 之前问的（顺序反了就永远是 replace）",
      run14.index("const isNewWord = kw !== state.kw;") < run14.index("state.kw = kw"), None)
check("地址与 meta 只在搜索成功那一路同步",
      run14.index("syncUrl(kw, page, isNewWord);") < run14.index("} else {"), None)
# 后退/前进那一次地址已经是目标了，不用再写一遍地址栏；但 meta 必须跟着换，
# 否则按一次后退就成了"屏幕是庆余年、标题写着繁花"（实测踩过）
check("从后退/前进进来时只跳过写地址栏，不跳过同步 meta",
      "syncSeo(kw, sdata);\n        if (!fromUrl) syncUrl(kw, page, isNewWord);" in js14, None)
check("同步的是当前这一词：title / canonical / description / og / JSON-LD 一起",
      all(k in js14 for k in ("document.title = title", "link[rel=canonical]",
                              'meta[name=description]', 'meta[property="og:url"]',
                              'script[type="application/ld+json"]')), None)
check("后退/前进接住了：地址是 /s/<词> 就搜那个词，不再出现「地址 A、屏幕 B」",
      "addEventListener('popstate'" in js14
      and "location.pathname.match(/^" in js14 and "$/);" in js14
      and "run(input.value, p, true)" in js14,
      re.findall(r"location\.pathname\.match\([^\n]*", js14)[:1])
check("从落地页换词时把服务端那份旧摘要整块收起来（.ssr-done 只藏标题，那行旧描述会留着）",
      "if (s) s.hidden = true;" in run14, None)

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
