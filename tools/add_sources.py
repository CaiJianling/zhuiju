# -*- coding: utf-8 -*-
"""把 tools/harvest_more_apis.py 实测通过的新接口并入 zhuiju/data/sources.json。

用法：
    python tools/harvest_more_apis.py     # 先抽取 + 实测，产出 .probe/more_sources.json
    python tools/add_sources.py           # 把新接口追加进配置
    python tools/probe_sources.py 庆余年   # 再整体体检一遍（写入 enabled / browsable）
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zhuiju.sources import Source, load_sources, save_sources  # noqa: E402

base = Path(__file__).resolve().parent.parent
src_file = base / "zhuiju" / "data" / "sources.json"
found_file = base / ".probe" / "more_sources.json"

if not found_file.exists():
    raise SystemExit(f"缺少 {found_file}，请先运行 tools/harvest_more_apis.py")

found = json.loads(found_file.read_text(encoding="utf-8"))
existing = load_sources(src_file)
have = {urlparse(s.api).netloc.lower() for s in existing}


def slug(host: str) -> str:
    s = re.sub(r"^(www|api|caiji|app|v\d*|m3u8|4k)\d*[.-]", "", host)
    s = re.sub(r"(api|provide|zy|vod|icu|com|net|top|me|cc|tv|xyz|vip|cn)\b|[.-]", "", s)
    s = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", s.lower())
    return (s or host.split(".")[0])[:14] or "src"


def clean_name(n: str) -> str:
    n = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", n or "")   # 去掉 emoji 前缀
    n = re.sub(r"[┃|·\-—_*\s]+", " ", n).strip()
    return n[:16]


added = []
for row in found:
    if not row.get("ok"):
        continue
    host = row["host"].lower()
    if host in have:
        continue
    sid, guard = slug(host), 0
    while any(s.id == sid for s in existing + added):
        guard += 1
        sid = f"{slug(host)}{guard}"
    added.append(Source(
        id=sid, name=clean_name(row["name"]) or host, kind="maccms",
        api=row["api"], params={}, root=f"{urlparse(row['api']).scheme}://{host}/",
        search_template=None, note="harvest_more_apis 实测通过", enabled=True,
        browsable=True,
    ))
    have.add(host)

if not added:
    print("没有新接口可加（都已收录或全部实测失败）")
else:
    save_sources(existing + added, src_file)
    print(f"新增 {len(added)} 个接口，现在共 {len(existing) + len(added)} 个：")
    for s in added:
        print(f"  + {s.id:<12} {s.name:<12} {s.api}")
    print("\n下一步请运行: python tools/probe_sources.py 庆余年")
