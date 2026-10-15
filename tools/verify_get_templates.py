# -*- coding: utf-8 -*-
"""用双关键词差分法严格验证各站搜索模板。

只看"页面里出现了关键词"是不够的：很多站首页本身就写着热门剧名。
真正的搜索结果页应当在换用无意义关键词时明显不同（更小 / 有"无结果"文案），
所以这里同时请求真实词与乱码词，比较两者差异才判定模板有效。
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

REAL = "庆余年"
# 不可能有结果的串；用纯 ASCII 避免中文被站点二次编码干扰
FAKE = "zzqxvqjgkurt"

NO_RESULT = re.compile(r"(没有找到|未找到|无相关|暂无结果|没有搜索|0 条|结果为空|"
                       r"no result|not found|0 个相关)", re.I)

base = Path(__file__).resolve().parent.parent
(base / ".probe").mkdir(exist_ok=True)

# 候选模板：name, 站点URL, 模板（{kw} 占位）
CANDIDATES = [
    ("PanSou", "https://pansou.de", "https://pansou.de/?s={kw}"),
    ("PanSou", "https://pansou.de", "https://pansou.de/search/{kw}"),
    ("夸克搜", "https://kkso.net", "https://kkso.net/?s={kw}"),
    ("夸克搜", "https://kkso.net", "https://kkso.net/search/{kw}.html"),
    ("追剧吧", "https://www.zhuiju.us/", "https://www.zhuiju.us/?s={kw}"),
    ("追剧吧", "https://www.zhuiju.us/", "https://www.zhuiju.us/search/{kw}"),
    ("谷哥搜", "https://gugeso.com/", "https://gugeso.com/?s={kw}"),
    ("谷哥搜", "https://gugeso.com/", "https://gugeso.com/?keyword={kw}"),
    ("谷哥搜", "https://gugeso.com/", "https://gugeso.com/search/{kw}"),
    ("磁力熊", "https://www.cilixiong.org", "https://www.cilixiong.org/?keyboard={kw}"),
    ("磁力熊", "https://www.cilixiong.org", "https://www.cilixiong.org/so.php?keyboard={kw}"),
    ("磁力狗", "https://ciligou.net", "https://ciligou.net/?q={kw}"),
    ("磁力狗", "https://ciligou.net", "https://ciligou.net/search/{kw}"),
    ("SeedHub", "https://sidhub.cc/", "https://sidhub.cc/?s={kw}"),
    ("SeedHub", "https://sidhub.cc/", "https://sidhub.cc/search/{kw}"),
    ("高清MP4", "https://www.mp4ba.vip", "https://www.mp4ba.vip/?s={kw}"),
    ("高清族", "https://hdzu.org", "https://hdzu.org/?wd={kw}"),
    ("高清族", "https://hdzu.org", "https://hdzu.org/?act=search&wd={kw}"),
    ("POMO", "https://pomo.mom/", "https://pomo.mom/?keyword={kw}"),
    ("BD影视聚合", "https://www.juhebd.com/", "https://www.juhebd.com/?searchword={kw}"),
    ("字幕库", "https://zimuku.org", "https://zimuku.org/search?keyword={kw}"),
    ("SubHD", "https://subhd.tv", "https://subhd.tv/search/{kw}"),
    ("射手网伪", "https://assrt.net", "https://assrt.net/sub/?searchword={kw}"),
    ("洛雪TV", "https://tv.lxyy.club/", "https://tv.lxyy.club/index.php/vod/search/wd/{kw}.html"),
    ("创享影视", "https://ys.cxkjg.cn/", "https://ys.cxkjg.cn/index.php/vod/search/wd/{kw}.html"),
    ("西瓜影视", "https://www.kanmovie.com/", "https://www.kanmovie.com/search/-------------.html?wd={kw}"),
    ("简云影视", "https://jianyunys.com/", "https://jianyunys.com/search?wd={kw}"),
    ("66大片网", "https://www.77dpw.vip/", "https://www.77dpw.vip/search?wd={kw}"),
    ("电影人生", "https://dyrs.tv", "https://dyrs.tv/search?wd={kw}"),
    ("PPnix", "https://www.ppnix.com/cn/", "https://www.ppnix.com/cn/search?wd={kw}"),
    ("爱盼", "https://www.aipan.me/", "https://www.aipan.me/search?wd={kw}"),
    ("布布追剧", "https://bubuzhuiju.com", "https://bubuzhuiju.com/search?wd={kw}"),
]


def fetch(url):
    try:
        r = requests.get(url, headers=HDRS, timeout=14, verify=False, allow_redirects=True)
        return r.status_code, r.url, r.text or ""
    except Exception as exc:  # noqa: BLE001
        return None, None, f"ERR:{type(exc).__name__}"


def verdict(tpl):
    url_real = tpl.replace("{kw}", quote(REAL))
    url_fake = tpl.replace("{kw}", quote(FAKE))
    s1, f1, b1 = fetch(url_real)
    s2, f2, b2 = fetch(url_fake)
    if s1 != 200 or s2 != 200:
        return False, f"status {s1}/{s2}"
    # 必须停在原站、URL 里带得上关键词
    host = urlparse(tpl).netloc.lower()
    if urlparse(f1).netloc.lower() != host or urlparse(f2).netloc.lower() != host:
        return False, f"跳转到别的域 {f1[:60]}"
    if quote(REAL) not in f1 and REAL not in f1:
        return False, "最终 URL 未保留关键词（多半是 POST 表单，GET 不生效）"
    sh, _, home = fetch(f"https://{host}/")
    home_len = len(home) if sh == 200 else 0

    fake_empty = bool(NO_RESULT.search(b2))
    # "无结果"文案常常本身就在页面模板里，不能单独作为依据：
    # 真结果页还必须明显不同于该站首页，否则就是在看首页。
    differs_from_home = home_len == 0 or abs(len(b1) - home_len) > home_len * 0.2
    grew = len(b1) > len(b2) * 1.1 or len(b1) - len(b2) > 3000
    if not differs_from_home:
        return False, f"结果页与首页大小一致({len(b1)}≈{home_len})，模板其实没生效"
    if not (fake_empty or grew):
        return False, f"两词结果页几乎一样 ({len(b1)} vs {len(b2)})，疑似模板无效"
    if len(b1) < 1500:
        return False, f"结果页太小 {len(b1)}"
    return True, f"len {len(b1)}/{len(b2)} 首页={home_len} fake无结果={fake_empty}"


results = []
for name, site, tpl in CANDIDATES:
    ok, why = verdict(tpl)
    results.append({"name": name, "site": site, "template": tpl, "ok": ok, "why": why})
    print(f"{'OK  ' if ok else '-- '}{name:<8} {why}")

out = base / ".probe" / "template_verify.json"
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n通过 {sum(1 for r in results if r['ok'])}/{len(results)}")
