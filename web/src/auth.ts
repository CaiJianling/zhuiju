/** 真人门禁的前端状态：只有一个问题要回答 —— "现在接口认不认这个请求"。
 *  服务端答 423 就当心虚地把它设成"要验证"，验证通过后再 +1 一格；
 *  所有取数 effect 都把这一格放进依赖里，于是"重新验证完自动把刚才那次补上"
 *  不需要每个调用点各写一遍 retry 回调。 */
import { useSyncExternalStore } from "react";
import { boot } from "./boot";

// 首屏就被服务端挡下（没 cookie）时，界面一上来就该是验证页，而不是先闪一下空列表
let denied = boot.locked;
let tick = 0;
const subs = new Set<() => void>();

function emit() {
  subs.forEach((f) => f());
}

function subscribe(fn: () => void) {
  subs.add(fn);
  return () => subs.delete(fn);
}

/** 接口回 423 时由 api 调用 */
export function markDenied() {
  if (denied) return;
  denied = true;
  emit();
}

/** 滑块过了之后调用：放行，并让所有在等的请求重发一次 */
export function markPassed() {
  denied = false;
  tick += 1;
  emit();
}

export function snapshot(): boolean {
  return denied;
}

export function useGateLocked(): boolean {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}

/** 每次"刚通过验证"都换一个数，给 effect 当依赖用 */
export function useAuthTick(): number {
  return useSyncExternalStore(subscribe, () => tick, () => tick);
}
