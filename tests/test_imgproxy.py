# -*- coding: utf-8 -*-
"""图片代理的离线测试：防盗链 Referer 映射与安全边界（不发真实请求）。

    python tests/test_imgproxy.py
"""
import sys
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

print("\n结果:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}")
sys.exit(1 if FAILS else 0)
