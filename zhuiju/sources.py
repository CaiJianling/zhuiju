# -*- coding: utf-8 -*-
"""检索接口配置：只收录在本机网络下实测能返回片名的公开采集接口。

字段说明：
  kind            响应风格，目前支持 maccms（苹果CMS provide/vod 规范）
  api             采集接口地址
  params          附加查询参数
  root            对应站点首页，用于兜底跳转
  search_template 站内搜索页模板，{kw} 为关键词占位符（实测可用）
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "sources.json"

# 兜底：tools/probe_sources.py 实测通过的 8 个接口（search_template 由工具补全）
FALLBACK = [
    {"id": "huya", "name": "虎牙资源", "kind": "maccms",
     "api": "https://www.huyaapi.com/api.php/provide/vod/from/hym3u8",
     "params": {}, "root": "https://www.huyaapi.com/", "search_template": None,
     "browsable": False,
     "note": "TVBox 配置『老刘备』内实测可用"},
    {"id": "hhzy", "name": "火狐资源", "kind": "maccms",
     "api": "https://hhzyapi.com/api.php/provide/vod/",
     "params": {}, "root": "https://hhzyapi.com/", "search_template": None,
     "browsable": False,
     "note": "TVBox 配置『老刘备』内实测可用"},
    {"id": "apibdzy", "name": "百度资源", "kind": "maccms",
     "api": "https://api.apibdzy.com/api.php/provide/vod/",
     "params": {}, "root": "https://api.apibdzy.com/", "search_template": None,
     "browsable": True,
     "note": "TVBox 配置『老刘备』内实测可用"},
    {"id": "hongniu", "name": "红牛资源", "kind": "maccms",
     "api": "https://www.hongniuzy2.com/api.php/provide/vod/",
     "params": {}, "root": "https://www.hongniuzy2.com/", "search_template": None,
     "browsable": True,
     "note": "常见公开采集接口，实测可用"},
    {"id": "jszy", "name": "极速资源", "kind": "maccms",
     "api": "https://jszyapi.com/api.php/provide/vod/",
     "params": {}, "root": "https://jszyapi.com/", "search_template": None,
     "browsable": False,
     "note": "常见公开采集接口，实测可用"},
    {"id": "guangsu", "name": "光速资源", "kind": "maccms",
     "api": "https://api.guangsuapi.com/api.php/provide/vod/",
     "params": {}, "root": "https://api.guangsuapi.com/", "search_template": None,
     "browsable": False,
     "note": "常见公开采集接口，实测可用"},
    {"id": "bfzy", "name": "备番资源", "kind": "maccms",
     "api": "https://bfzyapi.com/api.php/provide/vod/",
     "params": {}, "root": "https://bfzyapi.com/", "search_template": None,
     "browsable": False,
     "note": "常见公开采集接口，实测可用，番剧较多"},
    {"id": "taopian", "name": "淘片资源", "kind": "maccms",
     "api": "https://taopianapi.com/cjapi/mc/vod/json.html",
     "params": {}, "root": "https://taopianapi.com/", "search_template": None,
     "browsable": True,
     "note": "TVBox 配置『老刘备』内实测可用"},
]


@dataclass
class Source:
    id: str
    name: str
    kind: str
    api: str
    params: dict = field(default_factory=dict)
    root: str = ""
    search_template: str | None = None
    note: str = ""
    enabled: bool = True
    # 有些采集接口只开放 API，站点首页会返回 403/500，此时不给"打开站点"链接
    browsable: bool = True


def load_sources(path: Path = DATA):
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            raw = data["sources"] if isinstance(data, dict) else data
        except Exception:
            raw = FALLBACK
    else:
        raw = FALLBACK
    return [Source(**{k: v for k, v in s.items() if k in Source.__dataclass_fields__})
            for s in raw]


def save_sources(sources, path: Path = DATA):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [dict((k, getattr(s, k)) for k in Source.__dataclass_fields__)
               for s in sources]
    path.write_text(json.dumps({"sources": payload}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
