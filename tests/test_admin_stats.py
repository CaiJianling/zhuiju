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

print("\n13) 首次登录引导改口令")
# 用一个看起来就像自动生成的口令（12 位、小写字母+数字、不含 l/o）
GEN = "zx9k3mp7q2a4"
admin_mod.save({"password": GEN, "secret_key": cfg["secret_key"], "password_is_temp": True})
check("标记为临时口令时 is_temp_password 为真", admin_mod.is_temp_password())
c2 = app_mod.create_app().test_client()
r = c2.get("/admin")
check("没登录仍是 401", r.status_code == 401)
check("登录页提示这是自动生成的口令", "首次启动自动生成" in r.get_data(as_text=True))
tok2 = re.search(r'name="csrf" value="([0-9a-f]+)"', r.get_data(as_text=True)).group(1)
r = c2.post("/admin/login", data={"csrf": tok2, "password": GEN})
check("用临时口令登录成功", r.status_code == 302, r.status_code)
check("登录后先领着去改口令，而不是直接进统计页",
      "/admin/password" in r.headers["Location"] and "first=1" in r.headers["Location"],
      r.headers.get("Location"))
r = c2.get("/admin")
check("绕不开：硬访问 /admin 也会被引到改口令页",
      r.status_code == 302 and "/admin/password" in r.headers["Location"])
r = c2.get("/admin/password")
h = r.get_data(as_text=True)
check("改口令页 200", r.status_code == 200, r.status_code)
check("有当前口令与两次新口令输入",
      all(n in h for n in ('name="current"', 'name="password"', 'name="password2"')))
check("提示保存即生效不用重启", "不用重启服务" in h)
check("minlength 和后端下限一致", f'minlength="{admin_mod.MIN_LEN}"' in h)
tok3 = re.search(r'name="csrf" value="([0-9a-f]+)"', h).group(1)

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
# 提示是随跳转地址带过去的，要按浏览器实际会请求的那个地址来验
r = c2.get("/admin?set=1")
check("页面上有口令已更新的提示", "口令已更新" in r.get_data(as_text=True), r.status_code)
check("统计页上有改口令入口", "改口令" in r.get_data(as_text=True))

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
check("被环境变量锁住时页面上说明清楚", "ZHUIJU_ADMIN_PASSWORD" in r.get_data(as_text=True))
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
r = c3.get("/admin")
tok3 = re.search(r'name="csrf" value="([0-9a-f]+)"', r.get_data(as_text=True)).group(1)
r = c3.post("/admin/login", data={"csrf": tok3, "password": NEW})
r = c3.get("/admin")
dash = r.get_data(as_text=True)
check("登录后 200", r.status_code == 200, r.status_code)
check("有地图画布", 'class="worldmap"' in dash)
svg = re.search(r'<svg class="worldmap" viewBox="0 0 360 180"[^>]*>(.*?)</svg>', dash, re.S)
check("SVG 用 viewBox 0 0 360 180（投影一致才对得上）", bool(svg))
circles = re.findall(r'<circle cx="([\d.\-]+)" cy="([\d.\-]+)" r="([\d.]+)"', dash or "")
check("画出了 5 个公网点位（内网与本机不画）", len(circles) == 5, (len(circles), circles))
if svg:
    inside = all(0 <= float(cx) <= 360 and 0 <= float(cy) <= 180 for cx, cy, _ in circles)
    check("所有点位都落在 viewBox 内", inside, circles)
check("有归属地列", "<th>归属地</th>" in dash)
check("明细里出现了具体归属地", "中国 北京市" in dash or "中国 浙江省杭州市" in dash
      or "United States" in dash, re.findall(r"\?geo=([A-Z]{2})", dash)[:6])
check("国家行可点筛选", len(re.findall(r'\?geo=[A-Z]{2}', dash)) >= 5,
      re.findall(r'\?geo=([A-Z]{2})', dash))
check("内网单独成一行而不是编造国家", "内网 / 保留地址" in dash)
check("说明了内网不上图的原理", "没有地理归属" in dash)
check("底图轮廓被描色的只有存在记录的国家",
      'class="land-on"' in dash and dash.count('class="land-on"') == 1)
r = c3.get("/admin?geo=CN")
d2 = r.get_data(as_text=True)
check("按国家筛选后只看得到该国的明细",
      r.status_code == 200 and "223.5.5.5" in d2 and "8.8.8.8" not in d2.split("明细")[-1])
r = c3.get("/admin?geo=--")
d3 = r.get_data(as_text=True)
check("筛内网能看到内网行", r.status_code == 200
      and ("192.168.1.50" in d3 or "127.0.0.1" in d3))
check("只看内网时地图上一个点都没有", len(re.findall(r"<circle", d3)) == 0,
      len(re.findall(r"<circle", d3)))

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
finally:
    stats_mod.DB, stats_mod._ready = _real_db2, False
    stats_mod.MIGRATE_ERROR = ""
    stats_mod.ensure_schema()

print("\n19) 区块顺序与明细翻页控件")
dash = c3.get("/admin?per=2&page=2&kw=" + "繁花").get_data(as_text=True)
ids = [m for m in re.findall(r'<section class="asect" id="(\w+)"', dash)]
check("明细在归属地之前（归属地垫底）", ids[-1] == "geo" and "detail" in ids, ids)
check("归属地有独立 id 便于定位", ids == ["detail", "geo"], ids)
pager = dash[dash.index('class="pager"'):dash.index("</div>", dash.index('class="pager"'))]
check("翻页区有跳转表单", 'class="jumpform"' in pager)
check("跳转框是 number 且带 min/max",
      re.search(r'type="number" name="page" min="1" max="\d+"', pager) is not None,
      re.findall(r'min="1" max="(\d+)"', pager))
check("跳转表单带住了当前筛选", 'name="kw" value="繁花"' in pager,
      re.findall(r'name="(\w+)" value="([^"]*)"', pager))
check("翻页链接带 data-page（交给局部刷新）", pager.count("data-page") >= 1, pager.count("data-page"))
check("翻页链接带住筛选条件",
      all(("kw=" in u or "繁花" in u) for u in re.findall(r'href="([^"]+)"', pager)
          if "page=" in u), re.findall(r'href="([^"]+)"', pager))
check("页码输入框初值是当前页", re.search(r'name="page"[^>]*?value="(\d+)"', pager, re.S).group(1) == "2",
      re.search(r'value="(\d+)"', pager).group(1))
check("局部刷新脚本只在登录后出现", "DOMParser" in dash)
fresh = app_mod.create_app().test_client().get("/admin").get_data(as_text=True)
check("未登录页面里没有这套脚本", "DOMParser" not in fresh and "jumpform" not in fresh)
check("滚动定位留了避让空间", "#detail { scroll-margin-top" in
      (BASE / "zhuiju" / "static" / "app.css").read_text(encoding="utf-8"))
check("隐藏态瞬时滚动（否则 smooth 不执行，翻页后停在原地）",
      "document.hidden" in dash and "'auto'" in dash)

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
