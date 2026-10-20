# -*- coding: utf-8 -*-
"""图片代理：解决第三方海报的防盗链与证书问题。

实测：豆瓣图床 img*.doubanio.com 无 Referer 返回 418、带本站 Referer 返回 403、
只有带 https://movie.douban.com/ 才 200；而部分采集站图床挂在非标端口 + 自签证书上
（浏览器静默失败）。浏览器里伪造不了 Referer，所以由本站代取。

缓存三层，各管一段：浏览器 `Cache-Control: max-age=86400`（同一台机器一天内不回头问本站）、
进程内 `_mem`（这次请求真的不用再出去）、磁盘 `data/cache/img/`（重启之后还在，
也免得每台设备各去敲一次别人的图床）。只缓存"200 + image/*"的应答，
失败与 403 一律不落盘 —— 那些结论必须每次都重新判。

安全上收紧到：只允许 http/https、拒绝回环与内网地址、限制体积与类型，
并且只代理本站页面里发出过的图片地址（register/allowed），避免变成公共代理。
"""
from __future__ import annotations

import hashlib
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
MEM_TTL = 3600               # 内存里一小时
DISK_TTL = 7 * 86400         # 磁盘上 7 天：海报换了我自己会拿到新地址（URL 变了就是新键）
DISK_MAX = 200 << 20         # 磁盘缓存总量上限，超了按最久没动的丢

# 按域名给防盗链补 Referer
REFERERS = {
    "doubanio.com": "https://movie.douban.com/",
    "douban.com": "https://movie.douban.com/",
}

_mem: dict[str, tuple[float, int, str, bytes]] = {}
CACHE_DIR = Path(__file__).resolve().parent / "data" / "cache" / "img"
_IDX = CACHE_DIR / "index.json"
# 磁盘索引：sha1(地址) -> {u 地址, c 类型, s 字节数, t 落盘时间}
_disk: dict[str, dict] = {}
_disk_loaded = False
DISK_ON = os.environ.get("ZHUIJU_IMG_DISK", "1") != "0"
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


def _key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:32]


def _load_disk() -> None:
    """读磁盘索引：条目与文件必须一一对上。

    文件名就是键（不带扩展名，类型记在索引里），不存在"存的扩展名与算出来的不一致"这类错位。
    索引里没记的文件是真孤儿（索引每次落盘都是即时的，不会滞后于文件），清掉以免磁盘只涨不降。
    """
    global _disk, _disk_loaded
    _disk_loaded = True
    if not DISK_ON or not CACHE_DIR.is_dir():
        _disk = {}
        return
    try:
        rows = json.loads(_IDX.read_text(encoding="utf-8"))
        _disk = {k: v for k, v in rows.items()
                 if isinstance(v, dict) and v.get("u") and v.get("c", "").startswith("image/")}
    except Exception:  # noqa: BLE001 - 索引坏了就当没有，重新攒
        _disk = {}
    alive = set()
    for k in list(_disk):
        if (CACHE_DIR / k).exists():
            alive.add(k)
        else:
            _disk.pop(k, None)
    for f in CACHE_DIR.iterdir():
        if f.name != _IDX.name and f.name not in alive:
            try:
                f.unlink()
            except OSError:
                pass


def _save_idx() -> None:
    """索引即时落盘：先写临时文件再改名。

    这里的"即时"是必须的 —— 一旦允许索引滞后于图片文件，下次启动时那些还没记进索引的
    图片就成了"孤儿"，被上面的清理删掉，缓存等于被自己删了（第一版就踩了这个坑：
    5 秒节流 + 重启，一次删掉了 22 张里没来得及登记的那些）。
    """
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _IDX.with_name(_IDX.name + ".tmp")
        tmp.write_text(json.dumps(_disk, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_IDX)
    except OSError:
        pass


def _find_disk(url: str):
    """命中且没过期就返回 (状态码, 类型, 内容)。"""
    if not DISK_ON:
        return None
    if not _disk_loaded:
        _load_disk()
    k = _key(url)
    ent = _disk.get(k)
    if not ent:
        return None
    if time.time() - float(ent.get("t") or 0) > DISK_TTL:
        _drop_disk(k)
        return None
    f = CACHE_DIR / k
    try:
        data = f.read_bytes()
    except OSError:
        _drop_disk(k)
        return None
    return 200, ent["c"], data


def _drop_disk(k: str) -> None:
    """丢掉一个条目并把它的文件一起删掉（过期、损坏、被剪枝都走这里）。"""
    _disk.pop(k, None)
    try:
        (CACHE_DIR / k).unlink(missing_ok=True)
    except OSError:
        pass


def _put_disk(url: str, ctype: str, data: bytes) -> None:
    if not DISK_ON:
        return
    if not _disk_loaded:
        _load_disk()
    k = _key(url)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        f = CACHE_DIR / k                      # 文件名只放键：类型从索引里读，不靠扩展名
        tmp = f.with_name(k + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(f)            # 先写临时文件再改名：半截文件不会被当成缓存命中
    except OSError:
        return
    _disk[k] = {"u": url, "c": ctype, "s": len(data), "t": time.time()}
    _prune_disk()
    _save_idx()


def _prune_disk() -> None:
    """超体积就按最久没动的丢（磁盘上限是个兜底，不是让它长到填满分区）。"""
    total = sum(int(v.get("s") or 0) for v in _disk.values())
    if total <= DISK_MAX:
        return
    for k, v in sorted(_disk.items(), key=lambda kv: kv[1].get("t") or 0):
        if total <= DISK_MAX * 0.8:        # 一次多清一点，别每张都在上限边上反复进出
            break
        total -= int(v.get("s") or 0)
        _drop_disk(k)


def disk_stats() -> dict:
    if not _disk_loaded:
        _load_disk()
    return {"items": len(_disk), "bytes": sum(int(v.get("s") or 0) for v in _disk.values()),
            "dir": str(CACHE_DIR)}


def resolve(url: str) -> tuple[int, str, bytes, str]:
    """返回 (状态码, Content-Type, 内容, 说明)。内存 → 磁盘 → 上游，逐层兜。"""
    now = time.time()
    hit = _mem.get(url)
    if hit and now - hit[0] < MEM_TTL:
        return hit[1], hit[2], hit[3], "cache"
    disk = _find_disk(url)
    if disk:
        _mem[url] = (now, disk[0], disk[1], disk[2])   # 回填内存，下一次连磁盘都不用读
        return disk[0], disk[1], disk[2], "disk"

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
    _put_disk(url, ctype, data)      # 只有走到这里的才落盘：200 且确实是 image/*
    return r.status_code, ctype, data, "fetched"
