# -*- coding: utf-8 -*-
"""Emby STRM 库：采集结果先落 SQLite，再由库里导出成能刮削的 strm 目录树。

为什么中间必须过一道数据库
  采集是跨天翻页翻出来的（每轮只有几分钟预算），而一部片的多条线路来自不同源、
  不同轮次。要"所有能看的源都挂上去、Emby 播放前能选线路"，就得先把每个源
  各自的 (影片ID -> 线路 -> 集数 -> m3u8) 存住，导出时按片名归并。
  直接边采边写文件会写出半截的库（一部剧只有前两集的 strm），也分不清哪条线是新的。
  顺带的好处：导出变成"库里有什么就写什么"，可以重复跑、只重写变过的那部分。

目录布局（这一节是整个模块的唯一口径，改这里等于改库结构）
  电影   strm/movie/movie01/<片名> (<年份>)/<片名> (<年份>) - <线路名>.strm
  剧集   strm/tv/tv01/<剧名> (<年份>)/Season 01/<剧名> (<年份>) - S01E03 - <线路名>.strm

  为什么是"文件夹名 + 空格横线 + 版本名"：Emby 认多版本的条件是同一条影片的几个文件
  放在同一个文件夹里，而且文件名以文件夹名开头、后面接 " - " 再接版本说明
  （剧集则是 <剧名> - S01E01 - 版本名）；" - " 后面那段就是客户端里选版本时显示的字样。
  写成别的样子（比如把线路名塞在年份前面）会被认成两部影片，海报墙上出现两张
  一模一样的海报，比不合并还糟。所以线路名只写在最后那一段。

为什么"一个 strm 文件"必然要分卷
  一个 strm 只能对应一部影片/一集：Emby 是"扫文件名入库"，文件内容就是一行播放地址。
  所以"近一年全量"是几十万个小文件，不可能塞进一个大 strm。
  分卷（movie01/movie02…、tv01/tv02…）就是目录树上的一层，接口按卷清单暴露
  （见 manifest()），每卷的条目数和取文件的地址都能查到。

  卷号保持稳定：part 表把"某个片名第一次导出时进哪一卷"钉住，新片只往后追加。
  要是每次导出都按片名重排卷号，一部片就会从 movie03 搬到 movie07，
  Emby 那边等于删了又加，播放进度和收藏都可能掉。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

from .hot import kind_of
from .search import clean_text, display_title, title_key

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "zhuiju" / "data"
DB = DATA / "strm.db"
ROOT = BASE / "strm"                       # 导出目录（gitignore；strm 树本身，打包的数据源）
ZIPS = BASE / "strm_zips"                  # 分卷 zip（gitignore；下载接口给的就是这些文件）

KINDS = ("movie", "tv")
KIND_CN = {"movie": "电影", "tv": "电视剧"}
# 一部"电影"如果某条线路给了超过这个数的集，那就是站点把剧标错分类（实测有），
# 改按剧集布局导出 —— 按电影布局只会留一集，整部剧就丢了。
MOVIE_EP_MAX = 3

# ------------------------------------------------------------------ 设置（strm.db 的 setting 表）
# key -> (中文标签, 最小值, 最大值, 默认值)。后台表单、校验、测试都从这里取，避免三处各写一份。
# window_days 上限 1095 = 三年：上游更新流翻到第三年就是上万页，再宽没意义。
SPEC: dict[str, tuple] = {
    "enabled": ("启用每日采集", 0, 1, 1),
    "window_days": ("采集时间范围（天）", 7, 1095, 365),
    "m3u8_only": ("只要 m3u8 直连线路", 0, 1, 1),
    "max_lines_per_src": ("每个源最多保留几条线路", 1, 8, 1),
    "max_eps_per_title": ("每部剧最多导出几集", 1, 2000, 120),
    # 每卷按"文件数"切：实测 3 个源翻 111 页就写出 1.75 万个 strm（一部 60 集的剧
    # × 8 个源就是 480 个文件），一年窗口 ×17 个源是百万级。3000 个一卷会切出几百卷，
    # 包数量比包大小更难受；strm 是纯文本一行地址，2 万个文件的包也就 1MB 上下。
    "part_files": ("每卷最多几个 strm 文件", 200, 200000, 20000),
    # 默认不带：解压到媒体库根就直接是「片名 (年份)/…」，和 Emby 一个文件夹一部片的
    # 常规布局对齐；想按卷整目录删除的人可以打开这一项。
    "zip_part_dir": ("包内带卷号目录（movie01/…）", 0, 1, 0),
    # 每个 strm 旁边一份**同名** .nfo（用户点名要的形态：`x.strm` 配 `x.nfo`），
    # 剧集另外在剧集根目录补一份 tvshow.nfo —— 系列级的 ID 只能写在那儿。
    "write_nfo": ("每个 strm 旁边写一份同名 NFO", 0, 1, 1),
    # 目录名里的 ID 标签：Emby 认 tmdbid（要拿 key 去 TMDB 查），豆瓣插件/MoviePilot
    # 认 doubanid（上游就有，不用查，但只有约一成条目带得上）。两颗开关分开，
    # 因为"要不要为刮削多打一个第三方接口"是你那边的网络说了算，不该我替你定。
    "tag_douban_id": ("目录名带上游豆瓣号 [doubanid=…]", 0, 1, 0),
    "tag_tmdb_id": ("目录名带 TMDB 号 [tmdbid=…]", 0, 1, 0),
    "tmdb_api_key": ("TMDB API Key（v3）", 0, 0, ""),
    "tmdb_host": ("TMDB 接口地址", 0, 0, "https://api.tmdb.org/3"),
    "tmdb_per_round": ("每轮最多查几部（TMDB）", 0, 2000, 120),
    "budget_seconds": ("每轮采集时间预算（秒）", 60, 7200, 900),
    "delay_ms": ("每次请求间隔（毫秒）", 0, 5000, 400),
    "workers": ("同时翻几个源", 1, 8, 3),
    "min_interval_minutes": ("两次采集至少间隔（分钟）", 1, 1440, 30),
    "exclude_srcs": ("不参与采集的源（id，逗号分隔）", 0, 0, ""),
}

# 页面上每一项后面那句解释。写在这里而不是写在模板里：
# 上下界和说明必须同源，否则改了 SPEC 的界、页面还在教人按旧的数填。
SPEC_HELP = {
    "enabled": "关掉后访问网站不再自动拉起采集；已采到的数据、已写出的文件和分卷包都留着。",
    "window_days": "只收这个时间范围内**出品**的片子（按上游的出品年份判，不是按更新时间）。"
                   "改小了要按一次「全量重建」，不然旧窗口采进来的还留在库里。",
    "m3u8_only": "只收 .m3u8 直连地址。关掉会连 HTML 播放器页一起收，"
                 "那种地址 Emby 点开来是没有画面的，文件数还会翻倍。",
    "max_lines_per_src": "一个源留几条线路。多数站每条影片给两条（一条 m3u8、一条网页页），"
                         "只留一条时版本名里就不带线路名。",
    "max_eps_per_title": "一部剧最多导出几集。番剧常年上千集（实测备番有 8000 多页），"
                         "不设上限时一部片就能撑爆一卷。",
    "part_files": "每卷最多几个 strm 文件，决定要分成多少个卷（movie01、movie02… / "
                  "tv01、tv02…）。太大 Emby 一次扫描吃不下，太小卷的数量不好看。",
    "zip_part_dir": "关掉（默认）时包里就是 `片名 (年份)/…`，几卷一起解压到媒体库根正好拼成一棵树；"
                    "打开后多一层卷号目录 `movie01/片名 (年份)/…`，好处是"
                    "\"这一卷不要了\"能整目录删掉。改这里会重打所有卷；"
                    "已经解压过的先别改——旧路径那套还留在库里，同一部片会出现两次。",
    "tag_douban_id": "在片名目录末尾加一段 ` [doubanid=38185414]`。号是上游给的，"
                     "不用联网查，但实测**只有约一成条目带得上**（11706 行里 548 行）。"
                     "注意 Emby 本体不认这个标签，只认 tmdbid/imdbid/tvdbid —— "
                     "这一项是给豆瓣刮削插件、MoviePilot 那类工具用的。",
    "tag_tmdb_id": "在片名目录末尾加一段 ` [tmdbid=157336]`，Emby 读到就直接按 ID 命中，"
                   "不再拿片名去搜（同名翻拍片、只有年份的片子最容易认错）。"
                   "ID 不在上游数据里，得拿 TMDB 接口查，所以下面两个空着时这颗开关等于没用。"
                   "查不到的那部分照旧只写`片名 (年份)`，不会硬塞一个猜来的号。",
    "tmdb_api_key": "TMDB 网站 → 设置 → API → 开发者 Key（v3，32 位十六进制那种）。"
                    "只存在 strm.db 的 setting 表里、不外发，页面上也不回显（留空就是不改）。"
                    "服务器上也可以不设这里、改用环境变量 `ZHUIJU_TMDB_KEY`；两边都有时以这里为准。",
    "tmdb_host": "TMDB 接口根地址，一般不用改。默认 `https://api.tmdb.org/3` —— "
                 "实测 `api.themoviedb.org` 在这台机器上连不上（TCP 直接超时），"
                 "而这一个是通的（回 401，说明只差 key）。"
                 "换你那边能出去的那个域名。",
    "tmdb_per_round": "一轮采集里最多查几部。一部片一次请求，查过的（命中或确认没有）"
                      "不再重查，所以这个数字只影响「新片多时这一轮多跑几分钟」。"
                      "库里 4312 部全查一遍约 4300 次请求，按 400ms 间隔是半小时多。",
    "budget_seconds": "一轮采集最多跑多久。近一年全量一轮跑不完是设计内的，"
                      "预算用完就停，下一次访问接着翻。",
    "delay_ms": "每个请求之间睡多久（各源分别算）。调到 0 就是贴着上游打，不建议。",
    "workers": "同时翻几个源。这是唯一会让上游同时挨几路请求的参数。",
    "min_interval_minutes": "两次自动采集至少隔多久。一轮跑不完时靠它决定推进节奏。",
    "exclude_srcs": "填采集源的 id（逗号分隔），这些源从这一轮起不再采；"
                    "库里已经采到的先留着，要清干净就按一次全量重建。",
}


# 文本型设置：不能用"上下界"去判类型（exclude_srcs 的界是 0/0，会被误判成开关）
TEXT_KEYS = ("exclude_srcs", "tmdb_api_key", "tmdb_host")
# 页面上要按密码框显示的（TMDB key 是账号级凭据，别在表单里明文回显）
SECRET_KEYS = ("tmdb_api_key",)


def spec_rows(cfg: dict | None = None) -> list[dict]:
    """给后台表单的一行行描述（顺序就是 SPEC 的定义顺序，控件类型也在这里判）。"""
    cfg = cfg or settings()
    rows = []
    for k, (label, lo, hi, default) in SPEC.items():
        kind = ("text" if k in TEXT_KEYS
                else "bool" if hi <= 1 else "int")
        secret = k in SECRET_KEYS
        rows.append({"key": k, "label": label,
                     # 密钥不回显：页面源码里放一份明文凭据是最容易漏的那种泄露
                     # （旁边那台机器可能正开着浏览器）。留空 = 不改，见 save_settings
                     "value": "" if secret else cfg[k],
                     "filled": bool(str(cfg[k] or "").strip()) if secret else False,
                     "lo": lo, "hi": hi,
                     "default": default, "kind": kind, "help": SPEC_HELP.get(k, ""),
                     "secret": secret})
    return rows


# TMDB key：字母数字和 - 这几种，别的字符（空格、引号、换行）一律不收。
# 不收紧一点的理由和当年判"本站对外地址"一样 —— 这串要拼进请求 URL 打到第三方。
KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")
HOST_RE = re.compile(r"^https?://[A-Za-z0-9._\-]+(:\d{1,5})?(/[A-Za-z0-9._/\-]*)?$")


def clean_host(raw: str) -> str:
    """校验 TMDB 接口根地址：只收 http(s)://主机[:端口][/路径]，去掉结尾斜杠。"""
    s = str(raw or "").strip().rstrip("/")
    if not s:
        return ""
    return s if HOST_RE.match(s) else ""


_init_lock = threading.Lock()
_ready = False

SCHEMA = """
-- 每个源每条影片一行（采集原始结果）。lines 存拆好的线路 JSON：
-- 导出时不再联网、也不再解析上游那种 $$$ / # / $ 三层拼接串。
CREATE TABLE IF NOT EXISTS vod (
  src        TEXT NOT NULL,       -- 采集源 id
  vid        TEXT NOT NULL,       -- 该源里的影片 ID
  src_name   TEXT NOT NULL,
  key        TEXT NOT NULL,       -- 归一化片名（跨源合并的钥匙，见 search.title_key）
  title      TEXT NOT NULL,
  year       TEXT,
  kind       TEXT,                -- movie / tv；''（认不出类别的）不进库
  type_name  TEXT,
  remarks    TEXT,                -- 上游"更新至第几集"那行，分卷清单接口里直接给出去
  pic        TEXT,                -- 上游海报原图地址：NFO 的 thumb 与 /api/strm/index 都用它
  douban_id  TEXT,                -- 上游豆瓣号：目录名里那个 [doubanid=…] 与 NFO 的 uniqueid
  blurb      TEXT,                -- 简介（vod_blurb，空时退 vod_content）：NFO 的 plot
  actor      TEXT,
  director   TEXT,
  area       TEXT,
  douban_score TEXT,              -- 上游评分：实测多数填 0.0，0 不当"有分"
  updated    TEXT,                -- 上游 vod_time（更新时间）
  pubdate    TEXT,                -- 上游 vod_pubdate（上映日期，实测形如 "2026-10-09中国大陆"）
  lines      TEXT NOT NULL,       -- [{from, eps:[{name,url}]}]
  url_count  INTEGER NOT NULL DEFAULT 0,
  m3u8_count INTEGER NOT NULL DEFAULT 0,
  sig        TEXT NOT NULL,       -- lines 的短哈希：变了才标脏、才重写 strm
  msig       TEXT,                -- 元数据的短哈希：变了只重写 NFO，不算"翻到新片"
  dirty      INTEGER NOT NULL DEFAULT 0,
  pass       INTEGER NOT NULL DEFAULT 0,   -- 最近在哪一轮采集里见到它
  first_seen TEXT,
  last_seen  TEXT,
  PRIMARY KEY (src, vid)
);
CREATE INDEX IF NOT EXISTS idx_vod_key  ON vod(key);
CREATE INDEX IF NOT EXISTS idx_vod_dirty ON vod(dirty);

-- 片子 -> 外部元数据站点的 ID。目录名里那个 [tmdbid=…] 就取这张表。
-- 为什么不并进 vod：vod 是"每个源一行"，同一部片在 17 个源里最多 17 行，
-- 而 ID 是片子级的 —— 跟着源走既重复存，又会出现"三个源给三个不同豆瓣号"没法判。
-- key 就是 vod.key（跨源合并的那把钥匙）。豆瓣号不在这里存：它上游就有，
-- 导出时直接从 vod 里取众数（见 merged_versions），存两份反而会对不上。
-- state 记的是**查询结论**：'' 没查过 / ok 命中 / none 查过确实没有 / bad 没查成
-- （key 不对、超时、被限流）。none 和 bad 必须分开：前者不该再打第二次，
-- 后者下次还得接着试（tries 封顶，免得一个永远修不好的 key 每轮白打）。
CREATE TABLE IF NOT EXISTS idmap (
  key        TEXT PRIMARY KEY,
  kind       TEXT NOT NULL,
  title      TEXT,
  year       TEXT,
  tmdb_id    TEXT,
  state      TEXT NOT NULL DEFAULT '',
  reason     TEXT,
  tries      INTEGER NOT NULL DEFAULT 0,
  checked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_idmap_state ON idmap(state);

-- 翻页游标：慢速采集的断点。一轮预算用完，下次从这一页接着翻。
CREATE TABLE IF NOT EXISTS cur (
  src        TEXT PRIMARY KEY,
  pg         INTEGER NOT NULL DEFAULT 1,
  done       INTEGER NOT NULL DEFAULT 0,   -- 1 = 这一轮不用再翻了
  stop       TEXT,                          -- 停下来的原因，见 collect 里那三个常量
  pass       INTEGER NOT NULL DEFAULT 0,   -- 游标属于哪一轮
  last_time  TEXT,                          -- 游标那一页最新的 vod_time
  known      INTEGER NOT NULL DEFAULT 0,   -- 连续几页"全是老片且没变"
  backfill   INTEGER NOT NULL DEFAULT 0,   -- 1 = 这个源已经完整翻出过窗口，之后可以增量早停
  requests   INTEGER NOT NULL DEFAULT 0,   -- 本 pass 该源已发多少请求
  updated_at TEXT
);

-- 片名 -> 第几卷。钉住不动，新片往后追加，避免 Emby 库里同一部片换路径。
CREATE TABLE IF NOT EXISTS part (
  key    TEXT NOT NULL,
  kind   TEXT NOT NULL,
  part   INTEGER NOT NULL,
  PRIMARY KEY (key, kind)
);

-- 已经写出去的文件：用来做"内容没变就不重写"和"这条没了就把文件删掉"
CREATE TABLE IF NOT EXISTS file (
  path       TEXT PRIMARY KEY,   -- 相对 strm/ 的 posix 路径，形如 movie/movie01/x/x.strm
  kind       TEXT NOT NULL,
  part       INTEGER NOT NULL,
  key        TEXT NOT NULL,
  sig        TEXT NOT NULL,
  bytes      INTEGER,
  written_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_file_key  ON file(key);
CREATE INDEX IF NOT EXISTS idx_file_kind ON file(kind, part);

-- 分卷 zip：一卷一个包，是下载接口真正给出去的东西。
-- sig 是"这一卷的文件清单+每个文件的内容哈希"合起来的短哈希，没变就不重打包
-- （zip 的 mtime 一动，Emby 那边不算变化，但同步脚本会白拷一遍）。
CREATE TABLE IF NOT EXISTS zip (
  kind     TEXT NOT NULL,
  part     INTEGER NOT NULL,
  path     TEXT NOT NULL,    -- strm_zips/ 下的文件名本身（movie01.zip）：
                             -- 存相对项目根的路径会让"包在哪儿"跟着 BASE 走，
                             -- 输出目录被指到别的盘时就错到另一个盘上去
  files    INTEGER NOT NULL,
  titles   INTEGER NOT NULL,
  bytes    INTEGER NOT NULL,
  sig      TEXT NOT NULL,
  built_at TEXT,
  PRIMARY KEY (kind, part)
);

-- 每轮采集/导出的结果：后台页与 /api/strm/manifest 都从这里取"上次跑得怎么样"
CREATE TABLE IF NOT EXISTS run (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  kind          TEXT NOT NULL,     -- collect / export
  started_at    TEXT,
  finished_at   TEXT,
  seconds       REAL,
  srcs          INTEGER,
  requests      INTEGER,
  pages         INTEGER,
  rows_new      INTEGER,
  rows_changed  INTEGER,
  files_written INTEGER,
  files_skipped INTEGER,
  files_removed INTEGER,
  note          TEXT
);

CREATE TABLE IF NOT EXISTS setting (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

# 后加的列：CREATE TABLE IF NOT EXISTS 不会改已有表，老库要单独补一次
# （和 stats.py 同一套路）。补不上也不能把站点挡下来，记进 MIGRATE_ERROR 让后台能说清。
# 语义分工要说清：sig 只管**播放地址**（决定"这一页是不是新内容"，采集的早停靠它），
# msig 只管**元数据**（简介/演员/豆瓣分变了只该让 NFO 重写，不该让采集以为翻到了新片）。
EXTRA_COLUMNS = (("vod", "pubdate", "TEXT"),
                 ("vod", "douban_id", "TEXT"),
                 ("vod", "blurb", "TEXT"), ("vod", "actor", "TEXT"),
                 ("vod", "director", "TEXT"), ("vod", "area", "TEXT"),
                 ("vod", "douban_score", "TEXT"), ("vod", "msig", "TEXT"))
MIGRATE_ERROR = ""


def ensure_columns(con) -> None:
    for table, col, typ in EXTRA_COLUMNS:
        have = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
        if col not in have:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def connect() -> sqlite3.Connection:
    """短连接 + WAL：和 stats.py 同一套路，开发服务器是多线程的，不共享 connection。"""
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB), timeout=8)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=6000")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def ensure_schema() -> None:
    global _ready, MIGRATE_ERROR
    if _ready:
        return
    with _init_lock:
        if _ready:
            return
        con = connect()
        try:
            con.executescript(SCHEMA)
            try:
                ensure_columns(con)
            except sqlite3.Error as exc:
                # 补列失败不抛：站点和采集都还能跑，只是"按上映日期判窗口"会退到按年份判。
                # 但要说得出来 —— 记进 MIGRATE_ERROR，后台那一行会显示它
                MIGRATE_ERROR = f"{type(exc).__name__}: {exc}"[:160]
            con.commit()
        finally:
            con.close()
        _ready = True


# ------------------------------------------------------------------------------- 设置
def settings() -> dict:
    """全部设置；库里缺的按 SPEC 默认补齐，整数键统一转好。"""
    ensure_schema()
    raw = {}
    con = connect()
    try:
        raw = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM setting")}
    finally:
        con.close()
    out = {}
    for k, (_label, _lo, _hi, default) in SPEC.items():
        v = raw.get(k)
        if k in TEXT_KEYS:
            out[k] = str(v if v is not None else default)
            if k == "tmdb_api_key" and not out[k].strip():
                # 服务器上更常用的放法：写在服务的环境变量里，不落到库、也不出现在页面上
                out[k] = os.environ.get("ZHUIJU_TMDB_KEY", "").strip()
            continue
        try:
            out[k] = int(default if v in (None, "") else int(str(v)))
        except ValueError:
            out[k] = int(default)
    return out


def save_settings(pairs: dict) -> tuple[dict, str | None]:
    """校验并保存后台表单，返回（生效设置, 错误说明）。有一条非法就整份不写，
    免得"时间范围存了、每卷上限没存"这种半套设置导出出一棵奇怪的树。"""
    ensure_schema()
    cur = settings()
    errs: list[str] = []
    nxt = dict(cur)
    for k, (label, lo, hi, default) in SPEC.items():
        if k not in pairs:
            continue
        raw = str(pairs.get(k) or "").strip()
        if k == "exclude_srcs":
            # 源 id 就是 [a-z0-9_-] 这个形状；空格和奇怪字符不进库，免得拼 SQL/比 id 时出岔子
            ids = [x for x in re.split(r"[,\s]+", raw.lower())
                   if re.fullmatch(r"[a-z0-9_-]{1,32}", x)]
            nxt[k] = ",".join(dict.fromkeys(ids))
            continue
        if k == "tmdb_api_key":
            key = raw.strip()
            if not key:
                # 页面上这一栏不回显已存的值，所以"留空"只能是"不改"——
                # 存成空串等于按一次保存就把 key 擦了，而人不会想到是这么没的
                nxt[k] = cur[k]
                continue
            if not KEY_RE.match(key):
                errs.append(f"「{label}」看着不像 TMDB 的 key（只要字母、数字、- 或 _，8~64 位）")
                continue
            nxt[k] = key
            continue
        if k == "tmdb_host":
            h = clean_host(raw)
            if raw and not h:
                errs.append(f"「{label}」要写成 https://api.tmdb.org/3 这样（不能带空格或引号）")
                continue
            # 留空回默认值而不是存空串：空串拼不出请求地址，TMDB 那颗开关会变成
            # "看着开了、其实一部都没查"这种最难查的状态
            nxt[k] = h or str(SPEC[k][3])
            continue
        # 开关型（上下界 0/1）的复选框：浏览器在"没勾"的时候**根本不发这个字段**，
        # 而后台表单也可能传 "off" —— 两种都得认成 0。
        # 上一版写的是"空值就退回默认值"，于是把 m3u8_only 的默认 1 又填回去，
        # 结果"关掉只要 m3u8"这颗开关怎么关都关不上。
        is_bool = hi <= 1
        if raw.lower() in ("on", "true", "yes", "1"):
            raw = "1"
        elif raw.lower() in ("off", "false", "no", ""):
            raw = "0" if is_bool else str(default)
        try:
            v = int(raw)
        except ValueError:
            errs.append(f"「{label}」要填整数")
            continue
        if lo != hi and not (lo <= v <= hi):
            errs.append(f"「{label}」要在 {lo}～{hi} 之间（填的是 {v}）")
            continue
        nxt[k] = v
    if errs:
        return cur, "；".join(errs)
    # 采集/导出正在写同一个库时，SQLite(WAL) 一次只允许一个写者。
    # 这里必须重试而不是让它冒 500：后台点"保存设置"点在一个正在打包的导出上，
    # 是完全正常的时间点（实测就是在这里报了 database is locked 把整页炸了）。
    last: str = ""
    for attempt in range(6):
        try:
            con = connect()
            try:
                for k in SPEC:
                    con.execute("INSERT INTO setting(key, value) VALUES(?, ?)"
                                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                (k, str(nxt[k])))
                con.commit()
            finally:
                con.close()
            return nxt, None
        except sqlite3.OperationalError as exc:
            last = f"{type(exc).__name__}: {exc}"
            if "locked" not in str(exc) and "busy" not in str(exc):
                break
            time.sleep(0.4 + attempt * 0.4)      # 最长等 6 次 ≈ 8 秒
    return cur, f"没写进去：采集/导出正在占用数据库（{last[:80]}），稍等一下再保存"


def cutoff(cfg: dict | None = None) -> date:
    cfg = cfg or settings()
    return date.today() - timedelta(days=int(cfg["window_days"]))


PUB_RE = re.compile(r"(19|20)(\d{2})(?:[-/.]\s*(\d{1,2})(?:[-/.]\s*(\d{1,2}))?)?")


def pub_date(vod: dict) -> tuple[date | None, int]:
    """上游的 vod_pubdate -> (精确日期或 None, 年份或 0)。

    实测写法是"日期 + 国家/地区"直接连着写（`2026-10-09中国大陆`、`2025美国`），
    所以只能剥前缀、不能整个字符串解析。带月份的能判到"天"，只给年份的退到判"年"。
    """
    s = clean_text(vod.get("vod_pubdate", ""))
    m = PUB_RE.search(s or "")
    if not m:
        return None, 0
    year = int(f"{m.group(1)}{m.group(2)}")
    if year < 1900 or year > date.today().year + 3:
        return None, 0                       # 明显填错的（9999、0000）当没有
    try:
        if m.group(3) and m.group(4):
            return date(year, int(m.group(3)), int(m.group(4))), year
    except ValueError:
        pass                                 # 2026-02-31 这种，退到只认年份
    return None, year


def in_window(vod: dict, since: date) -> bool:
    """这条算不算"近 N 年出品"。判据从准到粗依次是：
    完整上映日期 -> 上映年份 -> vod_year -> 上游更新时间。

    为什么留这么多级：窗口只有 90/180 天时，"只认年份"会立刻失真 ——
    一年窗口下 `年份 >= 去年` 差不多就是"近一年"，
    但把窗口调到 180 天，`年份 >= 今年` 就把今年上半年的片子全否掉了。
    有了 vod_pubdate 就能真的按日期判，只有它缺失才退到年份。
    """
    pd, py = pub_date(vod)
    if pd:
        return pd >= since
    if py:
        return py >= since.year
    y = re.search(r"(19|20)\d{2}", clean_text(vod.get("vod_year", "")))
    if y:
        return int(y.group(0)) >= since.year
    return clean_text(vod.get("vod_time", ""))[:10] >= since.isoformat()


def excluded(cfg: dict | None = None) -> set[str]:
    cfg = cfg or settings()
    return {x for x in re.split(r"[,\s]+", str(cfg.get("exclude_srcs") or "")) if x}


# --------------------------------------------------------------------- 上游线路与集数解析
_M3U8 = re.compile(r"\.m3u8(\?|#|$)", re.I)
SEASON_RE = re.compile(r"[Ss](?:eason)?\s*(\d{1,2})\s*[-_.Ee]\s*(\d{1,4})")
EP_WORD_RE = re.compile(r"^[\s【\[]*(?:第|EP|E|P)?\s*(\d{1,4})\s*[集话話期章回]\s*[\]】]?$")
NUM_RE = re.compile(r"(?<!\d)(\d{1,4})(?!\d)")
DATE_RE = re.compile(r"(20\d{2})[-./年]\s*(\d{1,2})[-./月]\s*(\d{1,2})")
MOVIE_WORDS = re.compile(r"^(?:正片|HD|BD|TC|TS|HD中字|清晰版|全集|完整版|预告片?|未删减|加长版)$")
NOISE_TAIL = re.compile(r"(?:\[|\s)(?:HD|BD|4K|1080P|720P|预览|无删减|加长版)\s*\]?\s*$", re.I)
BADFN = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
TRAILING = re.compile(r"[.\s]+$")


def is_playable(url: str, m3u8_only: bool = True) -> bool:
    """能不能进 strm：必须是 http(s) 绝对地址；m3u8_only 时还要真的是 m3u8 直连。

    为什么默认只收 m3u8：实测 17 个源里，多数站每条影片给两条线路，一条是
    `https://play.xxx.com/play/abcd`（HTML 播放器页，Emby 拿它取不到流），
    另一条才是 `https://play.xxx.com/play/abcd/index.m3u8`。
    两条都收的话，Emby 里一半版本点了没画面，文件数还直接翻倍。
    """
    u = (url or "").strip()
    if not u.lower().startswith(("http://", "https://")):
        return False
    return bool(_M3U8.search(u)) if m3u8_only else True


def split_lines(vod: dict, m3u8_only: bool = True, max_lines: int = 1) -> list[dict]:
    """vod_play_url / vod_play_from -> [{from, eps:[{name,url}]}]，只留可播的。

    上游拼接规则（实测 17 个源一致）：`$$$` 分线路、`#` 分集、`$` 分「集名/地址」。
    线路名那一段分隔符不统一（`$$$` 或 `,`），块数对不上时退成"线路N"——
    不能硬按位置配，配错了会把 A 线的地址挂到 B 线的名字上。
    """
    blocks = [b for b in str(vod.get("vod_play_url") or "").split("$$$") if b.strip()]
    raw_from = str(vod.get("vod_play_from") or "")
    froms = [clean_text(f) for f in re.split(r"\$\$\$|,", raw_from) if clean_text(f)]
    if len(froms) != len(blocks):
        froms = []
    out = []
    for i, block in enumerate(blocks):
        eps = []
        for piece in block.split("#"):
            if not piece.strip():
                continue
            name, _, addr = piece.partition("$")
            addr = addr.strip()
            if not addr or not is_playable(addr, m3u8_only):
                continue
            eps.append({"name": clean_text(name) or f"第{len(eps) + 1}集", "url": addr})
        if eps:
            out.append({"from": (froms[i] if i < len(froms) else f"线路{i + 1}"), "eps": eps})
    # 集最全的线路排前面：只留 max_lines 条时，留下的应该是能看完的那条
    out.sort(key=lambda l: -len(l["eps"]))
    return out[:max(1, int(max_lines))]


def season_hint(title: str, type_name: str = "") -> int:
    """从片名/分类里认季号：《庆余年 第二季》-> 2。认不出算第 1 季。

    只用于命名，不参与跨源合并：同一部剧的不同季在上游本来就是两条 vod（片名也不同），
    硬并成"第一季到第 40 集"会让 Emby 的季页面全对不上。
    """
    s = f"{title} {type_name}"
    m = re.search(r"第\s*([一二三四五六七八九十百\d]{1,3})\s*季", s)
    if m:
        num = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
               "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}.get(m.group(1))
        if num is None:
            try:
                num = int(m.group(1))
            except ValueError:
                num = None
        if num:
            return num
    m = re.search(r"[Ss]eason\s*(\d{1,2})", s)
    return int(m.group(1)) if m else 1


def parse_ep(name: str, index: int, season: int) -> tuple[int, int]:
    """选集名 -> (季, 集)。试的顺序有讲究：

    先完整季集（S01E03 / Season 1 Ep3），再"第N集 / EP N / N话"，
    再日期写法（2026-10-12 期，综艺常见 —— 这一判必须放在"纯数字"之前，
    否则整个综艺会被认成 S01E2026 这种根本不存在的东西），
    再纯数字，最后退到出现顺序。宁可退化成序号，也别把整集丢掉。
    """
    s = clean_text(name)
    if not s:
        return season, index
    m = SEASON_RE.search(s)
    if m and 1 <= int(m.group(2)) <= 5000:
        return (int(m.group(1)) or season), int(m.group(2))
    m = EP_WORD_RE.match(s)
    if m:
        return season, int(m.group(1))
    if DATE_RE.search(s):
        return season, index
    if MOVIE_WORDS.match(s):
        return season, 1
    m = NUM_RE.search(s)
    if m and 1 <= int(m.group(1)) <= 5000:
        return season, int(m.group(1))
    return season, index


def safe(seg: str, limit: int = 70) -> str:
    """Windows/Linux 通吃的路径片段。

    这些片名最后要落到磁盘上，而科室那边的机器是 Windows：`:` `/` `?` 直接报错，
    结尾的点号或空格会让资源管理器把名字吃掉（"A." 变成 "A"），
    中文名再套两层目录容易撞 MAX_PATH 260。所以统一清洗 + 截断。
    """
    s = BADFN.sub(" ", clean_text(str(seg or ""))).strip()
    s = NOISE_TAIL.sub("", s).strip()
    s = TRAILING.sub("", s).strip()
    if len(s) > limit:
        s = s[:limit].rstrip()
        s = TRAILING.sub("", s).strip()
    return s or "未命名"


def folder_title(title: str, year: str) -> str:
    """`片名 (年份)` —— 年份是刮削的关键：没有它 Emby 全靠片名猜，
    同名翻拍片（实测《毒液》就有两条）会挂到同一张海报上。"""
    y = re.search(r"(19|20)\d{2}", str(year or ""))
    return f"{safe(title)} ({y.group(0)})" if y else safe(title)


def id_tag(item: dict, ids: dict | None, cfg: dict) -> str:
    """目录名末尾那一个 ID 标签；没开或查不到就是空串。

    Emby 官方只认 `tmdbid` / `imdbid` / `tvdbid` 三种标签（`=` 和 `-` 两种分隔都认，
    见 emby.media 的 Movie Naming / TV Naming），**豆瓣号它本体不认** ——
    `[doubanid=…]` 只有装了豆瓣刮削插件或用 MoviePilot 那类工具才吃，
    所以那一颗开关默认关着，别指望 Emby 靠它命中。
    两个开关都开且两个号都有时只写 tmdbid：标签是拿来"绕过名称搜索"的，
    一个够了，写两个只会把文件名往 MAX_PATH 那边推。
    """
    if cfg.get("tag_tmdb_id", 0):
        tmdb = str((ids or {}).get("tmdb_id") or "").strip()
        if tmdb:
            return f" [tmdbid={safe(tmdb, 24)}]"
    if cfg.get("tag_douban_id", 0):
        db = str(item.get("douban_id") or "").strip()
        if db:
            return f" [doubanid={safe(db, 24)}]"
    return ""


def version_label(src_name: str, line_from: str, need_line: bool) -> str:
    """Emby 版本下拉框里显示的字样。

    一个源通常只留一条 m3u8 线路，那就直接写源名（"虎牙资源"）；
    关掉"只要 m3u8"、或一个源留了多条线路时，得把线路名带上，
    否则客户端里两个同名版本分不出谁是谁。
    """
    a = safe(src_name, 24)
    return a if not need_line else f"{a}·{safe(line_from, 16)}"


def sig_of(lines: list[dict]) -> str:
    body = json.dumps([{"f": l["from"], "e": [(x["name"], x["url"]) for x in l["eps"]]}
                       for l in lines], ensure_ascii=False, sort_keys=True)
    return hashlib.md5(body.encode("utf-8")).hexdigest()[:16]


# 元数据字段：全部来自上游 videolist 一次请求，不需要额外联网
META_LIMITS = {"blurb": 400, "actor": 200, "director": 80, "area": 40,
               "douban_id": 16, "douban_score": 8}


def _cut_sentence(text: str, limit: int) -> str:
    """截到 limit 字以内，并尽量停在整句上。

    实测直接按字数切会断成"在命运与时间的交织"这种半句，写进 NFO 里看着像坏数据；
    所以先切够，再回退到最后一个句末标点（找不到就照原样截，不能为了找标点把
    整段 400 字都吐出去）。
    """
    s = str(text or "").strip()
    if len(s) <= limit:
        return s
    head = s[:limit]
    for mark in ("。", "！", "？", "…", ";", ";", ". "):
        i = head.rfind(mark)
        if i >= limit * 0.5:                 # 太靠前的就别退了，等于丢了一大段信息
            return head[:i + len(mark)].rstrip()
    return head.rstrip()


def meta_of(vod: dict) -> dict:
    """从上游条目里取 NFO 要用的那几个字段。

    简介优先 vod_blurb（短的那份），空了才退到 vod_content —— 后者常常带着
    `<p>` 标签和上千字剧情，实测最长的有 5KB 多，全存下来 NFO 就没法看了，
    所以两条都截到 400 字。豆瓣号有些站填 0（不是空），0 当没有。
    """
    blurb = clean_text(vod.get("vod_blurb", "")) or clean_text(vod.get("vod_content", ""))
    did = str(vod.get("vod_douban_id") or "").strip()
    return {
        "blurb": _cut_sentence(blurb, META_LIMITS["blurb"]),
        "actor": clean_text(vod.get("vod_actor", ""))[:META_LIMITS["actor"]],
        "director": clean_text(vod.get("vod_director", ""))[:META_LIMITS["director"]],
        "area": clean_text(vod.get("vod_area", ""))[:META_LIMITS["area"]],
        "douban_id": "" if did in ("0", "") else did[:META_LIMITS["douban_id"]],
        "douban_score": clean_text(vod.get("vod_douban_score", ""))[:META_LIMITS["douban_score"]],
    }


def msig_of(meta: dict) -> str:
    body = json.dumps(meta, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(body.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- 落库（采集侧）
def record_vod(con, src_id: str, src_name: str, vod: dict, cfg: dict,
               pass_id: int, since: date | None = None) -> str:
    """一条上游 videolist 条目 -> vod 表一行。返回 new / changed / same / skip。

    时间范围在这里判（不在导出时判）：库里只留窗口内的东西，
    导出就永远是"库里有什么写什么"，不必每次重新过滤一遍几十万行。
    判据用 vod_year（出品年份）而不是更新时间 —— 用户要的是"近一年拍的片子"，
    而老片被源站重新上架时更新时间也变成今天，只看时间会把 2003 年的片子收进来。
    年份为空时（实测各源条目级偶发）退到"更新时间落在窗口内"。
    """
    title = display_title(vod.get("vod_name", ""))
    key = title_key(title)
    if len(key) < 2:
        return "skip"
    kind = kind_of(vod.get("type_name", ""))
    if kind not in KINDS:
        return "skip"                       # 认不出类别的（体育/解说）不进库
    year = clean_text(vod.get("vod_year", ""))
    pubdate = clean_text(vod.get("vod_pubdate", ""))[:24]
    updated = clean_text(vod.get("vod_time", ""))[:19]
    since = since or cutoff(cfg)
    if not in_window(vod, since):
        return "skip"
    lines = split_lines(vod, bool(cfg["m3u8_only"]), int(cfg["max_lines_per_src"]))
    if not lines:
        return "skip"                       # 一条能播的都没有：进库也只能导出空文件
    if max(len(l["eps"]) for l in lines) > MOVIE_EP_MAX:
        kind = "tv"                         # 站点把剧标成电影了（见 MOVIE_EP_MAX 的注释）
    sig = sig_of(lines)
    meta = meta_of(vod)
    ms = msig_of(meta)
    # 豆瓣号有些站填 0（不是空），0 当没有；后面拼 [doubanid=…] 时用它
    did = str(vod.get("vod_douban_id") or "").strip()
    douban_id = "" if did in ("0", "") else did[:16]
    url_count = sum(len(l["eps"]) for l in lines)
    m3u8_count = sum(1 for l in lines for e in l["eps"] if _M3U8.search(e["url"]))
    payload = json.dumps(lines, ensure_ascii=False, separators=(",", ":"))
    stamp = now()
    vid = str(vod.get("vod_id"))
    row = con.execute("SELECT sig, msig FROM vod WHERE src=? AND vid=?",
                      (src_id, vid)).fetchone()
    args = (src_name, key, title, year, pubdate, kind, clean_text(vod.get("type_name", "")),
            clean_text(vod.get("vod_remarks", "")), clean_text(vod.get("vod_pic", "")),
            douban_id, meta["blurb"], meta["actor"], meta["director"], meta["area"],
            meta["douban_score"],
            updated, payload, url_count, m3u8_count, sig, ms)
    if row is None:
        con.execute(
            "INSERT INTO vod(src, vid, src_name, key, title, year, pubdate, kind, type_name,"
            " remarks, pic, douban_id, blurb, actor, director, area, douban_score,"
            " updated, lines, url_count, m3u8_count, sig, msig, dirty, pass,"
            " first_seen, last_seen) VALUES(" + ",".join("?" * 27) + ")",
            (src_id, vid) + args + (1, pass_id, stamp, stamp))
        return "new"
    # 两个指纹各管一件事：sig（播放地址）变了算"翻到新内容"，采集的增量早停看它；
    # msig（元数据）变了只把行标脏去重写 NFO，不该让采集以为这片子是新的。
    play_changed = row["sig"] != sig
    dirty = 1 if (play_changed or (row["msig"] or "") != ms) else 0
    # dirty 用 MAX(旧值, 本次结论)：没变的话**不能**把脏标记清成 0 ——
    # 只有 export() 才有资格清脏。采集跑到一半进程被杀、还没来得及导出时，
    # 下一轮把这些行判成"没变"就会把待导出状态抹掉，那批 strm 永远写不出来。
    con.execute(
        "UPDATE vod SET src_name=?, key=?, title=?, year=?, pubdate=?, kind=?, type_name=?,"
        " remarks=?, pic=?, douban_id=?, blurb=?, actor=?, director=?, area=?, douban_score=?,"
        " updated=?, lines=?, url_count=?, m3u8_count=?, sig=?, msig=?,"
        " dirty=MAX(dirty, ?), pass=?, last_seen=? WHERE src=? AND vid=?",
        args + (dirty, pass_id, stamp, src_id, vid))
    return "changed" if play_changed else "same"


def prune_source(con, src_id: str, pass_id: int) -> int:
    """某源这一轮翻完了，把这一轮没再见到的行删掉（上游下架了 / 掉出时间窗口了）。

    只在 done=1 时对整个源做一次。删行之后要连带把它占过的 strm 文件清掉，
    所以这里不直接删文件 —— 把那个 key 标脏，交给下一次 export 重算（库里查不到
    这个 key 的行了，export 就走"删文件"那一支）。
    """
    gone = {r["key"] for r in con.execute(
        "SELECT DISTINCT key FROM vod WHERE src=? AND pass<>?", (src_id, pass_id))}
    n = con.execute("DELETE FROM vod WHERE src=? AND pass<>?", (src_id, pass_id)).rowcount
    con.execute("DELETE FROM part WHERE key NOT IN (SELECT DISTINCT key FROM vod)")
    for k in gone:
        if con.execute("SELECT 1 FROM vod WHERE key=? LIMIT 1", (k,)).fetchone() is None:
            con.execute("DELETE FROM part WHERE key=?", (k,))
            con.execute("UPDATE file SET sig='gone' WHERE key=?", (k,))
    return n


# --------------------------------------------------------------------- 游标 / 运行记录 / 计数
def cursors(con=None) -> dict:
    own = con is None
    con = con or connect()
    try:
        return {r["src"]: dict(r) for r in con.execute("SELECT * FROM cur")}
    finally:
        if own:
            con.close()


def save_cursor(con, src: str, pg: int, done: bool, pass_id: int, last_time: str,
                known: int, requests: int, stop: str = "", backfill: int = 0) -> None:
    con.execute(
        "INSERT INTO cur(src, pg, done, stop, pass, last_time, known, backfill, requests,"
        " updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(src) DO UPDATE SET pg=excluded.pg, done=excluded.done,"
        " stop=excluded.stop, pass=excluded.pass, last_time=excluded.last_time,"
        " known=excluded.known, backfill=MAX(cur.backfill, excluded.backfill),"
        " requests=excluded.requests, updated_at=excluded.updated_at",
        (src, int(pg), 1 if done else 0, str(stop or ""), int(pass_id), str(last_time or ""),
         int(known), int(backfill), int(requests), now()))


def new_pass_id(con) -> int:
    """一轮采集一个号：游标和 vod.pass 都靠它对得上，跨天续采时才知道谁是"这一轮的"。"""
    row = con.execute("SELECT COALESCE(MAX(pass), 0) + 1 AS p FROM cur").fetchone()
    return int(row["p"])


def log_run(con, kind: str, started: float, **f) -> None:
    con.execute(
        "INSERT INTO run(kind, started_at, finished_at, seconds, srcs, requests, pages,"
        " rows_new, rows_changed, files_written, files_skipped, files_removed, note)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (kind, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)), now(),
         round(time.time() - started, 1), f.get("srcs"), f.get("requests"), f.get("pages"),
         f.get("rows_new"), f.get("rows_changed"), f.get("files_written"),
         f.get("files_skipped"), f.get("files_removed"), str(f.get("note") or "")[:400]))
    con.commit()


def last_run(kind: str, con=None) -> dict:
    own = con is None
    con = con or connect()
    try:
        r = con.execute("SELECT * FROM run WHERE kind=? ORDER BY id DESC LIMIT 1", (kind,))
        d = r.fetchone()
        return dict(d) if d else {}
    finally:
        if own:
            con.close()


def db_counts(con=None) -> dict:
    own = con is None
    con = con or connect()
    try:
        q = lambda sql, *a: con.execute(sql, a).fetchone()[0]  # noqa: E731
        return {
            "vods": q("SELECT COUNT(*) FROM vod"),
            "titles": q("SELECT COUNT(DISTINCT key) FROM vod"),
            "movies": q("SELECT COUNT(DISTINCT key) FROM vod WHERE kind='movie'"),
            "shows": q("SELECT COUNT(DISTINCT key) FROM vod WHERE kind='tv'"),
            "sources": q("SELECT COUNT(DISTINCT src) FROM vod"),
            "urls": q("SELECT COALESCE(SUM(m3u8_count), 0) FROM vod"),
            "eps": q("SELECT COALESCE(SUM(url_count), 0) FROM vod"),
            "dirty": q("SELECT COUNT(*) FROM vod WHERE dirty=1"),
            "files": q("SELECT COUNT(*) FROM file"),
        }
    finally:
        if own:
            con.close()


# ------------------------------------------------------------------- 外部 ID（查 TMDB 用）
# 查询本身在 tools/collect_strm.py（那边才有联网和节奏控制），这里只管库。
ID_RETRY_MAX = 3          # 一个 key 最多试这么多次；之后只能靠后台"重查没命中的"手动清


def pending_ids(limit: int = 0, con=None, all_keys: bool = False) -> list[dict]:
    """还没查到 TMDB 号的片，按"上游集数多的先来"排。

    每行给 {key, kind, title, year, douban_id, tries, state} —— title/year 取的是
    "各源里集数最多的那一行"（SQLite 保证 MAX(url_count) 那一行的裸列就是这么取的），
    因为集数多的那行通常是站点填得最全的那行，拿它的名字去查命中率高一点。
    all_keys=True 时把已经判过"确实没有"的也放回来（后台那颗"重查没命中的"就用它，
    不然 TMDB 上新增了条目的片子永远没机会）。
    """
    own = con is None
    con = con or connect()
    try:
        where = ("(m.key IS NULL OR (m.state NOT IN ('ok', 'none') AND m.tries < ?))"
                 if not all_keys else
                 "(m.key IS NULL OR m.state <> 'ok')")
        sql = (
            "SELECT v.key AS key, v.kind AS kind, v.title AS title, v.year AS year,"
            " v.douban_id AS douban_id, COALESCE(m.tries, 0) AS tries,"
            " COALESCE(m.state, '') AS state, MAX(v.url_count) AS eps"
            " FROM vod v LEFT JOIN idmap m ON m.key = v.key"
            f" WHERE {where}"
            " GROUP BY v.key ORDER BY eps DESC")
        rows = list(con.execute(sql, (ID_RETRY_MAX,)))
        return rows[:limit] if limit else rows
    finally:
        if own:
            con.close()


def save_id(con, key: str, kind: str, title: str = "", year: str = "",
            tmdb_id: str = "", state: str = "", reason: str = "",
            tries: int = 0) -> bool:
    """写一条查询结论，返回"这次是不是真的换来了一个新 ID"。

    tries 由调用方给（它才知道这是第几次试）。换成新 ID 时把这个 key 标脏 ——
    ID 是**写进目录名**的，不标脏的话下一轮增量导出根本不会看这个 key，
    查到的号就永远躺在 idmap 里、名字还是老的（这个坑很容易漏，所以写在返回值上）。
    """
    tmdb_id = str(tmdb_id or "")[:16]
    old = con.execute("SELECT tmdb_id FROM idmap WHERE key=?", (key,)).fetchone()
    was = str(old["tmdb_id"] or "") if old else ""
    con.execute(
        "INSERT INTO idmap(key, kind, title, year, tmdb_id, state, reason, tries, checked_at)"
        " VALUES(?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(key) DO UPDATE SET kind=excluded.kind, title=excluded.title,"
        " year=excluded.year, tmdb_id=excluded.tmdb_id, state=excluded.state,"
        " reason=excluded.reason, tries=excluded.tries, checked_at=excluded.checked_at",
        (key, kind, str(title or "")[:80], str(year or "")[:8], tmdb_id,
         state, str(reason or "")[:120], int(tries), now()))
    if tmdb_id and tmdb_id != was:
        con.execute("UPDATE vod SET dirty=1 WHERE key=?", (key,))
        return True
    return False


def reset_ids(con=None, state: str = "none") -> int:
    """把某个结论清掉重查（默认清"查过确实没有"的那些）。"""
    own = con is None
    con = con or connect()
    try:
        n = con.execute("DELETE FROM idmap WHERE state=?", (state,)).rowcount
        con.commit()
        return n
    finally:
        if own:
            con.close()


def meta_gap(con=None) -> int:
    """还有多少条没补过元数据（NFO 里就只有片名和年份）。

    判据用 msig 空不空，不用 blurb 空不空：上游本来就有真没填简介的条目，
    补过一次之后 msig 就有值了，不该被当成"还没补"反复问。
    `--backfill-only` 那一支的进度也是数这个。
    """
    own = con is None
    con = con or connect()
    try:
        return int(con.execute(
            "SELECT COUNT(*) FROM vod WHERE msig IS NULL OR msig=''").fetchone()[0])
    finally:
        if own:
            con.close()


def id_stats(con=None) -> dict:
    """这一项目前到什么程度了：命中多少、确认没有多少、还剩多少没查。"""
    own = con is None
    con = con or connect()
    try:
        c = {r["state"] or "": r["n"] for r in con.execute(
            "SELECT state, COUNT(*) AS n FROM idmap GROUP BY state")}
        total = con.execute("SELECT COUNT(DISTINCT key) FROM vod").fetchone()[0]
        ok = c.get("ok", 0)
        return {"ok": ok, "none": c.get("none", 0), "bad": c.get("bad", 0),
                "pending": max(0, total - ok - c.get("none", 0)),
                "titles": total,
                "douban_titles": int(con.execute(
                    "SELECT COUNT(DISTINCT key) FROM vod"
                    " WHERE douban_id NOT IN ('', '0') AND douban_id IS NOT NULL"
                ).fetchone()[0])}
    finally:
        if own:
            con.close()


# 集名到底在说"第几集"还是"第几个版本"：判类别时这是比站点分类更硬的证据
EPISH_RE = re.compile(r"(第\s*\d+\s*[集话話期回]\s*[完结完]*|EP\s*\.?\s*\d+|S\d{1,2}\s*E\d{1,3}"
                      r"|更新至|抢先|加更|全集)", re.I)
VERSIONISH_RE = re.compile(r"(HD|BD|DVD|TC|TS|CAM|SCR|SD|4K|8K|1080P|720P|480P|中字|国语|粤语"
                           r"|闽南|沪语|正片|完整版|未删减|超清|高清|标清|清晰)", re.I)
SERIAL_TITLE_RE = re.compile(r"(第\s*[一二三四五六七八九十百\d]+\s*季|Season\s*\d+)", re.I)
MOVIE_TITLE_RE = re.compile(r"(剧场版|电影版|特别篇|SP特辑)", re.I)


def kind_of_rows(rows: list[sqlite3.Row], title: str) -> str:
    """一部片在 Emby 里应该按电影还是剧集布局导出 —— 各源说法不一致时的取舍。

    为什么要单独写这个函数：以前取的是 `ORDER BY src_name` 第一行的 kind，
    等于**用中文源名的字节序决定一部片进电影库还是电视剧库**。实测库里 11 个 key
    各源类别不一致（《疯狂动物城2》电影天堂标电影、两家非凡标动漫；
    《鬼的新娘》三家给"正片"、淘片给 10 集；《我的美食向导 第二季》备番给 4 集）。

    判据从硬到软，找到第一个能定案的证据就停：
      1) 有任何一家给了超过 MOVIE_EP_MAX 集 —— 一定不是电影（这条和 record_vod
         里把那一行改成 tv 是同一个理由：按电影布局只会留一集，整部剧就丢了）；
      2) 所有集名都"像版本、不像集"（`HD中字 / HD国语 / HD粤语`、`TC中字` 这种）——
         那就是一部片的几个版本，哪怕有两家把它塞进了"动漫"分类也算电影。
         这条实测是**决定性**的：《疯狂动物城2》三个源给的"三集"就是这三个版本；
      3) 片名里写着「剧场版 / 电影版」→ 电影；写着「第 X 季 / Season」→ 剧集；
      4) 以上都没证据就按各家 type_name 投票，平票算剧集 ——
         站点的"电影"分类常拿来塞网络大电影和短片，而"动漫 / 剧 / 番"这类标签
         基本只在真是剧集时才出现；并且往剧集倒不丢内容（每集都还在，只是布局变了）。
    """
    counts: dict[str, int] = {}
    all_names: list[str] = []
    for r in rows:
        if r["kind"] in KINDS:
            counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        if int(r["url_count"] or 0) > MOVIE_EP_MAX:
            return "tv"
        try:
            lines = json.loads(r["lines"])
        except (TypeError, ValueError):
            lines = []
        for l in lines:
            all_names += [clean_text(e.get("name", "")) for e in l.get("eps") or []]
    names = [n for n in all_names if n]
    if names and not any(EPISH_RE.search(n) for n in names) \
            and all(VERSIONISH_RE.search(n) for n in names):
        return "movie"
    t = str(title or "")
    if MOVIE_TITLE_RE.search(t):
        return "movie"
    if SERIAL_TITLE_RE.search(t):
        return "tv"
    if counts:
        return max(counts, key=lambda k: (counts[k], k == "tv"))
    return "movie"


# --------------------------------------------------------------------------- 导出 strm
def merged_versions(rows: list[sqlite3.Row], cfg: dict) -> dict:
    """一个 key 的各行（每源一条）归并成导出要的结构。

    这里管两件跨源的事：
      1) 同一个源有两条同名 vod（上游自己重复上架）只留集数多的那条 —— 否则海报墙
         会出现"虎牙资源 / 虎牙资源"两个一模一样的版本；
      2) 片名与年份取"出现次数最多"的那个写法（各源同名不同写法很常见，
         比如《A》和《A 最新版》同时存在时以多数字为准）。
    """
    by_src: dict[str, sqlite3.Row] = {}
    titles: dict[str, int] = {}
    years: dict[str, int] = {}
    types: dict[str, int] = {}
    for r in rows:
        t = clean_text(r["title"])
        if t:
            titles[t] = titles.get(t, 0) + 1
        y = clean_text(r["year"] or "")
        if y:
            years[y] = years.get(y, 0) + 1
        tn = clean_text(r["type_name"] or "")
        if tn:
            types[tn] = types.get(tn, 0) + 1
        old = by_src.get(r["src"])
        if old is None or int(r["url_count"] or 0) > int(old["url_count"] or 0):
            by_src[r["src"]] = r
    title = max(titles, key=lambda k: (titles[k], len(k))) if titles else rows[0]["title"]
    year = max(years, key=lambda k: (years[k], k)) if years else (rows[0]["year"] or "")
    type_name = max(types, key=lambda k: types[k]) if types else ""
    kind = kind_of_rows(rows, title)
    # 豆瓣号取"各源里出现最多的那个写法"而不是最长非空：同一部片偶尔两个源给两个号
    # （改版/填错），众数至少不会被某一站的填错带跑。空就是没有。
    def mode(field: str) -> str:
        cnt: dict[str, int] = {}
        for r in rows:
            v = clean_text(r[field] or "")
            if v:
                cnt[v] = cnt.get(v, 0) + 1
        return max(cnt, key=lambda k: (cnt[k], len(k))) if cnt else ""

    # 其余文本字段取"各源里最完整的那一份"：同一个片在 A 站只有名字、在 B 站有简介和演员表，
    # 就该用 B 站那份。逐字段取最长非空，而不是整行挑一条 —— 实测各源填的字段
    # 参差不齐（虎牙常缺简介、百度缺导演），整行挑会白丢掉别源有的信息。
    def longest(field: str) -> str:
        vals = [clean_text(r[field] or "") for r in rows]
        return max([v for v in vals if v], key=len) if any(vals) else ""

    pub = ""
    for r in rows:
        pd, _y = pub_date({"vod_pubdate": r["pubdate"] or ""})
        if pd:
            pub = pd.isoformat()
            break
    if not pub:                      # 只有年份的（实测淘片全是 "2026"）也带上，别空着
        for r in rows:
            m = re.search(r"(19|20)\d{2}", str(r["pubdate"] or ""))
            if m:
                pub = m.group(0)
                break
    meta = {"blurb": longest("blurb"), "actor": longest("actor"),
            "director": longest("director"), "area": longest("area"),
            "douban_id": mode("douban_id"), "douban_score": longest("douban_score"),
            "pic": longest("pic"), "pubdate": pub, "remarks": longest("remarks"),
            "sources": sorted({r["src_name"] for r in rows})}
    versions = []
    for r in sorted(by_src.values(), key=lambda x: (-int(x["url_count"] or 0), x["src_name"])):
        try:
            lines = json.loads(r["lines"])
        except (TypeError, ValueError):
            continue
        if not lines:
            continue
        versions.append({
            "src": r["src"], "src_name": r["src_name"],
            # 一个源留了多条线路（或关了 m3u8 限定）时，版本名要带上线路名
            "need_line": len(lines) > 1 or not cfg["m3u8_only"],
            "season": season_hint(title, r["type_name"] or type_name),
            "lines": lines,
        })
    return {"kind": kind, "title": title, "year": year, "type_name": type_name,
            "douban_id": meta["douban_id"], "meta": meta, "versions": versions}


def x(s) -> str:
    """NFO 里的文本一律转义：片名带 & 和 < 是常事（实测有《A&B》这种），
    不转义会写出一份解析不了的 NFO，而 Emby 对坏 NFO 的处理是整条不认。"""
    from xml.sax.saxutils import escape
    return escape(str(s or ""))


def nfo_id_tags(item: dict, ids: dict | None) -> str:
    """ID 那几行。

    写法照用户给的那份 Emby 自己生成的 NFO：`<tmdbid>` 和 `<uniqueid type="tmdb">`
    同时出现 —— 一个是 Emby 存自己库用的标签，一个是"这条片子的外部号"的规范写法，
    两种都给，插件与本体各读各的都不会扑空。豆瓣号同理给两种：Emby 本体不认豆瓣号，
    豆瓣插件认哪一种我没法在本机验证，所以两种都写；认不出来的 type 会被直接忽略。
    """
    out = []
    tmdb = str((ids or {}).get("tmdb_id") or "").strip()
    if tmdb:
        out.append(f"  <uniqueid type=\"tmdb\" default=\"true\">{x(tmdb)}</uniqueid>\n"
                   f"  <tmdbid>{x(tmdb)}</tmdbid>\n")
    db = str(item["meta"].get("douban_id") or "").strip()
    if db:
        out.append(f"  <uniqueid type=\"douban\">{x(db)}</uniqueid>\n"
                   f"  <uniqueid type=\"douban_id\">{x(db)}</uniqueid>\n"
                   f"  <doubanid>{x(db)}</doubanid>\n")
    return "".join(out)


def nfo_common(item: dict, ids: dict | None) -> str:
    """`<movie>` / `<tvshow>` 共用的那一批字段。

    `premiered` 只在 `vod_pubdate` 真给到"年月日"时才写：只有年份时写进去等于
    让 Emby 以为这片子是 1 月 1 日首映的，宁缺毋假。评分同理 —— 实测多数上游填
    "0.0"，写进 NFO 就是让 Emby 显示一个假的 0 分，比不写更糟。
    """
    meta = item["meta"]
    title = x(item["title"])
    y = re.search(r"(19|20)\d{2}", str(item["year"] or ""))
    pub = str(meta.get("pubdate") or "")
    parts = [f"  <title>{title}</title>\n",
             f"  <originaltitle>{title}</originaltitle>\n",
             f"  <sorttitle>{title}</sorttitle>\n"]
    if y:
        parts.append(f"  <year>{y.group(0)}</year>\n")
    if len(pub) >= 10:
        parts.append(f"  <premiered>{x(pub[:10])}</premiered>\n"
                     f"  <releasedate>{x(pub[:10])}</releasedate>\n")
    parts.append("".join(f"  <genre>{g}</genre>\n"
                         for g in re.split(r"[ /、,，]+", x(str(item.get("type_name") or "")))
                         if g.strip()))
    if meta.get("area"):
        parts.append(f"  <country>{x(meta['area'])}</country>\n")
    for d in re.split(r"[/,，、]", str(meta.get("director") or ""))[:4]:
        if d.strip():
            parts.append(f"  <director>{x(d.strip())}</director>\n")
    parts.append("".join(f"  <actor><name>{x(a.strip())}</name><role>主演</role></actor>\n"
                         for a in re.split(r"[/,，、]", str(meta.get("actor") or ""))
                         if a.strip())[:2000])          # 演员表有的站写了几十个，截一下
    if meta.get("blurb"):
        # 渲染端再截一次：库里那列是 record_vod 截过的，但 NFO 的长度不该依赖
        # "每一行都是从 record_vod 进来的"这个假设（迁移、手工修数据都可能塞进更长的）
        parts.append(f"  <plot>{x(_cut_sentence(meta['blurb'], META_LIMITS['blurb']))}</plot>\n")
    sc = str(meta.get("douban_score") or "").strip()
    try:
        if float(sc) > 0:
            parts.append(f"  <rating>{x(sc)}</rating>\n")
    except ValueError:
        pass
    parts.append(nfo_id_tags(item, ids))
    pic = str(meta.get("pic") or "").strip()
    if pic.startswith("http"):
        # 写上游原地址，不走本站代理：实测这些图床不带 Referer 也能直接取到
        # （pic.youkupic.com / image.huyajs.com / fffgood.com 抽样 12 张全 200），
        # 走代理就得为每部片登记一次白名单，那份清单是**每个进程各自一份**的，
        # 片数一多会把首页猜你想搜那些图挤掉 —— 上一版就是这么把自己挡在门外的。
        parts.append(f"  <thumb>{x(pic)}</thumb>\n")
    srcs = "、".join((meta.get("sources") or [])[:4])
    if srcs:
        # 来源写进 studio：Emby 的"工作室"栏正好能显示这条片是哪个源给的，
        # 某源地址失效时在界面上就能认出来
        parts.append(f"  <studio>{x(srcs)}</studio>\n")
    return "".join(parts)


def nfo_document(kind: str, item: dict, ids: dict | None, cfg: dict,
                 sea: int = 0, ep_no: int = 0, ep_name: str = "") -> str:
    """一份 NFO 的正文。

    三种根标签是 Emby/Kodi 认的写法，不能自己发明：
      `movie`          —— 一个电影版本一份（文件名同名）
      `tvshow`         —— 剧集根目录那一份：系列的 ID 只能写在这里，
                          每一集的 nfo 里放系列号会被当成"某一集的号"
      `episodedetails` —— 一集一份，只写这一集用得上的东西（集名 / 季号 / 集号）；
                          系列级的简介、演员留给 tvshow.nfo，否则 13 万个文件
                          各抄一遍同样的大段文本，包体积和 Emby 的解析都白付两倍
    """
    head = '<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n'
    if kind == "episode":
        return (head + "<episodedetails>\n"
                + f"  <title>{x(ep_name or item['title'])}</title>\n"
                + f"  <showtitle>{x(item['title'])}</showtitle>\n"
                + f"  <season>{int(sea)}</season>\n"
                + f"  <episode>{int(ep_no)}</episode>\n"
                + "</episodedetails>\n")
    body = nfo_common(item, ids)
    if kind == "tvshow":
        return head + "<tvshow>\n" + body + "</tvshow>\n"
    return head + "<movie>\n" + body + "</movie>\n"


def ids_line(cfg: dict | None = None, stats: dict | None = None,
             last: dict | None = None) -> str:
    """后台「ID 标签」那一句话。

    为什么在 Python 里拼整句而不是在模板里排 span：这一行改成了异步刷新
    （保存设置/按按钮不重载页面），文案写两份就一定会对不上一次 ——
    模板说"没配 key"而 JS 说"已配"是最难查的那种错。
    """
    cfg = cfg or settings()
    st = stats if stats is not None else id_stats()
    return ("目录名 ID 标签：tmdbid " + ("开" if cfg.get("tag_tmdb_id") else "关")
            + " / doubanid " + ("开" if cfg.get("tag_douban_id") else "关")
            + " · TMDB key " + ("已配" if str(cfg.get("tmdb_api_key") or "").strip()
                                else "没配（这一支不会打接口）")
            + f" —— 查到号 {st['ok']} 部 / 确实没有 {st['none']} 部 / "
            + f"没查成 {st['bad']} 部 / 还没查 {st['pending']} 部（共 {st['titles']} 部）· "
            + f"上游自带豆瓣号 {st['douban_titles']} 部"
            + (f"；上一轮问了 {last['asked']} 部、命中 {last['ok']} 部"
               f"{'，停在「' + last['stopped'] + '」' if last.get('stopped') else ''}"
               if last else ""))


def nfo_line(cfg: dict | None = None, files: int | None = None) -> str:
    """后台「NFO」那一句话（同上一条的理由：异步刷新不能有两份文案）。

    份数要数一次 `path LIKE '%.nfo'`，那是全表扫（后缀匹配用不上主键），二十几万行
    几十毫秒 —— 这一句只出现在后台那一页和它的轮询里，不值得为它维护一个计数器：
    计数器会和 file 表对不上，那种错比慢更难查。
    """
    cfg = cfg or settings()
    if not cfg.get("write_nfo"):
        return ("NFO：关 —— Emby 只靠 `片名 (年份)` 这套文件名在线刮削；"
                "要本地元数据就打开「每个 strm 旁边写一份同名 NFO」再按一次全量重建")
    n = files if files is not None else nfo_count()
    return (f"NFO：开 —— 每个 strm 旁边一份同名 .nfo（剧集另有 tvshow.nfo 承载系列号）· "
            f"已写 {n} 份 · 代价是文件数与包里条目翻倍，Emby 也多读一倍")


def nfo_count(con=None) -> int:
    own = con is None
    con = con or connect()
    try:
        return int(con.execute(
            "SELECT COUNT(*) FROM file WHERE path LIKE '%.nfo'").fetchone()[0])
    finally:
        if own:
            con.close()


def status_lines(cfg: dict | None = None, last: dict | None = None, con=None) -> dict:
    """后台那一节要的两句话（模板渲染和 JS 刷新都从这里取，全站只有这一份文案）。

    `last` 是状态文件里上一轮的 ids（问了几个、命中多少、为什么停着）：
    只有跑过的人才知道"开关开了却一个号都没查到"是哪一种情况，这句必须带上。
    """
    cfg = cfg or settings()
    own = con is None
    con = con or connect()
    try:
        return {"ids": ids_line(cfg, id_stats(con), last),
                "nfo": nfo_line(cfg, nfo_count(con))}
    finally:
        if own:
            con.close()


def plan(key: str, rows: list[sqlite3.Row], cfg: dict, ids: dict | None = None) -> list[dict]:
    """一个 key -> 文件计划 [{path, url, content, sig, kind, ep, label, title, year}]。

    path 是**不含 kind/卷号**的那一段（`<片名 (年份>)/...`），
    由 export() 补成 `movie/movie01/...` —— 卷号是全局分配的，plan 不该知道。
    `ids` 是这个 key 在 idmap 里那一行（查到的 TMDB 号），用来拼目录名尾的标签
    和 NFO 里那几行 uniqueid。
    """
    item = merged_versions(rows, cfg)
    kind = item["kind"]
    # 目录名带 ID 标签，文件名不一定带：
    #   电影 —— 文件名**必须**以文件夹名开头，Emby 才把同一文件夹里的几个源并成
    #          "多版本"，所以标签跟着进文件名（《星际穿越 (2014) [tmdbid=157336] - 虎牙资源》）；
    #   剧集 —— Emby 只读剧集根目录那一个标签，季目录和每集文件名都不必再带，
    #          带上等于把 60 集 ×N 源的文件名全拉长一遍（实测容易顶到 MAX_PATH）。
    folder = folder_title(item["title"], item["year"])
    dirn = folder + id_tag(item, ids, cfg)
    cap = int(cfg["max_eps_per_title"])
    out: list[dict] = []
    for v in item["versions"]:
        eps: dict[tuple[int, int], tuple[str, str]] = {}
        multi_line = len(v["lines"]) > 1
        for li, line in enumerate(v["lines"]):
            for i, e in enumerate(line["eps"][:cap], start=1):
                if kind == "movie":
                    pos = (1, i)                 # 电影：一集一个版本文件，序号只为区分
                else:
                    pos = parse_ep(e["name"], i, v["season"])
                eps.setdefault(pos, (e["name"], e["url"], line["from"], li))
        label0 = version_label(v["src_name"], v["lines"][0]["from"], v["need_line"])
        for (sea, ep), (name, url, from_name, li) in sorted(eps.items()):
            if kind == "movie":
                # 一部"电影"给了 2~3 段（HD国语/HD粤语、上下集）时，把集名带进版本名，
                # 免得两个文件都叫"虎牙资源"，在 Emby 里看就是同一集重复了两次
                tail = ""
                if len(eps) > 1 and not MOVIE_WORDS.match(clean_text(name)):
                    tail = f"·{safe(name, 12)}"
                label = label0 + tail if li == 0 or not multi_line else \
                    f"{label0}·{safe(from_name, 12)}{tail}"
                fn = safe(f"{dirn} - {label}", 150) + ".strm"
                rel = f"{dirn}/{fn}"
                shown = ""
            else:
                # 集号固定两位起（S01E01）：写成 E001 那种三位补零，Emby 认，
                # 但客户端的版本列表和"下一集"排序看起来会别扭
                se = f"S{sea:02d}E{max(1, int(ep)):02d}"
                label = label0 if li == 0 or not multi_line else f"{label0}·{safe(from_name, 12)}"
                fn = safe(f"{folder} - {se} - {label}", 150) + ".strm"
                rel = f"{dirn}/Season {sea:02d}/{fn}"
                shown = se
            out.append({"path": rel, "url": url, "content": url + "\n",
                        "sig": hashlib.md5(url.encode("utf-8")).hexdigest()[:16],
                        "kind": kind, "key": key, "ep": shown, "label": label,
                        "title": item["title"], "year": item["year"]})
            if cfg["write_nfo"]:
                # 和这个 strm **同名**的一份 .nfo：Emby 就是按"同名 sidecar"配的，
                # 名字差一个字它就不读了。内容只取这部片自己的元数据，
                # 同一个 key 的几个源版本各有一份（文本很小，压缩率高）
                doc = (nfo_document("movie", item, ids, cfg) if kind == "movie" else
                       nfo_document("episode", item, ids, cfg, sea=sea, ep_no=int(ep),
                                    ep_name=clean_text(name)))
                out.append({"path": rel[:-len(".strm")] + ".nfo", "url": "", "content": doc,
                            "sig": hashlib.md5(doc.encode("utf-8")).hexdigest()[:16],
                            "kind": kind, "key": key, "ep": shown, "label": "NFO",
                            "title": item["title"], "year": item["year"]})
    if kind == "tv" and cfg["write_nfo"]:
        # 系列级那一份：tmdbid / 简介 / 演员 / 年份只能写在 tvshow.nfo 里。
        # 每一集的 <episodedetails> 里放系列的号是错的（那表示"这一集的号"），
        # 而 Emby 认整部剧的号恰恰是从这一份读的。
        doc = nfo_document("tvshow", item, ids, cfg)
        out.append({"path": f"{dirn}/tvshow.nfo", "url": "", "content": doc,
                    "sig": hashlib.md5(doc.encode("utf-8")).hexdigest()[:16],
                    "kind": kind, "key": key, "ep": "", "label": "NFO",
                    "title": item["title"], "year": item["year"]})
    # 同一路径只留一条（两个源版本名撞车时以先出现的为准）：
    # 一个路径两个内容会写出"半部片"，谁后写谁说了算，导出结果就不稳定了
    seen: dict[str, dict] = {}
    for it in out:
        seen.setdefault(it["path"], it)
    return list(seen.values())


def part_name(kind: str, part: int) -> str:
    return f"{kind}{int(part):02d}"


class PartAlloc:
    """卷号分配：已有卷号不动，新片填进没满的卷，满了往后开一卷。

    容量按**文件数**算而不是部数：一部 60 集的剧 × 8 个源 = 480 个文件，
    按部数算的话"每卷 3000 部"能撑出十几万个文件的卷，Emby 一次扫描扫不动。
    """

    def __init__(self, con, part_files: int):
        self.con = con
        self.cap = max(1, int(part_files))
        # 已用量盘"已经写出去的文件"，而不是 part 表里的部数：
        # part 表只说这一卷有几部片，一部 60 集 ×8 个源的剧占的是 480 个文件的量。
        # 而且只数 .strm —— 设置项说的就是"每卷最多几个 strm 文件"，
        # 打开同名 NFO 之后每部片旁边多一个文本文件，不该因此把卷切成两倍
        # （那等于"改一个不影响容量的开关，卷号全变了"）。
        self.used: dict[tuple[str, int], int] = {
            (r["kind"], r["part"]): r["n"] for r in con.execute(
                "SELECT kind, part, COUNT(*) AS n FROM file"
                " WHERE path LIKE '%.strm' GROUP BY kind, part")}

    def part_of(self, key: str, kind: str) -> int | None:
        r = self.con.execute("SELECT part FROM part WHERE key=? AND kind=?",
                             (key, kind)).fetchone()
        return int(r["part"]) if r else None

    def alloc(self, key: str, kind: str, nfiles: int) -> int:
        p = self.part_of(key, kind)
        if p is not None:
            return p
        n = max(1, int(nfiles))
        # 整部片塞不进去就换下一卷：一部片跨两卷 = 海报墙上两个同名条目
        p = 1
        while self.used.get((kind, p), 0) + n > self.cap and p < 999:
            p += 1
        self.con.execute("INSERT OR IGNORE INTO part(key, kind, part) VALUES(?,?,?)",
                         (key, kind, p))
        self.used[(kind, p)] = self.used.get((kind, p), 0) + n
        return p


def export(full: bool = False, note: str = "", keys_limit: int = 0) -> dict:
    """把库里的东西导出成 strm 目录树；full=True 重建全部（改完时间范围该跑一次）。

    "到一定时间合并 strm"就落在这里：采集进程每跑完一段预算调一次本函数，
    只处理 dirty=1 的那些 key，内容签名没变的文件不重写
    （Emby 那边 mtime 不动，就不会把整个库重新扫一遍）。
    """
    t0 = time.time()
    cfg = settings()
    ensure_schema()
    ROOT.mkdir(parents=True, exist_ok=True)
    con = connect()
    written = skipped = removed = 0
    touched = 0
    try:
        if full:
            keys = [r["key"] for r in con.execute("SELECT DISTINCT key FROM vod")]
            # 重建时先看有没有孤儿文件（库里已经没这个 key 了），否则它们会一直留在盘上
            keys += [r["key"] for r in con.execute(
                "SELECT DISTINCT f.key FROM file f LEFT JOIN vod v ON v.key=f.key"
                " WHERE v.key IS NULL")]
        else:
            keys = [r["key"] for r in con.execute(
                "SELECT DISTINCT key FROM vod WHERE dirty=1")]
            keys += [r["key"] for r in con.execute(
                "SELECT DISTINCT f.key FROM file f LEFT JOIN vod v ON v.key=f.key"
                " WHERE v.key IS NULL")]
        keys = list(dict.fromkeys(keys))
        if keys_limit:
            keys = keys[:keys_limit]
        alloc = PartAlloc(con, int(cfg["part_files"]))
        # 这一批要用的 ID 一次读全：逐 key 查 idmap 就是每部片多一条 SQL。
        # 整张表读进内存而不是 WHERE key IN(...) —— 一轮 dirty 的 key 能有好几千，
        # 拼成 IN 参数会撞上 SQLite 的变量数上限（999/32766，看编译期）
        ids_by_key = {r["key"]: dict(r) for r in con.execute(
            "SELECT key, tmdb_id FROM idmap")}
        for key in keys:
            rows = list(con.execute("SELECT * FROM vod WHERE key=? ORDER BY src_name", (key,)))
            old = {r["path"]: r["sig"] for r in con.execute(
                "SELECT path, sig FROM file WHERE key=?", (key,))}
            items = plan(key, rows, cfg, ids_by_key.get(key)) if rows else []
            keep: dict[str, dict] = {}
            kind = items[0]["kind"] if items else (
                kind_of_rows(rows, rows[0]["title"]) if rows else "movie")
            if items:
                # 类别是各源投票投出来的（见 merged_versions），上游改标注就可能从电影变成剧集：
                # 旧类别那一行卷号必须放掉，不然它会一直占着那一卷的名额，
                # 而且这个 key 万一又变回电影，会被塞回几周前那卷去
                con.execute("DELETE FROM part WHERE key=? AND kind<>?", (key, kind))
            # 名额只按 strm 数算（同名 NFO 不算）：开了 NFO 不该让同一部片换到别的卷去，
            # 更不该因为一个跟容量无关的开关把整棵树的卷号重排
            n_strm = sum(1 for it in items if it["path"].endswith(".strm"))
            part = alloc.alloc(key, kind, n_strm) if items else 0
            for it in items:
                rel = f"{kind}/{part_name(kind, part)}/{it['path']}"
                keep[rel] = it
            for path, sig in old.items():
                if path not in keep:
                    _unlink(ROOT / path.replace("/", os.sep))
                    con.execute("DELETE FROM file WHERE path=?", (path,))
                    removed += 1
            for rel, it in keep.items():
                if old.get(rel) == it["sig"]:
                    skipped += 1
                    continue
                p = ROOT / rel.replace("/", os.sep)
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_suffix(p.suffix + ".tmp")
                tmp.write_text(it["content"], encoding="utf-8")
                tmp.replace(p)
                con.execute(
                    "INSERT INTO file(path, kind, part, key, sig, bytes, written_at)"
                    " VALUES(?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET"
                    " kind=excluded.kind, part=excluded.part, key=excluded.key,"
                    " sig=excluded.sig, bytes=excluded.bytes, written_at=excluded.written_at",
                    (rel, kind, part, key, it["sig"], len(it["content"]), now()))
                written += 1
            if not rows:
                con.execute("DELETE FROM part WHERE key=?", (key,))
            touched += 1
            # 每 200 部提交一次：导出几千个文件的事务要是攒到最后才提交，
            # 期间站点里任何写入（后台保存设置）都会被 WAL 的单一写者挡死
            if touched % 200 == 0:
                con.commit()
        if not full:
            con.execute("UPDATE vod SET dirty=0 WHERE dirty=1")
        else:
            con.execute("UPDATE vod SET dirty=0")
        prune_dirs()
        # "到一定时间合并 strm"包含两步：先把文件写/删齐，再按卷打成 zip。
        # 顺序不能倒 —— 先打包的话，这一轮刚写出来的那几个文件根本不在这个卷的清单里。
        # 中间先提交一次：写文件和打包是两段长事务，攒成一个的话期间谁都写不进这个库
        con.commit()
        zp = build_zips(con, cfg)
        # 打包之后还要写 manifest.json / 接入说明（这两步只读库 + 写文件，
        # 但读一份清单在 WAL 下也会拿快照；先提交让别的写者能挤进来）
        con.commit()
        write_docs(con, cfg)
        log_run(con, "export", t0, files_written=written, files_skipped=skipped,
                files_removed=removed, srcs=touched,
                note=(note + " " if note else "") + f"{'全量' if full else '增量'}处理 {touched} 部"
                     f" · 打包 {zp['made']} 卷（沿用 {zp['skipped']}）")
        con.commit()
    finally:
        con.close()
    return {"ok": True, "full": full, "keys": touched, "written": written,
            "skipped": skipped, "removed": removed, "zips": zp,
            "seconds": round(time.time() - t0, 1), "dir": str(ROOT), "zip_dir": str(ZIPS)}


def _unlink(p: Path) -> None:
    try:
        p.unlink()
    except OSError:
        pass


def prune_dirs() -> int:
    """清掉空的 Season / 影片 / 卷目录（Windows 上一堆空目录很碍眼）。

    只往下走三层、只删空目录：有人往 strm/ 里手动塞了字幕也不会被误删。
    """
    n = 0
    if not ROOT.exists():
        return 0
    for kind in KINDS:
        base = ROOT / kind
        if not base.is_dir():
            continue
        for part in sorted(base.iterdir()):
            if not part.is_dir():
                continue
            for item in sorted(part.iterdir()):
                if not item.is_dir():
                    continue
                for sub in sorted(item.iterdir()):
                    if sub.is_dir() and not any(sub.iterdir()):
                        _rmdir(sub)
                        n += 1
                if not any(item.iterdir()):
                    _rmdir(item)
                    n += 1
            if not any(part.iterdir()):
                _rmdir(part)
                n += 1
    return n


def _rmdir(p: Path) -> None:
    try:
        p.rmdir()
    except OSError:
        pass


def zip_arcname(rel: str, keep_part: bool = False) -> str:
    """盘上的相对路径 -> zip 里的路径。

    盘上是 `movie/movie01/片名 (年份)/片名 (年份) - 虎牙资源.strm`，包里的写法看设置：

      keep_part=False（默认）→ `片名 (年份)/片名 (年份) - 虎牙资源.strm`
          几卷一起解压到媒体库根，直接就是 `电影库根/片名 (年份)/…` 这一层，
          和"媒体库根下面每个文件夹一部片"的常规布局完全对齐。
      keep_part=True        → `movie01/片名 (年份)/…`
          多留一层卷号目录。好处是"这一卷不要了"能整目录删掉，坏处是媒体库根下面
          多一层和 Emby 无关的目录。

    两种写法都不带最外层的 `movie/` 或 `tv/`：那一层只是本站用来把两类分开存，
    Emby 的电影库和电视剧库本来就是两个库、两个根，再套一层纯属多余。

    换这个设置会重打所有卷（签名里带了这个开关）。已经解压过的人要小心：
    换写法后旧的那套目录还在库里，同一部片会以两个路径各出现一次，
    要么先清掉旧解压结果，要么就别换了。
    """
    parts = rel.split("/")
    if parts[0] not in KINDS or len(parts) <= 2:
        return rel
    return "/".join(parts[1:] if keep_part else parts[2:])


def build_zips(con, cfg: dict | None = None) -> dict:
    """每一卷打一个 zip；内容签名没变的卷不重打包。

    包里的条目一律用 writestr 写文本，不用 write(filename)：
    后者会把磁盘上的 mtime 打进 zip，导出重写文件时 zip 字节也跟着变，
    "这一卷到底有没有变过"就没法用文件大小/哈希一眼对上了。
    """
    cfg = cfg or settings()
    keep = bool(cfg.get("zip_part_dir", 0))
    ZIPS.mkdir(parents=True, exist_ok=True)
    # 清掉上一次被打断留下的中间文件：打包是"先写 .zip.tmp 再 replace"，
    # 进程在中间被杀就会留一个半成品躺在那儿（实测留过 tv05.zip.tmp），
    # 它不会被任何人读到，但会一直占着目录、让人以为打包没干净
    for stale in ZIPS.glob("*.zip.tmp"):
        _unlink(stale)
    made = skipped = removed = 0
    groups = list(con.execute(
        "SELECT kind, part, COUNT(*) AS files, COUNT(DISTINCT key) AS titles FROM file"
        " GROUP BY kind, part ORDER BY kind, part"))
    alive = set()
    for g in groups:
        alive.add((g["kind"], g["part"]))
        rows = list(con.execute(
            "SELECT path, sig FROM file WHERE kind=? AND part=? ORDER BY path",
            (g["kind"], g["part"])))
        # 签名里带上"包内带不带卷号目录"这个开关：不带的话，改了设置却判成"没变"，
        # 老包会一直原样发出去，人只会看到"我明明改了，解压出来还是老样子"
        body = f"part_dir={int(keep)}\n" + "\n".join(f"{r['path']}\t{r['sig']}" for r in rows)
        sig = hashlib.md5(body.encode("utf-8")).hexdigest()[:16]
        name = f"{part_name(g['kind'], g['part'])}.zip"
        path = ZIPS / name
        old = con.execute("SELECT sig, path FROM zip WHERE kind=? AND part=?",
                          (g["kind"], g["part"])).fetchone()
        if old and old["sig"] == sig and path.is_file():
            skipped += 1
            continue
        tmp = path.with_suffix(".zip.tmp")
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
                for r in rows:
                    p = ROOT / r["path"].replace("/", os.sep)
                    if not p.is_file():
                        continue            # 理论上不会发生（file 表就是导出时写的）；真缺了就跳过这一条，别让整卷打不出来
                    z.writestr(zip_arcname(r["path"], keep), p.read_text(encoding="utf-8"))
            tmp.replace(path)
        except OSError:
            _unlink(tmp)
            continue
        con.execute(
            "INSERT INTO zip(kind, part, path, files, titles, bytes, sig, built_at)"
            " VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(kind, part) DO UPDATE SET"
            " path=excluded.path, files=excluded.files, titles=excluded.titles,"
            " bytes=excluded.bytes, sig=excluded.sig, built_at=excluded.built_at",
            (g["kind"], g["part"], name, len(rows), g["titles"],
             path.stat().st_size, sig, now()))
        made += 1
        # 一卷常常是几万个条目、打包要几十秒；这一段的写事务必须一段一段提交，
        # 否则后台"保存设置"会顶着 6 秒 busy_timeout 失败（实测过：导出进程就是这么被顶死的）
        con.commit()
    for r in list(con.execute("SELECT kind, part, path FROM zip")):
        if (r["kind"], r["part"]) in alive:
            continue
        # 同样按文件名删：老库里那一列可能带 "strm_zips/" 前缀
        _unlink(ZIPS / os.path.basename(str(r["path"]).replace("\\", "/")))
        con.execute("DELETE FROM zip WHERE kind=? AND part=?", (r["kind"], r["part"]))
        removed += 1
    con.commit()
    return {"made": made, "skipped": skipped, "removed": removed}


HOWTO = """# Emby 接入说明（这一棵树和这些包都是程序生成的，重跑导出会覆盖）

## 一、拿包（推荐）
分卷包在项目里的 `strm_zips/`，也可以从接口下：`GET /strm/zip?name=movie01.zip`。

1. 把 `movie01.zip`、`movie02.zip`… 全部**解压到同一个「电影」媒体库根目录**；
   把 `tv01.zip`、`tv02.zip`… 全部解压到同一个「电视剧」媒体库根目录。
   包里默认就是 `片名 (年份)/片名 (年份) - 虎牙资源.strm` 这一层，解开直接得到
   `电影库根/片名 (年份)/…`，和 Emby「一个文件夹一部片」的常规布局对齐。
   （后台「包内带卷号目录」打开后会多一层 `movie01/`，好处是"这一卷不要了"能整目录删。
   改这一项会重打所有卷；已经解压过的别改 —— 旧路径那套还留在库里，同一部片会出现两次。）
2. Emby 后台 → 媒体库 → 新建「电影」库指到那个目录，「电视剧」库指到另一个目录。
   以后新增的卷（movie03、tv05…）解进同一个目录再扫一次库就行，不用新建库。
3. 影片名统一是 `片名 (年份)`，同一文件夹里的多个文件是不同源的线路：
   `片名 (2026) - 虎牙资源.strm`、`片名 (2026) - 百度资源.strm`…
   Emby 认「文件夹名 + ` - ` + 版本名」为多版本，所以海报只出一张，
   播放时在「版本」下拉里换线路。电视剧同理，只是多一段集号：
   `剧名 (2026) - S01E03 - 虎牙资源.strm`。
4. strm 里写的就是上游的 m3u8 直链，播放不经过本站。上游换地址了要靠下一轮采集
   重写文件，然后让 Emby 做一次「扫描新建和更新的文件」。
@@IDS@@
@@NFO@@
## 二、直接挂目录
不想拷包就把项目里的 `strm/movie`、`strm/tv` 直接指给 Emby
（同一台机器或能用 SMB/WebDAV 挂上时最省事），接口和包都只是搬运手段。

## 三、接口
- `GET /api/strm/manifest`  列出两类各有哪些卷、每卷多少部/多少文件、包多大、下载地址
- `GET /api/strm/index?kind=movie&part=movie01`  这一卷里有哪些片、各有几条线路
- `GET /api/strm/tree?kind=tv&part=tv01`  这一卷所有文件的相对路径，一行一个
- `GET /strm/zip?name=tv01.zip`  下载分卷包
- `GET /strm/file?path=tv/tv01/…/x.strm`  只取单个 strm 文件
"""

IDS_ON = """5. 目录名末尾带了一段 ID 标签（` [tmdbid=…]` 或 ` [doubanid=…]`）。
   电影是**目录名和文件名都带**（`星际穿越 (2014) [tmdbid=157336]/星际穿越 (2014) [tmdbid=157336] - 虎牙资源.strm`），
   因为 Emby 认多版本的前提就是"文件名以文件夹名开头"；剧集只带在**剧集根目录**那一段
   （`绝命毒师 (2008) [tmdbid=1396]/Season 01/绝命毒师 (2008) - S01E01 - 虎牙资源.strm`），
   Emby 只读剧集目录那一个标签，每集文件名再带一遍只是把路径往 260 字符的上限推。
   Emby 读到标签就直接按 ID 命中，不再拿片名去搜 —— 同名翻拍片、只有年份的片子
   最容易认错，这就是这一项存在的理由。
   `tmdbid` 是查 TMDB 来的（要后台填 API Key），`doubanid` 是上游自带的：
   **Emby 本体不认 doubanid**，那颗开关只对接了豆瓣插件/MoviePilot 的人有用。
   没查到 ID 的片子照旧只写 `片名 (年份)`，不会塞一个猜来的号。

"""

IDS_OFF = """5. 目录名只到 `片名 (年份)`，不带 ID 标签。同名翻拍片要靠 Emby 自己在搜索结果里挑，
   认错时手动「修改元数据」即可。后台「目录名带 TMDB 号」打开后目录会变成
   `片名 (年份) [tmdbid=…]`，**改这一项要跑一次全量重建**，路径全换，
   Emby 那边等于整库重扫（已看进度、收藏会跟着丢，先想清楚再切）。

"""


def howto(cfg: dict) -> str:
    """接入说明里那两条开关相关的说法跟着设置走：写死了就是在说假话。"""
    on = bool(cfg.get("tag_tmdb_id") or cfg.get("tag_douban_id"))
    txt = HOWTO.replace("@@IDS@@", IDS_ON if on else IDS_OFF)
    nfo = ("6. 每个 strm 旁边还有一份**同名**的 `.nfo`（`x.strm` 配 `x.nfo`）：片名、年份、\n"
           "   上映日、类型、地区、导演演员、简介、评分、豆瓣号、TMDB 号、海报地址、来源。\n"
           "   Emby 扫到同名 NFO 时优先用它，不再拿片名去猜。剧集另外在剧集根目录有一份\n"
           "   `tvshow.nfo` —— 系列级的 ID 只能写在那儿，每一集的 `<episodedetails>` 里放\n"
           "   系列的号会被当成某一集的号。代价是**文件数和包里条目翻倍**，Emby 也要多读一倍\n"
           "   的东西；后台关掉这一项，已有的 `.nfo` 会被删干净。\n\n") if cfg.get("write_nfo") \
        else ("6. 没有 `.nfo`：Emby 全靠 `片名 (年份)` 这套文件名去在线刮削。需要本地元数据\n"
              "   就在后台打开「每个 strm 旁边写一份同名 NFO」再按一次全量重建。\n\n")
    return txt.replace("@@NFO@@", nfo)



def write_docs(con, cfg: dict) -> None:
    """目录里留一份接入说明和 manifest.json：不开接口时也能看懂这棵树。"""
    try:
        (ROOT / "接入说明.md").write_text(howto(cfg), encoding="utf-8")
        (ROOT / "manifest.json").write_text(
            json.dumps(_manifest(con, cfg), ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


# --------------------------------------------------------------------- 清单 / 索引（接口用）
def _manifest(con, cfg: dict | None = None) -> dict:
    cfg = cfg or settings()
    out = {"generated_at": now(), "dir": "strm/",
           "window_days": int(cfg["window_days"]), "since": cutoff(cfg).isoformat(),
           "m3u8_only": bool(cfg["m3u8_only"]),
           "part_files": int(cfg["part_files"]),
           "ids": {"tag_tmdb_id": bool(cfg.get("tag_tmdb_id")),
                   "tag_douban_id": bool(cfg.get("tag_douban_id")),
                   # key 只在"有没有配"这一层露出，不把凭据写进公开的清单文件
                   "tmdb_key": bool(str(cfg.get("tmdb_api_key") or "").strip()),
                   "tmdb_host": str(cfg.get("tmdb_host") or ""),
                   **id_stats(con)},
           "nfo": {"write": bool(cfg.get("write_nfo")), "files": 0},
           "counts": db_counts(con), "kinds": {}}
    for kind in KINDS:
        # 说法跟着"包内带不带卷号目录"这个设置走：写死一种，改了设置页面就在说假话
        inside = (f"{part_name(kind, 1)}/片名 (年份)/…" if cfg["zip_part_dir"]
                  else "片名 (年份)/…")
        rows = list(con.execute(
            "SELECT f.part AS part, COUNT(DISTINCT f.key) AS titles, COUNT(*) AS files,"
            " MAX(z.path) AS zpath, MAX(z.bytes) AS zbytes,"
            " MAX(z.built_at) AS zbuild"
            " FROM file f LEFT JOIN zip z ON z.kind=f.kind AND z.part=f.part"
            " WHERE f.kind=? GROUP BY f.part ORDER BY f.part", (kind,)))
        out["kinds"][kind] = {
            "label": KIND_CN[kind],
            "titles": sum(r["titles"] for r in rows),
            "files": sum(r["files"] for r in rows),
            # 卷只是同一棵树被切成几段，所以"解到同一个库根"是关键用法，写在清单里
            "zip_hint": f"{KIND_CN[kind]}的分卷包全部解压到同一个媒体库根目录，"
                        f"拼起来就是完整的一棵树；包里是 `{inside}`"
                        "（不带本站用来分门别类的 movie/ 或 tv/ 那一层）",
            "parts": [],
        }
        for r in rows:
            zname = os.path.basename(str(r["zpath"] or "")) if r["zpath"] else ""
            out["kinds"][kind]["parts"].append({
                "name": part_name(kind, r["part"]), "part": r["part"],
                "titles": r["titles"], "files": r["files"],
                "dir": f"strm/{kind}/{part_name(kind, r['part'])}/",
                "zip": zname,
                "zip_path": f"strm_zips/{zname}" if zname else "",
                "zip_bytes": r["zbytes"] or 0,
                "zip_built_at": r["zbuild"] or "",
                "zip_url": f"/strm/zip?name={_q(zname)}" if zname else "",
                "index_url": f"/api/strm/index?kind={kind}&part={part_name(kind, r['part'])}",
                "tree_url": f"/api/strm/tree?kind={kind}&part={part_name(kind, r['part'])}",
            })
    out["nfo"]["files"] = int(con.execute(
        "SELECT COUNT(*) FROM file WHERE path LIKE '%.nfo'").fetchone()[0])
    out["sources"] = [{"id": r["src"], "name": r["src_name"], "vods": r["n"],
                       "titles": r["keys"], "m3u8_urls": r["m3u8"]}
                      for r in con.execute(
                          "SELECT src, MAX(src_name) AS src_name, COUNT(*) AS n,"
                          " COUNT(DISTINCT key) AS keys,"
                          " COALESCE(SUM(m3u8_count), 0) AS m3u8"
                          " FROM vod GROUP BY src ORDER BY n DESC")]
    out["last"] = {"collect": last_run("collect", con), "export": last_run("export", con)}
    out["cursor"] = [{"src": r["src"], "pg": r["pg"], "done": bool(r["done"]),
                      "stop": str(r["stop"] or ""), "last_time": r["last_time"],
                      "requests": r["requests"]}
                     for r in con.execute("SELECT * FROM cur ORDER BY src")]
    return out


def manifest() -> dict:
    ensure_schema()
    con = connect()
    try:
        return _manifest(con)
    finally:
        con.close()


def download_map(base: str = "") -> dict:
    """扁平的下载清单：文件名 -> 下载地址。

        {"Movies": {"movie01.zip": "http://host:5000/strm/zip?name=movie01.zip", ...},
         "TVs":    {"tv01.zip": "...", ...}}

    和 manifest() 的分工：那一份是"这一卷有多少部、多少文件、包多大、什么时候打的"，
    给页面和人看；这一份只回答"要下载哪些包、地址是什么"，给脚本直接用 ——
    所以键名固定两组（Movies / TVs，跟用户约定的一致，不用再去 kinds 里找），
    值就是能 GET 的地址。

    base 传站点根地址时给绝对 URL（拷到别的机器、别的网段也能下）；
    传空就是相对地址（同源脚本用 curl -O 够用）。

    只列**盘上确实有文件**的那些卷：清单里有、文件被删了的情况留给
    manifest() 与 /strm/zip 的 404 去说清楚，下载清单里不该塞死链。
    """
    ensure_schema()
    base = str(base or "").rstrip("/")
    out: dict = {"Movies": {}, "TVs": {}}
    con = connect()
    try:
        rows = list(con.execute("SELECT kind, part, path, files, titles, bytes, built_at"
                                " FROM zip ORDER BY kind, part"))
    finally:
        con.close()
    for r in rows:
        name = os.path.basename(str(r["path"] or ""))
        if not name or not (ZIPS / name).is_file():
            continue
        key = "Movies" if r["kind"] == "movie" else "TVs"
        out[key][name] = f"{base}/strm/zip?name={_q(name)}"
    return out


def _part_no(kind: str, name: str) -> int | None:
    """卷名 -> 卷号：movie01 / movie1 / MOVIE001 都认，别的算不合法。"""
    m = re.fullmatch(rf"{kind}0*(\d{{1,3}})", str(name or "").strip().lower())
    return int(m.group(1)) if m else None


def part_titles(kind: str, name: str, page: int = 1, per: int = 200) -> dict:
    """某一卷里有哪些片（按片名排）、各有几条线路、文件都在哪儿。"""
    ensure_schema()
    if kind not in KINDS:
        return {"error": "kind 只能是 movie 或 tv"}
    part = _part_no(kind, name)
    if part is None:
        return {"error": f"卷名不对：电影是 movie01、movie02…，电视剧是 tv01、tv02…（收到 {name}）"}
    per = max(1, min(1000, int(per)))
    page = max(1, int(page))
    cfg = settings()
    con = connect()
    try:
        total = con.execute("SELECT COUNT(DISTINCT key) FROM file WHERE kind=? AND part=?",
                            (kind, part)).fetchone()[0]
        keys = [r["key"] for r in con.execute(
            "SELECT DISTINCT key FROM file WHERE kind=? AND part=?"
            " ORDER BY key LIMIT ? OFFSET ?", (kind, part, per, (page - 1) * per))]
        # 这一卷的文件一次取全，再按 key 分组：逐片查会把一次接口打成几百条 SQL
        paths: dict[str, list[str]] = {}
        for r in con.execute("SELECT key, path FROM file WHERE kind=? AND part=?"
                             " ORDER BY path", (kind, part)):
            paths.setdefault(r["key"], []).append(r["path"])
        items = []
        for key in keys:
            # 这一卷的文件清单里含同名 NFO，而这个接口说的是"这一部有几个 strm、几条线路"，
            # 所以只把 .strm 数进去（开了 NFO 之后文件数刚好翻倍，混着报会看着奇怪）
            mine = [p for p in paths.get(key, []) if p.endswith(".strm")]
            rows = list(con.execute("SELECT * FROM vod WHERE key=? ORDER BY src_name", (key,)))
            first = rows[0] if rows else None
            items.append({
                "title": first["title"] if first else "",
                "year": first["year"] if first else "",
                "kind": kind,
                "type": first["type_name"] if first else "",
                "remarks": first["remarks"] if first else "",
                "pic": (f"/img?url={_q(first['pic'])}"
                        if first and str(first["pic"]).startswith("http") else ""),
                "folder": f"{part_name(kind, part)}/{folder_title(first['title'], first['year'])}"
                          if first else "",
                "n_sources": len({r["src"] for r in rows}),
                "sources": [{"id": r["src"], "name": r["src_name"],
                             "eps": sum(len(l["eps"]) for l in json.loads(r["lines"]))}
                            for r in rows],
                "files": len(mine),
                "strm_paths": mine[:8],
                "strm_urls": [f"/strm/file?path={_q(p)}" for p in mine[:8]],
                "more_files": max(0, len(mine) - 8),
            })
        return {"kind": kind, "part": part_name(kind, part), "page": page, "per": per,
                "total": total, "pages": max(1, -(-total // per)),
                "dir": f"strm/{kind}/{part_name(kind, part)}/", "items": items}
    finally:
        con.close()


def _q(s) -> str:
    from urllib.parse import quote
    return quote(str(s or ""), safe="")


def part_paths(kind: str, name: str) -> list[str]:
    """某一卷下所有 strm 的相对路径（给"写脚本批量下载"用）。"""
    part = _part_no(kind, name)
    if part is None:
        return []
    ensure_schema()
    con = connect()
    try:
        return [r["path"] for r in con.execute(
            "SELECT path FROM file WHERE kind=? AND part=? ORDER BY path", (kind, part))]
    finally:
        con.close()


def _under(base: str, full: str) -> bool:
    """full 是不是在 base 里面。

    为什么不直接写 os.path.commonpath(...) != base：Windows 上比较不同盘符的两条路径
    （项目在 E:、临时目录在 C:，测试和"把 strm 目录放到别处"都会遇到）
    commonpath 是直接抛 ValueError 的，那时候要的结论是"不在里面"，不是一个 500。
    """
    try:
        return os.path.commonpath([base, full]) == base
    except ValueError:
        return False


def safe_path(rel: str) -> str | None:
    """把接口传来的相对路径收进 strm/ 目录里；越界或不合法返回 None。

    必须逐段判：除了 `..`，Windows 那边还可能收到 `movie\\..\\..\\x`，
    而 resolve() 在目标不存在时会跟着软链接走，判断反而不如拆段可靠。
    """
    rel = str(rel or "").strip().replace("\\", "/").lstrip("/")
    if not rel.endswith(".strm") or len(rel) > 500:
        return None
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return None
    if parts[0] not in KINDS:
        return None
    base = os.path.abspath(str(ROOT))
    full = os.path.abspath(os.path.join(base, *parts))
    if not _under(base, full):
        return None
    return full


def read_strm(rel: str) -> tuple[int, str, str]:
    """取一个 strm 文件：(状态码, 内容, 错误说明)。

    单个文件的接口是给"就想拿一条线"的场景用的；批量走分卷包（见 zip_file）。
    """
    full = safe_path(rel)
    if not full:
        return 400, "", ("路径不合法：要形如 "
                         "movie/movie01/片名 (2026)/片名 (2026) - 虎牙资源.strm")
    if not os.path.isfile(full):
        return 404, "", "文件不存在（这一卷重排过？重新取一次清单 /api/strm/index）"
    try:
        with open(full, encoding="utf-8") as f:
            return 200, f.read(), ""
    except OSError as exc:  # noqa: BLE001
        return 500, "", f"{type(exc).__name__}: {exc}"


def zip_file(name: str) -> tuple[int, str, str]:
    """取一个分卷包：(状态码, 绝对路径, 说明)。

    只认 `movieNN.zip` / `tvNN.zip` 这一个形状，而且"查库看在不在"而不是"看文件在不在"：
    zip 表是打包时写进去的，盘上被人手删了、或者有人往里塞了个别的东西，
    都不该被接口端出去（那等于开了一个任意文件下载）。
    """
    name = str(name or "").strip()
    m = re.fullmatch(r"(movie|tv)0*(\d{1,3})\.zip", name.lower())
    if not m:
        return 400, "", "包名不对：要形如 movie01.zip、movie02.zip、tv01.zip"
    kind, part = m.group(1), int(m.group(2))
    ensure_schema()
    con = connect()
    try:
        row = con.execute("SELECT path FROM zip WHERE kind=? AND part=?",
                          (kind, part)).fetchone()
    finally:
        con.close()
    if not row:
        return 404, "", f"还没有 {name}（这一卷没内容，或者还没打包）"
    # 按文件名取，不按库里的 path 直接拼：老版本把 "strm_zips/movie01.zip" 整串存进了库，
    # 而现在这一列只存文件名。归一之后两种写法都能取到，升级代码的人不会突然下不了包
    fname = os.path.basename(str(row["path"]).replace("\\", "/"))
    base = os.path.abspath(str(ZIPS))
    full = os.path.abspath(str(ZIPS / fname))
    if not _under(base, full):
        return 400, "", "路径不合法"
    if not os.path.isfile(full):
        return 404, "", f"{name} 清单里有、盘上没有了：跑一次 tools/collect_strm.py --export-only 重打包"
    return 200, full, ""
