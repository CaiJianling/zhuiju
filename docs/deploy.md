# 部署到 Linux（宝塔面板）

解释器与端口写在哪、权限与要带过去的文件、验收清单、端口与反向代理、nginx 挂域名。

← 返回 [README](../README.md)：这台机器怎么跑起来、口令在哪、能做什么不能做什么，都在那一页。

## 部署到 Linux（宝塔面板）

本仓库里所有命令示例都是 Windows 写法。Linux 上把 `.venv\Scripts\python.exe`
换成 `.venv/bin/python`；用宝塔的话把站点根目录 `zhuiju.env` 建好（见下），
`sh refresh.sh --check-env` 会把它最终会用哪个解释器打出来。

**别把 Windows 的 `.venv` 目录传上去。** venv 不可移植：里面是 Windows 的 exe 和指向本机
的 `pyvenv.cfg`。传上去之后 `exec` 会得到

```
OSError: [Errno 8] Exec format error: '/www/wwwroot/zhuiju/.venv/Scripts/python.exe'
```

六个步骤挂在同一行上、`seconds` 只有 0.1 —— 就是这个原因（以前 `tools/refresh.py` 写死了
那个路径）。删掉 `.venv`，在服务器上用宝塔的 Python 环境重建，或者：

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 解释器与端口写在哪

宝塔创建的 venv **在站点目录外面**，例如 `/www/server/pyporject_evn/zhuiju/bin/python`。
代码不再假设它在哪儿：`autoupdate.python_bin()` 按
`ZHUIJU_PYTHON` → 正在跑站点的那个解释器 → `ZHUIJU_VENV` 指的目录 → 站点内 `.venv|venv|env`
的顺序现找，并且真的跑一句 `import flask, requests` 确认依赖齐不齐，缺依赖的候选不会被选。
所以站点自己触发的更新本来就用对了解释器，什么都不用配；要手动跑 `tools/*.py` 才需要指一下：

```sh
# 站点根目录建 zhuiju.env（模板是 zhuiju.env.example；这文件已被 git 忽略，因为可以写口令）
ZHUIJU_PYTHON=/www/server/pyporject_evn/zhuiju/bin/python
ZHUIJU_PORT=5000
```

`zhuiju.env` 在导入 `zhuiju` 包时读取，只认列出的那几个键，值两边的引号和 CRLF 的 `\r` 都会去掉，
**已经设了的环境变量优先**。`ZHUIJU_VENV` 则给"不想写全路径"的场合用（指到 venv 目录即可）。

选出来的路径**故意不做 `resolve()`**：venv 里的 `bin/python` 通常是指向真解释器的软链接，
一解析就跑到 venv 外面了，`site-packages` 跟着丢——探依赖时明明齐全，真跑起来却说 import 不到
flask。`tests/test_deploy_paths.py` 用一条带 `..` 的路径钉住了这个行为。

### 权限与要带过去的文件

`zhuiju/data/` 和 `logs/` 必须能被跑站点的那个用户写（宝塔通常是 `www`）——更新状态、进度、
锁、SQLite 统计库、`data/cache/` 全在那里：

```sh
chown -R www:www /www/wwwroot/zhuiju
```

只用标准库 + Flask + requests，没有别的二进制依赖。开发实测在 Python 3.13；宝塔常见版本
（3.8–3.12）里那些新式类型标注都被 `from __future__ import annotations` 推迟了，不会在运行时求值，
但**低版本我没有真跑过**，装完先跑一句 `sh refresh.sh --check-env` 确认依赖 import 得动。

跟着 git 走的三个数据文件（`sources.json` / `templates.json` / `catalog.json`）克隆下来就有；
`admin.json`、`stats.db`、`refresh_state.json`、`data/geo/` 都被 git 忽略，属于本机数据：
口令会在服务器首次启动时随机生成并打印一次（登录后领你改），统计库要从本机拷才留得住历史，
归属地库要重跑一次 `sh refresh.sh` 之外的那条命令：

```sh
.venv/bin/python tools/fetch_geo.py        # 约 14MB，走 gh-proxy 镜像链
```

### 验收

```sh
sh refresh.sh --check-env     # 会用哪个解释器、依赖齐不齐、zhuiju.env 读到了没有
sh refresh.sh --force         # 真跑一轮六步，成功与否写进 zhuiju/data/refresh_state.json
tail -n 40 logs/refresh-*.log # 日志头两行有解释器和选它的理由
```

页头横幅和 `/admin` 顶部那行会显示"自动更新用的解释器 / 最近一次访问触发的结论 / 失败冷却还剩
多久"，不用登服务器翻日志。更新仍然**只在访问时触发**，不需要 cron 或计划任务；一轮失败后默认
15 分钟内不再自动重跑（`ZHUIJU_RETRY_MINUTES=0` 可以关掉），改完环境跑一次 `--force` 就正常了。
挂反代时 `X-Forwarded-For` 只有在上一跳是回环地址时才被采信，所以后台统计要能看出真实访客，
得靠 nginx 传头（见"端口与反向代理"）。

## 端口与反向代理

端口有三种指定方式，优先级从高到低：

```bat
python run.py --port 8000              :: 命令行
python run.py --port 8000 --host 0.0.0.0   :: 同时允许局域网访问
set ZHUIJU_PORT=8000 && python run.py  :: 环境变量
启动.bat 8000                          :: 双击脚本带参数（第二个参数是 host）
```

端口被占用时会直接说明并给出两条出路，而不是抛一句 Flask 的堆栈：

```
端口 8124 已被占用。
  换个端口：  python run.py --port 8000
  或先结束占用进程：  python tools/restart.py --port 8124   （它会先杀干净再起）
```

`tools/restart.py --port N` 用 WinAPI 查出监听该端口的进程并结束，再验证新代码已生效——旧进程占着端口、页面却跑旧代码这个坑踩过两次，所以固化成了工具。

### 用 nginx 挂到域名

支持，代码里已为反向代理做了两件事：

- `TrustForwarded` 中间件读 `X-Forwarded-Proto` / `-Host` / `-Prefix`，让 `canonical`、`og:url`、`sitemap.xml` 生成的是你的域名而不是 `http://127.0.0.1:5000/`。**只信任来自回环地址的转发头**，否则任何人都能用一个伪造的 Host 头污染规范链接。必须是 WSGI 中间件而不是 `before_request`——Werkzeug 在建 `Request` 时就算好了 `host_url`，实测在 `before_request` 里改 `environ` 完全无效。
- `/img` 图片代理只服务**本站页面发出过的地址**（`imgproxy.register`，登记表在 `zhuiju/data/cache/img_urls.json`，上限 3000 条按登记序淘汰）。不这么做的话，挂到域名上它就成了任何人都能驱使的公共图片代理。设 `ZHUIJU_IMG_OPEN=1` 可关掉这层限制，公网暴露时别关。

一份能用的 nginx 配置：

```nginx
location / {
    proxy_pass http://127.0.0.1:5000;
    proxy_set_header Host              $host;
    proxy_set_header X-Forwarded-Host  $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP         $remote_addr;
}
```

三个要注意的边界：

1. **必须挂在域名根路径**。页面里的资源都是 `/static`、`/api`、`/s/`、`/img` 这样的绝对路径，挂到子路径（如 `/zhuiju/`）会全部 404。要挂子路径就给 nginx 加 `proxy_set_header X-Forwarded-Prefix /zhuiju;` 并把代码里的路径改成 `url_for`——目前没做这一步。
2. **Werkzeug 自带服务器不适合对外提供服务**（单进程、无连接管理）。挂域名前建议换 waitress：`pip install waitress -i https://pypi.tuna.tsinghua.edu.cn/simple`，然后 `python -c "from waitress import serve; from zhuiju.app import create_app; serve(create_app(), listen='127.0.0.1:5000', threads=8)"`。
3. 一旦公网可访问，"访问时触发自动更新"就意味着访客和爬虫也会触发更新（有当天标记与 5 分钟重启间隔兜底，一天只会真跑一次）；同时页面上那些第三方资源站链接也就公开了，这属于你要不要承担的范围。

