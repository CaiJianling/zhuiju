import { useEffect, useState } from "react";
import { api } from "../api";
import type { Banner, RefreshProgress } from "../types";

export interface RefreshState extends Banner {
  /** 这一轮是"看着它跑完"的：这时候才提"刷新页面查看"，本来就已经是新的就别催 */
  finished: boolean;
}

const EMPTY_PROGRESS: RefreshProgress = {
  running: false,
  pct: 0,
  done: 0,
  total: 6,
  step_key: "",
  step_label: "",
  note: "",
  steps: [],
};

/** 页头那句"今天更新过没有"是服务端算好的，前端只在它说 running 时接着轮询。
 *  没跑就不轮询：静止的横幅每秒戳一次 /api/refresh 只会把日志淹掉。 */
export function useRefresh(initial: Banner | null): RefreshState | null {
  const [b, setB] = useState<RefreshState | null>(initial ? { ...initial, finished: false } : null);

  useEffect(() => {
    if (!b || b.state !== "running") return;
    let alive = true;
    const timer = window.setInterval(async () => {
      try {
        const s = await api.refresh();
        if (!alive) return;
        const p = s.progress ?? EMPTY_PROGRESS;
        const total = p.total || 6;
        if (p.running) {
          setB((prev) =>
            prev && {
              ...prev,
              state: "running",
              progress: p,
              text: `正在后台更新（第 ${Math.min((p.done || 0) + 1, total)}/${total} 步：${p.step_label || "准备中"}）`,
              hint: `已完成 ${p.done || 0}/${total} 步 · 当前显示的是上一次的数据${p.note ? " · " + p.note : ""}`,
            },
          );
          return;
        }
        setB((prev) => prev && { ...prev, state: "fresh", text: "数据已更新完成", hint: "", progress: p, finished: true });
      } catch {
        /* 瞬时错误留给下一次轮询 */
      }
    }, 3000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [b?.state]);

  return b;
}

export const TONE: Record<Banner["state"] | "done", string> = {
  fresh: "text-success",
  running: "text-accent",
  partial: "text-warning",
  stale: "text-muted",
  failed: "text-danger",
  never: "text-muted",
  done: "text-success",
};
