# -*- coding: utf-8 -*-
"""图片代理的离线测试：防盗链 Referer 映射与安全边界（不发真实请求）。

    python tests/test_imgproxy.py
"""
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zhuiju import imgproxy  # noqa: E402

FAILS = []


def check(name, cond, got=None):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  got={got!r}"))
    if not cond:
        FAILS.append(name)


print("1) 防盗链 Referer 映射（实测：doubanio 无 Referer→418、本站 Referer→403、豆瓣→200）")
check("img3.doubanio.com 补豆瓣 Referer",
      imgproxy._referer_for("img3.doubanio.com") == "https://movie.douban.com/",
      imgproxy._referer_for("img3.doubanio.com"))
check("子域同样命中", imgproxy._referer_for("a.b.doubanio.com") == "https://movie.douban.com/",
      imgproxy._referer_for("a.b.doubanio.com"))
check("普通图床不补 Referer", imgproxy._referer_for("hhmage.com") == "", imgproxy._referer_for("hhmage.com"))
check("不能被 doubanioX.com 这类前缀骗到",
      imgproxy._referer_for("evil-doubanio.com") == "", imgproxy._referer_for("evil-doubanio.com"))

print("\n2) 内网与非法地址拦截（避免本机代理被打内网）")
for bad in ("127.0.0.1", "localhost", "0.0.0.0", "192.168.1.1", "10.0.0.5", "169.254.1.1", "::1"):
    check(f"拒绝 {bad}", imgproxy._blocked_host(bad) is True, imgproxy._blocked_host(bad))
check("公网 IP 放行", imgproxy._blocked_host("114.114.114.114") is False)
check("域名放行", imgproxy._blocked_host("img3.doubanio.com") is False)

print("\n3) resolve 的入口校验（不触发网络）")
for label, url in (("file 协议", "file:///c:/windows/win.ini"),
                   ("javascript 伪协议", "javascript:alert(1)"),
                   ("相对路径", "/static/app.js"),
                   ("空串", "")):
    code, _ct, _body, note = imgproxy.resolve(url)
    check(f"{label} 被拒（400/scheme）", code == 400 and note == "scheme", (code, note))
code, _ct, _b, note = imgproxy.resolve("http://127.0.0.1:5000/api/health")
check("回环地址被拒（blocked）", code == 403 and note == "blocked", (code, note))

print("\n4) 缓存结构")
imgproxy._mem.clear()
imgproxy._mem["x"] = (0.0, 200, "image/jpeg", b"\xff\xd8")
hit = imgproxy.resolve("x")   # 命中缓存也要走同样的返回形状
check("缓存命中返回 4 元组", isinstance(hit, tuple) and len(hit) == 4, hit)
imgproxy._mem.clear()

print("\n5) 磁盘缓存：重启之后也不用再敲图床")
import json
import tempfile
import time

TMP = Path(tempfile.mkdtemp(prefix="zhuiju_img_"))
_keep = (imgproxy.CACHE_DIR, imgproxy._IDX, imgproxy._disk, imgproxy._disk_loaded,
         imgproxy._urls_file, imgproxy._mem.copy(), imgproxy.requests.get)
imgproxy.CACHE_DIR = TMP / "img"
imgproxy._IDX = TMP / "img" / "index.json"
imgproxy._urls_file = TMP / "img_urls.json"      # 测试地址不许进真实的"本站发出过"清单
imgproxy._disk, imgproxy._disk_loaded = {}, False
imgproxy._mem.clear()
calls = []


class FakeResp:
    def __init__(self, url, code=200, ctype="image/jpeg", body=b"\xff\xd8fake"):
        self.url, self.status_code = url, code
        self.headers = {"Content-Type": ctype}
        self._b = body

    def iter_content(self, n):
        yield self._b


def fake_get(url, **k):
    calls.append(url)
    return resp_next(url)


resp_next = lambda url: FakeResp(url)          # noqa: E731
imgproxy.requests.get = fake_get
U = "https://img.test/a.jpg"
imgproxy.register(U)
try:
    code, ct, body, note = imgproxy.resolve(U)
    check("第一次确实去取（fetched）", (code, note, len(calls)) == (200, "fetched", 1), (code, note, len(calls)))
    files = [p.name for p in imgproxy.CACHE_DIR.iterdir()]
    check("落盘：图片文件与索引都在", any(n == imgproxy._key(U) for n in files) and "index.json" in files, files)
    # 真·重启：内存与已加载的索引全丢掉，只能靠磁盘上那两个文件恢复
    imgproxy._mem.clear()
    imgproxy._disk, imgproxy._disk_loaded = {}, False
    code, ct, body, note = imgproxy.resolve(U)
    check("重启后从磁盘命中，一次请求都不发",
          note == "disk" and len(calls) == 1 and body == b"\xff\xd8fake", (note, len(calls), body))
    check("索引必须与图片文件同步落盘：只清内存不算重启，清掉索引重载才算",
          len(imgproxy._disk) == 1 and U in [v["u"] for v in imgproxy._disk.values()],
          imgproxy._disk)
    check("磁盘命中顺手回填内存", U in imgproxy._mem, list(imgproxy._mem))
    # 过期：把索引里的时间戳推到 TTL 之外
    imgproxy._disk[imgproxy._key(U)]["t"] = time.time() - imgproxy.DISK_TTL - 10
    imgproxy._save_idx()
    imgproxy._mem.clear()
    code, ct, body, note = imgproxy.resolve(U)
    check("超过 7 天的缓存重新取一次，不拿旧图糊弄", note == "fetched" and len(calls) == 2, (note, len(calls)))
    # 失败与非图片一律不落盘
    before = len(imgproxy._disk)
    imgproxy._mem.clear()
    imgproxy.register("https://img.test/404.jpg")
    resp_next = lambda url: FakeResp(url, code=404, ctype="text/plain")      # noqa: E731
    code, ct, body, note = imgproxy.resolve("https://img.test/404.jpg")
    check("上游 404 不进磁盘缓存（否则错误会被钉住 7 天）",
          note == "upstream" and len(imgproxy._disk) == before, (note, len(imgproxy._disk), before))
    imgproxy.register("https://img.test/html.jpg")
    resp_next = lambda url: FakeResp(url, ctype="text/html")                 # noqa: E731
    code, ct, body, note = imgproxy.resolve("https://img.test/html.jpg")
    check("不是 image/* 的不落盘", note == "type" and len(imgproxy._disk) == before, (note, len(imgproxy._disk)))
    # 半截文件不可能被当成命中：先写 .tmp 再改名
    imgproxy._mem.clear()
    resp_next = lambda url: FakeResp(url, body=b"\xff\xd8second-shot")       # noqa: E731
    imgproxy.register("https://img.test/b.jpg")
    imgproxy.resolve("https://img.test/b.jpg")
    strays = [p.name for p in imgproxy.CACHE_DIR.iterdir() if p.name.endswith(".tmp")]
    check("落盘是改名进来的，缓存目录里不留 .tmp", strays == [], strays)
    # 体积上限
    _max = imgproxy.DISK_MAX
    imgproxy.DISK_MAX = 40
    imgproxy._prune_disk()
    total = sum(v["s"] for v in imgproxy._disk.values())
    imgproxy.DISK_MAX = _max
    check("超体积上限就按最久没动的丢", total <= 40, (total, {k: v["s"] for k, v in imgproxy._disk.items()}))
    # 关掉磁盘
    imgproxy._mem.clear()
    _on, imgproxy.DISK_ON = imgproxy.DISK_ON, False
    n0 = len(calls)
    imgproxy.register("https://img.test/c.jpg")
    resp_next = lambda url: FakeResp(url)                                    # noqa: E731
    first = imgproxy.resolve("https://img.test/c.jpg")
    imgproxy._mem.clear()
    second = imgproxy.resolve("https://img.test/c.jpg")
    imgproxy.DISK_ON = _on
    check("ZHUIJU_IMG_DISK=0 时不读磁盘：关缓存后同一张要再取一次",
          first[3] == "fetched" and second[3] == "fetched" and len(calls) - n0 == 2,
          (first[3], second[3], len(calls) - n0))
    check("磁盘统计能报出条目数与体积", set(imgproxy.disk_stats()) >= {"items", "bytes", "dir"},
          imgproxy.disk_stats())
finally:
    (imgproxy.CACHE_DIR, imgproxy._IDX, imgproxy._disk, imgproxy._disk_loaded,
     imgproxy._urls_file, imgproxy._mem, imgproxy.requests.get) = _keep

print("\n6) /img 把「是哪一层答的」写在响应头上")
from zhuiju.app import create_app                # noqa: E402

_keep2 = (imgproxy._urls_file, imgproxy._mem.copy())
imgproxy._urls_file = TMP / "img_urls2.json"
imgproxy._mem.clear()
imgproxy.CACHE_DIR = TMP / "img2"
imgproxy._IDX = TMP / "img2" / "index.json"
imgproxy._disk, imgproxy._disk_loaded = {}, False
try:
    H = "https://hdr.test/h.jpg"
    imgproxy.register(H)
    imgproxy._mem[H] = (time.time(), 200, "image/jpeg", b"\xff\xd8")
    cl = create_app().test_client()
    r = cl.get("/img?url=" + urllib.parse.quote(H, safe=""))
    check("命中内存缓存时头里写 cache", r.status_code == 200 and r.headers.get("X-Img-Cache") == "cache",
          (r.status_code, r.headers.get("X-Img-Cache")))
    check("浏览器侧仍然缓存一天", r.headers.get("Cache-Control") == "public, max-age=86400",
          r.headers.get("Cache-Control"))
    imgproxy._mem.clear()
    resp_next = lambda url: FakeResp(url)        # noqa: E731
    imgproxy.requests.get = fake_get
    r = cl.get("/img?url=" + urllib.parse.quote("https://nosuch.test/n.jpg", safe=""))
    check("没登记过的地址被拒，原因也写在头里（不是闷声 403）",
          r.status_code == 403 and r.headers.get("X-Img-Cache") == "notallowed",
          (r.status_code, r.headers.get("X-Img-Cache")))
    r = cl.get("/img?url=" + urllib.parse.quote("javascript:alert(1)", safe=""))
    check("伪协议同样写清原因", r.headers.get("X-Img-Cache") == "scheme", r.headers.get("X-Img-Cache"))
finally:
    (imgproxy._urls_file, imgproxy._mem) = _keep2

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
