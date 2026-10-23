import { useCallback, useLayoutEffect, useRef } from "react";

/** 「N 行内联滚动」那点事：给一个滚动框量出刚好装下 N 行的高度，写成 maxHeight。
 *
 *  三条都是踩出来的：
 *  1. 量的是第 N+1 行的 `offsetTop`，不是 N×行高 —— 各列换行情况不一，写死像素会切掉半行，
 *     而且中文行高本来就不是整数。容器必须是定位元素（`relative`），否则 offsetTop
 *     会一路找到页面外层，算出来的高度大得离谱，限高等于没限。
 *  2. 写完还要再量一次：竖向滚动条占掉宽度会让行重新折行，横向滚动条占掉高度会把最后一行
 *     压在下面，两笔都得补（`offsetHeight - clientHeight`）。
 *  3. **不能用 requestAnimationFrame 推迟首测**：后台标签里 rAF 压根不回调（实测踩过），
 *     限高就静默失效。所以每次渲染后用 layout effect 同步量一次，observer 的回调里
 *     也直接量 —— 只在算出来的高度**变了**才写 DOM：写同一个值不会再触发 observer，
 *     自己引起的 resize 两轮就收敛，不会出现
 *     "ResizeObserver loop completed with undelivered notifications"。
 *  4. ResizeObserver 只在"渲染生命周期"里回调，隐藏标签里那一轮可以永远不来；而
 *     HeroUI 的 Table 把行排在**另一次提交**里（React 重渲染我们的组件时 tbody 还是空的，
 *     量出来就是"不用限高"）。所以还要一个 MutationObserver 盯 childList：它是微任务，
 *     跟可见性无关，行一落地就重算。窄屏改宽度那种还是归 ResizeObserver 管。
 *
 *  用法：`const setBox = useClamp((el) => {...算出 maxHeight 或 null...})`，把 `setBox`
 *  当 ref 挂在那个滚动容器上。容器换了节点（折叠后重新展开）回调 ref 会重跑，
 *  observer 也跟着重挂，不需要额外的依赖项。 */
export function useClamp(calc: (el: HTMLElement) => number | null) {
  const el = useRef<HTMLElement | null>(null);
  const ro = useRef<ResizeObserver | null>(null);
  const mo = useRef<MutationObserver | null>(null);
  const last = useRef<number | null | undefined>(undefined);
  const calcRef = useRef(calc);
  calcRef.current = calc;

  const measure = useCallback(() => {
    const node = el.current;
    if (!node) return;
    const next = calcRef.current(node);
    if (next === last.current) return;   // 同一个值不再写：写了只会再多一轮 observer
    last.current = next;
    node.style.maxHeight = next === null ? "" : `${next}px`;
  }, []);

  const setBox = useCallback(
    (node: HTMLElement | null) => {
      if (ro.current) {
        ro.current.disconnect();
        ro.current = null;
      }
      if (mo.current) {
        mo.current.disconnect();
        mo.current = null;
      }
      el.current = node;
      last.current = undefined;          // 换了节点：别拿上一个节点的值当"没变"
      if (!node) return;
      ro.current = new ResizeObserver(measure);
      ro.current.observe(node);
      // 行是另一次提交才落地的（HeroUI 的 Table 内部如此），childList 一变就重算
      mo.current = new MutationObserver(measure);
      mo.current.observe(node, { childList: true, subtree: true });
      measure();
    },
    [measure],
  );

  // 每次渲染后再量一遍：数据换了页、折叠展开、宽度变了都在这一次覆盖到，
  // 不用等 observer 那一轮（写完同一个值会 bail，所以不会循环渲染）
  useLayoutEffect(measure);

  return setBox;
}
