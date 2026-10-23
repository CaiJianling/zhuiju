# -*- coding: utf-8 -*-
"""Emby STRM：解析、落库、导出分卷、打包、接口与触发（全部离线，不联网）。

    python tests/test_strm.py

关键点：把 strm.DB / strm.ROOT / strm.ZIPS / admin.CONFIG / stats.DB 全指到临时目录，
而且必须在 `from zhuiju import app` 之前改完 —— app.py 末尾有一句模块级
`app = create_app()`，导入它就会拿真实路径去建库（之前 check_autoupdate 就踩过：
测试写真实状态文件，正在读的站点把假状态显示到页头上了）。
"""
import importlib.util
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("PYTHONUTF8", "1")

from zhuiju import admin as admin_mod      # noqa: E402
from zhuiju import autoupdate              # noqa: E402
from zhuiju import stats as stats_mod      # noqa: E402
from zhuiju import strm                    # noqa: E402
from zhuiju import strmjob                 # noqa: E402

SEP = "$$$"          # 上游分线路的分隔符，实测 17 个源一致
FAILS = []
TMP = Path(tempfile.mkdtemp(prefix="zhuiju_strm_test_"))

admin_mod.CONFIG = TMP / "admin.json"
stats_mod.DB = TMP / "stats.db"
stats_mod.DATA = TMP
stats_mod._ready = False
strm.DB = TMP / "strm.db"
strm.DATA = TMP / "strmdata"
import gate_off  # noqa: E402  门禁与本文件的测试对象无关，见 tests/gate_off.py
gate_off.off(TMP)
strm.ROOT = TMP / "strm"
strm.ZIPS = TMP / "strm_zips"
strm._ready = False
strmjob.STATE = strm.DATA / "strm_state.json"
strmjob.PROGRESS = strm.DATA / "strm_progress.json"
strmjob.LOCK = TMP / "logs" / "strm.lock"
strmjob.LOG = TMP / "logs" / "strm.log"
strmjob.SCRIPT = BASE / "tools" / "collect_strm.py"
# 触发用的 spawn 换成记账桩：测试不能真的起采集进程（那会联网、会写盘）
SPAWNED = []


def fake_spawn(script, log, lock, args=()):
    SPAWNED.append(list(args))
    (TMP / "logs").mkdir(exist_ok=True)
    lock.write_text(f"{os.getpid()} {time.time()}", encoding="utf-8")
    return os.getpid()


autoupdate.spawn = fake_spawn

from zhuiju import app as app_mod          # noqa: E402


def check(name, cond, got=None):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  got={got!r}"))
    if not cond:
        FAILS.append(name)


def mk(title, year, type_name, frm, n=1, vid=1, pubdate="", remarks="", douban=0,
       blurb="一段有头有尾的简介。", actor="张三,李四", director="王五", area="中国大陆",
       score="8.4"):
    """造一条上游 videolist 条目。

    每条影片都带两条线路：一条 m3u8 直连、一条 HTML 播放器页 —— 实测多数站就是这样，
    所以"默认只收 m3u8"这条判据必须被真实形状检验，不能只喂干净的。
    简介/演员/导演/地区/评分也按真实形状给（实测一次 videolist 就全带回来了，
    NFO 要用就是从这里来）。`douban` 默认 0：实测各源这一列大多填 0
    （11706 行里只有 548 行有号），"没号"才是常态，要验标签命名时按条给。
    """
    eps = "#".join(f"第{i:02d}集$https://cdn.test/{vid}-{i}/index.m3u8"
                   for i in range(1, n + 1)) if n > 1 else \
        f"正片$https://cdn.test/{vid}-1/index.m3u8"
    html = f"正片$https://play.test/{vid}" if n == 1 else \
        "#".join(f"第{i:02d}集$https://play.test/{vid}-{i}" for i in range(1, n + 1))
    return {"vod_id": vid, "vod_name": title, "vod_year": year, "vod_pubdate": pubdate,
            "type_name": type_name, "vod_time": "2026-10-20 10:00:00",
            "vod_remarks": remarks, "vod_pic": "https://pic.test/1.jpg",
            "vod_blurb": blurb, "vod_actor": actor, "vod_director": director,
            "vod_area": area, "vod_douban_score": score,
            "vod_douban_id": douban,
            "vod_play_from": SEP.join([frm, "webplay"]), "vod_play_url": SEP.join([eps, html])}


def con():
    return strm.connect()


def reset_db():
    """每段用例从干净的库开始：卷号、文件、游标都会互相影响，混在一起就没法判。"""
    for p in (strm.DB, strm.ROOT, strm.ZIPS):
        try:
            p.unlink() if p.is_file() else None
        except OSError:
            pass
    if strm.ROOT.exists():
        import shutil
        shutil.rmtree(strm.ROOT)
    if strm.ZIPS.exists():
        import shutil
        shutil.rmtree(strm.ZIPS)
    for suffix in ("-wal", "-shm"):
        q = Path(str(strm.DB) + suffix)
        if q.exists():
            q.unlink()
    strm._ready = False
    strm.ensure_schema()
    strm.save_settings({"window_days": "365", "part_files": "200",
                        "max_eps_per_title": "120", "delay_ms": "0"})


print("1) 上游线路与集数解析")
v = mk("测试片", "2026", "动作片", "hym3u8", n=1, vid=7)
lines = strm.split_lines(v, True, 1)
check("默认只留 m3u8 那条线路", len(lines) == 1 and lines[0]["from"] == "hym3u8", lines)
check("留下的地址确实是 m3u8", ".m3u8" in lines[0]["eps"][0]["url"], lines)
lines2 = strm.split_lines(v, False, 4)
check("关掉 m3u8 限定后两条线路都收（集数多的排前面）", len(lines2) == 2,
      [l["from"] for l in lines2])
check("is_playable 拒掉相对地址与 javascript:", not strm.is_playable("/a.m3u8")
      and not strm.is_playable("javascript:alert(1)") and strm.is_playable("HTTP://x/a.M3U8"))
check("线路名块数对不上时退成 线路N 而不是错配",
      strm.split_lines({"vod_play_from": "aaa", "vod_play_url": "正片$https://x/a.m3u8"
                        "$$$正片$https://x/b.m3u8"}, True, 8)[1]["from"] == "线路2")
cases = [("第12集", (1, 12)), ("EP07", (1, 7)), ("S02E05", (2, 5)), ("03", (1, 3)),
         ("2026-10-12期", (1, 9)), ("正片", (1, 1)), ("", (1, 9)), ("HD", (1, 1))]
check("集数解析：日期写法不认成第 2026 集，认不出时退到序号",
      [strm.parse_ep(s, 9, 1) for s, _ in cases] == [e for _, e in cases],
      [strm.parse_ep(s, 9, 1) for s, _ in cases])
check("季号：第X季认得出来", strm.season_hint("庆余年 第二季", "") == 2
      and strm.season_hint("某剧", "") == 1)
check("非法文件名字符被换掉，结尾点号不留下",
      "/" not in strm.safe("a/b: c?*") and not strm.safe("结尾点号...").endswith("."),
      strm.safe("a/b: c?*"))
check("超长片名被截断（撞 MAX_PATH 比截断难查）", len(strm.safe("名" * 200)) <= 70)
check("folder_title 带年份", strm.folder_title("毒液", "2025") == "毒液 (2025)"
      and strm.folder_title("无年份片", "") == "无年份片")

print("\n2) 时间范围判据（vod_pubdate 优先，退到年份再退到更新时间）")
since = date(2026, 4, 1)
check("完整上映日期按天判", strm.pub_date(mk("x", "2026", "电影", "f", pubdate="2026-03-31中国大陆"))[0]
      == date(2026, 3, 31))
check("窗口内（日期准）", strm.in_window(mk("x", "2026", "电影", "f", pubdate="2026-10-09中国大陆"), since))
check("窗口外（日期准）：哪怕年份是今年",
      not strm.in_window(mk("x", "2026", "电影", "f", pubdate="2026-01-05"), since))
check("只有年份时退到年份判", not strm.in_window(mk("x", "2025", "电影", "f", pubdate="2025美国"), since))
check("没有 pubdate 用 vod_year", strm.in_window(mk("x", "2026", "电影", "f"), since)
      and not strm.in_window(mk("x", "2019", "电影", "f"), since))
check("年份也没有时退到更新时间", strm.in_window({"vod_year": "", "vod_pubdate": "",
                                                 "vod_time": "2026-05-01 1:00:00",
                                                 "type_name": "电影", "vod_name": "x"}, since))
check("9999 这种填错的上映日期不当真", strm.pub_date(mk("x", "2026", "电影", "f",
                                                        pubdate="9999-01-01")) == (None, 0))

print("\n3) 落库：新/改/同/跳 与脏标记")
reset_db()
cfg = strm.settings()
c = con()
check("窗口内且能播的进库", strm.record_vod(c, "huya", "虎牙资源",
      mk("毒液：最后一舞", "2025", "动作片", "hym3u8", vid=1, pubdate="2025-12-30美国"), cfg, 1) == "new")
check("同一条重采是 same", strm.record_vod(c, "huya", "虎牙资源",
      mk("毒液：最后一舞", "2025", "动作片", "hym3u8", vid=1, pubdate="2025-12-30美国"), cfg, 1) == "same")
changed = mk("毒液：最后一舞", "2025", "动作片", "hym3u8", vid=1, pubdate="2025-12-30美国")
changed["vod_play_url"] = changed["vod_play_url"].replace("1/index.m3u8", "9/index.m3u8")
check("地址变了是 changed",
      strm.record_vod(c, "huya", "虎牙资源", changed, cfg, 2) == "changed")
check("窗口外的老片被跳过", strm.record_vod(c, "huya", "虎牙资源",
      mk("2003年的老片", "2003", "恐怖片", "hym3u8", vid=2), cfg, 1) == "skip")
check("认不出类别的被跳过", strm.record_vod(c, "huya", "虎牙资源",
      mk("某足球赛", "2026", "体育", "hym3u8", vid=3), cfg, 1) == "skip")
check("一条能播线路都没有的被跳过（全 HTML 且开了 m3u8 限定）",
      strm.record_vod(c, "huya", "虎牙资源",
                      {"vod_id": 4, "vod_name": "只有网页", "vod_year": "2026",
                       "type_name": "恐怖片", "vod_time": "2026-10-20",
                       "vod_play_from": "hhyun", "vod_play_url": "正片$https://play.test/4"},
                      cfg, 1) == "skip")
check("站点把剧标成电影时按剧集收（多集的不能只留一集）",
      strm.record_vod(c, "huya", "虎牙资源", mk("被标错的剧", "2026", "动作片", "hym3u8",
                                               n=8, vid=5), cfg, 1) == "new"
      and c.execute("SELECT kind FROM vod WHERE vid='5'").fetchone()["kind"] == "tv")
# 脏标记这条是回归测试：以前"没变"会把 dirty 写成 0，采集进程在导出前被杀就永远丢批
c.execute("UPDATE vod SET dirty=1")
strm.record_vod(c, "huya", "虎牙资源", mk("毒液：最后一舞", "2025", "动作片", "hym3u8", vid=1),
                cfg, 1)
check("没变的重采不会把待导出标记抹掉（只有导出能清）",
      c.execute("SELECT dirty FROM vod WHERE vid='1'").fetchone()["dirty"] == 1)
c.commit()
c.close()

print("\n4) 游标：写进去读得出来（这一条踩过占位符多一个的坑）")
c = con()
strm.save_cursor(c, "huya", 42, False, 1, "2026-10-18 10:00:00", 0, 41, stop="budget", backfill=0)
strm.save_cursor(c, "huya", 60, True, 1, "2025-11-01 09:00:00", 3, 60, stop="cutoff", backfill=1)
cur = strm.cursors(c)["huya"]
check("同一个源只有一条游标，后写的覆盖先写的", cur["pg"] == 60 and cur["done"] == 1, cur)
check("游标条数就是一个源一行", c.execute("SELECT COUNT(*) FROM cur").fetchone()[0] == 1)
check("backfill 只进不退（补翻过一次就永远算补过）", cur["backfill"] == 1)
check("stop 记下来了", cur["stop"] == "cutoff", cur["stop"])
c.commit()
c.close()

print("\n5) 导出：命名、布局、多线路版本")
reset_db()
cfg = strm.settings()
c = con()
strm.record_vod(c, "huya", "虎牙资源", mk("毒液：最后一舞", "2025", "动作片", "hym3u8",
                                          vid=1, pubdate="2025-12-30美国"), cfg, 1)
strm.record_vod(c, "apibdzy", "百度资源", mk("毒液：最后一舞", "2025", "动作片", "dbm3u8",
                                             vid=9, pubdate="2025-12-30美国"), cfg, 1)
strm.record_vod(c, "huya", "虎牙资源", mk("庆余年 第二季", "2026", "国产剧", "hym3u8",
                                          n=4, vid=11, pubdate="2026-05-16中国大陆"), cfg, 1)
strm.record_vod(c, "suoni", "索尼资源", mk("庆余年 第二季", "2026", "国产剧", "snm3u8",
                                           n=3, vid=21, pubdate="2026-05-16中国大陆"), cfg, 1)
c.commit()
c.close()
out = strm.export(full=True)
allout = sorted(str(p.relative_to(strm.ROOT)).replace(os.sep, "/")
                for p in strm.ROOT.rglob("*") if p.is_file())
files = [q for q in allout if q.endswith(".strm")]
check("电影：片名 (年份)/片名 (年份) - 源名.strm",
      "movie/movie01/毒液：最后一舞 (2025)/毒液：最后一舞 (2025) - 虎牙资源.strm" in files, files[:4])
check("电影：同一个文件夹里两条线路 = Emby 的多版本",
      any(x.endswith("虎牙资源.strm") for x in files) and
      any(x.endswith("百度资源.strm") for x in files), files)
check("剧集：Season 目录 + 剧名 (年份) - S02E0x - 源名.strm（片名里写了第二季就归第 2 季）",
      "tv/tv01/庆余年 第二季 (2026)/Season 02/庆余年 第二季 (2026) - S02E03 - 虎牙资源.strm" in files,
      [f for f in files if "E03" in f])
check("集数按各源实际给的来（索尼只有 3 集就不硬凑第 4 集）",
      sum(1 for f in files if "E04" in f) == 1 and sum(1 for f in files if "E03" in f) == 2, files)
one = strm.read_strm("movie/movie01/毒液：最后一舞 (2025)/毒液：最后一舞 (2025) - 虎牙资源.strm")
check("文件内容就是一行 m3u8", one[0] == 200 and one[1].startswith("https://cdn.test/")
      and one[1].endswith("index.m3u8\n"), one)
check("导出的文件数与库里的行数对得上（file 表就是这一棵树到底写了什么：strm + 同名 NFO）",
      len([q for q in allout if q.endswith((".strm", ".nfo"))]) == strm.db_counts()["files"],
      (len(files), strm.db_counts()["files"]))
again = strm.export()
check("没有脏行时增量导出一个文件都不碰（keys=0 就是 dirty 标记在起作用）",
      again["keys"] == 0 and again["written"] == 0, again)
check("重跑之后盘上的文件一个都没少",
      len([p for p in strm.ROOT.rglob("*.strm")]) == len(files),
      (len([p for p in strm.ROOT.rglob("*.strm")]), len(files)))
c = con()
c.execute("UPDATE vod SET lines=? WHERE src='huya' AND vid='1'",
          (json.dumps([{"from": "hym3u8", "eps": [{"name": "正片",
                                                   "url": "https://cdn.test/new-1/index.m3u8"}]}],
                      ensure_ascii=False),))
c.execute("UPDATE vod SET dirty=1 WHERE src='huya' AND vid='1'")
c.commit()
c.close()
third = strm.export()
check("只有变过的那条被重写", third["written"] == 1 and third["skipped"] >= 1, third)
check("变过的内容确实落到文件里",
      "new-1" in strm.read_strm("movie/movie01/毒液：最后一舞 (2025)/毒液：最后一舞 (2025) - 虎牙资源.strm")[1])

print("\n5b) 目录名里的 ID 标签：[doubanid=…] 与 [tmdbid=…]")
# 上游 17 个源实测只有 vod_douban_id 这一个外部号（11706 行里只有 548 行有），
# tmdbid 得查 TMDB —— 所以这一段全部用手工写进 idmap 的方式验命名，不打接口
c = con()
c.execute("UPDATE vod SET douban_id='38185414' WHERE src='huya' AND vid='1'")
c.execute("UPDATE vod SET douban_id='26309763' WHERE src='huya' AND vid='11'")
strm.record_vod(c, "huya", "虎牙资源", mk("无号片", "2026", "动作片", "hym3u8", vid=77), cfg, 1)
c.execute("UPDATE vod SET dirty=1")
c.commit()
c.close()
key_movie = strm.title_key(strm.display_title("毒液：最后一舞"))
key_tv = strm.title_key(strm.display_title("庆余年 第二季"))
key_none = strm.title_key(strm.display_title("无号片"))
strm.save_settings({"tag_douban_id": "1"})
strm.export(full=True)
p5 = sorted(str(p.relative_to(strm.ROOT)).replace(os.sep, "/")
            for p in strm.ROOT.rglob("*.strm"))


def _has(tag):
    return [x for x in p5 if tag in x]


check("电影：目录名和文件名都带 [doubanid=…]（文件名以文件夹名开头这条规则不能被标签破）",
      "movie/movie01/毒液：最后一舞 (2025) [doubanid=38185414]/"
      "毒液：最后一舞 (2025) [doubanid=38185414] - 虎牙资源.strm" in p5,
      _has("毒液")[:2])
tv_eps = [x for x in p5 if x.startswith(
    "tv/tv01/庆余年 第二季 (2026) [doubanid=26309763]/Season 02/")]
check("剧集：标签只带在剧集根目录，Season 以下每集文件名都不带",
      bool(tv_eps) and not any("doubanid" in x.split("/")[-1] for x in tv_eps),
      tv_eps[:2])
check("同一个 key 的另一条源（百度资源，上游没给号）跟着目录走，不会另开一个不带号的文件夹",
      len([x for x in p5 if x.startswith("movie/movie01/毒液：最后一舞 (2025) [doubanid=")]) == 2,
      _has("毒液"))
check("上游没给号的片子照旧只写「片名 (年份)」，不会写一个空标签出来",
      any(x.startswith("movie/movie01/无号片 (2026)/") for x in p5)
      and not any("[doubanid=]" in x for x in p5), _has("无号片"))
check("换了标签就是换了路径：旧的不带标签目录被删掉（留着等于同一部片出现两次）",
      not (strm.ROOT / "movie" / "movie01" / "毒液：最后一舞 (2025)").exists(),
      sorted(q.name for q in (strm.ROOT / "movie" / "movie01").iterdir()))
# TMDB 号：查到才写，而且优先于豆瓣号（一个目录只挂一个标签）
c = con()
got_new = strm.save_id(c, key_movie, "movie", "毒液：最后一舞", "2025", "157336", "ok", "", 1)
c.commit()
same_again = strm.save_id(c, key_movie, "movie", "毒液：最后一舞", "2025", "157336", "ok", "", 2)
c.commit()
dirty_now = c.execute("SELECT dirty FROM vod WHERE key=?", (key_movie,)).fetchone()[0]
c.close()
check("save_id 换成新号时把这个 key 标脏（不标脏的话查到的号永远进不了目录名）",
      got_new is True and dirty_now == 1, (got_new, dirty_now))
check("同一个号重存一遍不算新 ID（不该为此把整部片重导一次）", same_again is False)
strm.save_settings({"tag_tmdb_id": "1"})
strm.export()
p5b = sorted(str(p.relative_to(strm.ROOT)).replace(os.sep, "/")
             for p in strm.ROOT.rglob("*.strm"))
check("增量导出就把刚查到的号用上了：[tmdbid=…] 顶掉 [doubanid=…]",
      "movie/movie01/毒液：最后一舞 (2025) [tmdbid=157336]/"
      "毒液：最后一舞 (2025) [tmdbid=157336] - 虎牙资源.strm" in p5b
      and not any("doubanid=38185414" in x for x in p5b),
      [x for x in p5b if "毒液" in x][:2])
check("还没查到号的庆余年继续用豆瓣号：两颗开关都开时是「退而求其次」，不是二选一",
      any("庆余年 第二季 (2026) [doubanid=26309763]" in x for x in p5b),
      [x for x in p5b if "庆余年" in x][:1])
man5 = strm.manifest()
check("清单报得出 ID 这一项现在的状态（后台那一行就从这里取）",
      man5["ids"]["tag_tmdb_id"] and man5["ids"]["ok"] == 1
      and man5["ids"]["titles"] >= 3, man5["ids"])
pend = {r["key"] for r in strm.pending_ids()}
check("pending_ids 里不含已经命中过的片（那是白打第三方接口）", key_movie not in pend,
      sorted(pend))
c = con()
strm.save_id(c, key_tv, "tv", "庆余年 第二季", "2026", "", "none", "名字或年份没对上", 1)
strm.save_id(c, key_none, "movie", "无号片", "2026", "", "bad", "ConnectTimeout", 1)
c.commit()
pend = {r["key"] for r in strm.pending_ids()}
check("查过、确认没有的不再重查；没查成的（bad）下次还要接着试",
      key_tv not in pend and key_none in pend, sorted(pend))
n_res = strm.reset_ids(c, "none")
c.commit()
pend = {r["key"] for r in strm.pending_ids()}
c.close()
check("reset_ids 能把某个结论清掉重查（TMDB 上新增了条目的片就靠这个再问一次）",
      n_res == 1 and key_tv in pend, (n_res, key_tv in pend))
strm.save_settings({"tag_douban_id": "0", "tag_tmdb_id": "0"})
strm.export(full=True)
p5c = sorted(str(p.relative_to(strm.ROOT)).replace(os.sep, "/")
             for p in strm.ROOT.rglob("*.strm"))
check("两颗开关都关掉：整棵树回到不带标签的样子（设置和盘上必须一致）",
      not any("[" in x for x in p5c), p5c[:2])
print("\n5c) 每个 strm 一份同名 NFO")
import xml.etree.ElementTree as ET     # noqa: E402

reset_db()
cfg = strm.settings()
check("「写同名 NFO」默认是开的（用户点名要这一项）", bool(cfg["write_nfo"]), cfg["write_nfo"])
c = con()
strm.record_vod(c, "huya", "虎牙资源", mk("毒液：最后一舞", "2025", "动作片", "hym3u8",
                                          vid=1, pubdate="2025-12-30美国", douban=38185414),
                cfg, 1)
strm.record_vod(c, "apibdzy", "百度资源", mk("毒液：最后一舞", "2025", "动作片", "dbm3u8",
                                             vid=9, pubdate="2025-12-30美国"), cfg, 1)
strm.record_vod(c, "huya", "虎牙资源", mk("庆余年 第二季", "2026", "国产剧", "hym3u8", n=4,
                                          vid=11, pubdate="2026-05-16中国大陆",
                                          douban=26309763), cfg, 1)
strm.record_vod(c, "huya", "虎牙资源", mk("A&B <测试>", "2026", "动作片", "hym3u8", vid=13,
                                          pubdate="2026-06-01中国大陆"), cfg, 1)
# 上游常见的"什么都没说"的一条：评分填 0.0、简介演员都空 —— NFO 里不该出现假的 0 分
strm.record_vod(c, "huya", "虎牙资源", mk("零分无简介", "2026", "动作片", "hym3u8", vid=15,
                                          pubdate="2026-07-01中国大陆", blurb="", actor="",
                                          director="", area="", score="0.0"), cfg, 1)
c.commit()
c.close()
zN = "movie/movie01/零分无简介 (2026)/零分无简介 (2026) - 虎牙资源.nfo"
strm.export(full=True)
kv = strm.title_key(strm.display_title("毒液：最后一舞"))
strm_paths = sorted(str(p.relative_to(strm.ROOT)).replace(os.sep, "/")
                    for p in strm.ROOT.rglob("*.strm"))
nfo_paths = sorted(str(p.relative_to(strm.ROOT)).replace(os.sep, "/")
                   for p in strm.ROOT.rglob("*.nfo"))
check("每个 strm 旁边都有一份同名的 .nfo（名字差一个字 Emby 就不读了）",
      strm_paths and all(p[:-len(".strm")] + ".nfo" in nfo_paths for p in strm_paths),
      [p for p in strm_paths if p[:-5] + ".nfo" not in nfo_paths][:2])
mN = "movie/movie01/毒液：最后一舞 (2025)/毒液：最后一舞 (2025) - 虎牙资源.nfo"
root = ET.fromstring((strm.ROOT / mN.replace("/", os.sep)).read_text(encoding="utf-8"))
check("电影那份是合法 XML、根标签 <movie>", root.tag == "movie", root.tag)
check("字段齐到够 Emby 不再猜：片名/年份/上映日/类型/地区/导演/演员/简介/评分/来源/海报",
      all(root.find(t) is not None for t in ("title", "originaltitle", "sorttitle", "year",
                                             "premiered", "genre", "country", "director",
                                             "actor", "plot", "rating", "studio", "thumb")),
      [e.tag for e in root])
check("豆瓣号三种写法都给（Emby 本体不认豆瓣号，插件认哪种没法在本机验证）",
      root.findtext("doubanid") == "38185414"
      and [u.get("type") for u in root.findall("uniqueid")] == ["douban", "douban_id"],
      [(u.get("type"), u.text) for u in root.findall("uniqueid")])
check("海报写上游原地址，不走本站代理（实测这些图床不要 Referer；走代理就得为每部片登记白名单）",
      root.findtext("thumb") == "https://pic.test/1.jpg"
      and "/img?url=" not in (strm.ROOT / mN.replace("/", os.sep)).read_text(encoding="utf-8"),
      root.findtext("thumb"))
check("studio 写这条片来自哪些源（地址失效时在界面上能认出是哪一家）",
      root.findtext("studio") == "百度资源、虎牙资源", root.findtext("studio"))
c = con()
strm.save_id(c, kv, "movie", "毒液：最后一舞", "2025", "157336", "ok", "", 1)
c.commit()
c.close()
strm.export()
root2 = ET.fromstring((strm.ROOT / mN.replace("/", os.sep)).read_text(encoding="utf-8"))
check("查到 TMDB 号后 NFO 里就带上（<tmdbid> 与 uniqueid type=tmdb 都给，照 Emby 自己写的那份）",
      root2.findtext("tmdbid") == "157336"
      and any(u.get("type") == "tmdb" for u in root2.findall("uniqueid")),
      [(u.get("type"), u.text) for u in root2.findall("uniqueid")])
tvN = "tv/tv01/庆余年 第二季 (2026)/Season 02/庆余年 第二季 (2026) - S02E03 - 虎牙资源.nfo"
er = ET.fromstring((strm.ROOT / tvN.replace("/", os.sep)).read_text(encoding="utf-8"))
check("每一集是一份 <episodedetails>，写的是这一集的季号与集号",
      er.tag == "episodedetails" and er.findtext("season") == "2"
      and er.findtext("episode") == "3" and er.findtext("showtitle") == "庆余年 第二季",
      [er.tag, er.findtext("season"), er.findtext("episode")])
shN = "tv/tv01/庆余年 第二季 (2026)/tvshow.nfo"
sr = ET.fromstring((strm.ROOT / shN.replace("/", os.sep)).read_text(encoding="utf-8"))
check("剧集根目录另有一份 <tvshow>：系列级的号只能写在这里",
      sr.tag == "tvshow" and sr.findtext("doubanid") == "26309763"
      and sr.findtext("title") == "庆余年 第二季", [e.tag for e in sr][:6])
check("系列的号没有被抄进每一集（那会被 Emby 当成「某一集的号」）",
      er.find("uniqueid") is None and er.find("tmdbid") is None,
      [e.tag for e in er])
abN = [p for p in nfo_paths if "A&amp;B" in p or "A&B" in p]
raw = (strm.ROOT / abN[0].replace("/", os.sep)).read_text(encoding="utf-8") if abN else ""
check("片名里的 & 被转义、夹的 HTML 标签被剥掉（坏 NFO 等于整条不认）",
      bool(abN) and "<title>A&amp;B</title>" in raw and "<测试>" not in raw
      and ET.fromstring(raw).findtext("title") == "A&B", raw.splitlines()[2:3])
# 只改元数据：播放地址没变 → 采集判"同一条"，但 msig 变了要标脏，重写的是 NFO 不是 strm
c = con()
strm.record_vod(c, "huya", "虎牙资源", mk("毒液：最后一舞", "2025", "动作片", "hym3u8",
                                          vid=1, pubdate="2025-12-30美国", douban=38185414,
                                          blurb="换了个新简介，还是一句完整的话。"), cfg, 1)
c.commit()
c.close()
r5 = strm.export()
raw5 = (strm.ROOT / mN.replace("/", os.sep)).read_text(encoding="utf-8")
check("简介变了：NFO 被重写，一条 strm 都不重写（签名只算播放地址）",
      "新简介" in raw5 and r5["written"] >= 1 and r5["skipped"] >= 1,
      {k: r5[k] for k in ("written", "skipped")})
check("上游填的评分是 0 时不写 rating（写进去就是让 Emby 显示一个假的 0 分，比不写更糟）",
      ET.fromstring((strm.ROOT / zN).read_text(encoding="utf-8")).find("rating") is None
      and ET.fromstring((strm.ROOT / zN).read_text(encoding="utf-8")).findtext("plot") is None,
      (strm.ROOT / zN).read_text(encoding="utf-8")[:200])
strm.save_settings({"write_nfo": "0"})
strm.export(full=True)
left = sorted(strm.ROOT.rglob("*.nfo"))
still = sorted(strm.ROOT.rglob("*.strm"))
check("关掉开关：已有的 .nfo 全删干净（设置和盘上必须一致）", not left, [p.name for p in left][:3])
check("删 NFO 不动 strm：一部片、一集都没少", len(still) == len(strm_paths),
      (len(still), len(strm_paths)))
check("清单报得出 NFO 的开与份数", strm.manifest()["nfo"] == {"write": False, "files": 0},
      strm.manifest()["nfo"])
strm.save_settings({"write_nfo": "1"})
strm.export(full=True)
check("重新打开就都写回来了", strm.manifest()["nfo"]["files"] >= len(strm_paths),
      strm.manifest()["nfo"])
strm.save_settings({"tag_douban_id": "0", "tag_tmdb_id": "0"})
strm.export(full=True)

print("\n6) 下架/掉出窗口时文件要跟着删")
before = sorted(strm.ROOT.rglob("*.strm"))
n_qny = sum(1 for p in before if "庆余年" in p.name)
c = con()
c.execute("DELETE FROM vod WHERE src='apibdzy'")
gone_key = c.execute("SELECT key FROM vod WHERE title LIKE '%毒液%'").fetchone()["key"]
c.execute("DELETE FROM vod WHERE key=?", (gone_key,))
c.commit()
c.close()
fourth = strm.export()
check("库里没了的片，它的 strm 与同名 NFO 一起被删掉", fourth["removed"] >= 2, fourth)
rest = sorted(str(p.relative_to(strm.ROOT)).replace(os.sep, "/")
              for p in strm.ROOT.rglob("*.strm"))
check("被删的只有毒液那两条，庆余年一集都没少",
      not any("毒液" in r for r in rest) and sum(1 for r in rest if "庆余年" in r) == n_qny,
      (n_qny, sorted(r for r in rest if "庆余年" in r)))
check("空目录被清掉（Windows 上留一堆空目录很碍眼）",
      not (strm.ROOT / "movie" / "movie01" / "毒液：最后一舞 (2025)").exists())

print("\n7) 分卷：按文件数切、卷号稳定")
reset_db()
c = con()
c.execute("INSERT OR REPLACE INTO setting(key, value) VALUES('part_files','6')")
c.commit()
c.close()
cfg = strm.settings()
check("设置能直接读到小写的卷容量", cfg["part_files"] == 6, cfg)
c = con()
for i in range(1, 5):
    strm.record_vod(c, "huya", "虎牙资源", mk(f"第{i}号电影", "2026", "动作片", "hym3u8",
                                              vid=100 + i), cfg, 1)
    strm.record_vod(c, "suoni", "索尼资源", mk(f"第{i}号电影", "2026", "动作片", "snm3u8",
                                               vid=200 + i), cfg, 1)
c.commit()
c.close()
strm.export(full=True)
m1 = strm.part_paths("movie", "movie01")
m2 = strm.part_paths("movie", "movie02")
check("超出每卷上限后开了第二卷", m1 and m2, (len(m1), len(m2)))
check("第一卷被填满到上限（名额只数 strm，开不开同名 NFO 都不该改变卷的切法）",
      len([p for p in m1 if p.endswith(".strm")]) == 6, len(m1))
c = con()
per_folder = {}
for r in c.execute("SELECT key, part FROM file GROUP BY key, part"):
    per_folder.setdefault(r["key"], set()).add(r["part"])
check("同一部片的所有文件都在同一卷里（跨卷就是海报墙上两条同名影片）",
      all(len(v) == 1 for v in per_folder.values()), per_folder)
check("两个源的版本名不撞车（撞了就只剩一条线路，另一条被覆盖）",
      len({p.split("/")[-1] for p in m1 if p.endswith(".strm")})
      == len([p for p in m1 if p.endswith(".strm")]), m1)
c.close()
c = con()
strm.record_vod(c, "huya", "虎牙资源", mk("新来的第5号电影", "2026", "动作片", "hym3u8", vid=305),
                cfg, 2)
c.commit()
c.close()
strm.export()
m1b = strm.part_paths("movie", "movie01")
check("新片只往后追加，老片的卷号不动（换卷等于 Emby 里删了重加）",
      sorted(m1) == sorted(m1b), (m1[:2], m1b[:2]))
check("卷名解析认 movie01/movie1/MOVIE001，别的不认",
      strm._part_no("movie", "movie01") == 1 and strm._part_no("movie", "movie7") == 7
      and strm._part_no("movie", "MOVIE003") == 3 and strm._part_no("movie", "tv01") is None)

print("\n8) 分卷 zip")
zpath = strm.ZIPS / "movie01.zip"
check("打包写出了 movie01.zip", zpath.is_file())
with zipfile.ZipFile(zpath) as z:
    names = z.namelist()
    # 默认不带卷号目录：解压到媒体库根就是「片名 (年份)/…」，和 Emby 一个文件夹一部片对齐
    check("包内既不带 movie/ 那层、也不带 movie01/ 那层，直接是片名目录",
          names and all(not n.startswith(("movie", "tv")) for n in names)
          and all(n.count("/") >= 1 for n in names), names[:3])
    check("包内每个 strm 都以它所在文件夹名开头（Emby 认多版本就认这一条）",
          all(n.split("/")[-2] in n.split("/")[-1] and " - " in n.split("/")[-1]
              for n in names if n.endswith(".strm")), names[:2])
    check("每个 strm 在包里都配一份同名 .nfo（Emby 认的就是「同名 sidecar」，名字差一字它不读）",
          names and all(n[:-len(".strm")] + ".nfo" in names
                        for n in names if n.endswith(".strm")), names[:2])
    check("电影那一份是 <movie> 根标签（剧集另有 tvshow.nfo，见第 5c 节）",
          any(n.endswith(".nfo") for n in names))
    check("包里的文件数与这一卷清单一模一样",
          len(names) == len([p for p in strm.part_paths("movie", "movie01")]),
          (len(names), len(strm.part_paths("movie", "movie01"))))
    sn = [n for n in names if n.endswith(".strm")]
    first = z.read(sn[0]).decode("utf-8")
    check("包里的 strm 内容就是 m3u8 一行", first.startswith("http") and first.strip().endswith(".m3u8"),
          first[:60])
again = strm.export()["zips"]
check("内容没变就不重打包（否则同步脚本每次都要白拷一遍）",
      again["made"] == 0 and again["skipped"] >= 1, again)
# 打开"包内带卷号目录"：必须重打，而且条目要多一层 movie01/
strm.save_settings({"zip_part_dir": "1"})
sw = strm.export()["zips"]
check("改这个开关会重打所有卷（签名里带着开关，不然改了设置包还是老样子）",
      sw["made"] >= 1 and sw["skipped"] == 0, sw)
with zipfile.ZipFile(strm.ZIPS / "movie01.zip") as z:
    names2 = z.namelist()
check("打开后包里多一层卷号目录 movie01/",
      all(n.startswith("movie01/") for n in names2), names2[:2])
check("清单里那句解压说明跟着实际写法变（不写死一种）",
      "movie01/片名 (年份)" in strm.manifest()["kinds"]["movie"]["zip_hint"],
      strm.manifest()["kinds"]["movie"]["zip_hint"])
strm.save_settings({"zip_part_dir": "0"})
strm.export()
with zipfile.ZipFile(strm.ZIPS / "movie01.zip") as z:
    names3 = z.namelist()
check("关回去也照样重打，包内回到片名开头",
      names3 == names and all(not n.startswith("movie01/") for n in names3), names3[:2])
check("盘上的目录树不受包内写法影响（还是 strm/movie/movie01/…，两种写法共用一份文件）",
      (strm.ROOT / "movie" / "movie01").is_dir())
code, path, err = strm.zip_file("movie01.zip")
check("接口能取到包", code == 200 and path.endswith("movie01.zip"), (code, path, err))
# 老版本的 zip 表把 "strm_zips/movie01.zip" 整串存进了 path 列，新版只存文件名。
# 读的时候必须两种都认 —— 否则升级完代码，原来能下的包全部变成"清单里有、盘上没有了"
c = con()
c.execute("UPDATE zip SET path='strm_zips/' || path")
c.commit()
c.close()
code, path, err = strm.zip_file("movie01.zip")
check("老库里带目录前缀的 path 也照样下得来（升级不该弄坏下载）",
      code == 200 and os.path.isfile(path), (code, path, err))
c = con()
c.execute("UPDATE zip SET path=replace(path,'strm_zips/','')")
c.commit()
c.close()
check("任意文件名被拒（不是拿请求里的路径直接拼磁盘）",
      strm.zip_file("../zhuiju/data/admin.json")[0] == 400
      and strm.zip_file("strm.db")[0] == 400)
check("没打过的卷是 404 而不是 500", strm.zip_file("tv51.zip")[0] == 404)

print("\n9) 清单与索引")
man = strm.manifest()
check("清单里说清有几个 kind", set(man["kinds"]) == {"movie", "tv"}, list(man["kinds"]))
kp = man["kinds"]["movie"]["parts"]
check("每一卷都列出：名字、部数、文件数、包大小、下载地址",
      kp and all({"name", "titles", "files", "zip", "zip_bytes", "zip_url",
                  "index_url", "tree_url"} <= set(p) for p in kp), kp[:1])
check("卷名就是 movie01 这种写法（用户要的就是这个）",
      [p["name"] for p in kp] == [f"movie{i:02d}" for i in range(1, len(kp) + 1)],
      [p["name"] for p in kp])
check("清单带上了窗口与起始日", man["window_days"] == 365 and man["since"], man.get("window_days"))
check("源覆盖度按源列了出来", isinstance(man["sources"], list) and
      {s["id"] for s in man["sources"]} <= {"huya", "suoni"}, man["sources"][:2])
idx = strm.part_titles("movie", "movie01", 1, 50)
check("索引给到条目级的线路信息", idx.get("total", 0) > 0 and
      idx["items"][0]["n_sources"] >= 1 and idx["items"][0]["strm_urls"], idx.get("items", [])[:1])
check("索引里的 folder 就是 Emby 那个文件夹",
      idx["items"][0]["folder"].startswith("movie01/"), idx["items"][0]["folder"])
check("非法 kind/part 说人话", "kind" in (strm.part_titles("x", "movie01").get("error") or "")
      and "卷名" in (strm.part_titles("movie", "zz01").get("error") or ""))

print("\n10) 路径防护")
check("目录穿越被拒", strm.safe_path("../../zhuiju/data/admin.json") is None
      and strm.safe_path("movie/../../x.strm") is None
      and strm.safe_path("movie\\movie01\\..\\..\\x.strm") is None)
check("开头的斜杠被当成相对路径而不是文件系统绝对路径（仍然落在 strm/ 里）",
      str(strm.safe_path("/movie/movie01/a.strm") or "").replace("\\", "/").endswith(
          "strm/movie/movie01/a.strm"), strm.safe_path("/movie/movie01/a.strm"))
check("中间的空段也一并拒掉（宁可严一点，不给拼接留花样）",
      strm.safe_path("movie//movie01/a.strm") is None)
check("只放行 .strm 且必须在 movie/ 或 tv/ 下",
      strm.safe_path("movie/movie01/a/b.txt") is None
      and strm.safe_path("tv/tv01/a/b.strm") is not None)
check("read_strm 越界 400、没有 404", strm.read_strm("movie/x.strm")[0] == 404
      and strm.read_strm("../x.strm")[0] == 400)

print("\n11) 设置校验")
bad = strm.save_settings({"window_days": "2000", "part_files": "3000"})
check("越界值整份不保存（一半存了一半没存更难查）", bad[1] is not None and bad[0]["window_days"] == 365,
      (bad[1], bad[0]["window_days"]))
ok = strm.save_settings({"window_days": "180", "m3u8_only": "off", "exclude_srcs": "huya, suoni ; ../x"})
check("合法值保存了", ok[1] is None and ok[0]["window_days"] == 180, ok)
check("开关 checkbox 的 off 认成 0", ok[0]["m3u8_only"] == 0)
check("exclude_srcs 只留合法 id，路径与空格被丢掉",
      ok[0]["exclude_srcs"] == "huya,suoni", ok[0]["exclude_srcs"])
check("非法输入不会把已有设置改成半套",
      strm.settings()["window_days"] == 180)
check("页面要渲染的行里带了上下界和说明",
      all({"key", "label", "value", "lo", "hi", "kind", "help"} <= set(r) for r in strm.spec_rows()),
      strm.spec_rows()[:1])
strm.save_settings({"window_days": "365", "m3u8_only": "1"})

print("\n11b) 库正被采集/导出写时，保存设置要说人话而不是抛 500")
# 真场景就是这一条：导出要写几千个文件、打包要算清单，期间人在后台点"保存设置"。
# WAL 只允许一个写者，以前这里直接把 sqlite3.OperationalError 抛到 Flask 外面（实测 500）。
holder = con()
holder.execute("BEGIN IMMEDIATE")
holder.execute("INSERT INTO setting(key, value) VALUES('__hold', '1')")
real_connect, real_sleep = strm.connect, time.sleep


def quick_connect():
    c2 = real_connect()
    c2.execute("PRAGMA busy_timeout=100")     # 真连接等 6 秒，测试里等不起
    return c2


strm.connect = quick_connect
strm.time = type("T", (), {"sleep": staticmethod(lambda s: None),
                           "time": time.time, "strftime": time.strftime,
                           "localtime": time.localtime})()
try:
    _cfg, err = strm.save_settings({"window_days": "90"})
finally:
    strm.connect = real_connect
    strm.time = time
check("被占用时返回的是一句说明，不是异常", bool(err) and "没写进去" in (err or ""), err)
check("占用失败时窗口值没被改走", strm.settings()["window_days"] == 365,
      strm.settings()["window_days"])
holder.rollback()
holder.close()
check("锁放开之后再保存就成功了", strm.save_settings({"window_days": "90"})[1] is None)
strm.save_settings({"window_days": "365"})

print("\n11c) TMDB key 与接口地址：不回显、留空=不改、形状不对要拒")
strm.save_settings({"tmdb_api_key": "abc123456789"})
check("key 存得进去", strm.settings()["tmdb_api_key"] == "abc123456789",
      strm.settings()["tmdb_api_key"])
nxt, err = strm.save_settings({"tmdb_api_key": ""})
check("表单里留空提交不改已存的 key —— 页面上不回显，靠的就是这一条；"
      "否则别人点一次「保存设置」就把 key 擦了，还查不到是谁擦的",
      nxt["tmdb_api_key"] == "abc123456789" and err is None, (nxt["tmdb_api_key"], err))
nxt, err = strm.save_settings({"tmdb_api_key": "a b'c"})
check("带空格/引号的 key 拒收，整份都不写", bool(err)
      and strm.settings()["tmdb_api_key"] == "abc123456789", err)
nxt, err = strm.save_settings({"tmdb_host": "javascript:alert(1)"})
check("接口地址只认 http(s)://主机[:端口][/路径]", bool(err), (err, nxt["tmdb_host"]))
strm.save_settings({"tmdb_host": ""})
check("地址留空退回默认值（存空串等于开关开着却一部都查不出来）",
      strm.settings()["tmdb_host"] == "https://api.tmdb.org/3", strm.settings()["tmdb_host"])
rows = {r["key"]: r for r in strm.spec_rows()}
check("密钥那一行给页面的应该是空值 + filled=True（模板据此显示「已经存着了」）",
      rows["tmdb_api_key"]["value"] == "" and rows["tmdb_api_key"]["filled"] is True
      and rows["tmdb_api_key"]["secret"] is True, dict(rows["tmdb_api_key"]))
c = con()
c.execute("DELETE FROM setting WHERE key='tmdb_api_key'")
c.commit()
c.close()
check("两边都没有时清单报的是 tmdb_key=False（不能让人以为这一支在跑）",
      strm.settings()["tmdb_api_key"] == "" and strm.manifest()["ids"]["tmdb_key"] is False,
      strm.manifest()["ids"])
os.environ["ZHUIJU_TMDB_KEY"] = "envkey12345678"
check("库里空着时退到环境变量 ZHUIJU_TMDB_KEY（服务器上不想把 key 落进库的人靠这条）",
      strm.settings()["tmdb_api_key"] == "envkey12345678", strm.settings()["tmdb_api_key"])
del os.environ["ZHUIJU_TMDB_KEY"]

print("\n12) 接口（test_client，全部离线）")
client = app_mod.create_app().test_client()
r = client.get("/api/strm/manifest")
check("GET /api/strm/manifest 是公开可读的 200", r.status_code == 200, r.status_code)
jm = r.get_json()
check("清单里带采集任务状态（在不在跑、下次还要等多久）",
      "job" in jm and "running" in jm["job"], list(jm)[:8])
r = client.get("/api/strm/index?kind=movie&part=movie01&per=5")
check("GET /api/strm/index 能按卷取条目", r.status_code == 200 and r.get_json()["items"],
      r.status_code)
r = client.get("/api/strm/index?kind=zzz&part=movie01")
check("kind 不对时 400 而不是 500", r.status_code == 400, r.status_code)
r = client.get("/api/strm/tree?kind=movie&part=movie01")
check("GET /api/strm/tree 一行一个（能直接 curl 给脚本用）",
      r.status_code == 200 and "text/plain" in r.headers["Content-Type"]
      and len(r.get_data(as_text=True).strip().splitlines()) >= 2, r.status_code)
r = client.get("/api/strm/tree?kind=movie&part=movie99")
check("没有的卷 404", r.status_code == 404)
r = client.get("/strm/zip?name=movie01.zip")
check("GET /strm/zip 下载分卷包", r.status_code == 200 and len(r.get_data()) > 22,
      (r.status_code, len(r.get_data())))
check("下载头带文件名", "movie01.zip" in (r.headers.get("Content-Disposition") or ""),
      r.headers.get("Content-Disposition"))
cd = r.headers.get("Content-Disposition") or ""
check("文件名就是卷名本身，不带任何路径（不能出现 E:\\ 或 strm_zips/ 这种）",
      "filename=movie01.zip" in cd and "\\" not in cd and "/" not in cd.split("filename=")[-1],
      cd)
check("清单里 zip 字段也是裸文件名（下载接口认的就是它）",
      all(p["zip"] == f"{p['name']}.zip" for p in strm.manifest()["kinds"]["movie"]["parts"]),
      strm.manifest()["kinds"]["movie"]["parts"][:1])
r = client.get("/strm/zip?name=../../zhuiju/data/admin.json")
check("包名不合法时 400（挡掉任意文件下载）", r.status_code == 400, r.status_code)
one_path = [q for q in strm.part_paths("movie", "movie01") if q.endswith(".strm")][0]
r = client.get("/strm/file?path=" + quote(one_path))
check("GET /strm/file 取单个 strm", r.status_code == 200 and r.get_data(as_text=True).startswith("http"),
      r.status_code)
r = client.get("/strm/file?path=../../requirements.txt")
check("单个文件接口同样挡住穿越", r.status_code == 400, r.status_code)
r = client.get("/api/strm/status")
st = r.get_json()
check("状态接口带上了设置、库计数和上次结果",
      r.status_code == 200 and "settings" in st and "counts" in st, r.status_code)

print("\n12b) 扁平下载清单 /api/strm/download")
r = client.get("/api/strm/download")
dm = r.get_json()
check("键就两组，名字按约定的 Movies / TVs", set(dm) == {"Movies", "TVs"}, list(dm))
check("值就是能直接 GET 的包地址，且文件名是裸卷名（没有路径）",
      dm["Movies"] and all(v.endswith(f"/strm/zip?name={k}") and "/" not in k
                           and k.endswith(".zip") for k, v in dm["Movies"].items()),
      list(dm["Movies"].items())[:2])
check("默认给绝对地址（清单常在另一台机器上照着敲，相对地址离开本站就没用）",
      all(v.startswith("http://") for v in dm["Movies"].values()),
      next(iter(dm["Movies"].values()), None))
check("?abs=0 退成相对地址",
      all(v.startswith("/strm/zip?") for v in
          client.get("/api/strm/download?abs=0").get_json()["Movies"].values()))
one_name, one_url = next(iter(dm["Movies"].items()))
rr = client.get(one_url.replace("http://localhost", ""))
check("清单里给出的地址真能下到包", rr.status_code == 200 and len(rr.get_data()) > 22,
      (one_name, rr.status_code, len(rr.get_data())))
check("电影卷和电视剧卷不会混（Movies 里全是 movieNN.zip）",
      all(k.startswith("movie") for k in dm["Movies"])
      and all(k.startswith("tv") for k in dm["TVs"]), (list(dm["Movies"]), list(dm["TVs"])))
# 用有数据的那一组来验顺序：第 7 节重置过库，这一节里 TVs 可能本来就是空的，
# 拿空列表断言顺序等于什么都没测
order_grp = "Movies" if dm["Movies"] else "TVs"
check("卷号按数值顺序排（不是 movie10 排在 movie2 前面）",
      len(dm[order_grp]) >= 2 and
      list(dm[order_grp]) == sorted(dm[order_grp], key=lambda x: int(re.search(r"\d+", x).group())),
      (order_grp, list(dm[order_grp])))
# 盘上没有对应文件的卷不该出现在下载清单里（那是死链）。
# 这里往库里塞一条"第 77 卷"的记录，但根本不打包 —— 比把真文件改名安全：
# send_file 之后响应对象还握着那个文件句柄，Windows 上改名会直接 PermissionError
c = con()
c.execute("INSERT OR REPLACE INTO zip(kind, part, path, files, titles, bytes, sig, built_at)"
          " VALUES('movie', 77, 'movie77.zip', 1, 1, 10, 'x', ?)", (strm.now(),))
c.commit()
c.close()
dm2 = strm.download_map("http://127.0.0.1:5000")
check("文件不在盘上的卷不进下载清单（不给死链）",
      "movie77.zip" not in dm2["Movies"], list(dm2["Movies"]))
check("同一份清单带站点根地址时是完整 URL",
      all(v.startswith("http://127.0.0.1:5000/strm/zip?name=") for v in dm2["TVs"].values()),
      next(iter(dm2["TVs"].values()), None))
c = con()
c.execute("DELETE FROM zip WHERE part=77")
c.commit()
c.close()
check("清掉那条假记录后清单回到实际状态",
      "movie77.zip" not in strm.download_map()["Movies"])

print("\n12c) 清单里的地址跟着「人是怎么访问的」走")
r = client.get("/api/strm/download", headers={"Host": "123.com"})
u = next(iter(r.get_json()["Movies"].values()))
check("用 Host: 123.com 访问，URL 的头就是 http://123.com",
      u.startswith("http://123.com/strm/zip?name="), u)
r = client.get("/api/strm/download", headers={"Host": "123.com:8443"})
check("带端口也照抄（本站自己监听在 8443 时不会把端口丢掉）",
      next(iter(r.get_json()["Movies"].values())).startswith("http://123.com:8443/strm/zip?"),
      next(iter(r.get_json()["Movies"].values())))
r = client.get("/api/strm/download", headers={"X-Forwarded-Proto": "https",
                                              "X-Forwarded-Host": "video.example.cn"})
u = next(iter(r.get_json()["Movies"].values()))
check("nginx 反代（上一跳是回环）下按 X-Forwarded-* 出 https + 对外域名",
      u.startswith("https://video.example.cn/strm/zip?name="), u)
r = client.get("/api/strm/download?abs=0", headers={"Host": "123.com"})
d0 = r.get_json()
check("?abs=0 时仍然只给相对地址（不受 Host 影响）",
      all(v.startswith("/strm/zip?name=") for g in ("Movies", "TVs") for v in d0[g].values())
      and bool(d0["Movies"] or d0["TVs"]),
      {k: list(v.values())[:1] for k, v in d0.items()})

print("\n13) 后台页与登录门槛（后台已转 React：门槛在 /api/admin/view，那一屏数据在它的 JSON 里）")
# (a) 后台转 React 后 /admin 只是一个壳（admin_shell.html + spa/admin.js），
# Emby STRM 那一屏的数据全在 GET /api/admin/view?tab=strm 的 JSON 里（smeta / sspec / sjob）。
# 没登录时这个接口回 401，真正的门槛从「/admin 回口令页」搬到了这里。原来钉 HTML 的每条判据逐条搬：
# 数据搬到 view 的 smeta/sspec/sjob，写法（表单、按钮、四类状态文案）搬到 web/src/admin/Strm.tsx。
strm_tsx = (BASE / "web" / "src" / "admin" / "Strm.tsx").read_text(encoding="utf-8")
ui_tsx = (BASE / "web" / "src" / "admin" / "ui.tsx").read_text(encoding="utf-8")
clamp_ts = (BASE / "web" / "src" / "hooks" / "useClamp.ts").read_text(encoding="utf-8")
admin_api_ts = (BASE / "web" / "src" / "admin" / "api.ts").read_text(encoding="utf-8")
shell = client.get("/admin").get_data(as_text=True)
denied = client.get("/api/admin/view?tab=strm").get_json()
# (a) 「没登录时后台仍是口令页」：壳本身是公开的 200，门槛挪到了 view 的 401。
#     「口令页里看不到采集设置」：未登录的 view body 里根本没有 smeta/sspec 这些字段。
check("没登录时后台壳仍公开 200，但真正的门槛在 /api/admin/view 回 401（STRM 设置不能公开改）",
      client.get("/admin").status_code == 200 and denied.get("authed") is False
      and client.get("/api/admin/view?tab=strm").status_code == 401, denied.get("authed"))
check("未登录的 view 里没有任何采集设置或分卷数据",
      "smeta" not in denied and "sspec" not in denied, list(denied)[:8])
tok = denied["csrf"]
admin_mod.set_password("strm-test-mima")
r = client.post("/admin/login", data={"csrf": tok, "password": "strm-test-mima"})
check("登录成功跳回 /admin", r.status_code == 302, r.status_code)
sv = client.get("/api/admin/view?tab=strm").get_json()
# (a) 「登录后 200」：壳 200 且后台入口 admin.js 上屏，view 回 authed=True。
check("登录后台壳与 view 都上屏（壳里挂着后台入口 spa/admin.js、view 回 authed=True）",
      "spa/admin.js" in shell and sv.get("authed") is True, (shell.count("spa/admin.js"), sv.get("authed")))
check("后台出现了 Emby STRM 这一标签（标签名与它归的几块由服务端 tabs 下发）",
      any(t["id"] == "strm" and t["label"] == "Emby STRM"
          and [b[0] for b in t["blocks"]] == ["strm", "strm-zips", "strm-src"] for t in sv["tabs"]),
      [(t["id"], t["label"]) for t in sv["tabs"]])
parts = sv["smeta"]["kinds"]["movie"]["parts"]
check("分卷表里有 movie01 且带指向 /strm/zip 的下载地址（数据来自 view 的 smeta.kinds）",
      any(p["name"] == "movie01" and p["zip_url"] == "/strm/zip?name=movie01.zip" for p in parts),
      [(p["name"], p["zip_url"]) for p in parts][:3])
check("设置表单提交走 postForm→fetch、csrf 从请求头带（不然是个可被外部提交的表单）",
      'postForm("/admin/strm/settings"' in strm_tsx and '"X-CSRF-Token": csrf' in admin_api_ts, None)
sspec = sv["sspec"]
check("时间范围这一项在设置里（用户点名要能后台设）",
      any(f["key"] == "window_days" and "采集时间范围" in f["label"] for f in sspec),
      [(f["key"], f["label"]) for f in sspec][:4])
# (b) 旧那句「一个 strm 只对应一部片/一集」的解释散文只在死掉的 admin.html 里，SPA 不渲染它；
#     这条不变量还活着的另一半是命名规则本身（片名 (年份)），它随设置项的 help 由服务端下发。
check("命名规则里写了片名 (年份) 这一格式（随设置项 help 下发；那段解释散文随老模板一起退役）",
      any("片名 (年份)" in (f.get("help") or "") for f in sspec)
      and "f.help" in strm_tsx, [f["key"] for f in sspec if f.get("help")])
tok = sv["csrf"]
r = client.post("/admin/strm/settings", data={"csrf": tok, "window_days": "90",
                                             "part_files": "3000", "delay_ms": "400",
                                             "workers": "3", "budget_seconds": "900",
                                             "max_eps_per_title": "120",
                                             "max_lines_per_src": "1", "enabled": "1",
                                             "m3u8_only": "1", "exclude_srcs": "",
                                             "min_interval_minutes": "30"},
                follow_redirects=False)
check("保存设置 302 回到 Emby STRM 那个标签（只带 #strm 锚点不够：那一节被 CSS 藏着，"
      "看着就像跳回了后台首页）",
      r.status_code == 302 and "tab=strm" in r.headers["Location"]
      and "#strm" in r.headers["Location"], r.headers.get("Location"))
check("设置真的写进了库", strm.settings()["window_days"] == 90, strm.settings())
r = client.post("/admin/strm/settings", data={"csrf": "deadbeef", "window_days": "999"},
                follow_redirects=False)
check("csrf 不对时改不动设置", r.status_code == 400 and strm.settings()["window_days"] == 90)
# 异步那条路：页面不重载，接口回一句 JSON + 刷新要用的两份文案
r = client.post("/admin/strm/settings", headers={"X-Requested-With": "fetch"},
                data={"csrf": tok, "window_days": "180"}, follow_redirects=False)
j = r.get_json() or {}
check("带 X-Requested-With: fetch 的提交回 JSON，不是一跳 302",
      r.status_code == 200 and j.get("ok") is True and "已保存" in (j.get("msg") or ""),
      (r.status_code, j.get("msg")))
check("JSON 里带着那两句话（JS 刷新读的就是它，和模板渲染同一份文案）",
      "目录名 ID 标签" in (j.get("lines") or {}).get("ids", "")
      and (j.get("lines") or {}).get("nfo", "").startswith("NFO："), j.get("lines"))
check("校验没过时也回 JSON 并且说清哪儿不对（异步提交不能只给个红叉）",
      client.post("/admin/strm/settings", headers={"X-Requested-With": "fetch"},
                  data={"csrf": tok, "window_days": "3"}).get_json()["ok"] is False,
      None)
check("窗口 3 天这种非法值没写进库", strm.settings()["window_days"] == 180,
      strm.settings()["window_days"])

print("\n13c) 页面上的 ID 那一行与「重查没命中的」按钮")
strm.save_settings({"window_days": "365", "tag_douban_id": "1", "tag_tmdb_id": "1",
                    "tmdb_api_key": "testkey12345678"})
c = con()
kk = strm.title_key(strm.display_title("重查测试片"))
strm.record_vod(c, "huya", "虎牙资源", mk("重查测试片", "2026", "动作片", "hym3u8", vid=555),
                strm.settings(), 1)
strm.save_id(c, kk, "movie", "重查测试片", "2026", "", "none", "名字或年份没对上", 1)
c.commit()
c.close()
sv2 = client.get("/api/admin/view?tab=strm").get_json()
lines = sv2["sjob"]["lines"]
sspec2 = sv2["sspec"]
# (a) 旧几条都从 /admin 的 HTML 里 grep 文案；这些文案是服务端算好放进 view 的
#     sjob.lines（ID 那一行、NFO 那一行）与 sspec（每个设置项的 label/secret/filled）里，
#     渲染写法则在 Strm.tsx。逐条搬过去钉。
check("后台说得出 ID 这一项的状态（开/关、key 配没配、命中多少、还剩多少没查）",
      "目录名 ID 标签" in lines["ids"] and "还没查" in lines["ids"]
      and re.search(r"查到号 \d+ 部", lines["ids"]), lines["ids"][:120])
keyrow = next((f for f in sspec2 if f["key"] == "tmdb_api_key"), {})
check("密钥那一栏是 password 输入框且不回显存着的值（服务端根本不下发明文凭据）",
      keyrow.get("secret") is True and keyrow.get("value") == ""
      and 'f.secret' in strm_tsx and 'type="password"' in strm_tsx and 'value=""' in strm_tsx,
      {k: keyrow.get(k) for k in ("secret", "value", "filled")})
check("已经存了 key 时要有「已经存着了」这句提示",
      keyrow.get("filled") is True and "已经存着了" in strm_tsx, keyrow)
# (c) 判据不变（重查那颗按钮在、份数不写在按钮上），只是载体从 admin.html 换成 Strm.tsx；
#     文案那对引号也从「」改成了组件里实际用的『』。
check("重查那颗按钮在页面上（份数不写在按钮上：一按就清，标签上的数字当场变假）",
      'action="/admin/strm/recheck"' in strm_tsx and "重查 TMDB 说『没有』的那些" in strm_tsx,
      re.findall(r"重查 TMDB[^\"’]*", strm_tsx)[:1])
check("NFO 那一行也在，说得出开/关与代价",
      re.search(r"NFO：(开|关)", lines["nfo"]) is not None and "NFO：" in strm_tsx,
      lines["nfo"][:80])
# (b) bindForms()/X-Requested-With 是旧版整页 HTML 里那段手工 JS，React 里没有对应物：
#     表单提交改由 onSubmit{ e.preventDefault() } + postForm 走 fetch。等价形态钉这个新写法。
check("这一节里的表单都是异步提交的（React 拦下 submit 走 postForm，页面不重载）",
      strm_tsx.count("e.preventDefault()") >= 1 and 'postForm("/admin/strm/settings"' in strm_tsx
      and '"X-Requested-With": "fetch"' in admin_api_ts, None)
n_before = len(SPAWNED)
# 前面几次 GET 可能已经顺手拉起过一轮，锁里那个 PID（测试进程自己）还活着，
# 那样 start_now() 只会回"已经有一轮在跑"。先把锁和状态清掉，测的才是这颗按钮本身。
for _p in (strmjob.LOCK, strmjob.STATE):
    try:
        _p.unlink()
    except OSError:
        pass
strmjob._last[0] = 0.0
r = client.post("/admin/strm/recheck", data={"csrf": "deadbeef"}, follow_redirects=False)
check("没带对 csrf 就清不掉结论（这颗按钮会起后台任务，不能被人外部提交）",
      r.status_code == 400, r.status_code)
tok = client.get("/api/admin/view?tab=strm").get_json()["csrf"]
r = client.post("/admin/strm/recheck", data={"csrf": tok}, follow_redirects=False)
loc = r.headers.get("Location", "")
check("按一下就清掉 none 并起一轮去重查", r.status_code == 302 and "strm_recheck=1" in loc
      and "#strm" in loc, loc)
check("清掉之后库里那条 none 没了（下一轮就会把它当没查过的重问）",
      kk in {x["key"] for x in strm.pending_ids()}, sorted(x["key"] for x in strm.pending_ids()))
check("重查这一按真的拉起了一轮后台任务（不是只清了数据库就完事）",
      len(SPAWNED) == n_before + 1, SPAWNED[n_before - 1:n_before + 1])
smsg = client.get("/api/admin/view?tab=strm&strm_recheck=3&strm_run=1").get_json()["smsg"]
check("跳回后台后那句话要说清「清掉几条」和「有没有起一轮」（文案在 view 的 smsg 里）",
      "清掉 3 条" in smsg and "已拉起" in smsg, smsg[:120])

print("\n13b) 那一节的实时进度（不用手动刷新也在动）")
r = client.get("/api/strm/status")
stt = r.get_json()
check("状态接口带上了游标（页脚那张表就地更新要靠它）",
      "cursor" in stt and isinstance(stt["cursor"], dict), list(stt)[:10])
check("游标里能读到页码与停下来原因（和模板同一口径）",
      all({"pg", "stop", "requests", "last_time"} <= set(v.keys())
          for v in stt["cursor"].values()) if stt["cursor"] else True,
      list(stt["cursor"].values())[:1])
sv3 = client.get("/api/admin/view?tab=strm").get_json()
# (b) 旧这几条钉的是死掉的 admin.html 里那套手工更新的 DOM 锚点（id="strm-state" 等、
#     data-running、dispatchEvent('resize')、refreshParts、textContent vs innerHTML）。
#     转 React 后整块由 view 快照渲染、轮询只更新 sjob，滚动框高度由 ResizeObserver 量、
#     文案走 JSX 天然转义——每条各搬到它在新架构里的等价载体上。
check("采集状态、库计数、游标表、分卷表都在（三块各自的 Block 由 Strm.tsx 渲染，不再靠手工锚点）",
      all(f'<Block id="{x}"' in strm_tsx for x in ("strm", "strm-zips", "strm-src"))
      and "stateLine(job)" in strm_tsx, [x for x in ("strm", "strm-zips", "strm-src")
      if f'<Block id="{x}"' not in strm_tsx])
check("库里没游标时那张表也照样给出（首轮进度才有地方落），并留一句「还没采过」",
      "(meta.cursor || []).length" in strm_tsx and "还没采过" in strm_tsx, None)
check("两类分卷表都在（tv 一类还没打包时也要有地方填第一轮的结果）",
      '["movie", "tv"].map((kind)' in strm_tsx, None)
# (b) 内联滚动框重量高度：旧版往 DOM 里塞完行后 dispatchEvent('resize') 逼 foldH 重算；
#     现在 Table 的限高统一走 hooks/useClamp：ResizeObserver 管宽度，MutationObserver 管行落地。
check("行塞进去之后会重量一次内联滚动框高度（旧靠手动 resize 事件，现在是 useClamp 的两个 observer）",
      "new ResizeObserver" in clamp_ts and "new MutationObserver" in clamp_ts
      and "dispatchEvent" not in strm_tsx, None)
# (b) data-running 那个「多久问一次」的开关写在 DOM 属性上，React 里没有：
#     节奏直接由 status 接口回来的 running 决定。
check("轮询节奏由状态接口回来的 running 决定（不再有 data-running 那个 DOM 开关）",
      "const j = (await r.json()) as StrmJob;" in strm_tsx
      and "j.running ? 10000 : 60000" in strm_tsx, None)
check("轮询只问状态接口，且回到标签页立刻补一次",
      '"/api/strm/status"' in strm_tsx and "visibilitychange" in strm_tsx
      and "document.hidden" in strm_tsx, None)
check("在跑的时候 10 秒一次、闲下来 60 秒一次（不是越看越勤地把站点打死）",
      "10000" in strm_tsx and "60000" in strm_tsx, None)
# (b) 旧版在"这一轮刚结束"时用 /api/strm/manifest 单独重建分卷表；React 里分卷直接来自
#     进这一屏时那份 view 快照的 smeta，轮询只换 sjob、不回拉清单。等价形态：parts 读 v.smeta、
#     轮询不碰 smeta。
check("分卷表读的是进这一屏那份 view 快照，不跟着每次轮询重新拉清单",
      "const meta = v.smeta!;" in strm_tsx and "/api/strm/manifest" not in strm_tsx, None)
# (b) textContent vs innerHTML 那半在新架构没有对应物（React 里根本没有手工塞 HTML 的口子）：
#     JSX 表达式默认转义。钉「不用 dangerouslySetInnerHTML 这个逃生口」作等价的那一半。
check("更新文案不会把外部字符串当 HTML 塞进去（旧用 textContent 防注入，React 靠 JSX 默认转义）",
      "dangerouslySetInnerHTML" not in strm_tsx and "{c.src}" in strm_tsx and "{s.name}" in strm_tsx,
      None)
check("这一节仍然说得出在不在跑（服务端四种状态文案都在组件里）",
      all(t in strm_tsx for t in ("正在后台采集", "现在访问网站就会拉起一轮",
                                  "采集开关是关的", "这一轮跑完了，在等最小间隔")), None)
check("分卷那一行写的是真实卷名，不是 movieNN 这种程序员占位符（页面上没人认识 NN）",
      all(p["name"] != "movieNN" for p in sv3["smeta"]["kinds"]["movie"]["parts"])
      and "movieNN" not in strm_tsx and "movie01、movie02" in strm_tsx
      and "tv01、tv02" in strm_tsx, [p["name"] for p in sv3["smeta"]["kinds"]["movie"]["parts"]][:4])

print("\n14) 访问触发（spawn 换成了记账桩，不会真起进程）")
import time  # noqa: E402


def clean_job():
    """把锁和状态文件都清掉、缓存的结论也清掉，让每次判定都从头算。"""
    strmjob._last[0] = 0.0
    for p in (strmjob.LOCK, strmjob.STATE):
        try:
            p.unlink()
        except OSError:
            pass


SPAWNED.clear()
strm.save_settings({"enabled": "1", "min_interval_minutes": "30"})
clean_job()
check("从没跑过就该触发", strmjob.needs_trigger() is True)
check("触发结论是 started", strmjob.maybe_trigger() == "started", strmjob._last[1])
check("真的只调了 spawn 一次", len(SPAWNED) == 1, SPAWNED)
check("spawn 的参数里带上了本轮预算", "--budget" in SPAWNED[0], SPAWNED[0])
strmjob._last[0] = 0.0
check("锁里的进程还在跑时不重复起（反复刷新页面不该把同一轮排好几遍）",
      strmjob.maybe_trigger() == "running", strmjob._last[1])
strmjob.LOCK.write_text("2147483646 0", encoding="utf-8")     # 一个已经不存在的 PID
strmjob._last[0] = 0.0
check("锁里的进程已经不在了就重新起（否则一次崩溃会让页面永远假装在跑）",
      strmjob.maybe_trigger() == "started", strmjob._last[1])
strmjob.LOCK.unlink()
strmjob.STATE.write_text(json.dumps({"at": strm.now(), "ok": True}), encoding="utf-8")
strmjob._last[0] = 0.0
check("刚跑完就访问不会立刻再跑（最小间隔挡着）",
      strmjob.needs_trigger() is False and strmjob.next_in() > 0, strmjob.next_in())
check("冷却期的触发结论是 cooldown", strmjob.maybe_trigger() == "cooldown", strmjob._last[1])
old = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 99999))
strmjob.STATE.write_text(json.dumps({"at": old, "ok": True}), encoding="utf-8")
strmjob._last[0] = 0.0
check("间隔过了就又能触发", strmjob.needs_trigger() is True)
strm.save_settings({"enabled": "0"})
strmjob._last[0] = 0.0
n_before = len(SPAWNED)
check("开关关掉后结论是 disabled，且一个进程都不起",
      strmjob.maybe_trigger() == "disabled" and len(SPAWNED) == n_before,
      (strmjob._last[1], len(SPAWNED)))
strm.save_settings({"enabled": "1"})
# 这里不打 GET "/"：首页的 before_request 也会拉 tools/refresh.py（那要联网），
# 离线测试里碰它就成了"测试顺手敲了一遍第三方接口"。/admin 只挂采集这一条。
clean_job()
n1 = len(SPAWNED)
client.get("/admin")
check("访问后台也算一次访问（看进度的人顺手让它往前走一格）",
      len(SPAWNED) == n1 + 1, (n1, len(SPAWNED)))
clean_job()
n2 = len(SPAWNED)
client.get("/api/strm/manifest")
check("但纯接口调用不算访问（脚本轮询进度不该把采集越催越急）",
      len(SPAWNED) == n2, (n2, len(SPAWNED)))

print("\n15) 采集脚本：轮次判断与进度合并（导入脚本模块，不发请求）")
spec = importlib.util.spec_from_file_location("collect_strm", strmjob.SCRIPT)
col = importlib.util.module_from_spec(spec)
spec.loader.exec_module(col)
col.PROGRESS = TMP / "col_progress.json"
col.STATE = TMP / "col_state.json"
col._shared.update({"requests": 0, "pages": 0, "new": 0, "changed": 0,
                    "since_flush": 0, "last_flush": time.time()})
col.progress(running=True, per_src={"huya": {"pg": 5}}, reset_per_src=True)
col.progress(per_src={"suoni": {"pg": 7}})
p = json.loads(col.PROGRESS.read_text(encoding="utf-8"))
check("各线程的进度是合并不是覆盖（覆盖一次就只剩一个源）",
      set(p["per_src"]) == {"huya", "suoni"}, list(p["per_src"]))
col.progress(running=True, per_src={"huya": {"pg": 1}}, reset_per_src=True)
p = json.loads(col.PROGRESS.read_text(encoding="utf-8"))
check("新一轮开始时把上一轮的页码清掉（留着会看起来还在很后面）",
      set(p["per_src"]) == {"huya"}, list(p["per_src"]))
c = con()
c.execute("DELETE FROM cur")
strm.save_cursor(c, "huya", 50, False, 3, "2026-01-01", 0, 50, stop="budget")
strm.save_cursor(c, "suoni", 20, False, 3, "2026-02-01", 0, 20, stop="budget")
check("还有没翻完的游标就接着那一轮（一轮不该被拆成两轮）",
      col.decide_pass(c) == (3, []), col.decide_pass(c))
c.execute("UPDATE cur SET done=1")
pass_id, reset = col.decide_pass(c)
check("全翻完就起新一轮并复位", pass_id == 4 and set(reset) == {"huya", "suoni"}, (pass_id, reset))
c.commit()
c.close()

print("\n15b) 游标那一列「已翻页数」是本轮累计（不是这一批几页）")


class FakeSrc:
    id, name, api, params = "hhzy", "火狐资源", "https://hhzyapi.com/api.php/provide/vod/", {}


c = con()
c.execute("DELETE FROM cur")
c.commit()
c.close()
real_fetch = col.fetch_page
pages_seen = []


def fake_fetch(src, pg):
    pages_seen.append(pg)
    # 每页给一条新的、在窗口内的条目：这样 record_vod 判 new，known 不会被累加干扰
    return {"ok": True, "pagecount": 999, "error": None,
            "items": [mk(f"第{pg}页的片子", "2026", "动作片", "hhm3u8", vid=9000 + pg)]}


col.fetch_page = fake_fetch
cfg = strm.settings()
col.crawl_src(FakeSrc(), cfg, 7, strm.cutoff(cfg), time.time() + 60, 0.0, 3)
cur1 = strm.cursors()["hhzy"]
col.crawl_src(FakeSrc(), cfg, 7, strm.cutoff(cfg), time.time() + 60, 0.0, 3)
cur2 = strm.cursors()["hhzy"]
col.fetch_page = real_fetch
check("第一批翻 3 页 → 游标记 3", cur1["requests"] == 3, cur1)
check("第二批再翻 3 页 → 游标记 6（累计，不是被覆盖成 3 或 2）",
      cur2["requests"] == 6, cur2)
check("页码也确实往前走了", pages_seen[:6] == [1, 2, 3, 4, 5, 6], pages_seen)
check("下一跳页码 = 已翻页数 + 1", cur2["pg"] == 7, cur2)

print("\n15c) 查 TMDB：命中判据（这一步决定会不会把一部片指到另一部片上）")
# 全部拿手造的搜索结果验，不打接口：pick_hit 是纯函数
K = strm.title_key(strm.display_title("星际穿越"))
hit = [{"id": 157336, "title": "星际穿越", "original_title": "Interstellar",
        "release_date": "2014-11-07", "popularity": 90}]
check("片名（中文 title）对得上、年份对得上 → 就用这个号",
      col.pick_hit(hit, K, "2014") == ("157336", ""), col.pick_hit(hit, K, "2014"))
check("只有英文原名对得上也算命中（TMDB 的 title/original_title 谁中文谁英文不固定）",
      col.pick_hit([{"id": 157336, "title": "Interstellar", "original_title": "Interstellar",
                     "release_date": "2014-11-07"}],
                   strm.title_key(strm.display_title("Interstellar")), "2014")[0] == "157336")
check("名字对得上但年份差一年 → 不写（这是另一部片，写进去 Emby 就直接认错）",
      col.pick_hit([{"id": 999, "title": "星际穿越", "release_date": "2015-01-01"}],
                   K, "2014") == ("", "名字或年份没对上（不敢硬塞）"))
check("名字对不上绝不硬塞（哪怕只有一个搜索结果、 popularity 再高也不行）",
      col.pick_hit([{"id": 1, "title": "流浪地球", "release_date": "2019-01-01"}],
                   K, "2014")[0] == "")
check("没有搜索结果时说得出原因（后台那一行要用）",
      col.pick_hit([], K, "2014") == ("", "TMDB 搜不到这个名字"))
check("剧集用 name/first_air_date 那套字段（TMDB 两个搜索接口字段名不一样）",
      col.pick_hit([{"id": 1396, "name": "绝命毒师", "original_name": "Breaking Bad",
                     "first_air_date": "2008-01-20"}],
                   strm.title_key(strm.display_title("绝命毒师")), "2008")[0] == "1396")
check("上游年份是空时只按名字判（不能因为没年份就全部否掉）",
      col.pick_hit(hit, K, "")[0] == "157336")
check("没配 key 时 tmdb_get 直接拒，连请求都不发（这一支不能因为设置没填就白打）",
      col.tmdb_get({"tmdb_api_key": ""}, "/search/movie", {})["error"] == "没有配 TMDB API Key")
cfg_i = dict(strm.settings())
cfg_i.update({"tmdb_api_key": "", "tmdb_per_round": 5})
r0 = col.resolve_ids(cfg_i, time.time() + 1, 0)
check("没配 key 时整支一句原因就走，一次接口都不打",
      r0["asked"] == 0 and "Key" in r0["stopped"], r0)
cfg_i.update({"tmdb_api_key": "abc123456789", "tmdb_per_round": 0})
r1 = col.resolve_ids(cfg_i, time.time() + 1, 0)
check("「每轮最多查几部」设成 0 就是显式关掉，不该再去捞待办名单",
      r1["asked"] == 0 and "0" in r1["stopped"], r1)

print("\n15d) 回填元数据：只问没补过的，上游不认的写哨兵")
# 模拟"补字段之前采进来的老行"：msig 是空的（新写的行都带着 msig）
c = con()
c.execute("INSERT INTO vod(src,vid,src_name,key,title,year,kind,type_name,lines,url_count,"
          "m3u8_count,sig,dirty,pass) VALUES('huya','901','虎牙资源','laohu','老片没补过',"
          "'2026','movie','动作片','[{\"from\":\"h\",\"eps\":[{\"name\":\"正片\","
          "\"url\":\"https://x/901.m3u8\"}]}]',1,1,'s9',1,1)")
c.execute("UPDATE vod SET msig=NULL WHERE vid='901'")
c.commit()
c.close()
check("meta_gap 数的就是这种没补过的行", strm.meta_gap() >= 1, strm.meta_gap())


class FakeSrc:
    id, name, api, params = "huya", "虎牙资源", "https://x/api.php/provide/vod/", {}


asked = []


def fake_fetch_ids(src, vids):
    asked.append((src.id, list(vids)))
    return {"ok": True, "error": None, "items": [mk("老片没补过", "2026", "动作片", "h",
                                                    vid=int(v)) for v in vids
                                                  if v != "902"]}


real_fetch_ids = col.fetch_ids
col.fetch_ids = fake_fetch_ids
c = con()
c.execute("INSERT INTO vod(src,vid,src_name,key,title,year,kind,type_name,lines,url_count,"
          "m3u8_count,sig,dirty,pass) VALUES('huya','902','虎牙资源','diaoshou','已下架的片',"
          "'2026','movie','动作片','[{\"from\":\"h\",\"eps\":[{\"name\":\"正片\","
          "\"url\":\"https://x/902.m3u8\"}]}]',1,1,'s8',1,1)")
c.commit()
c.close()
b = col.backfill_meta(strm.settings(), 9, strm.cutoff(), time.time() + 60, 0.0,
                      {"huya": FakeSrc()})
check("一次按 ids 批量问（不是逐条 detail，也不是重翻整年）",
      b["chunks"] >= 1 and all(len(v) <= col.BACKFILL_CHUNK for _s, v in asked), (b, asked))
check("补上的那条现在有简介了，msig 也不再是空",
      con().execute("SELECT blurb FROM vod WHERE vid='901'").fetchone()[0] not in (None, ""))
check("上游已经不认的那个 ID 写了 gone 哨兵（否则每轮都当\"还没补\"重问，白敲上游）",
      con().execute("SELECT msig FROM vod WHERE vid='902'").fetchone()[0] == "gone",
      con().execute("SELECT msig FROM vod WHERE vid='902'").fetchone()[0])
c = con()
c.execute("UPDATE vod SET msig=NULL WHERE vid='901'")     # 再造一条"没补过"的
c.commit()
c.close()
n_before_gap = strm.meta_gap()
col.fetch_ids = lambda src, vids: {"ok": False, "items": [], "error": "HTTP 500"}
b2 = col.backfill_meta(strm.settings(), 9, strm.cutoff(), time.time() + 60, 0.0,
                       {"huya": FakeSrc()})
check("源今天不通就那一支直接停，不把整库标成\"补过了\"",
      b2["filled"] == 0 and strm.meta_gap() == n_before_gap, (b2, strm.meta_gap()))
col.fetch_ids = real_fetch_ids

print("\n16) 结构：库里到底存了什么（数据先落库再导出这条要求）")
tables = [x[0] for x in sqlite3.connect(str(strm.DB)).execute(
    "SELECT name FROM sqlite_master WHERE type='table'")]
check("八张表都在（vod=采集数据、cur=断点、part=分卷、file=已写文件、zip=打包记录、"
      "idmap=查来的外部 ID）",
      {"vod", "cur", "part", "file", "zip", "run", "setting", "idmap"} <= set(tables), tables)
c = con()
cols = {r["name"] for r in c.execute("PRAGMA table_info(vod)")}
check("vod 表里存了线路、脏标记、轮次、上映日期与 NFO 要用的那几个元数据字段",
      {"lines", "dirty", "pass", "sig", "msig", "pubdate", "kind", "key",
       "blurb", "actor", "director", "area", "douban_id", "douban_score", "pic"} <= cols,
      sorted(cols))
runs = [r["kind"] for r in c.execute("SELECT kind FROM run ORDER BY id")]
check("采集/导出都留了运行记录（页面上那句'上次跑得怎么样'从这里来）",
      "export" in runs, runs)
c.close()

print("\n17) 归并：类别是各源投票投出来的，不是按源名排序取的")
# 这一段换一套自己的目录和库：前面 12 节里 test_client 取过一次 /strm/zip，
# Flask 的 send_file 会把那个包的文件 handle 留在响应上，Windows 上删不掉 ——
# 再调 reset_db() 就是撞 PermissionError（这一节本来也只需要一个干净的库）
D17 = TMP / "s17"
D17.mkdir(parents=True, exist_ok=True)     # sqlite 不会替你把中间目录建出来
strm.DB, strm.ROOT, strm.ZIPS = D17 / "strm.db", D17 / "strm", D17 / "strm_zips"
strm._ready = False
strm.ensure_schema()      # 新库里没存过设置，settings() 直接给默认值（两颗 ID 开关都关着）
cfg = strm.settings()
c = con()
# 实测真有这样的片：《鬼的新娘》三家给"正片"、淘片给 10 集；《我的美食向导 第二季》
# 备番给 4 集、别家给 1~2 集。以前 kind 取的是 ORDER BY src_name 的第一行，
# 等于用中文源名的字节序决定它进电影库还是电视剧库
strm.record_vod(c, "apibdzy", "百度资源", mk("多集的假电影", "2026", "电影", "dbm3u8", vid=1), cfg, 1)
strm.record_vod(c, "huya", "虎牙资源", mk("多集的假电影", "2026", "动作片", "hym3u8", vid=2), cfg, 1)
strm.record_vod(c, "taopian", "淘片资源", mk("多集的假电影", "2026", "电影", "tpm3u8",
                                             n=10, vid=3), cfg, 1)
strm.record_vod(c, "suoni", "索尼资源", mk("平票的片", "2026", "电影", "snm3u8", n=2, vid=4), cfg, 1)
strm.record_vod(c, "bfzy", "备番资源", mk("平票的片", "2026", "动漫", "bfm3u8", n=2, vid=5), cfg, 1)
# 下面这几行都故意给"第01集/第02集"这种集名：给"正片"的话第 2 条判据（全是版本标记）
# 会先定案，就测不到投票那一层了
strm.record_vod(c, "apibdzy", "百度资源", mk("多数说是电影", "2026", "电影", "dbm3u8", n=2, vid=6), cfg, 1)
strm.record_vod(c, "huya", "虎牙资源", mk("多数说是电影", "2026", "电影", "hym3u8", n=2, vid=7), cfg, 1)
strm.record_vod(c, "sdzy", "速度资源", mk("多数说是电影", "2026", "电影", "sdm3u8", n=2, vid=8), cfg, 1)
strm.record_vod(c, "bfzy", "备番资源", mk("多数说是电影", "2026", "动漫", "bfm3u8", n=2, vid=9), cfg, 1)
# 库里真实的样子：三家给的不是"三集"，是 HD中字 / HD国语 / HD粤语 三个版本
strm.record_vod(c, "apibdzy", "百度资源", mk("全是版本名的片", "2026", "动漫", "dbm3u8", vid=11), cfg, 1)
strm.record_vod(c, "bfzy", "备番资源", mk("全是版本名的片", "2026", "动漫", "bfm3u8", vid=12), cfg, 1)
strm.record_vod(c, "huya", "虎牙资源", mk("全是版本名的片", "2026", "电影", "hym3u8", vid=13), cfg, 1)
c.commit()
c.close()
strm.export(full=True)
p17 = sorted(str(x.relative_to(strm.ROOT)).replace(os.sep, "/")
             for x in strm.ROOT.rglob("*.strm"))
check("有一家真给了 10 集 → 一定不是电影：三条线路全在 tv/ 下，电影那边一份都不留",
      sum(1 for x in p17 if x.startswith("tv/") and "多集的假电影" in x) == 12
      and not any("多集的假电影" in x and x.startswith("movie/") for x in p17),
      [x for x in p17 if "多集的假电影" in x][:2])
check("那一家的 10 集全导出来了（按电影布局只会留一集，整部剧就丢了）",
      sum(1 for x in p17 if "多集的假电影" in x and "S01E10" in x) == 1,
      [x for x in p17 if "E10" in x][:2])
check("一家说电影、一家说动漫且都没有多集证据时往剧集倒："
      "站点的\"电影\"分类常拿来塞网络大电影和短片，而\"动漫 / 剧\"这类标签基本只在真是剧集时才出现",
      any(x.startswith("tv/") and "平票的片" in x for x in p17)
      and not any(x.startswith("movie/") and "平票的片" in x for x in p17),
      [x for x in p17 if "平票的片" in x][:2])
check("三家说电影、一家说动漫时不倒过去（一部真电影被一家标错不该就变成剧集）",
      sum(1 for x in p17 if x.startswith("movie/") and "多数说是电影" in x) == 8
      and not any("多数说是电影" in x and x.startswith("tv/") for x in p17),
      [x for x in p17 if "多数说是电影" in x][:2])
check("集名全是 HD中字/正片 这类版本标记时算电影，哪怕两家都把它标进\"动漫\"："
      "实测《疯狂动物城2》三个源给的\"三集\"就是 HD中字/HD国语/HD粤语 三个版本",
      sum(1 for x in p17 if x.startswith("movie/") and "全是版本名的片" in x) == 3
      and not any("全是版本名的片" in x and x.startswith("tv/") for x in p17),
      [x for x in p17 if "全是版本名的片" in x][:2])
# 换类别时旧类别那一行卷号要放掉：占着名额不说，将来投回电影还会被塞回几周前那卷
k17 = strm.title_key(strm.display_title("多集的假电影"))
c = con()
had_tv = c.execute("SELECT COUNT(*) FROM part WHERE key=? AND kind='tv'", (k17,)).fetchone()[0]
c.execute("UPDATE vod SET url_count=1, m3u8_count=1, kind='movie', lines=?"
          " WHERE src='taopian' AND vid='3'",
          (json.dumps([{"from": "tpm3u8", "eps": [{"name": "正片",
                                                   "url": "https://cdn.test/only/index.m3u8"}]}],
                      ensure_ascii=False),))
c.execute("UPDATE vod SET dirty=1 WHERE key=?", (k17,))
c.commit()
c.close()
strm.export()
c = con()
now_tv = c.execute("SELECT COUNT(*) FROM part WHERE key=? AND kind='tv'", (k17,)).fetchone()[0]
now_movie = c.execute("SELECT COUNT(*) FROM part WHERE key=? AND kind='movie'",
                      (k17,)).fetchone()[0]
left = [x["path"] for x in c.execute("SELECT path FROM file WHERE key=?", (k17,))]
c.close()
check("投回电影之后：剧集那一行的卷号被释放，文件也整份搬到 movie/ 下（不留一份旧的）",
      had_tv == 1 and now_tv == 0 and now_movie == 1 and left
      and all(x.startswith("movie/") for x in left), (had_tv, now_tv, now_movie, left[:2]))
# 库里真实存在的形状：三家给的不是"三集"，是 HD中字 / HD国语 / HD粤语 三个版本
c = con()
for vid, frm, tn in ((21, "dbm3u8", "动漫"), (22, "ffm3u8", "动漫"), (23, "hnm3u8", "电影")):
    v = {"vod_id": vid, "vod_name": "疯狂动物城2", "vod_year": "2026",
         "vod_pubdate": "2026-11-26美国", "type_name": tn,
         "vod_time": "2026-10-20 10:00:00", "vod_remarks": "", "vod_pic": "",
         "vod_douban_id": 0,
         "vod_play_from": frm,
         "vod_play_url": "#".join(f"{n}$https://cdn.test/{vid}-{i}.m3u8"
                                 for i, n in enumerate(["HD中字", "HD国语", "HD粤语"]))}
    strm.record_vod(c, f"s{vid}", f"源{vid}", v, cfg, 1)
c.commit()
c.close()
strm.export()
p17b = sorted(str(x.relative_to(strm.ROOT)).replace(os.sep, "/")
              for x in strm.ROOT.rglob("*.strm"))
check("两家的分类标签都写着\"动漫\"，但集名是 HD中字/HD国语/HD粤语 → 那是一部片的三个版本，算电影",
      sum(1 for x in p17b if x.startswith("movie/") and "疯狂动物城2" in x) == 9
      and not any("疯狂动物城2" in x and x.startswith("tv/") for x in p17b),
      [x for x in p17b if "疯狂动物城2" in x][:3])
check("三个版本各成一个文件；HD中字 按正片处理不带尾缀、语言版本把名字带在 ` - ` 后面",
      sum(1 for x in p17b if "疯狂动物城2" in x) == 9
      and any(x.endswith("源21.strm") for x in p17b)
      and any(x.endswith("源21·HD国语.strm") for x in p17b),
      [x.split("/")[-1] for x in p17b if "疯狂动物城2" in x][:3])
c = con()
strm.record_vod(c, "tp", "淘片资源", mk("完美世界剧场版九劫焚天", "2026", "电影", "tpm3u8",
                                        vid=31), cfg, 1)
strm.record_vod(c, "bf", "备番资源", mk("完美世界剧场版九劫焚天", "2026", "动漫", "bfm3u8",
                                        vid=32), cfg, 1)
strm.record_vod(c, "sn", "索尼资源", mk("快乐老友屋 第三季", "2026", "综艺", "snm3u8",
                                        n=2, vid=33), cfg, 1)
strm.record_vod(c, "hj", "虎鲸资源", mk("快乐老友屋 第三季", "2026", "电影", "hjm3u8",
                                        vid=34), cfg, 1)
c.commit()
c.close()
strm.export()
p17c = sorted(str(x.relative_to(strm.ROOT)).replace(os.sep, "/")
              for x in strm.ROOT.rglob("*.strm"))
check("片名写着「剧场版」→ 1:1 平票时也判电影（这种名字不会是连续剧）",
      any(x.startswith("movie/") and "完美世界剧场版九劫焚天" in x for x in p17c)
      and not any("完美世界剧场版九劫焚天" in x and x.startswith("tv/") for x in p17c),
      [x for x in p17c if "剧场版" in x][:2])
check("片名写着「第三季」→ 判剧集并按 S03E0x 落文件（第几季从片名里读，不看源怎么标）",
      any(x.startswith("tv/") and "S03E02" in x for x in p17c),
      [x for x in p17c if "快乐老友屋" in x][:2])

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
