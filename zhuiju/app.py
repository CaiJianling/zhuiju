# -*- coding: utf-8 -*-
"""追剧资源搜索 — 本地 Flask 站点。

用法：
    python run.py            # 启动并自动打开浏览器
    python -m flask --app zhuiju.app run  # 等价方式
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import (Flask, g, jsonify, make_response, redirect, render_template,
                   request, send_file, session, url_for)
from markupsafe import escape as xml_escape

from . import admin as admin_mod
from . import autoupdate
from . import catalog as catalog_mod
from . import cloudsearch
from . import geoip
from . import hot as hot_mod
from . import human as human_mod
from . import imgproxy
from . import seo as seo_mod
from . import settings as settings_mod
from . import stats as stats_mod
from . import strm as strm_mod
from . import strmjob
from .search import by_id as source_by_id
from .search import detail as fetch_detail
from .search import detail_by_title, fetch_one, search
from .sources import load_sources

MIN_KW = 2        # 单字符关键词会引发一轮无意义的并发抓取，直接拒掉
MAX_KW = 60
# 观看点击是个公开接口，不设上限就等于邀请人拿脚本把统计库灌满。
# 一分钟内同一个 IP 超过这么多条就丢掉（仍然回 204，别让前端以为失败而重试）。
CLICK_WINDOW = 60
CLICK_MAX = 120
# ip -> (这一窗口的起始时刻, 已记条数)。开发服务器是多线程的，读写要上锁。
_click_rate: dict = {}
_click_lock = threading.Lock()
VIA_CN = {"api": "搜索", "seo": "落地页", "cloud": "网盘"}
CLICK_PLACE_CN = {"panel": "海报详情", "card": "卡片线路", "hot": "猜你想搜"}
CLICK_KIND_CN = {"play": "观看地址", "detail": "详情"}
# 明细列表看哪一半：合流是默认，另外两个是给"只想数搜索"的人的出口
SCOPE_CN = {"all": "全部", "query": "只看搜索", "click": "只看点开"}
# 后台分标签页。一整页 11 块太长了：进后台多数只想知道"今天有没有人用"，
# 翻明细、翻 STRM、改设置是完全不同的三件事，不该都挤在同一条滚动里。
# 分组的唯一口径就这一处：tab 校验、标签栏、侧边目录、模板上的 data-grp 都从它生成，
# 加一块内容时只改这里，不会出现"块归在总览、目录却写在明细"这种对不上的情况。
# 每个块 = (锚点 id, 目录里显示的名字)
ADMIN_TABS = {
    "overview": {"label": "总览", "blocks": [
        ("stat", "汇总卡片"), ("days", "按天"), ("top-kw", "热门关键词"),
        ("top-ip", "活跃 IP"), ("agents", "浏览器 / 设备"), ("refs", "来源页"),
        ("geo", "IP 归属地地图")]},
    "detail": {"label": "明细", "blocks": [
        ("behavior", "像脚本的行为特征"), ("detail", "明细")]},
    "strm": {"label": "Emby STRM", "blocks": [
        ("strm", "采集与状态"), ("strm-zips", "分卷包"), ("strm-src", "各源采集进度")]},
    "settings": {"label": "设置", "blocks": [("settings", "运行设置")]},
}


def admin_tab(raw) -> str:
    """tab 参数只认 ADMIN_TABS 里那几个键，认不出来回总览。

    和 scope / who 一样是"非法值不当没填处理"而不是"报错"：手改 URL 的人不该看到 500，
    而静默回总览最多是"咦怎么换了页"，比筛空或崩都好查。
    """
    return raw if raw in ADMIN_TABS else "overview"
DEFAULT_WINDOW = int(os.environ.get("ZHUIJU_ADMIN_DAYS", "7"))   # 后台不选日期时看最近几天
REF_KIND_CN = {"site": "站内上一页", "search": "搜索引擎", "out": "外部站点",
               "direct": "直接访问/无来源", "other": "无法解析"}


def refresh_info() -> dict:
    """读取自动更新的结果与进度，用于页头横幅。

    措辞要分清情况，别把"上次成功但已过周期"说成失败：
      running 正在跑（带进度） / fresh 本周期已成功 / stale 上次成功但到了新周期
      / failed 上次确有步骤失败 / never 从没跑过
    """
    try:
        s = json.loads(autoupdate.STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        s = {}
    prog = autoupdate.progress()
    # 页头那颗报的是"能被并发检索到的 / 配置里全部的"：站点把关键词搜索关了的那几个
    # （searchable=False，只喂猜你想搜）数进"检索源"里就是虚报，会让人以为搜一次打了 17 个站。
    # 状态文件是上一轮更新时写的，配置这轮加过源就跟不上号了（实测会写出 15/10 这种数），
    # 所以缺这个键时整对儿都当场按配置算，不用等明天那一轮更新才对上
    n_search = s.get("sources_searchable")
    if n_search is None:
        live = load_sources()
        n_search = sum(1 for x in live if x.enabled and x.searchable)
        src = f"{n_search}/{len(live)}"
    else:
        src = f"{n_search}/{s.get('sources_total', '?')}"

    if prog.get("running"):
        done, total = prog.get("done", 0), prog.get("total") or len(autoupdate.STEPS)
        cur = prog.get("step_label") or "准备中"
        return {"fresh": False, "state": "running", "progress": prog,
                "text": f"正在后台更新（第 {min(done + 1, total)}/{total} 步：{cur}）",
                "hint": f"已完成 {done}/{total} 步 · 当前显示的是上一次的数据，跑完刷新即可"}
    if not s:
        return {"fresh": False, "state": "never", "progress": prog,
                "text": "尚未自动更新过",
                "hint": "打开页面就会自动开始更新，" + autoupdate.retry_hint()}

    ok = bool(s.get("ok"))
    done_cycle = autoupdate._cycle_done(s)
    fresh_today = s.get("date") == autoupdate.logical_day().isoformat()
    if done_cycle and fresh_today:
        return {"fresh": True, "state": "fresh", "progress": prog,
                "text": f"数据 {str(s.get('finished_at', ''))[5:16]} 自动更新 · 检索源 {src}",
                "hint": f"上游目录版本 {s.get('upstream_updated_at', '未知')}"}
    if not ok:
        bad = "、".join(s.get("failed_steps") or []) or "未知步骤"
        left = autoupdate.next_retry_in(s)
        # 把"用的哪个解释器"带上：Linux/宝塔 上八成是解释器或依赖不对，
        # 光说"步骤失败"只能让人去翻日志猜
        cool = f"{left // 60 + 1} 分钟内不再自动重试，" if left else ""
        py = str(s.get("python") or autoupdate.python_bin())
        hint = (f"时间 {s.get('finished_at', '未知')} · {cool}{autoupdate.retry_hint()}；"
                f"详情看 logs 下最新的 refresh-*.log（解释器 {py}）")
        return {"fresh": False, "state": "failed", "progress": prog,
                "text": f"上次自动更新有步骤失败（{bad}）", "hint": hint}
    if autoupdate.is_partial(s):
        # 手动跑过 --skip-deep 的快版：数据确实新，但这一周期的全量更新还没做
        return {"fresh": False, "state": "partial", "progress": prog,
                "text": f"上次只跑了快版（{str(s.get('finished_at', ''))[5:16]}，"
                        f"跳过 {'、'.join(s.get('skipped_steps') or []) or '若干步骤'}）",
                "hint": "访问时会自动补跑完整一轮，" + autoupdate.retry_hint()}
    return {"fresh": False, "state": "stale", "progress": prog,
            "text": f"数据是 {s.get('date', '未知')} 更新的，已过当天周期",
            # 这句原来写死"凌晨 2 点后"：时间点现在是设置项，页面还在报一个可能的假数
            "hint": f"过了每天 {settings_mod.refresh_hour()} 点那道线之后访问会自动重来，"
                    + autoupdate.retry_hint()}


def _setinfo() -> dict:
    """后台「设置」那一节要显示的东西：当前生效值、是谁定的、下一道日切线、现在差不差。

    这几项一定要摆在页面上：访问触发的更新没有日历可看，一个人把时间改成 8 点、
    结果那天一整天没人访问，就会出现"设置明明对了怎么没更新"——那是最难查的一类问题。
    """
    hour = settings_mod.refresh_hour()
    now = datetime.now()
    roll = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if roll <= now:                       # 今天这道线已经过去了，那下一道是明天的
        roll += timedelta(days=1)
    return {"hour": hour, "spec": settings_mod.SPEC["refresh_hour"],
            "path": settings_mod.PATH.name,
            "source": settings_mod.source_of("refresh_hour"),
            "roll": roll.strftime("%m-%d %H:%M"),
            "logical_day": autoupdate.logical_day(now).isoformat(),
            "due": autoupdate.needs_update(now)}


def _strm_notice(args, st: dict) -> str:
    """后台「Emby STRM」那一节的操作结果提示，从跳转带回的查询参数拼一句人话。

    不写 session：这一页本来就用查询参数带筛选条件，多一个提示位就够了，
    犯不上为一个提示引入 flash。参数值都是我们自己在 redirect 里写死的，
    只有 strm_err 是用户输入拼出来的，所以模板里必须当文本渲染（不能 |safe）。
    """
    cfg = st["settings"]
    if args.get("strm_err"):
        return "没保存：" + str(args.get("strm_err"))[:160]
    if args.get("strm_set"):
        return (f"已保存：窗口 {cfg['window_days']} 天 · 每卷 {cfg['part_files']} 个文件 · "
                f"每请求间隔 {cfg['delay_ms']}ms · 每轮预算 {cfg['budget_seconds']}s。"
                "改了时间范围的话按一次「全量重建」，旧窗口采进来的才会从库里清掉")
    why = str(args.get("why") or "")[:120]
    if args.get("strm_run") == "1":
        return ("已拉起后台任务：" + why) if why else "已拉起一轮后台任务"
    if args.get("strm_run") == "0":
        return ("没启动：" + why) if why else "没启动"
    return ""


def _proxied_hot(h: dict) -> dict:
    """猜你想搜的海报改走本站代理，前端才能拿到被防盗链挡掉的图。"""
    from urllib.parse import quote

    def wrap(pic: str) -> str:
        return f"/img?url={quote(pic, safe='')}" if pic.startswith("http") else ""

    h = dict(h)
    for sec in ("movie", "tv"):
        rows = h.get(sec) or []
        imgproxy.register_all(rows)          # 先登记，/img 才肯代理
        h[sec] = [{**x, "pic": wrap(x.get("pic", ""))} for x in rows]
    return h


def _first_row(h: dict, per: int = 12) -> dict:
    """首屏每组只给一屏的量，其余由「上一页 / 下一页」整行切换。

    `*_total` 是缓存里的总条数：模板要拿它判断还有没有下一页，
    不能拿截过的 `rows` 长度判断（那样永远只剩一行、按钮永远禁用）。
    """
    h = dict(h)
    for sec in ("movie", "tv"):
        rows = h.get(sec) or []
        h[sec + "_total"] = len(rows)
        h[sec] = rows[:per]
    return h


def _markers(by_geo: list) -> list:
    """把"按归属地聚合"的结果换成地图上的点。

    半径按 sqrt(次数) 缩放：面积正比于半径平方，视觉上才和数量成比例，
    直接按次数线性放大半径会让大国点糊满整张图。
    """
    pts = geoip.points()
    out = []
    for row in by_geo:
        iso = (row.get("iso") or "").strip()
        p = pts.get(iso) if len(iso) == 2 else None
        if not p or p.get("lat") is None:
            continue
        x, y = geoip.project(p["lon"], p["lat"])
        n = row["n"]
        out.append({"iso": iso, "name": p.get("name") or row.get("geo") or iso,
                    "n": n, "ips": row["ips"], "x": round(x, 2), "y": round(y, 2),
                    "r": round(2.2 + (n ** 0.5) * 0.9, 2)})
    out.sort(key=lambda m: -m["n"])       # 大点画在下层，小点才不会被盖住
    return out


def _asset_ver() -> str:
    """静态资源版本号取最后修改时间：本地改完 css/js 刷新即生效，不必手动清缓存。"""
    try:
        newest = max(p.stat().st_mtime for p in (Path(__file__).parent / "static").iterdir())
        return str(int(newest))
    except Exception:  # noqa: BLE001
        return "1"


class TrustForwarded:
    """nginx 等反向代理下用 X-Forwarded-* 修正 scheme/host/前缀。

    必须是 WSGI 中间件而不是 before_request：Werkzeug 在构造 Request 时就算好了
    host_url，等 before_request 再改 environ 已经太晚（实测改了没效果）。
    只信任来自回环地址的转发头，否则外部请求可以自己伪造 Host，污染 canonical 与 sitemap。
    """

    LOOPBACK = ("127.0.0.1", "::1", "localhost")

    def __init__(self, wsgi):
        self.wsgi = wsgi

    def __call__(self, environ, start_response):
        if environ.get("REMOTE_ADDR") in self.LOOPBACK:
            get = lambda k: (environ.get("HTTP_" + k.upper().replace("-", "_")) or "").split(",")[0].strip()
            proto = get("x-forwarded-proto")
            host = get("x-forwarded-host")
            prefix = get("x-forwarded-prefix")
            if proto in ("http", "https"):
                environ["wsgi.url_scheme"] = proto
            if host:
                environ["HTTP_HOST"] = host
                name, _, port = host.partition(":")
                environ["SERVER_NAME"] = name
                environ["SERVER_PORT"] = port or ("443" if proto == "https" else "80")
            if prefix:
                environ["SCRIPT_NAME"] = prefix.rstrip("/")
        return self.wsgi(environ, start_response)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False
    app.json.ensure_ascii = False
    app.wsgi_app = TrustForwarded(app.wsgi_app)

    # 登录会话用配置文件里的密钥签名（zhuiju/data/admin.json，见 zhuiju/admin.py）
    app.secret_key = admin_mod.secret_key()
    app.permanent_session_lifetime = timedelta(seconds=admin_mod.SESSION_TTL)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # 本站的 POST 只有后台表单和观看埋点，都是几百字节。给个上限：/api/click 是公开接口，
    # 不设上限就等于让人拿任意大的正文来把进程撑住（超了直接 413，不进解析）
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

    # 后台里所有指向 /admin 的链接都自动带上当前标签页：切标签不该把人甩回总览，
    # 筛一个 IP 也不该把标签弄丢（同一件事：页内链接不该动我没点的东西）。
    # 写成 jinja 全局而不是每次 render 传参 —— admin.html 里指向 /admin 的链接有四十多个，
    # 漏掉一处就是"点这个链接回去标签复位了"这种只有真点到才发现的毛病。
    def _admin_url(**kw):
        if "tab" not in kw:
            kw["tab"] = admin_tab((request.args.get("tab") or "").strip())
        return url_for("admin", **kw)

    app.jinja_env.globals["admin_url"] = _admin_url
    try:
        stats_mod.ensure_schema()
    except Exception:  # noqa: BLE001 - 统计库不可写也不该挡住站点启动
        pass
    try:
        strm_mod.ensure_schema()
    except Exception:  # noqa: BLE001 - strm 库坏了也只是这一节空着，搜索照常
        pass

    def _csrf_token() -> str:
        tok = session.get("csrf")
        if not tok:
            tok = secrets.token_hex(16)
            session["csrf"] = tok
        return tok

    def _csrf_ok() -> bool:
        want = session.get("csrf") or ""
        got = request.form.get("csrf") or ""
        return bool(want) and hmac.compare_digest(str(want), str(got)[:64])

    def _authed() -> bool:
        at = session.get(admin_mod.SESSION_KEY)
        try:
            return bool(at) and (time.time() - float(at)) < admin_mod.SESSION_TTL
        except (TypeError, ValueError):
            return False

    def _login_page(error: str | None, code: int):
        return render_template("admin.html", authed=False, error=error,
                               csrf=_csrf_token(), asset_v=_asset_ver(),
                               temp=admin_mod.is_temp_password()), code

    def _record(kw: str, via: str, started: float, **num) -> None:
        """把一次查询落到 SQLite。IP 只在可信来源下取，见 admin.client_ip。

        UA 与 Referer 是客户端自己写的，当"指示"存，不当身份用；
        来源能拿到多少由浏览器的 Referrer-Policy 决定（见 zhuiju/agent.py）。
        """
        stats_mod.record(kw, admin_mod.client_ip(request.environ), via=via,
                         ms=(time.perf_counter() - started) * 1000,
                         ua=request.headers.get("User-Agent", ""),
                         referrer=request.headers.get("Referer", ""),
                         # 这一条是被谁放行的（1=拖过滑块 / 0=爬虫豁免 / None=门禁关着），
                         # 见 _human_gate；后台靠它把"猜的"和"知道的"分开
                         verified=getattr(g, "verified", None),
                         own_hosts=_own_hosts(), **num)

    def _own_hosts() -> tuple:
        """本站对外的主机名，判"站内跳转"要用；反代下 host 已被 TrustForwarded 修正过。"""
        hosts = {request.host, request.host.split(":")[0], "127.0.0.1", "localhost"}
        return tuple(h for h in hosts if h)

    # 门禁放行的前缀：静态资源、验证自己的两个接口、爬虫指令文件与退出登录。
    # /admin/logout 必须在里面：否则"退出"这个动作要先通过一道滑块，
    # 而人在被门禁页挡住时根本看不到自己已经登录的界面，等于把自己锁在里面。
    HUMAN_EXEMPT = ("/static/", "/api/human/", "/robots.txt", "/favicon.ico",
                    "/admin/logout")

    @app.before_request
    def _human_gate():
        """全站真人门禁：没拖过滑块的人，页面给验证页、接口给 423。

        注册顺序有讲究：这个钩子必须在 _touch（访问触发自动更新）**之前** —— 否则脚本只要
        不停地 GET / 就能在没被验过的情况下反复戳更新流程与 STRM 采集，那正是门禁要挡的事。

        `g.verified` 记的是"这一条是被谁放行的"，三种意思不能混成一个数：
          1    带着有效 cookie（当场拖过滑块）
          0    搜索引擎爬虫豁免（确实是机器，但按 SEO 的规则放它过去）
          None 门禁本身关着 —— 后台要是把它读成 0，就成了"关掉开关就等于全站都是机器人"
        """
        g.verified = None
        if not human_mod.enabled() or request.path.startswith(HUMAN_EXEMPT):
            return None
        ip = admin_mod.client_ip(request.environ)
        ua = request.headers.get("User-Agent", "")
        if human_mod.token_ok(request.cookies.get(human_mod.COOKIE), ip, ua):
            g.verified = 1
            return None
        if human_mod.is_search_crawler(ip, ua):
            g.verified = 0
            return None
        if request.path.startswith("/api/"):
            # 423：这个状态码本来就没什么别的用途，前端据此弹滑块；
            # 不用 401/403 是因为那不是"你没权限"，是"还不知道你是不是人"
            return jsonify({"error": "需要先通过真人验证", "human": 1}), 423
        host = request.host_url.rstrip("/")
        return make_response(render_template(
            "human.html", asset_v=_asset_ver(), csrf=_csrf_token(), hours=human_mod.max_age() // 3600,
            back=request.script_root + request.path,
            seo={"title": "追剧资源搜索 - 电影电视剧资源一站聚合",
                 "description": "输入电影、电视剧或动漫名称，一次查询多个影视资源站，"
                                "并汇总网盘、磁力与资源站入口。",
                 "canonical": f"{host}/", "site": host}), 200)

    @app.post("/api/human/challenge")
    def api_human_challenge():
        """要一块滑块：缺口位置由服务端随机，两分钟有效、只能用一次。"""
        return jsonify(human_mod.new_challenge(admin_mod.client_ip(request.environ)))

    @app.post("/api/human/verify")
    def api_human_verify():
        """提交拖到的位置。过了就发一枚匿名的签名 cookie（时长在后台「设置」里改）。"""
        body = request.get_json(silent=True) or {}
        ip = admin_mod.client_ip(request.environ)
        ua = request.headers.get("User-Agent", "")
        ok, err = human_mod.solve(ip, str(body.get("id") or ""), body.get("pct"),
                                  body.get("ms"), body.get("samples"), body.get("keys") or 0)
        if not ok:
            return jsonify({"ok": False, "error": err}), 400
        resp = make_response(jsonify({"ok": True, "hours": human_mod.max_age() // 3600}))
        # httponly：前端不需要读它（只靠"下一次请求自动带上"），给了 JS 反而多一处能被 XSS 拿走的东西；
        # secure 只在 https 下开 —— 本机 http 部署时加了这枚属性，cookie 会被浏览器整条丢掉，
        # 现象就是"验过了还是每次都弹滑块"，最难查。
        # 指纹里带的是**这一次请求**的来源与设备类型：换台电脑拿这枚 cookie 直接失效
        resp.set_cookie(human_mod.COOKIE, human_mod.issue(ip, ua),
                        max_age=human_mod.max_age(),
                        httponly=True, samesite="Lax", secure=request.is_secure, path="/")
        return resp

    @app.before_request
    def _touch():
        # 访问即触发：今天没更新过就丢一个后台进程，本次请求照常返回旧数据
        if request.path in ("/", "/sitemap.xml"):
            autoupdate.maybe_trigger()
        # STRM 采集同理，但它一轮跑不完（近一年要翻两三万页），所以判据是
        # "离上次结束满没满 min_interval_minutes"。/admin 也算一次访问：
        # 看后台的人正是想知道"采到哪了"，顺手让它往前走一格最合理。
        if request.path in ("/", "/sitemap.xml", "/admin"):
            strmjob.maybe_trigger()

    def _page(kw: str = "", snap: dict | None = None):
        host = request.host_url.rstrip("/")
        seo = {
            "kw": kw,
            "canonical": f"{host}/s/{urllib.parse.quote(kw)}" if kw else f"{host}/",
            "title": (f"《{kw}》影视资源怎么找 - 追剧资源搜索" if kw
                      else "追剧资源搜索 - 电影电视剧资源一站聚合"),
            "description": (seo_mod.describe(kw, snap or {}) if kw else
                            "输入电影、电视剧或动漫名称，一次查询多个影视资源站，"
                            "并汇总网盘、磁力与资源站入口。"),
            "snapshot": snap or {},
            "hot": _first_row(_proxied_hot(hot_mod.get())),
            "site": host,
        }
        return render_template(
            "index.html",
            categories=catalog_mod.categories(),
            # 首页那句"结果来自 N 个采集接口"和骨架屏那句"正在并发查询 N 个"数的是
            # **会被并发到的**源：停用的一律不算，只供最新流的那两个（见 Source.searchable）
            # 也不算 —— 它们不会进 search()，把它们数进去就是虚报
            sources=[{"id": s.id, "name": s.name, "note": s.note, "root": s.root}
                     for s in load_sources() if s.enabled and s.searchable],
            updated=catalog_mod.catalog().get("updated_at", ""),
            asset_v=_asset_ver(),
            refresh=refresh_info(),
            seo=seo,
        )

    @app.get("/")
    def index():
        # 禁用 JS 的人按回车：表单是普通 GET，会带着 ?kw= 回到这里。这里不接住它就等于
        # "搜了但什么都没发生"（首页照旧空着）。转到 /s/<关键词> 那个可收录的固定地址，
        # 和 JS 在地址栏里写的是同一个地方 —— 两条路落到同一个 URL，canonical 才不会分叉
        raw = (request.args.get("kw") or request.args.get("q") or "").strip()
        kw = seo_mod.clean_kw(raw)
        if len(kw) >= MIN_KW:
            return redirect(f"/s/{urllib.parse.quote(kw)}", code=302)
        return _page()

    @app.get("/s/<path:kw>")
    def seo_search(kw):
        """每个关键词一个可被搜索引擎收录的固定地址，服务端渲染结果摘要。"""
        kw = seo_mod.clean_kw(kw)
        if len(kw) < MIN_KW:
            return redirect(url_for("index"))
        autoupdate.maybe_trigger()
        seo_mod.log_query(kw)
        started = time.perf_counter()
        snap = seo_mod.snapshot(kw)
        # 只有真的去敲了上游（不是命中 6 小时快照）才记一条，
        # 否则同一部剧被反复打开会把"查询次数"灌水
        if not snap.get("from_cache"):
            _record(kw, "seo", started, results=snap.get("count"),
                    sources_ok=snap.get("sources_ok"),
                    sources_total=snap.get("sources_total"))
        return _page(kw, snap)

    @app.get("/img")
    def api_img():
        """海报代理：给防盗链的图床补 Referer，并绕开自签证书。

        `X-Img-Cache` 把这次是谁答的写出来（cache=内存 / disk=磁盘 / fetched=真去取了 /
        拒绝原因），验证"重启后海报还快不快"就靠它，不用猜。
        """
        url = (request.args.get("url") or "").strip()
        if not url:
            return "missing url", 400
        status, ctype, body, note = imgproxy.resolve(url)
        resp = make_response(body, status)
        resp.headers["Content-Type"] = ctype
        resp.headers["Cache-Control"] = "public, max-age=86400"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Img-Cache"] = note
        return resp

    @app.get("/api/hot")
    def api_hot():
        kind = request.args.get("kind", "")
        if kind in ("movie", "tv"):
            return jsonify(hot_mod.page(kind,
                                        request.args.get("offset", 0, type=int) or 0,
                                        request.args.get("limit", 12, type=int) or 12))
        # 与模板用同一份处理，海报都走 /img 代理，避免两条路径行为不一致
        h = _proxied_hot(hot_mod.get())
        for sec in ("movie", "tv"):
            h[sec] = h.get(sec) or []
            h[sec + "_total"] = len(h[sec])
            h[sec] = h[sec][:12]          # 首屏只给一行，其余点箭头按需加载
        return jsonify(h)

    @app.post("/api/hot/rebuild")
    def api_hot_rebuild():
        data = hot_mod.rebuild()
        return jsonify(data or {"error": "重建失败，沿用旧缓存"})

    @app.get("/robots.txt")
    def robots():
        return seo_mod.robots_txt(request.host_url.rstrip("/")), 200, {
            "Content-Type": "text/plain; charset=utf-8"}

    @app.get("/sitemap.xml")
    def sitemap():
        host = request.host_url.rstrip("/")
        rows = "\n".join(
            f"  <url><loc>{xml_escape(e['loc'])}</loc>"
            f"<lastmod>{e['lastmod']}</lastmod></url>"
            for e in seo_mod.sitemap_entries(host))
        return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                f'{rows}\n</urlset>\n'), 200, {"Content-Type": "application/xml; charset=utf-8"}

    @app.get("/api/refresh")
    def api_refresh():
        """前端轮询：后台更新是否在跑、什么时候结束的。"""
        return jsonify(autoupdate.status())

    @app.get("/api/search")
    def api_search():
        kw = _kw()
        if kw is None:
            return jsonify({"error": f"关键词至少需要 {MIN_KW} 个字符"}), 400
        page = max(1, min(20, request.args.get("page", 1, type=int)))
        seo_mod.log_query(kw)
        started = time.perf_counter()
        out = search(kw, page=page)
        _record(kw, "api", started, results=len(out.get("results") or []),
                hits=out.get("hits"), sources_ok=out.get("sources_ok"),
                sources_total=out.get("sources_total"))
        imgproxy.register_all(out.get("results"))
        return jsonify(out)

    @app.get("/api/catalog")
    def api_catalog():
        kw = request.args.get("kw", "").strip()
        if len(kw) > MAX_KW:
            kw = kw[:MAX_KW]
        cat = request.args.get("category") or None
        rows = catalog_mod.search(kw, category=cat,
                                  only_working=bool(request.args.get("only_working")))
        # 目录本身按分类浏览，但行内的"搜此片"要用当前影片名拼链接
        link_kw = (request.args.get("link_kw") or "").strip()[:MAX_KW]
        if link_kw:
            for r in rows:
                r["deep"] = catalog_mod.link_for(r, link_kw)
        return jsonify({"keyword": kw, "link_kw": link_kw, "total": len(rows),
                        "items": rows, "categories": catalog_mod.categories()})

    @app.get("/api/deeplinks")
    def api_deeplinks():
        # 不要求关键词：没有关键词时也给出各站入口，页面不至于空着
        kw = (request.args.get("kw") or request.args.get("q") or "").strip()[:MAX_KW]
        return jsonify({"keyword": kw, "items": catalog_mod.deeplinks(kw)})

    @app.get("/api/cloud")
    def api_cloud():
        """网盘 / 磁力查询：服务端抓取各站搜索结果页并解析条目。

        不带关键词时不查询、也不抓站，返回这一页会覆盖的站点清单（`mode="sites"`），
        页面因此不必空着；这条路径不写统计 —— 没真的搜过任何东西。
        """
        kw = (request.args.get("kw") or "").strip()[:MAX_KW]
        if not kw:
            rows = cloudsearch.site_rows()
            n = sum(1 for r in rows if r["can_query"])
            return jsonify({"keyword": "", "mode": "sites", "sites": rows,
                            "total_sites": len(rows), "can_query": n,
                            "with_results": 0, "entries": 0,
                            "note": f"{len(rows)} 个网盘 / 磁力站，其中 {n} 个有已验证的 GET 搜索模板，"
                                    f"本站能直接抓出结果；其余只能在浏览器里打开该站自己搜。"})
        if len(kw) < MIN_KW:
            return jsonify({"error": f"关键词至少需要 {MIN_KW} 个字符"}), 400
        started = time.perf_counter()
        out = cloudsearch.search(kw)
        _record(kw, "cloud", started, results=out.get("entries"),
                sources_ok=out.get("with_results"), sources_total=out.get("total_sites"))
        return jsonify(out)

    @app.get("/api/detail")
    def api_detail():
        """取一部片的详情：影片信息 + 播放线路。

        优先按 (来源, 影片 ID) 查 —— 搜索结果里每个来源都带着 ID，一次请求就够。
        没有 ID 时（猜你想搜那些海报）才按片名查：那条路要并发打一遍所有检索源，
        所以只在用户真的点开详情时才走，页面渲染时一律不预取。

        线路在这里一并返回（上游 ac=detail 本来就一起给）。以前海报详情面板走的是
        `meta=1` 剥掉 lines，那是"点详情不给链接"那一版的产物；现在面板也要给观看地址
        （折叠起来，点开某条线路才铺集数），这个参数就没有调用方了，删掉比留着
        一段没人走的分支好。
        """
        src_id = (request.args.get("src") or "").strip()[:32]
        vid = (request.args.get("vid") or "").strip()[:32]
        title = (request.args.get("t") or request.args.get("kw") or "").strip()[:60]
        src = source_by_id(src_id) if src_id else None
        if src is not None and vid:
            if not src.enabled:
                return jsonify({"ok": False, "via": "id", "source": src.id,
                                "source_name": src.name, "error": f"{src.name} 已停用"}), 404
            out = fetch_detail(src, vid, title)
        elif len(title) >= MIN_KW:
            out = detail_by_title(title)
        else:
            return jsonify({"ok": False, "error": "既没有来源与影片 ID，也没给出片名"}), 400
        return jsonify(out)

    @app.post("/api/click")
    def api_click():
        """记一次行为：kind=play 点开了观看地址，kind=detail 点了海报上的「详情」按钮。

        播放页是第三方的，点了之后浏览器直接跳走，本站只能知道"这人从哪条线路点了第几集"。
        详情那一列加上观看那一列，合起来是这个漏斗：搜了 → 点开详情看了 → 真去点了播放地址；
        光看查询数分不出这三步。

        公开接口，所以几件事必须做：play 只收 http(s)（值由客户端写，进库后还要当链接用，
        `javascript:` 混进来就是自己留 XSS；detail 本来就没有地址）、字段全部截断、按 IP 限流。
        校验不过就安静丢掉并回 204：这是埋点，回 4xx 只会让前端以为没发出去而重试。
        """
        raw = request.get_data(cache=True, as_text=True) or ""
        try:
            p = json.loads(raw) if raw else {}
        except ValueError:
            p = request.get_json(silent=True) or {}
        if not isinstance(p, dict):
            p = {}
        ip = admin_mod.client_ip(request.environ)
        now = time.time()
        with _click_lock:
            start, cnt = _click_rate.get(ip) or (now, 0)
            if now - start > CLICK_WINDOW:
                start, cnt = now, 0
            if len(_click_rate) > 4096:          # 别让这张表本身变成内存漏洞
                _click_rate.clear()
                start, cnt = now, 0
            if cnt >= CLICK_MAX:
                return "", 204
            _click_rate[ip] = (start, cnt + 1)
        stats_mod.record_click(
            ip, kind=str(p.get("kind") or "play"), url=str(p.get("url") or ""),
            kw=str(p.get("kw") or ""), title=str(p.get("title") or ""),
            src=str(p.get("src") or ""), src_name=str(p.get("src_name") or ""),
            vid=str(p.get("vid") or ""), line=str(p.get("line") or ""),
            ep=str(p.get("ep") or ""), place=str(p.get("place") or "card"),
            ua=request.headers.get("User-Agent", ""))
        return "", 204

    @app.get("/api/health")
    def api_health():
        """自检：用固定关键词逐个访问检索源，确认接口是否仍然可用。"""
        kw = request.args.get("kw", "电影")
        out = []
        for s in load_sources():
            # 站点把搜索关了的那两个（见 Source.searchable）不该按"搜不到"来判死：
            # 它们靠最新流活着，所以换个探法，并把用的是哪条路一起报出来，
            # 否则自检页上永远是两个红叉，久而久之就没人看这页了
            probe_kw = kw if s.searchable else ""
            r = fetch_one(s, probe_kw)
            out.append({"id": s.id, "name": s.name, "ok": r["ok"],
                        "mode": "search" if s.searchable else "latest",
                        "count": r["count"], "ms": r["ms"], "error": r["error"],
                        "sample": [i["title"] for i in r["items"][:2]]})
        return jsonify({"keyword": kw, "results": out})

    # ------------------------------------------------------------- Emby STRM 接口
    @app.get("/api/strm/manifest")
    def api_strm_manifest():
        """分卷清单：电影/电视剧各有哪些卷、每卷多少部多少文件、包多大、下载地址。

        这就是"strm 太多要分成 movie01、movie02… 并在接口里体现"的那一份出口。
        """
        out = strm_mod.manifest()
        st = strmjob.status()
        out["job"] = {k: st.get(k) for k in
                      ("running", "next_in", "last_trigger", "state", "progress")}
        out["settings"] = st["settings"]
        return jsonify(out)

    @app.get("/api/strm/status")
    def api_strm_status():
        """采集到哪了：在不在跑、上次跑了多少页、库里多少条、待导出多少。"""
        return jsonify(strmjob.status())

    @app.get("/api/strm/download")
    def api_strm_download():
        """扁平下载清单：`{"Movies": {"movie01.zip": "url"}, "TVs": {"tv01.zip": "url"}}`。

        和 /api/strm/manifest 的分工：那份讲"每卷多少部、多少文件、包多大、什么时候打的"，
        这一份只回答"要下哪些包、地址是什么"，给脚本直接遍历下载用。
        默认给绝对地址（?abs=0 退成相对）—— 清单常常是在另一台机器上照着敲的，
        相对地址离开本站就没用了。
        """
        base = "" if (request.args.get("abs") or "1") == "0" else request.host_url.rstrip("/")
        return jsonify(strm_mod.download_map(base))

    @app.get("/api/strm/index")
    def api_strm_index():
        kind = (request.args.get("kind") or "").strip().lower()
        part = (request.args.get("part") or "").strip().lower()
        out = strm_mod.part_titles(kind, part,
                                   request.args.get("page", 1, type=int) or 1,
                                   request.args.get("per", 200, type=int) or 200)
        return jsonify(out), (400 if out.get("error") else 200)

    @app.get("/api/strm/tree")
    def api_strm_tree():
        """一卷里所有 strm 的相对路径，一行一个 —— 给"自己写脚本批量拉"用。

        用 text/plain 而不是 JSON：这份清单的主要用法是 `curl ... | while read p`，
        一行一个比转义过的一串引号好处理。要结构化数据去打 /api/strm/index。
        """
        kind = (request.args.get("kind") or "").strip().lower()
        part = (request.args.get("part") or "").strip().lower()
        paths = strm_mod.part_paths(kind, part)
        if not paths:
            return ("没有这一卷（kind 要 movie 或 tv，part 要 movie01/tv01 这种写法）\n",
                    404, {"Content-Type": "text/plain; charset=utf-8"})
        head = f"# {kind}/{part} 共 {len(paths)} 个 strm · 单个文件取 " \
               f"/strm/file?path=<这一行> · 整卷包取 /strm/zip?name={part}.zip\n"
        return (head + "\n".join(paths) + "\n", 200,
                {"Content-Type": "text/plain; charset=utf-8"})

    @app.get("/strm/zip")
    def strm_zip():
        """下载一个分卷包（movie01.zip / tv01.zip …）。

        文件名是从库里查出来的，不是把请求里的路径直接拼到磁盘上 ——
        那等于开一个任意文件下载。见 strm.zip_file()。
        """
        name = (request.args.get("name") or "").strip()
        code, path, err = strm_mod.zip_file(name)
        if code != 200:
            return jsonify({"error": err or "取不到"}), code
        # download_name 用盘上那个文件名，不用请求里传来的字符串：
        # 名字已经被 zip_file() 按 movieNN.zip 的形状认过一遍并查过库了
        return send_file(path, as_attachment=True,
                         download_name=os.path.basename(path),
                         mimetype="application/zip")

    @app.get("/strm/file")
    def strm_file():
        """取单个 strm 文件（排查某一条线路时用得上，批量还是走分卷包）。"""
        rel = (request.args.get("path") or "").strip()
        code, body, err = strm_mod.read_strm(rel)
        if code != 200:
            return jsonify({"error": err or "取不到"}), code
        return (body, 200, {"Content-Type": "text/plain; charset=utf-8",
                            "Cache-Control": "no-cache"})

    @app.post("/admin/strm/settings")
    def admin_strm_settings():
        """后台改采集设置（含时间范围）：写进 strm.db，立刻生效不用重启。"""
        if not _authed():
            return _login_page(None, 401)
        if not _csrf_ok():
            return _login_page("表单已过期，请重新提交", 400)
        try:
            _cfg, err = strm_mod.save_settings(request.form.to_dict())
        except Exception as exc:  # noqa: BLE001 - 保存失败要说人话，不该把后台页变成 500
            return redirect(url_for("admin", strm_err=f"{type(exc).__name__}: {exc}"[:160],
                                    _anchor="strm"))
        if err:
            return redirect(url_for("admin", strm_err=err[:160], _anchor="strm"))
        return redirect(url_for("admin", strm_set="1", _anchor="strm"))

    @app.post("/admin/strm/run")
    def admin_strm_run():
        """立刻催一轮采集（不等最小间隔）。已经在跑就只是回到页面看进度。"""
        if not _authed():
            return _login_page(None, 401)
        if not _csrf_ok():
            return _login_page("表单已过期，请重新提交", 400)
        out = strmjob.start_now()
        return redirect(url_for("admin", strm_run="1" if out.get("ok") else "0",
                                why=str(out.get("error") or out.get("pid") or "")[:60], _anchor="strm"))

    @app.post("/admin/strm/export")
    def admin_strm_export():
        """立刻把库里的东西导出+打包。全量重建是"改了时间范围"之后该按的那一颗。

        和采集共用同一把锁（strmjob.LOCK）：导出要写几千上万个文件，
        这时候再起一轮采集就是在改同一批文件，两边会互相踩。
        """
        if not _authed():
            return _login_page(None, 401)
        if not _csrf_ok():
            return _login_page("表单已过期，请重新提交", 400)
        full = (request.form.get("mode") or "") == "full"
        if strmjob.running():
            return redirect(url_for("admin", strm_run="0", why="已经有一轮任务在跑，等它结束再导出",
                                    _anchor="strm"))
        try:
            autoupdate.spawn(strmjob.SCRIPT, strmjob.LOG, strmjob.LOCK,
                             args=["--export-only"] + (["--full"] if full else []))
        except Exception as exc:  # noqa: BLE001
            return redirect(url_for("admin", strm_run="0", why=f"{type(exc).__name__}: {exc}"[:120],
                                    _anchor="strm"))
        return redirect(url_for("admin", strm_run="1", why="全量重建并打包" if full else "增量导出并打包",
                                _anchor="strm"))

    @app.get("/admin")
    def admin():
        """后台统计：口令通过才给看，全部数据来自 SQLite。"""
        if not _authed():
            return _login_page(None, 401)
        # 用的还是首次启动随机生成的口令 -> 先领着去改成自己定的
        # （环境变量指定口令时不算，那种部署方式本来就不打算改文件）
        if admin_mod.is_temp_password():
            return redirect(url_for("admin_password", first=1))
        flt = {k: (request.args.get(k) or "").strip()[:80]
               for k in ("ip", "kw", "via", "geo", "browser", "os", "device", "ref_kind",
                         "who", "day_from", "day_to", "title", "host", "place", "kind")}
        if flt["via"] not in stats_mod.VIA:
            flt["via"] = ""
        if flt["place"] not in stats_mod.CLICK_PLACES:
            flt["place"] = ""
        if flt["kind"] not in stats_mod.CLICK_KINDS:
            flt["kind"] = ""
        if flt["who"] not in stats_mod.WHO_VALUES:
            flt["who"] = ""
        # 什么都不选时默认最近一周（含今天）：用得越久这页越长，而"今天有没有人用"
        # 恰恰是最想知道的。?day=all 是显式要看全部的出口，日期框里回填的就是这个区间。
        day_all = (request.args.get("day") or "") == "all"
        if day_all:
            flt["day_from"] = flt["day_to"] = ""
        elif not flt["day_from"] and not flt["day_to"]:
            flt["day_to"] = date.today().isoformat()
            flt["day_from"] = (date.today() - timedelta(days=DEFAULT_WINDOW - 1)).isoformat()
        per = request.args.get("per", 50, type=int) or 50
        page = request.args.get("page", 1, type=int) or 1
        # 「只看搜索 / 只看点开」：合流列表按时间排在一起最贴近"这个人当时做了什么"，
        # 但只想数搜索的人不该被点击行掺进来，所以给一个显式的出口，而不是偷偷少一半
        scope = (request.args.get("scope") or "all").strip()
        if scope not in ("all", "query", "click"):
            scope = "all"
        flt["scope"] = scope
        # 标签页：非法值回总览（见 admin_tab）。tab 只决定"哪几块显示"，不参与任何数据口径 ——
        # 同一套筛选条件在四个标签里数的是同一批记录，切个标签不该把数字变了
        tab = admin_tab((request.args.get("tab") or "").strip())
        rows = stats_mod.list_activity(flt, page=page, per=per, scope=scope)
        agg = stats_mod.summary(flt)
        cagg = stats_mod.click_stats(flt)
        # 行为特征：UA 三档只是"它自己说的"，这一节按 IP 看节奏、跳转与点开比。
        # 多取一些再截前 40 行给表格里看，整份留给明细挂 IP 徽章 —— 明细那一页可能
        # 出现的 IP 未必排得进前 40，不能因为"表格没显示它"就不给它挂徽章。
        # 500 这个上限是为了**改判一致**：行为命中几条会把「像真人」改成「行为像脚本」，
        # 落在上限外的 IP 就改不到，同一个人在两张表上的说法会不一样。
        beh_all = stats_mod.behavior(flt, limit=500)
        beh = beh_all[:40]
        beh_map = {b["ip"]: b for b in beh_all}
        geo_info = geoip.available()
        markers = _markers(agg["by_geo"]) if geo_info["points"] else []
        base = geoip.basemap() if geo_info["basemap"] else {"d": "", "by_iso": {}, "error": "没有底图文件"}
        drawn = {m["iso"] for m in markers if m["iso"] in base["by_iso"]}
        # 翻页链接要把当前筛选条件一起带上，否则点了下一页筛选就丢了
        keep = {k: v for k, v in flt.items() if v}
        keep["per"] = rows["per"]
        if day_all:
            # 日期被默认值顶掉了，不把这个标记带上，点一次"下一页"就悄悄回到最近一周
            keep["day"] = "all"
        # 「看全部历史」那个链接要留住除日期以外的筛选，否则一去看全部，筛的东西全丢了
        keep_args = {k: v for k, v in flt.items()
                     if v and k not in ("day_from", "day_to", "per", "page")}
        # 「全部 / 只看搜索 / 只看点开」三个胶囊的地址在 Python 里拼好：
        # Jinja 的字典字面量不认 `{**keep, ...}`（一渲染就是 unexpected '**'），
        # 而换范围必须回到第 1 页——两边条数不一样，停在第 4 页看"只看点开"会是空的
        args_scope = {s: {k: v for k, v in keep.items() if k != "page"} | {"scope": s}
                      for s in SCOPE_CN}
        # 汇总卡片里那颗「详情 / 观看点击」要点开的表上去，所以除了换 scope 还得换标签；
        # 这件事在 Python 里拼好整条 URL：Jinja 的函数调用不接受 `f(**d, k=v)` 这种混合写法
        # （直接 TemplateSyntaxError），留给模板就只能再加一个中间变量，不如这里一行搞定
        click_url = url_for("admin", **{**args_scope["click"], "tab": "detail"})
        # NFO 里的海报是绝对地址，得知道"人是从哪个地址访问本站的"：
        # 后台没填对外地址时就拿这次访问用的这个（反代下已被 TrustForwarded 修正过）
        strm_mod.remember_host(request.host_url)
        return render_template(
            "admin.html", authed=True, error=None, csrf=_csrf_token(),
            tab=tab, tabs=ADMIN_TABS,
            click_url=click_url,
            # 「设置」那一节的表单从 settings.SPEC 生成：加一项设置只改 settings.py，
            # 不用再来模板里补一格（补漏一次的后果是"后端认这个键、页面上看不见"）
            setfields=settings_mod.fields(),
            # 每一项现在是谁定的（env / file / default）：被环境变量顶着的时候
            # 页面上必须说出来，否则"我改了怎么没生效"根本查不到头
            setsrc={k: settings_mod.source_of(k) for k in settings_mod.DEFAULTS},
            asset_v=_asset_ver(), via_cn=VIA_CN, ref_kind_cn=REF_KIND_CN,
            place_cn=CLICK_PLACE_CN, kind_cn=CLICK_KIND_CN, scope_cn=SCOPE_CN,
            who_cn={k: stats_mod.who_label(k) for k in stats_mod.WHO_LABELS},
            beh=beh, beh_map=beh_map,
            # Emby STRM 那一节：设置与库都在 strm.db，进度在采集进程写的文件里，
            # 分卷清单从 file/zip 两张表聚合出来（页面只讲"采到哪了、有几卷"）
            smeta=strm_mod.manifest(), sjob=strmjob.status(),
            sspec=strm_mod.spec_rows(),
            smsg=_strm_notice(request.args, strmjob.status()),
            # 改判门槛要写在页面上（几条命中降到哪一档），不能只在代码里
            BEHAVIOR_SUSPECT=stats_mod.BEHAVIOR_SUSPECT,
            BEHAVIOR_SCRIPT=stats_mod.BEHAVIOR_SCRIPT,
            day_all=day_all, day_window=DEFAULT_WINDOW,
            keep_days=stats_mod.KEEP_DAYS, keep_args=keep_args,
            flt={**flt, "per": rows["per"]},
            agg=agg, rows=rows, temp=False, args_scope=args_scope,
            cagg=cagg,
            geo=geo_info, map_paths=base["d"], map_active="".join(
                base["by_iso"][i] for i in sorted(drawn)),
            geo_warn=stats_mod.MIGRATE_ERROR,
            fetch_cmd=autoupdate.py_exe("tools/fetch_geo.py"),
            upd=autoupdate.status(),
            markers=markers, offmap=[m for m in markers if m["iso"] not in base["by_iso"]],
            setinfo=_setinfo(),
            notice=("口令已更新，下次登录请用新口令" if request.args.get("set") else None)
                   or ("设置已保存，判断「今天该不该更新」立刻按新时间点走，不用重启"
                       if request.args.get("settings_saved") else None),
            settings_err=bool(request.args.get("settings_err")),
            pct_empty=round(agg["empty"] / agg["count"] * 100) if agg["count"] else 0,
            args_next={**keep, "page": rows["page"] + 1},
            args_prev={**keep, "page": rows["page"] - 1})

    @app.route("/admin/password", methods=("GET", "POST"))
    def admin_password():
        """改口令：写在配置文件里，不用重启服务。"""
        if not _authed():
            return _login_page(None, 401)
        first = bool(request.args.get("first"))
        ctx = dict(csrf=_csrf_token(), asset_v=_asset_ver(), first=first,
                   min_len=admin_mod.MIN_LEN,
                   env_lock=admin_mod.using_env_password(),
                   temp=admin_mod.is_temp_password())
        if request.method == "GET":
            return render_template("admin_password.html", error=None, **ctx)
        if not _csrf_ok():
            return _login_page("表单已过期，请重新提交", 400)
        new = (request.form.get("password") or "")[:admin_mod.MAX_LEN + 20]
        again = (request.form.get("password2") or "")[:admin_mod.MAX_LEN + 20]
        err = None
        # 当前口令必须验一次：改了文件才生效这件事，不该让一个过期会话替你做
        if not admin_mod.password_ok(request.form.get("current") or ""):
            err = "当前口令不对"
        elif new != again:
            err = "两次输入的新口令不一样"
        else:
            err = admin_mod.password_error(new)
        if err:
            return render_template("admin_password.html", error=err, **ctx), 400
        admin_mod.set_password(new)
        return redirect(url_for("admin", set=1))

    @app.post("/admin/settings")
    def admin_settings():
        """保存后台设置（几点算新的一天、门禁开不开、验证管多久）。写 data/settings.json，不用重启。"""
        if not _authed():
            return _login_page(None, 401)
        if not _csrf_ok():
            return _login_page("表单已过期，请重新提交", 400)
        bad = 0
        # 逐项存：认不出来的一项**一条都不写**（半套设置比没设置更难查），
        # 其余合法的照存 —— 一个人改了两个数、其中一个打错，不该让他白填一遍
        for key in settings_mod.SPEC:
            if key not in request.form:
                continue
            ok, _err = settings_mod.set_value(key, request.form.get(key))
            bad += 0 if ok else 1
        # 回到「设置」那一格：现在分标签页了，跳回默认标签等于"我点了保存，页面自己跑掉了"
        if bad:
            return redirect(url_for("admin", settings_err=1, tab="settings"))
        return redirect(url_for("admin", settings_saved=1, tab="settings"))

    @app.post("/admin/login")
    def admin_login():
        who = admin_mod.client_ip(request.environ)
        wait = admin_mod.throttle.blocked(who)
        if wait:                      # 同一来源连续错太多次就先冷却，脚本猜口令猜不动
            return _login_page(f"失败次数过多，请 {wait} 秒后再试", 429)
        if not _csrf_ok():
            return _login_page("表单已过期，请重新提交", 400)
        if admin_mod.password_ok(request.form.get("password") or ""):
            admin_mod.throttle.reset(who)
            session[admin_mod.SESSION_KEY] = time.time()
            session.permanent = True
            session["csrf"] = secrets.token_hex(16)     # 登录后换一枚，旧表单不能再复用
            # 还在用首次生成的随机口令 -> 直接领去改，别让人先撞一次统计页
            if admin_mod.is_temp_password():
                return redirect(url_for("admin_password", first=1))
            return redirect(url_for("admin"))
        left = admin_mod.throttle.fail(who)
        return _login_page(f"口令不正确（还可尝试 {left} 次）", 401)

    @app.post("/admin/logout")
    def admin_logout():
        if _csrf_ok():
            session.pop(admin_mod.SESSION_KEY, None)
        return redirect(url_for("admin"))

    @app.errorhandler(404)
    def nf(_e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "接口不存在"}), 404
        return _page()

    return app


def _kw() -> str | None:
    raw = (request.args.get("kw") or request.args.get("q") or "").strip()
    raw = re.sub(r"\s+", " ", raw)[:MAX_KW]
    return raw if len(raw) >= MIN_KW else None


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
