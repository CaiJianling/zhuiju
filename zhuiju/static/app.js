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
                  cloudKw: null, cloudData: null, cloudLoading: false, cloudSites: null };
  // 线路数据留在内存里按 id 取，展开哪条才把那一行的集数插进 DOM（见 linesHTML）
  const lineStore = {};
  let lineSeq = 0;
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const stars = (n) => '★'.repeat(Math.max(0, Math.min(5, n | 0))) +
    '☆'.repeat(Math.max(0, 5 - (n | 0)));

  // 后端给的是 emoji 状态，前端统一渲染成 CSS 圆点，颜色与整站一致
  const DOT_CLASS = { '🟢': 's-ok', '🟡': 's-restricted', '🔴': 's-bad', '⚪': '' };
  const dotEl = (emoji) => '<i class="dot ' + (DOT_CLASS[emoji] || '') + '" aria-hidden="true"></i>';

  /* ---------------- tabs ---------------- */
  document.querySelectorAll('.tab').forEach((t) => {
    t.addEventListener('click', () => switchTab(t.dataset.tab, t));
  });
  function switchTab(tab, t0) {
    state.tab = tab;
    document.querySelectorAll('.tab').forEach((t) =>
      t.classList.toggle('active', t.dataset.tab === tab));
    document.querySelectorAll('.panel').forEach((p) =>
      p.classList.toggle('active', p.id === 'panel-' + tab));
    // 窄屏上标签栏是横滑的：点完把选中的那个滚进视野，不然可能停在看不见的位置
    t0 && t0.scrollIntoView({ block: 'nearest', inline: 'nearest' });
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
      // 没有关键词时不再是一句"先搜索"的死胡同：把这一页会用到的站点先列出来。
      // 这条路径只读目录与已验证模板，一个站都不去抓。
      if (state.cloudSites) { renderCloudSites(state.cloudSites); return; }
      cloudbar.innerHTML = '';
      cloudEl.innerHTML = '<div class="skel">正在列这一页会用到的站点（只读目录，不联网）…</div>';
      getJSON('/api/cloud').then((d) => { state.cloudSites = d; renderCloudSites(d); })
        .catch((e) => {
          cloudEl.innerHTML = '<div class="empty"><b>站点清单读不出来</b><div>' +
            esc(e.message) + '</div></div>';
        });
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

  /* 没有关键词时的那份站点清单。分组只看 `can_query`，判据和后端真去抓时完全一致：
     目录里有已验证的 GET 搜索模板才算"本站能直接搜出结果"。空的那一组不渲染标题，
     顶着一个"本站能直接抓"却底下一行都没有，看着像坏了。 */
  function renderCloudSites(d) {
    const sites = d.sites || [];
    const q = sites.filter((s) => s.can_query), nq = sites.filter((s) => !s.can_query);
    cloudbar.innerHTML = '还没输入片名 · 先列出这一页会用到的 <b>' + sites.length +
      '</b> 个站，本站能直接搜出结果的是 <b>' + q.length + '</b> 个';
    const row = (s) =>
      '<div class="csite none"><div class="chead"><b>' + esc(s.name) + '</b>' +
      '<span class="ct">' + esc(s.category) + '</span>' +
      '<span class="cnum">' + stars(s.recommended) + '</span></div>' +
      '<div class="creason">' +
      (s.can_query
        ? '有已验证的 GET 搜索模板，输入片名后本站会直接抓它的结果页。'
        : (s.status && s.status !== '可访问'
            ? '该站状态是「' + esc(s.status) + '」，服务端抓不动，只能在浏览器里打开它自己搜。'
            : '搜索是 POST 表单或 JS 提交，服务端抓不到结果，只能打开该站自行搜索。')) +
      ' <a href="' + esc(s.home) + '" target="_blank" rel="noopener noreferrer">打开该站 ↗</a>' +
      (s.can_query ? '<div class="code url">' + esc(s.search_url) + '</div>' : '') +
      '</div></div>';
    cloudEl.innerHTML =
      (q.length ? '<div class="grouphead">本站能直接搜出结果</div><div class="clist">' +
        q.map(row).join('') + '</div>' : '') +
      '<div class="grouphead">只能打开该站自己搜</div><div class="clist">' +
      nq.map(row).join('') + '</div>' +
      '<p class="hotnote">这份清单不联网：站与状态都来自资源站目录，"能不能直接搜"按有没有' +
      '已验证的 GET 搜索模板判断，点这个标签页不会去抓这 ' + sites.length +
      ' 个站。想在这一页看到结果，在上面搜一个片名再进来。</p>';
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
    const proxied = r.pic && /^https?:/.test(r.pic) ? '/img?url=' + encodeURIComponent(r.pic) : '';
    const pic = proxied
      ? '<img loading="lazy" decoding="async" src="' + esc(proxied) + '" alt="" onerror="this.remove()">'
      : '';
    // 详情要的信息全放在按钮自己的 data-* 上：卡片已经渲染出来的东西不必再问一次后端
    const withVid = (r.sources || []).find((s) => s.vid) || {};
    const dAttrs = ' data-detail data-title="' + esc(r.title) + '" data-pic="' + esc(proxied) +
      '" data-year="' + esc(r.year || '') + '" data-area="' + esc(r.area || '') +
      '" data-type="' + esc(r.type || '') + '" data-remarks="' + esc(r.remarks || '') +
      '" data-actor="' + esc(r.actor || '') + '" data-n="' + (r.sources || []).length +
      '" data-src="' + esc(withVid.id || '') + '" data-vid="' + esc(withVid.vid || '') +
      '" data-srcs="' + esc(JSON.stringify((r.sources || []).map((s) =>
        ({ id: s.id, name: s.name, vid: s.vid || '' })))) + '"';
    const dbtn = '<button class="dbtn" type="button" aria-label="查看《' + esc(r.title) +
      '》的详情"' + dAttrs + '>详情</button>';
    const tags = [];
    if (r.type) tags.push('<span class="tag">' + esc(r.type) + '</span>');
    if (r.year) tags.push('<span class="tag">' + esc(r.year) + '</span>');
    if (r.area) tags.push('<span class="tag">' + esc(r.area) + '</span>');
    if (r.remarks) tags.push('<span class="tag hl">' + esc(r.remarks) + '</span>');

    const srcs = (r.sources || []).map((s) =>
      '<button class="srcbtn" data-i="' + i + '" data-sid="' + esc(s.id) + '" data-vid="' +
      esc(s.vid || '') + '" data-sname="' + esc(s.name) + '" data-title="' + esc(r.title) + '">' +
      esc(s.name) +
      (s.remarks ? '·' + esc(s.remarks) : '') + '</button>').join('');

    // 纯 API 源（首页 403/500）不显示"打开站点"，否则会跳到拦截页
    const homeSrc = (r.sources || []).find((s) => s.link);
    const openLink = homeSrc
      ? '<a class="openlink" href="' + esc(homeSrc.link) + '" target="_blank" rel="noopener noreferrer">' +
        '在' + esc(homeSrc.name) + '打开 ↗</a>'
      : '';
    const MATCH_LABEL = { series: '同系列版本', contains: '近似名称', other: '模糊匹配' };
    return '<article class="card">' +
      '<div class="cover">' + pic + dbtn + '</div>' +
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
    const ctx = { kw: state.kw || title, title: title, src: sid,
                  src_name: btn.dataset.sname || '', vid: vid, place: 'card' };
    if (state.cache[key]) { slot.innerHTML = linesHTML(state.cache[key], ctx); return; }
    slot.innerHTML = '<div class="lines"><div class="loading">正在读取「' +
      esc(btn.textContent) + '」的播放线路…</div></div>';
    try {
      const d = await getJSON('/api/detail?src=' + encodeURIComponent(sid) +
        '&vid=' + encodeURIComponent(vid) + '&t=' + encodeURIComponent(title));
      state.cache[key] = d;
      slot.innerHTML = linesHTML(d, ctx);
    } catch (err) {
      slot.innerHTML = '<div class="lines"><div class="loading">读取失败：' + esc(err.message) + '</div></div>';
    }
  });

  function linesHTML(d, ctx) {
    if (!d || !d.lines || !d.lines.length) {
      return '<div class="lines"><div class="loading">' +
        esc((d && d.error) || '该源没有返回可播放的线路') + '</div></div>';
    }
    // 默认只列线路名，集数等点了再插进 DOM：一部 120 集的剧一次铺出来会有
    // 上百个 <a>，面板和卡片都会被撑成长条，而且绝大多数没人点
    const id = 'L' + (++lineSeq);
    lineStore[id] = d.lines;
    return '<div class="lines" data-ls="' + id + '" data-ctx="' +
      esc(JSON.stringify(ctx || {})) + '">' +
      d.lines.map((ln, li) =>
        '<div class="line" data-line="' + esc(ln.from) + '">' +
        '<button class="lhead" type="button" data-li="' + li + '" aria-expanded="false">' +
        '<span>' + esc(ln.from) + ' · ' + ln.episodes.length + ' 条</span><i>展开</i></button>' +
        '<div class="lbody" hidden></div></div>').join('') + '</div>';
  }

  function epsHTML(ln) {
    const eps = (ln && ln.episodes) || [];
    if (!eps.length) return '<div class="loading">这条线路没给可播放的地址</div>';
    return '<div class="eps">' + eps.slice(0, 120).map((ep) =>
      '<a href="' + esc(ep.url) + '" target="_blank" rel="noopener noreferrer" data-ep="' +
      esc(ep.name || '播放') + '">' + esc(ep.name || '播放') + '</a>').join('') + '</div>';
  }

  /* 展开/收起某条线路。事件委托在 document 上：卡片里的线路和详情面板里的线路
     是两处渲染，行为要一样，而且面板换内容后新按钮也得管得到。 */
  document.addEventListener('click', (e) => {
    const h = e.target.closest('.lhead');
    if (!h) return;
    const box = h.closest('.lines'), body = h.parentNode.querySelector('.lbody');
    if (!box || !body) return;
    const open = !body.hidden;
    body.hidden = open;
    h.setAttribute('aria-expanded', open ? 'false' : 'true');
    h.parentNode.classList.toggle('open', !open);
    const caret = h.querySelector('i');
    if (caret) caret.textContent = open ? '展开' : '收起';
    if (!open && !body.dataset.filled) {
      body.innerHTML = epsHTML((lineStore[box.dataset.ls] || [])[+h.dataset.li]);
      body.dataset.filled = '1';
    }
  });

  /* ---------------- 观看点击：点了哪条播放地址，落库给后台看 ----------------
     播放页是第三方的，点完浏览器直接跳走，本站不知道他最后看不看得成；
     这一列回答的是"搜完之后有没有人真去看、从哪条线路看的"。
     用 sendBeacon：链接本身照常打开，不让埋点把跳转卡住；它不阻塞页面，
     新标签页打开时原来的页面也已经不需要等这个请求。 */
  function sendClick(p) {
    try {
      const body = JSON.stringify(p);
      if (navigator.sendBeacon) {
        navigator.sendBeacon('/api/click', new Blob([body], { type: 'application/json' }));
        return;
      }
      fetch('/api/click', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: body, keepalive: true, credentials: 'same-origin'
      });
    } catch (err) { /* 埋点失败绝不能影响人家点开播放 */ }
  }

  document.addEventListener('click', (e) => {
    const a = e.target.closest('.eps a[href]');
    if (!a) return;
    const box = a.closest('.lines');
    if (!box) return;
    let ctx = {};
    try { ctx = JSON.parse(box.dataset.ctx || '{}'); } catch (err) { ctx = {}; }
    const line = a.closest('.line');
    sendClick({
      kind: 'play',
      kw: ctx.kw || '', title: ctx.title || '', src: ctx.src || '',
      src_name: ctx.src_name || '', vid: ctx.vid || '',
      line: (line && line.dataset.line) || '', ep: a.dataset.ep || '',
      url: a.href, place: ctx.place || 'card'
    });
  });

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
    // 结构是 div.hotcard > span.hcover(图 + 详情按钮) + a.hotlink(片名 + 元信息)。
    // 不能像以前那样整张卡片是个 <a>：按钮嵌在链接里是无效 HTML，点了也会顺带跳转。
    // 缓存里那些老条目没留 src/vid，这时详情走"按片名查"那条路，
    // 服务端要并发检索一轮（所以更要点开才查）。
    // data-srcs 是「换源看」的依据：猜你想搜每一行都带着"每个源里这部片的 ID"，
    // 少了它就只能看这一个源的详情。
    const dAttrs = ' data-detail data-title="' + esc(x.title) +
      '" data-pic="' + esc(x.pic || '') + '" data-year="' + esc(x.year || '') +
      '" data-type="' + esc(x.type || '') + '" data-remarks="' + esc(x.remarks || '') +
      '" data-src="' + esc(x.src || '') + '" data-vid="' + esc(x.vid || '') +
      '" data-n="' + (x.n_sources || 0) +
      '" data-srcs="' + esc(JSON.stringify((x.sources || []).map((s) =>
        ({ id: s.id, name: s.name, vid: s.vid || '' })))) + '"';
    const dbtn = '<button class="dbtn" type="button" aria-label="查看《' + esc(x.title) +
      '》的详情"' + dAttrs + '>详情</button>';
    const cover = '<span class="hcover">' + (x.pic
        ? '<img loading="lazy" decoding="async" src="' + esc(x.pic) +
          '" alt="" onerror="this.remove()">' : '') + dbtn + '</span>';
    const meta = [x.year || x.type, x.rate ? '豆瓣 ' + x.rate : '',
                  x.n_sources > 1 ? x.n_sources + ' 源' : ''].filter(Boolean).join(' · ');
    return '<div class="hotcard">' + cover +
      '<a class="hotlink" href="' + esc(x.url) + '" data-title="' + esc(x.title) + '">' +
      '<b>' + esc(x.title) + '</b><span class="hotmeta">' + esc(meta) + '</span></a></div>';
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
        const pages = Math.max(1, Math.ceil((d.total || 0) / cols));
        // 这份缓存是后台每 6 小时重建一次的，正看着页面也可能从 36 条变成 25 条，
        // 于是页数跟着变小 —— 那是对的；错的是停在"第 5 页 / 共 4 页"这种一行都没有的页上。
        // 夹到最后一页重取一次（st.page 一定在变小，不会来回递归）。
        if (!items.length && st.page >= pages) {
          noteHotChange(kind, st.total, d.total || 0);
          st.total = d.total || 0;
          return showHotPage(kind, pages - 1);
        }
        noteHotChange(kind, st.total, d.total || 0);
        st.total = d.total || 0;
      }
      grid.innerHTML = items.map(hotCard).join('');
      paintHotNav(kind);
    } catch (e) { /* 保持已渲染内容不动 */ }
  }

  // 条数在眼皮底下变了却不说明，人只会觉得是翻页算错了：把它写出来
  function noteHotChange(kind, from, to) {
    const el = document.getElementById('hotupd-' + kind);
    if (!el) return;
    if (to && from && to !== from) {
      el.textContent = '列表刚更新过：' + from + ' → ' + to + ' 条';
    }
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

  /* ---------------- 海报右下角「详情」→ 影片信息 + 观看地址（点开才查，绝不预取） ------
     两条来路：搜索结果卡片每个来源都带影片 ID，一次 ac=detail 就够；
     猜你想搜那些（以及没留 ID 的旧缓存）只有片名，服务端要先并发检索一轮才知道 ID。
     两种都只在点了「详情」之后才发请求 —— 列表渲染时一个都不发。
     面板里给观看地址，但一行一条线路、集数点了才铺：这一版是"点开就能去看"，
     只是不把整页线路一次性塞进 DOM。 */
  const dpEl = $('dpanel'), dpTitle = $('dp-title'), dpBody = $('dp-body'), dpClose = $('dp-close');
  const dcache = {};                  // key -> 已取到的详情：来回开关不重复请求
  const dpending = {};                // key -> 在途请求：连点两次只发一次
  let dpToken = 0, dpBack = null;

  function specOf(el) {
    const d = el.dataset;
    let srcs = [];
    try { srcs = JSON.parse(d.srcs || '[]'); } catch (e) { srcs = []; }
    return { title: d.title || '', year: d.year || '', area: d.area || '', type: d.type || '',
             remarks: d.remarks || '', actor: d.actor || '', pic: d.pic || '',
             src: d.src || '', vid: d.vid || '', n: +d.n || 0, srcs: srcs,
             // 这张海报来自哪儿：后台要分得清"猜你想搜里点的详情"和"搜索结果里点的详情"
             from: el.closest('.hotcard') ? 'hot' : 'card' };
  }
  const dkey = (s) => (s.src && s.vid ? s.src + ':' + s.vid : 'kw:' + s.title);
  const detailURL = (s) => (s.src && s.vid
    ? '/api/detail?src=' + encodeURIComponent(s.src) + '&vid=' + encodeURIComponent(s.vid) +
      '&t=' + encodeURIComponent(s.title)
    : '/api/detail?kw=' + encodeURIComponent(s.title));

  /* 入口就是海报上那颗按钮。触屏上它只有 ~28px，拇指按不准，所以顺带把整张海报
     也当命中区（海报本身不是链接，不会像以前那样误跳转）；桌面仍只认按钮。 */
  const coarse = () => !!(window.matchMedia && window.matchMedia('(hover: none)').matches);
  document.addEventListener('click', (e) => {
    const hit = e.target.closest(coarse() ? '.hcover, .cover, .dbtn' : '.dbtn');
    const btn = hit && (hit.classList.contains('dbtn') ? hit : hit.querySelector('.dbtn'));
    if (!btn) return;
    openDetail(specOf(btn));
  });

  // 「换源看 / 来源」那一排。只有一个源也要显示：这一行说的是"这条详情是哪个源给的"，
  // 少了它就得去页脚那句话里找，而且源数一变整排的有无都不一样，看着像坏了。
  // 单个源时标签改成「来源」——"换"字本来就得有得换才说得通。
  function chipsRow(srcs, cur) {
    if (!srcs || !srcs.length) return '';
    // vid 从接口来是数字、从 data-* 读回来是字符串，比的时候两边都要当字符串，
    // 否则选中态永远点不亮
    return '<div class="dpchips"><span class="dplbl">' +
      (srcs.length > 1 ? '换源看' : '来源') + '</span>' +
      srcs.map((x, i) => '<button class="dchip' +
        (String(x.id) === String(cur.src) && String(x.vid) === String(cur.vid) ? ' on' : '') +
        '" type="button" data-i="' + i + '">' + esc(x.name || x.id) + '</button>').join('') +
      '</div>';
  }

  function headHTML(s) {
    const tags = [s.type, s.year, s.area, s.remarks].filter(Boolean)
      .map((t) => '<span class="tag">' + esc(t) + '</span>').join('');
    const chips = chipsRow(s.srcs, s);
    return '<div class="dpcover">' + (s.pic
        ? '<img src="' + esc(s.pic) + '" alt="" onerror="this.remove()">' : '') + '</div>' +
      (tags ? '<div class="dptags">' + tags + '</div>' : '') +
      (s.actor ? '<p class="dprow"><b>主演</b>' + esc(s.actor) + '</p>' : '') +
      (s.n > 1 ? '<p class="dprow"><b>覆盖</b>' + s.n + ' 个采集源</p>' : '') +
      chips +
      '<div id="dp-wait"><div class="dpskel"><i></i><i></i><i></i></div>' +
      '<p class="dphint">' + (dcache[dkey(s)] ? '这一条本页已经查过，直接用缓存，不再请求。'
        : (s.src && s.vid ? '正在读取这部片的详情…'
          : '这条没留影片 ID，正在按片名把各检索源都打一遍再取详情，会慢几秒…')) + '</p></div>';
  }

  function fillDetail(s, d) {
    const box = $('dp-wait');
    if (!box) return;                 // 面板已经关了或换了条目
    if (!d || d.ok === false) {
      box.innerHTML = '<p class="dperr">' + esc((d && d.error) || '没取到详情') +
        ' <button class="dpretry" type="button">重试</button></p>';
      box.querySelector('.dpretry').onclick = () => {
        delete dcache[dkey(s)];
        openDetail(s);                // 重走一遍：连头部一起重画，状态最简单
      };
      return;
    }
    // 采集源给的演员表常常是整部戏几十个名字连成一串，面板里截一下，不然一行 meta 占半屏
    const cut = (v, n) => { const t = String(v || ''); return t.length > n ? t.slice(0, n) + '…' : t; };
    const rows = [['导演', cut(d.director, 40)], ['主演', cut(d.actor || s.actor, 64)],
                  ['年份', d.year || s.year], ['地区', d.area || s.area],
                  ['类型', d.type || s.type],
                  ['更新', d.notes || d.remarks || s.remarks]].filter((r) => r[1]);
    // 按片名兜底那条路（猜你想搜的老缓存行）进来时前端不知道是哪个源，srcs 是空的。
    // 详情回来之后知道了，就把这一排补上 —— 不然那种面板就是唯一没有「来源」行的那种。
    if (!dpBody.querySelector('.dpchips') && d.source) {
      box.insertAdjacentHTML('beforebegin', chipsRow(
        [{ id: d.source, name: d.source_name || d.source, vid: s.vid }], { src: d.source, vid: s.vid }));
    }
    box.innerHTML =
      (rows.length ? '<dl class="dpmeta">' + rows.map((r) =>
        '<dt>' + esc(r[0]) + '</dt><dd>' + esc(String(r[1])) + '</dd>').join('') + '</dl>' : '') +
      (d.blurb ? '<p class="dpblurb">' + esc(d.blurb) + '</p>' : '') +
      // 观看地址就在面板里，一行一条线路，点某条才铺集数。
      // 这些是第三方的播放页，点开就直接跳过去，本站不代理也不校验它还在不在。
      '<p class="dplines-h">观看地址 <span class="dim">· ' +
      ((d.lines || []).length) + ' 条线路，点开看分集</span></p>' +
      linesHTML(d, { kw: state.kw || s.title, title: s.title, src: s.src || d.source || '',
                     src_name: d.source_name || '', vid: s.vid || '', place: 'panel' }) +
      '<p class="dpfoot">以上信息来自 ' + esc(d.source_name || '该源') +
      (d.via === 'kw' ? '（按片名定位到的）' : '（按影片 ID 直取）') +
      '，第三方接口随时可能失效。' +
      (s.title ? '<a href="/s/' + encodeURIComponent(s.title) + '">按这个片名搜一遍</a>' : '') +
      '</p>';
  }

  function openDetail(s) {
    const key = dkey(s), token = ++dpToken;
    // 点了「详情」本身就记一笔：只记查询数的话，"搜完看了一眼就走"和"真去看了"分不开。
    // 换源看也是又打开一次另一条详情，同样记 —— 后台按 (片名, 源) 数得出来。
    const self = (s.srcs || []).find((x) => String(x.id) === String(s.src)) || {};
    sendClick({ kind: 'detail', kw: state.kw || s.title || '', title: s.title || '',
                src: s.src || '', src_name: self.name || '', vid: s.vid || '',
                place: s.from || 'card' });
    if (!dpBack) dpBack = document.activeElement;
    dpTitle.textContent = s.title || '详情';
    dpBody.innerHTML = headHTML(s);
    dpEl.hidden = false;
    dpEl.classList.add('on');
    document.body.classList.add('dp-open');
    dpClose.focus();
    Array.prototype.forEach.call(dpBody.querySelectorAll('.dchip'), (b) => {
      b.onclick = () => {
        const x = (s.srcs || [])[+b.dataset.i];
        if (!x) return;
        // 点的就是当前这个源（只有一个源时那颗按钮永远是这样）：不重开、也不再上报一条，
        // 否则"看了一次详情"会被记成好几次
        if (String(x.id) === String(s.src) && String(x.vid) === String(s.vid)) return;
        openDetail(Object.assign({}, s, { src: x.id, vid: x.vid }));
      };
    });
    if (dcache[key]) { fillDetail(s, dcache[key]); return; }
    if (!s.title) { fillDetail(s, { ok: false, error: '这条目连片名都没有，查不了详情' }); return; }
    if (!dpending[key]) {
      dpending[key] = getJSON(detailURL(s))
        .then((d) => { delete dpending[key]; dcache[key] = d; return d; })
        .catch((e) => {
          delete dpending[key];
          return { ok: false, error: '读取失败：' + (e && e.message ? e.message : e) };
        });
    }
    dpending[key].then((d) => { if (token === dpToken) fillDetail(s, d); });
  }

  function closeDetail() {
    dpToken++;                        // 在途请求回来时不再填已经关掉的面板
    dpEl.classList.remove('on');
    document.body.classList.remove('dp-open');
    setTimeout(() => { if (!dpEl.classList.contains('on')) dpEl.hidden = true; }, 260);
    if (dpBack && dpBack.focus) dpBack.focus();
    dpBack = null;
  }
  dpClose.addEventListener('click', closeDetail);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !dpEl.hidden) closeDetail();
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
