@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo 首次运行，正在创建虚拟环境...
  python -m venv .venv || (echo 未找到 python，请先安装 Python 3 并加入 PATH & pause & exit /b 1)
  echo 正在用清华源安装依赖...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)

rem 用法： 启动.bat            默认 5000 端口
rem         启动.bat 8000      指定端口
rem         启动.bat 8000 0.0.0.0   指定端口并允许局域网访问
if "%~1"=="" (
  ".venv\Scripts\python.exe" run.py
) else if "%~2"=="" (
  ".venv\Scripts\python.exe" run.py --port %~1
) else (
  ".venv\Scripts\python.exe" run.py --port %~1 --host %~2
)
pause
