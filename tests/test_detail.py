# -*- coding: utf-8 -*-
"""海报「详情」按钮的离线测试（不联网：所有请求都被桩替掉）。

    python tests/test_detail.py

覆盖三层：
  1. 详情数据的来源 —— ac=detail 解析出的字段、按片名兜底那条路、缓存与失败重试、
     meta=1 必须把播放线路剥干净；
  2. /api/detail 的入参边界 —— 有 ID 走 ID，没 ID 走片名，两个都没有就 400；
  3. 前端接线 —— 按钮在不在海报角上、右键有没有被劫持、详情请求是不是只在点击之后才发。
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

print("\n4) /api/detail 的入参边界，以及 meta=1 把线路剥掉")
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
    j = c.get("/api/detail?src=s1&vid=1234&t=庆余年&meta=1").get_json()
    check("meta=1 时不返回 lines（前端也就无从渲染播放链接）",
          "lines" not in j and j.get("blurb"), j)
    check("meta=1 只是剥字段，没改缓存里的内容（线路仍在服务端）",
          "lines" in app_mod.fetch_detail(SRC, 1234, "庆余年"), app_mod.fetch_detail(SRC, 1234))
    j = c.get("/api/detail?kw=庆余年&meta=1").get_json()
    check("按片名那条路同样尊重 meta=1", "lines" not in j, j)
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
check("旧缓存没有 src/vid 时模板不报错（default('', true)）",
      "x.src | default('', true)" in html and "x.vid | default('', true)" in html)
check("点击走的是按钮代理，不是整张海报",
      "closest('.dbtn')" in js and "openDetail(specOf(b))" in js)
lazy = js[js.index("function openDetail"):js.index("function closeDetail")]
check("详情请求只在 openDetail 一处发起", js.count("getJSON(detailURL(s))") == 1)
check("请求一律带 meta=1（两条来路都带上）",
      js.count("&meta=1") == 2 and "meta=1" in js[js.index("const detailURL"):],
      js[js.index("const detailURL"):js.index("const detailURL") + 330])
check("渲染卡片/列表时完全不碰详情接口",
      "detailURL" not in js[js.index("function card("):js.index("function renderPager")] and
      "detailURL" not in js[js.index("function hotCard("):js.index("function hotCols")] and
      "openDetail" not in js[js.index("function card("):js.index("function renderPager")] and
      "getJSON" not in js[js.index("function hotCard("):js.index("function hotCols")])
check("面板里没有 linesHTML：详情面板不渲染播放链接",
      "linesHTML" not in js[js.index("function headHTML"):js.index("function openDetail")])
check("面板改成就给影片信息，并指一条去看线路的路", "dpgoto" in js)
check("同一部片连开两次不重复请求（在途与结果各一层缓存）",
      "if (!dpending[key])" in lazy and "dcache[key]" in lazy)
check("换源/切条目后旧请求回来不会填新面板（token 校验）",
      "token === dpToken" in lazy and "dpToken++" in js[js.index("function closeDetail"):])
# 失败结果也会被写进 dcache（.then 里不看 ok 就存），所以重试必须把它清掉，
# 否则点"重试"会立刻把上一次的失败又显示一遍
check("失败有重试入口，且会清掉缓存里的失败结果",
      "dpretry" in js and "delete dcache[dkey(s)]" in js)
check("Esc 关面板", "e.key === 'Escape' && !dpEl.hidden" in js)
check("hidden 真能盖掉 .dpanel 的 flex", ".dpanel[hidden] { display: none; }" in css)
check("显隐只用 hidden 表达，不写死 aria-hidden",
      'aria-hidden' not in html[html.index('<aside class="dpanel"'):html.index("</main>")])
check("面板滑入动画与骨架屏闪动在减少动效时都关掉",
      "@media (prefers-reduced-motion: reduce)" in css[css.index(".dpanel"):])
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
      "String(x.vid) === String(s.vid)" in js)
check("用法说明改成了详情按钮，不再提右键",
      "详情" in html and "右键" not in html[html.index('<div class="placeholder"'):html.index("</main>")])

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
