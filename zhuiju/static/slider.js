/* 真人滑块。首页（cookie 过期时弹出来）与门禁页 /verify 共用这一份实现 ——
   两处各写一份的话，"这边的校验改了、那边还能过"是最难查的那类不一致。

   这里的判断（耗时、采样数）只是**给服务端多几条依据**，裁决全在 zhuiju/human.py：
   缺口位置由服务端随机、容差由服务端定、挑战两分钟过期且提交一次就作废。
   写在这儿是为了让正常用户一次就过，不是为了"防住"谁 —— 想防的人直接照这个文件发请求。 */
window.zhuijuSlip = (function () {
  function post(url, body) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then((r) => r.json().catch(() => ({})).then((d) => ({ status: r.status, data: d })));
  }

  function mount(root, opts) {
    opts = opts || {};
    if (!root) return null;
    const track = root.querySelector('[data-track]');
    const knob = root.querySelector('[data-knob]');
    const hole = root.querySelector('[data-hole]');
    const msg = root.querySelector('[data-msg]');
    let ch = null;                     // 当前挑战：{id, target, tol}
    let pct = 0;                       // 滑块当前位置（0..1，与 target 同一个坐标）
    let down = 0;                      // 按下那一刻（performance.now()），0 = 没在拖
    let spent = 0;                     // 这一次拖了多久。**必须在 down 归零之前算好**：
                                       // 早先 submit 里现算 `performance.now() - t0`，而 pointerup
                                       // 已经先把 t0 清了 —— 于是鼠标拖每次都上报 0ms，
                                       // 服务端按"太快了"永远拒，真人怎么拖都过不去（实测踩到，
                                       // 键盘那条路反而能过，因为它没提前清 t0）
    let samples = 0;                   // 指针轨迹采样点数
    let keys = 0;                      // 方向键次数（键盘那条通路唯一能拿到的"动过"证据）
    let busy = false;
    let idle = 0;

    /* 滑块宽度**现量**，不写常量：窄屏 CSS 会把轨道加高、滑块加宽（拇指目标），
       这里写死一个数的话缺口就会和滑块错开半截 —— 用户看到的就是"明明对准了却说不匹配" */
    function kw() { return knob.offsetWidth || 44; }
    function span() { return Math.max(1, track.getBoundingClientRect().width - kw()); }

    function paint() {
      knob.style.setProperty('--p', (pct * 100).toFixed(2));
      knob.setAttribute('aria-valuenow', String(Math.round(pct * 100)));
    }

    // 缺口画成"容差范围内的那一段"，并且**以目标位置为中心**：只画一条线等于把容差藏起来，
    // 而中心算偏半格就是"看着对准了却不过"（滑块的中心在 target*span + kw/2）
    function layout() {
      if (!ch) return;
      const w = kw(), s = span();
      const zone = ch.tol * 2 * s + w;
      hole.style.width = Math.round(zone) + 'px';
      hole.style.left = Math.round(ch.target * s + w / 2 - zone / 2) + 'px';
    }

    function say(text, cls) {
      msg.textContent = text;
      msg.className = 'slip-msg' + (cls ? ' ' + cls : '');
    }

    function ask() {
      busy = true;
      say('正在准备验证…');
      return post('/api/human/challenge').then((r) => {
        if (r.status !== 200 || !r.data.id) {
          say('拿不到验证（' + (r.data && r.data.error ? r.data.error : r.status) + '），点这里重试', 'bad');
          knob.disabled = true;
          busy = false;
          return null;
        }
        ch = r.data;
        pct = 0; samples = 0; keys = 0; down = 0; spent = 0;
        knob.disabled = false;
        paint();
        layout();
        say('把滑块拖进虚线框里（不方便用鼠标就点一下滑块，再用左右方向键）');
        busy = false;
        return ch;
      }).catch(() => {
        say('网络不通，拿不到验证。点这里重试', 'bad');
        busy = false;
        return null;
      });
    }

    function submit() {
      if (busy || !ch) return;
      busy = true;
      knob.disabled = true;
      say('正在核对…');
      post('/api/human/verify', {
        id: ch.id, pct: pct, ms: Math.round(spent), samples: samples, keys: keys
      }).then((r) => {
        if (r.status === 200 && r.data.ok) {
          say('验证通过，正在回去…', 'good');
          if (opts.onok) { opts.onok(); return; }
          if (opts.next) window.location.href = opts.next;
          return;
        }
        // 挑战已经用掉了（服务端单次使用），所以失败后必须换一块新的，
        // 不然用户再拖一次是拿一条废挑战去提交，永远过不去
        say((r.data && r.data.error ? r.data.error : '没通过') + '，重来一次', 'bad');
        window.setTimeout(ask, 700);
      }).catch(() => {
        say('网络不通，没提交上。点这里重试', 'bad');
        window.setTimeout(ask, 700);
      });
    }

    function moveTo(clientX) {
      const rect = track.getBoundingClientRect(), w = kw();
      pct = Math.max(0, Math.min(1, (clientX - rect.left - w / 2) / span()));
      paint();
    }

    knob.addEventListener('pointerdown', (e) => {
      if (busy || !ch) return;
      down = performance.now();
      spent = 0;
      samples = 0;
      // 合成的指针事件没有"活动指针"，setPointerCapture 会抛错：抓不住照样能拖
      // （move 事件会发给窗口），为了一个测试工具抛的异常把正常流程挡住不值
      try { knob.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
      e.preventDefault();
    });
    knob.addEventListener('pointermove', (e) => {
      if (!down) return;
      moveTo(e.clientX);
      samples += 1;                   // 一次真实拖拽中间会有几十次，光"按下又抬起"是 0
    });
    knob.addEventListener('pointerup', () => {
      if (!down) return;
      spent = performance.now() - down;   // 先记下时长，再把 down 清掉
      down = 0;
      if (spent < 120 && samples < 3) return;   // 手快点一下不算拖，让用户再拖一次
      submit();
    });
    knob.addEventListener('pointercancel', () => { down = 0; });

    // 键盘通路：只有方向键算"动过"，每按一次挪 2%，攒够次数服务端才认
    knob.addEventListener('keydown', (e) => {
      if (busy || !ch) return;
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.preventDefault();
        if (!down) down = performance.now();
        pct = Math.max(0, Math.min(1, pct + (e.key === 'ArrowRight' ? 0.02 : -0.02)));
        keys += 1;
        paint();
        window.clearTimeout(idle);
        // 停手 0.6 秒就自动核对，不用记着按回车。这里顺手把 spent 也算了：
        // 从第一次按键到停手，本身就是一段真人用时
        idle = window.setTimeout(() => { spent = performance.now() - down; down = 0; submit(); }, 600);
      } else if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        if (down) spent = performance.now() - down;
        down = 0;
        submit();
      }
    });

    // 点着滑块（没拖动）也给它一条出路：说明文字点一下 = 重新拿一块挑战
    msg.addEventListener('click', () => { if (!busy) ask(); });
    // 窗口变宽变窄：滑块的 --p 是比例、自己会跟着走，缺口是按像素定的，必须重算
    window.addEventListener('resize', layout);

    ask();
    return { retry: ask };
  }

  return { mount: mount };
})();
