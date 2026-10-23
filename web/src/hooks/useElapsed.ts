import { useEffect, useState } from "react";

/** 请求已经跑了多少秒。并发检索没有分源进度可问，给不出百分比，
 *  但"已经等了 6 秒"是能如实说出来的 —— 没有这句话，人只能靠猜来决定要不要刷页面。 */
export function useElapsed(active: boolean): number {
  const [sec, setSec] = useState(0);
  useEffect(() => {
    if (!active) {
      setSec(0);
      return;
    }
    const t0 = Date.now();
    setSec(0);
    const timer = window.setInterval(() => setSec(Math.floor((Date.now() - t0) / 1000)), 500);
    return () => window.clearInterval(timer);
  }, [active]);
  return sec;
}
