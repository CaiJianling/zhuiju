#!/bin/sh
# 手动跑一次每日更新（Linux / macOS 这一侧的 refresh.bat）
#
#   sh refresh.sh                当天这个周期没跑过才跑
#   sh refresh.sh --force        忽略标记，强制重跑
#   sh refresh.sh --skip-deep    只跑快版（跳过补抽接口与模板验证）
#
# 用哪个 python：宝塔的 venv 建在站点外面（例如
# /www/server/pyporject_evn/zhuiju/bin/python），所以顺序是
#   ZHUIJU_PYTHON 环境变量 > zhuiju.env 里写的 ZHUIJU_PYTHON > .venv|venv/bin/python > python3
# 各步骤子进程用哪个解释器不由这里决定，是站点那套 autoupdate.python_bin() 现找的。
cd "$(dirname "$0")" || exit 1

if [ -z "$ZHUIJU_PYTHON" ] && [ -f zhuiju.env ]; then
    # 只抠这一行，去掉可能的引号与 Windows 换行符（文件是 CRLF 时 \r 会让 exec 失败）
    ZHUIJU_PYTHON=$(sed -n 's/^[[:space:]]*ZHUIJU_PYTHON[[:space:]]*=[[:space:]]*//p' zhuiju.env |
        tail -n 1 | tr -d "\"'\r")
    [ -n "$ZHUIJU_PYTHON" ] && export ZHUIJU_PYTHON
fi

PY=""
for c in "$ZHUIJU_PYTHON" .venv/bin/python venv/bin/python .venv/Scripts/python.exe python3 python; do
    [ -n "$c" ] || continue
    command -v "$c" >/dev/null 2>&1 || continue
    # 光 command -v 不够：Windows 的 python3 是应用商店的占位别名，能找到但一跑就报错，
    # 空跑一句 -c "" 才验得出这个解释器真能用
    if "$c" -c "" >/dev/null 2>&1; then PY=$c; break; fi
done

if [ -z "$PY" ]; then
    echo "找不到能用的 python。在站点根目录建 zhuiju.env 写一行：" >&2
    echo "  ZHUIJU_PYTHON=/www/server/pyporject_evn/zhuiju/bin/python" >&2
    exit 1
fi

echo "解释器： $PY"
exec "$PY" tools/refresh.py "$@"
