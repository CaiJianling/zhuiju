# -*- coding: utf-8 -*-
"""真人滑块门禁（zhuiju/human.py + app.py 的 _human_gate）。

    python tests/test_human.py

这一份是**唯一**开着门禁跑的离线测试：其他文件测 SEO、图片代理、合流列表……
都被 tests/gate_off.py 把门禁关掉，否则每个请求先被 423 挡住，红了也看不出自己错在哪。
不联网：接口返回什么都用打的桩，挑战与 cookie 全在这台机器上算。
"""
import json
import re
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from zhuiju import admin as admin_mod                              # noqa: E402
from zhuiju import app as app_mod                                  # noqa: E402
from zhuiju import hot as hot_mod                                  # noqa: E402
from zhuiju import human as human_mod                              # noqa: E402
from zhuiju import search as search_mod                            # noqa: E402
from zhuiju import settings as settings_mod                        # noqa: E402
from zhuiju import stats as stats_mod                              # noqa: E402

FAILS = []
TMP = Path(tempfile.mkdtemp(prefix="zhuiju_human_test_"))
admin_mod.CONFIG = TMP / "admin.json"
settings_mod.PATH = TMP / "settings.json"
stats_mod.DB = TMP / "stats.db"
stats_mod.DATA = TMP
stats_mod._ready = False
admin_mod.load()


def check(name, cond, got=None):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  got={got!r}"))
    if not cond:
        FAILS.append(name)


def fresh_ip(n=[0]):
    # 每条用例一个来源地址：失败限流与挑战都是按来源记的，共用一个会把上一条用例的
    # 失败次数算到下一条头上（现象就是"这条怎么突然说失败次数过多"）
    n[0] += 1
    return f"10.7.{n[0] // 250}.{n[0] % 250}"


print("1) 挑战：位置、容差、单次使用、过期、来源绑定")
c = human_mod.new_challenge(fresh_ip())
check("缺口位置在中间那一段（贴边就等于不用拖）",
      human_mod.TARGET_MIN <= c["target"] <= human_mod.TARGET_MAX, c)
check("带上容差与有效期，前端按这个画缺口",
      c["tol"] > 0 and c["ttl"] == human_mod.CHALLENGE_TTL, c)
ip = fresh_ip()
c = human_mod.new_challenge(ip)
check("拖偏了不给过", human_mod.solve(ip, c["id"], c["target"] + 0.3, 900, 40)[0] is False, None)
c = human_mod.new_challenge(ip)
check("拖准但太快（120ms）不像手拖的", human_mod.solve(ip, c["id"], c["target"], 120, 40)[0] is False, None)
c = human_mod.new_challenge(ip)
check("只有按下抬起、没有轨迹采样，判不过", human_mod.solve(ip, c["id"], c["target"], 900, 2)[0] is False, None)
c = human_mod.new_challenge(ip)
ok, _ = human_mod.solve(ip, c["id"], c["target"], 900, 40)
check("正解通过", ok, None)
check("同一条挑战不能提交两次",
      human_mod.solve(ip, c["id"], c["target"], 900, 40)[0] is False, None)
other = fresh_ip()
c = human_mod.new_challenge(ip)
check("挑战绑来源：换个人提交不算数",
      human_mod.solve(other, c["id"], c["target"], 900, 40)[0] is False, None)
c = human_mod.new_challenge(ip)
human_mod._ch[c["id"]]["exp"] = time.time() - 1          # 直接改库：等 2 分钟不现实
check("过期作废", human_mod.solve(ip, c["id"], c["target"], 900, 40)[0] is False, None)
c = human_mod.new_challenge(ip)
check("键盘那条路要够多次按键才算动过（6 次）",
      human_mod.solve(ip, c["id"], c["target"], 900, 0)[0] is False, None)
c = human_mod.new_challenge(ip)
check("方向键拖过去同样能过（无障碍必须留）",
      human_mod.solve(ip, c["id"], c["target"], 900, 0, 9)[0] is True, None)
bad_ip = fresh_ip()
for _ in range(12):
    human_mod.solve(bad_ip, "不存在的 id", 0.5, 900, 40)
blocked = human_mod.solve(bad_ip, "不存在的 id", 0.5, 900, 40)
check("同一来源失败太多次会先冷却（不然脚本可以无限试）",
      blocked[0] is False and "失败次数过多" in (blocked[1] or ""), blocked)

print("\n2) cookie：只认自己签给这台设备的、且没过期")
UA_WIN = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/124.0.0.0 Safari/537.36")
UA_WIN_NEW = UA_WIN.replace("Chrome/124.0.0.0", "Chrome/131.0.0.0")
UA_PHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1")
tok = human_mod.issue("10.1.2.3", UA_WIN)
check("签出来的一枚能验过", human_mod.token_ok(tok, "10.1.2.3", UA_WIN), tok[:14])
check("改一个字符就废",
      not human_mod.token_ok(tok[:-1] + ("0" if tok[-1] != "0" else "1"), "10.1.2.3", UA_WIN), None)
check("过期就废（时长读的是设置，默认 12 小时）",
      human_mod.token_ok(tok, "10.1.2.3", UA_WIN, now=time.time() + human_mod.max_age() + 10) is False
      and human_mod.max_age() == 12 * 3600, human_mod.max_age())
check("空的、乱写的、别人的签名都不算",
      not human_mod.token_ok(None, "10.1.2.3", UA_WIN)
      and not human_mod.token_ok("", "10.1.2.3", UA_WIN)
      and not human_mod.token_ok("123.abc", "10.1.2.3", UA_WIN)
      and not human_mod.token_ok("9999999999." + "0" * 16 + "." + "0" * 32, "10.1.2.3", UA_WIN), None)
# 这是这一节存在的理由：用户明确要求"cookie 拷到别的电脑上也能用"必须不成立
check("拷到别的 IP 上用不了（设备绑定）",
      human_mod.token_ok(tok, "10.9.9.9", UA_WIN) is False, None)
check("拷到别的设备类型上用不了（同一 IP、手机浏览器）",
      human_mod.token_ok(tok, "10.1.2.3", UA_PHONE) is False, None)
check("浏览器自己升级不该把人踢下线：同系统同设备类型、版本号变了照样过",
      human_mod.token_ok(tok, "10.1.2.3", UA_WIN_NEW) is True, None)
check("指纹算在签名里，改指纹不改签名过不了",
      human_mod.token_ok(tok.replace(tok.split(".")[1], "f" * 16), "10.1.2.3", UA_WIN) is False, None)
check("老格式（没有指纹那一段）一律不认，不会被当成「半个合法 cookie」",
      human_mod.token_ok("9999999999." + "0" * 32, "10.1.2.3", UA_WIN) is False, None)

print("\n3) 搜索引擎爬虫豁免：UA + 反查 DNS，两条都要")
real_lookup, real_cache = human_mod._lookup, dict(human_mod._rdns_cache)
try:
    human_mod._rdns_cache.clear()
    human_mod._lookup = lambda ip: "crawl-8-8-8-8.googlebot.com"
    check("UA 是 Googlebot 且反查落在 googlebot.com → 豁免",
          human_mod.is_search_crawler("8.8.8.8", "Mozilla/5.0 (compatible; Googlebot/2.1)"), None)
    human_mod._rdns_cache.clear()
    human_mod._lookup = lambda ip: "scrapy.example.com"
    check("自称 Googlebot 但反查不是官方域名 → 不豁免（这就是光看 UA 的漏洞）",
          human_mod.is_search_crawler("8.8.8.8", "Mozilla/5.0 (compatible; Googlebot/2.1)") is False, None)
    human_mod._rdns_cache.clear()
    check("反查彻底失败 → 不豁免",
          human_mod.is_search_crawler("8.8.8.8", "Mozilla/5.0 (compatible; Baiduspider/2.0)") is False, None)
    human_mod._rdns_cache.clear()
    human_mod._lookup = lambda ip: "crawl-13-68-1-1.search.msn.com"
    check("必应的官方段是 search.msn.com",
          human_mod.is_search_crawler("13.68.1.1", "Mozilla/5.0 (compatible; bingbot/2.0)"), None)
    human_mod._rdns_cache.clear()
    human_mod._lookup = lambda ip: "localhost"
    check("内网与回环一律不豁免：真爬虫不会从科室局域网里出来，"
          "这条也挡住了本机脚本挂个爬虫 UA 就绕过门禁",
          human_mod.is_search_crawler("127.0.0.1", "Mozilla/5.0 (compatible; Googlebot/2.1)") is False
          and human_mod.is_search_crawler("10.0.0.5", "Mozilla/5.0 (compatible; Baiduspider/2.0)") is False, None)
    human_mod._rdns_cache.clear()
    human_mod._lookup = lambda ip: "something.hrefscope.com"
    check("SEO 采集类 bot（不在名单里）没有豁免资格",
          human_mod.is_search_crawler("8.8.8.8", "Mozilla/5.0 (compatible; AhrefsBot/7.0)") is False, None)
finally:
    human_mod._lookup, human_mod._rdns_cache = real_lookup, real_cache

print("\n4) 门禁下的 HTTP：页面给验证页、接口给 423、静态与豁免路径照常")
# 让首页与搜索都不出网：这一节测的是"放不放行"，不是检索本身
hot_mod.get = lambda *a, **k: {"movie": [], "tv": [], "candidates": 0, "since": "", "cached": False}
search_mod.search = lambda kw, sources=None, page=1, budget=99: {
    "keyword": kw, "page": page, "results": [], "dropped_noise": 0, "status": [],
    "sources_ok": 0, "sources_total": 0, "hits": 0}
app = app_mod.create_app()
g1 = app.test_client()                                     # 没验证过的浏览器
g2 = app.test_client()                                     # 拖过滑块的浏览器
r = g1.get("/")
check("未验证访问首页：200，给的是验证页", r.status_code == 200 and "asect gatecard"
      in r.get_data(as_text=True), r.status_code)
# 判"是不是验证页"要用门禁页独有的 gatecard 那张卡片：滑块那句文案现在首页也有
# （cookie 过期时首页会就地弹同一块组件），拿文案判会两边都像验证页
body = r.get_data(as_text=True)
check("验证页里没有站点数据（搜索框、结果、统计都不给）",
      'id="kw"' not in body and 'class="res"' not in body and "查询次数" not in body, None)
check("验证页本身照样有 SEO：title / canonical / robots index / WebSite 结构化数据",
      "<title>追剧资源搜索" in body and 'rel="canonical"' in body
      and 'content="index,follow"' in body and '"@type":"WebSite"' in body, None)
check("接口未验证时 423 并带上 human 标记（前端据此弹滑块）",
      g1.get("/api/search?kw=%E5%BA%86%E4%BD%99%E5%B9%B4").status_code == 423
      and g1.get("/api/search?kw=%E5%BA%86%E4%BD%99%E5%B9%B4").get_json()["human"] == 1, None)
check("静态资源不挡（验证页自己要加载样式和 slider.js）",
      g1.get("/static/slider.js").status_code == 200
      and g1.get("/static/app.css").status_code == 200, None)
check("robots.txt 不挡（爬虫指令文件挡了就等于自断收录）", g1.get("/robots.txt").status_code == 200, None)
check("退出登录不挡：被门禁锁在外面的人也要能把自己登出去",
      g1.post("/admin/logout", data={"csrf": "x"}).status_code in (302, 200), None)
check("验证接口自己不挡自己（不然永远出不去）", g1.post("/api/human/challenge").status_code == 200, None)

ch = g1.post("/api/human/challenge").get_json()
wrong = g1.post("/api/human/verify", json={"id": ch["id"], "pct": 0.01, "ms": 900, "samples": 40})
check("拖偏：400 并给一句人话", wrong.status_code == 400 and wrong.get_json()["ok"] is False, wrong.get_json())
ch = g1.post("/api/human/challenge").get_json()
ok = g1.post("/api/human/verify", json={"id": ch["id"], "pct": ch["target"], "ms": 900, "samples": 40})
check("拖准：200 并签发 cookie", ok.status_code == 200 and ok.get_json()["ok"] is True, ok.get_json())
ck = ok.headers.get("Set-Cookie", "")
check("cookie 是 HttpOnly + SameSite=Lax + Path=/（JS 读不到，也不跨站带）",
      human_mod.COOKIE in ck and "HttpOnly" in ck and "SameSite=Lax" in ck and "Path=/" in ck, ck)
check("有效期跟着设置走（默认 12 小时）", f"Max-Age={12 * 3600}" in ck, ck)
r2 = g1.get("/")
b2 = r2.get_data(as_text=True)
check("验证过之后首页正常给内容", "asect gatecard" not in b2 and 'id="kw"' in b2,
      {"status": r2.status_code, "gatecard": "asect gatecard" in b2, "kw": 'id="kw"' in b2,
       "len": len(b2)})
r3 = g1.get("/api/search?kw=%E5%BA%86%E4%BD%99%E5%B9%B4")
check("验证过之后接口放行", r3.status_code == 200, r3.status_code)
g2.set_cookie(human_mod.COOKIE, "1234567890." + "0" * 16 + "." + "0" * 32)
check("伪造的 cookie 挡得住（签名不是本机算出来的）",
      g2.get("/api/search?kw=%E5%BA%86%E4%BD%99%E5%B9%B4").status_code == 423, None)
# 设备绑定的 HTTP 层验证：把刚签出来的那枚**原样**搬到另一个客户端用
stolen = ok.headers["Set-Cookie"].split(";")[0].split("=", 1)[1]
g6 = app.test_client()
g6.set_cookie(human_mod.COOKIE, stolen)
check("同一枚 cookie 换个设备类型（手机浏览器）就用不了",
      g6.get("/api/search?kw=%E5%BA%86%E4%BD%99%E5%B9%B4",
             headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
                      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"}
             ).status_code == 423, None)
check("同一枚 cookie 在同一台设备（同来源同系统）仍然有效——上面那条不是因为格式不对",
      g6.get("/api/search?kw=%E5%BA%86%E4%BD%99%E5%B9%B4").status_code == 200, None)
g3 = app.test_client()
g3.set_cookie(human_mod.COOKIE, human_mod.issue("127.0.0.1", "", now=time.time() - 99999))
check("过期的 cookie 也挡得住", g3.get("/api/search?kw=%E5%BA%86%E4%BD%99%E5%B9%B4").status_code == 423, None)
# 注意要换一个**干净**的 client：g1 这时候已经带着 cookie 了，用它测"后台先要真人"
# 等于已经验过了再看后台，看到的当然是口令页 —— 第一次就栽在这里
adm = app.test_client().get("/admin").get_data(as_text=True)
check("后台要**先**过真人验证再要口令：未验证时看到的是验证页，不是口令框",
      "asect gatecard" in adm and "输入口令" not in adm, None)

print("\n5) 统计里记的是「怎么被放行的」")
stats_mod._ready = False
stats_mod.ensure_schema()
cols = {r["name"] for r in stats_mod.connect().execute("PRAGMA table_info(queries)")}
check("queries 多了一列 verified（老库靠 ALTER 补，不在 CREATE 里改就算漏）", "verified" in cols, sorted(cols))


def verified_of(kw):
    """按关键词取最近一条的 verified。
    走裸 SQL 而不是 list_queries：明细那一长串列是给页面用的，
    verified 只在汇总里出一个数，没必要为它再动一次投影和表头。"""
    con = stats_mod.connect()
    try:
        row = con.execute("SELECT verified FROM queries WHERE kw = ? ORDER BY id DESC LIMIT 1",
                          (kw,)).fetchone()
    finally:
        con.close()
    return row[0] if row else None


g1.get("/api/search?kw=%E9%97%A8%E7%A6%81%E5%90%8E%E7%9A%84%E4%B8%80%E6%9D%A1")
check("带着有效 cookie 的那次查询记成 verified=1", verified_of("门禁后的一条") == 1,
      verified_of("门禁后的一条"))
g4 = app.test_client()
g4.get("/api/search?kw=%E6%9C%AA%E9%AA%8C%E8%AF%81")
check("被 423 挡掉的请求不进统计（没真的搜过任何东西，记了就是假数）",
      stats_mod.list_queries({"kw": "未验证"})["total"] == 0, None)
settings_mod.set_value("human_gate", 0)
settings_mod._cached.update(mtime=None, vals={})
g5 = app.test_client()
g5.get("/api/search?kw=%E9%97%A8%E7%A6%81%E5%85%B3%E7%9D%80")
check("门禁关着时的记录是 NULL，不是 0（0 的意思是「爬虫豁免」）",
      verified_of("门禁关着") is None, verified_of("门禁关着"))
agg = stats_mod.summary({})
check("汇总把三种放行方式各数一条",
      agg["by_verified"]["yes"] >= 1 and agg["by_verified"]["off"] >= 1
      and agg["by_verified"]["crawler"] == 0, agg["by_verified"])
check("三个数加起来就是当前条件下的总条数（每个数都能被现场复核）",
      sum(agg["by_verified"].values()) == stats_mod.list_queries({})["total"],
      (agg["by_verified"], stats_mod.list_queries({})["total"]))
check("老库升级：没有 verified 列时 ALTER 补上，不重建表、不动已有行",
      "verified" in str(stats_mod.HUMAN_COLUMNS)
      and "GEO_COLUMNS + AGENT_COLUMNS + HUMAN_COLUMNS" in
      (BASE / "zhuiju" / "stats.py").read_text(encoding="utf-8"), None)

print("\n6) 前端接线（三处对不齐就会「验过了还一直弹」）")
tpl = (BASE / "zhuiju" / "templates" / "index.html").read_text(encoding="utf-8")
gate = (BASE / "zhuiju" / "templates" / "human.html").read_text(encoding="utf-8")
slip = (BASE / "zhuiju" / "static" / "slider.js").read_text(encoding="utf-8")
appjs = (BASE / "zhuiju" / "static" / "app.js").read_text(encoding="utf-8")
css = (BASE / "zhuiju" / "static" / "app.css").read_text(encoding="utf-8")
check("首页有那块弹层，也加载了共用实现", 'id="slipwrap"' in tpl and "slider.js" in tpl, None)
check("slider.js 在 app.js 之前加载（app.js 收到 423 时要用它）",
      tpl.index("app.js") < tpl.index("slider.js"), None)
check("验证页与首页共用同一份 _slider.html（两处各写一份必然对不齐）",
      'include "_slider.html"' in tpl and 'include "_slider.html"' in gate, None)
check("收到 423 时只有一处出口：getJSON", "r.status === 423" in appjs and "needHuman(retry)" in appjs, None)
check("验证通过后重跑刚才那次搜索，不用重新输关键词",
      "onok: () =>" in appjs and "slipPending" in appjs and "() => run(kw, page)" in appjs, None)
check("失败后必须换一块新挑战（沿用作废的那条会永远过不去）",
      "window.setTimeout(ask, 700)" in slip and "ch.id" in slip, None)
check("键盘那条路给的是自动提交，不要求再按一次回车",
      "idle = window.setTimeout(() => { spent = performance.now() - down; down = 0; submit(); }, 600)"
      in slip, None)
# 用户报的"一直说太快了"：pointerup 里先把 t0 清零、submit 再拿 t0 算用时 → 永远 0ms。
# 现在改成"先记下 spent，再清 down"，提交时只读 spent
check("拖多久是**先记下来再清计时起点**的（旧写法每次都上报 0ms，永远被判太快）",
      "spent = performance.now() - down;   // 先记下时长，再把 down 清掉" in slip
      and "ms: Math.round(spent)" in slip
      # 注意不能直接判 "t0" not in slip：上面那段说明注释里就写着旧变量名 t0
      and "let t0" not in slip and "ms: t0" not in slip, None)
check("滑块宽度是现量的（窄屏 CSS 加宽之后写死的常量就会把缺口画偏）",
      "knob.offsetWidth" in slip and "const KW = 44;" not in slip, None)
check("缺口以目标位置为中心、按像素算，窗口变化还会重算",
      "ch.target * s + w / 2 - zone / 2" in slip and "addEventListener('resize', layout)" in slip, None)
check("--kw 只在轨道那一处定义（写在滑块上缺口就拿不到，窄屏正好错开一格）",
      "--kw: 44px" in css and ".slip-knob { --kw" not in css
      and "@media (max-width: 560px) {\n  body.gate .gatecard" in css
      and ".slip-track { --kw: 52px; height: 52px; }" in css, None)
check("手机上滑块禁用页面滚动（touch-action:none），否则拖滑块变成滚页面",
      "touch-action: none" in css, None)
# 用户看过截图后的意见是"这布局排版太丑了"：卡片用 margin:8vh 顶在上半屏、
# 下面整片空白，卡片外那段提示又跟着 .wrap 铺到 1680px，整页看着就是歪的
check("验证页由 main 把卡片压在视口正中（不再靠一个会随屏高乱飘的 margin-top）",
      "body.gate main {" in css and "place-items: center" in css
      and "margin: 8vh auto 0" not in css and "8vh" not in css, None)
check("所有说明都关在卡片里：卡片外不再甩段落",
      "atip" not in gate
      and gate.index('class="asect gatecard"') < gate.index('class="gatefoot"') < gate.index("</section>"),
      None)
check("cookie 那几段长说明默认收起（首屏只看到标题、一句引导和滑块）",
      '<details class="gate-more">' in gate and "匿名</b> cookie" in gate, None)
check("弹层的显隐只用 hidden 表达（全站那条 [hidden] 带 !important，压得住 display:grid）",
      'id="slipwrap" hidden' in tpl and "[hidden] { display: none !important; }" in css, None)
check("门禁关这一项在后台「设置」里（表单从 SPEC 生成，不是模板写死一格）",
      "for key, spec, val in setfields" in (BASE / "zhuiju" / "templates" / "admin.html").read_text(encoding="utf-8")
      and "human_gate" in settings_mod.SPEC and settings_mod.SPEC["human_gate"]["kind"] == "bool", None)
check("页面上写明了它挡得住什么、挡不住什么（不让把验证码当安全边界）",
      "挡不住" in (BASE / "zhuiju" / "templates" / "admin.html").read_text(encoding="utf-8")
      and "挡不住" in (BASE / "zhuiju" / "human.py").read_text(encoding="utf-8"), None)
check("豁免名单只放搜索引擎，不放 SEO 采集类 bot",
      "hrefscope" not in json.dumps(list(human_mod.CRAWLERS)) and len(human_mod.CRAWLERS) >= 6,
      list(human_mod.CRAWLERS))

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
