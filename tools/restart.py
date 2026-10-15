# -*- coding: utf-8 -*-
"""确定性地重启本地站点：先杀掉监听端口的旧进程，再起新的，最后验证路由已注册。

改完代码后用它，比手动关窗口可靠：旧进程占着端口时，新起的 Flask 会静默绑定失败，
页面看起来正常但跑的还是没有新路由的旧代码。全程只用 Python（WinAPI），不解析命令输出。

    python tools/restart.py
    python tools/restart.py --port 8000
"""
from __future__ import annotations

import argparse
import ctypes
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def pid_alive(pid: int) -> bool:
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        return bool(ok) and code.value == 259
    finally:
        k32.CloseHandle(h)


def kill_pid(pid: int) -> None:
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x0001, False, pid)
    if h:
        k32.TerminateProcess(h, 1)
        k32.CloseHandle(h)


def listener_pids(port: int) -> list[int]:
    """用 iphlpapi 的 TCP 表找到监听该端口的 PID。

    MIB_TCPROW_OWNER_PID 的字段顺序是 state, localAddr, localPort, remoteAddr,
    remotePort, owningPid —— 端口在第 3 个 DWORD（不是第 2 个，那是本地地址），
    且按网络字节序存放。取错列会永远匹配不上，导致旧进程杀不掉、
    页面看着"起来了"其实跑的还是旧代码。
    """
    if os.name != "nt":
        return []
    AF_INET, OWNER_PID_LISTENER = 2, 3
    g = ctypes.windll.iphlpapi
    size = ctypes.c_ulong(0)
    g.GetExtendedTcpTable(None, ctypes.byref(size), False, AF_INET, OWNER_PID_LISTENER, 0)
    if not size.value:
        return []
    buf = ctypes.create_string_buffer(size.value)
    if g.GetExtendedTcpTable(buf, ctypes.byref(size), False, AF_INET, OWNER_PID_LISTENER, 0) != 0:
        return []
    n = ctypes.c_ulong.from_buffer_copy(buf, 0).value
    pids = []
    for i in range(n):
        row = (ctypes.c_ulong * 6).from_buffer_copy(buf, 4 + i * 24)
        _state, _laddr, lport_raw, _raddr, _rport, owner = (int(x) for x in row)
        candidates = {socket.ntohs(lport_raw & 0xFFFF), (lport_raw >> 16) & 0xFFFF,
                      lport_raw & 0xFFFF}
        if port in candidates:
            pids.append(owner)
    return sorted(set(p for p in pids if p))


def http_status(url: str, timeout: float = 3.0) -> int:
    """返回 HTTP 状态码；连不上返回 0。

    注意 urlopen 对 4xx/5xx 是抛 HTTPError 而不是返回状态码，
    不接住它的话 400 会被当成"连不上"，就绪判断永远失败。
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001
        return 0


def kill_listeners(port: int, self_pid: int) -> int:
    """循环杀到端口空为止；一次杀不干净会留下旧进程继续应答，让人误判成新代码。"""
    killed = 0
    for _ in range(6):
        pids = [p for p in listener_pids(port) if p != self_pid]
        if not pids:
            break
        for pid in pids:
            if pid_alive(pid):
                kill_pid(pid)
                killed += 1
                print(f"已结束监听 PID={pid}")
        time.sleep(1.2)
    return killed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=os.environ.get("ZHUIJU_PORT", "5000"))
    args = ap.parse_args()
    port = int(args.port)
    root = f"http://127.0.0.1:{port}"

    targets = set(listener_pids(port))
    pidfile = BASE / "logs" / "server.pid"
    if pidfile.exists():
        try:
            targets.add(int(pidfile.read_text().strip()))
        except ValueError:
            pass
    for pid in sorted(targets):
        if pid and pid != os.getpid() and pid_alive(pid):
            kill_pid(pid)
            print(f"已结束旧进程 PID={pid}")
    kill_listeners(port, os.getpid())
    time.sleep(1)
    if listener_pids(port):
        print(f"端口 {port} 仍被占用：{listener_pids(port)}，请先手动结束")
        return 1

    (BASE / "logs").mkdir(exist_ok=True)
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0
    with open(BASE / "logs" / "server.out", "a", encoding="utf-8") as fh:
        fh.write(f"\n=== 重启 {time.strftime('%Y-%m-%d %H:%M:%S')} port={port} ===\n")
        subprocess.Popen([sys.executable, "-u", str(BASE / "run.py")], cwd=str(BASE),
                         stdout=fh, stderr=fh, creationflags=flags,
                         env={**os.environ, "ZHUIJU_PORT": str(port), "PYTHONUTF8": "1"})

    # 就绪判据用"只有当前这版代码才有"的特征，否则旧进程应答也会被判成起来了
    probe = root + "/api/catalog?kw=&link_kw=zz"

    def ready() -> bool:
        try:
            with urllib.request.urlopen(probe, timeout=4) as r:
                return b'"link_kw"' in r.read()
        except Exception:  # noqa: BLE001
            return False

    for _ in range(45):
        time.sleep(1)
        if ready() and http_status(root + "/") == 200:
            print(f"站点已就绪（新代码）： {root}/   PID="
                  f"{pidfile.read_text().strip() if pidfile.exists() else '?'}")
            return 0
    print(f"60 秒内 {probe} 没有以新代码应答；请看 logs/server.out")
    return 1


if __name__ == "__main__":
    sys.exit(main())
