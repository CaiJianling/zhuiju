# -*- coding: utf-8 -*-
"""图片代理：解决第三方海报的防盗链与证书问题。

实测：豆瓣图床 img*.doubanio.com 无 Referer 返回 418、带本站 Referer 返回 403、
只有带 https://movie.douban.com/ 才 200；而部分采集站图床挂在非标端口 + 自签证书上
（浏览器静默失败）。浏览器里伪造不了 Referer，所以由本站代取。

安全上收紧到：只允许 http/https、拒绝回环与内网地址、限制体积与类型，
并且只代理本站页面里发出过的图片地址（register/allowed），避免变成公共代理。
"""
from __future__ import annotations

import ipaddress
import json
import os
import time
import urllib.parse
from pathlib import Path

import requests

requests.packages.urllib3.disable_warnings()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
MAX_BYTES = 3 << 20          # 单张最多 3MB
TIMEOUT = 8.0
CACHE_MAX = 120

# 按域名给防盗链补 Referer
REFERERS = {
    "doubanio.com": "https://movie.douban.com/",
    "douban.com": "https://movie.douban.com/",
}

_mem: dict[str, tuple[float, int, str, bytes]] = {}
_urls_file = Path(__file__).resolve().parent / "data" / "cache" / "img_urls.json"
# 用 dict 而不是 set：要保持登记顺序，超量时才能丢掉最早登记的
_allowed: dict[str, None] = {}
_loaded = False
ALLOWED_MAX = 3000
# 只有本站主动发出过的图片地址才允许代理；关掉它等于开了个公共代理
STRICT = os.environ.get("ZHUIJU_IMG_OPEN", "0") != "1"


def _load_allowed() -> None:
    global _allowed, _loaded
    _loaded = True
    if _urls_file.exists():
        try:
            rows = json.loads(_urls_file.read_text(encoding="utf-8"))
            _allowed = dict.fromkeys(r for r in rows if isinstance(r, str))
        except Exception:  # noqa: BLE001
            _allowed = {}


def register(url: str) -> None:
    """页面/接口把某个图片地址发给前端时登记，之后 /img 才肯代理它。"""
    if not url or not url.startswith(("http://", "https://")):
        return
    if not _loaded:
        _load_allowed()
    if url in _allowed:
        _allowed.move_to_end(url) if hasattr(_allowed, "move_to_end") else None
        return
    _allowed[url] = None
    while len(_allowed) > ALLOWED_MAX:          # 丢最早登记的
        _allowed.pop(next(iter(_allowed)))
    try:
        _urls_file.parent.mkdir(parents=True, exist_ok=True)
        _urls_file.write_text(json.dumps(list(_allowed), ensure_ascii=False),
                              encoding="utf-8")
    except OSError:
        pass


def register_all(items) -> None:
    for it in items or []:
        if isinstance(it, dict) and it.get("pic"):
            register(it["pic"])


def allowed(url: str) -> bool:
    if not STRICT:
        return True
    if not _loaded:
        _load_allowed()
    return url in _allowed


def _referer_for(host: str) -> str:
    for suffix, ref in REFERERS.items():
        if host == suffix or host.endswith("." + suffix):
            return ref
    return ""


def _blocked_host(host: str) -> bool:
    """拒绝回环/内网/非法地址，避免这个代理被拿去打内网。"""
    if host in ("localhost", "0.0.0.0", "::", ""):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False          # 域名：放行（本机 hosts 除外难以判断，风险可接受）
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def resolve(url: str) -> tuple[int, str, bytes, str]:
    """返回 (状态码, Content-Type, 内容, 说明)。命中内存缓存则不发请求。"""
    now = time.time()
    hit = _mem.get(url)
    if hit and now - hit[0] < 3600:
        return hit[1], hit[2], hit[3], "cache"

    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https"):
        return 400, "text/plain; charset=utf-8", b"only http/https", "scheme"
    if _blocked_host(p.hostname or ""):
        return 403, "text/plain; charset=utf-8", b"blocked host", "blocked"
    # 只服务本站发出过的地址：否则挂到域名上就成了任何人都能驱使的公共图片代理
    if not allowed(url):
        return 403, "text/plain; charset=utf-8", b"url not issued by this site", "notallowed"

    headers = {"User-Agent": UA, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
    ref = _referer_for((p.hostname or "").lower())
    if ref:
        headers["Referer"] = ref
    try:
        r = requests.get(url, headers=headers, timeout=TIMEOUT, verify=False, stream=True)
    except Exception as exc:  # noqa: BLE001
        return 502, "text/plain; charset=utf-8", f"upstream failed: {type(exc).__name__}".encode(), "error"

    ctype = (r.headers.get("Content-Type") or "").lower()
    if r.status_code != 200:
        body = f"upstream {r.status_code}".encode()[:200]
        return r.status_code, "text/plain; charset=utf-8", body, "upstream"
    if not ctype.startswith("image/"):
        return 502, "text/plain; charset=utf-8", b"not an image", "type"

    chunks, size = [], 0
    for part in r.iter_content(65536):
        chunks.append(part)
        size += len(part)
        if size > MAX_BYTES:
            return 502, "text/plain; charset=utf-8", b"too large", "size"
    data = b"".join(chunks)

    if len(_mem) > CACHE_MAX:
        for k in sorted(_mem, key=lambda k: _mem[k][0])[:len(_mem) - CACHE_MAX]:
            _mem.pop(k, None)
    _mem[url] = (now, r.status_code, ctype, data)
    return r.status_code, ctype, data, "fetched"
