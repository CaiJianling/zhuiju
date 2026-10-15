/* 主题切换：亮 / 暗 / 跟随系统。
   预置脚本（templates/_theme.html）在 CSS 之前就把 data-theme 定好，这里只负责交互。 */
(function () {
  var KEY = "zhuiju_theme";
  var OPTS = ["auto", "light", "dark"];
  var LABEL = { auto: "跟随系统", light: "亮色", dark: "暗色" };

  function stored() {
    try { return localStorage.getItem(KEY) || "auto"; } catch (e) { return "auto"; }
  }
  function apply(mode, animate) {
    try { localStorage.setItem(KEY, mode); } catch (e) { /* 无痕模式写不了，本次照样生效 */ }
    var dark = mode === "dark" || (mode === "auto" &&
      window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
    // 只在用户主动切换时渐变色：首屏由 _theme.html 预置，不走这里，所以不会一进来就闪一遍
    if (animate) {
      var root = document.documentElement;
      root.classList.add("theme-anim");
      clearTimeout(apply.t);
      apply.t = setTimeout(function () { root.classList.remove("theme-anim"); }, 340);
    }
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    document.documentElement.dataset.themeMode = mode;
    sync();
  }
  function text(el) {
    var mode = document.documentElement.dataset.themeMode || stored();
    var cur = document.documentElement.dataset.theme === "dark" ? "暗色" : "亮色";
    el.textContent = "（" + LABEL[cur === "暗色" ? "dark" : "light"] + " · " + LABEL[mode] + "）";
  }
  function sync() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-theme-toggle]"), function (b) {
      text(b);
    });
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-theme-toggle]");
    if (!b) return;
    e.preventDefault();
    var mode = document.documentElement.dataset.themeMode || stored();
    apply(OPTS[(OPTS.indexOf(mode) + 1) % OPTS.length], true);
  });
  // 选"跟随系统"时，系统换了配色页面要立刻跟着换（同样带渐变）
  if (window.matchMedia) {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    var onSys = function () {
      if ((document.documentElement.dataset.themeMode || stored()) === "auto") apply("auto", true);
    };
    if (mq.addEventListener) mq.addEventListener("change", onSys);
    else if (mq.addListener) mq.addListener(onSys);
  }
  sync();
  window.ZHUIJU_THEME = { apply: apply, sync: sync };
})();
