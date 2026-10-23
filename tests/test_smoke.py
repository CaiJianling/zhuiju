# -*- coding: utf-8 -*-
"""离线冒烟测试：用固定样本验证解析、合并、分层排序、目录检索，不依赖外部网络。

    python tests/test_smoke.py
"""
import json
import os
import sys
from pathlib import Path

# Windows 控制台默认 GBK，中文断言名会乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zhuiju import catalog  # noqa: E402
from zhuiju import search as search_mod  # noqa: E402  需要模块对象来替换 fetch_one
from zhuiju.search import (detail, fetch_one, match_tier, merge,  # noqa: E402
                           parse_maccms, parse_maccms_detail, search, title_key)
from zhuiju.sources import Source  # noqa: E402

FAILS = []


def check(name, cond, got=None):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}  got={got!r}")
        FAILS.append(name)


print("1) 片名归一化")
check("空格/全角/尾部标记不影响 key",
      title_key("庆余年 第二季") == title_key("庆余年　第二季")
      and title_key("流浪地球 HD") == title_key("流浪地球"))
check("英文大小写归一", title_key("Oppenheimer") == "oppenheimer",
      title_key("Oppenheimer"))

print("2) 匹配分层（蹭名短剧不能压过正片）")
check("完全同名 = 0", match_tier("灌篮高手", "灌篮高手") == 0,
      match_tier("灌篮高手", "灌篮高手"))
check("前缀续集 = 1", match_tier("庆余年", "庆余年第二季") == 1,
      match_tier("庆余年", "庆余年第二季"))
check("包含 = 2", match_tier("甄嬛传", "后宫甄嬛传") == 2,
      match_tier("甄嬛传", "后宫甄嬛传"))
check("无关 = 3", match_tier("繁花", "海上花") == 3, match_tier("繁花", "海上花"))

print("3) list 响应解析")
raw = {"code": 1, "total": 2, "list": [
    {"vod_id": 1, "vod_name": "<em>庆余年</em> 第二季", "type_name": "国产剧",
     "vod_year": "2024", "vod_area": "大陆", "vod_remarks": "全36集",
     "vod_actor": "张若昀,李梦", "vod_pic": "https://x/y.jpg", "vod_time": "2024-06-11 10:00:00"},
    {"vod_id": 2, "vod_name": "庆余年之帝王业", "type_name": "古装仙侠",
     "vod_year": "2024", "vod_remarks": "全52集"}]}
items = parse_maccms(raw)
check("HTML 标签被清掉", items[0]["title"] == "庆余年 第二季", items[0]["title"])
check("海报/年份/更新状态保留",
      items[0]["pic"].startswith("https://") and items[0]["year"] == "2024"
      and items[0]["remarks"] == "全36集")
check("缺字段不报错", items[1]["pic"] == "" and items[1]["actor"] == "")

print("4) 跨源合并与排序")
def fake(src_id, name, payload_kw):
    return {"source": src_id, "source_name": name, "ok": True, "count": 1,
            "items": [{**x, "source": src_id, "source_name": name, "link": ""}
                      for x in parse_maccms(payload_kw)]}

a = fake("hhzy", "火狐", raw)
raw2 = {"list": [{"vod_id": 9, "vod_name": "庆余年第二季", "type_name": "国产剧",
                  "vod_year": "2024", "vod_remarks": "已完结"}]}
b = fake("jszy", "极速", raw2)
raw3 = {"list": [{"vod_id": 5, "vod_name": "庆余年之风起沧州", "vod_year": "2016"}]}
c = fake("bfzy", "备番", raw3)
res, dropped = merge([a, b, c], "庆余年")
check("同片跨源合并成一条",
      res[0]["title"] == "庆余年 第二季" and len(res[0]["sources"]) == 2,
      (res[0]["title"], len(res[0]["sources"])))
check("正片排在蹭名作品之前", res[0]["tier"] <= res[1]["tier"],
      [(r["title"], r["tier"], len(r["sources"])) for r in res])
check("match 字段可读", res[0]["match"] in ("exact", "series", "contains", "other"),
      res[0]["match"])
check("源去重", len({s["id"] for s in res[0]["sources"]}) == 2)

# 接口自身模糊匹配出来的无关结果（与关键词零重叠）必须丢掉
raw_junk = {"list": [{"vod_id": 77, "vod_name": "恐怖藏品", "vod_year": "2026"}]}
raw_en = {"list": [{"vod_id": 88, "vod_name": "奥本海默 Oppenheimer", "vod_year": "2023"}]}
res_j, dropped_j = merge([a, fake("jszy", "极速", raw_junk), fake("tp", "淘片", raw_en)],
                         "Oppenheimer")
check("只留下真正含关键词的结果",
      [r["title"] for r in res_j] == ["奥本海默 Oppenheimer"],
      [r["title"] for r in res_j])
# a 里两条《庆余年》+ 一条《恐怖藏品》对 Oppenheimer 都是零重叠
check("零重叠噪声计入 dropped", dropped_j == 3, dropped_j)

print("5) detail 线路解析（分隔符 $$$ 而非 +）")
dd = {"list": [{"vod_id": 1, "vod_name": "庆余年 第二季", "vod_year": "2024",
                "vod_play_from": "hhyun$$$hhm3u8",
                "vod_play_url": "第01集$u1#第02集$u2$$$第01集$u3"}]}
p = parse_maccms_detail(dd)
check("线路名按 $$$ 正确切分",
      [l["from"] for l in p["lines"]] == ["hhyun", "hhm3u8"],
      [l["from"] for l in p["lines"]])
check("各线路集数正确", [len(l["episodes"]) for l in p["lines"]] == [2, 1],
      [len(l["episodes"]) for l in p["lines"]])
check("播放地址完整", p["lines"][0]["episodes"][0]["url"] == "u1")

src = Source(id="t", name="测试源", kind="maccms", api="http://127.0.0.1:9/provide/vod/")
d_err = detail(src, "1")
check("接口不可达时返回 ok=False 且带原因",
      d_err.get("ok") is False and bool(d_err.get("error")), d_err)
src2 = Source(id="t2", name="测试源2", kind="maccms", api="http://127.0.0.1:9/provide/vod/")
check("未知 kind 不会误判为成功", parse_maccms_detail({"list": []})["lines"] == [],
      parse_maccms_detail({"list": []}))

print("6) 目录检索与直达链接")
catalog.reload_data()
rows = catalog.search("网盘")
check("目录能按分类/标签命中", any(r["category_cn"] == "网盘搜索" for r in rows),
      [r["name"] for r in rows][:5])
rows2 = catalog.search("字幕")
check("字幕分类可检索", len(rows2) > 0, len(rows2))
dl = catalog.deeplinks("庆余年")
verified = [x for x in dl if x["kind"] == "site_search"]
check("直达项存在", len(dl) > 20, len(dl))
check("已验证模板会带关键词",
      all("庆余年" in json.dumps(x, ensure_ascii=False) or "%" in x["url"]
          for x in verified[:1]))
check("状态灯已映射", dl[0]["dot"] in ("🟢", "🟡", "🔴", "⚪"), dl[0]["dot"])

print("7) 某源超过预算时不能崩（extra 曾被误初始化成 dict，只在超时时才触发）")
import time as _t


class SlowSource(Source):
    pass


def slow_fetch(src, kw, page=1, limit=20, type_id=None):
    if src.id == "slow":
        _t.sleep(3)
        return {"source": src.id, "source_name": src.name, "ok": True, "count": 0,
                "total": 0, "items": [], "ms": 3000, "error": None}
    return {"source": src.id, "source_name": src.name, "ok": True, "count": 1,
            "total": 1, "items": [{**parse_maccms(raw)[0], "source": src.id,
                                   "source_name": src.name, "link": ""}],
            "ms": 10, "error": None}


fast = Source(id="fast", name="快源", kind="maccms", api="http://x/api.php/provide/vod/")
slow = Source(id="slow", name="慢源", kind="maccms", api="http://y/api.php/provide/vod/")
_orig = search_mod.fetch_one
search_mod.fetch_one = slow_fetch
try:
    out = search("庆余年", sources=[fast, slow], budget=0.5)
    check("超时不抛异常", isinstance(out, dict), type(out))
    check("快源结果仍在", len(out["results"]) >= 1, len(out["results"]))
    names = {s["source"] for s in out["status"]}
    check("慢源被标为未响应", "slow" in names, out["status"])
    slowrow = next(s for s in out["status"] if s["source"] == "slow")
    check("超时原因写进状态", "未响应" in (slowrow["error"] or ""), slowrow)
finally:
    search_mod.fetch_one = _orig

print("7b) 自动更新的『当天』以几点为界（现在是设置项，默认凌晨 2 点）")
from datetime import datetime as _dt, timedelta as _td
from zhuiju import autoupdate as au
from zhuiju import settings as st

check("默认值都写在代码里，且日切仍是以前那个 2 点（改默认值等于改触发节奏）",
      st.DEFAULTS["refresh_hour"] == 2 and st.DEFAULTS["human_gate"] == 1
      and st.DEFAULTS["human_hours"] == 12, st.DEFAULTS)
check("设置项清单与默认值一一对应（加一项忘了给默认，页面上就不会出现那一格）",
      set(st.SPEC) == set(st.DEFAULTS), (sorted(st.SPEC), sorted(st.DEFAULTS)))
check("后台表单按 kind 决定渲染成数字框还是开/关",
      {k: v["kind"] for k, v in st.SPEC.items()}
      == {"refresh_hour": "int", "human_gate": "bool", "human_hours": "int"}, None)
check("01:30 仍属于昨天", au.logical_day(_dt(2026, 10, 14, 1, 30)) == _dt(2026, 10, 13).date(),
      str(au.logical_day(_dt(2026, 10, 14, 1, 30))))
check("02:00 起算新的一天", au.logical_day(_dt(2026, 10, 14, 2, 0)) == _dt(2026, 10, 14).date(),
      str(au.logical_day(_dt(2026, 10, 14, 2, 0))))
check("23:59 仍属于当天", au.logical_day(_dt(2026, 10, 14, 23, 59)) == _dt(2026, 10, 14).date())
# 23 点跑过一次，次日 01 点访问不该重跑，02 点后要重跑
ld_y = au.logical_day(_dt(2026, 10, 13, 23, 0)).isoformat()
check("凌晨 1 点：昨天 23 点跑过 -> 不需要更新",
      ld_y == au.logical_day(_dt(2026, 10, 14, 1, 0)).isoformat(), ld_y)
check("凌晨 2 点后：同一份记录 -> 需要更新",
      ld_y != au.logical_day(_dt(2026, 10, 14, 2, 5)).isoformat())
check("needs_update 走的是逻辑日而非自然日",
      "logical_day" in (Path(__file__).resolve().parent.parent
      / "zhuiju" / "autoupdate.py").read_text(encoding="utf-8"))

# 设置存哪儿：文件（不进版本库），不是 stats.db —— 这条判据要钉住，
# 否则哪天有人"顺手"把它挪进日志库，删库重统计就会顺手把设置也删了
check("设置写在 data/settings.json，.gitignore 里认了它",
      st.PATH.name == "settings.json" and st.PATH.parts[-3] == "zhuiju",
      str(st.PATH))
check(".gitignore 里确实有这一条（不然每个人的偏好都会提交进仓库）",
      "zhuiju/data/settings.json" in (Path(__file__).resolve().parent.parent
      / ".gitignore").read_text(encoding="utf-8"), None)
check("autoupdate 不再留一个 import 时算死的 REFRESH_HOUR 常量（改了要重启才会生效）",
      "REFRESH_HOUR = int(" not in (Path(__file__).resolve().parent.parent
      / "zhuiju" / "autoupdate.py").read_text(encoding="utf-8"), None)

# 拿 .probe 下的临时文件测读写，绝不碰真配置
_real_path, _real_env = st.PATH, os.environ.get("ZHUIJU_REFRESH_HOUR")
tmp_settings = Path(".probe/settings_test.json")
tmp_settings.parent.mkdir(exist_ok=True)
if tmp_settings.exists():
    tmp_settings.unlink()
st.PATH = tmp_settings
st._cached.update(mtime=None, vals={})
try:
    check("没文件时回默认值，来源标成 default",
          st.refresh_hour() == 2 and st.source_of("refresh_hour") == "default", None)
    ok, err = st.set_value("refresh_hour", "7")
    st._cached.update(mtime=None, vals={})       # 真进程里是靠 mtime 自动重读的
    check("保存合法值：写文件、生效、来源变成 file",
          ok and err is None and st.refresh_hour() == 7
          and st.source_of("refresh_hour") == "file", json.loads(tmp_settings.read_text()))
    check("日切线跟着设置走：7 点前访问仍算昨天",
          au.logical_day(_dt(2026, 10, 14, 6, 59)) == _dt(2026, 10, 13).date()
          and au.logical_day(_dt(2026, 10, 14, 7, 0)) == _dt(2026, 10, 14).date(), None)
    for bad in ("25", "-1", "abc", "", "1.5", None, "999999999999999999999"):
        ok, err = st.set_value("refresh_hour", bad)
        if ok or err is None:
            check(f"非法值 {bad!r} 该拒", False, (ok, err))
            break
    else:
        check("非法值一律拒掉且不落盘（半套设置比没有设置更难查）",
              st.refresh_hour() == 7, st.refresh_hour())
    check("不认识的键不当设置存进去", st.set_value("delete_stats", "1")[0] is False, None)
    tmp_settings.write_text(json.dumps({"refresh_hour": 3, "junk": 9}), encoding="utf-8")
    st._cached.update(mtime=None, vals={})
    st.set_value("refresh_hour", 4)
    check("写回时把文件里不认识的键清掉（设置文件不该变成垃圾场）",
          set(json.loads(tmp_settings.read_text())) == {"refresh_hour"},
          json.loads(tmp_settings.read_text()))
    os.environ["ZHUIJU_REFRESH_HOUR"] = "9"
    check("环境变量顶在文件上面，并且页面上说得清是谁定的",
          st.refresh_hour() == 9 and st.source_of("refresh_hour") == "env", None)
    del os.environ["ZHUIJU_REFRESH_HOUR"]
    check("撤掉环境变量就回文件里的值（不是把文件覆盖掉）",
          st.refresh_hour() == 4, st.refresh_hour())
finally:
    st.PATH = _real_path
    st._cached.update(mtime=None, vals={})
    tmp_settings.unlink(missing_ok=True)
    if _real_env is not None:
        os.environ["ZHUIJU_REFRESH_HOUR"] = _real_env

print("8) 数据文件完整性")
data = Path("zhuiju/data")
for f in ("catalog.json", "sources.json", "templates.json"):
    p = data / f
    check(f"{f} 可解析", p.exists() and isinstance(json.loads(p.read_text(encoding="utf-8")), dict),
          p.exists())
srcs = json.loads((data / "sources.json").read_text(encoding="utf-8"))["sources"]
check("检索源都有 api 与 kind", all(s.get("api") and s.get("kind") for s in srcs))
check("browsable 字段已落盘", all("browsable" in s for s in srcs),
      [list(s.keys()) for s in srcs[:1]])
check("searchable 字段已落盘（哪个源被站点关了搜索，要在配置文件里看得见，不能只写在注释里）",
      all("searchable" in s for s in srcs), [s["id"] for s in srcs if "searchable" not in s])
check("id 不重复（详情面板是按 id 找回那个源的，重了就互相顶掉）",
      len({s["id"] for s in srcs}) == len(srcs),
      sorted({s["id"] for s in srcs if [x["id"] for x in srcs].count(s["id"]) > 1}))
neth = [s["api"].split("//", 1)[-1].split("/", 1)[0].lower() for s in srcs]
check("同一个域名不重复收录（换源列表里会出现两条一模一样的线路）",
      len(set(neth)) == len(neth), sorted(h for h in neth if neth.count(h) > 1))
off = [s for s in srcs if not s["searchable"]]
check("关掉搜索的只有实测被站点拒的那两个",
      {s["id"] for s in off} == {"suoni", "sdzy"},
      [(s["id"], s["name"]) for s in off])
check("它们仍然 enabled：搜索不通但最新流与 ac=detail 都好，猜你想搜要用",
      all(s["enabled"] for s in off), [(s["id"], s["enabled"]) for s in off])

print("8b) searchable=False 的源只喂猜你想搜，不进并发检索")
S_OK = Source(id="s_ok", name="能搜的", kind="maccms", api="http://a/api.php/provide/vod/")
S_NS = Source(id="s_ns", name="只最新流", kind="maccms",
              api="http://b/api.php/provide/vod/", searchable=False)
real_fetch, real_load = search_mod.fetch_one, search_mod.load_sources
calls = []


def fake_fetch(src, kw, page=1, limit=20, type_id=None):
    calls.append((src.id, kw))
    # fetch_one 会给每一条 item 注入 source / source_name / link，merge 靠 source 归并线路，
    # 这里必须照抄，否则测的就不是同一条路径
    item = {"vid": 1, "title": "庆余年", "type": "电视剧", "year": "2024", "area": "大陆",
            "remarks": "", "actor": "", "director": "", "pic": "", "notes": "",
            "updated": "2024-05-01", "slug": "", "source": src.id,
            "source_name": src.name, "link": ""}
    return {"source": src.id, "source_name": src.name, "ok": True, "count": 1,
            "total": 1, "ms": 5.0, "error": None, "items": [item]}


search_mod.fetch_one, search_mod.load_sources = fake_fetch, (lambda *a, **k: [S_OK, S_NS])
try:
    r = search_mod.search("庆余年")
    check("并发列表里没有它，sources_total 也不数它（不然「平均可用源」永远少一个）",
          [c[0] for c in calls] == ["s_ok"] and r["sources_total"] == 1
          and r["sources_ok"] == 1, (calls, r["sources_total"]))
    check("结果仍然正常合并", len(r["results"]) == 1, r["results"])
    # 猜你想搜那条路要用得着它们：feed_pool 走的是最新流，不碰 wd
    hot_src = (Path("zhuiju") / "hot.py").read_text(encoding="utf-8")
    check("猜你想搜按 enabled 取源（不看 searchable），回查豆瓣候选才挑 searchable",
          "if s.enabled]" in hot_src and "[s for s in sources if s.searchable]" in hot_src, None)
finally:
    search_mod.fetch_one, search_mod.load_sources = real_fetch, real_load

print("\n8c) 有没有下一页：只认「这一页有没有被填满」")
L = search_mod.PAGE_LIMIT
S_OK2 = Source(id="s_ok2", name="另一个能搜的", kind="maccms", api="http://c/api.php/provide/vod/")


def fill_fetch(n_by_src):
    """按 {源 id: 这一页返回几条} 打桩；条数由 count 与 items 一起如实给。"""
    def f(src, kw, page=1, limit=L, type_id=None):
        n = n_by_src.get(src.id, 0)
        items = []
        for i in range(n):
            items.append({"vid": i + 1, "title": f"庆余年{i}号", "type": "电视剧", "year": "2024",
                          "area": "大陆", "remarks": "", "actor": "", "director": "", "pic": "",
                          "notes": "", "updated": "2024-05-01", "slug": "", "source": src.id,
                          "source_name": src.name, "link": ""})
        return {"source": src.id, "source_name": src.name, "ok": True, "count": n,
                "total": n * 9, "ms": 3.0, "error": None, "items": items}
    return f


search_mod.load_sources = lambda *a, **k: [S_OK, S_OK2, S_NS]
try:
    search_mod.fetch_one = fill_fetch({"s_ok": L - 1})
    r = search_mod.search("庆余年")
    check("单源差一条没填满 = 这个源到底了，不该亮「下一页」（旧判据 hits>=8 会亮）",
          r["has_more"] is False and r["hits"] >= 8 and len(r["results"]) >= 8,
          {k: r[k] for k in ("hits", "has_more")} | {"n": len(r["results"])})
    search_mod.fetch_one = fill_fetch({"s_ok": L})
    r = search_mod.search("庆余年")
    check("正好填满一页才算还有下一页", r["has_more"] is True, r["hits"])
    search_mod.fetch_one = fill_fetch({"s_ok": 7, "s_ok2": 13})
    r = search_mod.search("庆余年")
    check("两源合起来 20 条但谁都没填满 → 没有下一页（hits 加总正好等于页长也不行）",
          r["hits"] == L and r["has_more"] is False, (r["hits"], r["has_more"]))
    search_mod.fetch_one = fill_fetch({"s_ok": 0})
    r = search_mod.search("庆余年")
    check("空的一页：has_more 与结果数都为 0，翻页条该整条收掉",
          r["has_more"] is False and r["results"] == [] and r["limit"] == L, r["hits"])
    # 前端只认服务端这一句，且"这一页一条都没合出来"时不再邀请人往下翻
    # (a) 这条原来读的是 static/app.js 里的 renderPager，后来挪进 VodPanel。翻页按钮换成
    # "滚到末尾自动追加"之后，判据收在 stack.ts 的 stackFrom / appendPage 里（同一句话）。
    vod_ts = (Path("web") / "src" / "components" / "VodPanel.tsx").read_text(encoding="utf-8")
    stack_ts = (Path("web") / "src" / "stack.ts").read_text(encoding="utf-8")
    check("翻页判据用的是 d.has_more，旧的 hits 算术已不在这一屏（注释里提一句不算）",
          "hasMore: d.has_more && d.results.length > 0," in stack_ts
          and "hasMore: d.has_more && !stalled," in stack_ts
          and "d.hits >=" not in vod_ts and "hits >=" not in vod_ts, None)
    check("这一页合完是 0 条时不再邀请往下翻（hasMore 里带着 results.length > 0）",
          "d.results.length > 0" in stack_ts, None)
finally:
    search_mod.fetch_one, search_mod.load_sources = real_fetch, real_load

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
