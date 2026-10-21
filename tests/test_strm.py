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

FAILS = []
TMP = Path(tempfile.mkdtemp(prefix="zhuiju_strm_test_"))

admin_mod.CONFIG = TMP / "admin.json"
stats_mod.DB = TMP / "stats.db"
stats_mod.DATA = TMP
stats_mod._ready = False
strm.DB = TMP / "strm.db"
strm.DATA = TMP / "strmdata"
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


def mk(title, year, type_name, frm, n=1, vid=1, pubdate="", remarks=""):
    """造一条上游 videolist 条目。

    每条影片都带两条线路：一条 m3u8 直连、一条 HTML 播放器页 —— 实测多数站就是这样，
    所以"默认只收 m3u8"这条判据必须被真实形状检验，不能只喂干净的。
    """
    eps = "#".join(f"第{i:02d}集$https://cdn.test/{vid}-{i}/index.m3u8"
                   for i in range(1, n + 1)) if n > 1 else \
        f"正片$https://cdn.test/{vid}-1/index.m3u8"
    html = f"正片$https://play.test/{vid}" if n == 1 else \
        "#".join(f"第{i:02d}集$https://play.test/{vid}-{i}" for i in range(1, n + 1))
    return {"vod_id": vid, "vod_name": title, "vod_year": year, "vod_pubdate": pubdate,
            "type_name": type_name, "vod_time": "2026-10-20 10:00:00",
            "vod_remarks": remarks, "vod_pic": "https://pic.test/1.jpg",
            # 上游真实形状是"两条线路名对两个线路块"（火狐就是 hhyun$$$hhm3u8）；
            # 名字少写一条就会退成"线路N"，那条分支另有专门的用例
            "vod_play_from": f"{frm}$$$webplay", "vod_play_url": f"{eps}$$${html}"}


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
files = sorted(str(p.relative_to(strm.ROOT)).replace(os.sep, "/")
               for p in strm.ROOT.rglob("*.strm"))
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
check("导出的文件数与库里的行数对得上",
      len(files) == strm.db_counts()["files"], (len(files), strm.db_counts()["files"]))
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

print("\n6) 下架/掉出窗口时文件要跟着删")
c = con()
c.execute("DELETE FROM vod WHERE src='apibdzy'")
gone_key = c.execute("SELECT key FROM vod WHERE title LIKE '%毒液%'").fetchone()["key"]
c.execute("DELETE FROM vod WHERE key=?", (gone_key,))
c.commit()
c.close()
fourth = strm.export()
check("库里没了的片，它的 strm 文件被删掉", fourth["removed"] >= 1, fourth)
rest = sorted(str(p.relative_to(strm.ROOT)).replace(os.sep, "/")
              for p in strm.ROOT.rglob("*.strm"))
check("被删的是它那两条，庆余年一条没少",
      not any("毒液" in r for r in rest) and sum(1 for r in rest if "庆余年" in r) >= 7, rest)
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
check("第一卷被填满到上限", len(m1) == 6, len(m1))
c = con()
per_folder = {}
for r in c.execute("SELECT key, part FROM file GROUP BY key, part"):
    per_folder.setdefault(r["key"], set()).add(r["part"])
check("同一部片的所有文件都在同一卷里（跨卷就是海报墙上两条同名影片）",
      all(len(v) == 1 for v in per_folder.values()), per_folder)
check("两个源的版本名不撞车（撞了就只剩一条线路，另一条被覆盖）",
      len({p.split("/")[-1] for p in m1}) == len(m1), m1)
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
    check("包内每个文件名都以它所在文件夹名开头（Emby 认多版本就认这一条）",
          all(n.split("/")[-2] in n.split("/")[-1] and " - " in n.split("/")[-1]
              for n in names), names[:2])
    check("包里的文件数与这一卷清单一模一样",
          len(names) == len([p for p in strm.part_paths("movie", "movie01")]),
          (len(names), len(strm.part_paths("movie", "movie01"))))
    first = z.read(names[0]).decode("utf-8")
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
one_path = strm.part_paths("movie", "movie01")[0]
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

print("\n13) 后台页与登录门槛")
r = client.get("/admin")
check("没登录时后台仍是口令页（STRM 设置不能公开改）", r.status_code == 401, r.status_code)
check("口令页里看不到采集设置", "采集时间范围" not in r.get_data(as_text=True))
tok = re.search(r'name="csrf" value="([0-9a-f]+)"', r.get_data(as_text=True)).group(1)
admin_mod.set_password("strm-test-mima")
r = client.post("/admin/login", data={"csrf": tok, "password": "strm-test-mima"})
check("登录成功跳回 /admin", r.status_code == 302, r.status_code)
r = client.get("/admin")
page = r.get_data(as_text=True)
check("登录后 200", r.status_code == 200, r.status_code)
check("后台出现了 Emby STRM 那一节", 'id="strm"' in page and "Emby STRM" in page)
check("分卷表里有 movie01 和下载链接", "movie01" in page and "/strm/zip?name=movie01.zip" in page,
      re.findall(r'href="(/strm/zip[^"]*)"', page)[:2])
check("设置表单带 csrf（不然是个可被外部提交的表单）",
      'name="csrf"' in page and 'action="/admin/strm/settings"' in page)
check("时间范围这一项在页面上（用户点名要能后台设）",
      'name="window_days"' in page and "采集时间范围" in page)
check("页面上写了命名规则（为什么一个文件只有一集）",
      "片名 (年份)" in page and "一个 strm 只对应一部片" in page)
tok = re.search(r'name="csrf" value="([0-9a-f]+)"', page).group(1)
r = client.post("/admin/strm/settings", data={"csrf": tok, "window_days": "90",
                                             "part_files": "3000", "delay_ms": "400",
                                             "workers": "3", "budget_seconds": "900",
                                             "max_eps_per_title": "120",
                                             "max_lines_per_src": "1", "enabled": "1",
                                             "m3u8_only": "1", "exclude_srcs": "",
                                             "min_interval_minutes": "30"},
                follow_redirects=False)
check("保存设置 302 回后台并锚定到那一节",
      r.status_code == 302 and "/admin" in r.headers["Location"] and "#strm" in r.headers["Location"],
      r.headers.get("Location"))
check("设置真的写进了库", strm.settings()["window_days"] == 90, strm.settings())
r = client.post("/admin/strm/settings", data={"csrf": "deadbeef", "window_days": "999"},
                follow_redirects=False)
check("csrf 不对时改不动设置", r.status_code == 400 and strm.settings()["window_days"] == 90)

print("\n13b) 那一节的实时进度（不用手动刷新也在动）")
r = client.get("/api/strm/status")
stt = r.get_json()
check("状态接口带上了游标（页脚那张表就地更新要靠它）",
      "cursor" in stt and isinstance(stt["cursor"], dict), list(stt)[:10])
check("游标里能读到页码与停下来原因（和模板同一口径）",
      all({"pg", "stop", "requests", "last_time"} <= set(v.keys())
          for v in stt["cursor"].values()) if stt["cursor"] else True,
      list(stt["cursor"].values())[:1])
page = client.get("/admin").get_data(as_text=True)
check("状态行、库计数行、游标表、分卷表都有锚点给脚本更新",
      all(x in page for x in ('id="strm-state"', 'id="strm-kpi"',
                              'id="strm-cur"', 'id="strm-parts-movie"',
                              'id="strm-parts-tv"')),
      [x for x in ('strm-state', 'strm-kpi', 'strm-cur', 'strm-parts-movie',
                   'strm-parts-tv') if f'id="{x}"' not in page])
check("库里没游标时那张表也照样渲染出来（首轮进度才有地方落），并留一句「还没采过」",
      'id="strm-cur"' in page and 'id="strm-cur-empty"' in page)
check("两类分卷表都在（tv 一类还没打包时也要有地方填第一轮的结果）",
      'id="strm-parts-movie"' in page and 'id="strm-parts-tv"' in page)
check("行塞进去之后重量一次内联滚动框高度（那些 .fold 的高度是量出来的，不是 CSS 写死的）",
      "dispatchEvent(new Event('resize'))" in page)
check("初始状态写在 data-running 上（脚本据此决定多久问一次）",
      'data-running="0"' in page or 'data-running="1"' in page,
      re.findall(r'data-running="(\d)"', page))
check("轮询只问状态接口，且回到标签页立刻补一次",
      "/api/strm/status" in page and "visibilitychange" in page
      and "document.hidden" in page)
check("在跑的时候 10 秒一次、闲下来 60 秒一次（不是越看越勤地把站点打死）",
      "schedule(wasRunning ? 10000 : 60000)" in page.replace(" ", " ")
      or "wasRunning ? 10000 : 60000" in page)
check("分卷表只在这一轮刚结束时用 manifest 重建一次，不跟着每次轮询拉",
      "/api/strm/manifest" in page and "if (wasRunning && !s.running) refreshParts()" in page)
blk = page.split('「Emby STRM」那一节的实时进度')[-1].split('</script>')[0]
check("更新文案一律走 textContent（源名和上游备注是外部字符串，不能当 HTML 塞进去）",
      "n.textContent = text" in blk and "innerHTML" not in blk,
      ("textContent" in blk, "innerHTML" in blk))
check("没有 JavaScript 时这一节仍然说得出在不在跑（服务端四种文案都渲染）",
      any(t in page for t in ("正在后台采集", "现在访问网站就会拉起一轮",
                              "采集开关是关的", "这一轮跑完了，在等最小间隔")))
check("分卷那一行写的是真实卷名，不是 movieNN 这种程序员占位符（页面上没人认识 NN）",
      "movieNN" not in page and "tvNN" not in page
      and "movie01、movie02" in page and "tv01、tv02" in page,
      re.findall(r'asub">([^<]*)', page)[:6])

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

print("\n16) 结构：库里到底存了什么（数据先落库再导出这条要求）")
tables = [x[0] for x in sqlite3.connect(str(strm.DB)).execute(
    "SELECT name FROM sqlite_master WHERE type='table'")]
check("七张表都在（vod=采集数据、cur=断点、part=分卷、file=已写文件、zip=打包记录）",
      {"vod", "cur", "part", "file", "zip", "run", "setting"} <= set(tables), tables)
c = con()
cols = {r["name"] for r in c.execute("PRAGMA table_info(vod)")}
check("vod 表里存了线路、脏标记、轮次与上映日期",
      {"lines", "dirty", "pass", "sig", "pubdate", "kind", "key"} <= cols, sorted(cols))
runs = [r["kind"] for r in c.execute("SELECT kind FROM run ORDER BY id")]
check("采集/导出都留了运行记录（页面上那句'上次跑得怎么样'从这里来）",
      "export" in runs, runs)
c.close()

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
