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
  这张表记的是"谁的 IP 在什么时候搜了什么"。默认只监听 127.0.0.1，全部 IP 都是
  127.0.0.1；只有配合 --host 0.0.0.0 或 nginx 反代才会有多个客户端 IP。
  所以 stats.db 连同 admin.json 一起进了 .gitignore，不在版本库里分发。
"""
from __future__ import annotations

import ipaddress
import os
import sqlite3
import threading
import time
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
  geo           TEXT,               -- 归属地文案，直接存下来免得每次渲染再算
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
"""

# 老库没有这两列，加列要在建表之后单独补一次（CREATE TABLE IF NOT EXISTS 不会改已有表）
GEO_COLUMNS = (("iso", "TEXT"), ("geo", "TEXT"))
# 浏览器与来源页。这几列只用于分组，不单独建索引：表本来就小，
# 多一个索引就多一个"升级时列还不存在"的失败点（iso 索引就踩过这个坑）
AGENT_COLUMNS = (("browser", "TEXT"), ("os", "TEXT"), ("device", "TEXT"),
                 ("bot", "INTEGER"), ("ua", "TEXT"),
                 ("ref", "TEXT"), ("ref_kind", "TEXT"), ("ref_label", "TEXT"))
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
            con.commit()
            _ready = True
            MIGRATE_ERROR = ""
            if time.time() - _last_prune[0] > 3600:
                _last_prune[0] = time.time()
                cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
                con.execute("DELETE FROM queries WHERE day < ?", (cutoff,))
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
        rows = con.execute("SELECT DISTINCT ip FROM queries WHERE iso IS NULL LIMIT ?",
                           (limit,)).fetchall()
        if not rows:
            return 0
        n = 0
        for (ip,) in rows:
            r = geoip.locate(ip)
            con.execute("UPDATE queries SET iso = ?, geo = ? WHERE ip = ? AND iso IS NULL",
                        (r["iso"] if r["kind"] == "public" else "", r["label"], ip))
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
        a = agent.parse_ua(ua)
        f = agent.parse_ref(referrer, own_hosts)
        now = datetime.now()
        con = connect()
        try:
            con.execute(
                "INSERT INTO queries (ts, day, ip, kw, via, results, hits,"
                " sources_ok, sources_total, ms, iso, geo,"
                " browser, os, device, bot, ua, ref, ref_kind, ref_label)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (now.strftime("%Y-%m-%d %H:%M:%S"), now.date().isoformat(),
                 clean_ip(ip) or "unknown", kw, via if via in VIA else "api",
                 results, hits, sources_ok, sources_total,
                 round(float(ms), 1) if ms is not None else None, iso, geo,
                 a["browser"] or "未知", a["os"], a["device"], 1 if a["bot"] else 0,
                 a["ua"][:200], f["origin"] or f["path"] or "", f["kind"], f["label"]))
            con.commit()
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - 没盘、库被锁之类，都不该影响用户搜索
        return


# 过滤条件白名单：列名要拼进 SQL，只允许这几个值，其余一律拒绝
_COLUMNS = {
    "ip": "ip = ?",
    "kw": "kw LIKE ?",
    "via": "via = ?",
    "geo": "iso = ?",
    "browser": "browser = ?",
    "device": "device = ?",
    "ref_kind": "ref_kind = ?",
    "day_from": "day >= ?",
    "day_to": "day <= ?",
}
# 这几列的取值来自程序自己写入的集合，筛值不在白名单里就当没填
# （和 geo 一样：静默命中零行比忽略更难查）
_ENUMS = {
    "via": VIA,
    "device": ("手机", "平板", "桌面", "程序", "未知"),
    "ref_kind": ("direct", "site", "search", "out", "other"),
}


def _where(f: dict) -> tuple[str, list]:
    conds, params = [], []
    for key, sql in _COLUMNS.items():
        val = (f.get(key) or "").strip() if isinstance(f.get(key), str) else f.get(key)
        if val in (None, ""):
            continue
        if key == "kw":
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
        elif key == "via":
            # 认不出的入口就当没填：过滤条件静默命中零行，比忽略更难查
            if val not in VIA:
                continue
            conds.append(sql)
            params.append(val)
        elif key in ("device", "ref_kind"):
            if val not in _ENUMS[key]:
                continue
            conds.append(sql)
            params.append(val)
        elif key == "browser":
            conds.append(sql)
            params.append(str(val)[:60])
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
    """按条件分页取明细。"""
    if not _ready:
        ensure_schema()
    where, params = _where(f)
    page = max(1, min(MAX_PAGE, int(page or 1)))
    per = max(1, min(200, int(per or 50)))
    con = connect()
    try:
        total = con.execute(f"SELECT COUNT(*) FROM queries WHERE {where}",
                            params).fetchone()[0]
        # 先把页码夹进真实范围再算 offset：否则"第 999 页"会显示成第 1 页却是空的，
        # 页码和内容对不上
        pages = max(1, -(-total // per))
        page = min(page, pages)
        rows = con.execute(
            f"SELECT * FROM queries WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [per, (page - 1) * per]).fetchall()
    finally:
        con.close()
    return {"total": total, "page": page, "per": per, "pages": pages,
            "items": [dict(r) for r in rows]}


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
            f"SELECT COALESCE(iso,'') AS iso, MAX(geo) AS geo, COUNT(*) AS n,"
            f" COUNT(DISTINCT ip) AS ips, COUNT(DISTINCT kw) AS kws,"
            f" MAX(day) AS last_day"
            f" FROM queries WHERE {where} GROUP BY COALESCE(iso,'')"
            f" ORDER BY n DESC LIMIT ?", params + [int(top) + 12])]
        by_browser = [dict(r) for r in con.execute(
            f"SELECT COALESCE(browser,'未知') AS browser, COALESCE(os,'') AS os,"
            f" COALESCE(device,'') AS device, COUNT(*) AS n, COUNT(DISTINCT ip) AS ips,"
            f" SUM(bot) AS bots"
            f" FROM queries WHERE {where} GROUP BY COALESCE(browser,'未知'),"
            f" COALESCE(os,''), COALESCE(device,'') ORDER BY n DESC LIMIT ?",
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
        "by_day": list(reversed(by_day)),      # 画趋势时按时间正序好看
        "top_kw": top_kw, "top_ip": top_ip, "by_via": by_via, "by_geo": by_geo,
        "by_browser": by_browser, "by_ref": by_ref, "by_ref_src": by_ref_src,
    }
