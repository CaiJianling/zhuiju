# -*- coding: utf-8 -*-
"""后台统计（SQLite）与口令登录的离线测试（不联网）。

    python tests/test_admin_stats.py

关键点：把 stats.DB 与 admin.CONFIG 都指到临时目录，绝不碰真实的
zhuiju/data/stats.db 和 admin.json —— 之前 check_autoupdate 写真实状态文件，
正在读的站点就把测试造的假状态显示到页头上了。
"""
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from zhuiju import admin as admin_mod      # noqa: E402
from zhuiju import stats as stats_mod      # noqa: E402

FAILS = []
TMP = Path(tempfile.mkdtemp(prefix="zhuiju_admin_test_"))

# 必须在 create_app 之前改：app.secret_key 建应用时就要读配置文件
admin_mod.CONFIG = TMP / "admin.json"
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
check("聚合：按天是时间正序", [d["day"] for d in agg["by_day"]] == sorted(d["day"] for d in agg["by_day"]))
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
# Jinja 里 dict.items 会被解析成字典的 items 方法而不是 "items" 键，
# 这个坑在 index.html 上已经踩过一次（seo.snapshot.items），模板里统一用下标
admin_tpl = (BASE / "zhuiju" / "templates" / "admin.html").read_text(encoding="utf-8")
check("admin 模板不用裸 .items 属性写法", ".items %}" not in admin_tpl and ".items " not in admin_tpl,
      re.findall(r"\{\{[^}]*\.items[^}]*\}\}|{%[^%]*\.items[^%]*%}", admin_tpl))
check("admin 模板改用下标取 items", "rows['items']" in admin_tpl)

from zhuiju import app as app_mod  # noqa: E402

app_mod.admin_mod.secret_key()          # 确保配置已生成，再建 app
client = app_mod.create_app().test_client()

r = client.get("/admin")
check("未登录返回 401 而不是 200", r.status_code == 401, r.status_code)
html = r.get_data(as_text=True)
check("给的是口令页", "输入口令" in html)
check("口令页里没有任何查询数据", "庆余年" not in html and "10.0.0.1" not in html)
check("口令页带 noindex", 'name="robots" content="noindex' in html)
check("表单里有 csrf 字段", 'name="csrf" value="' in html)

print("\n7) 登录流程")
tok = re.search(r'name="csrf" value="([0-9a-f]+)"', html).group(1)
r = client.post("/admin/login", data={"csrf": tok, "password": "cuo-de-mi-ma"})
check("错口令 401", r.status_code == 401, r.status_code)
check("错口令后提示剩余次数", "还可尝试" in r.get_data(as_text=True))
r = client.post("/admin/login", data={"csrf": "deadbeef", "password": "wo-ziji-de-mima"})
check("csrf 不对时拒掉（400）", r.status_code == 400, r.status_code)
r = client.post("/admin/login", data={"csrf": tok, "password": "wo-ziji-de-mima"},
                follow_redirects=False)
check("对口令后 302 跳回统计页", r.status_code == 302 and "/admin" in r.headers["Location"],
      r.headers.get("Location"))
check("Set-Cookie 是 HttpOnly + SameSite=Lax",
      "HttpOnly" in r.headers["Set-Cookie"] and "samesite=lax" in r.headers["Set-Cookie"].lower())
r = client.get("/admin")
check("登录后 200", r.status_code == 200, r.status_code)
html = r.get_data(as_text=True)
check("能看到关键词", "庆余年" in html and "流浪地球" in html)
check("能看到 IP", "10.0.0.1" in html and "10.0.0.2" in html)
expect_total = stats_mod.list_queries({})["total"]
shown = re.findall(r"共 (\d+) 条", html)
check("页面显示的总条数与库里一致", str(expect_total) in shown, (expect_total, shown))
check("有页码信息", "页 · 共" in html)

print("\n8) 后台页面的筛选与翻页真的接到了 SQL")
r = client.get("/admin?ip=10.0.0.1")
h = r.get_data(as_text=True)
check("按 IP 过滤后只看得到这个 IP 的行", "10.0.0.2" not in h.split("明细")[-1])
check("IP 填进输入框了", 'name="ip" value="10.0.0.1"' in h)
r = client.get("/admin?day_from=" + today() + "&day_to=" + today())
h = r.get_data(as_text=True)
check("按日期范围过滤生效", "繁花" in h and "庆余年" not in h.split("明细")[-1])
r = client.get("/admin?kw=" + "庆余年")
check("按关键词过滤生效", "流浪地球" not in r.get_data(as_text=True).split("明细")[-1])
r = client.get("/admin?per=2&page=2")
h = r.get_data(as_text=True)
check("翻页参数被接受", r.status_code == 200 and "第 2 /" in h, re.findall(r"第 \d+ / \d+ 页", h))
check("翻页链接保住了筛选条件",
      all(k in h for k in ("per=2", "page=")), re.findall(r'href="/admin\?[^"]*page=\d+[^"]*"', h)[:2])
r = client.get("/admin?ip=" + "1=1) OR 1=1 --")
check("页面上注入串不报错", r.status_code == 200)

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
r = client.get("/admin")
tok = re.search(r'name="csrf" value="([0-9a-f]+)"', r.get_data(as_text=True)).group(1)
r = client.post("/admin/logout", data={"csrf": tok}, follow_redirects=False)
check("退出后 302", r.status_code == 302, r.status_code)
check("退出后再进 /admin 又要口令了", client.get("/admin").status_code == 401)

print("\n12) robots 不进后台")
rb = client.get("/robots.txt").get_data(as_text=True)
check("robots 里 Disallow 了 /admin", "Disallow: /admin" in rb, rb)

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
