import { ProgressBar } from "@heroui/react";
import type { RefreshState } from "../hooks/useRefresh";
import { TONE } from "../hooks/useRefresh";

const STEP_TONE: Record<string, string> = {
  ok: "text-success",
  fail: "text-danger",
  skipped: "text-muted/70",
};

/** 数据自动更新那一行：状态点 + 一句话 + （只在跑的时候）进度。
 *  五种状态各有各的颜色，不把"正在跑"和"快版没跑全"都染成红的。 */
export function StatusLine({ b }: { b: RefreshState }) {
  const running = b.state === "running";
  const p = b.progress;
  const total = p?.total || 6;
  const pct = p ? Math.max(4, Math.round(((p.done || 0) / total) * 100)) : 0;

  return (
    <section className="mt-4" aria-label="数据更新状态">
      <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-xs">
        <span
          aria-hidden="true"
          className={`inline-block size-1.5 shrink-0 self-center rounded-full ${
            running ? "animate-pulse bg-accent" : ""
          } ${b.state === "fresh" || b.finished ? "bg-success" : ""} ${
            b.state === "partial" ? "bg-warning" : ""
          } ${b.state === "stale" || b.state === "never" || b.state === "failed" ? "bg-muted" : ""}`}
        />
        <span className={`font-medium ${TONE[b.finished ? "done" : b.state]}`}>{b.text}</span>
        {b.hint ? <span className="text-muted">{b.hint}</span> : null}
        {b.finished ? (
          <button type="button" className="text-accent underline" onClick={() => window.location.reload()}>
            刷新页面查看
          </button>
        ) : null}
      </p>
      {running && p ? (
        <div className="mt-2 space-y-1.5">
          <ProgressBar aria-label="后台更新进度" value={pct} className="w-full">
            <ProgressBar.Track>
              <ProgressBar.Fill />
            </ProgressBar.Track>
          </ProgressBar>
          <div className="flex flex-wrap gap-x-2 gap-y-1 text-[11px] text-muted">
            {(p.steps || []).map((s, i) => (
              <span
                key={s.key || i}
                className={
                  STEP_TONE[s.state] ?? (i === (p.done || 0) && p.running ? "text-accent" : "text-muted/70")
                }
              >
                {s.label}
              </span>
            ))}
            {p.note ? <span className="num">{p.note}</span> : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
