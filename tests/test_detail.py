# -*- coding: utf-8 -*-
"""海报「详情」按钮的离线测试（不联网：所有请求都被桩替掉）。

    python tests/test_detail.py

覆盖三层：
  1. 详情数据的来源 —— ac=detail 解析出的字段、按片名兜底那条路、缓存与失败重试；
  2. /api/detail 的入参边界 —— 有 ID 走 ID，没 ID 走片名，两个都没有就 400；
  3. 前端接线 —— 按钮在不在海报角上、右键有没有被劫持、详情请求是不是只在点击之后才发、
     观看地址在面板里怎么折叠、点了之后往 /api/click 报什么。
"""
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from zhuiju import hot  # noqa: E402
from zhuiju import search as search_mod  # noqa: E402

FAILS = []


def check(name, cond, got=None):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  got={got!r}"))
    if not cond:
        FAILS.append(name)


print("1) ac=detail 解析：面板要显示的字段都得在")
raw = {"list": [{
    "vod_id": 1234, "vod_name": "庆余年 第二季", "type_name": "国产剧", "vod_year": "2026",
    "vod_area": "内地", "vod_actor": "张若昀,李沁", "vod_director": "孙皓",
    "vod_pic": "http://img.example.com/a.jpg", "vod_blurb": "少年携记忆入京都。",
    "vod_remarks": "更新至第8集", "vod_note": "HDR",
    "vod_play_from": "aliyun$$$xunlei",
    "vod_play_url": "第1集$http://p/1#第2集$http://p/2$$$第1集$http://q/1",
}]}
d = search_mod.parse_maccms_detail(raw)
for k in ("title", "type", "year", "area", "actor", "director", "pic", "blurb", "notes", "lines"):
    check(f"解析出 {k}", k in d and d[k] not in (None, "", []), d.get(k))
check("线路按 $$$ 分成两条", len(d["lines"]) == 2, [len(x["episodes"]) for x in d["lines"]])
check("空 list 不抛异常", search_mod.parse_maccms_detail({"list": []})["lines"] == [])
no_blurb = search_mod.parse_maccms_detail(
    {"list": [dict(raw["list"][0], vod_blurb="", vod_content="短" * 900)]})
check("没有 blurb 时退回 content 截断",
      no_blurb["blurb"].startswith("短") and len(no_blurb["blurb"]) <= 300, len(no_blurb["blurb"]))

print("\n2) 猜你想搜那一行要带上 (src, vid)，点详情才不必再搜一遍")
row = hot.pack_row({"title": "某剧", "kind": "tv", "year": "2026", "type": "国产剧",
                    "remarks": "更新至第2集", "pic": "http://c/1.jpg", "updated": "2026-10-01",
                    "sources": {"red", "douban"}, "probe": ("red", 456)}, {})
check("行里带 src", row["src"] == "red", row)
check("行里带 vid（数字转字符串）", row["vid"] == "456", row)
check("行仍然有 url 供片名那条链接跳转", str(row["url"]).startswith("/s/"), row["url"])
old = hot.pack_row({"title": "旧", "kind": "movie", "year": "", "type": "", "remarks": "",
                    "pic": "", "updated": "", "sources": set()}, {})
check("改造前的旧条目没 probe 时不炸，src/vid 是空串",
      old["src"] == "" and old["vid"] == "", old)
made = hot._mk("某剧", {"type": "电影", "year": "2026", "vid": 789, "source": "hongniu"}, "douban")
check("豆瓣回查那条路记的是条目自己的源，而不是占位词 douban",
      made["probe"][0] == "hongniu", made["probe"])
check("回查出来的行也能直接取详情", hot.pack_row(made, {})["vid"] == "789")

print("\n3) 按片名兜底：先检索一轮，取排序最靠前又带 ID 的那条")
calls = {"n": 0, "detail": []}
SRC = search_mod.Source(id="s1", name="能用的源", kind="maccms", api="http://x/api.php")
OFF = search_mod.Source(id="s2", name="停用源", kind="maccms", api="http://y/api.php",
                        enabled=False)


def fake_search(kw, sources=None, page=1, budget=99):
    calls["n"] += 1
    return {"results": [
        {"title": "停用源的片子", "match": "contains", "pic": "", "year": "", "area": "",
         "type": "", "actor": "", "sources": [{"id": "s2", "name": OFF.name, "vid": 5}]},
        {"title": "已消失的源的片子", "match": "contains", "pic": "", "year": "", "area": "",
         "type": "", "actor": "", "sources": [{"id": "s9", "name": "查无此源", "vid": 1}]},
        {"title": kw, "match": "exact", "pic": "http://c/2.jpg", "year": "2026",
         "area": "内地", "type": "国产剧", "actor": "张若昀",
         "sources": [{"id": "s1", "name": SRC.name, "vid": 1234}]},
    ]}


def fake_detail(src, vid, expect=""):
    calls["detail"].append((src.id, str(vid)))
    return {"ok": True, "title": "庆余年 第二季", "lines": [{"from": "l1", "episodes": [
        {"name": "第1集", "url": "http://p/1"}]}], "blurb": "少年。", "actor": "张若昀",
        "source": src.id, "source_name": src.name}


real = (search_mod.search, search_mod.detail, search_mod.load_sources)
search_mod._detail_cache.clear()
try:
    search_mod.search = fake_search
    search_mod.detail = fake_detail
    search_mod.load_sources = lambda *a, **k: [SRC, OFF]
    out = search_mod.detail_by_title("庆余年")
    check("取到了详情", out.get("ok") is True, out)
    check("停用源与已消失的源都被跳过，用的是能用那条 ID", calls["detail"] == [("s1", "1234")],
          calls["detail"])
    check("标注是按片名定位的（via=kw）", out.get("via") == "kw", out.get("via"))
    check("带上定位到的片名与匹配强度",
          out.get("matched") == "庆余年" and out.get("match") == "exact", out)
    check("卡片没有的字段从检索结果补上",
          out.get("year") == "2026" and out.get("pic") == "http://c/2.jpg", out)
    n = calls["n"]
    check("成功结果缓存，第二次不再检索一轮",
          search_mod.detail_by_title("庆余年").get("ok") is True and calls["n"] == n,
          (calls["n"], n))

    def empty(*a, **k):
        calls["n"] += 1
        return {"results": []}
    search_mod.search = empty
    search_mod._detail_cache.clear()
    bad = search_mod.detail_by_title("没有结果")
    check("一条都没搜到时给明确原因，而不是空壳", bad.get("ok") is False and bad.get("error"), bad)
    before = calls["n"]
    search_mod.detail_by_title("没有结果")
    check("失败不写缓存，下次还会真去试", calls["n"] == before + 1, (calls["n"], before))
    check("太短的片名直接拒", search_mod.detail_by_title("庆")["ok"] is False)

    def boom(*a, **k):
        raise RuntimeError("上游炸了")
    search_mod.search = boom
    search_mod._detail_cache.clear()
    got = search_mod.detail_by_title("会抛异常的片子")
    check("检索过程抛异常也只是查不到，不把整个请求炸掉",
          got.get("ok") is False and "RuntimeError" in got.get("error", ""), got)
finally:
    search_mod.search, search_mod.detail, search_mod.load_sources = real
    search_mod._detail_cache.clear()

print("\n4) /api/detail 的入参边界：详情连着播放线路一起给")
import zhuiju.app as app_mod  # noqa: E402

seen = []


def stub_detail(src, vid, t=""):
    seen.append(("id", src.id, str(vid), t))
    return {"ok": True, "title": "庆余年 第二季", "blurb": "少年。", "actor": "几十个演员",
            "lines": [{"from": "l1", "episodes": [{"name": "第1集", "url": "http://p/1"}]}],
            "source": src.id, "source_name": src.name}


def stub_by_title(kw):
    seen.append(("kw", kw))
    return {"ok": True, "title": kw, "lines": [{"from": "l1", "episodes": [
        {"name": "第1集", "url": "http://p/1"}]}]}


app_real = (app_mod.fetch_detail, app_mod.detail_by_title)
src_real = search_mod.load_sources
disabled = search_mod.Source(id="off1", name="临时停用", kind="maccms",
                             api="http://z/api.php", enabled=False)
search_mod.load_sources = lambda *a, **k: [SRC, disabled]
try:
    app_mod.fetch_detail = stub_detail
    app_mod.detail_by_title = stub_by_title
    c = app_mod.create_app().test_client()

    j = c.get("/api/detail?src=s1&vid=1234&t=庆余年").get_json()
    check("有 ID 时按 ID 走", j["ok"] is True and "lines" in j, j)
    check("ID 原样转给该源的 ac=detail", seen[-1][:3] == ("id", "s1", "1234"), seen[-1])
    # 上一版这里用 meta=1 把 lines 剥掉（"点详情不给链接"），现在面板要展示观看地址，
    # 这个参数已经删掉了。留着断言是为了钉住"没有一条静默的半旧分支"：
    # 带不带 meta 都该给完整详情，前端也就不会因为哪个入口忘了带参数而少东西。
    j = c.get("/api/detail?src=s1&vid=1234&t=庆余年&meta=1").get_json()
    check("meta=1 这个参数已经不存在：带它也是完整详情（不是被静默忽略的半旧行为）",
          "lines" in j and j.get("blurb"), j)
    check("线路确实来自该源的 ac=detail，条数与集名都在",
          [l["from"] for l in j["lines"]] == ["l1"] and j["lines"][0]["episodes"][0]["name"] == "第1集",
          j.get("lines"))
    j = c.get("/api/detail?kw=庆余年").get_json()
    check("按片名那条路也给线路（面板两条来路行为一致）", "lines" in j, j)
    check("只有片名时走兜底", seen[-1] == ("kw", "庆余年"), seen[-1])
    check("参数 t 也能当片名用", c.get("/api/detail?t=繁花").get_json()["ok"] is True)
    r = c.get("/api/detail")
    check("两样都没有 -> 400 并说清缺什么",
          r.status_code == 400 and "片名" in r.get_json()["error"], r.get_json())
    check("源对不上时退回按片名查，而不是硬报错",
          c.get("/api/detail?src=查无此源&vid=9&t=某剧").get_json()["ok"] is True)
    check("单字片名照样拒掉", c.get("/api/detail?kw=庆").status_code == 400)
    n_seen = len(seen)
    r = c.get("/api/detail?src=off1&vid=7&t=某剧")
    check("停用的源不直取，明确说已停用",
          r.status_code == 404 and "已停用" in r.get_json()["error"], r.get_json())
    check("这条 404 既没打 ac=detail 也没偷偷转去按片名查", len(seen) == n_seen,
          {"before": n_seen, "after": len(seen)})
finally:
    app_mod.fetch_detail, app_mod.detail_by_title = app_real
    search_mod.load_sources = src_real

print("\n5) 前端接线：按钮在海报角上，右键不劫持，请求只在点击之后")
html = (BASE / "zhuiju" / "templates" / "index.html").read_text(encoding="utf-8")
js = (BASE / "zhuiju" / "static" / "app.js").read_text(encoding="utf-8")
css = (BASE / "zhuiju" / "static" / "app.css").read_text(encoding="utf-8")
check("页面里已经没有右键菜单这回事",
      "ctxmenu" not in html and "ctxmenu" not in js and "contextmenu" not in js,
      re.findall(r".*contextmenu.*", js + html))
check("也没有任何 preventDefault 抢过原生右键",
      js.count("e.preventDefault()") == 2 and "contextmenu" not in js,
      re.findall(r".*preventDefault.*", js))
check("首屏（服务端渲染）每张海报右下角都有详情按钮",
      '<button class="dbtn" type="button" data-detail' in html and html.count('class="dbtn"') >= 1)
check("详情按钮带 aria-label（读屏能说出是哪一部）",
      'aria-label="查看《{{ x.title }}》的详情"' in html)
check("卡片改成海报+片名两层：整张卡片不再是个链接（按钮不能嵌在 a 里）",
      '<div class="hotcard">' in html and '<a class="hotlink"' in html and
      '<a class="hotcard"' not in html)
check("JS 重铺猜你想搜时用的是同一套结构",
      '<div class="hotcard">' in js and '<a class="hotlink"' in js and
      js.count('class="dbtn"') == 2, js.count('class="dbtn"'))
check("搜索结果卡片的封面也带详情按钮", "dbtn + '</div>'" in js)
check("详情数据挂在按钮自己的 data-* 上",
      'data-detail data-title="' in js and "dAttrs + '>详情</button>'" in js)
check("多源时把 (id, vid) 列表放进 data-srcs，供面板换源",
      "data-srcs=" in js and 'esc(JSON.stringify((r.sources || [])' in js)
# 猜你想搜那些行只有片名来自缓存，换源看的每一颗按钮都要有自己的 (源, ID)；
# 少这一条的话面板上就永远只有一行的详情，"换源看"整排按钮不会出现
check("猜你想搜的海报也带 data-srcs（不然面板上没有换源看）",
      'esc(JSON.stringify((x.sources || [])' in js,
      re.findall(r"data-srcs[^+]{0,60}", js))
check("服务端渲染那份猜你想搜也把 sources 写进 data-srcs",
      "data-srcs='{{ x.sources | default([], true) | tojson }}'" in html,
      re.findall(r"data-srcs=[^>]{0,60}", html))
check("JSON 属性用单引号包：tojson 出来的双引号会顶穿双引号属性",
      'data-srcs="' not in html and " | tojson }}'" in html,
      re.findall(r'data-srcs="[^"]*', html)[:2])
check("旧缓存没有 src/vid 时模板不报错（default('', true)）",
      "x.src | default('', true)" in html and "x.vid | default('', true)" in html)
check("点击走的是按钮代理，不是整张海报",
      "openDetail(specOf(btn))" in js
      and re.search(r"closest\(coarse\(\) \? '\.hcover, \.cover, \.dbtn' : '\.dbtn'\)", js) is not None
      and "hit.classList.contains('dbtn') ? hit : hit.querySelector('.dbtn')" in js,
      re.findall(r"closest\(.*?\);", js))
lazy = js[js.index("function openDetail"):js.index("function closeDetail")]
check("详情请求只在 openDetail 一处发起", js.count("getJSON(detailURL(s))") == 1)
check("面板的请求不带 meta（要的就是线路），两条来路都不带",
      "&meta=1" not in js and "meta=" not in js[js.index("const detailURL"):],
      js[js.index("const detailURL"):js.index("const detailURL") + 320])
check("渲染卡片/列表时完全不碰详情接口",
      "detailURL" not in js[js.index("function card("):js.index("function renderPager")] and
      "detailURL" not in js[js.index("function hotCard("):js.index("function hotCols")] and
      "openDetail" not in js[js.index("function card("):js.index("function renderPager")] and
      "getJSON" not in js[js.index("function hotCard("):js.index("function hotCols")])
panel_js = js[js.index("function fillDetail"):js.index("function openDetail")]
check("面板渲染观看地址（fillDetail 里调 linesHTML，并且标明是从详情面板点的）",
      "linesHTML(d, {" in panel_js and "place: 'panel'" in panel_js,
      re.findall(r"linesHTML\([^)]*", panel_js))
# 折叠不是"藏起来"这么简单：120 集一次插进 DOM 会把面板撑成长条，绝大多数没人点
check("线路默认折叠、集数点了才铺（DOM 里先只有线路名）",
      '<div class="lbody" hidden>' in js and "body.dataset.filled" in js
      and "body.innerHTML = epsHTML(" in js, re.findall(r"\.lbody[^;]{0,40}", js)[:3])
check("线路数据留在内存里按 id 取，不往属性里塞整份 JSON",
      "lineStore[id] = d.lines" in js and 'data-ls="' in js and "data-lines=" not in js,
      re.findall(r"lineStore[^;]{0,30}", js)[:3])
check("展开/收起用 aria-expanded，不是靠猜状态",
      re.search(r"""setAttribute\((['"])aria-expanded\1""", js) is not None
      and 'aria-expanded="false"' in js,
      re.findall(r"aria-expanded[^\"']{0,20}", js)[:4])
check("卡片线路与面板线路共用同一套折叠（委托在 document 上，两处都管得到）",
      js.count("closest('.lhead')") == 1 and js.count("closest('.eps a[href]')") == 1)

print("\n6) 观看点击的上报：报什么、怎么报、不能挡住跳转")
up = js[js.index("function sendClick"):js.index("document.addEventListener('click', (e) => {\n    const a =")]
check("用 sendBeacon 发，链接该跳就跳（埋点不阻塞跳转）",
      "navigator.sendBeacon('/api/click'" in up and "application/json" in up, up[:200])
check("没有 sendBeacon 时退到 fetch + keepalive",
      "keepalive: true" in up and "credentials: 'same-origin'" in up)
check("埋点整个包在 try 里：报错也不能影响人点开播放",
      "try {" in up and "catch" in up)
rep = js[js.index("const a = e.target.closest('.eps a[href]')"):]
rep = rep[:rep.index("\n  });")]
check("报的是当前这条链接与它所属线路的上下文",
      "kind: 'play'" in rep and "url: a.href" in rep
      and "line: (line && line.dataset.line) || ''" in rep
      and "ep: a.dataset.ep" in rep and "place: ctx.place || 'card'" in rep,
      re.findall(r"^\s+\w+: [^\n]+", rep, re.M)[:8])
op = js[js.index("function openDetail"):]
op = op[:op.index("if (!dpBack)")]
check("点「详情」按钮本身也报一条 kind=detail",
      "kind: 'detail'" in op and "sendClick(" in op, op[:200])
check("详情那一笔不许有 url 字段（它本来就没有地址，后端只给 play 校 scheme）",
      "url" not in op, re.findall(r"url[^\n]{0,30}", op)[:2])
check("报的 place 分得清海报来自猜你想搜还是搜索结果",
      "from: el.closest('.hotcard') ? 'hot' : 'card'" in js and "place: s.from || 'card'" in op,
      re.findall(r"place: s\.from[^\n]*", op))
check("上报只在点开这一条路径上，渲染列表时一条都不发",
      "sendClick" not in js[js.index("function card("):js.index("function renderPager")]
      and "sendClick" not in js[js.index("function hotCard("):js.index("function hotCols")],
      None)
check("不去 preventDefault：点了就是要打开那个播放页",
      "preventDefault" not in rep)
check("线路名与集名都写在 data- 上，报告才拼得出「哪条线路第几集」",
      'data-line="' in js and 'data-ep="' in js)
check("地址由后端筛 scheme，前端只把自己 href 的绝对地址发过去",
      "url: a.href" in js and "javascript:" not in js[js.index("function epsHTML"):
                                                js.index("function epsHTML") + 700],
      None)
check("同一部片连开两次不重复请求（在途与结果各一层缓存）",
      "if (!dpending[key])" in lazy and "dcache[key]" in lazy)
check("换源/切条目后旧请求回来不会填新面板（token 校验）",
      "token === dpToken" in lazy and "dpToken++" in js[js.index("function closeDetail"):])
# 失败结果也会被写进 dcache（.then 里不看 ok 就存），所以重试必须把它清掉，
# 否则点"重试"会立刻把上一次的失败又显示一遍
check("失败有重试入口，且会清掉缓存里的失败结果",
      "dpretry" in js and "delete dcache[dkey(s)]" in js)
check("Esc 关面板", "e.key === 'Escape' && !dpEl.hidden" in js)
check("hidden 真的能盖住 flex/block：全站一条 [hidden]，带 !important",
      "[hidden] { display: none !important; }" in css,
      re.findall(r"\[hidden\][^\n]{0,60}", css)[:3])
check("不再各打各的补丁（那正是漏掉一个元素就复发的写法）",
      ".dpanel[hidden]" not in css and ".homebtn[hidden]" not in css, None)
check("显隐只用 hidden 表达，不写死 aria-hidden",
      'aria-hidden' not in html[html.index('<aside class="dpanel"'):html.index("</main>")])
check("面板滑入动画与骨架屏闪动在减少动效时都关掉",
      "@media (prefers-reduced-motion: reduce)" in css[css.index(".dpanel"):])
op = js[js.index("dpEl.hidden = false;"):js.index("dpClose.focus()")]
check("点开是从屏幕外滑进来：先摘 hidden、强制一次布局、再加 .on",
      "void dpEl.offsetWidth;" in op and op.index("dpEl.hidden = false;")
      < op.index("void dpEl.offsetWidth;") < op.index("dpEl.classList.add('on');"),
      op[:200])
check("强制重排只在「摘 hidden → 加 .on」这一段里出现一次（别处不需要，多一处就多个坑）",
      js[js.index("function openDetail("):js.index("function closeDetail(")].count(
          "void dpEl.offsetWidth;") == 1, None)
cl = js[js.index("function closeDetail("):js.index("dpClose.addEventListener")]
check("关闭是滑出去再 display:none，时长从 CSS 读、不在 JS 里抄一份",
      "getComputedStyle(dpEl).transitionDuration" in cl and "dur * 1000 + 40" in cl
      and not re.search(r"setTimeout\([^\n]*?,\s*(260|600)\)", cl),
      re.findall(r"setTimeout\([^\n]{0,60}", cl))
check("滑出没播完之前不藏（期间又点开就不藏）",
      "if (!dpEl.classList.contains('on')) dpEl.hidden = true;" in cl, None)
out = js[js.index("点面板外面也收起"):]
check("点面板外面也关：只认鼠标左键，面板已经关了就不再管（右键本站不劫持）",
      "e.button !== 0 || dpEl.hidden" in out, None)
check("面板里面的点击不算外面（换源那排 chip、折叠的观看地址都长在面板里）",
      "if (dpEl.contains(e.target)) return;" in out, None)
check("卡片上那颗「详情」不算外面：开着面板点另一张是换一部看，不是关窗",
      "e.target.closest(coarse() ? '.dbtn, .hcover, .cover' : '.dbtn')" in out
      # 命中区两处共用一份说法，改 opener 必须一起改这里
      and "coarse() ? '.hcover, .cover, .dbtn' : '.dbtn'" in js, None)
check("外面那一下不抢焦点：只有 × 与 Esc 才把焦点还给当初那颗按钮",
      "closeDetail(false)" in out and "if (refocus && dpBack && dpBack.focus)" in cl, None)
check("× 的监听器包一层箭头函数（直接把 closeDetail 交出去会把 event 当成 refocus 参数）",
      "dpClose.addEventListener('click', () => closeDetail())" in js, None)
check("起点在屏幕外这件事写在 CSS 里（右侧 translateX、窄屏 translateY）",
      "transform: translateX(calc(100% + 20px))" in css and "transform: translateY(calc(100% + 20px))" in css,
      None)
check("窄屏时面板盖满并锁住页面滚动", "body.dp-open { overflow: hidden; }" in css)
check("详情按钮常驻可见（不靠 hover 才发现），触屏上给满不透明度",
      ".dbtn {" in css and "@media (hover: none) { .dbtn { opacity: 1; } }" in css)
check("按钮压在封面之上（封面 img 是 z-index:1）",
      re.search(r"\.dbtn \{[^}]*z-index: 2", css) is not None)
check("按钮用压在图片上的那对 token（不跟主题翻转，暗色下才不会黑压黑）",
      "var(--poster-ink)" in css[css.index(".dbtn {"):css.index(".dbtn:hover")] and
      "var(--poster-scrim)" in css[css.index(".dbtn {"):css.index(".dbtn:hover")],
      css[css.index(".dbtn {"):css.index(".dbtn:hover")])
check("这对 token 在两个主题里都定义了",
      css.count("--poster-ink:") == 2 and css.count("--poster-scrim:") == 2,
      (css.count("--poster-ink:"), css.count("--poster-scrim:")))
check("换源按钮的选中态按字符串比较（接口给的是数字 ID）",
      "String(x.id) === String(cur.src) && String(x.vid) === String(cur.vid)" in js)
# 只有一个源也要有这一排：它说的是"这条详情是哪个源给的"，不是可有可无的装饰
check("单源也渲染这一排（不再 length > 1 才画）",
      "if (!srcs || !srcs.length) return '';" in js and "srcs.length > 1 ? '换源看' : '来源'" in js,
      re.findall(r"srcs\.length[^{]{0,40}", js)[:3])
check("按片名兜底那条路（srcs 本来是空的）拿到详情后把这一排补上",
      "insertAdjacentHTML('beforebegin', chipsRow(" in js and "!dpBody.querySelector('.dpchips')" in js,
      re.findall(r"insertAdjacentHTML\([^\n]{0,60}", js)[:2])
check("点当前这个源不重开、也不再上报一条（不然一次查看被记成好几次）",
      "if (String(x.id) === String(s.src) && String(x.vid) === String(s.vid)) return;" in js)
check("用法说明改成了详情按钮，不再提右键",
      "详情" in html and "右键" not in html[html.index('<div class="placeholder"'):html.index("</main>")])

print("\n7) 海报淡入：不是一片张着等，也不是一片透明")
fade = css[css.index("html.hasjs .cover img"):css.index("@media (prefers-reduced-motion: reduce)",
                                                     css.index("html.hasjs .cover img"))]
check("三种海报盒（结果卡片、猜你想搜、详情面板）都在淡入范围内",
      ".cover img" in fade and ".hcover img" in fade and ".dpcover img" in fade, fade[:200])
check("默认透明、加载完淡上来，时长在 .4s 以内（比这长就像幻灯片）",
      "opacity: 0" in fade and "transition: opacity .34s ease" in fade
      and "opacity: 1 }" in css[css.index(".cover img.loaded"):css.index("@media (prefers-reduced-motion",
                                                                        css.index(".cover img.loaded"))],
      None)
check("第二次见这张图直接显示、不走过渡（.noanim）——翻页翻回来就是这条",
      "html.hasjs .cover img.noanim" in css and "transition: none" in
      css[css.index("html.hasjs .cover img.noanim"):
          css.index("@media (prefers-reduced-motion: reduce)", css.index("html.hasjs .cover img.noanim"))],
      None)
check("闸门挂在 html.hasjs 上：禁用 JS 与爬虫拿不到 .loaded，也不能把海报变成一片空白",
      "html.hasjs" in fade and (BASE / "zhuiju" / "templates" / "_theme.html").read_text(encoding="utf-8")
      .count("classList.add('hasjs')") == 1, None)
theme = (BASE / "zhuiju" / "templates" / "_theme.html").read_text(encoding="utf-8")
check("这个标记和主题一样在样式表之前的内联脚本里打，晚一帧就是先看见图再看见它变透明",
      theme.index("hasjs") < theme.index("dataset.theme"), None)
rev = js[js.index("function revealIn(root)"):js.index("const noMotion")]
check("已经缓存好的图当场显示（load 事件早发过了，只等事件就永远透明）",
      "(im.complete && im.naturalWidth)" in rev and "classList.add('loaded', 'noanim')" in rev, None)
check("第二次见到同一张海报不再淡：翻回来的那页不该像重新加载",
      "shownPics.has(src)" in rev and "im.classList.add('loaded')" in rev
      and "shownPics.add(src)" in rev, None)
check("记下的地址有上限（开一整天的标签页不能无限攒）",
      "PICS_MAX = 3000" in js and "shownPics.size < PICS_MAX" in rev, None)
check("同一棵子树重复 reveal 不重复挂监听", "if (im.dataset.shown) return;" in rev, None)
check("兜一个超时：卡在既不 load 也不 error 的连接上时，宁可显示也别留空白，而且不再淡",
      "setTimeout(() => im.classList.add('loaded', 'noanim'), 8000)" in rev, None)
for anchor in ("revealIn(resultsEl);", "revealIn(grid);", "revealIn(dpBody);", "revealIn(document);"):
    check("渲染点都调了它：" + anchor, anchor in js, None)
check("服务端渲染那 12 条不再靠 inline onload（缓存图根本不触发它）",
      'onload="this.closest' not in html, re.findall(r"<img[^>]{0,120}", html)[:2])
check("暗色主题不再用 opacity 压海报，否则和淡入抢同一个属性",
      "[data-theme=\"dark\"] img { filter: brightness(.94); }" in css
      and "dark\"] img, [data-theme=\"dark\"] .hcover img { opacity" not in css,
      re.findall(r'\[data-theme="dark"\] img[^\n]{0,60}', css)[:2])

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
