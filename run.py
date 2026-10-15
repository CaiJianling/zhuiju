# -*- coding: utf-8 -*-
"""一键启动：起服务并自动打开浏览器。

    python run.py                  默认 127.0.0.1:5000
    python run.py --port 8000      换端口
    python run.py --host 0.0.0.0   允许局域网访问（配合 nginx / 防火墙自行判断）

数据自动更新改为"访问网站时触发"（见 zhuiju/autoupdate.py），这里不再处理。
"""
import argparse
import os
import socket
import threading
import time
import webbrowser
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")

BASE = Path(__file__).resolve().parent
DEFAULT_PORT = int(os.environ.get("ZHUIJU_PORT", "5000"))
DEFAULT_HOST = os.environ.get("ZHUIJU_HOST", "127.0.0.1")


def port_in_use(host: str, port: int) -> bool:
    """先探一次端口：端口被占时 Flask 的报错很难懂，而这台机器上旧进程残留过。"""
    probe = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex((probe, port)) == 0


def _open(url: str, host: str, port: int):
    if os.environ.get("ZHUIJU_NO_BROWSER") == "1":
        return
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    for _ in range(40):
        try:
            with socket.create_connection((shown, port), timeout=0.3):
                break
        except OSError:
            time.sleep(0.25)
    webbrowser.open(url)


def main() -> int:
    ap = argparse.ArgumentParser(description="追剧资源搜索 本地站点")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"监听端口，默认 {DEFAULT_PORT}（也可用环境变量 ZHUIJU_PORT）")
    ap.add_argument("--host", default=DEFAULT_HOST,
                    help="监听地址，默认 127.0.0.1；填 0.0.0.0 允许局域网访问")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()

    if port_in_use(args.host, args.port):
        print(f"端口 {args.port} 已被占用。")
        print("  换个端口：  python run.py --port 8000")
        print("  或先结束占用进程：  python tools/restart.py --port "
              f"{args.port}   （它会先杀干净再起）")
        return 1

    host_shown = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    url = f"http://{host_shown}:{args.port}/"
    os.environ["ZHUIJU_PORT"] = str(args.port)
    if args.no_browser:
        os.environ["ZHUIJU_NO_BROWSER"] = "1"

    from zhuiju.app import app
    from zhuiju import admin as admin_mod

    (BASE / "logs").mkdir(exist_ok=True)
    (BASE / "logs" / "server.pid").write_text(str(os.getpid()), encoding="utf-8")

    cfg = admin_mod.load()
    print(f"追剧资源搜索已启动： {url}   （Ctrl+C 退出）")
    if args.host not in ("127.0.0.1", "localhost"):
        print(f"  监听在 {args.host}，局域网内其它设备可访问，请确认这是你想要的")
    print(f"  后台统计： {url}admin")
    if cfg.get("_generated"):
        # 口令是第一次启动时随机生成的，只在生成这一次打印（和 Flask 的调试 PIN 一个道理）
        print(f"    已在 {admin_mod.CONFIG} 生成口令文件，本次口令： {cfg['password']}")
        print("    用这个口令登录后会直接让你改成自己定的，改完立刻生效、不用重启")
    else:
        print(f"    口令在 {admin_mod.CONFIG} 的 password 字段；"
              "登录后也可以点页面右上角的「改口令」直接改，保存即生效")
    threading.Thread(target=_open, args=(url, args.host, args.port), daemon=True).start()
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
