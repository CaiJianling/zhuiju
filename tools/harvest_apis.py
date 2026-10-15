# -*- coding: utf-8 -*-
"""从 awesome-zhuiju-free 的 TVBox 配置地址中提取可 HTTP 调用的采集接口。"""
import json
import re
from urllib.parse import urlparse

import requests

requests.packages.urllib3.disable_warnings()

CONFIGS = [
    ("饭太硬", "http://www.饭太硬.net/tv"),
    ("肥猫", "http://肥猫.net/"),
    ("老刘备", "https://raw.liucn.cc/box/m.json"),
    ("小马", "https://szyyds.cn/tv/x.json"),
    ("摸鱼儿", "http://摸鱼儿.cc"),
    ("王二小", "http://new.王二小放牛娃.top"),
    ("小盒子4K", "http://xhztv.top/4k.json"),
    ("小盒子单仓", "http://xhztv.top/xhz"),
    ("VOX", "http://rihou.cc:88/demo.php"),
    ("嗷呜", "http://itv666.cc/aowu/config.webp"),
    ("无名", "https://6800.kstore.vip/fish.json"),
    ("小盒子多仓", "http://xhztv.top/dc"),
    ("拾光多仓", "http://xmbjm.fh4u.org/dc.txt"),
    ("挺好分享多仓", "http://ztha.top/TVBox/GYCK.json"),
]

HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

# 需要 Java jar 才能解析的，无法直接用 HTTP 调
JAR_HINT = re.compile(r"csp_|\.jar", re.I)


def get(url):
    for cand in (url, url.replace("http://", "https://")):
        try:
            r = requests.get(cand, headers=HDRS, timeout=15, verify=False)
            if r.ok and r.text.strip():
                return r.text
        except Exception:
            continue
    return None


def parse_json(text):
    if not text:
        return None
    t = text.strip()
    # 配置内可能带注释行
    try:
        return json.loads(t)
    except Exception:
        pass
    cleaned = "\n".join(
        ln for ln in t.splitlines() if not ln.strip().startswith("//")
    )
    try:
        return json.loads(cleaned)
    except Exception:
        return None


def looks_like_api(api):
    if not isinstance(api, str) or not api.lower().startswith("http"):
        return False
    if JAR_HINT.search(api):
        return False
    return True


def harvest(obj, source, acc):
    """递归收集 sites 条目。"""
    if not isinstance(obj, dict):
        return
    for s in obj.get("sites", []) or []:
        if isinstance(s, dict) and looks_like_api(s.get("api", "")):
            acc.append({
                "source": source,
                "name": s.get("name", ""),
                "api": s["api"],
                "type": s.get("type"),
                "host": urlparse(s["api"]).netloc,
            })
    # 多仓配置：urls 指向下层 json
    for u in obj.get("urls", []) or []:
        if isinstance(u, dict):
            url = u.get("url", "")
            if url.lower().startswith("http") and not url.endswith((".jar", ".png", ".webp")):
                sub = parse_json(get(url))
                if sub:
                    harvest(sub, f"{source}/{u.get('name', '')}", acc)


def main():
    acc = []
    log = []
    for name, url in CONFIGS:
        text = get(url)
        obj = parse_json(text)
        if obj is None:
            log.append(f"[FAIL] {name} {url}")
            continue
        before = len(acc)
        harvest(obj, name, acc)
        log.append(f"[ OK ] {name} {url} -> {len(acc) - before} sites")

    # 去重：同一 host 只留第一次出现的
    seen, uniq = set(), []
    for s in acc:
        if s["host"] in seen:
            continue
        seen.add(s["host"])
        uniq.append(s)

    with open(".probe/candidates.json", "w", encoding="utf-8") as f:
        json.dump(uniq, f, ensure_ascii=False, indent=2)
    with open(".probe/config_log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(log) + f"\n\nraw={len(acc)} unique_host={len(uniq)}\n")
        for s in uniq:
            f.write(f"{s['source']} | {s['name']} | {s['api']}\n")
    print(f"raw={len(acc)} unique={len(uniq)}")


if __name__ == "__main__":
    main()
