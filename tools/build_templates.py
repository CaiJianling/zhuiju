# -*- coding: utf-8 -*-
"""复核搜索模板有效性并落到 zhuiju/data/templates.json。

判据：用第二个关键词实际请求，最终 URL 必须仍带关键词参数，且页面有足够正文。
只保留通过复核的模板；未通过的站点退回首页链接。
"""
import json
import re
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

requests.packages.urllib3.disable_warnings()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HDRS = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
KW2 = "流浪地球"

base = Path(__file__).resolve().parent.parent
(base / ".probe").mkdir(exist_ok=True)
probe_path = base / ".probe" / "url_templates.json"
if probe_path.exists():
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
else:
    # 定时刷新会在没有手工探测结果的干净状态下跑，此时只用差分验证那批
    probe = []
    print("提示：没有 .probe/url_templates.json，跳过探测阶段结果，"
          "仅使用 tools/verify_get_templates.py 的差分验证结果")
catalog = json.loads((base / "zhuiju" / "data" / "catalog.json").read_text(encoding="utf-8"))


def norm_url(u: str) -> str:
    p = urlparse(u)
    return f"{p.scheme}://{p.netloc}".lower()


def name_key(s: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (s or "").lower())


# 目录项按 host 建索引，便于把探测结果对应回 catalog id
by_host = {}
for it in catalog["items"]:
    by_host[norm_url(it["url"])] = it["id"]

api_by_host = {}
for row in probe:
    if row.get("group") != "api_host":
        continue
    api_by_host[norm_url(row["site"])] = row

verified, rejected = {}, []
for row in probe:
    tpl = row.get("template")
    if not row.get("ok") or not tpl or "{kw}" not in tpl:
        rejected.append((row["name"], tpl or "(none)"))
        continue
    test = tpl.replace("{kw}", quote(KW2))
    try:
        r = requests.get(test, headers=HDRS, timeout=14, verify=False, allow_redirects=True)
        body = r.text or ""
    except Exception as exc:  # noqa: BLE001
        rejected.append((row["name"], f"{type(exc).__name__}"))
        continue
    ok = (r.status_code == 200 and len(body) > 1500
          and (quote(KW2) in r.url or KW2 in r.url)
          and norm_url(r.url) == norm_url(test))
    if not ok:
        rejected.append((row["name"], f"复核未通过 status={r.status_code} len={len(body)} final={r.url[:70]}"))
        continue
    host = norm_url(row["site"])
    key = by_host.get(host) or row["site"]
    verified[key] = tpl
    if row.get("group") == "api_host":
        verified[f"api:{host}"] = tpl

out = base / "zhuiju" / "data" / "templates.json"

# 并入 tools/verify_get_templates.py 的双关键词差分验证结果（判据更严，可信度更高）
verify_path = base / ".probe" / "template_verify.json"
extra = 0
if verify_path.exists():
    by_name = {it["name"]: it["id"] for it in catalog["items"]}
    for row in json.loads(verify_path.read_text(encoding="utf-8")):
        if not row.get("ok") or "{kw}" not in (row.get("template") or ""):
            continue
        host = norm_url(row["site"])
        key = by_host.get(host) or by_name.get(row["name"])
        if key is None:
            key = row["site"]
        if key not in verified:
            verified[key] = row["template"]
            extra += 1
    print(f"差分验证补入 {extra} 个模板")

out.write_text(json.dumps({"verified_with": KW2, "templates": verified},
                          ensure_ascii=False, indent=2), encoding="utf-8")
print(f"verified={len([k for k in verified if not k.startswith('api:')])} "
      f"rejected={len(rejected)}")
with open(base / ".probe" / "templates_final.txt", "w", encoding="utf-8") as f:
    f.write("=== VERIFIED ===\n")
    for k, v in verified.items():
        f.write(f"{k}\n    {v}\n")
    f.write("\n=== REJECTED / NO TEMPLATE ===\n")
    for n, t in rejected:
        f.write(f"{n}: {t}\n")
