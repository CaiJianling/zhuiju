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

后台统计在 <http://127.0.0.1:5000/admin>，口令第一次启动时随机生成、打印在控制台，
写在 `zhuiju/data/admin.json` 里，随时可以改成自己知道的（详见"后台统计"一节）。

## 四个标签页

| 标签页 | 内容 |
| --- | --- |
| 影视资源 | 10 个采集接口并发查询，同一部片按归一化片名合并，显示类型 / 年份 / 地区 / 更新状态 / 海报；点来源名展开该源的播放线路（多线路、逐集链接） |
| 网盘查询 | **点进标签页才发请求**：服务端并发抓取网盘 / 磁力站的搜索结果页并解析出条目（标题 + 该站详情页链接）；解析不出来的站逐条写明原因并给"打开该站搜索页"入口 |
| 网盘 · 磁力直达 | 76 个网盘 / 磁力 / 在线站 / 字幕站的入口，**不搜也有内容**（进页面即加载各站首页）；搜索后其中 18 个会直接带着关键词打开其站内搜索页 |
| 资源站目录 | 按**分类浏览**收录站点（不是拿影片名去匹配站名），带推荐指数和上游每日检测结果（🟢 可访问 / 🟡 受限 / 🔴 无法访问）；搜过片名之后每行多一个「搜此片」直达链接 |

「网盘查询」的实际覆盖要如实说明：目录里 4 家网盘站的搜索框是 POST 表单或 JS 提交，服务端抓不到结果（实测每种 GET/POST 变体返回的都是同一个 JS 空壳，页面大小和首页一致），所以这一类目前只能标注原因 + 打开首页；真正能解析出条目的是搜索页直接返回 HTML 的那几个站（庆余年实测 20 站中 3 站出结果、共 16 条）。只收与搜索页同域的链接——结果页上的跨域链接基本都是广告。

结果按匹配强度分层排序：完全同名 > 同系列版本（续集 / 特别版）> 近似名称 > 模糊匹配，同层再按"有几个源收录"排，所以《灌篮高手》不会被《灌篮高手的契约》这类蹭名短剧压下去。归一化后与关键词零重叠的结果（各源自身模糊匹配吐出来的噪声）会直接丢掉并在页面顶上标出条数——搜英文片名时尤其明显，`Oppenheimer` 从 13 条噪声收窄到 2 条相关。关键词至少 2 个字符，单字符会触发一轮无意义的并发抓取，直接拒掉。

## 猜你想搜（空关键词时）

搜索框为空时，下方展示**电影**和**电视剧**两个区域，按**更新时间从新到旧**排列。**每区固定一行，用「‹ 上一页 / 下一页 ›」整行切换**，不是横向拖动条——网格是 `repeat(var(--hot-cols), 1fr)` 且不带 `overflow-x`，所以 `scrollWidth == clientWidth`，永远不会出现滚动条。

每页张数不是写死的：CSS 按断点决定列数（≥1180px 6 列 → 1180 5 列 → 960 4 列 → 720 3 列 → 520 2 列），JS 从 `getComputedStyle(grid).gridTemplateColumns` 把实际列数读回来当每页张数，两边共用同一个来源；窗口缩放时防抖重铺当前页。组标题右侧显示「第 m / n 页」，到头自动禁用。

服务端仍然渲染 12 张（`_first_row(per=12)`）给爬虫和不执行 JS 的访问者，JS 起来后按列数重铺第 0 页——这 12 条已经在 `boot-data` 里，所以首屏不额外发请求。

翻页走 `/api/hot?kind=movie&offset=<page*cols>&limit=<cols>`，`offset` 越界返回空列表不报错。曾经的两个坑都由 `tests/test_seo_hot.py` 第 7、8 节锁死：① 按钮禁用条件写成 `rows|length <= 12`，而 `rows` 已被截成一行，导致按钮永远点不动；② 用 `flex + overflow-x` 做成了横向拖动条而不是翻页。

范围是最近半年（按 `vod_time` / `vod_year` 判定，页面副标题写明起算日期与候选总数），每类缓存 60 条。点卡片会跳到该片名自己的 `/s/` 地址。

两个池子的分工是实测出来的，不是设计偏好：

- 采集接口的"最近更新"流 `limit` 被硬限 20 条，内容又被 `中国动漫/内地剧` 占满（虎牙 20 条里 11 条是中国动漫），**电影在这个流里天然稀少**；带 `t=分类ID` 又只返回 0~2 条，所以"按分类列最新"这条路不通。
- 因此电视剧走 CMS 最新流（能拿到多源覆盖度），电影再补一批豆瓣「热门 / 新片」候选。
- 豆瓣 `j/search_subjects` 不返回上映日期，所以**只用于出候选、评分和海报**；"最近半年"一律以 CMS 的时间字段为准。豆瓣候选还要回查 CMS 命中才算数——这样点进去一定有结果。
- 列表接口 `ac=list` 常常不带 `vod_pic`，所以再用 `ac=detail&ids=` 批量回查补海报（`fill_pics`），否则卡片大片空白。
- TMDB：`api.themoviedb.org` 在本机网络超时，`api.tmdb.org` 可达但需要 API key，所以未接入。

构建一次约 100 秒以上，因此**绝不同步阻塞页面**：结果缓存在 `zhuiju/data/cache/hot.json`（6 小时），过期时请求立即返回旧缓存并标 `building: true`，后台线程重建；完全没缓存时先返回空并提示稍后刷新。

## 搜索结果的 SEO

每个关键词一个可被收录的固定地址：`/s/<关键词>`（如 `/s/%E5%BA%86%E4%BD%99%E5%B9%B4`）。

- 页面带 `title`、`description`、`canonical`、Open Graph，以及 JSON-LD：首页是 `WebSite` + `SearchAction`（告诉搜索引擎 `{{site}}/s/{关键词}` 是搜索模板），关键词页是 `ItemList`（含 `numberOfItems` 和每条结果的 `/s/` 链接）。
- **服务端渲染结果摘要**：爬虫不执行 JS 也能看到该关键词下的结果标题与链接；浏览器里 JS 自动接管成交互式界面，并把服务端摘要折叠成一行说明（`ssr-done`）。
- 结果快照在 `zhuiju/data/cache/seo-*.json`（6 小时），爬虫不必等并发检索，也不会每次抓取都敲上游接口；同一关键词的并发请求由锁去重。
- 搜过的关键词记入 `zhuiju/data/queries.jsonl`，`/sitemap.xml` 由「猜你想搜 + 历史搜索」生成——谁搜过某部剧，那部剧的 `/s/` 地址就会进 sitemap。
- `/robots.txt` 放行 `/` 和 `/s/`、禁止 `/api/`。

注意这仍是 127.0.0.1 的本地站点，要真被搜索引擎收录得先有公网地址；这套 URL 与元信息是为了让它能直接部署到可访问的地址上。

## 海报为什么走本站代理

第三方海报有两类问题，实测出来的：

- **防盗链**：`img*.doubanio.com` 无 Referer 返回 **418**、带本站 Referer 返回 **403**、只有带 `https://movie.douban.com/` 才 200。浏览器里伪造不了 Referer（`referrerpolicy="no-referrer"` 反而会让这些图全挂）。
- **证书 / 端口**：部分采集站图床挂在非标端口 + 自签证书上（如 `taopianimage.xyz:43333`），浏览器静默失败。

所以海报统一经 `/img?url=<原地址>` 取回：按域名补正确 Referer、忽略证书校验、只回传 `image/*`、限 3MB、并拒绝 `file:`/`javascript:` 等非 http(s) 与回环/内网地址（避免本机代理被打内网），结果在进程内缓存 1 小时。

另外 `ac=list` 列表接口常常不带 `vod_pic`（实测 36 条里 15 条没图），所以猜你想搜会用 `ac=detail` 按 `vod_id` 回查一次补海报；仍拿不到的，卡片用 `<img onerror>` 露出 🎬 占位符而不是留白。实测效果：猜你想搜 36 张里 **35 张成功加载**，唯一失败的是那个彻底连不上的图床。

## 自检

```bat
:: 离线：解析、跨源合并、分层排序、目录检索（不联网）
.venv\Scripts\python.exe tests\test_smoke.py

:: 离线：网盘结果解析器（自造 HTML 片段，不联网）
.venv\Scripts\python.exe tests\test_cloudparse.py

:: 离线：猜你想搜归类 / 半年窗口 / SEO 清洗与 robots、sitemap / 分页按钮可点性
.venv\Scripts\python.exe tests\test_seo_hot.py

:: 离线：图片代理的防盗链映射与内网拦截边界
.venv\Scripts\python.exe tests\test_imgproxy.py

:: 离线：后台统计（SQLite 写入/过滤/分页/聚合）与口令登录、限流、注入边界
.venv\Scripts\python.exe tests\test_admin_stats.py

:: 活体：自己起一个临时端口的服务，验证路由 / 网盘查询 / 未回归，跑完自动关闭
.venv\Scripts\python.exe tests\test_cloud_live.py

:: 验收"访问时异步触发更新"（用桩替换真实更新，不真跑几分钟）
.venv\Scripts\python.exe tools\check_autoupdate.py
```

## 目录结构

```
zhuiju/
  app.py            Flask 路由：/、/s/<关键词>、/admin、/api/search|catalog|deeplinks|cloud|detail|health|hot|refresh、/img、/robots.txt、/sitemap.xml
  search.py         并发检索、maccms 响应归一化、跨源片名合并与分层、播放线路解析
  catalog.py        目录检索与直达链接拼装（按文件 mtime 缓存，改数据不用重启）
  cloudsearch.py    网盘 / 磁力站结果页抓取与解析（只收同域、带逐站状态）
  hot.py            猜你想搜（CMS 最新流 + 豆瓣候选回查 + ac=detail 补海报，后台重建、6 小时缓存、按页取）
  seo.py            /s/ 落地页快照、查询记录、robots 与 sitemap
  imgproxy.py       海报代理（补防盗链 Referer、忽略自签证书、拦内网）
  autoupdate.py     访问时触发的后台更新（STEPS 唯一清单、逻辑日、锁文件 + 子进程 PID 判活、进度）
  stats.py          查询统计落 SQLite（过滤/分页/聚合走参数化 SQL；写失败不影响搜索）
  admin.py          后台口令配置读写、口令校验、登录失败限流、反代下取真实客户端 IP
  sources.py        检索源配置读写
  data/
    sources.json    实测可用的检索接口（含站内搜索模板、首页是否可浏览）
    catalog.json    资源站目录（由 tools/build_catalog.py 生成）
    templates.json  已复核通过的各站搜索 URL 模板
    refresh_state.json    最近一次自动更新的结果（页头新鲜度就来自这里）
    refresh_progress.json 后台更新的实时进度（页头进度条与步骤胶囊）
    stats.db        查询统计库（含 -wal/-shm 侧文件；本机隐私，不进版本库）
    admin.json      后台口令与会话签名密钥（明文口令，不进版本库）
    cache/hot.json  猜你想搜缓存   cache/mirror_used.json  这次上游数据实际走的哪个镜像
  templates/index.html, admin.html
  static/app.css, app.js
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
  restart.py            确定性地重启本地站点（先杀干净旧进程，再验证新路由已生效）
  check_autoupdate.py   验收访问触发的异步更新（用桩，不真跑几分钟；七个场景）
tests/
  test_smoke.py         离线：检索解析、合并分层、目录
  test_cloudparse.py    离线：网盘结果解析器（自造 HTML）
  test_seo_hot.py       离线：猜你想搜归类 / 半年窗口 / SEO 清洗与 robots、sitemap
  test_cloud_live.py    活体：临时端口起服务验证路由与查询，跑完自动关
data/upstream/          上游 JSON 缓存（build_catalog.py 自动下载）
zhuiju/data/cache/      运行时缓存：hot.json（猜你想搜）、seo-*.json（/s/ 快照）
zhuiju/data/queries.jsonl  搜过的关键词，供 sitemap 生成
logs/                   更新日志、后台更新记录、服务输出、server.pid
run.py              起服务 + 自动开浏览器（ZHUIJU_NO_BROWSER=1 可关）
启动.bat            一键启动
refresh.bat         一键手动更新
```

## 数据自动更新（访问时触发）

不使用系统计划任务。判据是 `zhuiju/data/refresh_state.json` 里"**当天**有没有成功更新过"，而**"当天"以凌晨 2 点为界**（`ZHUIJU_REFRESH_HOUR` 可改）：

```
01:30 访问  ->  仍属上一个周期，不触发
02:00 访问  ->  新周期开始，当天没跑过才触发
23:00 跑过  ->  次日 01:00 访问不重跑，02:05 访问才会再跑一次
```

按自然日会有两个毛病：凌晨 1 点访问就把"今天"的更新跑掉、2 点后又会再跑一次；反过来 23 点跑过的，次日 00:30 访问会被判成"没更新"而白跑一趟。`tools/refresh.py` 写标记用的是同一个 `logical_day()`，两边口径一致才不会重复触发。

- 打开网站时（请求 `/` 或 `/sitemap.xml`）检查一次，需要更新就**丢一个独立进程**去跑 `tools/refresh.py`，
  请求本身不等待，因此**这次照常返回上一次的数据**。
- 页头横幅按真实情况分六种措辞与颜色，不把"陈旧"说成"失败"：

  | 状态 | 颜色 | 页头显示 |
  |---|---|---|
  | `fresh` | 绿 | `数据 10-15 14:41 自动更新 · 检索源 10/10`，副文案带上游目录版本 |
  | `running` | 黄 | `正在后台更新（第 5/6 步：验证各站搜索路径）` + 进度条 + 六个步骤胶囊 |
  | `partial` | 黄 | `上次只跑了快版（14:41，跳过 deep、merge…）`，提示访问时会补跑全量 |
  | `stale` | 红 | `数据是 2026-10-12 更新的，已过当天周期` |
  | `failed` | 红 | `上次自动更新有步骤失败（health、verify）`，副文案指向 `logs/refresh-*.log` |
  | `never` | 红 | `尚未自动更新过` |

- **进度是实时轮询出来的**：`tools/refresh.py` 每开始/结束一步就把 `done/total/step_label/steps[]/note`
  写进 `zhuiju/data/refresh_progress.json`，页面在 `running` 状态下每 3 秒读 `/api/refresh`，
  更新进度条与步骤胶囊；跑完把横幅变成"数据已更新完成"并给出「刷新页面查看」链接。
  步骤清单只有一份（`autoupdate.STEPS`），`refresh.py` 和页面都从它取，不会两边对不上。
- **"是否在跑"以锁文件里的子进程 PID 为准**，进度文件只补充细节。子进程刚拉起、
  还没写第一个进度文件时页头也已经能说"正在后台更新"；子进程崩了而进度文件还停在
  `running: true` 时，`running()` 用 WinAPI 探活识破并清锁，不会一直谎报进行中。
  进程活着就不受 `LOCK_TTL`（25 分钟）约束——单个步骤最坏 15 分钟，用超时推翻"进程明明还在"
  会多起一个更新进程。
- 锁文件 `logs/autoupdate.lock` 记录子进程 PID；更新进行中重复访问不会再启动第二个。
  今天更新**失败**、或只跑过 `--skip-deep` 快版时，再次访问会重新触发完整一轮。
- 更新写完文件后，站点按 mtime 重新读取，**不用重启服务**就能看到新数据。
- 更新过程逐步写入 `logs/refresh-*.log`（保留 14 份），长跑期间也能看进度。

一次更新做的事：拉上游目录（走 gh-proxy）→ 体检所有检索源并写回 `enabled`/`browsable` →
从 TVBox 配置补抽新接口 → 并入实测可用的 → 双关键词验证各站搜索路径 → 写入模板。
整套约 8 分钟；只想快点走完可加 `--skip-deep`（这种快版不再算"本周期已更新"）。手动执行：双击 `refresh.bat`，
或 `.venv\Scripts\python.exe tools\refresh.py --force`。

### GitHub 数据一律走国内镜像

上游目录与 TVBox 配置都在 GitHub raw 上，直连在国内基本拉不动。`tools/build_catalog.py`
按 `MIRRORS` 顺序试：`gh-proxy.com` → `ghproxy.net` → `ghfast.top` → `mirror.ghproxy.com`
→ 最后才是 `raw.githubusercontent.com`，并把这次真正用到的镜像写进
`zhuiju/data/cache/mirror_used.json`，同时回填到进度里，页头副文案因此能说清
`上游数据源：gh-proxy.com（149889 字节）`。本机 pip 依赖用清华源（见"国内环境准备"）。

注意 `upstream()` 每次都会重新下载，本地文件只当镜像全挂时的兜底——之前"本地有文件就跳过"
让每天的"拉上游目录"实际是个空操作。

验收这套机制：`.venv\Scripts\python.exe tools\check_autoupdate.py`（用桩替换真实更新，
七个场景：不该触发时不触发、该触发时启动、期间仍可搜索、重复访问只起一个、
进程死了要识破、失败后要重试、横幅措辞对得上、进度以子进程存活为准）。
测试的状态/进度/锁文件全在 `.probe/autoupdate_test/`，不会污染真实数据。

## 后台统计（/admin）

打开 http://127.0.0.1:5000/admin ，要口令。

### 口令在哪改

`zhuiju/data/admin.json`：

```json
{
  "password": "你自己改成知道的口令",
  "secret_key": "随机 64 位串，用来签登录 cookie"
}
```

文件不存在时第一次启动会自动生成（`password` 随机），**并在启动控制台打印这一次**；
之后想换，直接编辑 `password` 再重启服务即可，不影响已登录的会话。
也可以用环境变量 `ZHUIJU_ADMIN_PASSWORD` 覆盖，让明文不落盘；`ZHUIJU_SECRET_KEY` 同理。

这个文件和统计库一样进了 `.gitignore`——里面是明文口令，不该提交。

### 统计了什么

每次真正敲上游接口的查询记一条，存 SQLite（`zhuiju/data/stats.db`，标准库 `sqlite3`，无额外依赖）：

| 字段 | 含义 |
|---|---|
| `ts` / `day` | 时间戳与日期（按日期范围筛就用 `day`，含两端） |
| `ip` | 客户端 IP |
| `kw` | 关键词 |
| `via` | `api`=页面搜索 / `seo`=落地页快照 / `cloud`=网盘查询 |
| `results` / `hits` | 合并去重后的条数 / 各源原始命中之和 |
| `sources_ok` / `sources_total` | 本次有多少源真的返回了 |
| `ms` | 这次等了多久 |

页面分六块：汇总卡片（查询次数、独立 IP、独立关键词、零结果及占比、平均可用源、平均耗时）、
按天（点某天=把范围收到那天）、热门关键词、活跃 IP（点 IP=只看这个 IP）、明细表、分页。
筛选表单支持 起始/结束日期、IP、关键词包含、入口、每页 25/50/100/200；
**所有条件都走参数化 SQL，翻页链接会带上当前条件**。

`/s/` 落地页只在**真的建了快照**时才记一条，命中 6 小时缓存的重复打开不计数，
否则同一部剧被反复点开会把"查询次数"灌水。

### 几点设计上的取舍

- **登录失败限流**：同一来源 15 分钟内最多错 8 次，之后返回 429 并提示还需等多久；纯内存，重启清零。
- **CSRF**：登录与退出表单都带一次性 token，登录后立刻换一枚。
- **会话**：`HttpOnly + SameSite=Lax` cookie，8 小时有效。
- **IP 只能采信一次**：只有当直接连过来的那一跳是回环地址（也就是本机 nginx）时才读
  `X-Forwarded-For` 的最左一项，规则与 `TrustForwarded` 完全一致。外部直连时这个头是自己写的，
  采信就等于让访问者随便伪造统计里的来源。写入前还会用 `ipaddress` 解析一次，解析不出的一律丢弃，
  所以这个字段里不会混进换行或任意文本。
- **默认全是 127.0.0.1**：只监听回环时所有记录 IP 都是 127.0.0.1，按 IP 分组没意义；
  要按设备区分得 `--host 0.0.0.0` 或挂反代。
- **统计写不进去也不影响搜索**：`record()` 整个包在 try 里，磁盘满、库被别的过程锁住，
  搜索照常返回。
- **保留期**：默认只留 365 天，更早的记录在初始化时清掉（每小时最多清一次），
  环境变量 `ZHUIJU_STATS_KEEP_DAYS` 可改。
- **不进搜索引擎**：`/robots.txt` 里 `Disallow: /admin`，页面本身也带 `noindex`。
- **公网暴露前请先想清楚**：这个口令是给"同事乱点"设的门槛，不是严格的多人账号体系。
  要放到能被公网访问的地址，至少得配合 HTTPS，并考虑在 nginx 上再加一层基本认证。

验收：`.venv\Scripts\python.exe tests\test_admin_stats.py`（离线，不联网）。统计库和口令文件
都被指到临时目录，不会碰你正在用的那份数据；覆盖口令生成与修改、环境变量覆盖、
写入/过滤/分页/聚合、脏输入与注入串、XFF 采信规则、限流、未登录不泄漏数据、
登录全流程、三个入口的埋点、以及"统计库打不开时搜索仍 200"。

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

## 维护

第三方公开接口随时会失效，失效的源不会静默吞掉结果，页面顶部会标出哪个源挂了（鼠标悬停看原因）。

```bat
:: 日常：体检所有检索源 + 首页可浏览性，只保留能返回片名的
.venv\Scripts\python.exe tools\probe_sources.py 庆余年

:: 目录数据有更新时
.venv\Scripts\python.exe tools\build_catalog.py

:: 想换/加检索源，按这个顺序走一遍
.venv\Scripts\python.exe tools\harvest_apis.py
.venv\Scripts\python.exe tools\test_apis.py
.venv\Scripts\python.exe tools\test_apis_extra.py
.venv\Scripts\python.exe tools\harvest_templates.py
.venv\Scripts\python.exe tools\verify_get_templates.py
.venv\Scripts\python.exe tools\build_templates.py
.venv\Scripts\python.exe tools\probe_sources.py 庆余年
.venv\Scripts\python.exe tests\test_smoke.py
```

脚本产生的中间文件都落在 `.probe/`（可随时删，重跑即可）。浏览器直接访问 `http://127.0.0.1:5000/api/health` 也能看当前源状态。

收录标准只有一条：**本机实测能返回片名才写进配置**，所以 15 个 TVBox 配置里只有 3 个能打开、抽出的 16 个候选接口最后只留 8 个，这是真实数字而不是漏配。

## 国内环境准备

装包和拉取 GitHub 数据都走国内通道，仓库内脚本已按下述方式处理：

- pip 用清华镜像：`-i https://pypi.tuna.tsinghua.edu.cn/simple`（`启动.bat` 已内置）
- 拉取上游 `resources.json` / `README` 等 GitHub raw 文件走 `https://gh-proxy.com/` 前缀，例如
  `curl -L "https://gh-proxy.com/https://raw.githubusercontent.com/laoma528/awesome-zhuiju-free/main/resources/resources.json"`

检索接口本身是国内第三方站点，不需要代理；目录里标了 `GLOBAL` 或"需梯子"的站点是例外。

## 限制与说明

- 采集接口是第三方公益站，稳定性、片源完整度都不受控；某个源挂了直接影响结果数，页面顶部会标出是哪个源，可多试几种关键词写法（只留主标题、去掉"第 X 季"）。
- `tools/probe_sources.py` 只验证"能返回片名"，不验证点开能不能真播。
- **网盘这一类拿不到结果，而且是原理性的限制**：目录里 4 家网盘站（PanSou、夸克搜、追剧吧、谷哥搜）的搜索框是 POST 表单或纯 JS 提交，GET 拼关键词不生效，实测每种变体返回的都是和首页一样的 JS 空壳。考虑过自建 [pansou](https://github.com/fish2018/pansou) 补这块，但它的数据源是 **Telegram 公开频道**——本机网络访问不了 Telegram，所以这条路走不通，已放弃（相关代码也已删除，不留半成品）。
- 「网盘查询」标签页因此只对**搜索页直接返回 HTML** 的站做服务端抓取与解析（庆余年实测 20 站中 2–3 站出结果、约 14–16 条），其余站逐条标注原因并给"打开该站搜索页"入口；只收与搜索页同域的链接，跨域的基本是广告。
- 76 个直达站点里 18 个有已验证的站内搜索路径，其余 58 个退回首页，页面上逐条标注了。
- 8 个检索源里 4 个（虎牙 / 火狐 / 极速 / 光速 / 备番）首页返回 403 或 500，属于只开放 API 的采集站，这类结果不显示"打开站点"，以免跳到拦截页。
- 结果标题带"同系列版本 / 近似名称 / 模糊匹配"标记的，是接口返回的续作、特别版或同名蹭名作品（例如各种"庆余年之××"短剧）；完全同名的正片排在最前。
- 英文片名往往搜不到，这些接口收的是中文片名，请换中文译名（如 Oppenheimer → 奥本海默），无结果时页面也会提示。
- 本工具只做第三方公开接口的聚合查询，不存储、不转发任何影视内容；外链安全性由使用者自行判断。仅供个人技术学习与找片参考，请支持正版。
- **会存查询日志**：`zhuiju/data/stats.db` 里记着"哪个 IP 在什么时候搜了什么词"，另有
  `zhuiju/data/queries.jsonl`（给 sitemap 用）与 `logs/`。这三个文件都只在你的机器上、
  且都进了 `.gitignore`；不想留就把 `stats.db` 删掉，它会自动重建。想彻底不记，
  把 `zhuiju/app.py` 里的 `_record()` 调用注掉即可（统计页会因此变空）。
- 后台统计页 `/admin` 只有一层口令，够挡住乱点的同事，不够当多人账号体系用；
  要挂到能被公网访问的地址，先配合 HTTPS，并考虑在 nginx 上再加一层基本认证（见"后台统计"一节）。
