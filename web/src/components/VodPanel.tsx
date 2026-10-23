import { useState } from "react";
import { Button, Skeleton, useMediaQuery } from "@heroui/react";
import { useElapsed } from "../hooks/useElapsed";
import type { SearchResult, VodItem } from "../types";
import { Poster, type DetailSpec } from "./Poster";
import { Dot, EmptyNote } from "./ui";

const MATCH_LABEL: Record<string, string> = { series: "同系列版本", contains: "近似名称", other: "模糊匹配" };

const GRID = "grid grid-cols-3 gap-x-4 gap-y-6 sm:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6";

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

function Card({ r, onDetail }: { r: VodItem; onDetail: (s: DetailSpec) => void }) {
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
  data,
  loading,
  error,
  ms,
  page,
  sourcesTotal,
  onPage,
  onDetail,
}: {
  kw: string;
  data: SearchResult | null;
  loading: boolean;
  error: string;
  ms: number;
  page: number;
  sourcesTotal: number;
  onPage: (p: number) => void;
  onDetail: (s: DetailSpec) => void;
}) {
  const sec = useElapsed(loading);
  // 一次并发 15 个源、服务端没有分源进度可问，所以只报"在跑 + 等了多久"，不编百分比
  const running = loading ? (
    <div className="space-y-2" role="status">
      <div className="bar-run" aria-hidden="true" />
      <p className="num text-xs text-muted">
        {page > 1 ? `正在取第 ${page} 页` : `正在并发查询「${kw}」· ${sourcesTotal} 个采集接口`} · 已等 {sec}s
        <span className="text-muted/70">（单个源最长 7 秒，慢源会被丢掉而不是拖住整轮）</span>
      </p>
    </div>
  ) : null;

  if (loading && !data) {
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
  if (!data) {
    return (
      <EmptyNote
        title="输入片名开始"
        tip={`回车即查，结果来自并发的采集接口。同一部片会合并多个来源，右下角「详情」看播放线路。`}
      />
    );
  }
  const d = data;
  if (!d.results.length) {
    const ascii = /^[\x00-\x7F]+$/.test(d.keyword) && /[A-Za-z]/.test(d.keyword);
    return (
      <EmptyNote
        title={`采集接口没有「${d.keyword}」的结果`}
        tip={
          (ascii
            ? "这些接口收的是中文片名，英文原名往往搜不到，试试中文译名（如 Oppenheimer → 奥本海默）。"
            : "可换个说法再搜（例如只留主标题、去掉季数），") + "或切到「网盘 · 磁力直达」用各站自己的搜索。"
        }
        extra="公开接口稳定性有限，稍后重试通常就有了。"
      />
    );
  }

  const hasMore = !!d.has_more && d.results.length > 0;
  return (
    <div className="space-y-5">
      {running}
      <p className="num flex flex-wrap items-center gap-x-2 text-xs text-muted">
        <span>
          命中 <b className="text-foreground">{d.results.length}</b> 部
        </span>
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
          用时 <b className="text-foreground">{ms}</b>ms
        </span>
      </p>

      <div className={GRID}>
        {d.results.map((r) => (
          <Card key={`${r.title}-${r.source}-${r.vid}`} r={r} onDetail={onDetail} />
        ))}
      </div>

      {/* 判"还有下一页"只看服务端那句：有没有哪个源把这一页正好填满。
          以前拿 hits 当页数依据，于是《庆余年》合并完只有 14 部、下一页还亮着，点进去一片空。 */}
      {hasMore || page > 1 ? (
        <div className="flex items-center justify-between border-t border-separator pt-4">
          <Button
            size="sm"
            variant="tertiary"
            className="rounded-full"
            isDisabled={page <= 1 || loading}
            onPress={() => onPage(page - 1)}
          >
            ‹ 上一页
          </Button>
          <span className="num text-xs text-muted">
            {loading && page > 1 ? `正在取第 ${page} 页…` : `第 ${page} 页`}
          </span>
          <Button
            size="sm"
            variant="tertiary"
            className="rounded-full"
            isDisabled={!hasMore || loading}
            onPress={() => onPage(page + 1)}
          >
            下一页 ›
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/** 接口状态：宽屏是右栏里一列表，窄屏默认折起来只留一行汇总。
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
