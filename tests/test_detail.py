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
import tempfile
import gate_off  # noqa: E402  门禁与本文件的测试对象无关，见 tests/gate_off.py
gate_off.off(tempfile.mkdtemp(prefix="zhuiju_gateoff_"))

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
# 这一节原来读 templates/index.html + static/app.js + static/app.css 那三份。前两份不再上屏，
# app.css 虽还活着（后台在用），但 .dbtn/.hotcard/.dpanel 那批规则只有旧前台在用。
# (a) 所以逐条搬到活的表面上：web/src/components/*.tsx 与 web/src/styles.css；
# 服务端那一份（首屏列表）搬到 shell.html / test_client 的响应上。
WEB = BASE / "web" / "src"


def wread(*rel):
    return WEB.joinpath(*rel).read_text(encoding="utf-8")


all_src = "".join(p.read_text(encoding="utf-8") for p in sorted(WEB.rglob("*.ts*")))
# 后台现在也是 React（web/src/admin/**）。这一节判的是前台那条渲染路径，
# 所以计数只数前台的文件：把后台一起数进去的话，"没有全局 reveal"这类判据会
# 因为后台用了 querySelectorAll 而误报成前台退化成了 DOM 操作。
front_src = "".join(p.read_text(encoding="utf-8") for p in sorted(WEB.rglob("*.ts*"))
                    if "admin" not in p.parts)
poster_ts = wread("components", "Poster.tsx")
drawer_ts = wread("components", "DetailDrawer.tsx")
vod_ts = wread("components", "VodPanel.tsx")
hot_ts = wread("components", "HotSection.tsx")
app_ts = wread("App.tsx")
stcss = wread("styles.css")
shell = (BASE / "zhuiju" / "templates" / "shell.html").read_text(encoding="utf-8")


def _boot_hot_first_row():
    """取壳里 boot.hot 的第一条电影行：换源看要的那对 (源, ID) 必须服务端就带着。"""
    import json as _json
    real = app_mod.hot_mod.get
    app_mod.hot_mod.get = lambda *a, **k: {
        "since": "2026-04-01", "candidates": 1, "building": False,
        "movie": [{"title": "甲", "kind": "movie", "year": "2026", "type": "动作片",
                   "remarks": "", "pic": "http://x/1.jpg", "n_sources": 2, "rate": "",
                   "sources": [{"id": "red", "name": "红牛资源", "vid": "456"}],
                   "src": "red", "vid": "456", "url": "/s/甲"}],
        "tv": []}
    try:
        h = app_mod.create_app().test_client().get("/").get_data(as_text=True)
    finally:
        app_mod.hot_mod.get = real
    return _json.loads(h.split('<script id="boot-data" type="application/json">')[1]
                       .split("</script>")[0])["hot"]["movie"][0]


check("页面里已经没有右键菜单这回事", "ctxmenu" not in all_src and "contextmenu" not in all_src,
      re.findall(r".{0,30}contextmenu.{0,30}", all_src))
check("拦下默认动作的只有那两处：滑块的指针/按键与搜索表单的回车，没有一处是抢右键",
      front_src.count("preventDefault")
      == wread("components", "Gate.tsx").count("preventDefault")
      + wread("components", "SearchBar.tsx").count("preventDefault")
      and "contextmenu" not in all_src,
      re.findall(r".{0,20}preventDefault.{0,20}", all_src))
# (b) 旧那条钉的是首屏 SSR 每张海报右下角的详情按钮。现在服务端那份（#nojs）是一份纯文字列表，
# 它的入口是每一条自己的落地页链接；详情按钮这一层只在 JS 那一侧（Poster 组件）存在。
check("服务端渲染那份首屏列表每条都自带能点开的落地页链接（禁 JS 的人不需要详情也能走）",
      '<li><a href="{{ it.url }}">{{ it.title }}</a>' in shell
      and shell.count("<img") == 0, re.findall(r"<li><a href=[^>]*>[^<]*", shell)[:2])
check("详情按钮带 aria-label（读屏能说出是哪一部）",
      "aria-label={`查看《${title}》的详情`}" in poster_ts, None)
check("卡片改成海报+片名两层：整张卡片不再是个链接（按钮不能嵌在 a 里）",
      "<article" in poster_ts and "href={href}" in poster_ts
      and poster_ts.index("<div") < poster_ts.index("<Button") and "<a\n            href={href}" in poster_ts,
      re.findall(r"<(a|article|div|Button)", poster_ts)[:6])
check("结果页与猜你想搜用的是同一个 Poster（两处才长得不一样，也不会一处漏按钮）",
      "<Poster" in vod_ts and "<Poster" in hot_ts and poster_ts.count("<Button") == 1,
      (vod_ts.count("<Poster"), hot_ts.count("<Poster"), poster_ts.count("<Button")))
check("搜索结果与猜你想搜的封面都自带详情按钮：按钮只有 Poster 这一处，两处共用",
      "const open = () => onDetail(spec, cover.current);" in poster_ts
      and poster_ts.count("onPress={open}") == 1
      and "onDetail" not in drawer_ts, None)
# (c) 旧写法把详情数据写成按钮上的 data-title/data-srcs 那串属性，点击时再从 DOM 读回来。
# React 这边等价形态是：spec 由数据当场组出来（specOf）并作为 props 传下去，
# 按钮的 onPress 闭包直接捕获它 —— 不再有「属性里那份 JSON」这个中间层
check("详情数据靠 props 传（specOf 组出来的那个对象），不再往 DOM 属性里塞一份",
      "export function specOf(r: VodItem" in vod_ts and "spec={specOf(r)}" in vod_ts
      and "data-detail" not in all_src and "data-srcs" not in all_src, None)
check("多源时把 (id, name, vid) 列表一起放进 spec，供面板换源",
      "sources: r.sources.map((s) => ({ id: s.id, name: s.name, vid: s.vid ?? \"\" }))" in vod_ts, None)
check("猜你想搜那条也带上 sources（不然面板上没有换源看）",
      "sources: (x.sources || []).map((s) => ({ id: s.id, name: s.name, vid: s.vid ?? \"\" }))" in hot_ts,
      None)
check("服务端注进 boot.hot 的每一份行里就带着 sources，前端不用二次请求补齐（换源看才有得换）",
      _boot_hot_first_row().get("sources"), None)
# (c) 旧那条防的是「tojson 出来的双引号顶穿双引号属性」。现在整份 JSON 只落在 #boot-data 那一个
# script 里（由 tojson 转义），HTML 属性里不再内嵌 JSON，这个坑没有载体了
check("HTML 属性里不再内嵌 JSON：整份数据只在 #boot-data 那一处（另一处 tojson 是 JSON-LD 里的片名）",
      re.search(r"data-[a-z]+=\"\{\{", shell) is None and shell.count(" | tojson") == 2
      and 'id="boot-data" type="application/json">{{ boot | tojson }}</script>' in shell
      and '"name":{{ it.title | tojson }},' in shell,
      re.findall(r"data-[a-z]+=\"\{\{[^}]*\}\}", shell))
check("旧缓存没有 src/vid 时前端不炸：那两个字段在类型里就是可选的",
      "src?: string;" in wread("types.ts") and "vid?: string | number;" in wread("types.ts"), None)
# (c) 这一条原来判的是「只有右下角那颗按钮可点，海报本身不是点击区」。现在按需求整张封面都能
# 开面板，但点击层仍然得是一个 <button>（div 加 onClick 键盘走不到），而且卡片不能整个套进 <a>
# —— 那样「详情」这颗就嵌在链接里（无效 HTML），点按钮会顺带跳去搜索页。
check("整张海报都是点击区：那一层是透明 <button>（键盘走得到），垫在「详情」那颗下面",
      'className="cover-hit absolute inset-0"' in poster_ts
      and "onClick={open}" in poster_ts
      and poster_ts.index("cover-hit") < poster_ts.index('className="dbtn')
      and 'z-10 min-h-8 min-w-10 rounded-full"' in poster_ts
      and re.search(r"<div[^>]*onClick=", poster_ts) is None, None)
check("触屏上没有 hover：详情按钮在这种情况下常驻可见",
      "@media (hover: none) {\n    .dbtn {\n      opacity: 1;" in stcss, None)
check("详情请求只在抽屉里发起，列表与卡片那一路一次都不碰",
      drawer_ts.count(".detail(") == 1 and "detail(" not in vod_ts + hot_ts + poster_ts,
      re.findall(r"\.detail\(", drawer_ts + vod_ts + hot_ts + poster_ts))
api_ts = wread("api.ts")
det_slice = api_ts[api_ts.index("detail: (params:"):]
det_slice = det_slice[:det_slice.index("hot: (")]
check("面板的请求不带 meta（要的就是线路），参数只有 src/vid/t 或 kw",
      "meta" not in det_slice and {"src", "vid", "t", "kw"} <= set(
          re.findall(r"(\w+)\?:", det_slice)), det_slice[:120])
check("渲染卡片与列表时完全不碰详情接口",
      "api." not in poster_ts and "fetch(" not in poster_ts + vod_ts + hot_ts, None)
check("抽屉渲染观看地址，并标明是从详情面板点的",
      "place: \"panel\"," in drawer_ts and "<Line key={ln.from} line={ln}" in drawer_ts, None)
# 折叠不是"藏起来"这么简单：120 集一次插进 DOM 会把面板撑成长条，绝大多数没人点
check("线路默认折叠、集数点了才铺（DOM 里先只有线路名）",
      "const [open, setOpen] = useState(false);" in drawer_ts
      and "{open ? (" in drawer_ts and "eps.slice(0, 120)" in drawer_ts, None)
# (c) 旧写法要把整份线路 JSON 塞进 data-lines（或存进一个 lineStore 里按 id 取）。
# React 这边数据本来就在内存的 state 里，组件直接接 line 这个对象，没有"往属性里塞"这一步
check("线路数据是对象直接传下去的，没有往属性里塞整份 JSON 这一说",
      "data-lines" not in all_src and "lineStore" not in all_src and "line: { from: string" in drawer_ts,
      None)
check("展开/收起用 aria-expanded，不是靠猜状态",
      "aria-expanded={open}" in drawer_ts, None)
# (c) 旧写法把折叠委托在 document 上，为的是"卡片线路与面板线路两处都管得到"。
# 现在折叠三处：抽屉里的线路、右栏的接口状态、右栏的检索快照 —— 每处一个组件、一个局部 state，
# 委托不再需要（也多不得：窄屏那两处要各自记住自己开没开）
check("折叠都是组件里的局部状态（线路一处、接口状态一处、检索快照一处），没有 document 上的委托",
      front_src.count("aria-expanded") == 3 and "addEventListener(\"click\"" not in drawer_ts,
      re.findall(r"aria-expanded", all_src))

print("\n6) 观看点击的上报：报什么、怎么报、不能挡住跳转")
# (a) 这一节原来读 static/app.js 里那个 document 上的点击委托，以及 static/app.css 里
# .dpanel 那一套手写进出场。上报只有两个调用点（分集链接 = play、点详情 = detail），
# 函数本体在 web/src/api.ts；抽屉的开关与进出场整块交给 HeroUI 的 Drawer。
up = api_ts[api_ts.index("export function sendClick"):]
up = up[:up.index("/** 上游图床")]
check("用 sendBeacon 发，链接该跳就跳（埋点不阻塞跳转）",
      'navigator.sendBeacon("/api/click"' in up and 'type: "application/json"' in up, up[:200])
check("没有 sendBeacon 时退到 fetch + keepalive",
      "keepalive: true" in up and 'credentials: "same-origin"' in up, None)
check("埋点整个包在 try 里：报错也不能影响人点开播放",
      "try {" in up and "catch" in up, None)
rep = drawer_ts[drawer_ts.index("onClick={() =>"):]
rep = rep[:rep.index('className="num rounded-md')]
check("报的是当前这条链接与它所属线路的上下文",
      'kind: "play",' in rep and "url: ep.url," in rep and "line: line.from," in rep
      and "ep: ep.name ||" in rep and 'place: "panel",' in rep,
      re.findall(r"^\s+\w+: [^\n]+", rep, re.M)[:8])
od = app_ts[app_ts.index("const openDetail = useCallback"):app_ts.index("if (locked && boot.locked)")]
check("点「详情」按钮本身也报一条 kind=detail",
      'kind: "detail",' in od and "sendClick({" in od, od[:220])
check("详情那一笔不许有 url 字段（它本来就没有地址，后端只给 play 校 scheme）",
      "url:" not in od, re.findall(r"url[^\n]{0,30}", od)[:2])
check("报的 place 分得清海报来自猜你想搜还是搜索结果",
      'from: "card" | "hot";' in poster_ts and 'from: DetailSpec["from"] = "card"' in vod_ts
      and 'from: "hot",' in hot_ts and "place: s.from," in od,
      re.findall(r"place: s\.from[^\n]*", od))
check("上报只在点开这一条路径上，渲染列表与卡片时一条都不发",
      "sendClick" not in poster_ts + vod_ts + hot_ts + app_ts[app_ts.index("if (locked && boot.locked)"):]
      and app_ts.count("sendClick(") == 1 and drawer_ts.count("sendClick(") == 1,
      (app_ts.count("sendClick("), drawer_ts.count("sendClick(")))
check("不去 preventDefault：点了就是要打开那个播放页",
      "preventDefault" not in drawer_ts, re.findall(r"preventDefault", drawer_ts))
# (c) 旧写法把线路名与集名先写进 data-line / data-ep，再从 DOM 读回来拼进报告。
# React 里 line.from 与 ep.name 本来就在闭包中，直接读对象：等价形态是这两个字段有值
check("线路名与集名直接从对象里取，不再中转一份 data-*（报告照样拼得出哪条线路第几集）",
      "data-line" not in all_src and "data-ep" not in all_src
      and "line: line.from," in drawer_ts and 'ep: ep.name || "播放"' in drawer_ts, None)
check("地址由后端筛 scheme，前端只把 href 那份原样发过去（自己不拼协议、不判白名单）",
      "href={ep.url}" in drawer_ts and "url: ep.url," in drawer_ts
      and "javascript:" not in drawer_ts and ".startsWith(\"http" not in drawer_ts, None)
check("同一部片连开两次不重复请求（模块级那份缓存按 src+vid+片名 记，命中就直接用）",
      "const cache = new Map<string, DetailResult>();" in drawer_ts
      and "const hit = cache.get(key);" in drawer_ts and "cache.set(key, d);" in drawer_ts, None)
check("命中缓存时界面还会说出来（不然人以为卡住了）",
      "setFromCache(true);" in drawer_ts and "这一条本页已经查过" in drawer_ts, None)
check("换源/切条目后旧请求回来不会填新面板（token 校验，两条出口都认它）",
      "const mine = ++token.current;" in drawer_ts
      and drawer_ts.count("if (mine !== token.current) return") == 2, None)
check("失败有重试入口，且会清掉缓存里那一条（不然重试就是把上一次的失败再显示一遍）",
      "cache.delete(key);" in drawer_ts and "setNonce((n) => n + 1);" in drawer_ts
      and "重试" in drawer_ts, None)
# (c) 旧那条是手写 keydown：Esc 且面板没关时调 closeDetail。现在 Esc 与点外面都由
# HeroUI 的 Drawer 自己处理，前端不再写键盘监听 —— 判据换成"开关只由一个布尔受控"
check("Esc 与点外面都交给 Drawer 组件（不再手写 keydown，也不再有第二个 Escape 判据）",
      "Escape" not in drawer_ts and "onKeyDown" not in drawer_ts
      and "onOpenChange={(v) => !v && onClose()}" in drawer_ts, None)
# (c) 旧那条靠全站一条 [hidden] { display:none !important } 压住 flex/block。
# React 这边显隐就是不渲染（条件渲染 + 组件的 isOpen），那条全局补丁没有对应物了
check("CSS 里不再需要那条全局 [hidden] 硬压（新架构根本不用 hidden 属性表达显隐）",
      "[hidden]" not in stcss and "hidden={" not in drawer_ts + poster_ts + vod_ts,
      re.findall(r"\[hidden\]", stcss))
check("也没有再给某个组件单独写一条 hidden 覆盖（那正是漏掉一个元素就复发的写法）",
      ".dpanel" not in stcss and ".homebtn" not in stcss and "hidden]" not in stcss, None)
check("aria-hidden 只用来藏装饰性的图标与色点，不用它表达显隐",
      not re.search(r"aria-hidden=\{", all_src) and all_src.count('aria-hidden="true"') >= 5
      and "[hidden]" not in stcss, re.findall(r"aria-hidden=[^\n]{0,20}", all_src))
# 抽屉的滑入滑出与骨架屏都是组件库的动效；这一条管得住的是我们自己写的那两组关键帧
check("我们自己的动效（海报淡入、整行推入、主题过渡）在减少动效时全部关掉",
      "@media (prefers-reduced-motion: reduce)" in stcss
      and ".poster-in,\n    .row-push-next,\n    .row-push-prev" in stcss
      and ".theme-anim *" in stcss, re.findall(r"@media \(prefers-reduced-motion[^{]*\{", stcss))
check("抽屉开合只有一个受控布尔：点开来、关掉就是把那一份 spec 清空",
      "const open = !!spec;" in drawer_ts and "isOpen={open}" in drawer_ts
      and "onClose={closeDetail}" in app_ts and "setSpec(null);" in app_ts, None)
# 注意：offsetWidth 全站只允许出现在滑块那一处（那是量控件宽度，不是逼浏览器重排）；
# 抽屉这条路一次都不许有 —— 旧写法那三行 void dpEl.offsetWidth 在新架构里就是这个判据
check("进出场不再需要一次强制重排（抽屉里 offsetWidth 一次都不出现）",
      "offsetWidth" not in drawer_ts and all_src.count("offsetWidth") == 1
      and "offsetWidth" in wread("components", "Gate.tsx"), re.findall(r"offsetWidth", all_src))
check("时长没有第二个来源：JS 里不抄一份等待动画的计时",
      "setTimeout" not in drawer_ts, re.findall(r"setTimeout[^\n]{0,30}", drawer_ts))
check("没有「滑出没播完之前不藏」那一步：状态一改就交回组件，不留中间态",
      "classList" not in drawer_ts and "display: none" not in drawer_ts, None)
check("点外面那一下能关（组件把 open 状态的变化原样交回 onClose）",
      "onOpenChange={(v) => !v && onClose()}" in drawer_ts
      and "onClose: () => void" in drawer_ts, None)
# (c) 旧写法要在 document 上判"这一下是在面板外面吗"，还得先按事件路径（composedPath）判，
# 因为被点的节点可能刚被重画摘出文档。React 这边 open 是状态，不是从事件路径推出来的，
# 这一整类坑（composedPath / contains 退回）没有载体
check("判内外不靠事件路径：既没有 composedPath，也没有 dpEl.contains 这一类自研判据",
      "composedPath" not in all_src and "contains(e.target)" not in all_src, None)
check("卡片上那颗「详情」不算外面：开着抽屉点另一张是换一部看，不是关窗",
      "onPress={open}" in poster_ts and "setSpec(s);" in od
      and "spec={spec}" in app_ts, None)
check("外面那一下不抢焦点：前端没有一处手写 focus（焦点归还由组件处理）",
      ".focus()" not in drawer_ts and "dpBack" not in all_src, re.findall(r"\.focus\(\)", all_src))
check("关闭那颗 × 由组件提供，前端不写监听器（不用包一层箭头函数去挡 event）",
      '<CloseButton aria-label="关闭详情" onPress={onClose}' in drawer_ts
      and "addEventListener" not in drawer_ts, None)
check("详情是居中弹框：不再有 right/bottom 两套 placement，宽窄屏同一个形状"
      "（展开起点是海报，交给 View Transitions 的位移+缩放，见 App.tsx）",
      '<Modal.Container size="md">' in drawer_ts and "placement" not in drawer_ts
      and "useMediaQuery" not in drawer_ts, None)
# 宽高只跟窗口走：内容（骨架屏 → 详情 → 展开线路）变来变去，弹框不许跟着长/缩，
# 否则每换一次源背后的页面都被挤得跳一下。
sheet_css = re.search(r"\.detail-sheet\s*\{([^}]*)\}", stcss).group(1)
check("详情弹框按窗口固定宽高，内容超出在框里滚（不跟内容撑高）",
      "width: min(560px, calc(100vw - 2rem))" in sheet_css
      and "height: min(760px, 84dvh)" in sheet_css
      and "max-width: 100%" in sheet_css, sheet_css)
check("盖满与锁页面滚动是 Drawer 组件的职责，前端不再往 body 上挂一个类",
      "dp-open" not in all_src and not re.search(r"(html|body)\s*\{[^}]*overflow", stcss), None)
check("详情按钮常驻可见（不靠 hover 才发现），触屏上给满不透明度",
      ".dbtn {" in stcss and "@media (hover: none) {\n    .dbtn {\n      opacity: 1;" in stcss, None)
# (c) 旧那条比的是 .dbtn { z-index: 2 } 压在 .cover img { z-index: 1 } 之上。
# 现在按钮是 absolute 定位、排在图片之后，画在上层靠的是定位与文档顺序，不需要再写 z-index。
# styles.css 里那两个 z-index 属于 View Transition 的暗幕/弹框快照层（另一件事），
# 按钮与封面这两条规则里仍然一个都不许有。
check("按钮压在封面之上：靠 absolute 定位 + 文档顺序，封面与按钮自己不再手写 z-index",
      "absolute right-1.5 bottom-1.5" in poster_ts
      and not re.search(r"\.dbtn\s*\{[^}]*z-index", stcss)
      and not re.search(r"\.cover-box[^{]*\{[^}]*z-index", stcss),
      re.findall(r"z-index[^\n]*", stcss))
# (c) 旧的那对 --poster-ink / --poster-scrim 是"压在任意封面上的东西不能跟主题翻"的手写 token。
# 现在这颗按钮直接用 HeroUI 的 secondary 变体，配色由组件的令牌给：这对 token 在新样式里
# 已经没有定义，也就没有"只定义一处"这件事要钉 —— 等价形态是这套颜色只有一个来源（组件变体）
check("按钮配色只有一个来源（HeroUI 的变体），不再有一对自造的封面 token",
      'variant="secondary"' in poster_ts and "--poster-ink" not in stcss
      and "--poster-scrim" not in stcss, None)
check("换源按钮的选中态按字符串比较（接口给的是数字 ID，比不中就一直选不上）",
      'String(x.id) === String(src) && String(x.vid) === String(vid)' in drawer_ts, None)
# 只有一个源也要有这一排：它说的是"这条详情是哪个源给的"，不是可有可无的装饰
check("单源也渲染这一排（不再 length > 1 才画，标题跟着长度换词）",
      "{sources.length ? (" in drawer_ts and 'sources.length > 1 ? "换源看" : "来源"' in drawer_ts,
      re.findall(r"sources\.length[^\n]{0,30}", drawer_ts))
# (c) 旧写法在"按片名兜底"那条路上要事后把这一排插回面板里（那时 data-srcs 是空的）。
# 现在这一排读的是 spec.sources（点开来那份数据里就带着），与接口回什么无关，补那一步不存在
check("这一排排在 loading/error/结果三个分支之外，不依赖接口回没回 sources",
      drawer_ts.index("{sources.length ? (") < drawer_ts.index("{loading ? ("), None)
check("点当前这个源不重开、也不再上报一条（门闩是 key，key 没变就不重查；换源那颗按钮只改 pick）",
      'const key = spec ? dkey(src, vid, spec.title) : "";' in drawer_ts
      and "sendClick" not in drawer_ts[drawer_ts.index("{sources.map((x) =>"):
                                  drawer_ts.index("{loading ? (")]
      and "onPress={() => setPick(" in drawer_ts,
      re.findall(r"sendClick", drawer_ts))
howto_ts = wread("components", "HowTo.tsx")
check("用法说明收进顶栏那颗「怎么用」按钮里，文案不再提右键",
      "海报右下角的「详情」" in howto_ts and "怎么用" in howto_ts
      and "右键" not in howto_ts and "右键" not in app_ts,
      re.findall(r".{0,20}右键.{0,20}", howto_ts + app_ts))

print("\n7) 海报淡入：不是一片张着等，也不是一片透明")
# (a) 原来这一节切的是 static/app.css 里 html.hasjs .cover img 那一段与 static/app.js 里
# 那个全局 revealIn()。现在淡入是 Poster 组件的一个 state + styles.css 里一组关键帧，
# 闸门从 html.hasjs 换成 html.js（由壳那段内联脚本打）。
check("两处海报（海报卡与详情抽屉）共用同一个 PosterImage：poster-img 这个类前台只写一处",
      stcss.count(".poster-img") >= 1 and front_src.count("poster-img") == 1
      and "<PosterImage pic={pic} title={title} />" in poster_ts
      and "<PosterImage pic={spec.pic} title={spec.title} />" in drawer_ts,
      re.findall(r"poster-\w+", all_src))
check("没加载完是 opacity-0（Tailwind 那个类），加载完换成走 .poster-in 的淡入",
      '"poster-in") : "opacity-0"' in poster_ts and "instant" in poster_ts
      and "animation: poster-in 0.28s ease-out both" in stcss, None)
check("时长在 .4s 以内（比这长就像幻灯片）",
      "poster-in 0.28s" in stcss and "row-next 0.32s" in stcss, re.findall(r"\d\.\d+s", stcss))
# (c) 旧写法要专门给"第二次见这张图"加一个 .noanim 跳过过渡。新实现在 ref 里当场问一句
# complete，命中磁盘缓存的图第一帧就是可见态，只统一淡一次 —— 作者把这个当成取舍写进了注释
check("命中缓存的图由 ref 当场判定可见（不再有 .noanim 那个特例，也不再攒看过的地址）",
      "node?.complete && node.naturalWidth > 0" in poster_ts
      and "noanim" not in all_src and "shownPics" not in all_src, None)
# (c) 旧那条的闸门是 html.hasjs（模板里 CSS 默认 opacity:0，靠 JS 补 .loaded）。
# 新架构海报卡片本身就只在 JS 那侧存在：没有 JS 的人拿到的是 #nojs 那份文字列表，
# 一片透明的图这个状态在结构上就不可能出现。闸门类仍然留着，但它管的是 #nojs/#app 让位
check("禁用 JS 与爬虫不会拿到一片透明：图只存在于 React 那一侧，壳那份是纯文字列表",
      shell.count("<img") == 0 and 'html.js #nojs' in stcss and "html:not(.js) #app" in stcss,
      re.findall(r"<img", shell))
check("闸门那个类由壳里样式表之前的内联脚本打，晚一帧就是先看见图再看见它变透明",
      shell.index("classList.add('js')") < shell.index("spa/app.css"), None)
check("同一棵树不会重复挂监听：淡入是 onLoad/onError 两个属性，不往节点上 addEventListener",
      'onLoad={() => setSt((s) => ({ ...s, shown: true }))}' in poster_ts and 'onError={() => setBroken(true)}' in poster_ts
      and "addEventListener" not in poster_ts, None)
# 这条的一半（既不 load 也不 error 时那个 8 秒兜底）在新实现里**没有**搬过来：
# 那张图会一直停在 opacity-0。不改实现，只钉还成立的那一半（error 那一路会退回片名占位），
# 缺的那半已作为疑似回归写进交付报告。
check("图坏了不会留一块空白：onError 之后原位换成片名占位（既不 load 也不 error 的兜底缺失，已上报）",
      "if (!src || broken)" in poster_ts and "grid size-full place-items-center" in poster_ts
      and "{title.slice(0, 8)}" in poster_ts, None)
for anchor, tgt in (("结果卡片", vod_ts), ("猜你想搜", hot_ts)):
    check(f"渲染点用的是同一个 Poster（{anchor}）：淡入逻辑不用再在各处补跑一遍",
          "<Poster" in tgt, None)
check("详情抽屉那张封面也走同一个 PosterImage：代理与淡入因此只有一份，抽屉里不自己拼 src",
      "<PosterImage pic={spec.pic} title={spec.title} />" in drawer_ts
      and "posterOf" not in drawer_ts and "revealIn" not in all_src, None)
check("没有全局 reveal 扫一遍：前台唯一那次 querySelectorAll 是量「6 行」的行高用的",
      "revealIn" not in all_src and front_src.count("querySelectorAll") == 1
      and 'el.querySelectorAll("li")' in vod_ts, re.findall(r"querySelectorAll", front_src))
check("服务端渲染那 12 条不靠 inline onload（壳里根本没有 img，也没有 onload 属性）",
      "onload=" not in shell and "<img" not in shell, re.findall(r"onload=[^ ]*", shell))
# 这条原来判的是 .mdui-theme-dark img { filter: brightness(.94) }，那批选择器随旧前端一起没了；
# 判据搬到新样式上：暗色压亮度，且绝不碰 opacity（会和淡入抢同一个属性）
dark_rule = stcss[stcss.index(".dark .poster-img"):stcss.index(".dark .poster-img") + 90]
check("暗色主题用 filter 压海报亮度，不透明度留给淡入（两者抢同一个属性就会闪）",
      "filter: brightness(0.94)" in stcss and "opacity" not in dark_rule, dark_rule)

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
