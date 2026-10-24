# 前端：React 19 + HeroUI v3，Flask 只出 API 和一个壳

这一篇说清楚四件事：界面在哪儿、怎么改、主题怎么生效、以及**为什么爬虫和禁用 JS
的人还能看到内容**。改后台（`/admin`）的样式请看文末那一节 —— 它仍是 Jinja，但用的是同一套令牌。

## 分工：谁产 HTML，谁产数据

```
Flask (zhuiju/app.py)  ──JSON──▶  /api/*  ──▶  web/src (React 19 + HeroUI v3)
        │                                            │
        └── 一个 HTML 壳 templates/shell.html ◀──构建产物 zhuiju/static/spa/{app.js,app.css}
```

- **Flask 不再画界面。** `GET /` 与 `GET /s/<关键词>` 渲染的 `shell.html` 里只有一个
  `#app` 挂载点、一份 `<script id="boot-data">` 首屏数据、一行 SEO 元信息，其余全是 React 的。
- **所有数据都走 `/api/*`**，字段契约在 `web/src/types.ts` 里逐条写着（`snake_case`，
  跟 Python 那边一模一样，前端不改名 —— 改了名出问题时两边对不上号是最难查的）。
- **构建产物提交进仓库**（`zhuiju/static/spa/`）。部署那台机器**不需要装 Node**，
  `python run.py` 照旧；只有真要改界面时才需要过一次构建。

## 改界面

```bash
cd web
npm install            # .npmrc 里默认 npmmirror，国内直接通；要官方源就 --registry 覆盖
npm run check          # tsc --noEmit，先看类型
npm run build          # 产出 ../zhuiju/static/spa/app.js 与 app.css
```

开发时 `npm run dev` 起 5173，`/api`、`/img`、`/s` 全部代理到本站 5000
（`ZHUIJU_PORT` 改过就同步改 `web/vite.config.ts` 里的 `BACKEND`），所以那是真数据、真门禁。

产物文件名是**故意写死**成 `app.js` / `app.css` 的（`rollupOptions.output` 里配的），
这样壳里能直接 `?v={{ asset_v }}` 复用原来那枚「按 `static/` 一级子项 mtime 取最大值」的
版本号，不必再引一份 manifest 去读哈希名。

体积：`app.js` 128 KB / gzip 40 KB，`app.css` 458 KB / gzip 44 KB，`admin.js` 173 KB。大头是
React 19 + React Aria（HeroUI v3 的可访问性是它给的）。局域网/本机加载这点量无所谓，
但它意味着**一件不能踩的事：不要把它扔到公网 CDN** —— 站点常年跑在没有外网出口的机器上。

浏览器基线是 Vite 默认的 baseline-widely-available（ES modules + ES2020），
所以太老的内核跑不了界面 —— 老浏览器仍然能拿到 `#nojs` 那份服务端渲染的结果。

## SEO 与无 JS：壳里那份「同一数据、两种出口」

`shell.html` 的 `<head>` 里是完整的 SEO：`title` / `description` / `canonical` / `og:` /
`robots` / JSON-LD（有词 = `ItemList`，无词 = `WebSite` + `SearchAction`），
和 React 在客户端 `syncSeo()` 改的是同一套形状。

`<body>` 里有两块，靠 `<html class="js">` 这一个开关互斥：

| 谁 | 看到 |
| --- | --- |
| 真人（浏览器执行 JS） | `#app` 里的 React 界面，`#nojs` 被 CSS 藏掉 |
| 禁用 JS 的人 / 只取 HTML 的抓取器 | `#nojs`：一个 `method=get` 的搜索表单 + 服务端渲染的结果列表 |

`/?kw=…` 仍然 302 到 `/s/<kw>`，所以禁 JS 那条路和 JS 那条路落到**同一个地址**，
`canonical` 不会分叉。

**门禁优先于这一切**：`_human_gate` 判定未验证时，同一个壳以 `boot.locked=true` 下发，
`#nojs` 那一块**整个不渲染**，快照与榜单一个字段都不给，界面上只剩一块滑块。
爬虫豁免（UA + 反查 DNS 落到官方域名后缀）走的是 unlocked 那条路，
所以它拿到的仍是服务端渲染的真内容 —— 见 [human.md](human.md)。

## 主题：三态，存在 localStorage，首帧就定色

- 值：`system` / `light` / `dark`，键 **`heroui-theme`**，由 HeroUI 的 `useTheme` 读写，
  它会把 `<html>` 的 `class` 和 `data-theme` 一起写上。
- 防闪白：`shell.html` 里那段**内联**脚本在样式之前跑，读同一个键、写同一对属性。
  不能改成外链或 `defer`（要多一次网络往返就来不及了）。完全禁用 JS 时拿不到系统偏好，
  会固定亮色 —— 那时本来也没有界面，划算。
- 切换是渐变的，但过渡只在切换那 ~380ms 里临时挂 `.theme-anim` 再摘掉；
  写成常驻的 `* { transition }` 会把 hover 拖慢、长列表掉帧。
  `prefers-reduced-motion: reduce` 下不渐变，海报淡入与「猜你想搜」的平滑滚动也一起关掉。
- 反馈：切完用 HeroUI 的 `toast` 报一声「已保存 · 暗色」；写不进 localStorage（无痕）
  就直说「这台浏览器不给存，这次生效、关掉就忘」。
- 覆盖点只有两处，都在 `web/src/styles.css`：
  `--accent: oklch(0.578 0.186 262.1)`（比默认靛蓝压深一档，白字压在上面才够对比度），
  以及 `@custom-variant dark (&:where(.dark, .dark *))` —— Tailwind v4 的 `dark:` 默认问
  `prefers-color-scheme`，而 HeroUI 的主题块认的是 `.dark` / `[data-theme="dark"]`；
  「系统暗但手动强制亮」时两者会分家，所以把变体也改成问同一个属性。
- HeroUI v3 是 CSS-first：`@import "tailwindcss";` 之后 `@import "@heroui/styles";`
  （**顺序反了不报错，只是样式会歪**），没有 `tailwind.config.js`，也没有 Provider 要包。

版式约定：按钮/输入一律 `rounded-full` 药丸；数据字段（命中数、耗时、条数、页码）
一律 `.num`（等宽 + `tabular-nums`）；**前台与后台统一收在 `max-w-[1680px]`**，边距随屏给
（`px-4 sm:px-6`），超宽屏不再各用一档。
搜索那一屏 ≥1280px（`xl`）时两栏（左结果、右资料栏粘性跟随），窄屏 `<aside>` 拆成两块
跟着结果依次排在后面：接口状态在前、《xxx》的检索结果在后 —— 两块默认都折起只占一行
标题，不再把结果顶出半屏（`order-first` 那个写法就是这么闯的祸，别写回去）。

那份「《X》的检索结果」是**服务端为该关键词存的快照**（搜索引擎与禁用 JS 时看到的都是它）。
直开 `/s/<关键词>` 时它随 boot 一起下发；SPA 里换词不刷新整页，则由 `/api/search` 第一页
捎回同一份快照 —— 服务端拿刚跑完的那一页结果裁一份写盘，不为同一批片再并发查一遍所有源，
随后直开 `/s/` 还能直接命中。前端只认 `snapshot.kw === kw`，切词后不会把上一个词的摘要留着。
快照在窄屏默认折叠，展开后固定 6 行、框内滚动：
高度量第 7 条 `li` 的 `offsetTop`，不写死像素（行高会随折行变化），再加上
`offsetHeight - clientHeight` 补偿滚动条占掉的宽度与高度。首次测量必须**同步**跑 ——
rAF 在后台标签里可能压根不回调，限高就会静默失效；宽度变化由 `ResizeObserver`、内容变化由
`MutationObserver` 重算（同一个 `useClamp` 也供后台表格用）。

## 后台：同一个工程里的第二个入口

`/admin` 与 `/admin/password` 也是 React + HeroUI 了，但它是**同一个 `web/` 工程里的另一个入口**：

```
web/src/main.tsx   ─▶ spa/app.js    ─▶ templates/shell.html        （前台）
web/src/admin.tsx  ─▶ spa/admin.js  ─▶ templates/admin_shell.html  （后台）
                     两个入口共用 spa/app.css（cssCodeSplit=false）
```

数据一律走 `GET /api/admin/view`（带当前查询串，返回这一屏要的全部），底图那 230KB 路径单独走
`GET /api/admin/map` 让浏览器缓存住。写操作还是 POST 到原来的 `/admin/...` 路径：
请求体是 **`application/x-www-form-urlencoded`**（后端读的是 `request.form`），
带 `X-Requested-With: fetch` 或 `Accept: application/json` 时回 JSON，否则回老的重定向 ——
同一套处理函数服务两种客户端，靠 `_wants_json()` 分叉。

### 三条要紧的口径

1. **tab 只决定哪几块上屏，不改任何统计口径** —— 但 `_admin_ctx()` 现在**按标签算贵的那几块**：
   STRM 的 `manifest()` + `status()` 要 3.5 秒（在近一年的 strm.db 上聚合），底图 230KB。
   整页模板时代没人察觉（每次都是整页刷新），换成 SPA 之后"点一下设置等五秒"就是故障，
   所以 `want_strm` / `want_map` 之外一律不算。改这块时别把这两个开关拿掉。
2. **过场要有指示**：换标签/换筛选时旧内容留着，顶上那根 `.bar-run` 说"在取新的"。
   STRM 那一屏 3.7 秒，没这句话看着就是卡死。条外面那个 3px 的槽位**常驻**，
   只在取数时往槽里放条：不占位的话，这根条一出现就把 sticky header 撑高 3px，
   下面整页跟着往下跳一下，表格正读着的时候尤其明显。
3. **口令的边界**：`/api/admin/view` 未登录回 401，body 里只有 `authed:false` + `csrf` +
   三个口令页要用的标志位，**一个统计字段都不下发**。`admin.html` 现在只剩一个用途 ——
   禁用 JS 的人提交登录表单时的兜底页（`_login_page` 在客户端不要 JSON 时才渲染它），
   `admin_password.html` 同理。所以 `static/app.css`、`theme.js`、`_theme.html` 这三份还活着，
   但只服务那一页；后台主体样式全在 HeroUI 令牌上。

### 顺带两条会咬人的

- **`setfields` 在 JSON 里必须是对象。** `settings.fields()` 返回 `(key, spec, value)` 三元组，
  Jinja 那边直接解包用，过 JSON 就成了数组 —— React 按 `f.spec.label` 读会拿到 undefined，
  整棵后台白屏。`_admin_ctx()` 里已经摊平成 `{key, spec, value}`，别再退回直接塞元组。
- **`--surface: var(--surface)` 这种自引用不能写**（HeroUI 自己那一档就叫 `--surface`，
  会被判成循环、变量整个空掉）；Tailwind v4 会把没用到的主题变量从产物里剔掉，
  所以 `--radius-md` 之类**不存在**，圆角要写死 px。`static/app.css` 那份桥接层已经踩过这两条。
- 把"跟随系统"解析成具体颜色时必须直接问 `matchMedia`，不能经由读 localStorage 的那条路 ——
  写存储发生在解析之后，用旧值解析的结果就是"按钮说亮色、页面还黑着"（`theme.js` 里踩过）。

MDUI 已经完全退出。被替换掉但还在盘上的死文件（Flask 不再渲染，确认后可以直接删）：
`templates/index.html`、`templates/human.html`、`templates/_slider.html`、
`static/app.js`、`static/slider.js`、`static/vendor/mdui/`、`tools/vendor_mdui.py`。

## 几个踩过或差点踩的坑

1. **HeroUI 的 `Tabs` 只挂载当前面板**。所以各标签页的数据必须存在 `App` 里而不是面板组件里，
   否则切回来就重新发一遍请求（「网盘查询」那一轮要十几秒）。
2. **`SearchField` 的受控值是挂在 root 上**，不是挂在 `SearchField.Input` 上；
   `Label` / `Description` / `FieldError` 是独立导出，不是 `TextField.Label`。
3. **`Button` 没有 `title` 属性**（它不是原生 button 的透传），想要悬浮说明就包 `Tooltip`。
4. **`useTheme` 只写 `<html>`**，画布背景得自己接上：`body { background: var(--background) }`。
   只在根 div 上写 `bg-background`，橡皮筋滚动和 React 挂载前那一瞬间都会露白。
5. **详情是 `Drawer`，不是常驻面板**。旧的「点面板外面收起」「点换源不该关」这两条行为
   在 React 里天然成立（换源只改 state、不重挂 DOM），但 `isDismissable` 要保持默认 true。
6. **滑块几何必须现量**：轨道宽度用 `ResizeObserver` 测，缺口按像素算；写死一个数，
   窄屏就会「明明对准了却说不匹配」。提交时长要在清 `down` 之前算好，晚一步就永远上报 0ms。
7. **海报必须过 `/img`**（`posterOf()`）：上游图床有防盗链，直接贴外链一定是裂的；
   而且 `/img` 只代理服务端登记过的地址，所以 `search`/`hot` 那条路径两边都要先 `register`。
