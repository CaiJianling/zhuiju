# -*- coding: utf-8 -*-
"""网盘/磁力结果解析的离线测试：用自造的 HTML 片段，不依赖外部站点。

    python tests/test_cloudparse.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zhuiju.cloudsearch import parse_results  # noqa: E402

FAILS = []


def check(name, cond, got=None):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  got={got!r}"))
    if not cond:
        FAILS.append(name)


HTML = """
<html><body>
  <div class="nav">
    <a href="/index.html">首页</a>
    <a href="/search?q=%s">庆余年搜索</a>
    <a href="?cat=2">更多</a>
  </div>
  <ul class="result">
    <li><a href="/file-1.html">庆余年 第二季
        全36集 1080P
        中文字幕</a></li>
    <li><a href="/file-2.html">庆余年 第一季[1080P]</a></li>
    <li><a href="/subject/x.html">庆余年 第二季-1080P全集中文字幕-BT迅雷下载</a></li>
    <li><a href="/file-3.html"> unrelated 推荐影片 </a></li>
    <li><a href="javascript:void(0)">庆余年 点击播放</a></li>
    <li><a href="https://other.example.com/庆余年 广告位">庆余年 外站广告</a></li>
  </ul>
</body></html>
""" % "庆余年"

base = "https://example.org/search?q=%E5%BA%86%E4%BD%99%E5%B9%B4"
rows = parse_results(HTML, base, "庆余年")
titles = [r["title"] for r in rows]
links = [r["link"] for r in rows]

print(f"解析出 {len(rows)} 条：")
for r in rows:
    print("   ", r["title"], "->", r["link"])

check("结果条数符合预期(3 条真结果)", len(rows) == 3, len(rows))
check("多行标题压成一行", all("\n" not in t for t in titles), titles)
check("标题内多余空白被压缩",
      titles and "  " not in titles[0] and "庆余年 第二季 全36集" in titles[0], titles[:1])
check("导航『××搜索』被排除", not any(t.endswith("搜索") for t in titles), titles)
check("『更多』『首页』被排除", all(t not in ("更多", "首页") for t in titles), titles)
check("与关键词无关的推荐位被排除",
      not any("unrelated" in t for t in titles), titles)
check("javascript: 链接被排除", not any("javascript" in l.lower() for l in links), links)
check("相对链接补全为绝对地址",
      all(l.startswith("https://example.org/") for l in links if "subject" in l or "file" in l),
      links)
check("去重：同一链接只出现一次", len(links) == len(set(links)), links)
check("空关键词不返回任何结果", parse_results(HTML, base, "") == [], parse_results(HTML, base, ""))

print("\n没有关键词时的站点清单（cloudsearch.site_rows）")
from zhuiju import catalog as catalog_mod          # noqa: E402
from zhuiju import cloudsearch                     # noqa: E402

_real_get = cloudsearch.requests.get


def _boom(*a, **k):
    raise AssertionError("清单不该发网络请求")


cloudsearch.requests.get = _boom
try:
    rows = cloudsearch.site_rows()
finally:
    cloudsearch.requests.get = _real_get
check("这份清单一个请求都不发（把 requests.get 换成抛错也照常返回）", len(rows) > 0, len(rows))
check("只收网盘与磁力两类",
      all(r["category"] in cloudsearch.SOURCE_CATS for r in rows),
      {r["category"] for r in rows})
rec = [r["recommended"] for r in rows]
check("推荐指数高的排在前面（排序键与真去抓时一致）",
      rec == sorted(rec, reverse=True), rec[:10])
check("每行都有名字/分类/状态/首页地址",
      all(r["name"] and r["category"] and r["status"] and r["home"].startswith("http") for r in rows),
      rows[0])
check("can_query 的判据与 query_site 一致：kind 必须是 site_search",
      all((r["can_query"] == (r["kind"] == "site_search")) for r in rows),
      {(r["name"], r["kind"], r["can_query"]) for r in rows[:5]})
# 给某个站配一条已验证模板，它就该翻成"本站能直接搜出结果"，并把模板地址摊出来
victim = rows[0]["id"]
tpl = catalog_mod.templates()
_real_tpl = dict(tpl)
tpl[victim] = "https://tpl.test/s/{kw}"
try:
    one = [r for r in cloudsearch.site_rows() if r["id"] == victim][0]
    # 关键词进去应当被编码进模板 URL（和真去抓时同一个拼法）
    two = [r for r in cloudsearch.site_rows("庆余年") if r["id"] == victim][0]
finally:
    tpl.clear()
    tpl.update(_real_tpl)
check("有已验证模板的站翻成 can_query，并摊出模板地址",
      one["can_query"] is True and "{kw}" in one["search_url"], one)
check("带上关键词时模板里的 {kw} 被编码替换（与 query_site 的拼法一致）",
      two["search_url"].startswith("https://tpl.test/s/") and "%E5" in two["search_url"],
      two["search_url"])

print("\n/api/cloud 不带关键词时的契约")
from zhuiju.app import create_app                  # noqa: E402
from zhuiju import stats as stats_mod              # noqa: E402
cl = create_app().test_client()
n_before = stats_mod.summary({})["count"]
r = cl.get("/api/cloud")
d = r.get_json()
check("不带关键词回 200 的清单，不再是 400", r.status_code == 200 and d["mode"] == "sites",
      (r.status_code, d.get("mode")))
check("清单里给了站点数与「本站能直接搜」的个数",
      d["total_sites"] == len(d["sites"]) and d["can_query"] == sum(1 for s in d["sites"] if s["can_query"]),
      (d["total_sites"], d["can_query"]))
check("这一条路径不写统计（没真的搜过任何东西）",
      stats_mod.summary({})["count"] == n_before, (n_before, stats_mod.summary({})["count"]))
check("关键词太短仍然是 400，不被当成「没填」",
      cl.get("/api/cloud?kw=x").status_code == 400, cl.get("/api/cloud?kw=x").status_code)

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
