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

print("\n7) 猜你想搜：一行横着滚、滚到头自动补下一批（不再整行换页）")
# 旧版是"整行换页"：上一页渐隐、下一页渐现，三十几张海报同时改透明度，看着像整块在闪。
# 现在是一条横滚条：内容一直在那儿，动的是位移不是透明度；滚到右端自动补 12 条。
# (a) 这一节原来读 static/app.css 的 .hotgrid 与 static/app.js。那两份不上屏了，
# 判据搬到 web/src/components/HotSection.tsx 与 App.tsx。
import re  # noqa: E402

from zhuiju import app as app_mod  # noqa: E402

hotsec = wread("components", "HotSection.tsx")
app_ts = wread("App.tsx")
stcss = wread("styles.css")
check("热榜是一条横滚条（snap-x + overflow-x-auto），不是整行换页也不按断点重排",
      'className="scroll-thin snap-x flex gap-4 overflow-x-auto pb-1"' in hotsec
      and "grid-cols-" not in hotsec, re.findall(r"overflow-\S+", hotsec))
check("每颗宽度 31% 起、176px 封顶（手机三颗，宽屏多露几颗而不是把海报摊成墙）",
      'const CELL = "w-[31%] min-w-[104px] max-w-[176px] shrink-0 snap-start";' in hotsec,
      None)
check("每批 12 条：一个常量同时进请求，没有 data-per / --hot-cols 这类跨文件对齐的口子",
      "const BATCH = 12;" in hotsec and "api\n      .hot(kind, offset, BATCH)" in hotsec
      and "data-per" not in hotsec and "--hot-cols" not in hotsec,
      re.findall(r"\.hot\([^\n]*", hotsec))
check("右端哨兵进视野才补下一批（root 是横滚条本身，rootMargin 只往右放 260px）",
      "new IntersectionObserver((es) => {" in hotsec
      and 'root: el, rootMargin: "0px 260px 0px 0px"' in hotsec, None)

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
check("两组各有一条横滚条和一对箭头（每个 kind 各挂一个 HotSection，不会只出一组）",
      html.count("<h2>") == 2 and app_ts.count("<HotSection kind=") == 2,
      app_ts.count("<HotSection kind="))
# 箭头只是把视野往左右挪一屏（0.86 个容器宽）；补数仍由右端哨兵负责。
check("左右箭头按容器宽度的 86% 滚（一次挪一屏，不是一格一格蹭），来回两颗都常驻",
      "Math.max(160, el.clientWidth * 0.86)" in hotsec
      and 'aria-label={`把${label}往回滚`}' in hotsec
      and 'aria-label={`把${label}往后滚`}' in hotsec, None)
check("往后那颗在补数时按住、真到末尾也按住；往回那颗始终可用（左端只是没得滚）",
      "isDisabled={loading || (atEnd && items.length >= total)}" in hotsec
      and "boot.total || boot.rows.length" in hotsec, None)
check("总数每次跟着接口回来的 d.total 更新，列表变短会夹住，不停在空的那一截",
      "const t = d.total ?? total;" in hotsec and "setTotal(t);" in hotsec
      and "data-total" not in hotsec, None)
# (a) 这里和新版要求一致地改成「追加」：下一批并进已有那一叠，
# 按 片名+年份 去重（同一部片在两批里都上榜时只留一张卡），不重置正在看的位置。
check("补下一批是追加而非替换，同一部片按 片名+年份 去重",
      "setItems((prev) => {" in hotsec and "seen.has(key(x))" in hotsec
      and "next.push(x);" in hotsec and ".push(" in hotsec, None)
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
# 缓存每 6 小时后台重建一次，条目数会变（实测过 36 → 25）。横滚条没有"页码"这回事：
# offset 就是"已经拿到几条"，总数变短只会停止继续补，不会落在一个空 offset 上。
eff = hotsec[hotsec.index("const more = useCallback"):
             hotsec.index("  if (!boot.rows.length && !boot.building)")]
check("补下一批的 offset 就是「已经拿到几条」（不是页码×列数），列表变短也不会落到空页",
      "const offset = gotRef.current;" in eff
      and "if (loadingRef.current || offset >= total) return;" in eff,
      re.findall(r"const offset[^\n]*", eff))
check("接口回来的 total 变少时当场写出来，并把上限换成新的 total",
      "if (t !== total) {" in eff and "列表刚更新过：" in eff and "setTotal(t);" in eff,
      [l for l in eff.splitlines() if "列表刚更新过" in l])
check("已经铺出去的卡不因为 total 变短被抹掉（不重置 items，只停止继续补）",
      "setItems((prev) => {" in eff and "setItems([])" not in eff, None)
check("同一轮里只发一个请求（loadingRef 挡着；每批到货重挂 observer 才会连着补第二批）",
      "if (loadingRef.current || offset >= total) return;" in eff
      and "loadingRef.current = true;" in eff and "loadingRef.current = false;" in eff, None)
# (a) 旧写法靠模板里那一个 id="hotupd-{{ sec }}"。现在这一句是组件的 note，
# 两个 HotSection 各自渲染自己的标题行，天然是"每组一个"。
check("进度挂在两组的组标题上（电影、电视剧各一个：已铺 N / total 部）",
      "已铺 {items.length} / {total} 部" in hotsec and "<SectionHead" in hotsec, None)
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

print("\n12) 猜你想搜横滚：不推不隐、海报不重复解码，与「没有搜索时不挂横滚」")
# (a) 这一节原来读 static/app.js 里那套手工搬 DOM 的推入（ghost 节点、offsetWidth 重排、
# 三路收尾）与 WAAPI 的 28px 轻推。整行换页整个撤掉后，这些机械在组件里没有载体：
# 横滚条只做 scrollBy，内容从不重挂、也不改透明度。
vod_ts = wread("components", "VodPanel.tsx")
poster_ts = wread("components", "Poster.tsx")
searchbar_ts = wread("components", "SearchBar.tsx")
check("横滚不靠关键帧与幽灵节点：没有 WAAPI、没有 replaceChildren/cloneNode，只有 scrollBy",
      "el.scrollBy({" in hotsec and "el.animate(" not in hotsec
      and "replaceChildren" not in hotsec and "cloneNode" not in hotsec, None)
check("系统要求减少动态效果时直接跳过去，不用 smooth",
      'behavior: reduced() ? "auto" : "smooth"' in hotsec, None)
check("没有动画收尾要兜底：组件里没有 animationend / 定时器这一类临时状态",
      "animationend" not in hotsec and "setTimeout" not in hotsec
      and "clearTimeout" not in hotsec, None)
check("也不需要 offsetWidth 强制重排（横滚不量行高，也不靠换 key 重播动画）",
      "offsetWidth" not in hotsec, None)
# (c) 判据原样成立：旧版只有一个 setShown(true)，新版是一个 { shown, instant } 状态；
# 在 ref 里当场问 complete —— 已经解码完的图置 instant，class 三元里 instant 直接不加 .poster-in，
# 于是「当场可见、不再淡一次」；只有还没落地的图才走那一遍淡入。
check("横滚经过同一张海报不重新解码、也不再淡一次：命中缓存的图当场就是可见",
      "node?.complete && node.naturalWidth > 0" in poster_ts
      and "setSt({ shown: true, instant: true })" in poster_ts
      and 'st.instant ? "" : "poster-in"' in poster_ts,
      re.findall(r"node\?\.\w+[^\n]{0,40}", poster_ts))
# 数据只有两条路：boot 首屏一次、右端哨兵补批（且不是见底就发）。
check("已铺出去的内容不会因为补批被重置（setItems 是 append 不是 replace）",
      "useState<HotRow[]>(boot.rows)" in hotsec
      and "setItems((prev) => {" in hotsec and "setItems([])" not in hotsec, None)
# 动效挂在容器滚动上而不是每张卡：Poster 里不出现 scrollBy，横滚只有一处触发点。
check("滚动只由那一条横滚容器执行，Poster 里没有第二处 scrollBy / animate",
      "animate" not in poster_ts and "scrollBy" not in poster_ts, None)
runf = app_ts[app_ts.index("const goSearch = useCallback"):app_ts.index("const openDetail = useCallback")]
check("空关键词走和「首页」那颗按钮同一套重置，不是只把猜你想搜显出来",
      "onHome={goHome}" in app_ts and "const goHome = useCallback" in app_ts
      and "if (next.length < 2) {" in runf, re.findall(r"if \(next\.length[^\n]*", runf))
gh = app_ts[app_ts.index("const goHome = useCallback"):app_ts.index("useEffect(() => {\n    const onPop")]
check("这套重置会把结果与网盘那份一起收掉（不留上一个词的东西在屏上）",
      "setStack(null);" in gh and "setCloud(null);" in gh
      and 'setLoad({ loading: false, appending: false, error: "" });' in gh,
      re.findall(r"set(Cloud|Stack|Load)\([^\n]*", gh))
check("自动追加的尾巴只在有数据那一路：loading、error、空结果三种分支都排在它前面",
      vod_ts.index("if (loading && !stack)") < vod_ts.index("const d = stack;")
      and vod_ts.index("const d = stack;") < vod_ts.index("ref={sentinel}"), None)
check("标签栏不跟着搜索一起藏了：Tabs 整块在任何 kw 条件之外（没词也能切到网盘查询 / 资源站目录）",
      "{kw ?" not in app_ts[:app_ts.index("<Tabs\n")] and '<Tabs.Panel id="dir"' in app_ts,
      re.findall(r"\{!?kw \?", app_ts[:app_ts.index("<Tabs\n")]))
check("统计那一段跟着 stack 走：stack 一空（loading / error / 空结果）就整块不渲染",
      "{d.hits}" in vod_ts and "if (loading && !stack) {" in vod_ts
      and "if (!stack) {" in vod_ts and vod_ts.index("if (!stack) {") < vod_ts.index("命中"),
      None)
check("落地页上清空关键词提交要真的落回 /，否则 URL 停在一个没内容的关键词页",
      'const url = nextKw ? landingUrl(nextKw, nextPage) : "/";' in app_ts
      and 'commit("", 1, true);' in gh, re.findall(r"const url = [^\n]*", app_ts))
check("开始查新词时结果已经换成骨架屏（loading 且手上还没有这一叠）",
      "if (loading && !stack) {" in vod_ts and "<Skeleton" in vod_ts
      and "setStack((cur) => (cur && cur.kw === kw && cur.from === page ? cur : null));" in app_ts,
      None)
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
check("标题写的是「已铺 N / total 部」，不再只写「共 N 条候选」",
      "候选 ${hot.candidates} 条" in sub and "已铺 {items.length} / {total} 部" in hotsec
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
check("meta 只在「当前这一词与已到手的那一叠」变化时同步，不挂在请求成功那一路的回调里",
      "useEffect(\n    () => syncSeo(kw, stack ? { items: stack.items, sourcesOk: stack.sources_ok } : null),\n    [kw, stack],\n  );"
      in app_ts, None)
pop = app_ts[app_ts.index("const onPop = () => {"):app_ts.index("useEffect(\n    () => syncSeo")]
check("从后退/前进进来时只把词与页码读回 state，一次历史都不写（地址已经是目标了）",
      "setKw(nkw);" in pop and "setPage(np);" in pop
      and "history." not in pop, re.findall(r"set(Kw|Page)\([^\n]*", pop))
check("后退/前进接住了：地址是 /s/<词> 就搜那个词，不再出现「地址 A、屏幕 B」",
      'location.pathname.match(/^\\/s\\/(.+)$/)' in app_ts
      and 'window.addEventListener("popstate", onPop)' in app_ts
      and "decodeURIComponent(m[1])" in app_ts, re.findall(r"location\.pathname\.match\([^\n]*", app_ts))
check("起始页与取数用的是同一个 state（page 进 commit、也进取数依赖；往后追加只读 stack.pages）",
      "const [page, setPage] = useState(boot.page || 1);" in app_ts
      and "api\n      .search(kw, page, ac.signal)" in app_ts
      and "}, [kw, page, tick]);" in app_ts, None)
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
