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

后台统计在 <http://127.0.0.1:5000/admin>。**第一次进去会直接领你把口令改成自己定的**
（那时用的还是首次启动随机生成、只在控制台打印过一次的那个），保存即写回
`zhuiju/data/admin.json` 并生效，不用重启。详见"后台统计"一节。

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

:: 离线：后台统计（SQLite 写入/过滤/分页/聚合）、IP 归属地与地图点位、
::         口令登录、首次改口令、限流、注入边界、老库升级回填
.venv\Scripts\python.exe tests\test_admin_stats.py

:: 离线：浏览器识别与来源页判定、爬虫分离、主题（调色板完整性与页面接线）
.venv\Scripts\python.exe tests\test_agent_theme.py

:: 离线：跨平台部署路径（解释器现找、zhuiju.env 解析、refresh.sh 行尾、Linux 的 /proc 解析）
.venv\Scripts\python.exe tests\test_deploy_paths.py

:: 活体：自己起一个临时端口的服务，验证路由 / 网盘查询 / 未回归，跑完自动关闭
.venv\Scripts\python.exe tests\test_cloud_live.py

:: 验收"访问时异步触发更新"（用桩替换真实更新，不真跑几分钟）
.venv\Scripts\python.exe tools\check_autoupdate.py
```

Linux 上把 `.venv\Scripts\python.exe` 换成 `<你的venv>/bin/python`（宝塔见"部署到 Linux"一节），
`\` 换成 `/`。上面的测试都不依赖 shell 命令，两边结果一致。

## 目录结构

```
zhuiju/
  app.py            Flask 路由：/、/s/<关键词>、/admin、/admin/password、/api/search|catalog|deeplinks|cloud|detail|health|hot|refresh、/img、/robots.txt、/sitemap.xml
  search.py         并发检索、maccms 响应归一化、跨源片名合并与分层、播放线路解析
  catalog.py        目录检索与直达链接拼装（按文件 mtime 缓存，改数据不用重启）
  cloudsearch.py    网盘 / 磁力站结果页抓取与解析（只收同域、带逐站状态）
  hot.py            猜你想搜（CMS 最新流 + 豆瓣候选回查 + ac=detail 补海报，后台重建、6 小时缓存、按页取）
  seo.py            /s/ 落地页快照、查询记录、robots 与 sitemap
  imgproxy.py       海报代理（补防盗链 Referer、忽略自签证书、拦内网）
  __init__.py       包导入时读 zhuiju.env（venv 在站点外面时在那儿指一次，处处都认）
  autoupdate.py     访问时触发的后台更新（STEPS 唯一清单、逻辑日、锁文件 + 子进程 PID 判活、
                    进度、解释器现找 python_bin()、失败冷却 ZHUIJU_RETRY_MINUTES）
  stats.py          查询统计落 SQLite（过滤/分页/聚合走参数化 SQL；写失败不影响搜索）
  geoip.py          离线 IP 归属地：纯标准库读 ip2region xdb + 国家轮廓转内嵌 SVG 路径
  agent.py          User-Agent 识别（浏览器/系统/设备/爬虫）与 Referer 来源判定，纯标准库
  admin.py          后台口令配置读写、口令校验、首次登录判断、登录失败限流、反代下取真实客户端 IP
  sources.py        检索源配置读写
  data/
    sources.json    实测可用的检索接口（含站内搜索模板、首页是否可浏览）
    catalog.json    资源站目录（由 tools/build_catalog.py 生成）
    templates.json  已复核通过的各站搜索 URL 模板
    refresh_state.json    最近一次自动更新的结果（页头新鲜度就来自这里）
    refresh_progress.json 后台更新的实时进度（页头进度条与步骤胶囊）
    stats.db        查询统计库（含 -wal/-shm 侧文件；本机隐私，不进版本库）
    admin.json      后台口令、会话签名密钥、是否还是首次生成的随机口令（明文口令，不进版本库）
    cache/hot.json  猜你想搜缓存   cache/mirror_used.json  这次上游数据实际走的哪个镜像
  templates/index.html, admin.html, admin_password.html, _theme.html
  static/app.css, app.js, theme.js
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
                        --check-env 只报告"会用哪个解释器、依赖齐不齐"，部署排查用
  fetch_geo.py          下载 IP 归属地库与国家轮廓底图，算好 country_points.json（走 gh-proxy）
  restart.py            确定性地重启本地站点（先杀干净旧进程，再验证新路由已生效）
                        Windows 走 WinAPI，Linux 走 /proc（非 root 时只能按 server.pid 收尾）
  check_autoupdate.py   验收访问触发的异步更新（用桩，不真跑几分钟；九个场景）
tests/
  test_smoke.py         离线：检索解析、合并分层、目录
  test_cloudparse.py    离线：网盘结果解析器（自造 HTML）
  test_seo_hot.py       离线：猜你想搜归类 / 半年窗口 / SEO 清洗与 robots、sitemap
  test_cloud_live.py    活体：临时端口起服务验证路由与查询，跑完自动关
  test_deploy_paths.py  离线：跨平台部署路径（解释器现找、zhuiju.env、refresh.sh 行尾、/proc 解析）
data/upstream/          上游 JSON 缓存（build_catalog.py 自动下载）
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
  今天更新**失败**、或只跑过 `--skip-deep` 快版时，再次访问会重新触发完整一轮——
  但失败的要等冷却过去：一轮刚失败（状态里有 `finished_at`）后的 `ZHUIJU_RETRY_MINUTES`
  （默认 15）分钟内不再自动重跑。失败大多是环境性的（解释器不对、依赖没装、出网被挡），
  这种时候只要有人访问就重跑一遍注定失败的六步，等于每分钟敲一次第三方接口并灌满 `logs/`。
  冷却对"读不出 `finished_at` 的老状态文件"不算数（不猜，直接允许重试）。
- 更新写完文件后，站点按 mtime 重新读取，**不用重启服务**就能看到新数据。
- 更新过程逐步写入 `logs/refresh-*.log`（保留 14 份），长跑期间也能看进度。日志开头两行
  写明了**跑各步骤用的解释器以及选它的理由**——"六步全挂且 `seconds` 只有 0.1"这种就一眼能看出来。

一次更新做的事：拉上游目录（走 gh-proxy）→ 体检所有检索源并写回 `enabled`/`browsable` →
从 TVBox 配置补抽新接口 → 并入实测可用的 → 双关键词验证各站搜索路径 → 写入模板。
整套约 8 分钟；只想快点走完可加 `--skip-deep`（这种快版不再算"本周期已更新"）。手动执行：
Windows 双击 `refresh.bat`，或 `.venv\Scripts\python.exe tools\refresh.py --force`；
Linux 用 `sh refresh.sh --force`。想先确认环境对不对，加 `--check-env`（只报解释器和依赖，不跑）。

跑之前有一道 preflight：解释器不存在、或者里面没装 `flask/requests`，就直接把这句话写进状态
和日志并结束（`failed_steps: ["env"]`），不会让六个步骤各抛一遍 `Exec format error`。

### GitHub 数据一律走国内镜像

上游目录与 TVBox 配置都在 GitHub raw 上，直连在国内基本拉不动。`tools/build_catalog.py`
按 `MIRRORS` 顺序试：`gh-proxy.com` → `ghproxy.net` → `ghfast.top` → `mirror.ghproxy.com`
→ 最后才是 `raw.githubusercontent.com`，并把这次真正用到的镜像写进
`zhuiju/data/cache/mirror_used.json`，同时回填到进度里，页头副文案因此能说清
`上游数据源：gh-proxy.com（149889 字节）`。本机 pip 依赖用清华源（见"国内环境准备"）。

注意 `upstream()` 每次都会重新下载，本地文件只当镜像全挂时的兜底——之前"本地有文件就跳过"
让每天的"拉上游目录"实际是个空操作。

验收这套机制：`.venv\Scripts\python.exe tools\check_autoupdate.py`（用桩替换真实更新，
九个场景：不该触发时不触发、该触发时启动、期间仍可搜索、重复访问只起一个、
进程死了要识破、失败后要重试、横幅措辞对得上、进度以子进程存活为准、
**失败冷却期内不重跑**、**解释器是现找的**）。
测试的状态/进度/锁文件全在 `.probe/autoupdate_test/`，不会污染真实数据。

跨平台那部分另有 `.venv\Scripts\python.exe tests\test_deploy_paths.py`：在 Windows 上把
`is_windows()` 换成假值来验 Linux 的候选顺序，再造一棵假 `/proc` 验端口归属的解析
（真 `/proc` 和 socket 软链接在 Windows 上造不出来，不注入就没法测——这条测试确实抓出过一次
"参数写了但函数里没用它"的错）。

## 后台统计（/admin）

打开 http://127.0.0.1:5000/admin ，要口令。

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
| `iso` / `country` / `geo` | 国家码、国家名、完整归属地文案；内网/保留地址的 `iso` 是空串 |
| `browser` / `os` / `device` | 从 User-Agent 认出的浏览器+版本、系统、手机/平板/桌面/程序 |
| `bot` | 1=爬虫或脚本客户端（curl、requests、Googlebot…），与真人分开数 |
| `ua` | 原始 UA（截断 200 字节），认错了要能回查 |
| `ref` / `ref_kind` / `ref_label` | 来源：站内是完整路径，站外只有域名；类型 `site`/`search`/`out`/`direct`/`other` |

### 浏览器识别

只用标准库认，没引第三方 UA 库（清华源上有 `ua-parser` 之类但没必要为这一列多加依赖）。
覆盖 Chrome / Edge / Opera / Firefox / Safari / IE / 三星 / Vivaldi / Electron，
以及国内常见的微信内置、QQ浏览器、UC、夸克、360、搜狗，外加爬虫与命令行客户端。
**顺序是关键**：Edge、Opera、微信的 UA 里同时带 `Chrome/xxx` 和 `Safari/604.1`，
先判 Chrome 就会把它们全认成 Chrome；Safari 那条也因为这个必须排在最后。
iPad 的 UA 里带 `Mobile/15E148`（苹果为兼容老站点留的历史标记），所以不能靠有没有
`Mobile` 来区分手机和平板，iPad 要单独认。

要当它是"大致构成"而不是精确计数：UA 由客户端自己写，可以随便伪造；国产壳浏览器
（360、搜狗、各家双核）也经常不自报身份，认不出就写"未知"，不猜。

### 来源页（对方从哪来）

取自 `Referer` 头。**能给多少由浏览器的 Referrer-Policy 决定，不是我们能控制的**，
默认策略 `strict-origin-when-cross-origin` 的实际行为是：

| 场景 | 浏览器给什么 | 这一列显示 |
|---|---|---|
| 站内跳转（同源） | **完整 URL** | `站内 /s/庆余年`（能看到上一页具体是哪部剧） |
| 跨站跳转 | 只给 `协议://域名` | `https://movie.douban.com`（路径被抹掉，拿不到就不编） |
| 搜索引擎点进来 | 只给域名，但查询词在 URL 参数里 | `百度 搜索「春风烈马」进来` |
| https → http | 什么都不发 | 归到"直接访问" |
| 手输地址 / 书签 / 新标签页 | 什么都不发 | `直接访问 / 无来源` |

所以"直接访问"那一类里混着好几种情况，分不开就不硬分。这个头同样可伪造。
站内判定用的是 `request.host` + 去端口主机名 + `127.0.0.1` + `localhost` 一组口径；
`localhost` 和 `127.0.0.1` 在浏览器眼里是两个不同 origin，只有都登记成本机地址时才算站内。
搜索引荐认 Google / 必应 / 百度 / 搜狗 / 360 / 神马 / DuckDuckGo / Yandex / Yahoo，
各家参数名不同（`q` / `wd` / `query` / `p` / `text`）。

历史行在这两批列加上之前是没有数据的，页面显示"未知 / 未解析"，不做任何猜测性回填
（归属地可以凭 IP 事后算，UA 和 Referer 是当时那一个请求才有的信息，错过就没了）。

### 主题（亮 / 暗 / 跟随系统）

标题旁的按钮点一下在 **跟随系统 → 亮色 → 暗色** 之间循环，选择记在 `localStorage`，
两个页面（首页与后台）都有。默认是"跟随系统"，选"跟随系统"时还监听系统配色变化，
切了立刻跟着变。

实现上有两点值得记：

- 调色板**只靠自定义属性**：先把散在规则里的 24 处写死浅色值抽成语义变量
  （`--ok-bg`、`--bad-line`、`--sea`、`--on-accent` …），亮色取值一字未改，
  然后 `[data-theme="dark"]` 里整组覆盖一遍并声明 `color-scheme: dark`
  （表单控件、滚动条、原生日期选择器才会跟着变）。加新组件时只要用变量写颜色，
  两套主题就自动都成立。
- 主题必须在样式表加载前就定下来，否则暗色用户每次刷新都会闪一下白。
  所以 `templates/_theme.html` 是**内联**在 `<head>` 里的读值脚本，不能改成 `defer`
  或外链（那样要等一次网络往返）。副作用是完全禁用 JS 时拿不到系统偏好，
  会固定在亮色——这个站点去掉 JS 本来就没有搜索界面，所以是笔划算的取舍。
- 切换是**渐变**的，但过渡只在切换那 0.34s 里临时挂一个 `.theme-anim` 类，之后立刻摘掉。
  写成常驻的 `* { transition: … }` 会把 hover/focus 原有的短过渡全拖成 300ms，
  长表格里滚动还会掉帧。`prefers-reduced-motion: reduce` 时完全不渐变。
  首屏不走这条路径（由预置脚本直接定色），所以打开页面时不会先闪一遍。

### 配色体检

`tests/test_agent_theme.py` 第 8 节直接把 CSS 调色板里的颜色配对算 WCAG 对比度
（`--on-accent`/`--brand`、`--dim`/`--surface`、`--ok`/`--ok-bg` 等九对，亮暗各算一遍），
低于 4.5 就报错。它是查出来的第一批问题：

| 位置 | 原来 | 现在 |
|---|---|---|
| 主按钮（搜索/筛选/进入） | 蓝底上写红字（`color: var(--bad)`，一次批量替换的失误） | 白字，5.01 |
| 次级文字 `--dim` | 2.98，11–12px 的小字基本看不清 | 4.77 |
| 成功 / 警告 / 失败文字 | 3.31 / 3.32 / 4.16 | 5.41 / 5.25 / 4.79 |

`.gobtn`、`.reset`、`.pbtn`、`.pager a`、`.jumpbtn`、`.themebtn`、`.fbtn`
原本是七份几乎一样的规则（各写一遍圆角和 hover），现在合并成一条，
圆角与输入框统一（胶囊 99px、按钮 8px），次级动作一律淡底 + 悬停转品牌色，
不再用红色暗示"危险"（清空筛选不是删库）。输入框背景从 `--surface` 换成 `--surface-2`，
在白卡片上才有边界。

### IP 归属地与世界地图

**要先下数据**（约 14MB，走 gh-proxy 镜像，一次性的）：

```bat
.venv\Scripts\python.exe tools\fetch_geo.py
```

没下也不影响使用：归属地列会显示"未下载归属地库"，地图那一块给出上面这条命令。

| 文件（都在 `data/geo/`，已 gitignore） | 大小 | 用途 |
|---|---|---|
| `ip2region_v4.xdb` | 10.6MB | IP → `国家\|省\|市\|ISP\|ISO`，55 万网段 |
| `ne_110m.geo.json` | 0.8MB | 画地图的国家轮廓 |
| `ne_50m.geo.json` | 2.9MB | 只用来算国家坐标（110m 缺新加坡、马耳他等小城邦） |
| `country_points.json` | 几十 KB | 算好的 ISO → 经纬度，246 个国家 |

解析完全**离线**、只用标准库：实测清华源上没有 `ip2region` 这个包，而 xdb 格式本身很简单，
自己读（`zhuiju/geoip.py`）反而少一个依赖，也不用把访客 IP 交给任何第三方接口。
查询算法对着 20 个已知 IP 验过（1.1.1.1→AU、223.5.5.5→中国浙江杭州、8.8.8.8→US 等）。
`tools/fetch_geo.py` 每次跑完还会报告"库里的国家码有几个在坐标表里找不到"，当前是 0。

地图是**内嵌 SVG**，不引 Leaflet、不接瓦片服务：那要连境外 CDN（这台机器上不可靠），
而且等于把访客 IP 泄露给第三方。投影用等距圆柱（`viewBox="0 0 360 180"`，`x=经度+180`、
`y=90-纬度`），轮廓路径来自 110m（约 115KB，精度取 0.1°，肉眼看不出但体积小一半），
**有查询记录的国家会被单独描色**，圆点半径按 `sqrt(次数)` 缩放（面积才与数量成正比，
线性放大半径会让大国糊满整张图）。点圆点或表格里的国家名 = 只看这个国家的查询。

国家坐标按"最大那个多边形的面积加权形心"算，不是所有点取平均：俄罗斯、美国、澳大利亚
这种带飞地/跨半球的国家，平均点会被拖到海上去。踩过的坑：澳属外部领地（Ashmore and Cartier
Islands 之类）的 `ISO_A2_EH` 也是 `AU`，按写入顺序会让澳大利亚的点落到海里那块小岛上——
所以同一个国家码只保留**面积最大**的那个要素，结果与遍历顺序无关。

不属于公网的地址**不上图**，也不去查库，按语义分开标注：`本机`（127.x/::1）、
`内网`（10.x、192.168.x、172.16-31.x）、`保留地址`（组播、链路本地、CGNAT 100.64/10、
基准测试 198.18/15，以及 203.0.113.x 这类文档用例段）。这里有个容易忽略的细节：
Python 3.13 把文档用例段也算进 `is_private`，若先判 private 就会把 TEST-NET 说成"内网"，
所以判定顺序是先排除保留段、再判内网。

统计页因此默认只会有"本机/内网"一行——服务只听 127.0.0.1 时本来就该如此，
地图上有国家分布的前提是 `--host 0.0.0.0` 或挂 nginx 反代（后者才会认真读 X-Forwarded-For）。

页面还会多一块「国家 / 地区」表（国家名 / 次数 / 独立 IP / 关键词数 / 最近日期）。**这一列只显示国家名**（库里的 `country` 列：中国 / Australia / United States），省市与运营商只在明细行的完整文案里出现——早先拿整条 `geo` 文案当分组标签，列表里就会冒出「中国 浙江省杭州市 · 阿里」这种地区级内容，看着像分组错了，
筛选表单多一个「国家码」输入框，填 `--` 就是筛内网与保留地址。
老库升级时会自动补 `iso`/`geo` 两列并把历史记录回填一遍，之后不再重算。


内容宽度按屏走：`min(1680px, 100% - 48px)`，1366 / 1600 / 1920 的 16:9 屏上分别占 95% / 96% / 88%，
超宽双屏靠 1680px 上限挡住，不至于把一行表格拉到没边。猜你想搜的列数也跟着屏走：
≥1500px 9 列、1240–1499px 7 列、默认 6 列，窄屏再降到 5/4/3/2。

页面分八块：汇总卡片（查询次数、独立 IP、独立关键词、零结果及占比、平均可用源、平均耗时）、
按天（点某天=把范围收到那天）、热门关键词、活跃 IP（点 IP=只看这个 IP）、
浏览器/设备、来源页、明细表、
**IP 归属地地图（放最底下，日常翻明细用不上，不占首屏）**。
筛选表单支持 起始/结束日期、IP、国家码（填 `--` 就是内网/保留）、关键词包含、入口、每页 25/50/100/200；
**所有条件都走参数化 SQL，翻页链接会带上当前条件**。

明细翻页不整页重载：点上一页/下一页或在「跳到 __ 页」里输页码，只重新拉取并替换 `#detail`
这一块（`fetch` + `DOMParser`），地址栏用 `history.replaceState` 同步。没 JS 时这些链接与表单
仍是普通 GET 请求，功能不坏，只是会回到页顶。页码输入框带 `min/max`，越界会被夹到首页/末页
（前后端各夹一次）。
**页面一步都不滚**：明细自己就是个固定高度的滚动框（见下），换进来的是全新的框元素、
`scrollTop` 天生是 0，新页自然从第一行开始，外面原来停在哪儿就还停在哪儿。早先这里做过一次
「翻页后把明细滚回视野里」的定位（`scrollIntoView` + `#detail { scroll-margin-top }`），当时明细
整块摊在页面上，翻一页就得重新滚下来；现在框内滚动，这个定位反而会把人甩到别处，所以整段删掉了。

每块表都固定在自己的高度里滚，而不是把整页拉长：热门关键词 / 活跃 IP / 浏览器·设备 / 来源页 /
国家·地区 只露 **5 行**，明细只露 **10 行**，剩下的在框内用滚动条看（`.fold { overflow: auto }`，
没有展开/收起按钮）。三个不显然的点：

- **框高不是写死的像素。** 行高会随折行变化（来源格、浏览器格经常换行），写死就露半行，
  所以由脚本量第 N+1 行的 `offsetTop` 来定，且**设完高度再量一次**：竖向滚动条占掉宽度会让行
  重新折行，横向滚动条占掉高度会把最后一行压在上面，两笔都得补偿。行数不足 N 时不设高度，
  也不会有滚动条（`scrollHeight == clientHeight`）。窗口宽度变了防抖 200ms 重算。
- **框内滚动时表头吸顶**（`position: sticky`），分隔线用 `inset box-shadow` 而不是 `border-bottom`：
  表格是 `border-collapse: collapse`，吸顶的 `th` 在 Chrome 里画不出被折叠掉的那条边框，
  滚动时表头会和内容粘成一片。
- 滚动条收成 8px 细条、颜色走 `var(--line)`，暗色下不会是一道白槽；明细换页后调 `refold()`
  重算，否则新一页行数不同高度就对不上。

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
- **统计写入失败不影响搜索**：`record()` 整个包在 try 里。但这也意味着"库结构升级失败"
  会表现为"归属地一直是空的"而没有任何提示，所以 `ensure_schema()` 的出错原因记在
  `stats.MIGRATE_ERROR` 里，统计页顶部会直接显示出来。
- **归属地不联网**：解析全在本地 xdb 里完成，不会把访客 IP 发给任何第三方接口或地图瓦片服务。
- **公网暴露前请先想清楚**：这个口令是给"同事乱点"设的门槛，不是严格的多人账号体系。
  要放到能被公网访问的地址，至少得配合 HTTPS，并考虑在 nginx 上再加一层基本认证。

验收：`.venv\Scripts\python.exe tests\test_admin_stats.py`（离线，不联网）。统计库和口令文件
都被指到临时目录，不会碰你正在用的那份数据；覆盖口令生成与修改、环境变量覆盖、
写入/过滤/分页/聚合、脏输入与注入串、XFF 采信规则、限流、未登录不泄漏数据、
登录全流程、三个入口的埋点、以及"统计库打不开时搜索仍 200"。

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
- **会存查询日志**：`zhuiju/data/stats.db` 里记着"哪个 IP、用什么浏览器和系统、从哪个页面来、
  在什么时候搜了什么词"，另有
  `zhuiju/data/queries.jsonl`（给 sitemap 用）与 `logs/`。这三个文件都只在你的机器上、
  且都进了 `.gitignore`；不想留就把 `stats.db` 删掉，它会自动重建。想彻底不记，
  把 `zhuiju/app.py` 里的 `_record()` 调用注掉即可（统计页会因此变空）。
- 后台统计页 `/admin` 只有一层口令，够挡住乱点的同事，不够当多人账号体系用；
  要挂到能被公网访问的地址，先配合 HTTPS，并考虑在 nginx 上再加一层基本认证（见"后台统计"一节）。
