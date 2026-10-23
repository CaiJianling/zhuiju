import { Button } from "@heroui/react";
import type { CatalogResult, CloudResult, CloudSite, DeeplinksResult } from "../types";
import { Dot, EmptyNote, SectionHead, Stars } from "./ui";

function Group({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2.5">
      <SectionHead title={title} note={note} />
      {children}
    </div>
  );
}

const HEAD = "flex min-w-0 items-baseline gap-x-2 gap-y-0.5 text-xs";

/** 网盘查询：有词时服务端真去各站抓了一遍结果页；没词时只列这一页会用到的站，一个都不抓。 */
export function CloudPanel({
  data,
  loading,
  error,
}: {
  data: CloudResult | null;
  loading: boolean;
  error: string;
}) {
  if (loading && !data) {
    return (
      <div className="space-y-3">
        <p className="text-xs text-muted">正在并发抓取网盘 / 磁力站的搜索结果页…</p>
        <div className="grid gap-3 sm:grid-cols-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-2xl bg-default/60" />
          ))}
        </div>
        <p className="text-[11px] text-muted">解析各站结果页中，站点较多时约需十几秒。</p>
      </div>
    );
  }
  if (error) return <EmptyNote title="查询失败" tip={error} />;
  if (!data) return <EmptyNote title="正在读站点清单" tip="只读目录，不联网。" />;

  if (data.mode === "sites") {
    const sites = data.sites || [];
    const q = sites.filter((s) => s.can_query);
    const nq = sites.filter((s) => !s.can_query);
    const row = (s: CloudSite) => (
      <div key={s.id} className="rounded-2xl bg-surface p-3.5 shadow-surface ring-1 ring-border">
        <div className={HEAD}>
          <b className="truncate text-foreground">{s.name}</b>
          <span className="shrink-0 text-muted">{s.category}</span>
          <span className="ml-auto shrink-0">
            <Stars n={s.recommended} />
          </span>
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-muted">
          {s.can_query
            ? "有已验证的 GET 搜索模板，输入片名后本站会直接抓它的结果页。"
            : s.status && s.status !== "可访问"
              ? `该站状态是「${s.status}」，服务端抓不动，只能在浏览器里打开它自己搜。`
              : "搜索是 POST 表单或 JS 提交，服务端抓不到结果，只能打开该站自行搜索。"}{" "}
          <a className="text-accent underline" href={s.home} target="_blank" rel="noopener noreferrer">
            打开该站 ↗
          </a>
        </p>
        {s.can_query && s.search_url ? (
          <p className="num mt-2 truncate rounded bg-default/70 px-2 py-1 text-[10px] text-muted" title={s.search_url}>
            {s.search_url}
          </p>
        ) : null}
      </div>
    );
    return (
      <div className="space-y-6">
        <p className="text-xs text-muted">
          还没输入片名 · 先列出这一页会用到的 <b className="num text-foreground">{sites.length}</b> 个站，
          本站能直接搜出结果的是 <b className="num text-foreground">{q.length}</b> 个
        </p>
        {q.length ? (
          <Group title="本站能直接搜出结果">
            <div className="grid gap-3 sm:grid-cols-2">{q.map(row)}</div>
          </Group>
        ) : null}
        <Group title="只能打开该站自己搜">
          <div className="space-y-2.5">{nq.map(row)}</div>
        </Group>
        <p className="text-[11px] leading-relaxed text-muted">
          这份清单不联网：站与状态都来自资源站目录，"能不能直接搜"按有没有已验证的 GET 搜索模板判断，
          点这个标签页不会去抓这 {sites.length} 个站。想在这一页看到结果，在上面搜一个片名再进来。
        </p>
      </div>
    );
  }

  const sites = data.sites || [];
  const withRes = sites.filter((s) => s.ok);
  const noRes = sites.filter((s) => !s.ok);
  return (
    <div className="space-y-6">
      <p className="num text-xs text-muted">
        查询 <b className="text-foreground">{data.keyword}</b> · {sites.length} 个网盘 / 磁力站，其中{" "}
        <b className="text-foreground">{data.with_results}</b> 个解析出结果，共 <b className="text-foreground">{data.entries}</b> 条
      </p>
      {withRes.length ? (
        <Group title="已解析出结果">
          <div className="grid gap-3 sm:grid-cols-2">
            {withRes.map((s) => (
              <div key={s.id} className="rounded-2xl bg-surface p-3.5 shadow-surface ring-1 ring-border">
                <div className={HEAD}>
                  <b className="truncate text-foreground">{s.name}</b>
                  <span className="shrink-0 text-muted">{s.category}</span>
                  <span className="num ml-auto shrink-0 text-muted">{s.count} 条</span>
                </div>
                <ul className="mt-2 max-h-44 space-y-1 overflow-auto">
                  {(s.items || []).map((it, i) => (
                    <li key={`${it.link}-${i}`}>
                      <a
                        href={it.link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block truncate rounded px-1.5 py-1 text-xs text-foreground transition hover:bg-accent-soft hover:text-accent-soft-foreground"
                        title={it.title}
                      >
                        {it.title}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </Group>
      ) : null}
      <Group title="无法在服务端取到结果">
        <div className="space-y-2">
          {noRes.map((s) => (
            <div key={s.id} className="rounded-2xl bg-surface/60 p-3 ring-1 ring-border">
              <div className={HEAD}>
                <Dot dot="🔴" />
                <b className="truncate text-foreground">{s.name}</b>
                <span className="shrink-0 text-muted">{s.category}</span>
              </div>
              <p className="mt-1.5 text-[11px] leading-relaxed text-muted">
                {s.error || "未返回结果"}{" "}
                {s.search_url ? (
                  <a className="text-accent underline" href={s.search_url} target="_blank" rel="noopener noreferrer">
                    打开该站搜索页 ↗
                  </a>
                ) : null}
              </p>
            </div>
          ))}
        </div>
      </Group>
    </div>
  );
}

/** 网盘 · 磁力直达：不抓结果，只把片名带到各站自己的搜索页 */
export function DeepPanel({ data, kw }: { data: DeeplinksResult | null; kw: string }) {
  const items = data?.items || [];
  if (!items.length) {
    return <EmptyNote title="直达清单读不出来" tip="目录里没有可用的站内搜索路径时这一栏就是空的。" />;
  }
  const cats: Record<string, typeof items> = {};
  items.forEach((it) => {
    (cats[it.category] ||= []).push(it);
  });
  return (
    <div className="space-y-6">
      {Object.entries(cats).map(([cat, list]) => (
        <Group key={cat} title={cat} note={kw ? `用「${kw}」直达搜索` : `共 ${list.length} 站，搜索后自动带上关键词`}>
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {list.map((it) => (
              <a
                key={it.url}
                href={it.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 rounded-xl bg-surface px-3 py-2.5 text-xs ring-1 ring-border transition hover:ring-accent/50"
              >
                <Dot dot={it.dot} />
                <span className="min-w-0 flex-1">
                  <b className="block truncate text-foreground">{it.name}</b>
                  <span className="block truncate text-[11px] text-muted">
                    {it.status}
                    {it.kind === "site_search" ? "" : kw ? " · 未验证站内搜索路径，打开首页自行搜索" : " · 打开首页"}
                  </span>
                </span>
                <Stars n={it.recommended} />
              </a>
            ))}
          </div>
        </Group>
      ))}
    </div>
  );
}

/** 资源站目录：按分类浏览收录的站点，不拿影片名去"匹配站点" */
export function DirPanel({
  data,
  loading,
  error,
  categories,
  category,
  onCategory,
}: {
  data: CatalogResult | null;
  loading: boolean;
  error: string;
  categories: { name: string; total: number; working: number }[];
  category: string;
  onCategory: (c: string) => void;
}) {
  const cats = data?.categories || categories;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1.5">
        <Button
          size="sm"
          variant={category === "" ? "primary" : "tertiary"}
          className="rounded-full"
          onPress={() => onCategory("")}
        >
          全部
        </Button>
        {cats.map((c) => (
          <Button
            key={c.name}
            size="sm"
            variant={category === c.name ? "primary" : "tertiary"}
            className="rounded-full"
            onPress={() => onCategory(c.name)}
          >
            {c.name} <span className="num opacity-70">{c.working}/{c.total}</span>
          </Button>
        ))}
      </div>
      {error ? (
        <EmptyNote title="目录读不出来" tip={error} />
      ) : loading && !data ? (
        <p className="py-8 text-center text-xs text-muted">正在读目录…</p>
      ) : !data?.items.length ? (
        <EmptyNote title="该分类下暂无可显示的站点" tip="换个分类，或等自动更新拉到新的目录。" />
      ) : (
        <ul className="divide-y divide-separator overflow-hidden rounded-2xl bg-surface ring-1 ring-border">
          {data.items.map((it) => (
            <li key={it.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3.5 py-2.5 text-xs">
              <Dot dot={it.dot} />
              <span className="w-40 shrink-0 truncate font-medium text-foreground" title={it.name}>
                {it.name}
              </span>
              <span className="w-20 shrink-0 text-muted">{it.category_cn}</span>
              <span className="min-w-0 flex-1 truncate text-muted" title={[...it.tags, ...it.hints].join(" / ")}>
                {[...it.tags, ...it.hints].join(" / ")}
              </span>
              <Stars n={it.recommended} />
              <span className="flex shrink-0 gap-2">
                <a className="text-accent underline" href={it.url} target="_blank" rel="noopener noreferrer">
                  首页 ↗
                </a>
                {it.deep ? (
                  <a className="text-accent underline" href={it.deep.url} target="_blank" rel="noopener noreferrer">
                    搜此片 ↗
                  </a>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
