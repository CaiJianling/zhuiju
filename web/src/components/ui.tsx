import type { ReactNode } from "react";
import { Chip } from "@heroui/react";

/** 后端把站点状态给成 emoji（🟢🟡🔴⚪），这里统一换成一个色点：
 *  emoji 在表格里宽度不定、暗色下还特别跳，一排看下来根本扫不出谁有问题。 */
const DOT: Record<string, string> = {
  "🟢": "bg-success",
  "🟡": "bg-warning",
  "🔴": "bg-danger",
  "⚪": "bg-muted/60",
};

export function Dot({ dot, title }: { dot?: string; title?: string }) {
  return (
    <span
      aria-hidden="true"
      title={title}
      className={`inline-block size-2 shrink-0 rounded-full ${DOT[dot ?? ""] ?? "bg-muted/60"}`}
    />
  );
}

/** 推荐度：后端给的是 0..5 那个数，原来用 ★☆ 字符串渲染，字距一乱就长短不齐。
 *  这里画成实心/空心小方点，位置和数量都锁死。 */
export function Stars({ n }: { n?: number }) {
  const v = Math.max(0, Math.min(5, Number(n) || 0));
  return (
    <span className="inline-flex items-center gap-1" aria-label={`推荐 ${v} / 5`} title={`推荐 ${v} / 5`}>
      {[0, 1, 2, 3, 4].map((i) => (
        <span key={i} className={`size-1.5 rounded-full ${i < v ? "bg-accent" : "bg-border"}`} />
      ))}
    </span>
  );
}

export function Flag({ children }: { children: ReactNode }) {
  return (
    <Chip size="sm" variant="soft" color="default">
      {children}
    </Chip>
  );
}

/** 区块标题：一条细分隔线把标题和右侧的操作挤到同一基线上，
 *  比"标题 + 下面一行小字"省两层高度，长页面扫读时节奏更整齐 */
export function SectionHead({
  title,
  note,
  actions,
  id,
}: {
  title: ReactNode;
  note?: ReactNode;
  actions?: ReactNode;
  id?: string;
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1" id={id}>
      <h2 className="text-[15px] font-semibold tracking-wide text-foreground">{title}</h2>
      {note ? <span className="num text-xs text-muted">{note}</span> : null}
      <span className="h-px min-w-4 flex-1 self-center bg-separator" />
      {actions ? <span className="flex shrink-0 items-center gap-2 self-center">{actions}</span> : null}
    </div>
  );
}

export function Meta({ parts }: { parts: (string | number | undefined | false)[] }) {
  const list = parts.filter(Boolean).map(String);
  if (!list.length) return null;
  return <span className="num text-xs text-muted">{list.join(" · ")}</span>;
}

export function EmptyNote({ title, tip, extra }: { title: string; tip?: string; extra?: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-border bg-surface/60 px-5 py-8 text-center">
      <p className="text-sm font-medium text-foreground">{title}</p>
      {tip ? <p className="mx-auto mt-2 max-w-[46ch] text-xs leading-relaxed text-muted">{tip}</p> : null}
      {extra ? <p className="mt-2 text-xs text-muted/80">{extra}</p> : null}
    </div>
  );
}
