# -*- coding: utf-8 -*-
"""后台统计页的口令与登录。

配置文件 zhuiju/data/admin.json（已 gitignore，含明文口令，不进版本库）：

    {"password": "你自己改的口令", "secret_key": "随机串，用来签登录 cookie"}

文件不存在时自动创建，口令随机生成并打印在服务控制台；想换成自己知道的口令，
直接改 password 字段再重启服务即可（也支持环境变量 ZHUIJU_ADMIN_PASSWORD 覆盖，
方便部署时不落地明文）。

为什么明文存文件：用户要能自己改（这是需求），而这个工具本来就只在自己机器上跑。
配套的缓解措施是登录失败限流 + 只在回环/局域网监听。真要公网暴露，
应当放到 nginx 后面再加一层 TLS，README 里写了这点。
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import string
import threading
import time
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
CONFIG = DATA / "admin.json"

SESSION_KEY = "admin_login_at"       # session 里存的标记
SESSION_TTL = 8 * 3600               # 登录后 8 小时内免口令

# 失败限流：15 分钟内同一个来源最多错 8 次。本地工具也值得防一下"挂着端口被人猜"
MAX_FAILS = 8
WINDOW = 15 * 60

_ALPHABET = (string.ascii_lowercase + string.digits).replace("l", "").replace("o", "")


def _gen_password(n: int = 12) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def load(create: bool = True) -> dict:
    """读配置；缺失就补一个可用的（随机口令 + 随机密钥）并落盘。"""
    cfg = {}
    if CONFIG.exists():
        try:
            cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cfg = {}
    changed = False
    if not isinstance(cfg, dict):
        cfg = {}
    if not cfg.get("secret_key"):
        cfg["secret_key"] = secrets.token_hex(32)
        changed = True
    if not str(cfg.get("password") or "").strip():
        cfg["password"] = _gen_password()
        cfg["_generated"] = True
        changed = True
    if create and changed:
        save(cfg)
    return cfg


def save(cfg: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    out = {k: v for k, v in cfg.items() if not k.startswith("_")}
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CONFIG)
    try:
        os.chmod(CONFIG, 0o600)       # 只有当前用户可读，别的账号看不到口令
    except OSError:
        pass


def password_expected() -> str:
    env = os.environ.get("ZHUIJU_ADMIN_PASSWORD")
    if env:
        return env
    return str(load().get("password") or "")


def password_ok(got: str) -> bool:
    """定长比较，避免按耗时猜口令。"""
    want = password_expected()
    if not want or not got:
        return False
    return hmac.compare_digest(want, got[:200])


def secret_key() -> str:
    env = os.environ.get("ZHUIJU_SECRET_KEY")
    if env:
        return env
    return str(load().get("secret_key") or "")


class Throttle:
    """按来源记失败次数。纯内存：重启后清零，够用。"""

    def __init__(self, max_fails: int = MAX_FAILS, window: int = WINDOW):
        self.max_fails = max_fails
        self.window = window
        self._hits: dict[str, list[float]] = {}
        self._guard = threading.Lock()

    def blocked(self, who: str) -> int:
        """还能不能试；返回需要等待的秒数，0 表示可以。"""
        now = time.time()
        with self._guard:
            ts = [t for t in self._hits.get(who, []) if now - t < self.window]
            self._hits[who] = ts
            if len(ts) < self.max_fails:
                return 0
            return int(self.window - (now - ts[0])) or 1

    def fail(self, who: str) -> int:
        now = time.time()
        with self._guard:
            ts = [t for t in self._hits.get(who, []) if now - t < self.window]
            ts.append(now)
            self._hits[who] = ts
            return self.max_fails - len(ts)

    def reset(self, who: str) -> None:
        with self._guard:
            self._hits.pop(who, None)

    def pending(self) -> int:
        with self._guard:
            return sum(1 for v in self._hits.values() if v)


throttle = Throttle()


def client_ip(environ: dict) -> str:
    """取真实客户端 IP，信任规则和 app 里的 TrustForwarded 保持一致。

    只有当直接连过来的那一跳是回环地址（也就是本机 nginx 反代）时，
    才认 X-Forwarded-For 的最左边一项；否则任何人都能伪造这个头，
    把统计里的 IP 写成任意值。
    """
    from .stats import clean_ip

    remote = clean_ip(environ.get("REMOTE_ADDR"))
    forwarded = str(environ.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    if remote in ("127.0.0.1", "::1") and forwarded:
        return clean_ip(forwarded) or remote
    return remote or "unknown"
