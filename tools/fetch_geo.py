# -*- coding: utf-8 -*-
"""下载 IP 归属地库与世界地图底图，并生成地图要用的国家坐标表。

    python tools/fetch_geo.py              下载并生成坐标表
    python tools/fetch_geo.py --check      只看现有文件的状态，不联网
    python tools/fetch_geo.py --with-v6    额外下 IPv6 库（35MB，默认不下）

三份数据（都走 gh-proxy 一类的国内镜像，理由见 README"国内环境准备"）：

  ip2region_v4.xdb        10.6MB  IP -> 国家|省|市|ISP|ISO，55 万网段
  ne_110m...geojson        0.8MB  画地图用的国家轮廓（要素少，内嵌进页面才扛得住）
  ne_50m...geojson         2.9MB  只用来算国家坐标：110m 少了新加坡、马耳他这类小城邦，
                                  marker 会没地方落，而 50m 的 238 个国家是全的

坐标算完就写进 country_points.json（几十 KB），运行时不再解析 2.9MB 的 50m，
所以 50m 只有重新生成坐标表时才需要。
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "data" / "geo"
MIRRORS = ["https://gh-proxy.com/", "https://ghproxy.net/", "https://ghfast.top/",
           "https://mirror.ghproxy.com/", "https://raw.githubusercontent.com/"]
NE = "nvkelso/natural-earth-vector/master/geojson/"
IP2 = "lionsoul2014/ip2region/master/data/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# rel 路径 -> (落地文件名, 最小可信体积)：镜像挂了常返回几百字节的错误页，按体积挡一道
FILES = [
    (IP2 + "ip2region_v4.xdb", "ip2region_v4.xdb", 8_000_000),
    (NE + "ne_110m_admin_0_countries.geojson", "ne_110m.geo.json", 200_000),
    (NE + "ne_50m_admin_0_countries.geojson", "ne_50m.geo.json", 1_000_000),
]
V6 = (IP2 + "ip2region_v6.xdb", "ip2region_v6.xdb", 20_000_000)


def fetch(rel: str, dest: Path, min_bytes: int, label_out: str) -> dict | None:
    """按镜像链下载；每个镜像都试一遍，全挂就返回 None（由调用方决定沿用旧文件还是报错）。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for pre in MIRRORS:
        url = pre + "https://raw.githubusercontent.com/" + rel
        name = pre.rstrip("/").replace("https://", "") or "直连 GitHub"
        t0 = time.time()
        try:
            with requests.get(url, headers={"User-Agent": UA}, timeout=(8, 300),
                              stream=True, allow_redirects=True) as r:
                if r.status_code != 200:
                    print(f"    {name:<24} HTTP {r.status_code}")
                    continue
                n = 0
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_content(1 << 16):
                        fh.write(chunk)
                        n += len(chunk)
        except Exception as exc:  # noqa: BLE001 - 一个源不通就换下一个
            print(f"    {name:<24} {type(exc).__name__}: {str(exc)[:60]}")
            tmp.unlink(missing_ok=True)
            continue
        if n < min_bytes:
            print(f"    {name:<24} 只有 {n} 字节，不像真文件，换下一个源")
            tmp.unlink(missing_ok=True)
            continue
        tmp.replace(dest)
        ms = round((time.time() - t0) * 1000)
        print(f"    {name:<24} {n / 1048576:.2f}MB  {ms}ms")
        return {"file": label_out, "bytes": n, "mirror": name, "ms": ms}
    tmp.unlink(missing_ok=True)
    return None


# --- 国家坐标 -------------------------------------------------------------
# 算质心用"最大那个多边形的面积加权形心"，而不是所有点的平均值：
# 俄罗斯、美国这类跨半球的国家，平均点会被阿拉斯加/楚科奇拖到错的地方，
# 取主体那块既能落在国境里，也天然避开了 180° 经线环绕的问题。
def _rings(geom: dict):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    return list(geom["coordinates"])


# 母国的海外省 / 极小岛：Natural Earth 并进了母国要素或干脆没有，但 ip2region 会
# 单独给出这些码。不补的话就是"查得出归属地，图上却没有位置"。
EXTRA_POINTS = {
    "BQ": ("Caribbean Netherlands", 12.16, -68.29, "North America"),
    "GF": ("French Guiana", 3.93, -53.13, "South America"),
    "GI": ("Gibraltar", 36.14, -5.35, "Europe"),
    "GP": ("Guadeloupe", 16.24, -61.55, "North America"),
    "MQ": ("Martinique", 14.64, -61.02, "North America"),
    "RE": ("Réunion", -21.12, 55.54, "Africa"),
    "SJ": ("Svalbard and Jan Mayen", 78.22, 15.63, "Europe"),
    "TK": ("Tokelau", -9.20, -171.84, "Oceania"),
    "YT": ("Mayotte", -12.83, 45.14, "Africa"),
}


def _ring_area(pts: list) -> float:
    """鞋带公式，单位是"平方度"，只用来比大小。"""
    s = 0.0
    for i in range(len(pts) - 1):
        x1, y1 = pts[i][0], pts[i][1]
        x2, y2 = pts[i + 1][0], pts[i + 1][1]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _centroid(pts: list) -> tuple[float, float]:
    """面积加权形心；退化成交叉线的环就退回包围盒中心。"""
    a = sx = sy = 0.0
    for i in range(len(pts) - 1):
        x1, y1 = pts[i][0], pts[i][1]
        x2, y2 = pts[i + 1][0], pts[i + 1][1]
        cross = x1 * y2 - x2 * y1
        a += cross
        sx += (x1 + x2) * cross
        sy += (y1 + y2) * cross
    if abs(a) < 1e-9:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    a *= 0.5
    return (sx / (6 * a), sy / (6 * a))


def country_points(geojson_path: Path) -> dict:
    d = json.loads(geojson_path.read_text(encoding="utf-8"))
    out, area = {}, {}
    for f in d["features"]:
        p = f.get("properties") or {}
        # Natural Earth 把法国、挪威这类国家的 ISO_A2 记成 -99，得靠 ISO_A2_EH 兜底，
        # 否则这两个国家的 marker 无处可去
        code = next((c for c in (p.get("ISO_A2"), p.get("ISO_A2_EH"))
                     if c and c != "-99"), None)
        geom = f.get("geometry")
        if not code or not geom:
            continue
        best, best_a = None, -1.0
        for rings in _rings(geom):
            outer = rings[0]
            if len(outer) < 4:
                continue
            a = _ring_area(outer)
            if a > best_a:
                best, best_a = outer, a
        if best is None:
            continue
        # 同一个码可能被多个要素认领：澳属外部领地（Ashmore and Cartier Is. 之类）的
        # ISO_A2_EH 也是 AU，按写入顺序就会让澳洲的 marker 落到海上那块小岛上。
        # 只保留面积最大的要素——主体国土永远比飞地大，结果就与遍历顺序无关。
        if best_a <= area.get(code, -1.0):
            continue
        area[code] = best_a
        lon, lat = _centroid(best)
        out[code] = {"name": p.get("NAME") or p.get("ADMIN") or code,
                     "lat": round(lat, 3), "lon": round(lon, 3),
                     "cont": p.get("CONTINENT") or ""}
    # 剩下这几个是母国的海外省/极小岛，Natural Earth 把它们并进了母国要素或干脆没有，
    # 但 ip2region 会单独给出这些码，不补就会"查得出归属地却在图上没有位置"
    for code, (name, lat, lon, cont) in EXTRA_POINTS.items():
        out.setdefault(code, {"name": name, "lat": lat, "lon": lon, "cont": cont})
    return out


def xdb_countries(path: Path) -> dict:
    """扫一遍库，拿到它实际会吐出的国家码全集，用来检查坐标表覆没覆盖上。"""
    buf = path.read_bytes()
    u16 = lambda o: int.from_bytes(buf[o:o + 2], "little")
    u32 = lambda o: int.from_bytes(buf[o:o + 4], "little")
    s_ptr, e_ptr, isz = u32(8), u32(12), 14
    n = int((e_ptr - s_ptr) / isz)
    found: dict[str, str] = {}
    for i in range(n):
        p = s_ptr + i * isz
        dlen, dptr = u16(p + 8), u32(p + 10)
        if not dlen:
            continue
        parts = buf[dptr:dptr + dlen].decode("utf-8", "replace").split("|")
        if len(parts) < 5:
            continue
        code, name = parts[-1].strip(), parts[0].strip()
        if len(code) == 2 and code.isalpha():
            found.setdefault(code.upper(), name)
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="不联网，只看现有文件")
    ap.add_argument("--with-v6", action="store_true", help="额外下载 IPv6 库（35MB）")
    args = ap.parse_args()

    manifest = OUT / "manifest.json"
    had = {}
    if manifest.exists():
        try:
            had = json.loads(manifest.read_text(encoding="utf-8"))
        except ValueError:
            had = {}

    if args.check:
        print("=== 本地文件状态 ===")
        for _, name, _ in FILES + ([V6] if args.with_v6 else []):
            p = OUT / name
            size = f"{p.stat().st_size / 1048576:.2f}MB" if p.exists() else "—"
            print(f"  {name:<28} {'在' if p.exists() else '缺'}  {size}")
        pts = OUT / "country_points.json"
        print(f"  country_points.json        {'在' if pts.exists() else '缺'}")
        return 0 if all((OUT / n).exists() for _, n, _ in FILES) and pts.exists() else 1

    print("=== 下载 ===")
    got, failed = [], []
    for rel, name, minb in FILES + ([V6] if args.with_v6 else []):
        print(f"  {name}")
        dest = OUT / name
        res = fetch(rel, dest, minb, name)
        if res:
            got.append(res)
        elif dest.exists():
            print(f"    下载失败，沿用本地已有副本（{datetime.fromtimestamp(dest.stat().st_mtime):%Y-%m-%d}）")
            got.append({"file": name, "bytes": dest.stat().st_size,
                        "mirror": "沿用本地", "ms": 0})
        else:
            failed.append(name)
    if failed:
        print(f"\n这些文件既没下到也没有本地副本：{failed}\n归属地功能需要 ip2region_v4.xdb + 底图才能工作。")
        return 1

    print("\n=== 生成国家坐标表（取自 50m，110m 缺小城邦）===")
    pts = country_points(OUT / "ne_50m.geo.json")
    (OUT / "country_points.json").write_text(
        json.dumps(pts, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"  写入 {len(pts)} 个国家坐标")

    codes = xdb_countries(OUT / "ip2region_v4.xdb")
    miss = sorted({(c, n) for c, n in codes.items() if c not in pts})
    print(f"  库里共 {len(codes)} 个国家码，坐标表没覆盖的 {len(miss)} 个"
          + (f"：{miss}" if miss and len(miss) <= 12 else ""))
    drawn = {f["properties"].get("ISO_A2") or f["properties"].get("ISO_A2_EH")
             for f in json.loads((OUT / "ne_110m.geo.json").read_text(encoding="utf-8"))["features"]}
    print(f"  110m 能画出轮廓的国家 {len(drawn)} 个；"
          f"库里 {len(codes)} 个里有 {sum(1 for c in codes if c in drawn)} 个能被画出来"
          f"（其余只在表格与 marker 里出现，底图没这块轮廓）")

    manifest.write_text(json.dumps({
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "files": got,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n完成，清单写在", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
