# -*- coding: utf-8 -*-
"""查询统计：SQLite 落盘 + 后台页面要用的聚合查询。

为什么用 SQLite 而不是继续加 jsonl
  queries.jsonl 只能追加、要算"某 IP 在某个日期范围内查了几次"就得整份读进来解析，
  统计页要按 IP / 关键词 / 日期范围过滤还要分页，这些正好是 SQL 的强项，
  而且 sqlite3 是标准库，不额外加依赖。

并发
  开发服务器是多线程的，所以每次操作用一个短连接（WAL + busy_timeout），
  不开长连接、不跨线程共享 connection。

隐私
  这两张表记的是"谁的 IP 在什么时候搜了什么、点开了哪条播放地址"。默认只监听
  127.0.0.1，所以全部 IP 都是 127.0.0.1；只有配合 --host 0.0.0.0 或 nginx 反代
  才会有多个客户端 IP。
  所以 stats.db 连同 admin.json 一起进了 .gitignore，不在版本库里分发。
"""
from __future__ import annotations

import ipaddress
import math
import os
import re
import sqlite3
import threading
import time
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
DB = DATA / "stats.db"

# 留多久。本地小工具，默认一年；超过就在初始化时清掉，免得文件无限长大
KEEP_DAYS = int(os.environ.get("ZHUIJU_STATS_KEEP_DAYS", "365"))
MAX_PAGE = 500                    # 最多翻到第几页，防止 offset 大到扫全表
VIA = ("api", "seo", "cloud")     # 一次查询是从哪个入口来的

_init_lock = threading.Lock()
_ready = False
_last_prune = [0.0]
# 建表/补列出过什么问题要能被看到：create_app 里那层 try 是为了"统计库坏了也不挡住搜索"，
# 但因此失败就会静默——之前列索引顺序写错，症状只是"归属地永远是空"，很难归因
MIGRATE_ERROR = ""

SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  ts            TEXT NOT NULL,      -- 本地时间 YYYY-MM-DD HH:MM:SS，展示用
  day           TEXT NOT NULL,      -- YYYY-MM-DD，日期范围过滤与按天聚合都用它
  ip            TEXT NOT NULL,
  kw            TEXT NOT NULL,
  via           TEXT NOT NULL,      -- api=交互搜索 / seo=落地页快照 / cloud=网盘查询
  results       INTEGER,            -- 合并去重后的条数
  hits          INTEGER,            -- 各源原始命中数之和
  sources_ok    INTEGER,
  sources_total INTEGER,
  ms            REAL,               -- 本次搜索实际等了多久
  iso           TEXT,               -- 归属地国家码；内网/保留为 ''
  country       TEXT,               -- 国家名（归属地列表用这个，不带省市运营商）
  geo           TEXT,               -- 完整归属地文案，明细行显示
  browser       TEXT,               -- 解析出的浏览器名+版本，如 "Edge 124.0"
  os            TEXT,               -- 系统，如 "Windows 10/11"
  device        TEXT,               -- 手机 / 平板 / 桌面 / 程序
  bot           INTEGER,            -- 1=爬虫或脚本客户端，与真人的查询分开看
  ua            TEXT,               -- 原始 UA（截断），排查识别错误时要用
  ref           TEXT,               -- 来源：站内是完整路径，站外只有 origin（浏览器策略）
  ref_kind      TEXT,               -- direct / site / search / out / other
  ref_label     TEXT                -- 给人看的来源文案
);
CREATE INDEX IF NOT EXISTS idx_queries_day ON queries(day);
CREATE INDEX IF NOT EXISTS idx_queries_ip  ON queries(ip);
CREATE INDEX IF NOT EXISTS idx_queries_kw  ON queries(kw);

-- 行为日志：点开详情、点开某条观看地址。单独一张表：一次查询可以点好几条，
-- 塞进 queries 要么覆盖要么得改主键语义。
-- 归属地、浏览器这几列 queries 有，clicks 也必须有一份：明细页把两张表合成
-- 一张活动列表按时间排，缺哪一列那一行就只能空着，"谁在什么时候点了什么"
-- 恰恰是最想按浏览器/归属地筛出来的部分。
CREATE TABLE IF NOT EXISTS clicks (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  ts      TEXT NOT NULL,
  day     TEXT NOT NULL,
  ip      TEXT NOT NULL,
  kind    TEXT NOT NULL DEFAULT 'play',  -- play=点开观看地址 / detail=点了「详情」按钮
  kw      TEXT,                 -- 从哪个关键词来的（前端带，可能为空）
  title   TEXT,                 -- 点的是哪部片
  src     TEXT,                 -- 采集源 id
  src_name TEXT,                -- 采集源名字，后台直接显示
  vid     TEXT,                 -- 影片 ID
  line    TEXT,                 -- 线路名，如 "新浪线路"
  ep      TEXT,                 -- 集名/选集名，如 "第03集"
  url     TEXT,                 -- 目标播放地址（截断）
  host    TEXT,                 -- 它的域名：按站聚合比整条 URL 有用
  place   TEXT,                 -- panel=海报详情面板 / card=卡片里展开的线路 / hot=猜你想搜的海报
  iso     TEXT,                 -- 下面六列与 queries 同口径，见 normalize_agent
  country TEXT,
  geo     TEXT,
  browser TEXT,
  os      TEXT,
  device  TEXT,
  bot     INTEGER,
  ua      TEXT
);
CREATE INDEX IF NOT EXISTS idx_clicks_day ON clicks(day);
CREATE INDEX IF NOT EXISTS idx_clicks_kw  ON clicks(kw);
"""

# 老库没有这两列，加列要在建表之后单独补一次（CREATE TABLE IF NOT EXISTS 不会改已有表）
GEO_COLUMNS = (("iso", "TEXT"), ("geo", "TEXT"),
               # 国家名单独一列：geo 是给人看的整行文案（会掺进省市与运营商），
               # 归属地列表要的是"哪个国家"，两者不能共用一个字段
               ("country", "TEXT"))
# 浏览器与来源页。这几列只用于分组，不单独建索引：表本来就小，
# 多一个索引就多一个"升级时列还不存在"的失败点（iso 索引就踩过这个坑）
AGENT_COLUMNS = (("browser", "TEXT"), ("os", "TEXT"), ("device", "TEXT"),
                 ("bot", "INTEGER"), ("ua", "TEXT"),
                 ("ref", "TEXT"), ("ref_kind", "TEXT"), ("ref_label", "TEXT"))
# 老库里的 clicks 没有这几列，补上：kind 把老行认成 play（它们确实是观看点击），
# 归属地与浏览器六列由 normalize_clicks() 按留存的 ua / ip 回填一次
CLICK_COLUMNS = (("kind", "TEXT NOT NULL DEFAULT 'play'"),
                 ("iso", "TEXT"), ("country", "TEXT"), ("geo", "TEXT"),
                 ("browser", "TEXT"), ("os", "TEXT"), ("device", "TEXT"))

# 「认不出来」在库里只能有一种写法。补列之前那批行这三列是 NULL（那时根本没存 UA），
# 现在的写法是 browser/device 存 "未知"、os 存 ''（见 record()）。两套写法混在一张表里，
# 面板上同一个"未知"就占两行（看着像重复统计），点进去过滤条件又只命中其中一套，
# 数字对不上比数错更难查。
UNKNOWN = "未知"

# 「这条像真人吗」只有三档，而且**不装得比实际更确定**：
#   bot     —— UA 自己报了爬虫或脚本客户端（agent.BOTS 命中，写库时就是 bot=1）
#   unknown —— 无从判断：当初没存 UA、`bot` 这列是补列之前的 NULL，
#              或者**UA 根本不是浏览器的样子**（不以 `Mozilla/` 开头）
#   human   —— UA 有浏览器骨架且没自报爬虫。**这不代表一定是人**：UA 是客户端随便写的，
#              要往下分只能看行为（见 behavior()），或者上会话 token（那要加 cookie）
# 「浏览器的样子」这一判是补上来的：以前只要 UA 里没写 curl 就落进 human，于是
# `Werkzeug/3.1.9`（Flask 的 test_client 自带 UA，离线工具每跑一次就往真实库里写一行）
# 被算成"像真人"，页面上那一行同时显示「浏览器 未知 + 像真人」，自相矛盾。
# 为什么用 `Mozilla/` 开头而不是 `like Gecko`：Chrome/Edge/Safari/微信/QQ/UC/夸克/ Firefox
# 全都以 `Mozilla/5.0` 开头，而 Firefox 的 UA 里是 `Gecko/20100101`、没有 `like Gecko`，
# 用后者会把真 Firefox 判成说不清（实测过：这一判加上去前后，非 Mozilla/ 的 27 条全是 Werkzeug）。
# 这段 SQL 是唯一口径：三档徽章、筛选、聚合都从这里出，别在模板里再拼一份 CASE。
WHO_SQL = ("CASE WHEN COALESCE(bot, 0) = 1 THEN 'bot'"
           " WHEN ua IS NULL OR bot IS NULL OR ua NOT LIKE 'Mozilla/%' THEN 'unknown'"
           " ELSE 'human' END")
WHO_VALUES = ("human", "bot", "unknown")


def who_label(who: str) -> str:
    """给三档一个固定说法（模板与报表都用它，不各自翻译）。

    `mixed` 只出现在 behavior() 那种**按 IP 汇总**的地方：同一个 IP 里既有浏览器 UA
    又有脚本 UA（家里共用一个出口、或有人边用边跑脚本），单条记录不会是这个值。
    """
    return {"human": "像真人", "bot": "脚本/爬虫", "unknown": "说不清",
            "mixed": "两种都有"}.get(who, who or "说不清")


def normalize_agent(con) -> int:
    """把历史 NULL 行写成和现在一样的口径，返回改了多少行。幂等：没有 NULL 就是 0。

    原始 UA 仍然留在 ua 列里（这批行的 ua 是空串，所以确实无从判断，不是丢了证据）。
    """
    n = con.execute("SELECT COUNT(*) FROM queries WHERE browser IS NULL"
                    " OR os IS NULL OR device IS NULL").fetchone()[0]
    if not n:
        return 0
    for col, val in (("browser", UNKNOWN), ("device", UNKNOWN), ("os", "")):
        con.execute(f"UPDATE queries SET {col} = ? WHERE {col} IS NULL", (val,))
    return n


def normalize_clicks(con) -> int:
    """给 clicks 里补列之前的行回填归属地与浏览器，返回改了多少行。幂等。

    这六列是后加的：老行只有 ip 与 ua，就地按现在写行的同一套办法解析一次
    （parse_ua / geoip.locate），补出来的口径才和新行对得上——否则同一个浏览器
    在明细里会一半有名字一半是空的，按浏览器筛还筛不到老行。
    """
    # 按位置解包而不是 r["na"]：调用方给的连接未必设了 row_factory=Row
    # （ensure_schema 里的连接设了，测试与普通 sqlite3.connect 出来的没有），
    # 依赖 row_factory 的函数没法被复用
    rows = list(con.execute("SELECT id, ip, ua, browser IS NULL, country IS NULL FROM clicks"))
    if not rows:
        return 0
    from . import agent, geoip
    # 归属地库还没下载时这一半先不补：补了就把 country 写成非 NULL，
    # 等库到位后再跑也认不出这些行是"没解析过"还是"解析成内网"了（backfill_geo 同理）
    has_geo = geoip.available()["xdb"]
    n = 0
    for rid, ip, ua, na, ng in rows:
        sets, vals = [], []
        if na:
            a = agent.parse_ua(ua)
            sets += ["browser = ?", "os = ?", "device = ?"]
            vals += [a["browser"] or UNKNOWN, a["os"] or "", a["device"] or UNKNOWN]
        if ng and has_geo:
            g = geoip.locate(clean_ip(ip) or "")
            pub = g["kind"] == "public"
            sets += ["iso = ?", "country = ?", "geo = ?"]
            vals += [g["iso"] if pub else "", g["country"] if pub else "", g["label"]]
        if not sets:
            continue
        vals.append(rid)
        con.execute(f"UPDATE clicks SET {', '.join(sets)} WHERE id = ?", vals)
        n += 1
    return n

# 归属地的索引必须等列真的存在之后再建：把它写在 SCHEMA 里，
# 对已有库就是"给还不存在的列建索引" -> no such column，整个 ensure_schema 失败
# （而且 create_app 把异常吞了，症状是"新克隆正常、老库升级后归属地一直是空"）
GEO_INDEX = "CREATE INDEX IF NOT EXISTS idx_queries_iso ON queries(iso)"


def connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB), timeout=5)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=4000")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def ensure_schema() -> None:
    """建表、补列、按 KEEP_DAYS 清一次老数据（每小时最多清一次）。"""
    global _ready, MIGRATE_ERROR
    with _init_lock:
        con = connect()
        try:
            con.executescript(SCHEMA)
            cols = {r["name"] for r in con.execute("PRAGMA table_info(queries)")}
            for name, typ in GEO_COLUMNS + AGENT_COLUMNS:
                if name not in cols:
                    con.execute(f"ALTER TABLE queries ADD COLUMN {name} {typ}")
            con.execute(GEO_INDEX)          # 列确定了存在之后才建它的索引
            # 老行的 browser/device/os 是 NULL，和新写的 '未知'/'' 是同一个意思，
            # 不归一就会在面板上占两行
            normalize_agent(con)
            # clicks 也是后加的表：已经建过的库里它没有 kind 与归属地那几列，
            # 补列之后按留存的 ip / ua 回填一次，新老行才是同一套口径
            ccols = {r["name"] for r in con.execute("PRAGMA table_info(clicks)")}
            for name, typ in CLICK_COLUMNS:
                if name not in ccols:
                    con.execute(f"ALTER TABLE clicks ADD COLUMN {name} {typ}")
            normalize_clicks(con)
            con.commit()
            _ready = True
            MIGRATE_ERROR = ""
            if time.time() - _last_prune[0] > 3600:
                _last_prune[0] = time.time()
                cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
                con.execute("DELETE FROM queries WHERE day < ?", (cutoff,))
                # 点击表和查询表一起过期：只清一张的话，另一张会一直长，
                # 而且留下的点击对不上已经被清掉的搜索，看着像凭空多了些人
                con.execute("DELETE FROM clicks WHERE day < ?", (cutoff,))
                con.commit()
        except sqlite3.Error as exc:
            # 记下来给后台页面显示，别让它只表现为"归属地一直是空的"
            MIGRATE_ERROR = f"{type(exc).__name__}: {str(exc)[:140]}"
            raise
        finally:
            con.close()
    backfill_geo()


def backfill_geo(limit: int = 20000) -> int:
    """给历史上没有归属地的记录补一次解析。

    补列之前的行 iso 是 NULL（不是 ''，'' 表示"查过、是内网"），所以只挑 NULL 的。
    归属地库没下载时直接返回，不做无谓的循环。
    """
    from . import geoip
    if not geoip.available()["xdb"]:
        return 0
    con = connect()
    try:
        rows = con.execute("SELECT DISTINCT ip FROM queries WHERE country IS NULL LIMIT ?",
                           (limit,)).fetchall()
        if not rows:
            return 0
        n = 0
        for (ip,) in rows:
            r = geoip.locate(ip)
            con.execute("UPDATE queries SET iso = ?, country = ?, geo = ?"
                        " WHERE ip = ? AND country IS NULL",
                        (r["iso"] if r["kind"] == "public" else "",
                         r["country"] if r["kind"] == "public" else "", r["label"], ip))
            n += 1
        con.commit()
        return n
    finally:
        con.close()


def clean_ip(raw) -> str:
    """只收看起来确实是 IP 的字符串。

    反代头是外部可写的，直接入库会塞进任意文本（换行还能伪造日志行），
    所以用标准库解析一次，解析不出就退回空串。
    """
    s = str(raw or "").strip().strip("[]")
    if not s:
        return ""
    try:
        return str(ipaddress.ip_address(s))
    except ValueError:
        return ""


def record(kw: str, ip: str, *, via: str = "api", results: int | None = None,
           hits: int | None = None, sources_ok: int | None = None,
           sources_total: int | None = None, ms: float | None = None,
           iso: str | None = None, geo: str | None = None,
           ua: str | None = None, referrer: str | None = None,
           own_hosts=()) -> None:
    """记一次查询。统计绝不能把搜索本身搞挂，所以任何异常都吞掉。

    ua / referrer 是原始请求头，浏览器与来源在这里就地解析并落成结构化列，
    这样"按浏览器分组""按来源分组"就是普通的 SQL，不必每次渲染再猜。
    """
    kw = (kw or "").strip()[:60]
    if len(kw) < 1:
        return
    try:
        if not _ready:
            ensure_schema()
        from . import agent, geoip
        if iso is None or geo is None:
            r = geoip.locate(clean_ip(ip) or "")
            iso = r["iso"] if r["kind"] == "public" else ""
            geo = r["label"]
            country = r["country"] if r["kind"] == "public" else ""
        else:
            country = "" if not iso else None      # 调用方给了 iso/geo 但没给 country 时补一次
            if country is None:
                country = (geoip.locate(clean_ip(ip) or "") or {}).get("country", "")
        a = agent.parse_ua(ua)
        f = agent.parse_ref(referrer, own_hosts)
        now = datetime.now()
        con = connect()
        try:
            con.execute(
                "INSERT INTO queries (ts, day, ip, kw, via, results, hits,"
                " sources_ok, sources_total, ms, iso, country, geo,"
                " browser, os, device, bot, ua, ref, ref_kind, ref_label)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (now.strftime("%Y-%m-%d %H:%M:%S"), now.date().isoformat(),
                 clean_ip(ip) or "unknown", kw, via if via in VIA else "api",
                 results, hits, sources_ok, sources_total,
                 round(float(ms), 1) if ms is not None else None, iso, country, geo,
                 # 认不出来就按库里的统一写法存（'' 也算认不出来），别把 NULL/''/'未知'
                 # 三种写法混进同一张表——那会让面板上同一个"未知"占两行
                 a["browser"] or UNKNOWN, a["os"] or "", a["device"] or UNKNOWN,
                 1 if a["bot"] else 0,
                 a["ua"][:200], f["origin"] or f["path"] or "", f["kind"], f["label"]))
            con.commit()
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - 没盘、库被锁之类，都不该影响用户搜索
        return


# 行为日志的两个种类：点开观看地址 / 点了「详情」按钮
CLICK_KINDS = ("play", "detail")
# 从哪儿点的。观看地址只有 panel（详情面板里）与 card（卡片展开的线路里）；
# hot 只出现在 kind='detail' 上，表示那张海报来自「猜你想搜」
CLICK_PLACES = ("panel", "card", "hot")
CLICK_MAX_URL = 300          # 播放地址常常带一串 token 参数，截断后仍然能认出是哪个站


def click_host(url: str) -> str:
    """取播放地址的域名。聚合按域名看"都点了哪些站"，整条 URL 太碎没法看。"""
    try:
        netloc = urllib.parse.urlsplit(url).netloc
    except ValueError:                       # 畸形 URL 会在 urlsplit 里抛，不能带崩埋点
        return ""
    return netloc.lower()[:120]


def record_click(ip: str, *, url: str = "", kind: str = "play", kw: str = "", title: str = "",
                 src: str = "", src_name: str = "", vid: str = "", line: str = "", ep: str = "",
                 place: str = "card", ua: str = "") -> bool:
    """记一次行为：`play` = 点开了某条观看地址，`detail` = 点了海报上的「详情」按钮。

    `play` 只收 http(s)：这一列的值由前端写，进库后要在后台页面上当链接用，
    `javascript:`/`data:` 混进来就是自己给自己留 XSS。`detail` 本来就没有地址，
    不给 url 是正常情况，不是漏传。长度全部截断，字段没给就留空，不猜。
    写失败不该影响用户点开播放或看到详情 —— 和 record() 一样把异常吞掉。
    """
    kind = kind if kind in CLICK_KINDS else "play"
    url = (url or "").strip()[:CLICK_MAX_URL]
    if kind == "play" and not re.match(r"^https?://", url, re.I):
        return False
    try:
        if not _ready:
            ensure_schema()
        from . import agent, geoip
        a = agent.parse_ua(ua)
        r = geoip.locate(clean_ip(ip) or "")
        pub = r["kind"] == "public"
        now = datetime.now()
        con = connect()
        try:
            con.execute(
                "INSERT INTO clicks (ts, day, ip, kind, kw, title, src, src_name, vid,"
                " line, ep, url, host, place, iso, country, geo, browser, os, device, bot, ua)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (now.strftime("%Y-%m-%d %H:%M:%S"), now.date().isoformat(),
                 clean_ip(ip) or "unknown", kind, (kw or "").strip()[:60],
                 (title or "").strip()[:80], (src or "").strip()[:32],
                 (src_name or "").strip()[:40], (vid or "").strip()[:32],
                 (line or "").strip()[:40], (ep or "").strip()[:40], url,
                 click_host(url), place if place in CLICK_PLACES else "card",
                 r["iso"] if pub else "", r["country"] if pub else "", r["label"],
                 # 与 queries 同一套"认不出来"的写法（见 normalize_agent）
                 a["browser"] or UNKNOWN, a["os"] or "", a["device"] or UNKNOWN,
                 1 if a["bot"] else 0, a["ua"][:200]))
            con.commit()
        finally:
            con.close()
        return True
    except Exception:  # noqa: BLE001
        return False



# 过滤条件白名单：列名要拼进 SQL，只允许这几个值，其余一律拒绝
_COLUMNS = {
    "ip": "ip = ?",
    "kw": "kw LIKE ?",
    "via": "via = ?",
    "geo": "iso = ?",
    "browser": "browser LIKE ?",
    "os": "os LIKE ?",
    "device": "device = ?",
    "ref_kind": "ref_kind = ?",
    # 三档归类：拼的是 WHO_SQL，所以筛值必须在 _ENUMS 里，绝不能让人自由输入
    "who": WHO_SQL + " = ?",
    "day_from": "day >= ?",
    "day_to": "day <= ?",
}
# 这几列的取值来自程序自己写入的集合，筛值不在白名单里就当没填
# （和 geo 一样：静默命中零行比忽略更难查）
_ENUMS = {
    "via": VIA,
    "device": ("手机", "平板", "桌面", "程序", "未知"),
    "ref_kind": ("direct", "site", "search", "out", "other"),
    "place": CLICK_PLACES,
    "kind": CLICK_KINDS,
    "who": WHO_VALUES,
}


def _where(f: dict, cols: dict | None = None) -> tuple[str, list]:
    """按白名单把表单值拼成 WHERE。两张表共用这一份实现：
    明细页现在把搜索与点开放在同一张列表里按时间排，两边的日期、IP、浏览器、
    归属地必须是同一个口径算出来的，各写一份迟早会漂。"""
    conds, params = [], []
    for key, sql in (_COLUMNS if cols is None else cols).items():
        val = (f.get(key) or "").strip() if isinstance(f.get(key), str) else f.get(key)
        if val in (None, ""):
            continue
        if key == "kw":
            conds.append(sql)
            params.append(f"%{val}%")
        elif key in ("browser", "os"):
            # 这两个是自由文本框：输 "Windows" 该能命中 "Windows 10/11"，
            # 所以用模糊匹配；表格里的胶囊传的是精确值，同样命中
            if val == UNKNOWN:
                # 「未知」这个桶要把 NULL 与 '' 一起算上（库里同一含义有三种写法，
                # 见 normalize_agent），否则面板合成一行、点进去却少几行
                conds.append(f"({key} IS NULL OR {key} = '' OR {key} = ?)")
                params.append(val)
            else:
                conds.append(sql)
                params.append(f"%{val}%")
        elif key in ("day_from", "day_to"):
            # 日期一律规整成 YYYY-MM-DD，别让人往 SQL 里塞奇怪东西
            d = _norm_date(val)
            if not d:
                continue
            conds.append(sql)
            params.append(d)
        elif key == "ip":
            ip = clean_ip(val)
            if not ip:
                continue
            conds.append(sql)
            params.append(ip)
        elif key in _ENUMS:
            # 认不出的取值当没填（静默命中零行比忽略更难查）
            if val not in _ENUMS[key]:
                continue
            if key == "device" and val == UNKNOWN:
                # 同 browser：老行是 NULL，新行是 '未知'，一个桶
                conds.append("(device IS NULL OR device = '' OR device = ?)")
                params.append(val)
            else:
                conds.append(sql)
                params.append(val)
        elif key == "geo":
            # 国家码就两位大写字母；'--' 是页面上"内网/保留"那个桶的暗号
            g = str(val).strip().upper()
            if g == "--":
                conds.append("(iso IS NULL OR iso = '')")
            elif len(g) == 2 and g.isalpha():
                conds.append(sql)
                params.append(g)
            else:
                continue
        else:
            conds.append(sql)
            params.append(val)
    return (" AND ".join(conds) or "1=1"), params


def _norm_date(val) -> str:
    """接受 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS，只取日期部分。"""
    s = str(val or "").strip()[:10]
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        return ""


def list_queries(f: dict, page: int = 1, per: int = 50) -> dict:
    """按条件分页取搜索明细（就是合流列表的"只看搜索"那一半，见 list_activity）。"""
    return list_activity(f, page=page, per=per, scope="query")


# 点开行为能过滤的列。日期、IP、关键词、浏览器、系统、设备、归属地这一半
# 与 queries 同名同写法（normalize_clicks 补的就是这几列），所以两张表用的是同一个表单
_CLICK_COLUMNS = {
    "ip": "ip = ?",
    "kw": "kw LIKE ?",
    "geo": "iso = ?",
    "browser": "browser LIKE ?",
    "os": "os LIKE ?",
    "device": "device = ?",
    "who": WHO_SQL + " = ?",
    "day_from": "day >= ?",
    "day_to": "day <= ?",
    "title": "title LIKE ?",
    "src": "src = ?",
    "host": "host = ?",
    "place": "place = ?",
    "kind": "kind = ?",
}


def _where_clicks(f: dict) -> tuple[str, list]:
    """clicks 表的过滤条件。与查询明细共用同一份表单值：
    按某个 IP 或某天筛的时候，两张表筛的是同一批人同一件事，口径得一致。"""
    return _where(f, _CLICK_COLUMNS)


def click_stats(f: dict, top: int = 10) -> dict:
    """观看点击的聚合：总量、独立 IP、按目标域名、按线路来源。"""
    if not _ready:
        ensure_schema()
    where, params = _where_clicks(f)
    con = connect()
    try:
        agg = con.execute(
            f"SELECT COUNT(*) AS n, COUNT(DISTINCT ip) AS ips,"
            f" COUNT(DISTINCT title) AS titles, MIN(ts) AS first_ts, MAX(ts) AS last_ts"
            f" FROM clicks WHERE {where}", params).fetchone()
        by_host = [dict(r) for r in con.execute(
            f"SELECT COALESCE(host,'') AS host, COUNT(*) AS n,"
            f" COUNT(DISTINCT ip) AS ips, COUNT(DISTINCT title) AS titles,"
            f" MAX(day) AS last_day"
            f" FROM clicks WHERE {where} GROUP BY COALESCE(host,'')"
            f" ORDER BY n DESC LIMIT ?", params + [int(top)])]
        by_place = [dict(r) for r in con.execute(
            f"SELECT COALESCE(place,'card') AS place, COUNT(*) AS n"
            f" FROM clicks WHERE {where} GROUP BY COALESCE(place,'card')", params)]
        by_src = [dict(r) for r in con.execute(
            f"SELECT COALESCE(src_name,'') AS name, COUNT(*) AS n,"
            f" COUNT(DISTINCT title) AS titles"
            f" FROM clicks WHERE {where} GROUP BY COALESCE(src_name,'')"
            f" ORDER BY n DESC LIMIT ?", params + [int(top)])]
        # 种类分布（详情 / 观看）单独一份：后台要看的就是这个漏斗 ——
        # 多少人点了详情，其中多少又真去点了观看地址
        by_kind = [dict(r) for r in con.execute(
            f"SELECT COALESCE(kind,'play') AS kind, COUNT(*) AS n,"
            f" COUNT(DISTINCT ip) AS ips, COUNT(DISTINCT title) AS titles"
            f" FROM clicks WHERE {where} GROUP BY COALESCE(kind,'play')", params)]
    finally:
        con.close()
    kinds = {k["kind"]: k["n"] for k in by_kind}
    return {"count": agg["n"] or 0, "ips": agg["ips"] or 0,
            "titles": agg["titles"] or 0, "first_ts": agg["first_ts"],
            "last_ts": agg["last_ts"], "by_host": by_host,
            "by_place": by_place, "by_src": by_src, "by_kind": by_kind,
            "detail": kinds.get("detail", 0), "play": kinds.get("play", 0)}


# 明细页的合流列表：两张表投影成同一套列名，谁没有哪一列就补 NULL。
# 列的次序固定，两个 SELECT 用同一个列表生成，加一列只用改 _ACT_COLS 一处
_ACT_COLS = (
    # 两张表都有
    ("id", "ts", "day", "ip", "kw", "iso", "country", "geo",
     "browser", "os", "device", "bot", "ua", "who"),
    # 只有搜索有：结果数、耗时、入口、Referer
    ("via", "results", "hits", "sources_ok", "sources_total", "ms",
     "ref", "ref_kind", "ref_label"),
    # 只有点开有：点了哪部片、哪条线路、哪个地址
    ("kind", "title", "src", "src_name", "vid", "line", "ep", "url", "host", "place"),
)
_QUERY_HAS = frozenset(_ACT_COLS[0] + _ACT_COLS[1])
_CLICK_HAS = frozenset(_ACT_COLS[0] + _ACT_COLS[2])
# 算出来的列（不是表里的字段）：两张表用同一个表达式，两行的徽章才会说同一种话
_COMPUTED = {"who": WHO_SQL}


def _select_side(has: frozenset) -> str:
    def one(c: str) -> str:
        if c in _COMPUTED:
            return f"{_COMPUTED[c]} AS {c}"
        return c if c in has else f"NULL AS {c}"
    return ", ".join(one(c) for c in sum(_ACT_COLS, ()))


def list_activity(f: dict, page: int = 1, per: int = 50, scope: str = "all") -> dict:
    """搜索记录与点开行为合成一条按时间倒序的活动列表，后台「明细」用的就是它。

    为什么合流而不是「点某条搜索、展开它下面的点击」：点开行为的关键词是前端带的
    片名，从「猜你想搜」的海报点进来的根本没人搜过它 —— 实测 15 条点击按
    (ip, 关键词) 能对上搜索记录的有 0 条，挂在搜索行下面的写法等于一条都看不见。
    两张表本来记的就是同一个人连续的动作，按时间排在一起才对得上。
    `scope`：all=合流 / query=只看搜索 / click=只看点开。
    """
    if not _ready:
        ensure_schema()
    scope = scope if scope in ("all", "query", "click") else "all"
    page = max(1, min(MAX_PAGE, int(page or 1)))
    per = max(1, min(200, int(per or 50)))
    parts, params = [], []
    if scope in ("all", "query"):
        where, wp = _where(f)
        parts.append(f"SELECT {_select_side(_QUERY_HAS)}, 'query' AS type"
                     f" FROM queries WHERE {where}")
        params += wp
    if scope in ("all", "click"):
        where, wp = _where_clicks(f)
        parts.append(f"SELECT {_select_side(_CLICK_HAS)}, 'click' AS type"
                     f" FROM clicks WHERE {where}")
        params += wp
    body = " UNION ALL ".join(parts)
    con = connect()
    try:
        total = con.execute(f"SELECT COUNT(*) FROM ({body})", params).fetchone()[0]
        # 先把页码夹进真实范围再算 offset：否则"第 999 页"会显示成第 1 页却是空的
        pages = max(1, -(-total // per))
        page = min(page, pages)
        rows = con.execute(
            f"SELECT * FROM ({body}) ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?",
            params + [per, (page - 1) * per]).fetchall()
    finally:
        con.close()
    return {"total": total, "page": page, "per": per, "pages": pages,
            "scope": scope, "items": [dict(r) for r in rows]}


def summary(f: dict, top: int = 15) -> dict:
    """同一批过滤条件下的聚合：总量、独立 IP / 关键词、按天、热门关键词、活跃 IP。"""
    if not _ready:
        ensure_schema()
    where, params = _where(f)
    con = connect()
    try:
        agg = con.execute(
            f"SELECT COUNT(*) AS n,"
            f" COUNT(DISTINCT ip) AS ips, COUNT(DISTINCT kw) AS kws,"
            f" SUM(CASE WHEN results = 0 THEN 1 ELSE 0 END) AS empty,"
            f" AVG(sources_ok) AS avg_ok, AVG(ms) AS avg_ms,"
            f" MIN(ts) AS first_ts, MAX(ts) AS last_ts"
            f" FROM queries WHERE {where}", params).fetchone()
        by_day = [dict(r) for r in con.execute(
            f"SELECT day, COUNT(*) AS n, COUNT(DISTINCT ip) AS ips,"
            f" SUM(CASE WHEN results = 0 THEN 1 ELSE 0 END) AS empty"
            f" FROM queries WHERE {where} GROUP BY day ORDER BY day DESC LIMIT 60",
            params)]
        top_kw = [dict(r) for r in con.execute(
            f"SELECT kw, COUNT(*) AS n, MAX(ts) AS last,"
            f" COUNT(DISTINCT ip) AS ips, AVG(results) AS avg_results"
            f" FROM queries WHERE {where} GROUP BY kw ORDER BY n DESC, kw LIMIT ?",
            params + [int(top)])]
        top_ip = [dict(r) for r in con.execute(
            f"SELECT ip, COUNT(*) AS n, COUNT(DISTINCT kw) AS kws,"
            f" MIN(day) AS first_day, MAX(day) AS last_day"
            f" FROM queries WHERE {where} GROUP BY ip ORDER BY n DESC LIMIT ?",
            params + [int(top)])]
        by_via = [dict(r) for r in con.execute(
            f"SELECT via, COUNT(*) AS n FROM queries WHERE {where} GROUP BY via",
            params)]
        # 按归属地聚合：内网/保留的 iso 是空串，合到一行显示成"内网/保留地址"
        by_geo = [dict(r) for r in con.execute(
            f"SELECT COALESCE(iso,'') AS iso, MAX(country) AS country, MAX(geo) AS geo,"
            f" COUNT(*) AS n,"
            f" COUNT(DISTINCT ip) AS ips, COUNT(DISTINCT kw) AS kws,"
            f" MAX(day) AS last_day"
            f" FROM queries WHERE {where} GROUP BY COALESCE(iso,'')"
            f" ORDER BY n DESC LIMIT ?", params + [int(top) + 12])]
        # 三列都按"同一种未知只算一个桶"归一之后再分组：GROUP BY 用列号引用上面
        # 归一好的表达式，免得 SELECT 和 GROUP BY 各写一份、改一处漏一处
        by_browser = [dict(r) for r in con.execute(
            f"SELECT CASE WHEN browser IS NULL OR browser = '' THEN '未知' ELSE browser END"
            f" AS browser,"
            f" COALESCE(os, '') AS os,"
            f" CASE WHEN device IS NULL OR device = '' THEN '未知' ELSE device END"
            f" AS device,"
            f" COUNT(*) AS n, COUNT(DISTINCT ip) AS ips,"
            f" SUM(bot) AS bots"
            f" FROM queries WHERE {where}"
            f" GROUP BY 1, 2, 3 ORDER BY n DESC LIMIT ?",
            params + [int(top)])]
        by_ref = [dict(r) for r in con.execute(
            f"SELECT COALESCE(ref_kind,'direct') AS kind, COUNT(*) AS n,"
            f" COUNT(DISTINCT ip) AS ips, COUNT(DISTINCT ref) AS refs,"
            f" MAX(ref_label) AS example"
            f" FROM queries WHERE {where} GROUP BY COALESCE(ref_kind,'direct')"
            f" ORDER BY n DESC", params)]
        # 来源要能看到具体是哪一页/哪个站，光按 kind 分组信息量不够
        by_ref_src = [dict(r) for r in con.execute(
            f"SELECT COALESCE(ref_label,'直接访问 / 无来源') AS label,"
            f" COALESCE(ref_kind,'direct') AS kind, COUNT(*) AS n,"
            f" COUNT(DISTINCT ip) AS ips, MAX(day) AS last_day"
            f" FROM queries WHERE {where} GROUP BY COALESCE(ref_label,'direct')"
            f" ORDER BY n DESC LIMIT ?", params + [int(top)])]
        # 三档归类：GROUP BY 1 引用上面 SELECT 出来的 who 表达式，口径与筛选、
        # 明细徽章都是同一个 WHO_SQL，不会出现"面板合成一行、点进去却少几行"
        by_who = [dict(r) for r in con.execute(
            f"SELECT {WHO_SQL} AS who, COUNT(*) AS n,"
            f" COUNT(DISTINCT ip) AS ips, COUNT(DISTINCT kw) AS kws,"
            f" MAX(day) AS last_day"
            f" FROM queries WHERE {where} GROUP BY 1 ORDER BY n DESC", params)]
    finally:
        con.close()
    days = [d["day"] for d in by_day if d.get("day")]
    return {
        "count": agg["n"] or 0, "ips": agg["ips"] or 0, "kws": agg["kws"] or 0,
        "empty": agg["empty"] or 0,
        "avg_ok": round(agg["avg_ok"], 2) if agg["avg_ok"] is not None else None,
        "avg_ms": round(agg["avg_ms"]) if agg["avg_ms"] is not None else None,
        "first_ts": agg["first_ts"], "last_ts": agg["last_ts"],
        "span": [min(days), max(days)] if days else [],
        "by_day": by_day,      # 最新的日期在最上面：后台是"今天有没有人用"先看，不是画年报
        "top_kw": top_kw, "top_ip": top_ip, "by_via": by_via, "by_geo": by_geo,
        "by_browser": by_browser, "by_ref": by_ref, "by_ref_src": by_ref_src,
        "by_who": by_who,
    }


# ---- 行为特征：UA 三档只是"它自己说的是什么"，这一节看的是做出来的样子 ----

# 少于这个搜索次数谈不上"节奏"，报了也是 noise；点开比同理
BEHAVIOR_MIN_Q = 3
# 判读理由分两种来源：`ua` 是 UA 自己报的（明细每一行已经有三档徽章，别再重复一遍），
# `act` 是从时间/跳转/点开算出来的行为 —— 往明细的 IP 上挂的只有 `act` 这一类
BEHAVIOR_UA_KEYS = ("ua-bot", "ua-none")
# 判读理由：key 给 CSS 与测试用，text 给人看（行为那一节用全称，因为那节要解释阈值），
# short 给明细的 IP 上挂的小徽章用（那一格里挤不下整句话）。
# 每条都必须可以用页面上那一列的数复核，不做"综合可疑度打分"那种说不清来源的数字。
BEHAVIOR_REASONS = {
    "ua-bot": ("UA 自报脚本", "UA 自己报了爬虫/脚本"),
    "ua-none": ("没留 UA", "有一批请求根本没留 UA，判断不了"),
    "burst": ("秒级连发", "秒级连发（最快间隔 ≤ 1 秒）"),
    "metronome": ("节拍器", "间隔稳得像节拍器（标准差 / 平均值 ≤ 0.25）"),
    "no-ref": ("无站内跳转", "从来不带站内跳转（没有上一页就从没搜过）"),
    "no-click": ("从没点开", "搜了但从没点开过详情或播放地址"),
}


def behavior(f: dict, limit: int = 40) -> list[dict]:
    """按 IP 汇总行为特征，并把能解释的判读理由挂上。

    用的都是库里已有的字段，不额外埋点：`ts` 算相邻间隔与每分钟峰值，
    `ref_kind` 算站内跳转占比，`clicks` 表算点开/搜索比，`bot`/`ua` 走 WHO_SQL 三档。
    标准差 SQLite 没有 `sqrt`（这台的 libsqlite 没编数学函数），所以 SQL 只给
    `n / sum / sumsq`，开方在这里算 —— 这样两边算的是同一批数，不会出现"面板的方差
    与明细的间隔对不上"。
    """
    if not _ready:
        ensure_schema()
    where, params = _where(f)
    cwhere, cparams = _where_clicks(f)
    con = connect()
    try:
        base = {r["ip"]: dict(r) for r in con.execute(
            f"SELECT ip, MAX(geo) AS geo, MAX(country) AS country, COUNT(*) AS n,"
            f" COUNT(DISTINCT kw) AS kws, MAX(day) AS last_day,"
            f" SUM(CASE WHEN ref_kind = 'site' THEN 1 ELSE 0 END) AS site_n,"
            f" SUM(CASE WHEN {WHO_SQL} = 'bot' THEN 1 ELSE 0 END) AS bot_n,"
            f" SUM(CASE WHEN {WHO_SQL} = 'unknown' THEN 1 ELSE 0 END) AS unknown_n"
            f" FROM queries WHERE {where} GROUP BY ip", params)}
        # 相邻间隔：LAG 取上一条的时间，第一行给 NULL，所以 COUNT(gap) 天然比 n 少 1
        for r in con.execute(
                f"WITH gap AS (SELECT ip, strftime('%s', ts)"
                f" - LAG(strftime('%s', ts)) OVER (PARTITION BY ip ORDER BY ts) AS g"
                f" FROM queries WHERE {where})"
                f" SELECT ip, COUNT(g) AS n_gap, MIN(g) AS min_gap, MAX(g) AS max_gap,"
                f" AVG(g) AS avg_gap, SUM(g * g) AS sumsq FROM gap WHERE g IS NOT NULL"
                f" GROUP BY ip", params):
            d = base.get(r["ip"])
            if d:
                d.update(n_gap=r["n_gap"], min_gap=r["min_gap"], max_gap=r["max_gap"],
                         avg_gap=r["avg_gap"], sumsq=r["sumsq"])
        # 一分钟里的峰值：把 "YYYY-MM-DD HH:MM:SS" 截到分钟，纯文本分组，不碰日期函数
        for r in con.execute(
                f"SELECT ip, MAX(c) AS peak_min FROM (SELECT ip, SUBSTR(ts, 1, 16) AS minute,"
                f" COUNT(*) AS c FROM queries WHERE {where} GROUP BY 1, 2) GROUP BY ip", params):
            d = base.get(r["ip"])
            if d:
                d["peak_min"] = r["peak_min"]
        for r in con.execute(
                f"SELECT ip, COUNT(*) AS click_n FROM clicks WHERE {cwhere} GROUP BY ip",
                cparams):
            d = base.get(r["ip"])
            if d:
                d["click_n"] = r["click_n"]
    finally:
        con.close()

    out = []
    for ip, d in base.items():
        d.setdefault("click_n", 0)
        d.setdefault("peak_min", 1)
        # 只有一条搜索的 IP 在上面那几个 GROUP BY 里一行都不返回（LAG 给的是 NULL），
        # 这些都得先补默认值，否则下面按 key 取值直接 KeyError
        for k in ("n_gap", "min_gap", "max_gap", "avg_gap", "sumsq"):
            d.setdefault(k, 0 if k in ("n_gap", "sumsq") else None)
        n_gap, sumsq = d["n_gap"] or 0, d["sumsq"] or 0
        avg = d["avg_gap"] or 0.0
        # 平方和减均值平方可能因为浮点误差给出极小的负数，夹住再开方
        var = max(0.0, sumsq / n_gap - avg * avg) if n_gap else 0.0
        d["sd_gap"] = math.sqrt(var)
        d["cv"] = (d["sd_gap"] / avg) if avg > 0 else None
        d["who"] = ("bot" if d["bot_n"] == d["n"] else
                    "unknown" if d["unknown_n"] == d["n"] else
                    "mixed" if (d["bot_n"] or d["unknown_n"]) else "human")
        reasons = []
        if d["bot_n"]:
            reasons.append("ua-bot")
        if d["unknown_n"]:
            reasons.append("ua-none")
        if n_gap >= 3 and d["min_gap"] is not None and d["min_gap"] <= 1:
            reasons.append("burst")
        if n_gap >= 8 and d["cv"] is not None and d["cv"] <= 0.25:
            reasons.append("metronome")
        if d["n"] >= BEHAVIOR_MIN_Q and not d["site_n"]:
            reasons.append("no-ref")
        if d["n"] >= BEHAVIOR_MIN_Q and not d["click_n"]:
            reasons.append("no-click")
        d["reasons"] = [{"key": k, "short": BEHAVIOR_REASONS[k][0],
                         "text": BEHAVIOR_REASONS[k][1],
                         "src": "ua" if k in BEHAVIOR_UA_KEYS else "act"} for k in reasons]
        out.append(d)
    # 排序按"能举出几条理由"再按条数：理由多的排前面，但都摆着数让人自己复核
    out.sort(key=lambda d: (-len(d["reasons"]), -(d["n"] or 0), d["ip"]))
    return out[:max(1, min(200, int(limit)))]
