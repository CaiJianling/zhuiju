# -*- coding: utf-8 -*-
"""确定性地重启本地站点：先杀掉监听端口的旧进程，再起新的，最后验证路由已注册。

改完代码后用它，比手动关窗口可靠：旧进程占着端口时，新起的 Flask 会静默绑定失败，
页面看起来正常但跑的还是没有新路由的旧代码。全程只用 Python，不解析任何命令输出。

    python tools/restart.py
    python tools/restart.py --port 8000

Windows 走 WinAPI（kernel32 + iphlpapi 的 TCP 表），Linux 走 /proc：
读 /proc/net/tcp* 找 LISTEN 的 socket inode，再在 /proc/<pid>/fd 里反查归属。
非 root 时看不到别人的 fd，这时候只能按 logs/server.pid 收尾，会明确说出来。
"""
from __future__ import annotations

import argparse
import ctypes
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
WIN = os.name == "nt"


def pid_alive(pid: int) -> bool:
    if not WIN:
        try:
            os.kill(pid, 0)             # 只是探活，不发信号
        except ProcessLookupError:
            return False
        except PermissionError:
            return True                 # 进程在，只是不属于我
        except OSError:
            return False
        return True
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
    if not WIN:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                return                  # 已经没了 / 不是我的进程
            if sig == signal.SIGTERM:
                for _ in range(12):     # 给 Flask 一点收尾时间，别留半死的监听
                    time.sleep(0.25)
                    if not pid_alive(pid):
                        return
        return
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x0001, False, pid)
    if h:
        k32.TerminateProcess(h, 1)
        k32.CloseHandle(h)


def _proc_listen_pids(port: int, proc: Path | None = None, readlink=None) -> list[int]:
    """Linux：从 /proc 找监听该端口的 PID。找不到就返回空表，不猜。

    /proc/net/tcp 的表头把 tx_queue rx_queue、tr tm->when 各写成两个名字，数据行里它们
    却各自合成一个字段，所以列号不能照着表头数。内核 seq_printf 的实际顺序是：
    sl, local, remote, st, tx:rx, tr:when, retrnsmt, uid, timeout, inode ——
    inode 在 **f[9]**，st 在 f[3]，端口是 f[1] 冒号后面那段 16 进制。
    照着表头数会取到 f[8]（那是 timeout），端口永远匹配不上：旧进程杀不掉、
    页面看着"起来了"其实跑的还是旧代码。
    st=0A 才是 LISTEN。inode 只是号码，还得去 /proc/<pid>/fd 里找 socket:[inode] 反查归属，
    非 root 时看别人的 fd 会 EACCES，只能跳过（那种情况按 logs/server.pid 收尾）。

    proc / readlink 可以注入：真实 /proc 与 socket 软链接都只在 Linux 有，
    在 Windows 上没法造出来，不注入就没法验证这套解析。
    """
    readlink = readlink or os.readlink
    proc = proc or Path("/proc")
    inodes = set()
    for name in ("net/tcp", "net/tcp6"):
        try:
            lines = (proc / name).read_text().splitlines()[1:]
        except (OSError, UnicodeDecodeError):
            continue
        for ln in lines:
            f = ln.split()
            if len(f) < 10 or f[3] != "0A":
                continue
            try:
                if int(f[1].split(":")[1], 16) != port:
                    continue
            except (ValueError, IndexError):
                continue
            inodes.add(f[9])
    if not inodes:
        return []
    pids = []
    try:
        entries = list(proc.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            links = list((entry / "fd").iterdir())
        except OSError:
            continue                        # 权限不够 / 进程已退出
        for link in links:
            try:
                tgt = readlink(str(link))         # 不是 os.readlink：注入点要真被用上
            except OSError:
                continue
            if tgt.startswith("socket:[") and tgt[8:-1] in inodes:
                pids.append(int(entry.name))
                break
    return sorted(set(pids))



def listener_pids(port: int) -> list[int]:
    """用 iphlpapi 的 TCP 表找到监听该端口的 PID（Linux 走 /proc，见 _proc_listen_pids）。

    MIB_TCPROW_OWNER_PID 的字段顺序是 state, localAddr, localPort, remoteAddr,
    remotePort, owningPid —— 端口在第 3 个 DWORD（不是第 2 个，那是本地地址），
    且按网络字节序存放。取错列会永远匹配不上，导致旧进程杀不掉、
    页面看着"起来了"其实跑的还是旧代码。
    """
    if not WIN:
        return _proc_listen_pids(port)
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
    kw = {"creationflags": 0x00000008 | 0x00000200} if WIN else {"start_new_session": True}
    with open(BASE / "logs" / "server.out", "a", encoding="utf-8") as fh:
        fh.write(f"\n=== 重启 {time.strftime('%Y-%m-%d %H:%M:%S')} port={port} ===\n")
        # 用"跑这个脚本的解释器"起站点，宝塔那类 venv 建在站点外面的部署才不会被
        # 起成系统 python（那样起来也没依赖，页面直接 500）
        subprocess.Popen([sys.executable, "-u", str(BASE / "run.py")], cwd=str(BASE),
                         stdout=fh, stderr=fh,
                         env={**os.environ, "ZHUIJU_PORT": str(port), "PYTHONUTF8": "1"},
                         **kw)

    # 就绪判据用"只有当前这版代码才有"的特征，否则旧进程应答也会被判成起来了
    probe = root + "/api/catalog?kw=&link_kw=zz"

    def ready() -> bool:
        """423 也算"起来了"。

        真人门禁开着时，这个脚本客户端没有 cookie，任何路由都会先被挡成 423 ——
        但那恰恰证明进程活着、而且是这版代码在应答（旧进程没有 /api/catalog 的 link_kw
        特征，只会给 404）。不这么写的话，一上门禁 restart.py 就永远报"60 秒内没应答"，
        而站点其实好好的（实测踩过：日志里 423 一条接一条，重启脚本却判定失败）。
        """
        try:
            with urllib.request.urlopen(probe, timeout=4) as r:
                return r.status == 200 and b'"link_kw"' in r.read()
        except urllib.error.HTTPError as exc:
            return exc.code == 423
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
