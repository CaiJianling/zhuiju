/* 后台的亮/暗/跟随系统切换。前台那一套是 React 的 useTheme（web/src/components/ThemeToggle.tsx），
   这里是它的无框架等价物：同一个 localStorage 键、同一对 <html> 属性，
   于是前后台共享同一份偏好 —— 切一次，两边一起翻面。 */
(function () {
  "use strict";

  var KEY = "heroui-theme";                 // HeroUI useTheme 认的键名，别改
  var OPTS = ["system", "light", "dark"];
  var LABEL = { system: "跟随系统", light: "亮色", dark: "暗色" };
  var root = document.documentElement;

  function stored() {
    var v = "system";
    try { v = localStorage.getItem(KEY) || "system"; } catch (e) { }
    return OPTS.indexOf(v) >= 0 ? v : "system";
  }

  // "跟随系统"不是一个可落地的颜色，要问系统才知道现在到底是亮还是暗
  function resolve(mode) {
    if (mode !== "system") return mode;
    return window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  // 实际生效的那一档（按钮文案要说的是它）
  function applied() {
    return resolve(stored());
  }

  function write(mode) {
    OPTS.forEach(function (t) { if (t !== "system") root.classList.remove(t); });
    // 这里必须直接问系统，不能用 applied()：调用 write 的时候 localStorage 还是**上一个**选择，
    // 从 stored() 往下解会把"跟随系统"解析成旧的 dark/light，现象是按钮说"亮色"而页面还黑着
    var r = resolve(mode);
    root.classList.add(r);
    root.setAttribute("data-theme", r);
  }

  function sync() {
    var mode = stored(), cur = applied();
    var text = mode === "system" ? LABEL.system + " · " + LABEL[cur] : LABEL[mode];
    Array.prototype.forEach.call(document.querySelectorAll("[data-theme-toggle]"), function (b) {
      b.textContent = text;
      b.setAttribute("aria-label", "界面主题：" + text);
    });
  }

  function apply(mode, animate) {
    if (animate) {
      // 只在切换这 0.3s 里给全局挂过渡，之后立刻摘掉：常驻会把 hover 拖慢、长表格掉帧
      root.classList.add("theme-anim");
      setTimeout(function () { root.classList.remove("theme-anim"); }, 380);
    }
    write(mode);
    try {
      localStorage.setItem(KEY, mode);
      return true;
    } catch (e) {
      return false;   // 无痕或禁了存储：这次生效，关掉就忘，页面上要如实说
    }
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-theme-toggle]");
    if (!b) return;
    var next = OPTS[(OPTS.indexOf(stored()) + 1) % OPTS.length];
    var saved = apply(next, true);
    sync();
    var label = next === "system" ? LABEL.system + "（现在是" + LABEL[applied()] + "）" : LABEL[next];
    b.textContent = saved ? "已保存 · " + label : "这台浏览器不给存，这次生效";
    setTimeout(sync, 1800);
  });

  // 系统偏好变了：只有"跟随系统"的人该跟着动，手动锁了亮/暗的人不许被翻面
  if (window.matchMedia) {
    var mq = matchMedia("(prefers-color-scheme: dark)");
    var onSys = function () { if (stored() === "system") apply("system", true); };
    if (mq.addEventListener) mq.addEventListener("change", onSys);
    else if (mq.addListener) mq.addListener(onSys);
  }

  write(stored());
  sync();
  window.ZHUIJU_THEME = { apply: apply, sync: sync, OPTS: OPTS, stored: stored, applied: applied };
})();
