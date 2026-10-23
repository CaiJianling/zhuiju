# 追剧资源搜索（本地站点）

一个跑在自己电脑上的 Flask 网站：一个搜索框，输入电影 / 电视剧 / 动漫名称，同时查多个公开影视采集接口，把同名结果合并成一部片，并附上网盘、磁力、资源站的直达入口。

参考了 [awesome-zhuiju-free](https://github.com/laoma528/awesome-zhuiju-free) 的资源清单（`精选资源` 章节），检索接口取自其 TVBox 配置项并逐个实测，目录数据取自其 `resources/resources.json` 的事实字段（名称 / 地址 / 分类 / 标签 / 评分 / 可用状态）。

## 快速开始

双击 `启动.bat` 即可（首次会自动建虚拟环境并用清华源装依赖，之后直接起服务、自动开浏览器）。

手动方式：

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv\Scripts\python.exe run.py
```

打开 <http://127.0.0.1:5000/> 。想换端口：`set ZHUIJU_PORT=8000 && .venv\Scripts\python.exe run.py`。
Linux（含宝塔面板）不是这一套命令：解释器路径、`zhuiju.env`、权限与验收清单在 [docs/deploy.md](docs/deploy.md)。

**第一次打开会先看到一块滑块**（真人验证，拖一下就行，之后 12 小时内不再问）。
不想开这一道的，在后台「设置」里把「真人滑块验证」选成"关"；它挡得住随手抓页面的脚本，
挡不住铁了心的人，能确认的是哪来的 —— 见 [docs/human.md](docs/human.md)。

后台统计在 <http://127.0.0.1:5000/admin>。**第一次进去会直接领你把口令改成自己定的**
（那时用的还是首次启动随机生成、只在控制台打印过一次的那个），保存即写回
`zhuiju/data/admin.json` 并生效，不用重启。后台那一页每项统计的口径见 [docs/admin.md](docs/admin.md)。

## 四个标签页

| 标签页 | 内容 |
| --- | --- |
| 影视资源 | 10 个采集接口并发查询，同一部片按归一化片名合并，显示类型 / 年份 / 地区 / 更新状态 / 海报；点来源名展开该源的播放线路（多线路、逐集链接）；海报右下角的「详情」按钮给出影片信息与观看地址，线路一行一条、集数点了才铺 |
| 网盘查询 | **点进标签页才发请求**：服务端并发抓取网盘 / 磁力站的搜索结果页并解析出条目（标题 + 该站详情页链接）；解析不出来的站逐条写明原因并给"打开该站搜索页"入口。**没输关键词时不再是一句"先搜索"**：直接把这一页会用到的 20 个站列出来（本站能直接搜出结果的 / 只能打开该站自己搜的），这份清单只读目录与模板，一个请求都不发 |
| 网盘 · 磁力直达 | 76 个网盘 / 磁力 / 在线站 / 字幕站的入口，**不搜也有内容**（进页面即加载各站首页）；搜索后其中 18 个会直接带着关键词打开其站内搜索页 |
| 资源站目录 | 按**分类浏览**收录站点（不是拿影片名去匹配站名），带推荐指数和上游每日检测结果（🟢 可访问 / 🟡 受限 / 🔴 无法访问）；搜过片名之后每行多一个「搜此片」直达链接 |

「网盘查询」的实际覆盖要如实说明：目录里的网盘 / 磁力站大多把搜索框做成 POST 表单或 JS 提交，服务端抓不到结果（实测每种 GET/POST 变体返回的都是同一个 JS 空壳，页面大小和首页一致），只能标注原因 + 打开该站；能解析出条目靠的是 `data/templates.json` 里**已验证的 GET 搜索模板**，判据只有一个（`verify_get_templates.py` 双关键词差分验过），模板表每次更新都会重写，所以这个数会随时间掉。当前状态：**网盘 / 磁力这两类 20 个站里 0 个有可用模板**（表里剩的两条是字幕站，不在这个标签页范围内），所以这一页现在把所有站都归到"只能自己打开"。历史上抓到过：庆余年 20 站中 3 站出结果、共 16 条。只收与搜索页同域的链接——结果页上的跨域链接基本都是广告。

也正因为如此，**没输关键词时这个标签页不该空着**：`/api/cloud` 不带 `kw` 返回 `mode:"sites"` 的站点清单（`cloudsearch.site_rows()`，纯读目录 + 模板，一个请求都不发，也不写统计），页面把每个站的推荐指数、状态、能不能直接搜、首页链接摊开，有模板的还多显示一行搜索页模板（留着 `{kw}` 占位，而不是把空串填进去伪装成可用链接）。"能不能直接搜"用的判据与 `query_site()` 完全一致，清单和真搜起来不会两张皮。

**标签栏一直显示着，不跟着"有没有搜索"开关**：`#statline` 里那四个标签是进这几个面板的唯一入口，
而「网盘查询」的站点清单和「资源站目录」都不需要关键词。以前 JS 里确实按 `statline.hidden` 开关它，
但那行从来没生效过 —— CSS 的 `.statline { display: flex }` 把浏览器自带的 `[hidden]` 压掉了（那一头的
来龙去脉在 [docs/detail.md](docs/detail.md) 的「hidden 必须真能藏住东西」一节），所以它一直是露出来的，功能也就一直能用。现在把这个事实写进设计里：
`hidden` 属性从模板和 JS 里都去掉了，随搜索变的只有它右边那行 `#meta`（"命中 N 部…"）。

结果按匹配强度分层排序：完全同名 > 同系列版本（续集 / 特别版）> 近似名称 > 模糊匹配，同层再按"有几个源收录"排，所以《灌篮高手》不会被《灌篮高手的契约》这类蹭名短剧压下去。归一化后与关键词零重叠的结果（各源自身模糊匹配吐出来的噪声）会直接丢掉并在页面顶上标出条数——搜英文片名时尤其明显，`Oppenheimer` 从 13 条噪声收窄到 2 条相关。关键词至少 2 个字符，单字符会触发一轮无意义的并发抓取，直接拒掉。

## 界面：React 19 + HeroUI v3，前后端分开

前台不是模板渲染的界面了：`web/` 里是一份独立的 React 19 + HeroUI v3 + Tailwind v4 工程，
构建产物提交在 `zhuiju/static/spa/`（`app.js` / `app.css`），Flask 只出 **JSON API** 和
**一个 HTML 壳**（`templates/shell.html`）。跑站点仍旧 `python run.py`，那台机器**不需要 Node**；
只有改界面才 `cd web && npm run build`（`.npmrc` 默认 npmmirror，不引任何 CDN）。

壳里保留两样不能丢的东西：

- **SEO**：`title` / `description` / `canonical` / `og:` / JSON-LD 都在服务端写好（有词 =
  `ItemList`，无词 = `WebSite` + `SearchAction`），React 换词时同步同一套形状；
  禁用 JS 的人与只取 HTML 的抓取器看到的是 `#nojs` 那块服务端渲染的结果列表加一个
  `method=get` 的表单，`/?kw=…` 照样 302 到 `/s/<kw>` —— 两条路落同一个地址。
- **门禁**：没通过真人验证时，同一个壳以 `boot.locked=true` 下发，`#nojs` 整块不渲染、
  快照与榜单一个字段都不给，界面上只剩一块滑块；爬虫豁免走 unlocked 那条路，照旧拿到真内容。

主题三态（跟随系统 / 亮色 / 暗色）用 HeroUI 的 `useTheme`，记在 `localStorage['heroui-theme']`，
壳里一段内联脚本读同一个键提前把 `<html>` 定色，切换是渐变的（过渡只在那 380ms 里临时挂上），
切完用 toast 报一声「已保存 · 暗色」。配色、圆角、字号、阴影全部引 HeroUI 的 CSS 令牌，
`styles.css` 里只覆盖主色一处。按钮与输入一律药丸，所有数字走等宽，前台与后台统一收在 1680px，
够宽时两栏（左结果、右资料栏粘性跟随）。

**后台（`/admin`）是同一个 `web/` 工程里的第二个入口**（`src/admin.tsx` → `spa/admin.js`），
数据走 `/api/admin/view`，样式与主题开关和前台共用同一套 HeroUI 令牌。
为什么按标签取数、口令的边界、以及踩过的那几条坑写在
[docs/frontend.md](docs/frontend.md)。

## 这一页留什么，其余拆到哪儿了

这一页只留**要用它、要把它交付出去**必须看的内容：怎么跑起来、四个标签页都是干什么的、
后台怎么进、口令在哪改、每天几点更新、常用维护命令、能力边界。读代码才需要的、
排查时才需要的、以及实测过程的记录，按主题拆到了 `docs/` 下——内容一条都没删，只是搬走。
留在这一页里但平时用不上的（目录结构、加检索源的完整流程、这 17 个源是怎么筛出来的、
网盘那块为什么补不上）做成了**可折叠**的小节，标题一行字，点开才是内容。

| 想知道 | 去看 |
| --- | --- |
| 猜你想搜为什么给这些、排序与分页、海报为什么走本站代理、改完怎么自检 | [docs/hot.md](docs/hot.md) |
| 详情面板怎么点开、观看点击怎么落库、后台为什么默认只看最近一周、`[hidden]` 那个坑 | [docs/detail.md](docs/detail.md) |
| 手机 / 平板怎么排、主题（亮/暗/跟随系统）、阅读宽度与两栏栅格、配色体检 | [docs/mobile-theme.md](docs/mobile-theme.md) |
| 前端怎么搭（React 19 + HeroUI v3）、怎么改界面、SEO 壳与无 JS 出口、后台怎么共用同一套令牌 | [docs/frontend.md](docs/frontend.md) |
| 数据自动更新（访问时触发）的判据、失败冷却、GitHub 数据为什么一律走国内镜像 | [docs/autoupdate.md](docs/autoupdate.md) |
| 真人滑块验证：挡得住什么、挡不住什么，爬虫怎么豁免，cookie 里有什么 | [docs/human.md](docs/human.md) |
| 后台统计每一项的口径：聚合、浏览器与来源识别、真人/脚本/说不清三档与行为判读、IP 归属地地图 | [docs/admin.md](docs/admin.md) |
| Emby STRM：把近一年的资源导成媒体库 | [docs/strm.md](docs/strm.md) |
| 部署到 Linux（宝塔面板）、端口与反向代理、nginx 挂域名 | [docs/deploy.md](docs/deploy.md) |

## 后台统计（/admin）

打开 http://127.0.0.1:5000/admin ，要口令。

后台分**四个标签页**——总览 / 明细 / Emby STRM / 设置，左边贴一条只列当前标签小节的**目录**，
点了滚过去。当前标签与筛选都写在 URL 上，刷新或把链接发给别人都会停在同一屏；
页里任何筛选链接都会自动带上当前标签（切标签不会把筛了一半的条件甩掉）。每一项统计的口径见
[docs/admin.md](docs/admin.md)。标题那一行有一颗**回前台**，口令没输进去那一屏也在。

前台页脚最后那行（「本地运行，数据不出这台电脑」）末尾挂着一条**统计**回到这里：它跟那行字同色、
不带下划线，看着就是一句普通说明；`robots.txt` 里本来就 `Disallow: /admin`，这条链接又额外标了
`rel="nofollow"`。

### 口令在哪改

**第一次登录会自动带你去改口令。** 文件不存在时首次启动会随机生成一个 12 位口令（打印在控制台一次），
并在 `admin.json` 里标 `"password_is_temp": true`；用这个随机口令登录成功后，不会直接进统计页，
而是跳到「先设置一个你自己知道的口令」，输入当前口令 + 新口令两遍，**保存即写回配置文件、立刻生效，
不用重启服务**。改完标记变 `false`，以后登录就直奔统计页；页面上也留着「改口令」入口随时可以再改。

`zhuiju/data/admin.json`：

```json
{
  "password": "你自己定的口令",
  "secret_key": "随机 64 位串，用来签登录 cookie",
  "password_is_temp": false
}
```

想手动改也行：编辑 `password` 再重启（`secret_key` 那行别动，动了所有已登录会话都失效）。
老配置文件里没有 `password_is_temp` 这个键时，会按口令长得像不像随机生成的判断一次并写回文件。

新口令最少 6 个字符、不能首尾带空格；当前口令必须验对才能改（过期会话不能替你改），
两次输入不一致、太短、为空都会被拒且不会写进文件——空口令会让 `load()` 又生成一个随机的，反而更迷惑。

也可以用环境变量 `ZHUIJU_ADMIN_PASSWORD` 覆盖，让明文不落盘；这种方式下页面**不会**催你改口令
（本来就打算靠环境变量部署的人，改文件不会生效），改口令页会明确提示当前口令由环境变量指定。
`ZHUIJU_SECRET_KEY` 同理。

这个文件和统计库一样进了 `.gitignore`——里面是明文口令，不该提交。

## 设置：每天几点算「新的一天」

后台最下面「设置」那一节能改的就一件事：**几点之后的第一次访问才触发更新**（默认凌晨 2 点）。
两件事要知道：**没人访问就不会自己跑**（本站不用系统计划任务，"设成 8 点"不等于"8 点整一定更新"），
以及**改完立刻生效、不用重启**。值存在 `zhuiju/data/settings.json`（不进版本库；删了就回默认值），
`ZHUIJU_REFRESH_HOUR` 环境变量优先于文件，被顶着的时候页面上会写明白。
日切算法、为什么不存进 `stats.db`、失败冷却见 [docs/autoupdate.md](docs/autoupdate.md)。

<details>
<summary>目录结构（想知道每个文件干什么再展开）</summary>

```
zhuiju/
  app.py            Flask 路由：/、/s/<关键词>、/admin、/admin/password、/api/search|catalog|deeplinks|cloud|detail|click|health|hot|refresh|strm/*、
                    /strm/zip、/strm/file、/img、/robots.txt、/sitemap.xml
  search.py         并发检索、maccms 响应归一化、跨源片名合并与分层、播放线路解析、
                    按 ID 取详情（detail）与按片名兜底取详情（detail_by_title，15 分钟缓存）
  catalog.py        目录检索与直达链接拼装（按文件 mtime 缓存，改数据不用重启）
  cloudsearch.py    网盘 / 磁力站结果页抓取与解析（只收同域、带逐站状态）；site_rows() 给无关键词时那份不联网的站点清单
  hot.py            猜你想搜（CMS 最新流 + 豆瓣候选回查 + ac=detail 补海报，后台重建、6 小时缓存、按页取；
                    每行带 src/vid，供海报右键直接取详情）
  seo.py            /s/ 落地页快照、查询记录、robots 与 sitemap
  imgproxy.py       海报代理（补防盗链 Referer、忽略自签证书、拦内网；内存 + 磁盘两层缓存）
  __init__.py       包导入时读 zhuiju.env（venv 在站点外面时在那儿指一次，处处都认）
  autoupdate.py     访问时触发的后台更新（STEPS 唯一清单、逻辑日、锁文件 + 子进程 PID 判活、
                    进度、解释器现找 python_bin()、失败冷却 ZHUIJU_RETRY_MINUTES）
  stats.py          查询统计与观看点击落 SQLite（两张表 queries/clicks；后台明细按时间 UNION 成一条活动列表；过滤/分页/聚合走参数化 SQL；写失败不影响搜索）
  geoip.py          离线 IP 归属地：纯标准库读 ip2region xdb + 国家轮廓转内嵌 SVG 路径
  agent.py          User-Agent 识别（浏览器/系统/设备/爬虫）与 Referer 来源判定，纯标准库
  admin.py          后台口令配置读写、口令校验、首次登录判断、登录失败限流、反代下取真实客户端 IP
  human.py          真人滑块门禁：一次性挑战、签发/校验匿名 cookie、搜索引擎爬虫豁免（UA + 反查 DNS）
  settings.py       这台机器的运行设置（日切时间、门禁开关、验证管多久）：默认值、校验、读写 data/settings.json
  sources.py        检索源配置读写
  settings.py       这台机器的运行设置（后台能改的那几项）：默认值、校验、读写 data/settings.json、环境变量优先
  strm.py           Emby STRM 的数据层：采集结果落 data/strm.db、线路与集数解析、按 Emby 多版本规则导出目录树
                    （每个 strm 一份同名 NFO、目录名可带 [tmdbid=…]）、类别判据、分卷（movieNN/tvNN）与打包 zip、
                    清单与索引、下载接口用的路径校验（不联网，可离线测；查 TMDB 那一步在 collect_strm.py）
  strmjob.py        STRM 采集的"访问时触发"层：自己的锁与状态文件、最小间隔、进度、调 autoupdate.spawn 起子进程
  data/
    sources.json    实测可用的检索接口（含站内搜索模板、首页是否可浏览、能不能按关键词搜）
    catalog.json    资源站目录（由 tools/build_catalog.py 生成）
    templates.json  已复核通过的各站搜索 URL 模板
    refresh_state.json    最近一次自动更新的结果（页头新鲜度就来自这里）
    refresh_progress.json 后台更新的实时进度（页头进度条与步骤胶囊）
    stats.db        查询统计与观看点击两张表（含 -wal/-shm 侧文件；本机隐私，不进版本库）
    strm.db         Emby STRM 的采集库（vod 条目 / 翻页游标 / 分卷 / 已写文件 / 打包记录 / 运行记录 / 设置；
                    里面全是公开采集接口的地址，没有本机隐私，但换台机器就该重采，不进版本库）
    strm_state.json 最近一轮采集的结果   strm_progress.json 采集的实时进度（后台那一节的进度行）
    admin.json      后台口令、会话签名密钥、是否还是首次生成的随机口令（明文口令，不进版本库）
    settings.json   后台「设置」写的那几项（现在只有 refresh_hour：每天几点算新的一天）；不进版本库，删了就回默认值
    cache/hot.json  猜你想搜缓存   cache/mirror_used.json  这次上游数据实际走的哪个镜像
    cache/img/      海报的磁盘缓存（sha1 命名的图片 + index.json；7 天 / 200MB，删掉即清空）
  templates/shell.html  前台唯一的 HTML：SEO 元信息 + boot 数据 + React 挂载点 + 给爬虫/禁 JS 的那一份
  templates/admin_shell.html    后台唯一的 HTML（/admin 与 /admin/password 共用这一个壳）
  templates/admin.html, admin_password.html, _theme.html    只剩"禁用 JS 时提交登录/改口令"那一页兜底
  static/spa/app.js, admin.js, app.css    构建产物（由 web/ 生成，提交进仓库，部署机不需要 Node）
  static/app.css, theme.js      只服务上面那两份兜底页（同一套 HeroUI 令牌、同一个 heroui-theme 键）
web/                        前后台共用的源码工程：React 19 + HeroUI v3 + Tailwind v4 + Vite
  src/App.tsx               前台状态编排（关键词/页码/标签页/详情/门禁）
  src/admin/AdminApp.tsx     后台：登录、四个标签页、侧边目录、STRM 轮询
  src/api.ts, types.ts      JSON 接口客户端与字段契约（字段名跟 Python 侧一致，不改名）
  src/components/Gate.tsx   真人滑块（前台弹层与未验证首屏共用一份实现）
tools/                  重新采数据的维护脚本，日常使用不需要跑
  build_catalog.py      上游 resources.json -> 本地目录（requests 走 gh-proxy 镜像链，记下实际用的源）
  harvest_apis.py       从 15 个 TVBox 配置地址里抽取候选采集接口
  test_apis.py          逐个实测候选接口
  test_apis_extra.py    再补一批常见公开采集接口实测（红牛/极速/光速/备番这么来的）
  harvest_templates.py  抓各站搜索表单，试站内搜索路径
  verify_get_templates.py  双关键词差分验证模板是否真生效
  build_templates.py    复核 + 合并，写 templates.json
  probe_sources.py      重新体检检索源，重写 sources.json
  probe_cloud.py        探测网盘站有没有可用的搜索端点
  harvest_more_apis.py  从全部 TVBox 配置（含中文域名 IDN）补抽候选接口并实测
  add_sources.py        把实测通过的新接口并入 sources.json
  refresh.py            一次完整更新的总入口（本周期已完整跑过则跳过；--skip-deep 的快版不算跑完）
                        --check-env 只报告"会用哪个解释器、依赖齐不齐"，部署排查用
  fetch_geo.py          下载 IP 归属地库与国家轮廓底图，算好 country_points.json（走 gh-proxy）
  collect_strm.py       慢速采集近一年电影/电视剧：翻各源 videolist 更新流、游标续采、先落 strm.db，再合并导出
                        strm 目录树并按卷打 zip；也管查 TMDB 号与回填元数据（--check 看状态，--export-only 只导出，
                        --full 全量重建，--ids-only 只查号，--backfill-only 只补旧条目的元数据）
  restart.py            确定性地重启本地站点（先杀干净旧进程，再验证新路由已生效）
                        Windows 走 WinAPI，Linux 走 /proc（非 root 时只能按 server.pid 收尾）
  check_autoupdate.py   验收访问触发的异步更新（用桩，不真跑几分钟；九个场景）
tests/
  test_smoke.py         离线：检索解析、合并分层、目录
  test_cloudparse.py    离线：网盘结果解析器（自造 HTML）
  test_seo_hot.py       离线：猜你想搜归类 / 一年窗口 / SEO 清洗与 robots、sitemap
  test_strm.py          离线（244 项）：线路与集数解析、时间范围判据、导出命名/同名 NFO/分卷、类别投票、
                        TMDB 命中判据、打包、下载接口与路径防护、后台异步保存与访问触发
  test_detail.py        离线：详情接口（按 ID / 按片名兜底 / 缓存与失败边界）与右键前端接线
  test_cloud_live.py    活体：临时端口起服务验证路由与查询，跑完自动关
  test_deploy_paths.py  离线：跨平台部署路径（解释器现找、zhuiju.env、refresh.sh 行尾、/proc 解析）
data/upstream/          上游 JSON 缓存（build_catalog.py 自动下载）
strm/                   Emby 用的 strm 目录树（strm/movie/movieNN/片名 (年份)/…、strm/tv/tvNN/剧名 (年份)/Season NN/…；
                        开了 NFO 时每个 x.strm 旁边一份同名 x.nfo，剧集根目录另有 tvshow.nfo）
strm_zips/              分卷包 movieNN.zip、tvNN.zip（下载接口给的就是这些；两个目录都不进版本库）
zhuiju/data/cache/      运行时缓存：hot.json（猜你想搜）、seo-*.json（/s/ 快照）
zhuiju/data/queries.jsonl  搜过的关键词，供 sitemap 生成
logs/                   更新日志、后台更新记录、服务输出、server.pid
run.py              起服务 + 自动开浏览器（ZHUIJU_NO_BROWSER=1 可关；无 DISPLAY 时不开）
启动.bat            一键启动（Windows）
refresh.bat         一键手动更新（Windows）
refresh.sh          同上，Linux / macOS 版（sh refresh.sh --check-env 先看环境）
zhuiju.env.example  部署配置模板：拷成 zhuiju.env 就能指定站点外的 venv、端口、口令
.gitattributes      强制 .sh 用 LF、.bat 用 CRLF（.sh 带上 CRLF 会得到 /bin/sh^M）
```

</details>

## 维护

第三方公开接口随时会失效，失效的源不会静默吞掉结果，页面顶部会标出哪个源挂了（鼠标悬停看原因）。

```bat
:: 日常：体检所有检索源 + 首页可浏览性；搜索与最新流都拿不到片名的才停用，
:: 只是关键词这条路被站点关了的，标 searchable=false 留着喂猜你想搜
.venv\Scripts\python.exe tools\probe_sources.py 庆余年

:: 目录数据有更新时
.venv\Scripts\python.exe tools\build_catalog.py
```

<details>
<summary>想换 / 加检索源时才用得上：完整八步（平时不用管）</summary>

```bat
.venv\Scripts\python.exe tools\harvest_apis.py
.venv\Scripts\python.exe tools\test_apis.py
.venv\Scripts\python.exe tools\test_apis_extra.py
.venv\Scripts\python.exe tools\harvest_templates.py
.venv\Scripts\python.exe tools\verify_get_templates.py
.venv\Scripts\python.exe tools\build_templates.py
.venv\Scripts\python.exe tools\probe_sources.py 庆余年
.venv\Scripts\python.exe tests\test_smoke.py
```

</details>

脚本产生的中间文件都落在 `.probe/`（可随时删，重跑即可）。浏览器直接访问 `http://127.0.0.1:5000/api/health` 也能看当前源状态：
只供最新流的那两个是按"最新流"探的，返回里 `mode` 会写明这次走的是 `search` 还是 `latest`，所以它们不该以"搜不到"被判死。

<details>
<summary>这 17 个源是怎么筛出来的（含被站点自己关掉搜索的那两个）</summary>

收录标准只有一条：**本机实测能返回片名才写进配置**，所以 15 个 TVBox 配置里只有 3 个能打开、抽出的 16 个候选接口最后只留 8 个，这是真实数字而不是漏配。
后来按一份 17 条的公开资源清单逐个实测（搜索 + 最新流 + `ac=detail` 取线路三路都验），配置里现在是 **17 个源，其中 15 个能按关键词检索**：
新增可用的是 电影天堂 / 鲸鱼 / 无尽 / 魔都 / 非凡新域（`ffzy5.tv` 与已收录的 `cj.ffzyapi.com` 是同一套库换了域名，留作备用入口）；
清单里 广速=光速、海豚=火狐（同域重复列了两次），真正独立的站只有 16 个。
**索尼（`suoniapi.com`）与闪电（`sdzyapi.com`）没有静默丢掉，而是标了 `searchable: false`**：前者只要 URL 里带 `wd=`
就返回 403 拦截页（换 `ac=list`/`videolist`/`detail`、换纯 ASCII 关键词都一样，而 `keyword=`/`name=` 它不认 ——
会把参数忽略、原样返回整张列表，很容易被误判成"搜索成功"），后者接口明文回 6 个字「暂不支持搜索」。
两家的最新流与 `ac=detail` 都是好的，所以留在配置里喂「猜你想搜」，但 `search()` 跳过它们 ——
按关键词并发时把它们算进来，等于每次搜索都稳定失败一条，`sources_total` 与「平均可用源」都不再是实话。
首页那句"结果来自 N 个采集接口"和骨架屏那句"正在并发查询 N 个"数的都是**会被并发到的**那些。

</details>

## 国内环境准备

装包和拉取 GitHub 数据都走国内通道，仓库内脚本已按下述方式处理：

- pip 用清华镜像：`-i https://pypi.tuna.tsinghua.edu.cn/simple`（`启动.bat` 已内置）
- 拉取上游 `resources.json` / `README` 等 GitHub raw 文件走 `https://gh-proxy.com/` 前缀，例如
  `curl -L "https://gh-proxy.com/https://raw.githubusercontent.com/laoma528/awesome-zhuiju-free/main/resources/resources.json"`

检索接口本身是国内第三方站点，不需要代理；目录里标了 `GLOBAL` 或"需梯子"的站点是例外。

## 限制与说明

- 采集接口是第三方公益站，稳定性、片源完整度都不受控；某个源挂了直接影响结果数，页面顶部会标出是哪个源，可多试几种关键词写法（只留主标题、去掉"第 X 季"）。
- **滑块验证不是安全边界**：它把"随手 GET 的脚本"变成"要照流程发请求的脚本"，挡不住铁了心的人
  （挑战与校验都在这台机器上）。真正的产物是那枚签名 cookie 给后台的"这是真人"硬凭据。
  细节、爬虫豁免规则和关掉它的方式见 [docs/human.md](docs/human.md)。
- `tools/probe_sources.py` 只验证"能返回片名"，不验证点开能不能真播。
- **网盘这一类拿不到结果，而且是原理性的限制**（不是没配好）：细节和已经试过的路子见下面「网盘那两块为什么补不上」。
- 76 个直达站点里 18 个有已验证的站内搜索路径，其余 58 个退回首页，页面上逐条标注了。
- 17 个检索源里 10 个（虎牙 / 火狐 / 极速 / 光速 / 备番 / 量子 / 鲸鱼 / 无尽 / 索尼 / 闪电）首页返回 403 或 500，属于只开放 API 的采集站，这类结果不显示"打开站点"，以免跳到拦截页（`browsable` 由 `tools/probe_sources.py` 实测写回）。
- 结果标题带"同系列版本 / 近似名称 / 模糊匹配"标记的，是接口返回的续作、特别版或同名蹭名作品（例如各种"庆余年之××"短剧）；完全同名的正片排在最前。
- 英文片名往往搜不到，这些接口收的是中文片名，请换中文译名（如 Oppenheimer → 奥本海默），无结果时页面也会提示。
- 本工具只做第三方公开接口的聚合查询，不存储、不转发任何影视内容；外链安全性由使用者自行判断。仅供个人技术学习与找片参考，请支持正版。
- **会存查询日志**：`zhuiju/data/stats.db` 里记着"哪个 IP、用什么浏览器和系统、从哪个页面来、
  在什么时候搜了什么词"，另有
  `zhuiju/data/queries.jsonl`（给 sitemap 用）与 `logs/`。这三个文件都只在你的机器上、
  且都进了 `.gitignore`；不想留就把 `stats.db` 删掉，它会自动重建。想彻底不记，
  把 `zhuiju/app.py` 里的 `_record()` 调用注掉即可（统计页会因此变空）。
- 后台统计页 `/admin` 只有一层口令，够挡住乱点的同事，不够当多人账号体系用；
  要挂到能被公网访问的地址，先配合 HTTPS，并考虑在 nginx 上再加一层基本认证（nginx 那几行在 [docs/deploy.md](docs/deploy.md)）。

<details>
<summary>网盘那两块为什么补不上（原理性限制，不是没配好）</summary>

目录里 4 家网盘站（PanSou、夸克搜、追剧吧、谷哥搜）的搜索框是 POST 表单或纯 JS 提交，
GET 拼关键词不生效，实测每种变体返回的都是和首页一样的 JS 空壳。考虑过自建
[pansou](https://github.com/fish2018/pansou) 补这块，但它的数据源是 **Telegram 公开频道**
—— 本机网络访问不了 Telegram，所以这条路走不通，已放弃（相关代码也已删除，不留半成品）。

「网盘查询」标签页因此只对**搜索页直接返回 HTML** 的站做服务端抓取与解析
（庆余年实测 20 站中 2–3 站出结果、约 14–16 条），其余站逐条标注原因并给"打开该站搜索页"入口；
只收与搜索页同域的链接，跨域的基本是广告。

</details>
