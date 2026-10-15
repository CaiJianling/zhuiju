# -*- coding: utf-8 -*-
"""离线 IP 归属地：解析 ip2region 的 xdb，并把结果映射到世界地图坐标。

全部走标准库（ipaddress / struct / json），不额外装包 —— 实测清华源上没有 ip2region
这个 binding，而 xdb 格式本身很简单，自己读反而更可控。数据文件由 tools/fetch_geo.py
下载，缺文件时这里不抛错，而是标 available=False，让后台页面照常能用并提示该跑哪条命令。

xdb 结构（对齐官方 binding/python/ip2region/{util,searcher}.py，实测过 20 个已知 IP）
  0   u16  结构版本（2 或 3）
  2   u16  索引策略
  4   u32  生成时间
  8   u32  段索引起始指针        12  u32  段索引结束指针
  16  u16  IP 版本（4 / 6）     18  u16  运行时指针字节数
  256 起   向量索引 256×256×8B：按 IP 前两段定位所在段索引块 [s_ptr, e_ptr]
  段索引项 14B：起始IP(4B 小端) 结束IP(4B 小端) 数据长度(2B) 数据指针(4B)
  数据区   UTF-8 字符串 "国家|省|市|ISP|ISO"

IPv4 的段索引里 IP 是**小端**存的，所以比较要把字节序翻回来——这是最容易写错的地方，
写错的症状是查询能返回结果但全错，不会报错。
"""
from __future__ import annotations

import ipaddress
import json
import re
import struct
import threading
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "geo"
XDB_V4 = DATA / "ip2region_v4.xdb"
XDB_V6 = DATA / "ip2region_v6.xdb"
POINTS = DATA / "country_points.json"
BASEMAP = DATA / "ne_110m.geo.json"

HLEN, VCOLS, VSIZE = 256, 256, 8
ISZ_V4, ISZ_V6 = 14, 38
V4_BYTES, V6_BYTES = 4, 16

# 地图投影：等距圆柱（equirectangular），viewBox 0 0 360 180
MAP_W, MAP_H = 360.0, 180.0
_lock = threading.Lock()
_cache: dict[str, object] = {"buf4": None, "buf6": None, "points": None, "paths": None,
                             "loaded": False}


# --- 载入 -----------------------------------------------------------------
def _load() -> None:
    if _cache["loaded"]:
        return
    with _lock:
        if _cache["loaded"]:
            return
        for key, path in (("buf4", XDB_V4), ("buf6", XDB_V6)):
            if path.exists():
                try:
                    _cache[key] = path.read_bytes()
                except OSError:
                    _cache[key] = None
        if POINTS.exists():
            try:
                _cache["points"] = json.loads(POINTS.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _cache["points"] = None
        _cache["loaded"] = True


def reset() -> None:
    """让下次查询重新读文件（fetch_geo 更新完数据、或测试换路径时用）。"""
    with _lock:
        for k in ("buf4", "buf6", "points", "paths"):
            _cache[k] = None
        _cache["loaded"] = False


def available() -> dict:
    """各份数据在不在，页面据此决定显示什么、提示什么。"""
    _load()
    return {
        "xdb": bool(_cache["buf4"]),
        "xdb_v6": bool(_cache["buf6"]),
        "points": bool(_cache["points"]),
        "basemap": BASEMAP.exists(),
        "ready": bool(_cache["buf4"] and _cache["points"]),
    }


# --- xdb 查询 -------------------------------------------------------------
def _u16(b: bytes, o: int) -> int:
    return struct.unpack_from("<H", b, o)[0]


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def _search(buf: bytes, ip_bytes: bytes, isz: int, ip_int: int) -> str:
    """向量索引定位段块，再二分。isz 是段索引项长度（v4=14 / v6=38）。"""
    idx = HLEN + ip_bytes[0] * VCOLS * VSIZE + ip_bytes[1] * VSIZE
    s_ptr, e_ptr = _u32(buf, idx), _u32(buf, idx + 4)
    # 指针为 0 表示这块源数据缺失（库里允许有空洞），不是"查询失败"
    if not s_ptr or not e_ptr:
        return ""
    lo, hi, dlen, dptr = 0, int((e_ptr - s_ptr) / isz), 0, 0
    n = len(ip_bytes)
    while lo <= hi:
        mid = (lo + hi) >> 1
        p = s_ptr + mid * isz
        rec = buf[p:p + isz]
        # 起始 IP 在 [0:n]、结束 IP 在 [n:2n]，都是小端存的，翻成大端整数再比
        start = int.from_bytes(rec[0:n], "little")
        end = int.from_bytes(rec[n:2 * n], "little")
        if ip_int < start:
            hi = mid - 1
        elif ip_int > end:
            lo = mid + 1
        else:
            dlen = _u16(rec, 2 * n)
            dptr = _u32(rec, 2 * n + 2)
            break
    if not dlen:
        return ""
    return buf[dptr:dptr + dlen].decode("utf-8", "replace")


def _region(ip: str) -> tuple[str, ...]:
    """返回 (国家, 省, 市, ISP, ISO)；查不到给全空。"""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ("",) * 5
    packed, isz = addr.packed, ISZ_V6 if addr.version == 6 else ISZ_V4
    key = "buf6" if addr.version == 6 else "buf4"
    buf = _cache.get(key)
    if not isinstance(buf, bytes):
        return ("",) * 5
    raw = _search(buf, packed, isz, int(addr))
    parts = raw.split("|") if raw else []
    if len(parts) < 5:
        parts = (parts + ["", "", "", "", ""])[:5]
    return tuple(p.strip() for p in parts[:4] + [parts[-1].upper()])


def _tidy(v: str) -> str:
    """库里的占位值是 "0"（还有 "0.0.0.0" 之类），当空处理。"""
    return "" if v in ("0", "N/A", "None", "unknown", "Unknown") else v


# 这些段没有地理归属，但含义各不相同，文案要分得开
NON_GEO = (
    ("192.0.2.0/24", "文档用例"), ("198.51.100.0/24", "文档用例"), ("203.0.113.0/24", "文档用例"),
    ("100.64.0.0/10", "运营商级 NAT"), ("198.18.0.0/15", "基准测试"),
)


def classify(ip: str) -> str:
    """把 IP 分成 public / private / reserved / loopback / invalid / unsupported。

    先按 RFC 自己判，再落到库：内网与保留段不该送去查库，也不该显示成"某个国家"。
    顺序有意讲究：Python 3.13 把 203.0.113.0/24 这类**文档用例**段也算作 is_private，
    若先判 private 就会把 TEST-NET 说成"内网"；那些不是局域网地址，归到保留更准确。
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "invalid"
    if addr.is_loopback:
        return "loopback"
    if addr.is_link_local or addr.is_multicast or addr.is_reserved or addr.is_unspecified:
        return "reserved"
    if addr.version == 4 and any(addr in ipaddress.ip_network(c) for c, _ in NON_GEO):
        return "reserved"
    if addr.is_private:
        return "private"
    if addr.version == 6 and not _cache.get("buf6"):
        return "unsupported"      # 没下 IPv6 库：直说，别用 v4 库瞎查
    return "public"


# 内网/保留地址在页面上的说法：这是这台机器最常见的情况，得有明确文案
KIND_LABEL = {
    "loopback": "本机",
    "private": "内网",
    "reserved": "保留地址",
    "unsupported": "IPv6（未下库）",
    "invalid": "非法地址",
    "public": "",
    "nolib": "未下载归属地库",
}


def points() -> dict:
    """ISO 国家码 -> {name, lat, lon, cont}，由 tools/fetch_geo.py 从 50m 底图算出来。"""
    _load()
    return _cache.get("points") or {}


def locate(ip: str) -> dict:
    """一个 IP 的归属地 + 地图坐标。任何输入都不抛异常。"""
    _load()
    kind = classify(ip)
    out = {"ip": ip, "kind": kind, "country": "", "province": "", "city": "",
           "isp": "", "iso": "", "name": "", "lat": None, "lon": None, "label": ""}
    if kind == "public":
        if not _cache.get("buf4") and not _cache.get("buf6"):
            out["kind"] = "nolib"
            out["label"] = KIND_LABEL["nolib"]
            return out
        out["country"], out["province"], out["city"], out["isp"], out["iso"] = _region(ip)
        out["country"] = _tidy(out["country"])
        out["province"] = _tidy(out["province"])
        out["city"] = _tidy(out["city"])
        out["isp"] = _tidy(out["isp"])
        # 库对某些保留段也给 'Reserved'，别把它当国家显示
        if out["country"] in ("Reserved", "IANA", ""):
            out["kind"] = "reserved"
            out["country"] = ""
        elif out["iso"] in ("0", "") or len(out["iso"]) != 2:
            out["iso"] = ""
    if out["kind"] != "public":
        out["label"] = KIND_LABEL.get(out["kind"], "未知")
        return out

    pts = _cache.get("points") or {}
    p = pts.get(out["iso"])
    if p:
        out["name"] = p.get("name", "")
        out["lat"], out["lon"] = p.get("lat"), p.get("lon")
    label = out["country"] or out["name"] or "未知"
    # 国内的省+市对这台机器上的使用场景最有用；境外给到国家就够，
    # 因为库的境外省级名是英文原文，混在表格里更长更乱
    detail = "".join(x for x in (out["province"], out["city"]) if x) if out["iso"] == "CN" else ""
    tail = f" · {out['isp']}" if out["isp"] and len(out["isp"]) <= 24 else ""
    out["label"] = re.sub(r"\s+", " ", f"{label} {detail}{tail}").strip()
    return out


# --- 地图几何 -------------------------------------------------------------
def project(lon: float, lat: float) -> tuple[float, float]:
    """等距圆柱投影：经度直接当 x，纬度翻转当 y（屏幕 y 轴向下）。"""
    return (lon + 180.0, 90.0 - lat)


def _rings(geom: dict):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    return list(geom["coordinates"])


def basemap() -> dict:
    """把 110m 国家轮廓转成内嵌 SVG 用的路径串（进程内算一次就缓存）。

    返回 {"d": 整张地图的 path, "by_iso": {ISO: 该国的 path}}，
    by_iso 让"有查询记录的国家"能被单独描色。
    精度取 0.1°（约 11km），在这个尺度上看不出来，路径数据能小一半。
    """
    _load()
    if isinstance(_cache["paths"], dict):
        return _cache["paths"]
    out = {"d": "", "by_iso": {}, "error": "没有底图文件"}
    if BASEMAP.exists():
        try:
            feats = json.loads(BASEMAP.read_text(encoding="utf-8"))["features"]
        except (OSError, ValueError, KeyError) as exc:
            out["error"] = f"底图解析失败：{type(exc).__name__}"
            _cache["paths"] = out
            return out
        parts, by_iso = [], {}
        for f in feats:
            geom, p = f.get("geometry"), f.get("properties") or {}
            iso = next((c for c in (p.get("ISO_A2"), p.get("ISO_A2_EH"))
                        if c and c != "-99"), "")
            if not geom:
                continue
            segs = []
            for rs in _rings(geom):
                for ring in rs:
                    if len(ring) < 4:
                        continue
                    d = "M" + "L".join("%.1f,%.1f" % project(x, y) for x, y in ring) + "Z"
                    segs.append(d)
            if not segs:
                continue
            one = "".join(segs)
            parts.append(one)
            if iso:
                by_iso[iso] = by_iso.get(iso, "") + one
        out = {"d": "".join(parts), "by_iso": by_iso, "error": ""}
    _cache["paths"] = out
    return out
