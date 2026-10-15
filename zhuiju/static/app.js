/* 追剧资源搜索 — 前端逻辑 */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const form = $('form'), input = $('kw'), goBtn = $('go');
  const statline = $('statline'), meta = $('meta'), srcbar = $('sources');
  const resultsEl = $('results'), deepEl = $('deeplist');
  const dirEl = $('dirlist'), filtersEl = $('filters'), placeholder = $('placeholder');
  const cloudEl = $('cloudlist'), cloudbar = $('cloudbar');
  const pager = $('pager'), prevBtn = $('prev'), nextBtn = $('next'), pagemark = $('pagemark');

  const boot = JSON.parse($('boot-data').textContent);
  const state = { kw: '', page: 1, category: '', tab: 'vod', abort: null, cache: {},
                  catalogLoaded: false, deepLoaded: false,
                  cloudKw: null, cloudData: null, cloudLoading: false };
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const stars = (n) => '★'.repeat(Math.max(0, Math.min(5, n | 0))) +
    '☆'.repeat(Math.max(0, 5 - (n | 0)));

  // 后端给的是 emoji 状态，前端统一渲染成 CSS 圆点，颜色与整站一致
  const DOT_CLASS = { '🟢': 's-ok', '🟡': 's-restricted', '🔴': 's-bad', '⚪': '' };
  const dotEl = (emoji) => '<i class="dot ' + (DOT_CLASS[emoji] || '') + '" aria-hidden="true"></i>';

  /* ---------------- tabs ---------------- */
  document.querySelectorAll('.tab').forEach((t) => {
    t.addEventListener('click', () => switchTab(t.dataset.tab));
  });
  function switchTab(tab) {
    state.tab = tab;
    document.querySelectorAll('.tab').forEach((t) =>
      t.classList.toggle('active', t.dataset.tab === tab));
    document.querySelectorAll('.panel').forEach((p) =>
      p.classList.toggle('active', p.id === 'panel-' + tab));
    if (tab === 'dir') ensureCatalog();
    if (tab === 'cloud') ensureCloud();
    if (tab === 'deep') ensureDeep();
  }

  /* 直达：不搜也能看，所以进页面/进标签页就先加载一次 */
  function ensureDeep() {
    if (state.deepLoaded) return;
    getJSON('/api/deeplinks?kw=').then((d) => {
      state.deepLoaded = true;
      renderDeep(d);
    }).catch(() => {});
  }

  /* 网盘查询：只在点进标签页时才发请求，搜索本身不等它 */
  function ensureCloud() {
    if (!state.kw) {
      cloudbar.innerHTML = '';
      cloudEl.innerHTML = '<div class="empty"><b>先搜索一个片名</b>' +
        '<div>网盘查询要用影片名作为关键词，请在上方搜索后再点这个标签页。</div>' +
        '<div class="tip">查询是点击标签页时才发出的，不点就不占网络。</div></div>';
      return;
    }
    if (state.cloudKw === state.kw && state.cloudData) { renderCloud(state.cloudData); return; }
    if (state.cloudLoading) return;
    state.cloudLoading = true;
    cloudbar.innerHTML = '<span class="loadnote">正在并发抓取 ' +
      '网盘 / 磁力站的搜索结果页…</span>';
    cloudEl.innerHTML = '<div class="skel">解析各站结果页中，站点较多时约需十几秒</div>';
    fetch('/api/cloud?kw=' + encodeURIComponent(state.kw))
      .then((r) => r.json())
      .then((d) => { state.cloudData = d; state.cloudKw = state.kw; renderCloud(d); })
      .catch((e) => {
        cloudbar.innerHTML = '';
        cloudEl.innerHTML = '<div class="empty"><b>查询失败</b><div>' + esc(e.message) + '</div></div>';
      })
      .finally(() => { state.cloudLoading = false; });
  }

  function renderCloud(d) {
    const sites = d.sites || [];
    cloudbar.innerHTML = '查询 <b>' + esc(d.keyword) + '</b> · ' + sites.length +
      ' 个网盘 / 磁力站，其中 <b>' + d.with_results + '</b> 个解析出结果，共 <b>' +
      d.entries + '</b> 条';
    const withRes = sites.filter((s) => s.ok);
    const noRes = sites.filter((s) => !s.ok);
    const block = (s) => {
      const items = (s.items || []).map((it) =>
        '<a class="clouditem" href="' + esc(it.link) + '" target="_blank" rel="noopener noreferrer">' +
        esc(it.title) + '</a>').join('');
      return '<div class="csite"><div class="chead"><b>' + esc(s.name) + '</b>' +
        '<span class="ct">' + esc(s.category) + '</span>' +
        '<span class="cnum">' + s.count + ' 条</span></div>' +
        '<div class="clouditems">' + items + '</div></div>';
    };
    const noteBlock = (s) =>
      '<div class="csite none"><div class="chead"><b>' + esc(s.name) + '</b>' +
      '<span class="ct">' + esc(s.category) + '</span></div>' +
      '<div class="creason">' + esc(s.error || '未返回结果') + ' ' +
      (s.search_url ? '<a href="' + esc(s.search_url) + '" target="_blank" rel="noopener noreferrer">打开该站搜索页 ↗</a>' : '') +
      '</div></div>';
    cloudEl.innerHTML =
      (withRes.length ? '<div class="grouphead">已解析出结果</div><div class="cgrid">' +
        withRes.map(block).join('') + '</div>' : '') +
      '<div class="grouphead">无法在服务端取到结果</div><div class="clist">' +
      noRes.map(noteBlock).join('') + '</div>';
  }

  /* 目录页在首次进入时就该有内容，而不是等用户搜过一次才有筛选条 */
  function ensureCatalog() {
    if (state.catalogLoaded) return;
    state.catalogLoaded = true;
    getJSON('/api/catalog?kw=').then(renderCatalog).catch(() => {
      state.catalogLoaded = false;
    });
  }

  /* ---------------- search ---------------- */
  form.addEventListener('submit', (e) => { e.preventDefault(); run(input.value, 1); });
  $('home').addEventListener('click', goHome);

  function goHome() {
    // 落地页 /s/<关键词> 上必须真的跳回 /，否则 URL 还停在关键词页，等于重复内容
    if (boot.kw) { location.href = '/'; return; }
    if (state.abort) state.abort.abort();
    input.value = '';
    state.kw = ''; state.page = 1;
    state.cloudKw = null; state.cloudData = null; state.deepLoaded = false;
    resultsEl.innerHTML = ''; deepEl.innerHTML = ''; dirEl.innerHTML = '';
    $('sources').innerHTML = ''; cloudbar.innerHTML = '';
    document.getElementById('cloudlist').innerHTML = '';
    statline.hidden = true;
    pager.hidden = true;
    placeholder.hidden = false;
    const ssr = document.getElementById('ssr');
    if (ssr) ssr.hidden = true;
    const hot = document.getElementById('hot');
    if (hot) hot.hidden = false;      // 猜你想搜是服务端渲染好的，直接显出来
    switchTab('vod');
    input.focus();
  }
  $('examples').addEventListener('click', (e) => {
    const b = e.target.closest('.chip');
    if (!b) return;
    input.value = b.textContent.trim();
    run(input.value, 1);
  });
  prevBtn.addEventListener('click', () => run(state.kw, state.page - 1));
  nextBtn.addEventListener('click', () => run(state.kw, state.page + 1));

  async function run(rawKw, page) {
    const kw = (rawKw || '').trim();
    if (!kw) {
      const hot = document.getElementById('hot');
      if (hot) hot.hidden = false;
      input.focus();
      return;
    }
    page = Math.max(1, page || 1);
    state.kw = kw; state.page = page;
    state.cloudKw = null; state.cloudData = null;   // 换了关键词，网盘查询结果作废
    if (state.tab === 'cloud') ensureCloud();
    placeholder.hidden = true; statline.hidden = false;
    const hot = document.getElementById('hot');
    if (hot) hot.hidden = true;

    if (state.abort) state.abort.abort();
    const ctrl = new AbortController();
    state.abort = ctrl;

    goBtn.disabled = true;
    srcbar.innerHTML = '';
    meta.textContent = '正在查询 ' + kw + ' …';
    resultsEl.innerHTML = '<div class="skel">正在并发查询 ' + boot.sources.length + ' 个采集接口…</div>';
    deepEl.innerHTML = ''; dirEl.innerHTML = '';

    const t0 = performance.now();
    let searchOk = false;
    try {
      const [sr, dr, cr] = await Promise.allSettled([
        getJSON('/api/search?kw=' + encodeURIComponent(kw) + '&page=' + page, ctrl.signal),
        getJSON('/api/deeplinks?kw=' + encodeURIComponent(kw), ctrl.signal),
        // 目录按分类浏览，片名只用来拼"搜此片"
        getJSON('/api/catalog?kw=&category=' + encodeURIComponent(state.category) +
          '&link_kw=' + encodeURIComponent(kw), ctrl.signal),
      ]);
      searchOk = sr.status === 'fulfilled';
      const sdata = searchOk ? sr.value : null;

      const ms = Math.round(performance.now() - t0);
      if (sdata) {
        renderSources(sdata);
        renderResults(sdata, ms);
        renderPager(sdata);
      } else {
        resultsEl.innerHTML = emptyCard('检索接口无响应', '请检查本机网络，或稍后重试。第三方公开接口可能临时失效。');
        meta.textContent = '查询失败 · 用时 ' + ms + 'ms';
      }
      if (dr.status === 'fulfilled') renderDeep(dr.value);
      if (cr.status === 'fulfilled') renderCatalog(cr.value);
      if (state.deepLoaded) { state.deepLoaded = false; ensureDeep(); }
    } catch (e) {
      if (e.name === 'AbortError') return;
      resultsEl.innerHTML = emptyCard('出错了', esc(e.message));
    } finally {
      goBtn.disabled = false;
    }
    return searchOk;
  }

  async function getJSON(url, signal) {
    const r = await fetch(url, { signal });
    if (!r.ok) throw new Error('HTTP ' + r.status + ' @ ' + url);
    return r.json();
  }

  /* ---------------- renderers ---------------- */
  function renderSources(d) {
    srcbar.innerHTML = (d.status || []).map((s) => {
      const cls = s.ok ? 'ok' : 'bad';
      const txt = s.ok ? esc(s.source_name) + ' ' + s.count : esc(s.source_name) + ' 不可用';
      const tip = s.ok ? ('命中 ' + s.count + ' 条 · ' + s.ms + 'ms') : esc(s.error || '');
      return '<span class="srcbadge ' + cls + '" title="' + tip + '">' + txt + '</span>';
    }).join('');
  }

  function renderResults(d, ms) {
    meta.innerHTML = [
      '命中 <b>' + d.results.length + '</b> 部（接口返回 ' + d.hits + ' 条）',
      d.dropped_noise ? '已过滤 <b>' + d.dropped_noise + '</b> 条无关结果' : '',
      '可用源 <b>' + d.sources_ok + '/' + d.sources_total + '</b>',
      '用时 <b>' + ms + '</b>ms'
    ].filter(Boolean).join(' · ');
    if (!d.results.length) {
      const ascii = /^[\x00-\x7F]+$/.test(d.keyword) && /[A-Za-z]/.test(d.keyword);
      resultsEl.innerHTML = emptyCard(
        '采集接口没有「' + esc(d.keyword) + '」的结果',
        (ascii ? '这些接口收的是中文片名，英文原名往往搜不到，试试中文译名（如 Oppenheimer → 奥本海默）。'
               : '可换个说法再搜（例如只留主标题、去掉季数），') +
        '或切到「网盘 · 磁力直达」用各站自己的搜索。');
      return;
    }
    resultsEl.innerHTML = d.results.map((r, i) => card(r, i)).join('');
    state.cache = {};
    d.results.forEach((r, i) => { state.cache[i] = r; });
  }

  function card(r, i) {
    // 占位符由 CSS 的 .cover::before 负责：图片加载失败被移除后会自动露出
    // 海报统一走 /img 代理：第三方图床有防盗链（无/错 Referer 返回 418/403）和自签证书
    const pic = r.pic && /^https?:/.test(r.pic)
      ? '<img loading="lazy" decoding="async" src="/img?url=' + encodeURIComponent(r.pic) +
        '" alt="" onerror="this.remove()">'
      : '';
    const tags = [];
    if (r.type) tags.push('<span class="tag">' + esc(r.type) + '</span>');
    if (r.year) tags.push('<span class="tag">' + esc(r.year) + '</span>');
    if (r.area) tags.push('<span class="tag">' + esc(r.area) + '</span>');
    if (r.remarks) tags.push('<span class="tag hl">' + esc(r.remarks) + '</span>');

    const srcs = (r.sources || []).map((s) =>
      '<button class="srcbtn" data-i="' + i + '" data-sid="' + esc(s.id) + '" data-vid="' +
      esc(s.vid || '') + '" data-title="' + esc(r.title) + '">' + esc(s.name) +
      (s.remarks ? '·' + esc(s.remarks) : '') + '</button>').join('');

    // 纯 API 源（首页 403/500）不显示"打开站点"，否则会跳到拦截页
    const homeSrc = (r.sources || []).find((s) => s.link);
    const openLink = homeSrc
      ? '<a class="openlink" href="' + esc(homeSrc.link) + '" target="_blank" rel="noopener noreferrer">' +
        '在' + esc(homeSrc.name) + '打开 ↗</a>'
      : '';
    const MATCH_LABEL = { series: '同系列版本', contains: '近似名称', other: '模糊匹配' };
    return '<article class="card">' +
      '<div class="cover">' + pic + '</div>' +
      '<div class="body">' +
      '<h3 class="title">' + esc(r.title) +
      (r.match === 'exact' ? '' : '<span class="flag">' + (MATCH_LABEL[r.match] || '模糊匹配') + '</span>') +
      (r.sources.length > 1 ? '<span class="flag">' + r.sources.length + ' 个源</span>' : '') +
      '</h3>' +
      '<div class="tags">' + tags.join('') + '</div>' +
      (r.actor ? '<p class="sub">主演：' + esc(r.actor) + '</p>' : '') +
      '<div class="srcline"><span class="lbl">来源</span>' + srcs + openLink + '</div>' +
      '<div class="lineslot" id="slot-' + i + '"></div>' +
      '</div></article>';
  }

  function renderPager(d) {
    const hasMore = d.hits >= 8 && d.results.length >= 8;
    pager.hidden = !(hasMore || d.page > 1);
    pagemark.textContent = '第 ' + d.page + ' 页';
    prevBtn.disabled = d.page <= 1;
    nextBtn.disabled = !hasMore;
  }

  /* 展开某个源的播放线路 */
  resultsEl.addEventListener('click', async (e) => {
    const btn = e.target.closest('.srcbtn');
    if (!btn) return;
    const i = btn.dataset.i, sid = btn.dataset.sid, vid = btn.dataset.vid;
    const title = btn.dataset.title || '';
    const slot = $('slot-' + i);
    // 注意：来源按钮在 .srcline 里，不在 #slot-i 里，必须按所在卡片清理选中态，
    // 否则 .on 永远残留，同一个源再点就被判成"已展开"而什么都不做。
    const card = btn.closest('.card') || document;
    const isOpen = btn.classList.contains('on');
    card.querySelectorAll('.srcbtn').forEach((b) => b.classList.remove('on'));
    if (isOpen) { slot.innerHTML = ''; return; }
    btn.classList.add('on');
    if (!vid) { slot.innerHTML = '<div class="lines"><div class="loading">该源未提供影片 ID，无法取线路。</div></div>'; return; }

    const key = sid + ':' + vid;
    if (state.cache[key]) { slot.innerHTML = linesHTML(state.cache[key]); return; }
    slot.innerHTML = '<div class="lines"><div class="loading">正在读取「' +
      esc(btn.textContent) + '」的播放线路…</div></div>';
    try {
      const d = await getJSON('/api/detail?src=' + encodeURIComponent(sid) +
        '&vid=' + encodeURIComponent(vid) + '&t=' + encodeURIComponent(title));
      state.cache[key] = d;
      slot.innerHTML = linesHTML(d);
    } catch (err) {
      slot.innerHTML = '<div class="lines"><div class="loading">读取失败：' + esc(err.message) + '</div></div>';
    }
  });

  function linesHTML(d) {
    if (!d || !d.lines || !d.lines.length) {
      return '<div class="lines"><div class="loading">' +
        esc((d && d.error) || '该源没有返回可播放的线路') + '</div></div>';
    }
    return '<div class="lines">' + d.lines.map((ln) =>
      '<div class="line"><div class="lname">' + esc(ln.from) + ' · ' + ln.episodes.length + ' 条</div>' +
      '<div class="eps">' + ln.episodes.slice(0, 120).map((ep) =>
        '<a href="' + esc(ep.url) + '" target="_blank" rel="noopener noreferrer">' +
        esc(ep.name || '播放') + '</a>').join('') + '</div></div>'
    ).join('') + '</div>';
  }

  /* ---------------- 直达链接 ---------------- */
  function renderDeep(d) {
    const items = d.items || [];
    if (!items.length) { deepEl.innerHTML = ''; return; }
    const kw = d.keyword || '';
    const groups = {};
    items.forEach((it) => { (groups[it.category] = groups[it.category] || []).push(it); });
    deepEl.innerHTML = Object.keys(groups).map((cat) =>
      '<div class="grouphead">' + esc(cat) + (kw ? ' · 用「' + esc(kw) + '」直达搜索'
        : ' · 共 ' + groups[cat].length + ' 站，搜索后自动带上关键词') + '</div>' +
      '<div class="grid">' + groups[cat].map((it) =>
        '<a class="deep" href="' + esc(it.url) + '" target="_blank" rel="noopener noreferrer">' +
        '<b>' + dotEl(it.dot) + esc(it.name) + '</b>' +
        '<span>' + esc(it.status) + (it.kind === 'site_search' ? '' : (kw ? ' · 未验证站内搜索路径，打开首页自行搜索' : ' · 打开首页')) + '</span>' +
        '<span class="cat">' + stars(it.recommended) + '</span></a>').join('') + '</div>'
    ).join('');
  }

  /* ---------------- 资源站目录 ---------------- */
  function renderFilters(cats) {
    filtersEl.innerHTML = '<button class="fbtn on" data-cat="">全部</button>' +
      cats.map((c) => '<button class="fbtn" data-cat="' + esc(c.name) + '">' + esc(c.name) +
        ' <span class="dim">' + c.working + '/' + c.total + '</span></button>').join('');
  }
  filtersEl.addEventListener('click', (e) => {
    const b = e.target.closest('.fbtn');
    if (!b) return;
    filtersEl.querySelectorAll('.fbtn').forEach((x) => x.classList.toggle('on', x === b));
    state.category = b.dataset.cat;
    loadCatalog();
  });

  async function loadCatalog() {
    try {
      // 目录是按分类浏览站点用的，不拿影片名去"匹配站点"，所以不传 kw
      const d = await getJSON('/api/catalog?kw=&category=' + encodeURIComponent(state.category) +
        '&link_kw=' + encodeURIComponent(state.kw || ''));
      renderCatalogItems(d);
    } catch (e) { dirEl.innerHTML = ''; }
  }
  function renderCatalog(d) {
    renderFilters(d.categories || boot.categories);
    loadCatalog();
  }
  function renderCatalogItems(d) {
    if (!d.items.length) {
      dirEl.innerHTML = '<div class="empty"><b>该分类下暂无可显示的站点</b>' +
        '<div>换个分类，或等自动更新拉到新的目录。</div></div>';
      return;
    }
    dirEl.innerHTML = '<div class="list">' + d.items.map((it) =>
      '<div class="row">' + dotEl(it.dot) +
      '<span class="nm">' + esc(it.name) + '</span>' +
      '<span class="ct">' + esc(it.category_cn) + '</span>' +
      '<span class="tg">' + esc((it.tags || []).join(' / ')) + (it.hints.length ? ' · ' + esc(it.hints.join(' / ')) : '') + '</span>' +
      '<span class="stars">' + stars(it.recommended) + '</span>' +
      '<span class="links"><a href="' + esc(it.url) + '" target="_blank" rel="noopener noreferrer">首页 ↗</a>' +
      (it.deep ? '<a href="' + esc(it.deep.url) + '" target="_blank" rel="noopener noreferrer">搜此片 ↗</a>' : '') +
      '</span></div>').join('') + '</div>';
  }

  function emptyCard(title, tip) {
    return '<div class="empty"><b>' + title + '</b>' +
      '<div>' + esc(tip) + '</div>' +
      '<div class="tip">公开接口稳定性有限，稍后重试通常就有了。</div></div>';
  }

  /* 猜你想搜：一行正好铺满容器，翻页切换整行（不做横向滚动条） */
  function hotCard(x) {
    const cover = x.pic
      ? '<span class="hcover"><img loading="lazy" decoding="async" src="' + esc(x.pic) +
        '" alt="" onerror="this.remove()"></span>'
      : '<span class="hcover"></span>';
    const meta = [x.year || x.type, x.rate ? '豆瓣 ' + x.rate : '',
                  x.n_sources > 1 ? x.n_sources + ' 源' : ''].filter(Boolean).join(' · ');
    return '<a class="hotcard" href="' + esc(x.url) + '" data-title="' + esc(x.title) + '">' +
      cover + '<b>' + esc(x.title) + '</b><span class="hotmeta">' + esc(meta) + '</span></a>';
  }

  // 每页张数 = CSS 网格实际列数，两边共用一个来源，不会算错行
  function hotCols(grid) {
    const v = getComputedStyle(grid).gridTemplateColumns || '';
    const n = v.split(' ').filter(Boolean).length;
    return n > 0 ? n : 6;
  }

  const hotState = {};          // kind -> {page, cols, total}
  const bootRows = { movie: (boot.hot && boot.hot.movie) || [],
                     tv: (boot.hot && boot.hot.tv) || [] };

  function paintHotNav(kind) {
    const st = hotState[kind];
    const grid = document.querySelector('.hotgrid[data-kind="' + kind + '"]');
    if (!st || !grid) return;
    const pages = Math.max(1, Math.ceil(st.total / st.cols));
    const label = document.getElementById('pageof-' + kind);
    if (label) label.textContent = (st.page + 1) + ' / ' + pages;
    document.querySelectorAll('.pbtn[data-kind="' + kind + '"]').forEach((b) => {
      const dir = +b.dataset.dir;
      b.disabled = dir < 0 ? st.page <= 0 : st.page >= pages - 1;
    });
    grid.dataset.per = st.cols;
  }

  async function showHotPage(kind, page) {
    const grid = document.querySelector('.hotgrid[data-kind="' + kind + '"]');
    if (!grid) return;
    const cols = hotCols(grid);
    const st = hotState[kind] || (hotState[kind] = { page: 0, cols: cols, total: +grid.dataset.total || 0 });
    st.cols = cols;
    st.page = Math.max(0, page);
    const offset = st.page * cols;
    try {
      // 首屏那 12 条已经在页面里，第 0 页直接切片，不用再发一次请求
      let items;
      if (offset === 0 && bootRows[kind].length >= cols) {
        items = bootRows[kind].slice(0, cols);
        st.total = +grid.dataset.total || bootRows[kind].length;
      } else {
        const d = await getJSON('/api/hot?kind=' + encodeURIComponent(kind) +
          '&offset=' + offset + '&limit=' + cols);
        items = d.items || [];
        st.total = d.total;
      }
      grid.innerHTML = items.map(hotCard).join('');
      paintHotNav(kind);
    } catch (e) { /* 保持已渲染内容不动 */ }
  }

  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.pbtn');
    if (!btn) return;
    e.preventDefault();
    const kind = btn.dataset.kind;
    const st = hotState[kind];
    if (!st || btn.disabled) return;
    showHotPage(kind, st.page + (+btn.dataset.dir));
  });

  // 窗口变窄/变宽时列数会变，按新列数重铺当前这页
  let hotResize = null;
  window.addEventListener('resize', () => {
    clearTimeout(hotResize);
    hotResize = setTimeout(() => {
      Object.keys(hotState).forEach((kind) => showHotPage(kind, hotState[kind].page));
    }, 250);
  });

  ['movie', 'tv'].forEach((kind) => {
    if (document.querySelector('.hotgrid[data-kind="' + kind + '"]')) showHotPage(kind, 0);
  });

  /* 更新进度：跑起来时轮询，跑完提示刷新 */
  let progTimer = null;
  function renderProg(p) {
    const box = document.getElementById('prog');
    if (!box || !p) return;
    const total = p.total || 6, done = p.done || 0;
    box.querySelector('.progbar i').style.width = Math.max(4, Math.round(done / total * 100)) + '%';
    box.querySelector('#progsteps').innerHTML = (p.steps || []).map((s, i) => {
      const cls = s.state === 'ok' ? 'ok' : s.state === 'fail' ? 'fail'
        : s.state === 'skipped' ? 'skipped' : (i === done && p.running ? 'cur' : '');
      return '<span class="pstep ' + cls + '">' + esc(s.label) + '</span>';
    }).join('') + (p.note ? '<span class="pstep">' + esc(p.note) + '</span>' : '');
  }

  function watchProgress() {
    const banner = document.getElementById('banner');
    if (!banner || banner.dataset.state !== 'running' || progTimer) return;
    progTimer = setInterval(async () => {
      try {
        const s = await getJSON('/api/refresh');
        const p = s.progress || {};
        renderProg(p);
        const total = p.total || 6;
        document.getElementById('banner-text').textContent = p.running
          ? '正在后台更新（第 ' + Math.min((p.done || 0) + 1, total) + '/' + total +
            ' 步：' + (p.step_label || '准备中') + '）'
          : '更新已结束';
        const hint = document.getElementById('banner-hint');
        if (p.running) {
          hint.textContent = '已完成 ' + (p.done || 0) + '/' + total +
            ' 步 · 当前显示的是上一次的数据' + (p.note ? ' · ' + p.note : '');
          return;
        }
        clearInterval(progTimer); progTimer = null;
        banner.dataset.state = 'done';
        banner.classList.remove('run'); banner.classList.add('ok');
        document.getElementById('banner-text').textContent = '数据已更新完成';
        hint.innerHTML = '<a id="reloadnow">刷新页面查看</a>';
        const a = document.getElementById('reloadnow');
        if (a) a.onclick = () => location.reload();
      } catch (e) { /* 瞬时错误留给下一次轮询 */ }
    }, 3000);
  }

  switchTab('vod');
  ensureDeep();
  renderProg(boot.progress || null);   // 首屏就把步骤条画出来，不等第一次轮询
  watchProgress();
  if (boot.kw) {                 // SEO 落地页：服务端已渲染摘要，这里接管成交互式
    input.value = boot.kw;
    run(boot.kw, 1).then(() => {
      const ssr = document.getElementById('ssr');
      if (ssr) ssr.classList.add('ssr-done');
    });
  } else {
    input.focus();
  }
})();
