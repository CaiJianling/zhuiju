# -*- coding: utf-8 -*-
"""首页的真人滑块验证：一次性挑战 → 通过后签发匿名 cookie → 门禁与爬虫豁免都看这一枚。

先把"它挡得住什么、挡不住什么"写在脸上，否则容易被当成"上了验证码就安全了"：

  挡得住 —— 直接 GET 页面/接口的脚本、无差别抓站的爬虫、把本站当免费搜索 API 刷的人。
            它们要么拿不到 cookie，要么得先实现一整套流程：取挑战 → 按服务端给的缺口位置
            拖进容差 → 带上耗时与轨迹采样提交，而且提交一次就作废。
  挡不住 —— 铁了心的人。挑战与校验都在这台机器上，脚本读一眼 slider.js 就能照着发；
            服务端能确认的只有"这枚 cookie 是不是我签的、有没有过期"。

所以真正的收益是两条，都不是"绝对安全"：一是把无成本滥用变成有成本滥用（配合按 IP 的限流
足够劝退绝大多数），二是**后台第一次有了"这是真人"的硬凭据** —— 以前分真人和脚本全靠猜 UA
（见 docs/admin.md），现在 `queries.verified=1` 那几条是当场拖过滑块的，可以拿它反过来校准判读。

cookie 里只有一个带到期时间的 HMAC 签名，不含任何身份信息、不落盘、不进统计库
（统计库只多记一个 0/1/NULL 的 verified 列）。搜索引擎爬虫走豁免：UA 命中已知爬虫名，
**并且**反查 DNS 落在它的官方域名上 —— 光看 UA 等于什么都没有，任何脚本都能自称 Googlebot。
"""
from __future__ import annotations

import hmac
import ipaddress
import secrets
import socket
import hashlib
import threading
import time

from . import admin as admin_mod
from . import settings as settings_mod

COOKIE = "zhuiju_human"
# 签名前缀：将来要换算法或换口径时，老 cookie 会直接判无效而不是"看起来像但意思变了"
_SALT = b"zhuiju-human-v1"

# 挑战：两分钟内不作废就过期（拖太久说明人不在），缺口位置随机但不贴边——
# 贴到最左/最右的话"拖着不动"也能过，那就不是滑动验证了
CHALLENGE_TTL = 120
TARGET_MIN, TARGET_MAX = 0.12, 0.88
# 容差：缺口宽度的 ±4.5%（轨道全长的比例），手指粗一点也够，纯随机点不到
TOL = 0.045
# 从按下到松手的最短时间：真人拖动再快也不会低于这个数。留 200ms 而不是 320ms——
# 手快的人"啪"一下拖过去是真实存在的，把门槛抬太高就变成了"谁都用不了"（实测过 320 太紧）。
# 这条只是**多一条依据**，主判据是采样点数：一次真拖拽中间有几十次 move
MIN_MS = 200
# 指针轨迹至少要采到的点数：一次真实的拖拽中间会有几十个 move 事件
MIN_SAMPLES = 8
# 键盘那条路（无障碍必须留）没有轨迹点，改用按键次数当"确实动过"的证据
MIN_KEYSTROKES = 6

_ch_lock = threading.Lock()
_ch: dict = {}           # id -> {"target", "exp", "ip"}
_CH_MAX = 3000           # 极端情况下被人刷接口：内存里的挑战数要有顶

# 提交失败限流：同一个来源 10 分钟内最多错 10 次。口令限流在 admin.py 里是同一套写法
_solve_fails = admin_mod.Throttle(max_fails=10, window=600)

_rdns_lock = threading.Lock()
_rdns_cache: dict = {}   # ip -> (算的时刻, 主机名)  反查一次几十毫秒，只对"自称爬虫"的请求做
RDNS_TTL = 600


# ------------------------------------------------------------------ 门禁开关与有效期
def enabled() -> bool:
    return settings_mod.human_gate()


def max_age() -> int:
    return settings_mod.human_hours() * 3600


# ------------------------------------------------------------------ cookie：绑设备的到期签名
def _sign(exp: int, fp: str) -> str:
    return hmac.new(admin_mod.secret_key().encode("utf-8"),
                    _SALT + f"{exp}.{fp}".encode(), hashlib.sha256).hexdigest()[:32]


def fingerprint(ip: str, ua: str | None) -> str:
    """设备指纹 = 来源地址 + UA 的"家族"（系统 + 设备类型），**不含版本号**。

    不含版本号是有意的：浏览器自动升级一次就把全科室踢下线重新拖滑块，是给自己找麻烦；
    而"把 cookie 拷到另一台电脑"要骗过这条，得同时凑齐同一个来源地址和同一套系统/设备类型。
    """
    from . import agent
    a = agent.parse_ua(ua or "")
    return hashlib.sha256(f"{ip}|{a.get('os')}|{a.get('device')}".encode()).hexdigest()[:16]


def issue(ip: str, ua: str | None, now: float | None = None) -> str:
    """签发一枚："<到期 unix 秒>.<设备指纹>.<签名>"。不存表，重启后老 cookie 照样能验
    （密钥在配置文件里）。"""
    now = now if now is not None else time.time()
    exp = int(now) + max_age()
    fp = fingerprint(ip, ua)
    return f"{exp}.{fp}.{_sign(exp, fp)}"


def token_ok(value: str | None, ip: str, ua: str | None, now: float | None = None) -> bool:
    """只回答"这枚是不是我签给**这台设备**的、还没过期"。三样都要：

    签名（没被改过）、到期时间（没过期）、**指纹**（来源地址与系统/设备类型对得上）。
    所以把 cookie 拷到别的电脑上用不了；同一台机器上换个浏览器（系统/设备类型变了）也会要重验。
    """
    if not value:
        return False
    now = now if now is not None else time.time()
    parts = value.split(".")
    if len(parts) != 3:
        return False
    head, fp, sig = parts
    try:
        exp = int(head)
    except ValueError:
        return False
    if exp <= now:
        return False
    if not hmac.compare_digest(sig, _sign(exp, fp)):
        return False
    return hmac.compare_digest(fp, fingerprint(ip, ua))


# ------------------------------------------------------------------ 一次性挑战
def _gc(now: float) -> None:
    """清掉过期与超量的挑战。调用方已持锁。"""
    for cid in [k for k, v in _ch.items() if v["exp"] < now]:
        _ch.pop(cid, None)
    if len(_ch) > _CH_MAX:          # 还是被人灌爆了：丢最早过期的那批
        for cid, _v in sorted(_ch.items(), key=lambda kv: kv[1]["exp"])[:len(_ch) - _CH_MAX]:
            _ch.pop(cid, None)


def new_challenge(ip: str) -> dict:
    now = time.time()
    with _ch_lock:
        _gc(now)
        cid = secrets.token_urlsafe(12)
        _ch[cid] = {"target": round(secrets.randbelow(int((TARGET_MAX - TARGET_MIN) * 1000)) / 1000
                                    + TARGET_MIN, 3),
                    "exp": now + CHALLENGE_TTL, "ip": ip}
        return {"id": cid, "target": _ch[cid]["target"], "ttl": CHALLENGE_TTL,
                "tol": TOL}


def solve(ip: str, cid: str, pct, ms, samples, keys=0) -> tuple[bool, str | None]:
    """校验一次提交。**单次使用**：不管过没过，这条挑战都用掉了。

    所有客户端给的数（位置/耗时/采样数）在原理上都能伪造，这里要它们不是"防住脚本"，
    而是"让随手写脚本的人必须模拟出一个像样的拖拽"。真正兜底的是按 IP 的失败限流与
    挑战单次使用 —— 拿不到有效 cookie 就只能反复取新挑战，而那是会被限流掐住的。
    """
    who = ip                                   # 已经由调用方按反代规则取过真实来源
    wait = _solve_fails.blocked(who)
    if wait:
        return False, f"失败次数过多，请 {wait} 秒后再试"
    now = time.time()
    with _ch_lock:
        c = _ch.pop(cid or "", None)          # 拿到就摘走：不存在/已被用过都是 None
    if not c:
        _solve_fails.fail(who)
        return False, "这条验证已经过期或被用过了，请重新拖一次"
    if c["ip"] != ip:
        _solve_fails.fail(who)
        return False, "这条验证不是发给你的，请重新拖一次"
    if c["exp"] < now:
        _solve_fails.fail(who)
        return False, "拖得太久了（超过 2 分钟），请重新拖一次"
    try:
        got = float(pct)
        spent = float(ms)
        moved = int(samples)
    except (TypeError, ValueError):
        _solve_fails.fail(who)
        return False, "提交的内容不完整"
    keyboard = moved < MIN_SAMPLES and int(keys or 0) >= MIN_KEYSTROKES
    if abs(got - c["target"]) > TOL:
        _solve_fails.fail(who)
        return False, "没拖到缺口上"
    if spent < MIN_MS:
        _solve_fails.fail(who)
        return False, "这一下太快了，不像手拖的"
    if not (moved >= MIN_SAMPLES or keyboard):
        _solve_fails.fail(who)
        return False, "没看出拖动过程（用鼠标拖，或者点一下滑块后用左右方向键）"
    _solve_fails.reset(who)
    return True, None


# ------------------------------------------------------------------ 搜索引擎爬虫豁免
# UA 里出现左边这个词才可能算爬虫，右边是它做反查 DNS 时该落到的官方域名后缀。
# 名单只放**搜索引擎**：其它 bot（Ahrefs/Semrush 之类采集站 SEO 的）没有豁免资格。
CRAWLERS = {
    "googlebot": (".googlebot.com", ".googleusercontent.com"),
    "bingbot": (".search.msn.com",),
    "baiduspider": (".baidu.com", ".baidu.jp"),
    "sogou web spider": (".sogou.com",),
    "360spider": (".qihoo.com", ".so.com", ".360spider.com"),
    "yandexbot": (".yandex.ru", ".yandex.net", ".yandex.org"),
    "bytespider": (".bytedance.com", ".bytedance.org"),
    "duckduckbot": (".duckduckgo.com",),
}


def _lookup(ip: str) -> str:
    """反查主机名。抽成函数是为了测试能注入（离线测试拿不到真实 DNS）。"""
    try:
        return (socket.gethostbyaddr(ip)[0] or "").lower()
    except (OSError, ValueError):
        return ""


def _rdns(ip: str) -> str:
    now = time.time()
    with _rdns_lock:
        hit = _rdns_cache.get(ip)
        if hit and now - hit[0] < RDNS_TTL:
            return hit[1]
        host = _lookup(ip)
        _rdns_cache[ip] = (now, host)
        return host


def is_search_crawler(ip: str, ua: str | None) -> bool:
    """自称爬虫 + 反查 DNS 落在官方域名，两条都要。

    只看 UA 等于不设防：`curl -A "Googlebot"` 就进去了。
    内网/回环一律不豁免 —— 真正的搜索引擎不会从你科室的局域网里出来，
    而这条判据顺手挡住了"本机跑个脚本挂个爬虫 UA 就绕过门禁"（测试里最容易踩的那个坑）。
    """
    if not ua:
        return False
    low = ua.lower()
    key = next((k for k in CRAWLERS if k in low), None)
    if not key:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if not addr.is_global:
        return False
    host = _rdns(ip)
    return bool(host) and any(host.endswith(suf) for suf in CRAWLERS[key])
