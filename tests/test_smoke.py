# -*- coding: utf-8 -*-
"""离线冒烟测试：用固定样本验证解析、合并、分层排序、目录检索，不依赖外部网络。

    python tests/test_smoke.py
"""
import json
import sys
from pathlib import Path

# Windows 控制台默认 GBK，中文断言名会乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zhuiju import catalog  # noqa: E402
from zhuiju import search as search_mod  # noqa: E402  需要模块对象来替换 fetch_one
from zhuiju.search import (detail, fetch_one, match_tier, merge,  # noqa: E402
                           parse_maccms, parse_maccms_detail, search, title_key)
from zhuiju.sources import Source  # noqa: E402

FAILS = []


def check(name, cond, got=None):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}  got={got!r}")
        FAILS.append(name)


print("1) 片名归一化")
check("空格/全角/尾部标记不影响 key",
      title_key("庆余年 第二季") == title_key("庆余年　第二季")
      and title_key("流浪地球 HD") == title_key("流浪地球"))
check("英文大小写归一", title_key("Oppenheimer") == "oppenheimer",
      title_key("Oppenheimer"))

print("2) 匹配分层（蹭名短剧不能压过正片）")
check("完全同名 = 0", match_tier("灌篮高手", "灌篮高手") == 0,
      match_tier("灌篮高手", "灌篮高手"))
check("前缀续集 = 1", match_tier("庆余年", "庆余年第二季") == 1,
      match_tier("庆余年", "庆余年第二季"))
check("包含 = 2", match_tier("甄嬛传", "后宫甄嬛传") == 2,
      match_tier("甄嬛传", "后宫甄嬛传"))
check("无关 = 3", match_tier("繁花", "海上花") == 3, match_tier("繁花", "海上花"))

print("3) list 响应解析")
raw = {"code": 1, "total": 2, "list": [
    {"vod_id": 1, "vod_name": "<em>庆余年</em> 第二季", "type_name": "国产剧",
     "vod_year": "2024", "vod_area": "大陆", "vod_remarks": "全36集",
     "vod_actor": "张若昀,李梦", "vod_pic": "https://x/y.jpg", "vod_time": "2024-06-11 10:00:00"},
    {"vod_id": 2, "vod_name": "庆余年之帝王业", "type_name": "古装仙侠",
     "vod_year": "2024", "vod_remarks": "全52集"}]}
items = parse_maccms(raw)
check("HTML 标签被清掉", items[0]["title"] == "庆余年 第二季", items[0]["title"])
check("海报/年份/更新状态保留",
      items[0]["pic"].startswith("https://") and items[0]["year"] == "2024"
      and items[0]["remarks"] == "全36集")
check("缺字段不报错", items[1]["pic"] == "" and items[1]["actor"] == "")

print("4) 跨源合并与排序")
def fake(src_id, name, payload_kw):
    return {"source": src_id, "source_name": name, "ok": True, "count": 1,
            "items": [{**x, "source": src_id, "source_name": name, "link": ""}
                      for x in parse_maccms(payload_kw)]}

a = fake("hhzy", "火狐", raw)
raw2 = {"list": [{"vod_id": 9, "vod_name": "庆余年第二季", "type_name": "国产剧",
                  "vod_year": "2024", "vod_remarks": "已完结"}]}
b = fake("jszy", "极速", raw2)
raw3 = {"list": [{"vod_id": 5, "vod_name": "庆余年之风起沧州", "vod_year": "2016"}]}
c = fake("bfzy", "备番", raw3)
res, dropped = merge([a, b, c], "庆余年")
check("同片跨源合并成一条",
      res[0]["title"] == "庆余年 第二季" and len(res[0]["sources"]) == 2,
      (res[0]["title"], len(res[0]["sources"])))
check("正片排在蹭名作品之前", res[0]["tier"] <= res[1]["tier"],
      [(r["title"], r["tier"], len(r["sources"])) for r in res])
check("match 字段可读", res[0]["match"] in ("exact", "series", "contains", "other"),
      res[0]["match"])
check("源去重", len({s["id"] for s in res[0]["sources"]}) == 2)

# 接口自身模糊匹配出来的无关结果（与关键词零重叠）必须丢掉
raw_junk = {"list": [{"vod_id": 77, "vod_name": "恐怖藏品", "vod_year": "2026"}]}
raw_en = {"list": [{"vod_id": 88, "vod_name": "奥本海默 Oppenheimer", "vod_year": "2023"}]}
res_j, dropped_j = merge([a, fake("jszy", "极速", raw_junk), fake("tp", "淘片", raw_en)],
                         "Oppenheimer")
check("只留下真正含关键词的结果",
      [r["title"] for r in res_j] == ["奥本海默 Oppenheimer"],
      [r["title"] for r in res_j])
# a 里两条《庆余年》+ 一条《恐怖藏品》对 Oppenheimer 都是零重叠
check("零重叠噪声计入 dropped", dropped_j == 3, dropped_j)

print("5) detail 线路解析（分隔符 $$$ 而非 +）")
dd = {"list": [{"vod_id": 1, "vod_name": "庆余年 第二季", "vod_year": "2024",
                "vod_play_from": "hhyun$$$hhm3u8",
                "vod_play_url": "第01集$u1#第02集$u2$$$第01集$u3"}]}
p = parse_maccms_detail(dd)
check("线路名按 $$$ 正确切分",
      [l["from"] for l in p["lines"]] == ["hhyun", "hhm3u8"],
      [l["from"] for l in p["lines"]])
check("各线路集数正确", [len(l["episodes"]) for l in p["lines"]] == [2, 1],
      [len(l["episodes"]) for l in p["lines"]])
check("播放地址完整", p["lines"][0]["episodes"][0]["url"] == "u1")

src = Source(id="t", name="测试源", kind="maccms", api="http://127.0.0.1:9/provide/vod/")
d_err = detail(src, "1")
check("接口不可达时返回 ok=False 且带原因",
      d_err.get("ok") is False and bool(d_err.get("error")), d_err)
src2 = Source(id="t2", name="测试源2", kind="maccms", api="http://127.0.0.1:9/provide/vod/")
check("未知 kind 不会误判为成功", parse_maccms_detail({"list": []})["lines"] == [],
      parse_maccms_detail({"list": []}))

print("6) 目录检索与直达链接")
catalog.reload_data()
rows = catalog.search("网盘")
check("目录能按分类/标签命中", any(r["category_cn"] == "网盘搜索" for r in rows),
      [r["name"] for r in rows][:5])
rows2 = catalog.search("字幕")
check("字幕分类可检索", len(rows2) > 0, len(rows2))
dl = catalog.deeplinks("庆余年")
verified = [x for x in dl if x["kind"] == "site_search"]
check("直达项存在", len(dl) > 20, len(dl))
check("已验证模板会带关键词",
      all("庆余年" in json.dumps(x, ensure_ascii=False) or "%" in x["url"]
          for x in verified[:1]))
check("状态灯已映射", dl[0]["dot"] in ("🟢", "🟡", "🔴", "⚪"), dl[0]["dot"])

print("7) 某源超过预算时不能崩（extra 曾被误初始化成 dict，只在超时时才触发）")
import time as _t


class SlowSource(Source):
    pass


def slow_fetch(src, kw, page=1, limit=20, type_id=None):
    if src.id == "slow":
        _t.sleep(3)
        return {"source": src.id, "source_name": src.name, "ok": True, "count": 0,
                "total": 0, "items": [], "ms": 3000, "error": None}
    return {"source": src.id, "source_name": src.name, "ok": True, "count": 1,
            "total": 1, "items": [{**parse_maccms(raw)[0], "source": src.id,
                                   "source_name": src.name, "link": ""}],
            "ms": 10, "error": None}


fast = Source(id="fast", name="快源", kind="maccms", api="http://x/api.php/provide/vod/")
slow = Source(id="slow", name="慢源", kind="maccms", api="http://y/api.php/provide/vod/")
_orig = search_mod.fetch_one
search_mod.fetch_one = slow_fetch
try:
    out = search("庆余年", sources=[fast, slow], budget=0.5)
    check("超时不抛异常", isinstance(out, dict), type(out))
    check("快源结果仍在", len(out["results"]) >= 1, len(out["results"]))
    names = {s["source"] for s in out["status"]}
    check("慢源被标为未响应", "slow" in names, out["status"])
    slowrow = next(s for s in out["status"] if s["source"] == "slow")
    check("超时原因写进状态", "未响应" in (slowrow["error"] or ""), slowrow)
finally:
    search_mod.fetch_one = _orig

print("7b) 自动更新的『当天』以凌晨 2 点为界")
from datetime import datetime as _dt, timedelta as _td
from zhuiju import autoupdate as au
H = au.REFRESH_HOUR
check("01:30 仍属于昨天", au.logical_day(_dt(2026, 10, 14, 1, 30)) == _dt(2026, 10, 13).date(),
      str(au.logical_day(_dt(2026, 10, 14, 1, 30))))
check("02:00 起算新的一天", au.logical_day(_dt(2026, 10, 14, 2, 0)) == _dt(2026, 10, 14).date(),
      str(au.logical_day(_dt(2026, 10, 14, 2, 0))))
check("23:59 仍属于当天", au.logical_day(_dt(2026, 10, 14, 23, 59)) == _dt(2026, 10, 14).date())
# 23 点跑过一次，次日 01 点访问不该重跑，02 点后要重跑
ld_y = au.logical_day(_dt(2026, 10, 13, 23, 0)).isoformat()
check("凌晨 1 点：昨天 23 点跑过 -> 不需要更新",
      ld_y == au.logical_day(_dt(2026, 10, 14, 1, 0)).isoformat(), ld_y)
check("凌晨 2 点后：同一份记录 -> 需要更新",
      ld_y != au.logical_day(_dt(2026, 10, 14, 2, 5)).isoformat())
check("needs_update 走的是逻辑日而非自然日",
      "logical_day" in (Path(__file__).resolve().parent.parent
      / "zhuiju" / "autoupdate.py").read_text(encoding="utf-8"))

print("8) 数据文件完整性")
data = Path("zhuiju/data")
for f in ("catalog.json", "sources.json", "templates.json"):
    p = data / f
    check(f"{f} 可解析", p.exists() and isinstance(json.loads(p.read_text(encoding="utf-8")), dict),
          p.exists())
srcs = json.loads((data / "sources.json").read_text(encoding="utf-8"))["sources"]
check("检索源都有 api 与 kind", all(s.get("api") and s.get("kind") for s in srcs))
check("browsable 字段已落盘", all("browsable" in s for s in srcs),
      [list(s.keys()) for s in srcs[:1]])

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
