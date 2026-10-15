# -*- coding: utf-8 -*-
"""把上游 awesome-zhuiju-free 的结构化数据转成本地检索目录。

只保留事实性字段（名称/地址/分类/标签/评分/可用状态），用于站内搜索导航。
数据版权归上游仓库，本工具不做内容转发。
"""
import json
from datetime import datetime
from pathlib import Path

import requests

REPO_RAW = "https://raw.githubusercontent.com/laoma528/awesome-zhuiju-free/main/"
MIRRORS = ["https://gh-proxy.com/", "https://ghproxy.net/", "https://ghfast.top/",
           "https://mirror.ghproxy.com/", "https://raw.githubusercontent.com/"]
MIRROR_LOG = None   # 在 main() 里定成 data/cache/mirror_used.json
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


USED = {}


def fetch(rel_path: str, dest: Path) -> bool:
    """国内环境优先走 gh-proxy 一类加速源拉 GitHub raw 文件。

    实际用了哪个源要记下来，更新进度里会显示——否则看不出加速有没有生效。
    纯 Python 实现（requests），不依赖机器上有没有 curl。
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for pre in MIRRORS:
        url = pre + REPO_RAW + rel_path
        label = pre.rstrip("/").replace("https://", "")
        try:
            with requests.get(url, timeout=40, headers={"User-Agent": UA},
                              allow_redirects=True) as r:
                if r.status_code != 200:
                    print(f"  {url} -> HTTP {r.status_code}")
                    continue
                body = r.content
        except Exception as exc:  # noqa: BLE001 - 一个镜像不通就换下一个
            print(f"  {url} -> {type(exc).__name__}")
            continue
        # 镜像挂了常常返回一个几百字节的错误页，按体积和 JSON 头判一下
        if len(body) > 1000 and body.lstrip()[:1] in (b"{", b"["):
            tmp.write_bytes(body)
            tmp.replace(dest)
            print(f"  拉取 {url}  ({len(body)} bytes)  源={label}")
            USED[rel_path] = {"mirror": label, "bytes": len(body)}
            return True
        print(f"  {url} -> 内容不像 JSON 或过小（{len(body)} bytes），换下一个源")
    tmp.unlink(missing_ok=True)
    return False


def upstream(base: Path):
    """每次都重新拉上游：本地已有文件不能当主路径，否则"每日更新目录"是空转的。

    只有在所有镜像与直连都失败时，才退回本地已有副本（并说明它可能已过期）。
    """
    d = base / "data" / "upstream"
    res = d / "resources.json"
    av = d / "availability.json"
    for path, rel in ((res, "resources/resources.json"), (av, "reports/availability.json")):
        if fetch(rel, path):
            continue
        if path.exists():
            print(f"  镜像与直连都失败，沿用本地旧副本 {path.name}"
                  f"（{datetime.fromtimestamp(path.stat().st_mtime):%Y-%m-%d}）")
            continue
        scratch = base / ".probe" / f"zj_{path.name}"
        if scratch.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(scratch.read_bytes())
            print(f"  沿用已下载的 {rel}")
            continue
        raise SystemExit(f"无法获取上游 {rel}：镜像与直连都失败，且没有本地副本")
    return res, av

CATEGORY_CN = {
    "online_video": "在线影视",
    "video_app": "影视APP",
    "cloud_search": "网盘搜索",
    "magnet_search": "磁力 & BT",
    "subtitles": "字幕资源",
    "player": "TVBox 空壳",
    "tvbox_config": "TVBox 配置",
    "subscription": "直播源",
    "open_source": "开源项目",
}
STATUS_CN = {
    "ok": "可访问",
    "reachable": "可访问",
    "restricted": "访问受限",
    "unreachable": "无法访问",
    "failed": "无法访问",
    "unchecked": "未检测",
    None: "未检测",
}


def dump_mirror(base: Path) -> None:
    if not USED:
        return
    out = base / "data" / "cache" / "mirror_used.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    first = next(iter(USED.values()))
    out.write_text(json.dumps({"mirror": first["mirror"], "bytes": first["bytes"],
                               "detail": USED}, ensure_ascii=False, indent=2),
                   encoding="utf-8")


def main():
    base = Path(__file__).resolve().parent.parent
    res_path, av_path = upstream(base)
    raw = json.loads(res_path.read_text(encoding="utf-8"))
    status, checked_at = {}, {}
    if av_path.exists():
        av = json.loads(av_path.read_text(encoding="utf-8"))
        for r in av.get("results", []):
            status[r["resource_id"]] = r.get("status")
            checked_at[r["resource_id"]] = (r.get("checked_at") or "")[:10]

    items = []
    for r in raw["resources"]:
        acc = r.get("access") or {}
        hints = []
        if acc.get("requires_login"):
            hints.append("需登录")
        regions = acc.get("regions") or []
        if regions and regions != ["CN"]:
            hints.append("/".join(regions))
        items.append({
            "id": r["id"],
            "name": r["name"],
            "url": r["url"],
            "category": r["category"],
            "category_cn": CATEGORY_CN.get(r["category"], r["category"]),
            "tags": r.get("tags") or [],
            "scores": r.get("scores") or {},
            "recommended": int((r.get("scores") or {}).get("more") or 0),
            "featured": bool(r.get("featured")),
            "hints": hints,
            "status": STATUS_CN.get(status.get(r["id"]), "未检测"),
            "status_key": status.get(r["id"]) or "unchecked",
            "checked_at": checked_at.get(r["id"], ""),
        })

    items.sort(key=lambda x: (x["category"], -x["recommended"], x["name"]))
    out = base / "zhuiju" / "data"
    out.mkdir(parents=True, exist_ok=True)
    (out / "catalog.json").write_text(
        json.dumps({"generated_from": "laoma528/awesome-zhuiju-free",
                    "updated_at": raw.get("updated_at"), "items": items},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    dump_mirror(base)
    print(f"catalog items={len(items)}")


if __name__ == "__main__":
    main()
