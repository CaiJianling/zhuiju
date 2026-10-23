import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Skeleton, Spinner, useMediaQuery } from "@heroui/react";
import { useElapsed } from "../hooks/useElapsed";
import { useClamp } from "../hooks/useClamp";
import type { SearchResult, Snapshot, VodItem } from "../types";
import type { Stack } from "../stack";
import { Poster, type DetailSpec } from "./Poster";
import { Dot, EmptyNote } from "./ui";

const MATCH_LABEL: Record<string, string> = { series: "同系列版本", contains: "近似名称", other: "模糊匹配" };

const GRID = "grid grid-cols-3 gap-x-4 gap-y-6 sm:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6";

/** 老浏览器没有 IntersectionObserver，自动追加就没有触发器；
 *  这种情况不闷着，底下换成一条手动"取下一页"的出口。 */
const ioOk = typeof IntersectionObserver !== "undefined";

export function specOf(r: VodItem, from: DetailSpec["from"] = "card"): DetailSpec {
  return {
    title: r.title,
    pic: r.pic,
    year: r.year,
    area: r.area,
    type: r.type,
    remarks: r.remarks,
    actor: r.actor,
    director: r.director,
    src: r.source,
    vid: r.vid,
    n: r.sources.length,
    sources: r.sources.map((s) => ({ id: s.id, name: s.name, vid: s.vid ?? "" })),
    from,
  };
}

function Card({ r, onDetail }: { r: VodItem; onDetail: (s: DetailSpec, from?: HTMLElement | null) => void }) {
  return (
    <Poster
      title={r.title}
      pic={r.pic}
      href={`/s/${encodeURIComponent(r.title)}`}
      meta={[r.year, r.type, r.area]}
      flags={[
        r.match === "exact" ? "" : MATCH_LABEL[r.match] || "模糊匹配",
        r.sources.length > 1 ? `${r.sources.length} 个源` : "",
      ]}
      spec={specOf(r)}
      onDetail={onDetail}
    />
  );
}

export function VodPanel({
  kw,
  stack,
  loading,
  appending,
  error,
  sourcesTotal,
  onLoadMore,
  onDetail,
}: {
  kw: string;
  stack: Stack | null;
  loading: boolean;
  appending: boolean;
  error: string;
  sourcesTotal: number;
  onLoadMore: () => void;
  onDetail: (s: DetailSpec, from?: HTMLElement | null) => void;
}) {
  const sec = useElapsed(loading || appending);
  // 自动接着取：观察结果末尾那颗哨兵。为什么不是"点按钮"—— 一次并发 15 个源，
  // 滚到末尾的人就是想看更多，替他多点一次没意义；触发条件里卡着"还有下一页、
  // 此刻没在取、上一轮没出错"，取到重复的了服务端那句 has_more 会把它关掉。
  //
  // 这两个 hook 必须待在所有提前 return 之前：第一帧还在 loading、stack 还是 null，
  // 会走上面那条 "if (loading && !stack) return"；等结果到货的第二帧才碰到它们，
  // React 就判"这一帧比上一帧多了 hook"（#310），把整棵树卸载成黑屏。
  const sentinel = useRef<HTMLDivElement>(null);
  const canAuto = !!stack && stack.hasMore && !loading && !appending && !error && ioOk;
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !canAuto || !stack) return;
    // rootMargin 提前 200px：等人真的贴到底再发请求，慢源那一轮要 7 秒，会看着像卡住
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) onLoadMore();
      },
      { rootMargin: "200px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
    // items.length / appending 变了要重挂：观察对象换了位置，
    // 而且每次重挂都会立刻重算一次"看不看得见"，于是能一屏接一屏地连着滚
  }, [canAuto, onLoadMore, stack?.items.length, appending]);

  // 一次并发 15 个源、服务端没有分源进度可问，所以只报"在跑 + 等了多久"，不编百分比
  const running = loading ? (
    <div className="space-y-2" role="status">
      <div className="bar-run" aria-hidden="true" />
      <p className="num text-xs text-muted">
        {stack ? "正在重取这一叠" : `正在并发查询「${kw}」· ${sourcesTotal} 个采集接口`} · 已等 {sec}s
        <span className="text-muted/70">（单个源最长 7 秒，慢源会被丢掉而不是拖住整轮）</span>
      </p>
    </div>
  ) : null;

  if (loading && !stack) {
    return (
      <div className="space-y-4">
        {running}
        <div className={GRID} aria-hidden="true">
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="flex flex-col gap-2">
              <Skeleton className="aspect-2/3 rounded-xl" />
              <Skeleton className="h-3 w-4/5 rounded" />
              <Skeleton className="h-3 w-2/5 rounded" />
            </div>
          ))}
        </div>
      </div>
    );
  }
  if (error) {
    return <EmptyNote title="这次没查到" tip={error} extra="公开接口稳定性有限，稍后重试通常就有了。" />;
  }
  if (!stack) {
    return (
      <EmptyNote
        title="输入片名开始"
        tip={`回车即查，结果来自并发的采集接口。同一部片会合并多个来源，右下角「详情」看播放线路。`}
      />
    );
  }
  const d = stack;
  if (!d.items.length) {
    const ascii = /^[\x00-\x7F]+$/.test(d.kw) && /[A-Za-z]/.test(d.kw);
    return (
      <EmptyNote
        title={`采集接口没有「${d.kw}」的结果`}
        tip={
          (ascii
            ? "这些接口收的是中文片名，英文原名往往搜不到，试试中文译名（如 Oppenheimer → 奥本海默）。"
            : "可换个说法再搜（例如只留主标题、去掉季数），") + "或切到「网盘 · 磁力直达」用各站自己的搜索。"
        }
        extra="公开接口稳定性有限，稍后重试通常就有了。"
      />
    );
  }

  const paged = d.pages - d.from + 1;

  return (
    <div className="space-y-5">
      {running}
      <p className="num flex flex-wrap items-center gap-x-2 text-xs text-muted">
        <span>
          命中 <b className="text-foreground">{d.items.length}</b> 部
        </span>
        {paged > 1 ? (
          <>
            <span className="text-separator">·</span>
            <span>
              已并 <b className="text-foreground">{paged}</b> 页（第 {d.from}–{d.pages} 页）
            </span>
          </>
        ) : null}
        <span className="text-separator">·</span>
        <span>
          接口返回 <b className="text-foreground">{d.hits}</b> 条
        </span>
        {d.dropped_noise ? (
          <>
            <span className="text-separator">·</span>
            <span>
              已过滤 <b className="text-foreground">{d.dropped_noise}</b> 条无关结果
            </span>
          </>
        ) : null}
        <span className="text-separator">·</span>
        <span>
          可用源 <b className="text-foreground">{d.sources_ok}/{d.sources_total}</b>
        </span>
        <span className="text-separator">·</span>
        <span>
          用时 <b className="text-foreground">{d.ms}</b>ms
        </span>
      </p>

      <div className={GRID}>
        {d.items.map((r) => (
          <Card key={`${r.title}-${r.source}-${r.vid}`} r={r} onDetail={onDetail} />
        ))}
      </div>

      {/* 追加状态就说追加的事：第几页在并进来、并到第几页、为什么不再往下要了。
          判"还有下一页"只看服务端那句（有没有哪个源把这一页正好填满），
          再加上"这一页并进来一部新片都没有"也算到头。 */}
      <div ref={sentinel} className="border-t border-separator pt-4">
        {appending ? (
          <p className="num flex items-center gap-2 text-xs text-muted" role="status">
            <Spinner size="sm" className="text-accent" />
            正在把第 {d.pages + 1} 页并进来 · 已等 {sec}s
          </p>
        ) : canAuto ? (
          <p className="num text-xs text-muted">
            往下滚接着取第 {d.pages + 1} 页（并进来时同一部片合成一张卡，不会重复出现）
          </p>
        ) : d.hasMore ? (
          // 没有 IntersectionObserver 的老浏览器：自动触发就是空的，给一条手动出口
          <Button size="sm" variant="tertiary" className="rounded-full" onPress={onLoadMore}>
            取第 {d.pages + 1} 页
          </Button>
        ) : (
          <p className="text-xs text-muted">
            {d.stalled
              ? `再往下各源开始重复了（第 ${d.pages} 页没并进一部新片），就到这里。`
              : `没有下一页了：第 ${d.pages} 页没有任何一个源填满，${d.kw} 在各源就这么多。`}
          </p>
        )}
      </div>
    </div>
  );
}

/** 接口状态：宽屏是右栏里一列表，窄屏默认折起来只留一行汇总。
 *  手机上这 15 行本来就没人逐条看，展开前它占了半屏，把结果顶到看不见；
 *  但它又必须一眼能查到（"是不是某个源挂了"），所以标题那行始终带着 N/M 可用。 */
/** 检索快照那一栏。它本来就是给爬虫与禁用 JS 的那一份服务端渲染（JSON-LD 也读同一份数据），
 *  对开着 JS 的人而言和左边的结果列表高度重复 —— 所以窄屏排到最底部并默认折起，
 *  展开后也只给 6 行的高度，在框里自己滚，不把整页撑长。宽屏留在右栏里默认展开。 */
export function SnapshotCard({ kw, snapshot, description }: { kw: string; snapshot: Snapshot; description: string }) {
  const wide = useMediaQuery("(min-width: 1280px)");
  const [open, setOpen] = useState<boolean | null>(null);
  const shown = open ?? wide;
  const items = snapshot.items || [];

  // 6 行那个高度与后台表格的限高是同一件事，共用 useClamp（量第 7 条的 offsetTop、
  // 补滚动条那几像素、首测同步跑 —— 这三条都在 useClamp 的注释里写着为什么）
  const setBox = useClamp(
    useCallback((el: HTMLElement) => {
      const lis = el.querySelectorAll("li");
      if (lis.length <= 6) return null;
      const h = (lis[6] as HTMLElement).offsetTop;
      el.style.maxHeight = `${h}px`;
      return h + (el.offsetHeight - el.clientHeight);
    }, []),
  );

  if (!items.length) return null;

  return (
    <section className="rounded-2xl bg-surface p-4 text-surface-foreground shadow-surface ring-1 ring-border">
      <h2 className="text-[13px] font-semibold">
        <button
          type="button"
          aria-expanded={shown}
          onClick={() => setOpen(!shown)}
          className="flex w-full items-baseline justify-between gap-2 text-left"
        >
          <span className="min-w-0 truncate">《{kw}》的检索结果</span>
          <span className="flex shrink-0 items-center gap-1.5 text-[11px] font-normal text-muted">
            <span className="num">
              {snapshot.sources_ok || 0}/{snapshot.sources_total || 0} 源 · {snapshot.count || items.length} 条
            </span>
            <svg
              viewBox="0 0 24 24"
              className={`size-3.5 transition-transform ${shown ? "rotate-180" : ""}`}
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              aria-hidden="true"
            >
              <path d="M6 9l6 6 6-6" />
            </svg>
          </span>
        </button>
      </h2>
      {shown ? (
        <>
          <p className="mt-1.5 text-[11px] leading-relaxed text-muted">{description}</p>
          <div ref={setBox} className="scroll-thin relative mt-3 overflow-y-auto">
            <ul className="space-y-1.5">
              {items.map((it, i) => (
                <li key={`${it.title}-${i}`} className="text-xs leading-snug">
                  <a className="text-foreground hover:text-accent" href={it.url}>
                    {it.title}
                  </a>
                  <span className="num block text-[11px] text-muted">
                    {[it.year, it.type, it.remarks].filter(Boolean).join(" · ")}
                    {it.n_sources ? ` · ${it.n_sources} 个源` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <p className="mt-2 text-[10px] leading-relaxed text-muted/80">
            这一份是服务端为该关键词存的快照：搜索引擎抓到的、以及禁用 JavaScript 时看到的都是它。
          </p>
        </>
      ) : null}
    </section>
  );
}

/** 接口状态：宽屏是右栏里一列表，窄屏默认折起只留一行汇总。
 *  手机上这 15 行本来就没人逐条看，展开前它占了半屏，把结果顶到看不见；
 *  但它又必须一眼能查到（"是不是某个源挂了"），所以标题那行始终带着 N/M 可用。 */
export function SourcesPanel({ rows, sum }: { rows: SearchResult["status"]; sum: string }) {
  const wide = useMediaQuery("(min-width: 1280px)");
  // null = 用户没动过，跟着屏宽走（宽屏展开、窄屏折叠）
  const [open, setOpen] = useState<boolean | null>(null);
  const shown = open ?? wide;
  if (!rows.length) return null;
  return (
    <section className="rounded-2xl bg-surface p-4 text-surface-foreground shadow-surface ring-1 ring-border">
      <h2 className="flex items-baseline justify-between gap-2 text-[13px] font-semibold">
        <button
          type="button"
          aria-expanded={shown}
          onClick={() => setOpen(!shown)}
          className="flex flex-1 items-center justify-between gap-2 text-left"
        >
          接口状态
          <span className="flex items-center gap-1.5 text-[11px] font-normal text-muted">
            <span className="num">{sum}</span>
            <svg
              viewBox="0 0 24 24"
              className={`size-3.5 transition-transform ${shown ? "rotate-180" : ""}`}
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              aria-hidden="true"
            >
              <path d="M6 9l6 6 6-6" />
            </svg>
          </span>
        </button>
      </h2>
      {shown ? (
        <ul className="mt-3 space-y-1.5">
          {rows.map((s) => (
            <li key={s.source} className="grid grid-cols-[7px_minmax(0,1fr)_auto_46px] items-center gap-2 text-[11px]">
              <Dot dot={s.ok ? "🟢" : "🔴"} />
              <span className="truncate text-foreground" title={s.error || s.source_name}>
                {s.source_name}
              </span>
              <span className="num text-right text-muted">{s.count}</span>
              <span className={`num text-right ${s.ok && s.ms > 3000 ? "text-warning" : "text-muted/80"}`}>
                {s.ok ? `${s.ms}ms` : "—"}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
