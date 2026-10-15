# -*- coding: utf-8 -*-
"""生成/刷新 zhuiju/data/sources.json：实测每个采集接口，只保留能返回片名的。

    python tools/probe_sources.py            # 用默认关键词自检并写文件
    python tools/probe_sources.py 流浪地球    # 换关键词
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

requests.packages.urllib3.disable_warnings()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zhuiju.search import fetch_one                      # noqa: E402
from zhuiju.sources import Source, load_sources, save_sources  # noqa: E402


def browsable(root: str) -> bool:
    """站点首页是否能正常打开：部分采集接口只放 API，首页是 403/500 拦截页。"""
    if not root:
        return False
    try:
        r = requests.get(root, timeout=10, verify=False,
                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                                "Chrome/124.0 Safari/537.36"})
        body = (r.text or "").strip()
        return (r.status_code == 200
                and body[:15].lower().startswith(("<!doctype", "<html"))
                and len(body) > 4000)
    except Exception:  # noqa: BLE001
        return False

base = Path(__file__).resolve().parent.parent
KW = sys.argv[1] if len(sys.argv) > 1 else "庆余年"

tpl_path = base / "zhuiju" / "data" / "templates.json"
api_tpl = {}
if tpl_path.exists():
    for k, v in json.loads(tpl_path.read_text(encoding="utf-8"))["templates"].items():
        if k.startswith("api:"):
            api_tpl[k[4:]] = v

sources = load_sources(base / "zhuiju" / "data" / "sources_fallback.json"
                       if (base / "zhuiju" / "data" / "sources_fallback.json").exists()
                       else base / "zhuiju" / "data" / "sources.json")

checked = []
for s in sources:
    r = fetch_one(s, KW)
    key = f"{urlparse(s.api).scheme}://{urlparse(s.api).netloc}".lower()
    s.search_template = api_tpl.get(key) or s.search_template
    s.enabled = bool(r["ok"])
    s.browsable = browsable(s.root or f"{key}/")
    checked.append(s)
    print(f"{'OK ' if r['ok'] else 'FAIL'} {s.name:<8} {r['ms']:>5}ms "
          f"count={r['count']} 首页{'可浏览' if s.browsable else '不可浏览'} {r['error'] or ''}")

save_sources(checked, base / "zhuiju" / "data" / "sources.json")
alive = [s for s in checked if s.enabled]
print(f"\n可用检索源 {len(alive)}/{len(checked)} 已写入 data/sources.json")
