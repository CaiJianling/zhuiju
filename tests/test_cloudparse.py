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

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
