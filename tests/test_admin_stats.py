# -*- coding: utf-8 -*-
"""后台统计（SQLite）与口令登录的离线测试（不联网）。

    python tests/test_admin_stats.py

关键点：把 stats.DB 与 admin.CONFIG 都指到临时目录，绝不碰真实的
zhuiju/data/stats.db 和 admin.json —— 之前 check_autoupdate 写真实状态文件，
正在读的站点就把测试造的假状态显示到页头上了。
"""
import json
import re
import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from zhuiju import admin as admin_mod      # noqa: E402
from zhuiju import agent as agent_mod      # noqa: E402
from zhuiju import settings as settings_mod  # noqa: E402
from zhuiju import stats as stats_mod      # noqa: E402

FAILS = []
TMP = Path(tempfile.mkdtemp(prefix="zhuiju_admin_test_"))

# 必须在 create_app 之前改：app.secret_key 建应用时就要读配置文件
admin_mod.CONFIG = TMP / "admin.json"
# 「每日更新时间」那项设置也一样：后台测试会真的 POST 保存，不能写进本机那份配置里
settings_mod.PATH = TMP / "settings.json"
import gate_off  # noqa: E402  门禁与本文件的测试对象无关，见 tests/gate_off.py
gate_off.off(TMP)
stats_mod.DB = TMP / "stats.db"
stats_mod.DATA = TMP
stats_mod._ready = False
stats_mod.ensure_schema()          # 先把表建在临时目录里，下面的用例要直接插数据


def check(name, cond, got=None):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  got={got!r}"))
    if not cond:
        FAILS.append(name)


def today(offset: int = 0) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


print("1) 配置文件：没有就自动生成，口令可改")
cfg = admin_mod.load()
check("生成了配置文件", admin_mod.CONFIG.exists())
check("有口令", len(str(cfg.get("password") or "")) >= 8, cfg.get("password"))
check("有签名密钥", len(str(cfg.get("secret_key") or "")) == 64)
check("口令校验正确", admin_mod.password_ok(cfg["password"]))
check("错口令被拒", not admin_mod.password_ok(cfg["password"] + "x"))
check("空口令被拒", not admin_mod.password_ok(""))
# 改成自己的口令
admin_mod.save({"password": "wo-ziji-de-mima", "secret_key": cfg["secret_key"]})
check("改成自定义口令后生效", admin_mod.password_ok("wo-ziji-de-mima"))
check("旧口令失效", not admin_mod.password_ok(str(cfg["password"])))
import os  # noqa: E402
os.environ["ZHUIJU_ADMIN_PASSWORD"] = "mimal-ing-from-env"
check("环境变量能覆盖配置文件", admin_mod.password_ok("mimal-ing-from-env"))
check("环境变量覆盖后配置文件口令不再可用", not admin_mod.password_ok("wo-ziji-de-mima"))
del os.environ["ZHUIJU_ADMIN_PASSWORD"]
check("清掉环境变量后回到配置文件", admin_mod.password_ok("wo-ziji-de-mima"))

print("\n2) 统计层：写入、过滤、分页、聚合")
rows = [
    ("庆余年", "10.0.0.1", "api", 8, 40, 10, 10, 900, today(-3)),
    ("庆余年", "10.0.0.1", "api", 8, 40, 10, 10, 800, today(-1)),
    ("流浪地球", "10.0.0.2", "api", 3, 12, 9, 10, 1200, today(-1)),
    ("繁花", "10.0.0.2", "seo", 0, 0, 0, 10, 3000, today()),
    ("灌篮高手", "10.0.0.3", "cloud", 5, None, 3, 20, 6000, today()),
]
for kw, ip, via, res, hits, ok, tot, ms, day in rows:
    # 直接写库，把 day/ts 造出来（record 用的是当前时间）
    con = stats_mod.connect()
    con.execute("INSERT INTO queries (ts, day, ip, kw, via, results, hits,"
                " sources_ok, sources_total, ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"{day} 12:00:00", day, ip, kw, via, res, hits, ok, tot, ms))
    con.commit()
    con.close()

allq = stats_mod.list_queries({})
check("总条数对得上", allq["total"] == 5, allq["total"])
check("默认倒序（最新的在前）", allq["items"][0]["kw"] in ("繁花", "灌篮高手"),
      [x["kw"] for x in allq["items"][:2]])

by_ip = stats_mod.list_queries({"ip": "10.0.0.1"})
check("按 IP 过滤", by_ip["total"] == 2 and all(r["ip"] == "10.0.0.1" for r in by_ip["items"]),
      by_ip["total"])
by_kw = stats_mod.list_queries({"kw": "庆余年"})
check("按关键词模糊过滤", by_kw["total"] == 2, by_kw["total"])
by_range = stats_mod.list_queries({"day_from": today(-1), "day_to": today()})
check("按日期范围过滤", by_range["total"] == 4, by_range["total"])
by_range2 = stats_mod.list_queries({"day_from": today(-3), "day_to": today(-3)})
check("单日常规到边界（含两端）", by_range2["total"] == 1, by_range2["total"])
by_via = stats_mod.list_queries({"via": "cloud"})
check("按入口过滤", by_via["total"] == 1 and by_via["items"][0]["kw"] == "灌篮高手")
combo = stats_mod.list_queries({"ip": "10.0.0.2", "day_from": today(-1)})
check("多条件叠加", combo["total"] == 2, combo["total"])

p1 = stats_mod.list_queries({}, page=1, per=2)
p2 = stats_mod.list_queries({}, page=2, per=2)
p3 = stats_mod.list_queries({}, page=3, per=2)
ids = [r["id"] for r in p1["items"] + p2["items"] + p3["items"]]
check("分页不重不漏", len(ids) == 5 and len(set(ids)) == 5, ids)
check("页码总数正确", p1["pages"] == 3 and p3["pages"] == 3, (p1["pages"], p3["pages"]))
far = stats_mod.list_queries({}, page=999, per=50)
check("越界页码被夹到最后一页而不是报错", far["page"] == 1 and far["items"], far["page"])
check("每页上限被夹住", stats_mod.list_queries({}, per=10000)["per"] == 200)

agg = stats_mod.summary({})
check("聚合：总数", agg["count"] == 5, agg["count"])
check("聚合：独立 IP 数", agg["ips"] == 3, agg["ips"])
check("聚合：独立关键词数", agg["kws"] == 4, agg["kws"])
check("聚合：零结果数", agg["empty"] == 1, agg["empty"])
check("聚合：按天分桶", len(agg["by_day"]) == 3, agg["by_day"])
check("聚合：按天最新的一天在最上面（后台先看的是「今天有没有人用」）",
      [d["day"] for d in agg["by_day"]] == sorted((d["day"] for d in agg["by_day"]), reverse=True),
      [d["day"] for d in agg["by_day"]])
check("聚合：热门关键词第一名", agg["top_kw"][0]["kw"] == "庆余年" and agg["top_kw"][0]["n"] == 2,
      agg["top_kw"][:1])
check("聚合：活跃 IP 统计了首末次", agg["top_ip"][0]["first_day"] <= agg["top_ip"][0]["last_day"])
check("聚合：入口分布", {v["via"]: v["n"] for v in agg["by_via"]} == {"api": 3, "seo": 1, "cloud": 1},
      agg["by_via"])
agg_ip = stats_mod.summary({"ip": "10.0.0.1"})
check("聚合也吃同样的过滤条件", agg_ip["count"] == 2 and agg_ip["ips"] == 1, agg_ip)

print("\n3) 脏输入：不炸、不匹配、也不改写 SQL")
dirty = ["1=1) OR 1=1 --", "%", "*)", "'", '"', "\n", "../../etc/passwd", "'; DROP TABLE queries; --"]
for bad in dirty:
    try:
        stats_mod.list_queries({"ip": bad, "kw": bad, "via": bad,
                                "day_from": bad, "day_to": bad})
        ok = True
    except Exception as exc:  # noqa: BLE001
        ok = False
        check(f"脏输入不抛异常 [{bad!r}]", False, f"{type(exc).__name__}: {exc}")
    if not ok:
        break
else:
    check("脏输入都不抛异常", True)
check("表还在", stats_mod.list_queries({})["total"] == 5, stats_mod.list_queries({})["total"])
check("非法 IP 过滤条件被忽略而不是当字符串比",
      stats_mod.list_queries({"ip": "not-an-ip"})["total"] == 5)
check("非法日期被丢掉而不是报错", stats_mod.list_queries({"day_from": "昨天"})["total"] == 5)
check("非法 via 不参与过滤", stats_mod.list_queries({"via": "rm -rf"})["total"] == 5)
check("clean_ip 只放行真 IP",
      stats_mod.clean_ip("10.0.0.1") == "10.0.0.1" and stats_mod.clean_ip("::1") == "::1"
      and stats_mod.clean_ip("10.0.0.1\nfake") == "" and stats_mod.clean_ip("") == ""
      and stats_mod.clean_ip("999.1.1.1") == "")
stats_mod.record("灌篮高手 剧场版", "10.0.0.9", via="api", results=2, hits=6,
                 sources_ok=5, sources_total=10, ms=1234.567)
new = stats_mod.list_queries({"kw": "剧场版"})["items"][0]
check("record 写入并四舍五入耗时", new["ms"] == 1234.6 and new["results"] == 2, new)
stats_mod.record("测试未知来源", "not-an-ip", via="api")
check("IP 解析不出时记成 unknown",
      stats_mod.list_queries({"kw": "测试未知来源"})["items"][0]["ip"] == "unknown")
stats_mod.record("非法 via 也入库但不越界", "10.0.0.1", via="bogus")
check("未知 via 归到 api", stats_mod.list_queries({"kw": "非法 via"})["items"][0]["via"] == "api")

print("\n4) client_ip：只有上一跳是回环时才采信 X-Forwarded-For")
check("直连取 REMOTE_ADDR",
      admin_mod.client_ip({"REMOTE_ADDR": "10.0.0.7"}) == "10.0.0.7")
check("本机 nginx 反代时取 XFF 最左一项",
      admin_mod.client_ip({"REMOTE_ADDR": "127.0.0.1",
                           "HTTP_X_FORWARDED_FOR": "203.0.113.9, 10.0.0.1"}) == "203.0.113.9")
check("外部直连伪造 XFF 不生效",
      admin_mod.client_ip({"REMOTE_ADDR": "198.51.100.4",
                           "HTTP_X_FORWARDED_FOR": "1.2.3.4"}) == "198.51.100.4")
check("XFF 里塞垃圾时退回 REMOTE_ADDR",
      admin_mod.client_ip({"REMOTE_ADDR": "127.0.0.1",
                           "HTTP_X_FORWARDED_FOR": "not an ip"}) == "127.0.0.1")

print("\n5) 登录限流")
th = admin_mod.Throttle(max_fails=3, window=60)
check("起初可以试", th.blocked("1.1.1.1") == 0)
for _ in range(3):
    th.fail("1.1.1.1")
check("错满 3 次后被挡住", th.blocked("1.1.1.1") > 0, th.blocked("1.1.1.1"))
check("挡住别人不影响新来源", th.blocked("2.2.2.2") == 0)
th.reset("1.1.1.1")
check("登录成功后清零", th.blocked("1.1.1.1") == 0)

print("\n6) 路由：没登录什么都看不到")
# 后台已转 React：/admin 只是一个壳（admin_shell.html + spa/admin.js），这一屏的数据全在
# GET /api/admin/view 的 JSON 里，渲染写法在 web/src/admin/**。原来钉在 /admin 那页 HTML 上的
# 判据，数据部分搬到 view 的 JSON，写法部分搬到组件源码 —— 下面几个源码字符串就是新载体。
AD = BASE / "web" / "src" / "admin"
adminapp_ts = (AD / "AdminApp.tsx").read_text(encoding="utf-8")
login_ts = (AD / "Login.tsx").read_text(encoding="utf-8")
detail_ts = (AD / "Detail.tsx").read_text(encoding="utf-8")
overview_ts = (AD / "Overview.tsx").read_text(encoding="utf-8")
filters_ts = (AD / "Filters.tsx").read_text(encoding="utf-8")
settings_ts = (AD / "Settings.tsx").read_text(encoding="utf-8")
adminui_ts = (AD / "ui.tsx").read_text(encoding="utf-8")
adminapi_ts = (AD / "api.ts").read_text(encoding="utf-8")
# Jinja 里 dict.items 会被解析成字典的 items 方法而不是 "items" 键，
# 这个坑在 index.html 上已经踩过一次（seo.snapshot.items），模板里统一用下标
# (c) admin.html 现在只当「禁用 JS 的登录兜底页」，但它仍带着 rows['items'] 这套下标写法，
#     判据本身还成立，锚点也没变 —— 保留。
admin_tpl = (BASE / "zhuiju" / "templates" / "admin.html").read_text(encoding="utf-8")
check("admin 模板不用裸 .items 属性写法", ".items %}" not in admin_tpl and ".items " not in admin_tpl,
      re.findall(r"\{\{[^}]*\.items[^}]*\}\}|{%[^%]*\.items[^%]*%}", admin_tpl))
check("admin 模板改用下标取 items", "rows['items']" in admin_tpl)

from zhuiju import app as app_mod  # noqa: E402

app_mod.admin_mod.secret_key()          # 确保配置已生成，再建 app
client = app_mod.create_app().test_client()

# (a) 原来这三条（401 / 口令页 / csrf 字段）钉的是 GET /admin 直接回口令页。后台转 React 后
#     /admin 是公开的 200 壳，门槛挪到了 GET /api/admin/view：未登录它回 401，body 里带 csrf。
r = client.get("/api/admin/view")
check("未登录时取数接口返回 401 而不是 200", r.status_code == 401, r.status_code)
denied = r.get_json()
html = client.get("/admin").get_data(as_text=True)
check("给的是壳 + 后台入口（admin.js 上屏），未登录时 view 里没有任何统计数据字段",
      "spa/admin.js" in html and denied.get("authed") is False
      and not any(k in denied for k in ("agg", "rows", "beh", "links")), list(denied)[:8])
check("未登录那一屏里没有任何查询数据（既不在壳里、也不在 view body 里）",
      "庆余年" not in html and "10.0.0.1" not in html and "庆余年" not in r.get_data(as_text=True), None)
check("后台壳带 noindex", 'name="robots" content="noindex' in html, None)
check("未登录的 view body 里给了 csrf（登录框就靠它，不再从 HTML 抠 name=\"csrf\"）",
      isinstance(denied.get("csrf"), str) and re.fullmatch(r"[0-9a-f]{32}", denied["csrf"]), denied.get("csrf"))

print("\n7) 登录流程")
tok = denied["csrf"]
r = client.post("/admin/login", data={"csrf": tok, "password": "cuo-de-mi-ma"})
check("错口令 401", r.status_code == 401, r.status_code)
check("错口令后提示剩余次数（口令不正确那句来自服务端节流器）",
      "还可尝试" in r.get_data(as_text=True), None)
r = client.post("/admin/login", data={"csrf": "deadbeef", "password": "wo-ziji-de-mima"})
check("csrf 不对时拒掉（400）", r.status_code == 400, r.status_code)
r = client.post("/admin/login", data={"csrf": tok, "password": "wo-ziji-de-mima"},
                follow_redirects=False)
check("对口令后 302 跳回统计页", r.status_code == 302 and "/admin" in r.headers["Location"],
      r.headers.get("Location"))
check("Set-Cookie 是 HttpOnly + SameSite=Lax",
      "HttpOnly" in r.headers["Set-Cookie"] and "samesite=lax" in r.headers["Set-Cookie"].lower())
# (a) 登录后原来在 /admin 那张 HTML 表里读关键词/IP/总条数/页码，现在这些数都在
#     /api/admin/view 的 JSON 里（rows.items / agg.count），页码那句写法在 Detail.tsx。
v = client.get("/api/admin/view").get_json()
check("登录后壳 200 且 view 回 authed=True", client.get("/admin").status_code == 200
      and v.get("authed") is True, v.get("authed"))
kws = {it.get("kw") for it in v["rows"]["items"]}
check("能看到关键词", "庆余年" in kws and "流浪地球" in kws, sorted(kws))
ips = {it.get("ip") for it in v["rows"]["items"]}
check("能看到 IP", {"10.0.0.1", "10.0.0.2"} & ips == {"10.0.0.1", "10.0.0.2"}, sorted(ips))
expect_total = stats_mod.list_queries({})["total"]
check("view 给的总条数与库里一致", v["agg"]["count"] == expect_total
      and v["rows"]["total"] == expect_total, (expect_total, v["agg"]["count"], v["rows"]["total"]))
check("有页码信息（第 N / M 页 · 共 X 条 这句由 Detail.tsx 拼）",
      "第 {rows.page} / {rows.pages} 页" in detail_ts and "共 {rows.total} 条" in detail_ts
      and "页 · 共" not in v.get("csrf", ""), None)

print("\n8) 后台的筛选与翻页真的接到了 SQL")
# (a) 原来 GET /admin?... 看渲染出来的表；现在带同样的查询串打 /api/admin/view，看它 JSON 里的
#     rows/agg/links —— 筛选与翻页走的仍是同一份 SQL（_admin_ctx 里那套）。
v = client.get("/api/admin/view?ip=10.0.0.1").get_json()
check("按 IP 过滤后只看得到这个 IP 的行",
      v["rows"]["items"] and all(it["ip"] == "10.0.0.1" for it in v["rows"]["items"]),
      sorted({it["ip"] for it in v["rows"]["items"]}))
check("IP 回填进筛选条件（数据在 flt，输入框在 Filters.tsx 里按 flt 现值绑）",
      v["flt"]["ip"] == "10.0.0.1" and "value={draft[k] ?? \"\"}" in filters_ts, v["flt"].get("ip"))
v = client.get("/api/admin/view?day_from=" + today() + "&day_to=" + today()).get_json()
today_kws = {it.get("kw") for it in v["rows"]["items"]}
check("按日期范围过滤生效", "繁花" in today_kws and "庆余年" not in today_kws, sorted(today_kws))
v = client.get("/api/admin/view?kw=" + "庆余年").get_json()
check("按关键词过滤生效", all((it.get("kw") or "").find("庆余年") >= 0 for it in v["rows"]["items"])
      and "流浪地球" not in {it.get("kw") for it in v["rows"]["items"]},
      sorted({it.get("kw") for it in v["rows"]["items"]}))
v = client.get("/api/admin/view?per=2&page=2").get_json()
check("翻页参数被接受", v["rows"]["page"] == 2 and v["rows"]["per"] == 2,
      (v["rows"]["page"], v["rows"]["per"]))
check("翻页链接保住了筛选条件（next 由服务端拼，带着 per 与 page）",
      v["links"]["next"] and "per=2" in v["links"]["next"] and "page=" in v["links"]["next"],
      v["links"].get("next"))
check("注入串当普通条件处理、不报错（view 仍 200）",
      client.get("/api/admin/view?ip=" + "1=1) OR 1=1 --").status_code == 200, None)

print("\n9) 埋点：三个入口各记一条")
_real_search = app_mod.search
_real_snapshot = app_mod.seo_mod.snapshot
_real_cloud = app_mod.cloudsearch.search
app_mod.search = lambda kw, page=1: {"keyword": kw, "results": [{"title": "x"}],
                                     "hits": 7, "sources_ok": 9, "sources_total": 10,
                                     "status": [], "dropped_noise": 0}
app_mod.seo_mod.snapshot = lambda kw, force=False: {
    "kw": kw, "count": 4, "sources_ok": 8, "sources_total": 10, "items": [],
    "from_cache": False}
app_mod.cloudsearch.search = lambda kw: {"keyword": kw, "sites": [], "entries": 2,
                                         "with_results": 1, "total_sites": 5}
try:
    before = stats_mod.list_queries({})["total"]
    client.get("/api/search?kw=" + "测试埋点A")
    client.get("/s/" + "测试埋点B")
    client.get("/api/cloud?kw=" + "测试埋点C")
    after = stats_mod.list_queries({})["total"]
    check("三个入口各写了一条", after - before == 3, (before, after))
    via = {x["kw"]: x["via"] for x in stats_mod.list_queries({"day_from": today()})["items"]}
    check("入口标记正确",
          via.get("测试埋点A") == "api" and via.get("测试埋点B") == "seo"
          and via.get("测试埋点C") == "cloud", via)
    hit = next(x for x in stats_mod.list_queries({})["items"] if x["kw"] == "测试埋点A")
    check("记到了命中源数与结果数", hit["sources_ok"] == 9 and hit["results"] == 1, hit)

    app_mod.seo_mod.snapshot = lambda kw, force=False: {
        "kw": kw, "count": 4, "sources_ok": 8, "sources_total": 10, "items": [],
        "from_cache": True}
    n0 = stats_mod.list_queries({})["total"]
    client.get("/s/" + "测试埋点B")
    check("命中 6 小时快照时不重复计数", stats_mod.list_queries({})["total"] == n0)

    n1 = stats_mod.list_queries({})["total"]
    client.get("/api/search?kw=a")        # 关键词太短，被拒
    client.get("/api/search?kw=")         # 空
    check("被拒的请求不记查询", stats_mod.list_queries({})["total"] == n1)
finally:
    app_mod.search = _real_search
    app_mod.seo_mod.snapshot = _real_snapshot
    app_mod.cloudsearch.search = _real_cloud

print("\n10) 统计写入失败也不能影响搜索")
app_mod.search = lambda kw, page=1: {"keyword": kw, "results": [], "hits": 0,
                                     "sources_ok": 0, "sources_total": 0, "status": [],
                                     "dropped_noise": 0}
_real_db = stats_mod.DB
stats_mod.DB = TMP / "no" / "such" / "stats.db"
try:
    r = client.get("/api/search?kw=" + "库不可写")
    check("统计库打不开时搜索仍返回 200", r.status_code == 200, r.status_code)
finally:
    stats_mod.DB = _real_db
    app_mod.search = _real_search
    app_mod.seo_mod.snapshot = _real_snapshot

print("\n11) 退出登录")
# (c) 判据不变，锚点换：csrf 从 view 拿；"再进 /admin 又要口令" 的门槛在 /api/admin/view 401
#     （/admin 本身是公开壳，永远 200）。
tok = client.get("/api/admin/view").get_json()["csrf"]
r = client.post("/admin/logout", data={"csrf": tok}, follow_redirects=False)
check("退出后 302", r.status_code == 302, r.status_code)
check("退出后再取后台数据又要口令了（门槛在 view 的 401，不在壳上）",
      client.get("/api/admin/view").status_code == 401, client.get("/api/admin/view").status_code)

print("\n12) robots 不进后台")
rb = client.get("/robots.txt").get_data(as_text=True)
check("robots 里 Disallow 了 /admin", "Disallow: /admin" in rb, rb)

print("\n13) 首次登录引导改口令")
# 用一个看起来就像自动生成的口令（12 位、小写字母+数字、不含 l/o）
GEN = "zx9k3mp7q2a4"
admin_mod.save({"password": GEN, "secret_key": cfg["secret_key"], "password_is_temp": True})
check("标记为临时口令时 is_temp_password 为真", admin_mod.is_temp_password())
c2 = app_mod.create_app().test_client()
r = c2.get("/api/admin/view")
check("没登录取数接口仍是 401", r.status_code == 401, r.status_code)
dtemp = r.get_json()
check("未登录的 view 说这还是首次生成的随机口令，登录框据此催你改（文案在 Login.tsx）",
      dtemp.get("temp") is True and "首次启动自动生成" in login_ts, None)
tok2 = dtemp["csrf"]
r = c2.post("/admin/login", data={"csrf": tok2, "password": GEN})
check("用临时口令登录成功", r.status_code == 302, r.status_code)
check("登录后先领着去改口令，而不是直接进统计页",
      "/admin/password" in r.headers["Location"] and "first=1" in r.headers["Location"],
      r.headers.get("Location"))
r = c2.get("/admin")
check("绕不开：硬访问 /admin 也会被引到改口令页",
      r.status_code == 302 and "/admin/password" in r.headers["Location"])
# (a) 改口令页转 React：GET /admin/password 回的是壳（boot.route 指到口令页 + admin.js 上屏），
#     三个口令字段、"保存即生效不用重启"那句、minlength 与下限一致，写法都在 Login.tsx 的 Password。
r = c2.get("/admin/password")
h = r.get_data(as_text=True)
check("改口令页 200 且壳把入口领到口令页（boot.route=/admin/password + admin.js 上屏）",
      r.status_code == 200 and "spa/admin.js" in h and "/admin/password" in h, (r.status_code,))
check("有当前口令与两次新口令输入（提交走 postForm 的 current/password/password2）",
      all(n in login_ts for n in ("current: cur", "password: a", "password2: b")), None)
check("提示保存即生效不用重启", "不用重启服务" in login_ts, None)
check("minlength 和后端下限一致（下限由服务端 boot.min_len 带下来，组件用它做 minLength）",
      dtemp.get("min_len") == admin_mod.MIN_LEN and "minLength={min" in login_ts
      and "minLen={boot.min_len" in adminapp_ts, dtemp.get("min_len"))
tok3 = c2.get("/api/admin/view").get_json()["csrf"]

r = c2.post("/admin/password", data={"csrf": tok3, "current": "bu-dui-de",
                                     "password": "xin-mi-ma-1", "password2": "xin-mi-ma-1"})
check("当前口令不对时拒绝（400）", r.status_code == 400 and "当前口令不对" in r.get_data(as_text=True))
r = c2.post("/admin/password", data={"csrf": tok3, "current": GEN,
                                     "password": "xin-mi-ma-1", "password2": "bu-yiyang"})
check("两次不一致时拒绝", r.status_code == 400 and "两次输入" in r.get_data(as_text=True))
r = c2.post("/admin/password", data={"csrf": tok3, "current": GEN,
                                     "password": "abc", "password2": "abc"})
check("太短被拒", r.status_code == 400 and f"至少 {admin_mod.MIN_LEN}" in r.get_data(as_text=True))
r = c2.post("/admin/password", data={"csrf": tok3, "current": GEN,
                                     "password": "  kong-ge  ", "password2": "  kong-ge  "})
check("首尾带空格被拒", r.status_code == 400 and "空格" in r.get_data(as_text=True))
check("被拒的那些口令都没写进文件", admin_mod.password_ok(GEN))

NEW = "wo-xuan-de-mi-ma"
r = c2.post("/admin/password", data={"csrf": tok3, "current": GEN,
                                     "password": NEW, "password2": NEW})
check("改成功后 302 回统计页", r.status_code == 302 and "set=1" in r.headers["Location"],
      r.headers.get("Location"))
check("新口令可用", admin_mod.password_ok(NEW))
check("旧随机口令失效", not admin_mod.password_ok(GEN))
check("文件里落的是新口令", NEW in admin_mod.CONFIG.read_text(encoding="utf-8"))
check("不再算临时口令", not admin_mod.is_temp_password())
r = c2.get("/admin")
check("这次能真正进统计页了", r.status_code == 200, r.status_code)
# (a) 提示与入口：口令已更新那句由服务端算好放进 view.notice（?set=1 触发），
#     "改口令"那颗链接是后台标题行画的（AdminApp.tsx）。
vset = c2.get("/api/admin/view?set=1").get_json()
check("页面上有口令已更新的提示（在 view.notice 里，不再靠 HTML）",
      "口令已更新" in (vset.get("notice") or ""), vset.get("notice"))
check("统计页上有改口令入口（AdminApp.tsx 标题行那颗）", "改口令" in adminapp_ts, None)

print("\n14) 临时口令判定与环境变量互锁")
admin_mod.save({"password": "wo-xuan-de-mi-ma", "secret_key": cfg["secret_key"]})   # 没有标记
check("手写的口令（带短横）不会被当成自动生成", not admin_mod.is_temp_password())
check("判定结果已写回文件，避免每次再猜",
      "password_is_temp" in admin_mod.CONFIG.read_text(encoding="utf-8"))
admin_mod.save({"password": GEN, "secret_key": cfg["secret_key"]})                # 没标记但像生成的
check("老文件没有标记时按样式判一次", admin_mod.is_temp_password())
os.environ["ZHUIJU_ADMIN_PASSWORD"] = "from-env-mi-ma"
check("环境变量指定口令时不再催你改", not admin_mod.is_temp_password())
check("页面能知道口令被环境变量锁住", admin_mod.using_env_password())
r = c2.get("/admin/password")
# (a) 口令页转 React：环境变量的说明那句由 Password 组件画（login_ts），壳本身只在 boot 里带
#     env_lock 这个布尔——两者合起来才是"页面上说明清楚"。
pb = json.loads(r.get_data(as_text=True).split('<script id="boot-data" type="application/json">')[1]
                .split("</script>")[0])
check("被环境变量锁住时页面上说明清楚（说明在 Login.tsx，壳的 boot 带着 env_lock）",
      pb.get("env_lock") is True and "ZHUIJU_ADMIN_PASSWORD" in login_ts, pb.get("env_lock"))
del os.environ["ZHUIJU_ADMIN_PASSWORD"]
admin_mod.save({"password": NEW, "secret_key": cfg["secret_key"], "password_is_temp": False})

print("\n15) 归属地：写入、回填、筛选、聚合、投影")
from zhuiju import geoip  # noqa: E402

check("归属地库在这台机器上是可用的（若失败说明是环境问题不是代码问题）",
      geoip.available()["xdb"] and geoip.available()["points"], geoip.available())
pub = geoip.locate("8.8.8.8")
check("公网 IP 给出国家与 ISO", pub["kind"] == "public" and pub["iso"] == "US", pub)
check("坐标算出来且在美国范围内", 25 < pub["lat"] < 50 and -125 < pub["lon"] < -66, pub)
check("国家码能查到对应坐标", geoip.points()["US"]["lat"] == pub["lat"])
for ip, kind in (("127.0.0.1", "loopback"), ("10.1.2.3", "private"), ("192.168.9.9", "private"),
                 ("172.16.5.5", "private"), ("169.254.1.1", "reserved"), ("100.64.1.2", "reserved"),
                 ("239.1.1.1", "reserved"), ("203.0.113.5", "reserved"), ("192.0.2.1", "reserved"),
                 ("198.18.0.1", "reserved"), ("乱写的", "invalid")):
    got = geoip.locate(ip)["kind"]
    check(f"{ip} 判为 {kind}", got == kind, got)
check("内网类都不进地图（没有坐标）",
      all(geoip.locate(ip)["lat"] is None for ip in
          ("127.0.0.1", "10.1.2.3", "192.168.9.9", "100.64.1.2", "239.1.1.1")))
check("中文标签没有多余空格", "  " not in geoip.locate("223.5.5.5")["label"],
      repr(geoip.locate("223.5.5.5")["label"]))
check("省级信息只给国内", "杭州" in geoip.locate("223.5.5.5")["label"]
      and "California" not in geoip.locate("8.8.8.8")["label"])

# record() 要顺手把归属地写进去——之前占位符比列数多一个，异常被吞了，
# 结果是一条都没插入而页面看起来正常，所以这条必须钉住
n0 = stats_mod.list_queries({})["total"]
stats_mod.record("归属地入库", "8.8.8.8", via="api", results=3)
row = stats_mod.list_queries({"kw": "归属地入库"})["items"][0]
check("record 确实落库了一条", stats_mod.list_queries({})["total"] == n0 + 1)
check("record 自动补了 ISO 与归属地文案",
      row["iso"] == "US" and "United States" in (row["geo"] or ""), dict(row))
stats_mod.record("内网入库", "192.168.1.7", via="api", results=1)
row2 = stats_mod.list_queries({"kw": "内网入库"})["items"][0]
check("内网 IP 的 iso 是空串而不是瞎猜国家", row2["iso"] == "", row2)
check("内网 IP 有可读文案", row2["geo"] == "内网", row2)

# 老库里补列之前的行是 NULL，backfill 要能填上
con = stats_mod.connect()
con.execute("INSERT INTO queries (ts, day, ip, kw, via, results, iso, geo)"
            " VALUES ('2026-10-15 09:00:00', '2026-10-15', '1.1.1.1', '回填测试', 'api', 2, NULL, NULL)")
con.commit()
con.close()
done = stats_mod.backfill_geo()
row3 = stats_mod.list_queries({"kw": "回填测试"})["items"][0]
check("backfill 把 NULL 的行补上了归属地", row3["iso"] == "AU" and done >= 1, (done, row3))
check("回填过的行不会被反复重算", stats_mod.backfill_geo() == 0)

bygeo = stats_mod.summary({})["by_geo"]
buckets = {g["iso"]: g for g in bygeo}
check("聚合里有美国与澳洲两个桶", {"US", "AU"} <= {g["iso"] for g in bygeo},
      [g["iso"] for g in bygeo])
empty_bucket = [g for g in bygeo if not g["iso"]]
check("内网/保留/非法合到一个空 ISO 桶", len(empty_bucket) == 1 and empty_bucket[0]["n"] >= 1,
      empty_bucket)
check("桶里的次数与 IP 数都聚合上了", all(g["n"] >= g["ips"] or g["ips"] == 0 for g in bygeo),
      [(g["n"], g["ips"]) for g in bygeo][:4])
check("聚合按次数倒序", [g["n"] for g in bygeo] == sorted([g["n"] for g in bygeo], reverse=True),
      [g["n"] for g in bygeo])
only_us = stats_mod.list_queries({"geo": "US"})
check("按国家码筛选", all(r["iso"] == "US" for r in only_us["items"]) and only_us["total"] >= 1,
      only_us["total"])
only_in = stats_mod.list_queries({"geo": "--"})
check("'--' 能筛内网/保留", only_in["total"] >= 1 and
      all(not r["iso"] for r in only_in["items"]), only_in["total"])
check("认不出的国家码不参与过滤", stats_mod.list_queries({"geo": "XXYY"})["total"]
      == stats_mod.list_queries({})["total"])

from zhuiju.app import _markers  # noqa: E402
ms = _markers([{"iso": "CN", "geo": "中国", "n": 12, "ips": 3, "kws": 2, "last_day": "x"},
               {"iso": "", "geo": "内网", "n": 99, "ips": 2, "kws": 1, "last_day": "x"},
               {"iso": "US", "geo": "United States", "n": 3, "ips": 1, "kws": 1, "last_day": "x"}])
check("地图点位跳过内网", [m["iso"] for m in ms] == ["CN", "US"], [m["iso"] for m in ms])
cn = ms[0]
check("投影用等距圆柱：x=经度+180, y=90-纬度",
      abs(cn["x"] - (geoip.points()["CN"]["lon"] + 180)) < 0.02
      and abs(cn["y"] - (90 - geoip.points()["CN"]["lat"])) < 0.02, cn)
check("点的大小按 sqrt(次数) 缩放", ms[0]["r"] / ms[1]["r"] < (12 / 3), (ms[0]["r"], ms[1]["r"]))
check("大点在前面（先画、不被小点盖住）", [m["n"] for m in ms] == sorted([m["n"] for m in ms], reverse=True))

bm = geoip.basemap()
check("底图有轮廓路径且不是空串", len(bm["d"]) > 10000, len(bm["d"]))
check("底图按国家码索引了轮廓", "CN" in bm["by_iso"] and "US" in bm["by_iso"])
check("底图路径坐标在 viewBox 内", all(-1 < v < 361 for v in
      [float(x.split(",")[0]) for x in bm["by_iso"]["CN"][1:].split("Z")[0].split("L")[:200]]))
check("底图大小适合内嵌（<400KB）", len(bm["d"]) < 400_000, len(bm["d"]) // 1024)

print("\n16) 缺数据文件时的降级")
_real_geo_paths = (geoip.XDB_V4, geoip.POINTS, geoip.BASEMAP, geoip.DATA)
geoip.DATA = TMP
geoip.XDB_V4 = TMP / "nope.xdb"
geoip.POINTS = TMP / "nope.json"
geoip.BASEMAP = TMP / "nope.geo.json"
geoip.reset()
try:
    av = geoip.available()
    check("缺库时 available 标出来", not av["xdb"] and not av["ready"], av)
    r = geoip.locate("8.8.8.8")
    check("缺库时不抛异常，标 nolib", r["kind"] == "nolib" and "未下载" in r["label"], r)
    check("缺库时内网判定仍然照常（不依赖库）", geoip.locate("10.0.0.1")["kind"] == "private")
    check("缺坐标表时 points() 返回空 dict", geoip.points() == {})
    check("缺底图时 basemap 给出说明而不是崩", "error" in geoip.basemap(), geoip.basemap().get("error"))
    n1 = stats_mod.list_queries({})["total"]
    stats_mod.record("缺库时仍能记", "8.8.8.8", via="api", results=1)
    check("归属地库缺失不影响统计写入", stats_mod.list_queries({})["total"] == n1 + 1)
    rr = stats_mod.list_queries({"kw": "缺库时仍能记"})["items"][0]
    check("缺库时 iso 留空而不是编造", rr["iso"] in ("", None), rr)
finally:
    (geoip.XDB_V4, geoip.POINTS, geoip.BASEMAP, geoip.DATA) = _real_geo_paths
    geoip.reset()
check("还原后归属地又可用了", geoip.available()["ready"])

print("\n17) 登录后的统计页真的画出地图来（整条路径）")
# 造几个公网来源：record 直接写，省掉 HTTP 层，但渲染走的仍是 app.py + 模板
for ip, kw in (("223.5.5.5", "庆余年"), ("8.8.8.8", "流浪地球"), ("1.1.1.1", "繁花"),
               ("91.108.4.11", "灌篮高手"), ("3.0.0.0", "奥本海默"), ("192.168.1.50", "庆余年"),
               ("127.0.0.1", "繁花")):
    stats_mod.record(kw, ip, via="api", results=5, hits=20, sources_ok=10,
                     sources_total=10, ms=1000)
c3 = app_mod.create_app().test_client()
tok3 = c3.get("/api/admin/view").get_json()["csrf"]
c3.post("/admin/login", data={"csrf": tok3, "password": NEW})
ov = c3.get("/api/admin/view?tab=overview").get_json()
# (a) 原来这几条从 /admin 渲染出的那张 <svg class="worldmap"> 数 <circle>。后台转 React 后
#     地图由 Overview.tsx 的 GeoMap 画一棵 viewBox="0 0 360 180" 的静态 SVG，点位/坐标/描色国家
#     全部来自服务端算好、放进 view 的 markers/map_active。数据钉 view，画法钉组件。
check("登录后台壳 200 且 view 回 authed=True", c3.get("/admin").status_code == 200
      and ov.get("authed") is True, ov.get("authed"))
check("有地图画布（GeoMap 画的 SVG）", "<svg" in overview_ts and 'viewBox="0 0 360 180"' in overview_ts, None)
check("SVG 用 viewBox 0 0 360 180（投影一致才对得上）", 'viewBox="0 0 360 180"' in overview_ts, None)
markers = ov["markers"]
check("画出了 5 个公网点位（内网与本机不画，marker 由服务端 _markers 从 by_geo 算）",
      len(markers) == 5, [m["iso"] for m in markers])
check("所有点位都落在 viewBox 内（x∈[0,360]、y∈[0,180]）",
      all(0 <= m["x"] <= 360 and 0 <= m["y"] <= 180 for m in markers),
      [(m["x"], m["y"]) for m in markers])
check("有归属地列（明细表头里那一列，Detail.tsx）", '"归属地"' in detail_ts, None)
check("明细里出现了具体归属地（数据在 rows.items 的 geo 上）",
      any(("中国" in (it.get("geo") or "") or "United States" in (it.get("geo") or ""))
          for it in ov["rows"]["items"]), [it.get("geo") for it in ov["rows"]["items"][:6]])
check("国家行可点筛选（归属地表里两字国家码那行由 filterUrl({ geo: g.iso }) 变成一次筛选）",
      "filterUrl({ geo: g.iso })" in overview_ts
      and sum(1 for g in ov["agg"]["by_geo"] if g["iso"] and len(g["iso"]) == 2) >= 5,
      [g["iso"] for g in ov["agg"]["by_geo"]])
check("内网单独成一行而不是编造国家", "内网 / 保留地址" in overview_ts, None)
# (b) 旧那句"没有地理归属"的解释散文只在已退役的 admin.html 里；React 没有对应文案。
#     等价的那一半：内网/保留（空 iso）不进 marker（_markers 跳过空 iso），所以它只会成表里一行。
check("内网不上图的等价保证：空 iso 不生成 marker（组件里没有内网点）",
      all(m["iso"] for m in markers) and not any((it.get("iso") or "") == "" and it.get("x") is not None
                                                 for it in markers), None)
check("底图轮廓被描色的只有存在记录的国家（map_active 是一份合并路径，只描有描得上的国家）",
      "map-land-on" in overview_ts and bool(ov["map_active"]) and ov["map_active"].strip(), None)
d2 = c3.get("/api/admin/view?tab=overview&geo=CN").get_json()
check("按国家筛选后只看得到该国的明细", d2["rows"]["items"]
      and all((it.get("iso") or "") == "CN" for it in d2["rows"]["items"]),
      sorted({it.get("iso") for it in d2["rows"]["items"]}))
d3 = c3.get("/api/admin/view?tab=overview&geo=--").get_json()
check("筛内网能看到内网行", any((it.get("iso") or "") == "" for it in d3["rows"]["items"]),
      sorted({it.get("iso") or "-" for it in d3["rows"]["items"]}))
check("只看内网时地图上一个点都没有", len(d3["markers"]) == 0, len(d3["markers"]))

print("\n18) 老库升级：补列 + 建索引 + 回填，一步都不能静默失败")
# 曾经的真实故障：idx_queries_iso 写在 SCHEMA 里，对已有库就是"给还不存在的列建索引"，
# ensure_schema 抛错、create_app 的 try 把它吞掉，症状只是"归属地永远是空"。
old = TMP / "old.db"
oc = sqlite3.connect(str(old))
oc.execute("CREATE TABLE queries (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,"
           " day TEXT NOT NULL, ip TEXT NOT NULL, kw TEXT NOT NULL, via TEXT NOT NULL,"
           " results INTEGER, hits INTEGER, sources_ok INTEGER, sources_total INTEGER, ms REAL)")
oc.executemany("INSERT INTO queries (ts, day, ip, kw, via, results) VALUES (?,?,?,?,?,?)",
               [("2026-10-15 08:00:0%d" % i, "2026-10-15", ip, f"老记录{i}", "api", 3)
                for i, ip in enumerate(["223.5.5.5", "8.8.8.8", "192.168.1.9", "1.1.1.1"])])
oc.commit()
oc.close()
_real_db2, stats_mod._ready = stats_mod.DB, False
stats_mod.DB = old
stats_mod.MIGRATE_ERROR = ""
try:
    cols_before = [r[1] for r in sqlite3.connect(str(old)).execute("PRAGMA table_info(queries)")]
    check("老库确实没有 iso/geo 列", "iso" not in cols_before and "geo" not in cols_before, cols_before)
    stats_mod.ensure_schema()
    con = sqlite3.connect(str(old))
    con.row_factory = sqlite3.Row
    cols_after = [r[1] for r in con.execute("PRAGMA table_info(queries)")]
    check("升级后补上了 iso/geo", "iso" in cols_after and "geo" in cols_after, cols_after)
    check("升级没有报错", stats_mod.MIGRATE_ERROR == "", stats_mod.MIGRATE_ERROR)
    idx = [r[1] for r in con.execute("PRAGMA index_list(queries)")]
    check("iso 的索引也建上了", "idx_queries_iso" in idx, idx)
    nulls = con.execute("SELECT COUNT(*) FROM queries WHERE iso IS NULL").fetchone()[0]
    check("历史行被回填，没留 NULL", nulls == 0, nulls)
    filled = {r["ip"]: (r["iso"], r["geo"]) for r in
              con.execute("SELECT ip, iso, geo FROM queries ORDER BY id")}
    con.close()
    check("回填出来的归属地是对的", filled["223.5.5.5"][0] == "CN"
          and filled["8.8.8.8"][0] == "US" and filled["1.1.1.1"][0] == "AU", filled)
    check("内网那行回填成空 iso + 可读文案",
          filled["192.168.1.9"][0] == "" and filled["192.168.1.9"][1] == "内网", filled)
    check("升级后按国家筛选能查到历史数据",
          stats_mod.list_queries({"geo": "CN"})["total"] == 1,
          stats_mod.list_queries({"geo": "CN"})["total"])
    # 补列之前这批行的 browser/os/device 也是 NULL，而新写的用 '未知'/''——同一含义两种写法
    # 会在「浏览器 / 设备」里占两行都叫「未知」（真实库里就撞上过：16 条 + 9 条），
    # 点进去的过滤条件还只命中其中一套，数字对不上
    con2 = sqlite3.connect(str(old))
    null_agent = con2.execute("SELECT COUNT(*) FROM queries WHERE browser IS NULL"
                              " OR device IS NULL OR os IS NULL").fetchone()[0]
    con2.close()
    check("升级把这三列也归一了，库里不留 NULL", null_agent == 0, null_agent)
    s_old = stats_mod.summary({}, top=15)
    unk = [b for b in s_old["by_browser"] if b["browser"] == "未知"]
    check("没有 UA 的老记录在面板上只占一行「未知」", len(unk) == 1, s_old["by_browser"])
    check("那一行是全部 4 条，不是只算一段", bool(unk) and unk[0]["n"] == 4, unk)
    check("点「未知」进去还是这 4 条（浏览器口径与面板对得上）",
          stats_mod.list_queries({"browser": "未知"})["total"] == (unk[0]["n"] if unk else None),
          stats_mod.list_queries({"browser": "未知"})["total"])
    check("设备口径也对得上",
          stats_mod.list_queries({"device": "未知"})["total"] == (unk[0]["n"] if unk else None),
          stats_mod.list_queries({"device": "未知"})["total"])
finally:
    stats_mod.DB, stats_mod._ready = _real_db2, False
    stats_mod.MIGRATE_ERROR = ""
    stats_mod.ensure_schema()

print("\n18b) 就算没升级到一半，NULL / '' / '未知' 也得并成一个桶")
# 上面是"跑过 ensure_schema 之后"；这里故意绕开迁移，直接查一个混着三种写法的库，
# 验证聚合与过滤自己会并桶（备份恢复、老库刚补完列还没归一这类情况）
mix = TMP / "mix.db"
mc = sqlite3.connect(str(mix))
mc.executescript(stats_mod.SCHEMA)
mc.executemany("INSERT INTO queries (ts, day, ip, kw, via, browser, os, device, bot, ua)"
               " VALUES (?,?,?,?,?,?,?,?,?,?)",
               [("2026-10-16 09:00:%02d" % i, "2026-10-16", "1.1.1.%d" % (i + 2),
                 "混着%d" % i, "api", b, o, d, 0, "Mozilla/5.0")
                for i, (b, o, d) in enumerate([(None, None, None), ("未知", "", "未知"),
                                               ("", "", ""), (None, None, None)])])
mc.commit()
mc.close()
_real_db3, _ready3 = stats_mod.DB, stats_mod._ready
stats_mod.DB, stats_mod._ready = mix, True       # _ready=True：跳过 ensure_schema 的归一
try:
    s = stats_mod.summary({}, top=15)
    u = [x for x in s["by_browser"] if x["browser"] == "未知"]
    check("库里确实混着三种写法",
          sqlite3.connect(str(mix)).execute(
              "SELECT COUNT(*) FROM queries WHERE browser IS NULL OR browser = ''").fetchone()[0] == 3,
          None)
    check("没归一也只有一行「未知」，四条全在里面",
          len(u) == 1 and u[0]["n"] == 4, s["by_browser"])
    check("浏览器与设备两个口径都命中四条",
          stats_mod.list_queries({"browser": "未知"})["total"] == 4
          and stats_mod.list_queries({"device": "未知"})["total"] == 4,
          (stats_mod.list_queries({"browser": "未知"})["total"],
           stats_mod.list_queries({"device": "未知"})["total"]))
    con = sqlite3.connect(str(mix))
    first = stats_mod.normalize_agent(con)
    con.commit()
    again = stats_mod.normalize_agent(con)
    nul = con.execute("SELECT COUNT(*) FROM queries WHERE browser IS NULL"
                      " OR os IS NULL OR device IS NULL").fetchone()[0]
    con.close()
    check("归一函数幂等：第一次改 2 行，第二次 0 行，之后库里没有 NULL",
          first == 2 and again == 0 and nul == 0, (first, again, nul))
    check("归一完再查，还是那一行四条",
          [x for x in stats_mod.summary({}, top=15)["by_browser"]
           if x["browser"] == "未知"][0]["n"] == 4, None)
finally:
    stats_mod.DB, stats_mod._ready = _real_db3, _ready3

print("\n19) 区块顺序与明细翻页控件")
# (a) 原来这一节整段读 /admin 那张 HTML（asect 顺序、jumpform、data-page、DOMParser 局部刷新、
#     innerHTML+refold、getElementById('detail')）。后台转 React 后：块顺序由服务端 tabs 下发、
#     翻页控件在 Detail.tsx、局部刷新那套手工 DOM 没了（换筛选/换页就是重新取一份 view）。
#     每条按新载体重钉；纯手工 DOM 的（cpage/SECTIONS/DOMParser）按 (b) 换成它等价的那一半。
ov19 = c3.get("/api/admin/view?per=2&page=2&kw=" + "繁花&tab=detail").get_json()
tabs = ov19["tabs"]
# id 里带连字符（top-kw / strm-zips…），这里直接比服务端下发的 tabs→blocks 顺序
flat = [b[0] for t in tabs for b in t["blocks"]]
check("标签分组按 ADMIN_TABS 排：总览那几块在前，明细后接行为特征、STRM（含两块子表）、设置最后",
      [t["id"] for t in tabs] == ["overview", "detail", "strm", "settings"]
      and flat == ["stat", "days", "top-kw", "top-ip", "agents", "refs", "geo",
                   "detail", "behavior", "strm", "strm-zips", "strm-src", "settings"], flat)
# (b) 旧那句"明细在归属地之前"在整页布局下成立；分标签后 geo 归总览、detail 归明细，
#     跨标签的先后变成"总览标签整体在明细之前、设置在最后一个标签"。等价的那一半照钉。
check("归属地所在的总览排在明细标签之前、设置是最后一个标签（翻数据的人不该先撞见配置）",
      flat.index("geo") < flat.index("detail") and tabs[-1]["id"] == "settings"
      and flat[-1] == "settings", flat[-3:])
check("翻页区有跳转控件（跳转框 + 那颗 goPage，都在 Detail.tsx）",
      'aria-label="页码"' in detail_ts and "goPage(Number(jump)" in detail_ts, None)
check("跳转框是 number 且带 min/max（max 跟着真实页数走）",
      'type="number"' in detail_ts and "min={1}" in detail_ts and "max={rows.pages}" in detail_ts, None)
check("跳转与筛选都保住了当前条件（服务端把 per/页码拼好、组件的 goPage 也带着 per）",
      ov19["flt"]["kw"] == "繁花" and ov19["flt"]["per"] == 2 and ov19["rows"]["page"] == 2,
      {k: ov19["flt"].get(k) for k in ("kw", "per")})
# (b) data-page/DOMParser 那套"原地刷新一块"的局部更新随整页 HTML 一起退役了：
#     React 里点下一页就是走 links.next 重取整屏。等价的那一半是翻页链接仍带住筛选条件。
check("翻页链接带住筛选条件（prev/next 由服务端拼，带着 kw 与 page）",
      all(("kw=" in (u or "") or "繁花" in (u or "")) for u in (ov19["links"]["prev"], ov19["links"]["next"]) if u),
      {k: ov19["links"].get(k) for k in ("prev", "next")})
check("页码输入框初值是当前页（React 用 rows.page 直接 seed 那个 draft）",
      'useState(String(rows.page))' in detail_ts and "value={jump}" in detail_ts, None)
# (b) "局部刷新脚本只在登录后出现" 原来靠 DOMParser 只在 authed 分支渲染；SPA 里脚本始终随壳加载，
#     真正挡人的是数据门槛（未登录 view 里没有 rows/agg）。钉这一条等价判据。
check("后台入口脚本随壳加载，但门槛在数据：未登录 view 里根本没有 rows/agg，登录后才有",
      "DOMParser" not in detail_ts
      and client.get("/api/admin/view").get_json().get("rows") is None
      and ov19.get("rows") is not None, None)
check("翻页不滚页面：翻页走 onGo（pushState + 重取），明细组件里没有任何滚动定位",
      "onGo(v.links!.prev)" in detail_ts and "onGo(v.links!.next)" in detail_ts
      and "scrollIntoView" not in detail_ts and "window.scrollTo" not in detail_ts, None)
check("也就不需要给 #detail 留滚动避让了（滚动避让改由 Block 上的 scroll-mt 给目录锚点用）",
      "#detail { scroll-margin-top" not in
      (BASE / "zhuiju" / "static" / "app.css").read_text(encoding="utf-8")
      and "scroll-mt-14" in adminui_ts, None)
# (b) "换页后整块换 innerHTML 从第一行起、再 refold()" 是手工刷新；React 里翻页换的是整份 rows
#     快照、内联滚动框由 useClamp 的 ResizeObserver/MutationObserver 重新量。等价形态是组件里没有 innerHTML 赋值。
clamp_ts = (BASE / "web" / "src" / "hooks" / "useClamp.ts").read_text(encoding="utf-8")
check("换页后由 useClamp 重新量内联滚动框，不再手工换 innerHTML",
      "innerHTML" not in detail_ts and "new ResizeObserver" in clamp_ts
      and "new MutationObserver" in clamp_ts, None)
check("明细的翻页控件仍只有 page 一套（cpage 那套随独立面板一起撤了）",
      "filterUrl({ page:" in detail_ts and "cpage" not in detail_ts and "SECTIONS" not in detail_ts, None)
check("只剩明细一个区块要原地翻页，React 里没有任何按 id 找块的遗留脚本",
      "getElementById('detail')" not in detail_ts, re.findall(r"getElementById\([^)]*\)", detail_ts)[:4])

print("\n20) 观看点击：接口收什么、明细合流以后长什么样")
ct = lambda f={}: stats_mod.click_stats(f)["count"]        # noqa: E731
def ev(f={}, scope="click"):     # 合流列表：默认只看点开那一半
    return stats_mod.list_activity(f, per=200, scope=scope)["items"]
base = {"kw": "庆余年", "title": "庆余年 第一季", "src": "hhzy", "src_name": "火狐资源",
        "vid": "123", "line": "新浪线路", "ep": "第03集", "place": "panel"}
n0 = ct()
r = c3.post("/api/click", json={**base, "url": "https://v.example.com/play/3.html"})
check("点一条观看地址：204、真的落库", r.status_code == 204 and ct() == n0 + 1,
      (r.status_code, ct() - n0))
r = c3.post("/api/click", json={**base, "url": "javascript:alert(1)"})
check("javascript: 这类地址不进库（这一列进后台是要当链接点的）",
      r.status_code == 204 and ct() == n0 + 1, ct() - n0)
r = c3.post("/api/click", json={**base, "url": ""})
check("空地址不进库", r.status_code == 204 and ct() == n0 + 1, ct() - n0)
row = ev({"kw": "庆余年"})[0]
check("存下来的是哪条：域名单独一列，聚合才按得住",
      row["host"] == "v.example.com" and row["place"] == "panel" and row["ep"] == "第03集", row)
big = "T" * 500
c3.post("/api/click", json={"url": "https://x.test/a?token=" + big, "kw": "K" * 200,
                            "title": "J" * 300, "line": "L" * 200, "ep": "E" * 200,
                            "src": "S" * 200, "vid": "V" * 200})
row2 = ev({"kw": "K" * 60})[0]
check("字段一律截断，长度封顶",
      len(row2["url"]) <= stats_mod.CLICK_MAX_URL and len(row2["kw"]) <= 60
      and len(row2["title"]) <= 80 and len(row2["line"]) <= 40
      and len(row2["src"]) <= 32 and len(row2["vid"]) <= 32,
      {k: len(row2[k] or "") for k in ("url", "kw", "title", "line", "src", "vid")})
c3.post("/api/click", json={"url": "https://y.test/b", "place": "bu-cun-zai"})
check("place 不在枚举里退回卡片线路，不写一个没人认识的值",
      any(x["place"] == "card" and x["host"] == "y.test" for x in ev()), None)
r = c3.post("/api/click", data=json.dumps({"url": "https://z.test/c", "kw": "正文"}),
            content_type="text/plain")
check("sendBeacon 有时按 text/plain 发，正文照样解析",
      r.status_code == 204 and stats_mod.click_stats({"host": "z.test"})["count"] == 1,
      stats_mod.click_stats({"host": "z.test"})["count"])
r = c3.post("/api/click", data="这不是 JSON", content_type="application/json")
check("正文不是 JSON 也不 500（埋点不能把点击请求变成错误）", r.status_code == 204, r.status_code)
r = c3.post("/api/click", json={"url": "https://w.test/d;1=1) OR 1=1 --", "kw": "' OR 1=1 --"})
check("脏输入不炸也不改写 SQL", r.status_code == 204, r.status_code)
big_body = json.dumps({"url": "https://big.test/" + "A" * (40 * 1024)})
n_before = ct()
r = c3.post("/api/click", data=big_body, content_type="application/json")
check("公开接口的正文有上限：超了直接 413，不进来解析也不落库",
      r.status_code == 413 and ct() == n_before, (r.status_code, ct() - n_before))
_max, _rate = app_mod.CLICK_MAX, dict(app_mod._click_rate)
try:
    app_mod._click_rate.clear()
    app_mod.CLICK_MAX = 3
    got = [c3.post("/api/click", json={"url": f"https://r.test/{i}"}).status_code for i in range(6)]
    check("公开接口按 IP 限流：超过上限的丢掉、但仍然回 204（回 4xx 只会让前端重试）",
          set(got) == {204} and stats_mod.click_stats({"host": "r.test"})["count"] == 3,
          stats_mod.click_stats({"host": "r.test"})["count"])
finally:
    app_mod.CLICK_MAX, app_mod._click_rate = _max, _rate

print("\n21) 后台的详情/观看面板与明细那一列")
q0 = stats_mod.list_queries({}, per=1)["items"][0]
stats_mod.record_click(q0["ip"], kind="detail", kw=q0["kw"], title="测试片",
                       src="hhzy", src_name="火狐资源", vid="88", place="hot",
                       ua="Mozilla/5.0 (Windows NT 10.0) Chrome/124.0")
stats_mod.record_click(q0["ip"], url="https://k.test/1", kw=q0["kw"], title="测试片",
                       src="hhzy", src_name="火狐资源", line="新浪线路", ep="第01集",
                       place="panel", ua="Mozilla/5.0 (Windows NT 10.0) Chrome/124.0")
stats_mod.record_click(q0["ip"], url="https://k.test/2", kw=q0["kw"], title="测试片",
                       place="card", ua="Mozilla/5.0")
check("点详情按钮也落库，而且本来就没有播放地址",
      stats_mod.click_stats({"kind": "detail"})["count"] == 1
      and ev({"kind": "detail"})[0]["url"] == "",
      ev({"kind": "detail"})[:1])
s_kind = stats_mod.click_stats({})
check("detail 与 play 分得开，而且两数加起来就是总数",
      s_kind["detail"] == 1 and s_kind["play"] == s_kind["count"] - 1
      and s_kind["detail"] + s_kind["play"] == s_kind["count"],
      {k: v for k, v in s_kind.items() if k in ("count", "detail", "play")})
merged = stats_mod.list_activity({"ip": q0["ip"], "kw": q0["kw"]}, per=200)
kinds = [x["type"] for x in merged["items"]]
check("同一个 IP 同一个词：搜索行与点开行合在一张列表里",
      kinds.count("query") == 1 and kinds.count("click") == 3, kinds)
check("合流按时间倒序",
      [x["ts"] for x in merged["items"]] ==
      sorted([x["ts"] for x in merged["items"]], reverse=True)
      and merged["items"][0]["ts"] == max(x["ts"] for x in merged["items"]),
      [(x["type"], x["ts"]) for x in merged["items"]])
# 这里不断言"第一行是搜索还是点开"：种子数据那条搜索写的是固定时刻 12:00:00，
# 而点击用的是真实当前时间 —— 过了中午点击反而更晚，哪种都在理，测的是倒序不是谁在上头。
check("点开行带的就是那一行该带的：片名、线路、集、域名、从哪儿点的",
      all(x["title"] == "测试片" for x in merged["items"] if x["type"] == "click")
      and any(x["line"] == "新浪线路" and x["ep"] == "第01集" and x["host"] == "k.test"
              and x["place"] == "panel" for x in merged["items"])
      and any(x["place"] == "hot" for x in merged["items"]), None)
check("搜索行仍然带结果数，点开行这几列是 NULL 不是 0（0 会被读成「搜了没结果」）",
      next(x for x in merged["items"] if x["type"] == "query")["results"] is not None
      and all(x["results"] is None and x["ms"] is None
              for x in merged["items"] if x["type"] == "click"), None)
dv = c3.get("/api/admin/view?tab=detail&ip=" + q0["ip"] + "&kw=" + q0["kw"]).get_json()
clicks = [it for it in dv["rows"]["items"] if it["type"] == "click"]
# (a) 原来这一段读 /admin 明细表渲染出的 <tr class="crow">。转 React 后：哪些是点开行、每行带
#     什么，全在 view 的 rows.items 里；行上的标记（row-click）、把来源/动作写成人话的 labels、
#     破折号与「零结果」那格的红，都在 Detail.tsx + 服务端 labels。逐条搬到这两处钉。
check("点开行有自己那一行该带的数据（片名/线路/集/域名），行上另有标记",
      len(clicks) == 3 and any(it.get("line") == "新浪线路" and it.get("ep") == "第01集"
                               and it.get("host") == "k.test" for it in clicks)
      and "row-click" in detail_ts, [it.get("host") for it in clicks])
check("从哪儿点的、点了什么都写成人话，猜你想搜那种来源也认得（文案由服务端 labels 下发、组件套用）",
      set(dv["labels"]["place"].values()) >= {"海报详情", "卡片线路", "猜你想搜"}
      and "观看地址" in dv["labels"]["kind"].values() and "详情" in dv["labels"]["kind"].values()
      and "v.labels.place" in detail_ts and "v.labels.kind" in detail_ts, None)
# (b) 旧版明细行上那套展开开关（evbtn / evr）整块撤了，行内容一次铺全；aria-expanded 现在只剩
#     「像脚本的行为特征」那一节的折叠用（另一件事），所以这里只钉明细行没有 evbtn/evr。
check("明细行没有展开开关那套遗留（行内容一次铺全，不再 evbtn/evr 点开）",
      "evbtn" not in detail_ts and "evr" not in detail_ts, None)
# (a) 点开行的数字格是破折号而不是 0：数据侧 results/hits 是 None，渲染侧 Detail.tsx 用三元把
#     null 写成 "—"，且只有 results===0 才给那格上「零结果」的红。
check("点开行的数字格是破折号而不是 0（数据是 None，组件渲染成 —）",
      all(it["results"] is None for it in clicks)
      and 'r.results === null || r.results === undefined ? "—"' in detail_ts, None)
check("破折号那一格不套「零结果」的红，否则看着像这个人搜了没搜到",
      "zero={r.results === 0}" in detail_ts, None)
# (c) 独立的「详情与观看点击」表已经撤掉，事件合流进明细：块清单里不再有 clicks 这一块。
flat_ids = [b[0] for t in dv["tabs"] for b in t["blocks"]]
check("独立的「详情与观看点击」表已经撤掉，事件不再单开一处",
      "clicks" not in flat_ids and "cpage" not in detail_ts, flat_ids)
check("标题行给了「全部 / 只看搜索 / 只看点开」三个出口，当前那个高亮（scope 胶囊）",
      set(dv["labels"]["scope"].values()) == {"全部", "只看搜索", "只看点开"}
      and "Object.entries(v.labels.scope)" in detail_ts
      and dv["links"]["scopes"]["click"].find("scope=click") >= 0, dv["labels"]["scope"])
dc = c3.get("/api/admin/view?tab=detail&scope=click&kw=" + q0["kw"]).get_json()
check("只看点开：这一屏全是点开行，搜索行一条都不剩",
      dc["rows"]["items"] and all(it["type"] == "click" for it in dc["rows"]["items"])
      and len(dc["rows"]["items"]) == 3, [it["type"] for it in dc["rows"]["items"]])
dq = c3.get("/api/admin/view?tab=detail&scope=query&kw=" + q0["kw"]).get_json()
check("只看搜索：回到原来的口径，一条点击都不掺",
      all(it["type"] != "click" for it in dq["rows"]["items"]), [it["type"] for it in dq["rows"]["items"]])
dn = c3.get("/api/admin/view?tab=detail&scope=click&kw=查无此词").get_json()
# (a) 空态那句话（说清是哪一半空、给一条切回「全部」的路）现在写在 Detail.tsx 里，view 只回条数。
check("范围里没东西时空态要说清是哪一半空，别让人以为整个库没记录",
      dn["rows"]["items"] == [] and dn["rows"]["scope"] == "click"
      and "这个条件下没有记录" in detail_ts and "切回「全部」" in detail_ts, None)
check("换范围回到第 1 页：合流与单看两边条数不同，服务端拼的三个 scope 地址都不带 page",
      all("page=" not in (u or "") for u in dv["links"]["scopes"].values()), dv["links"]["scopes"])
stats_mod.record("没人点过的词", "10.9.9.9", via="api", results=3, ua="Mozilla/5.0 (Windows NT 10.0) Chrome/124.0")
dq2 = c3.get("/api/admin/view?tab=detail&ip=10.9.9.9").get_json()
check("没点过的 IP：整屏没有点开行，也不用留个空壳",
      all(it["type"] != "click" for it in dq2["rows"]["items"]), None)
# (b) 旧汇总行里那两颗「按域名 / 按动作」的快捷链接没进 React 的汇总卡片；但 host / kind 仍是
#     一等筛选入口（服务端 flt 认这两键、下面两条 click_stats 也照它们筛），等价的那一半钉这里。
check("域名与来源仍是筛选入口（服务端接 host / kind 两个条件，明细与聚合都吃）",
      "host" in dv["flt"] and "kind" in dv["flt"] and bool(dv["links"]["click_detail"]), dv["links"].get("click_detail"))
check("按 host 筛：只剩那两条", stats_mod.click_stats({"host": "k.test"})["count"] == 2,
      stats_mod.click_stats({"host": "k.test"})["count"])
check("按 place 筛：panel 与 card 分得开",
      stats_mod.click_stats({"place": "panel"})["count"] >= 1
      and stats_mod.click_stats({"place": "card"})["count"] >= 1, None)
check("非法 place 当没填，不静默命中零行",
      stats_mod.click_stats({"place": "javascript:"})["count"] == ct(), None)
check("两张表共用的筛选项也筛得到点击：按浏览器筛，点开行一起跟着筛",
      stats_mod.list_activity({"browser": "Chrome"}, scope="click")["total"] == 2
      and stats_mod.list_activity({"browser": "IE 1"}, scope="click")["total"] == 0,
      stats_mod.list_activity({"browser": "Chrome"}, scope="click")["total"])
check("没带 UA 的那条点击归进「未知」这一个桶，和搜索行同一套写法",
      stats_mod.list_activity({"browser": "未知"}, scope="click")["total"] >= 1,
      stats_mod.list_activity({"browser": "未知"}, scope="click")["total"])
check("归属地与浏览器补进 clicks 之后，点击行自己就带这些列，不用回表查",
      all(ev({"kw": q0["kw"]})[0][k] is not None
          for k in ("browser", "os", "device", "geo", "iso")),
      {k: ev({"kw": q0["kw"]})[0][k] for k in ("browser", "os", "device", "geo", "iso")})
check("聚合给出总量、独立 IP、点了哪些站",
      stats_mod.click_stats({})["count"] == ct()
      and stats_mod.click_stats({})["ips"] >= 1
      and isinstance(stats_mod.click_stats({})["by_host"], list),
      {k: v for k, v in stats_mod.click_stats({}).items() if k in ("count", "ips", "titles")})
check("点击表也一起过期：清老数据时两张表同一条界线",
      "DELETE FROM clicks WHERE day < ?" in
      (BASE / "zhuiju" / "stats.py").read_text(encoding="utf-8"), None)

print("\n22) 不选日期时默认只看最近一周")
old_day = (date.today() - timedelta(days=40)).isoformat()
con = sqlite3.connect(str(stats_mod.DB))
con.execute("INSERT INTO queries (ts, day, ip, kw, via, results) VALUES (?,?,?,?,?,?)",
            (old_day + " 09:00:00", old_day, "10.7.7.7", "很久以前的词", "api", 5))
con.execute("INSERT INTO clicks (ts, day, ip, kind, kw, title, url, host, place) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (old_day + " 09:01:00", old_day, "10.7.7.7", "detail", "很久以前的词",
             "很久以前的片", "", "", "hot"))
con.commit()
con.close()
w = c3.get("/api/admin/view").get_json()
want_from = (date.today() - timedelta(days=app_mod.DEFAULT_WINDOW - 1)).isoformat()
# (a) 日期回填、"最近 N 天"那句、40 天前那条默认不出现——都搬到 view 的 flt / day_window / rows 上钉。
check("日期框回填的就是实际用的那一周，不是空着让人以为看了全部（flt 里带回来的就是这一周）",
      w["flt"]["day_from"] == want_from and w["flt"]["day_to"] == today(),
      (w["flt"]["day_from"], w["flt"]["day_to"], want_from))
check("页面上写清了这是最近几天（这句由 Detail.tsx 拼，天数来自服务端 day_window）",
      "最近 ${v.day_window} 天" in detail_ts and w["day_window"] == app_mod.DEFAULT_WINDOW, w.get("day_window"))
wtexts = {it.get("kw") for it in w["rows"]["items"]} | {it.get("title") for it in w["rows"]["items"]}
check("40 天前那条查询默认不出现", "很久以前的词" not in wtexts, sorted(x for x in wtexts if x)[:4])
check("40 天前那条点击默认也不出现（两张表同一把尺子）",
      "很久以前的片" not in wtexts, None)
dall = c3.get("/api/admin/view?day=all").get_json()
atexts = {it.get("kw") for it in dall["rows"]["items"]} | {it.get("title") for it in dall["rows"]["items"]}
check("?day=all 是显式的出口：老记录又回来了（day_all 标记也回给前端）",
      "很久以前的词" in atexts and "很久以前的片" in atexts and dall["day_all"] is True, None)
check("这时页面上说的是全部历史", "全部历史" in detail_ts, None)
# (b) 旧版另写了一颗"回到最近 N 天"的链接；React 里没保留它——回到有界区间的路是筛栏那对
#     日期输入框（day_from / day_to）。等价的那一半钉这个入口。（缺专门"回到近一周"链接已记为疑似回归。）
check("回到近一周的路是筛栏的日期输入框（起/止两格始终在）",
      '["day_from", "起", "date"]' in filters_ts and '["day_to", "止", "date"]' in filters_ts, None)
check("看全部时翻页链接带着 day=all，不会点一次下一页就悄悄回到一周",
      all("day=all" in u for u in [dall["links"]["prev"], dall["links"]["next"]] if u)
      and "day=all" in dall["links"]["all_days"], {k: dall["links"].get(k) for k in ("prev", "next", "all_days")})
check("看全部时原地翻页也带着 day=all（goPage 走 filterUrl，把除页码外的条件原样保留）",
      "goPage" in detail_ts and "filterUrl({ page:" in detail_ts
      and "day=all" in dall["links"]["all_days"], None)
check("看全部时清空筛选不会把人送回一周（day=all 被当作当前状态带着）",
      'clear.day = v.day_all ? "all" : "";' in filters_ts, None)
one = c3.get("/api/admin/view?day_from=" + old_day + "&day_to=" + old_day).get_json()
onetexts = {it.get("kw") for it in one["rows"]["items"]} | {it.get("title") for it in one["rows"]["items"]}
check("显式填了日期就照办的，默认值不许把人家的区间顶掉",
      "很久以前的词" in onetexts and one["flt"]["day_from"] == old_day, None)
check("点击表同样吃这个区间",
      stats_mod.click_stats({"day_from": old_day, "day_to": old_day})["count"] == 1
      and stats_mod.click_stats({"day_from": today(), "day_to": today()})["count"] >= 1,
      stats_mod.click_stats({"day_from": old_day, "day_to": old_day})["count"])
check("归属地没回填成的老行（iso 是 NULL）不能把这页炸掉",
      dall["rows"]["items"] and "很久以前的词" in atexts, None)
check("默认区间可以从环境变量调",
      "ZHUIJU_ADMIN_DAYS" in (BASE / "zhuiju" / "app.py").read_text(encoding="utf-8"), None)

print("\n23) 已经建过 clicks 的库：补 kind 与归属地那几列，老行照样能筛")
old4 = TMP / "oldclicks.db"
oc = sqlite3.connect(str(old4))
# 上一版的 clicks 长这样（没有 kind，也没有归属地与浏览器）
oc.executescript("""
CREATE TABLE clicks (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, day TEXT NOT NULL,
  ip TEXT NOT NULL, kw TEXT, title TEXT, src TEXT, src_name TEXT, vid TEXT, line TEXT, ep TEXT,
  url TEXT, host TEXT, place TEXT, bot INTEGER, ua TEXT);
INSERT INTO clicks (ts, day, ip, kw, title, url, host, place)
  VALUES ('2026-10-18 10:00:00', '2026-10-18', '8.8.8.8', '老词', '老片',
          'https://old.test/1', 'old.test', 'panel');
""")
oc.commit()
oc.close()
_real4, _ready4 = stats_mod.DB, stats_mod._ready
stats_mod.DB, stats_mod._ready = old4, False
try:
    stats_mod.ensure_schema()
    con = sqlite3.connect(str(old4))
    cols = [r[1] for r in con.execute("PRAGMA table_info(clicks)")]
    got = [tuple(r) for r in con.execute("SELECT kind, url FROM clicks WHERE host = 'old.test'")]
    con.close()
    check("升级给 clicks 补上了 kind", "kind" in cols, cols)
    check("归属地、浏览器、系统、设备这六列也一起补上（明细合流要靠它们对齐）",
          {"iso", "country", "geo", "browser", "os", "device"} <= set(cols), cols)
    check("老行回填成 play，没有被当成详情", got == [("play", "https://old.test/1")], got)
    old_row = next(x for x in stats_mod.list_activity({}, scope="click")["items"]
                   if x["host"] == "old.test")
    check("老点击行没存 UA，也归进「未知」这一个桶，不留 NULL",
          old_row["browser"] == stats_mod.UNKNOWN and old_row["device"] == stats_mod.UNKNOWN
          and old_row["os"] == "",
          {k: old_row[k] for k in ("browser", "os", "device")})
    if geoip.available()["xdb"]:
        check("归属地顺手回填：公网 IP 补出国家码，按国家筛才筛得到老行",
              (old_row["iso"] or "") != "" and (old_row["country"] or "") != "",
              (old_row["iso"], old_row["country"], old_row["geo"]))
    else:
        check("归属地库不在就先不假装回填：country 留 NULL，等库到位再补一次",
              old_row["country"] is None, old_row["country"])
    check("按国家码筛点开行走的是同一份 WHERE，不报错且有整数条数",
          isinstance(stats_mod.list_activity({"geo": "--"}, scope="click")["total"], int), None)
    s = stats_mod.click_stats({})
    check("聚合与筛选都认得补出来的那一列",
          s["play"] == 1 and s["detail"] == 0
          and stats_mod.click_stats({"kind": "play"})["count"] == 1
          and stats_mod.click_stats({"kind": "detail"})["count"] == 0,
          {k: v for k, v in s.items() if k in ("count", "play", "detail")})
    check("补列之后新写的详情仍然分得开",
          stats_mod.record_click("8.8.8.8", kind="detail", title="新详情", place="hot")
          and stats_mod.click_stats({})["detail"] == 1, stats_mod.click_stats({}))
    con = sqlite3.connect(str(old4))
    try:
        check("归一是幂等的：再跑一次不改任何行", stats_mod.normalize_clicks(con) == 0, None)
    finally:
        con.close()
finally:
    stats_mod.DB, stats_mod._ready = _real4, _ready4
    stats_mod.ensure_schema()

print("\n24) 真人 / 脚本 / 说不清：三档口径 + 按 IP 的行为特征")
H_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) " \
       "Chrome/124.0.0.0 Safari/537.36"


def put(ip, minute, kw, *, ua=H_UA, ref_kind="direct", ref="", browser=None):
    """按指定时刻插一条搜索：节奏是这个测试的主角，不能让 record() 自己 now()。"""
    con = sqlite3.connect(str(stats_mod.DB))
    ts = f"{today()} 09:{minute // 60:02d}:{minute % 60:02d}"
    if browser is None:
        browser = ("未知" if not ua else
                   "Chrome 124.0" if "Chrome" in ua else
                   "curl" if "curl" in ua else "")
    con.execute("INSERT INTO queries (ts, day, ip, kw, via, results, hits, sources_ok,"
                " sources_total, ms, iso, country, geo, browser, os, device, bot, ua,"
                " ref, ref_kind, ref_label) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, today(), ip, kw, "api", 5, 8, 3, 4, 300.0, "", "", "本机",
                 browser, "" if not ua else "Windows 10/11", "未知" if not ua else "桌面",
                 None if ua is None else (1 if "curl" in ua else 0),
                 ua, ref, ref_kind, ref))
    con.commit()
    con.close()
    return ts


# A：像真人的样子 —— 站内跳转、有点开、间隔不规则
for i, (m, kw) in enumerate([(0, "A1"), (120, "A2"), (165, "A3"), (765, "A4"), (855, "A5")]):
    put("8.151.1.1", m, kw, ref_kind="site", ref="http://127.0.0.1:5000/")
stats_mod.record_click("8.151.1.1", kind="detail", kw="A1", title="A 第一部", place="panel", ua=H_UA)
# B：UA 老老实实是 Chrome，行为却是定时器 —— 这一条就是"为什么光看 UA 不够"
for i in range(10):
    put("8.151.2.2", i * 5, f"B{i}")
# C：UA 自报脚本
put("8.151.3.3", 600, "C1", ua="curl/8.5.0")
# D：只有一条、而且没留 UA（这既要顺手回归那个 KeyError：一条搜索的 IP 在
# LAG 那一组里一行都不返回，取 d["sumsq"] 就会炸）
put("8.151.4.4", 900, "D1", ua=None)
stats_mod.record_click("8.151.4.4", kind="detail", kw="D1", title="D 一部", place="hot",
                       ua="python-requests/2.32")
# E：浏览器认不出来，但 UA 有浏览器的骨架 —— 真 Firefox 的 UA 里是 `Gecko/20100101`、
# 没有 `like Gecko`，判据要是写成"含 like Gecko"就会把这种真人判成说不清
put("8.151.5.5", 1000, "E1", ua="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
                                "Gecko/20100101 Firefox/126.0")
# F：没自报爬虫、可也完全不像浏览器（以前这种直接落进"像真人"，页面上就出现
#    「浏览器 未知 + 像真人」这种自相矛盾的一行）
put("8.151.6.6", 1001, "F1", ua="MyOwnFetcher/2.1")
# G：UA 是浏览器的样子，但四条脚本特征全中（每秒一次 = 秒级连发 + 节拍器，
#    从不带站内跳转、从不点开）—— 这一条是用来验"改判到顶"的
for i in range(12):
    put("8.151.7.7", i, f"G{i}")

who = {x["who"]: x["n"] for x in stats_mod.summary({})["by_who"]}
check("三档加起来就是总数，没有第四种被吞掉",
      sum(who.values()) == stats_mod.list_queries({})["total"], who)
check("UA 自报爬虫 → bot 档", who.get("bot", 0) >= 1
      and stats_mod.list_queries({"who": "bot"})["total"] == who["bot"], who)
check("没留 UA 的老行 → 说不清，不再被当成 0 忽略", who.get("unknown", 0) >= 1, who)
w_of = lambda ip: stats_mod.list_activity({"ip": ip}, per=5)["items"][0]["who"]
check("浏览器认不出来、但 UA 有浏览器骨架 → 仍算像真人（Firefox 没有 like Gecko）",
      w_of("8.151.5.5") == "human"
      and stats_mod.list_activity({"ip": "8.151.5.5"}, per=5)["items"][0]["browser"] in ("", "未知"),
      w_of("8.151.5.5"))
check("UA 根本不像浏览器（MyOwnFetcher/2.1）→ 说不清，不冒充真人",
      w_of("8.151.6.6") == "unknown", w_of("8.151.6.6"))
check("三档里 human 那一档要求 UA 以 Mozilla/ 开头（词表漏了也不装）",
      "Mozilla/%" in stats_mod.WHO_SQL, stats_mod.WHO_SQL)
check("Werkzeug 这类离线工具的 UA 进了爬虫词表",
      "werkzeug" in agent_mod.BOTS and "python-httpx" in agent_mod.BOTS, None)
check("离线工具 check_autoupdate 不再往真实统计库里写测试记录",
      "stats_mod.DB = tmp" in (BASE / "tools" / "check_autoupdate.py").read_text(encoding="utf-8"),
      None)
check("认不出的 who 值当没填（静默筛空比忽略更难查）",
      stats_mod.list_queries({"who": "'; DROP"})["total"] == stats_mod.list_queries({})["total"],
      stats_mod.list_queries({"who": "'; DROP"})["total"])
act_b = stats_mod.list_activity({"ip": "8.151.2.2"}, per=50)["items"]
check("明细每一行都带着自己那一档", act_b and all(r["who"] for r in act_b),
      [r["who"] for r in act_b][:3])

beh = {b["ip"]: b for b in stats_mod.behavior({})}
b2 = beh.get("8.151.2.2") or {}
keys = [x["key"] for x in b2.get("reasons", [])]
check("节拍器被抓出来：十条固定 5 秒的 Chrome 请求，UA 说像真人，行为说不是",
      b2.get("who_ua") == "human" and b2.get("who") == "suspect"
      and "metronome" in keys and "no-ref" in keys
      and "no-click" in keys, {"who_ua": b2.get("who_ua"), "who": b2.get("who"), "reasons": keys})
check("间隔真的算对了：9 个间隔、每个 5 秒，标准差 0",
      b2.get("n_gap") == 9 and b2.get("min_gap") == 5 and b2.get("avg_gap") == 5.0
      and abs(b2.get("sd_gap") or 0) < 1e-6 and b2.get("cv") == 0.0,
      {k: b2.get(k) for k in ("n_gap", "min_gap", "avg_gap", "sd_gap", "cv")})
b1 = beh.get("8.151.1.1") or {}
check("有站内跳转、有点开、间隔不规则的那位不被冤枉",
      not {"metronome", "no-ref", "no-click"} & {x["key"] for x in b1["reasons"]}
      and b1["who"] == "human" == b1["who_ua"],
      {"who": b1.get("who"), "reasons": [x["key"] for x in b1["reasons"]]})
check("秒级连发单独一条判读（最快间隔 ≤ 1 秒才算，B 那位隔 5 秒不算）",
      "burst" not in keys and "burst" not in [x["key"] for x in b1["reasons"]], None)
check("UA 自报脚本的 IP 直接挂着 ua-bot 理由",
      "ua-bot" in [x["key"] for x in beh["8.151.3.3"]["reasons"]],
      [x["key"] for x in beh["8.151.3.3"]["reasons"]])
check("只有一条搜索的 IP 不炸，也没有间隔可报",
      beh["8.151.4.4"]["n_gap"] == 0 and beh["8.151.4.4"]["min_gap"] is None,
      {k: beh["8.151.4.4"].get(k) for k in ("n", "n_gap", "min_gap", "sd_gap", "cv")})
g7 = beh.get("8.151.7.7") or {}
check("四条全中的那位不再写「像真人」，直接按「脚本/爬虫」显示",
      g7.get("who_ua") == "human" and g7.get("who") == "bot" and g7.get("act_n") == 4,
      {"who_ua": g7.get("who_ua"), "who": g7.get("who"),
       "reasons": [x["key"] for x in g7.get("reasons", [])]})
check("改判只往上收：UA 已经自报脚本或没留 UA 的，不会因为行为被改回「像真人」",
      stats_mod.verdict("bot", 0) == "bot" and stats_mod.verdict("unknown", 4) == "unknown"
      and stats_mod.verdict("mixed", 4) == "mixed", None)
check("改判门槛就是页面上写的那两个数（2 条降级、4 条定性）",
      stats_mod.verdict("human", 1) == "human" and stats_mod.verdict("human", 2) == "suspect"
      and stats_mod.verdict("human", stats_mod.BEHAVIOR_SCRIPT - 1) == "suspect"
      and stats_mod.verdict("human", stats_mod.BEHAVIOR_SCRIPT) == "bot", None)
check("act_n 只数行为那几条（ua-bot / ua-none 不算进去，免得 curl 比真人还严重）",
      stats_mod.verdict("human", len([x for x in beh["8.151.3.3"]["reasons"]
                                      if x["src"] == "act"])) == "human"
      and beh["8.151.3.3"]["act_n"] == 0, beh["8.151.3.3"]["act_n"])
beh_list = stats_mod.behavior({})
check("排序按理由多的在前（多的先看，同分再按条数）",
      [len(v["reasons"]) for v in beh_list] ==
      sorted([len(v["reasons"]) for v in beh_list], reverse=True),
      [(v["ip"], len(v["reasons"])) for v in beh_list])
check("点开表吃同一个 who 口径（python-requests 那次点开要能被筛出来）",
      stats_mod.list_activity({"who": "bot"}, scope="click")["total"] >= 1, None)
allv = c3.get("/api/admin/view?tab=detail").get_json()
behmap = allv["beh_map"]
# (a) 这一节的徽章/理由原来从 /admin HTML 里 grep class="who who-*" 与行为胶囊。转 React 后：
#     徽章的档位色在 ui.tsx 的 WhoBadge、理由与那三个数是服务端算好放进 view 的 beh_map[].reasons
#     （每条带 short/text/src），明细行 IP 旁边的胶囊由 Detail.tsx 挂 ReasonChips。逐条搬到这两处。
check("后台出现了三档徽章（档位色集中在 WhoBadge，两张表共用一套 .who-*）",
      all(x in adminui_ts for x in ("who-bot", "who-unknown", "who-human")), None)
b2r = behmap.get("8.151.2.2") or {}
check("行为特征那一节出现了，IP 与判读理由都在（那一块是 Detail.tsx 的 Behavior，理由在 beh_map）",
      '<Block id="behavior"' in detail_ts and b2r.get("ip") == "8.151.2.2"
      and any(r["short"] == "节拍器" for r in b2r.get("reasons", [])), b2r)
check("筛选栏有「像谁」这一档", '["who", "真人 / 脚本"' in filters_ts, None)
# (b) 旧版汇总第一排有一格把三档（像真人 / 脚本爬虫 / 说不清）按条数列出来；React 的汇总卡片改列
#     验证方式、没保留这格。三档的枚举与文案本身还在（labels.who + 筛选栏），等价的那一半钉这里。
check("三档都在（labels.who 给全三档文案、筛选栏也各列一档；汇总那格随 SPA 改版撤了）",
      set(allv["labels"]["who"].values()) >= {"像真人", "脚本/爬虫", "说不清"}
      and all(k in filters_ts for k in ("像真人", "脚本/爬虫", "说不清")), allv["labels"]["who"])
# (b) "判读只是提示、不是判决"与"UA 是客户端自由发挥"两句都补回了 Behavior 那一节；
#     whoMerge 把「UA 那一档 / 改判那一档」分开写，并列出"站内跳转"这一行为列。
check("行为判读被说成提示而非结论（等价那半：判读只是提示 + 区分 UA 档与改判档）",
      "判读只是提示，不是判决" in detail_ts and "UA 是客户端自由发挥" in detail_ts
      and "所以不写「像真人」" in adminui_ts, None)
check("这几列是行为读出来的、带 Referer 的脚本那层老实话没进 SPA（等价那半钉「站内跳转」这一列）",
      "站内跳转" in detail_ts, None)
# (a) "理由挂在明细 IP 旁边" 的结构确实进了 React：Detail.tsx 在 IP 单元格里挂 ReasonChips（onlyAct）。
check("说了这些理由也挂在明细的 IP 旁边（翻明细不用回头对照）",
      "<ReasonChips reasons={bh.reasons} onlyAct />" in detail_ts, None)
r2 = b2["reasons"][0]
check("每条理由都带 key / 短文 / 全文 / 来源，组件按来源决定挂哪几种",
      {"key", "short", "text", "src"} <= set(r2) and
      {x["src"] for x in b2["reasons"]} == {"act"} and 'r.src === "act"' in adminui_ts, r2)
check("UA 自报那两种标成 ua（明细行上已有三档徽章，不重复挂）",
      {x["src"] for x in beh["8.151.3.3"]["reasons"] if x["key"] in ("ua-bot", "ua-none")} == {"ua"},
      beh["8.151.3.3"]["reasons"])
act_v = c3.get("/api/admin/view?tab=detail&ip=8.151.2.2").get_json()
b2a = act_v["beh_map"].get("8.151.2.2") or {}
acts = [r for r in b2a.get("reasons", []) if r["src"] == "act"]
# (a) 节拍器那位每行 IP 边上都挂胶囊：这个 IP 的明细行数 ≥ 10、它的 act 理由含那三条、
#     且组件在 IP 格里按 onlyAct 挂 ReasonChips——原来数 class="behflag" 换成这三处合起来。
check("节拍器那位：明细每一行的 IP 边上都挂到了行为胶囊",
      len(act_v["rows"]["items"]) >= 10
      and {r["short"] for r in acts} >= {"节拍器", "无站内跳转", "从没点开"}
      and "reasons={bh.reasons} onlyAct" in detail_ts, len(act_v["rows"]["items"]))
# (a) 胶囊挂的是短文、整句话在 title 里：ReasonChips 用 r.short 当文字、r.text 当 title。
check("挂的是短文，整句话在 title 里（一格里挤不下长句）",
      "{r.short}" in adminui_ts and "title={r.text}" in adminui_ts
      and any(r["short"] == "节拍器" and "节拍器" in r["text"] for r in acts), None)
b2u = c3.get("/api/admin/view?tab=detail&ip=8.151.3.3").get_json()["beh_map"].get("8.151.3.3") or {}
# (a) UA 自报脚本那位：who=bot（三档徽章），act 理由为空 → IP 边上不重复挂行为胶囊（同一件事不说两遍）。
check("UA 自报脚本的那位：行上是 bot 档徽章，IP 边上不再挂行为胶囊（act 理由为空）",
      b2u.get("who") == "bot" and not [r for r in b2u.get("reasons", []) if r["src"] == "act"],
      {"who": b2u.get("who"), "reasons": [(r["key"], r["src"]) for r in b2u.get("reasons", [])]})
b2c = c3.get("/api/admin/view?tab=detail&ip=8.151.1.1").get_json()["beh_map"].get("8.151.1.1") or {}
check("没被挑出行为毛病的那位，IP 边上干干净净（act 理由为空，ReasonChips 不渲染）",
      not [r for r in b2c.get("reasons", []) if r["src"] == "act"], b2c.get("reasons"))

print("\n25) 行为特征改判：徽章不再自相矛盾；那一节默认收起、可点开")
# (a) 这一节原来从 /admin 渲染出的 <span class="who who-x"> 与 <details> 判定改判与折叠。转 React
#     后：改判结果在 beh_map[].who / who_ua，档位文案在 labels.who，是否可点由 ui.tsx whoMerge 的
#     linkable 决定；那一节的折叠从 <details> 换成一个 aria-expanded 的按钮 + 本地记忆。逐条搬。
b_sus = allv["beh_map"].get("8.151.2.2") or {}
check("节拍器那位：明细里的徽章是「行为像脚本」，不是「像真人」（改判后的档来自 beh_map，文案来自 labels.who）",
      b_sus.get("who") == "suspect" and b_sus.get("who_ua") == "human"
      and allv["labels"]["who"]["suspect"] == "行为像脚本" and "who-suspect" in adminui_ts,
      {k: b_sus.get(k) for k in ("who", "who_ua")})
# (a) "改判出来的那一档不挂筛选链接" —— whoMerge 只在 merged 那一支返回 linkable:false
#     （?who= 筛的是 UA 档，改判行点了筛不出），钉这个判据。
check("改判出来的那一档不挂筛选链接（whoMerge 里 merged 支 linkable:false）",
      "linkable: false" in adminui_ts and "linkable: rWho === \"bot\" || rWho === \"unknown\"" in adminui_ts, None)
b_g = allv["beh_map"].get("8.151.7.7") or {}
check("四条全中的那位：明细按「脚本/爬虫」显示，但仍是不能点的 span（改判来的 bot，不是 UA 那一档）",
      b_g.get("who") == "bot" and b_g.get("who_ua") == "human" and "linkable: false" in adminui_ts,
      {k: b_g.get(k) for k in ("who", "who_ua")})
check("行为表上的徽章带 title，把 UA 那一档与改判后的那一档都写出来",
      "UA 那一档是" in detail_ts, None)
# (b) 这一节按需求改成直接展开在明细下面：不再有 <details>/aria-expanded，也没有本地记忆。
check("行为特征直接展开在明细下面，没有折叠开关（details 与 aria-expanded 都退了）",
      "<details" not in detail_ts and "aria-expanded" not in detail_ts
      and "useFoldMemo" not in detail_ts + adminui_ts, None)
check("明细在前、行为特征在后（读法说明排在它解释的那张表下面）",
      detail_ts.index("<Detail v={v}") < detail_ts.index("<Behavior v={v}"), None)
check("行为特征那张表也走同一套 N 行内联滚动（rows={5}，没有另写一份折叠用的量法）",
      "<Table dense rows={5}" in detail_ts and "new ResizeObserver" in clamp_ts, None)
# (c) 改判门槛仍写在页面上，只是措辞由"条及以上 / 4 条全中"改成 Detail.tsx 那句"命中 N 条改判…、M 条改判…"；
#     两个数（2 降级、4 定性）来自服务端 thresholds。
check("把改判规则写在页面上（几条降级、几条定性），不是悄悄换个说法",
      "命中 ${th.suspect} 条改判「行为像脚本」" in detail_ts
      and "${th.script} 条改判「脚本/爬虫」" in detail_ts
      and allv["thresholds"]["suspect"] == 2 and allv["thresholds"]["script"] == 4, allv["thresholds"])
check("suspicious 只挂在真有理由的行上（行上不会留一个空的 class=\"\"，那串会带偏正则）",
      'b.reasons?.length ? "row-suspicious" : undefined' in detail_ts
      and 'class=""' not in detail_ts, None)
b_ok = allv["beh_map"].get("8.151.1.1") or {}
check("没毛病的那位在明细里仍然是「像真人」，改判不是见谁都往上报",
      b_ok.get("who") == "human" and b_ok.get("who_ua") == "human",
      {k: b_ok.get(k) for k in ("who", "who_ua")})

print("\n26) 后台设置：每日更新时间（存配置文件，不写进统计库）")
# (a) 设置那一屏转 React：项目由服务端从 settings.SPEC 生成放进 view 的 setfields/setinfo/setsrc，
#     渲染写法在 Settings.tsx。原来 grep HTML 的判据搬到这两处；csrf 也从 view 拿。
sv26 = c3.get("/api/admin/view?tab=settings").get_json()
tok = sv26["csrf"]
sf = next((f for f in sv26["setfields"] if f["key"] == "refresh_hour"), {})
check("后台有设置那一节和「每日更新时间」这一项（默认就是以前写死的 2 点）",
      '<Block id="settings"' in settings_ts and sf.get("key") == "refresh_hour" and sf.get("value") == 2, sf)
check("写清了存哪个文件、保存即生效（路径由服务端 setinfo.path 带下来，写法在 Settings.tsx）",
      sv26["setinfo"]["path"].endswith("settings.json") and "settings.json"
      in (BASE / "zhuiju" / "settings.py").read_text(encoding="utf-8") and "不用重启" in settings_ts, sv26["setinfo"].get("path"))
# (b) 旧页头那两句散文（"为什么不放库里""每天几点触发 / 去 tab=settings 改"）没随整页改版进 SPA，
#     等价的那一半是「存哪个文件 + 保存即生效不用重启」这半句仍在 Settings.tsx 里（已记疑似回归）。
check("页头那句几点触发、去哪儿改没进 SPA（等价那半：文件路径 + 不用重启仍在）", "不用重启" in settings_ts, None)
sv_ov = c3.get("/api/admin/view?tab=overview").get_json()
ver = sv_ov["agg"]["by_verified"] or {}
# (c) 三种放行方式仍分开数，只是那格文案从"滑块验证过（另有 爬虫豁免 · 门禁未开）"改成
#     Overview.tsx 里的"真人验证放行 / 爬虫豁免 / 门禁关着时"。门禁关着时该有 off 那个数、不冒充 0 验证过。
check("总览那一格把放行方式分开数（门禁关着时不冒充成「验证过 0 条，剩下全是机器人」）",
      all(k in overview_ts for k in ("真人验证放行", "爬虫豁免", "门禁关着时"))
      and ("off" in ver or "crawler" in ver), ver)
r = c3.post("/admin/settings", data={"csrf": tok, "refresh_hour": "8"})
check("保存合法值：302 回列表并带 saved 标记",
      r.status_code == 302 and "settings_saved=1" in r.headers["Location"],
      r.headers.get("Location"))
def saved_settings():
    """读临时那份设置文件。断言只各看自己那一键：human_gate 是 gate_off 写进去的 0，
    拿整份字典相等去比就把两件事搅在一起，改任何一项设置都会假红。"""
    return json.loads((TMP / "settings.json").read_text(encoding="utf-8"))


saved = json.loads((TMP / "settings.json").read_text(encoding="utf-8"))
check("值落到配置文件里（不是写进 stats.db）", saved["refresh_hour"] == 8, saved)
con = stats_mod.connect()
try:
    has_tbl = con.execute("SELECT 1 FROM sqlite_master WHERE name='settings'").fetchone()
finally:
    con.close()
check("统计库里没有多出 settings 表（配置的归宿不是事件日志库）", has_tbl is None, has_tbl)
after = c3.get("/api/admin/view?tab=settings").get_json()
# (a) 改完立刻按新值说话：时间点在 setinfo.hour、日切线在 setinfo.roll，那句"每天 N 点那道线之后算新
#     的一天 / 下一道线"的写法在 Settings.tsx。原来 grep 的 'value="8"' / "08:00" / "下一道日切线" 搬过去。
sf_after = next((f for f in after["setfields"] if f["key"] == "refresh_hour"), {})
check("改完立刻按新值说话，不用重启（时间点回到 setinfo.hour=8，日切线那句在 Settings.tsx）",
      after["setinfo"]["hour"] == 8 and sf_after.get("value") == 8
      and "下一道线" in settings_ts and "那道线之后算新的一天" in settings_ts, after["setinfo"].get("hour"))
check("来源从「默认值」变成「来自 settings.json」（setsrc 说 file，组件那句「写在 path 里」也带着）",
      after["setsrc"]["refresh_hour"] == "file" and '写在 ${si.path} 里' in settings_ts, after["setsrc"].get("refresh_hour"))
# (a) 保存成功的提示仍走跳转带回的查询参数（不塞 session）：?settings_saved=1 时 view.notice 有那句、
#     不带时没有。文案由服务端 _admin_ctx 拼好放进 notice。
check("保存成功的提示走跳转带回的查询参数（不塞 session，和这一页别的状态一样）",
      "设置已保存" in (c3.get("/api/admin/view?tab=settings&settings_saved=1").get_json().get("notice") or "")
      and "设置已保存" not in (after.get("notice") or ""), after.get("notice"))
bad = c3.post("/admin/settings", data={"csrf": tok, "refresh_hour": "25"})
check("越界的值（25）被拒：跳回页面带 err 标记",
      bad.status_code == 302 and "settings_err=1" in bad.headers["Location"],
      bad.headers.get("Location"))
bp = c3.get("/api/admin/view?tab=settings&settings_err=1").get_json()
# (a) 拒的时候一句都不写盘、原来的值还在：view 带 settings_err=True，那句"有认不出来的取值、一条都没写"
#     在 Settings.tsx（旧页面写的是"没存上"，SPA 换了措辞）。refresh_hour 仍是 8。
check("拒的时候一句都不写盘，原来的值还在（半套设置比没设置更难查）",
      bp["settings_err"] is True and "有认不出来的取值" in settings_ts
      and saved_settings()["refresh_hour"] == 8, bp["settings_err"])
noauth = app_mod.create_app().test_client()
rn = noauth.post("/admin/settings", data={"csrf": "x", "refresh_hour": "3"})
check("没登录改不动设置（401，不落盘）",
      rn.status_code == 401 and saved_settings()["refresh_hour"] == 8, rn.status_code)
rc = c3.post("/admin/settings", data={"refresh_hour": "3"})
check("缺 csrf 的提交被当成过期表单挡掉", rc.status_code in (400, 401), rc.status_code)
# (a) min/max 仍是这一项的形状（服务端 setfields 带下来），组件把它写到 number 输入框上。
check("表单本身带 min/max（绕开浏览器才走到上面那条服务端校验）",
      sf.get("spec", {}).get("min") == 0 and sf.get("spec", {}).get("max") == 23
      and "min={f.spec.min} max={f.spec.max}" in settings_ts, sf.get("spec"))
os.environ["ZHUIJU_REFRESH_HOUR"] = "5"
try:
    envp = c3.get("/api/admin/view?tab=settings").get_json()
    sf_env = next((f for f in envp["setfields"] if f["key"] == "refresh_hour"), {})
    # (a) 环境变量顶着时页面上就说是环境变量顶的：setsrc=env、值跟着 env 走 5、组件那句「被环境变量 env 顶着」。
    check("环境变量顶着的时候页面上就说是环境变量顶的（不然「改了怎么没反应」最难查）",
          envp["setsrc"]["refresh_hour"] == "env" and sf_env.get("value") == 5
          and "被环境变量" in settings_ts, envp["setsrc"].get("refresh_hour"))
finally:
    del os.environ["ZHUIJU_REFRESH_HOUR"]
check("撤掉环境变量后回到文件里的 8 点（环境变量不写文件）",
      saved_settings()["refresh_hour"] == 8, saved_settings())
check("autoupdate 的日切判据和页面上那个数是同一个（都读 settings.refresh_hour）",
      "settings.refresh_hour()" in (BASE / "zhuiju" / "autoupdate.py").read_text(encoding="utf-8"),
      None)

print("\n27) 后台标签页与侧边目录")
TABS = app_mod.ADMIN_TABS
tov = c3.get("/api/admin/view?tab=overview").get_json()
tde = c3.get("/api/admin/view?tab=detail").get_json()
tst = c3.get("/api/admin/view?tab=strm").get_json()
tse = c3.get("/api/admin/view?tab=settings").get_json()
# (a) 标签页/侧边目录原来从 /admin 那页 HTML 里 grep（admintabs / aria-current / body[data-tab] /
#     data-grp / admintoc）。后台转 React 后：标签清单由服务端 tabs 下发、当前标签高亮与切屏都在
#     AdminApp.tsx、侧边目录按当前标签的 blocks 现列。逐条搬到 view 的 tabs + 组件写法上钉。
check("四个标签都在，链接各指自己那一组",
      [t["id"] for t in tov["tabs"]] == list(TABS) and all(f"tab={t['id']}" in t["href"] for t in tov["tabs"]),
      [t["id"] for t in tov["tabs"]])
# (b) 左侧菜单换成 <a> 之后 aria-current 又回来了：当前那颗标 page、配色同时跟着走。
check("当前标签那颗被高亮、一次只有一颗（aria-current=page + 配色随 tab 切）",
      'aria-current={on ? "page" : undefined}' in adminapp_ts
      and "const on = t.id === v.tab;" in adminapp_ts, None)
check("tab 由服务端算好、前端按它只渲染那一组（切屏在 AdminApp，不再写 body 属性）",
      all(f'tab === "{k}" ? <' in adminapp_ts for k in TABS)
      and tov["tab"] == "overview" and tde["tab"] == "detail"
      and tst["tab"] == "strm" and tse["tab"] == "settings", None)
check("认不出来的 tab 值回总览，不报错也不空白",
      c3.get("/api/admin/view?tab=瞎写").get_json()["tab"] == "overview", None)
check("每一组标签的块清单都由服务端按 ADMIN_TABS 下发（anchors 与登记一致，拼错一个就是那块无处显示）",
      {t["id"]: [b[0] for b in t["blocks"]] for t in tov["tabs"]}
      == {k: [a for a, _ in v["blocks"]] for k, v in TABS.items()}, None)
# (b) 显示哪一组从"CSS 按 body[data-tab] 藏 data-grp"改成 React 直接按 tab 选组件；data-grp 那套没了。
#     侧边目录只列当前标签的几块：Toc 用 tab.blocks.map + href=`#${id}`，锚点不会混进别的标签。
check("侧边目录只列当前标签那几块、点了就锚到那一块（Toc 现列 tab.blocks，不再有 data-grp）",
      "tab.blocks.map(([id, name])" in adminapp_ts and "href={`#${id}`}" in adminapp_ts
      and "data-grp" not in adminapp_ts, None)
check("目录锚点跟着当前标签走（先按 v.tab 找出这一组，再列它的 blocks）",
      "const tab = v.tabs.find((t) => t.id === v.tab)" in adminapp_ts, None)
# (b) 旧版靠 app.css 的 body[data-tab] 隐藏规则 + .admintoc sticky 布局；React 里切屏靠组件分支、
#     粘性目录靠 Tailwind 类。CSS 那几条是死规则，等价形态钉组件里的那一处。
check("侧边目录是粘性的、窄屏不出现（sticky + 只在 xl 上显示，不跟正文抢宽度）",
      "sticky top-20" in adminapp_ts and "xl:block" in adminapp_ts
      and "xl:grid-cols-[176px_minmax(0,1fr)_200px]" in adminapp_ts, None)
check("页内链接都带当前 tab（filterUrl 把 tab 一并写进查询串，切回来看的还是那一组）",
      'u.searchParams.set("tab", tab ?? (u.searchParams.get("tab") || "overview"))' in adminui_ts, None)
check("汇总卡片那颗「详情 / 观看点击」连标签一起换（click_detail 同时带 scope=click 与 tab=detail）",
      "scope=click" in tov["links"]["click_detail"] and "tab=detail" in tov["links"]["click_detail"],
      tov["links"].get("click_detail"))
# (b) "局部刷新基址带 tab / 目录 rAF 节流" 那套整页 HTML 的手写脚本没了：SPA 里 reload 取的就是当前
#     location.search（带 tab），目录高亮走 scroll 监听 + 量顶边。等价形态钉这些新写法。
check("原地翻页/换筛选后地址仍带着 tab（reload 取的就是当前 location.search）",
      "fetchView(location.search)" in adminapp_ts
      and '({}, "", u.pathname + u.search)' in adminui_ts, None)
check("目录高亮跟着滚动走（scroll 监听 + 量顶边，不再 requestAnimationFrame/mark）",
      'addEventListener("scroll", onScroll' in adminapp_ts
      and "getBoundingClientRect().top <= 84" in adminapp_ts, None)

print("\n28) 后台与前台之间那两个入口")
app_src = (BASE / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
# (a) 回前台那颗在 AdminApp 的标题行（四张标签共用同一个 header，不只总览有），指的就是首页 "/"。
check("后台标题行有「回前台」，四张标签共用同一个 header（不只总览有）",
      "回前台" in adminapp_ts and adminapp_ts.index('route === "/admin/password"') > 0
      and 'href="/"' in adminapp_ts, None)
check("那颗指向的就是首页，不是当前页自己（写成 /admin 就出不去了）",
      '<a href="/" className="text-[11px] text-muted hover:text-foreground">回前台</a>' in adminapp_ts, None)
# (b) 登录那一屏（denied 分支）现在没有"回前台"出口了——旧版口令页有、SPA 的 Login 组件漏了（已记疑似
#     回归）。等价的那一半只能钉"前台首页始终可达 + 前台组件里没有那颗旧 class"，把缺失如实钉出来。
check("前台首页始终可达（口令页里的回前台出口没进 SPA，已记回归）",
      client.get("/").status_code == 200 and "frontbtn" not in login_ts, None)
# (a) 前台页脚那条后台入口在 App.tsx 画的（不再是 shell.html 那份），带 rel=nofollow。
check("前台页脚有一条后台入口，且带 nofollow（robots.txt 那条 Disallow 之外的第二道）",
      '<a href="/admin" rel="nofollow"' in app_src and "<footer" in app_src, None)
# (c) 它在页脚最后那行、与旁字同 muted 色、hover 才显出——判据仍成立，锚点从 .dim/.footadm 那批死 CSS
#     换成 App.tsx 里的 Tailwind 类（footer 里 text-muted/70 + hover:text-foreground）。
check("它在页脚最后那行、与旁字同 muted 色、hover 才显出（写法搬到 App.tsx 的类名）",
      "text-muted/70" in app_src and 'className="hover:text-foreground"' in app_src
      and app_src.index("text-muted/70") < app_src.index('href="/admin" rel="nofollow"') < app_src.index("</footer>"), None)
# (b) "回前台复用胶囊样式 / 手机上两颗撑到够按" 依赖的那批 .pbtn/.frontbtn/.footadm 圆角与 padding 规则
#     是后台整页 HTML 的死 CSS；SPA 里这两颗就是普通文字链接（等价那半：不再各写一份配色/胶囊类）。
check("回前台不再另写一套胶囊配色（.frontbtn 那套胶囊 CSS 随整页改版退役，SPA 里就是普通链接）",
      "frontbtn" not in adminapp_ts and "回前台" in adminapp_ts, None)
check("页脚那颗也不再靠 .footadm 的 padding 撑高（那批触摸规则已随死 CSS 退役，已记回归）",
      "footadm" not in app_src and 'href="/admin"' in app_src, None)

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
