import { useCallback, useEffect, useRef, useState } from "react";
import { Tabs, toast, Toast } from "@heroui/react";
import { api, isGate, sendClick } from "./api";
import { useAuthTick, useGateLocked } from "./auth";
import { boot } from "./boot";
import { useRefresh } from "./hooks/useRefresh";
import type { CatalogResult, CloudResult, DeeplinksResult, HotRow, SearchResult } from "./types";
import { DetailDrawer } from "./components/DetailDrawer";
import { GateModal, LockedView } from "./components/Gate";
import { HotSection, hotNote } from "./components/HotSection";
import { HowTo } from "./components/HowTo";
import { DeepPanel, CloudPanel, DirPanel } from "./components/OtherPanels";
import type { DetailSpec } from "./components/Poster";
import { SearchBar } from "./components/SearchBar";
import { SourcesPanel, VodPanel } from "./components/VodPanel";
import { StatusLine } from "./components/StatusLine";
import { ThemeToggle } from "./components/ThemeToggle";

type Tab = "vod" | "cloud" | "deep" | "dir";

const landingUrl = (kw: string, page: number) =>
  `/s/${encodeURIComponent(kw)}${page > 1 ? `?page=${page}` : ""}`;

const parseUrl = (): { kw: string; page: number } => {
  const m = location.pathname.match(/^\/s\/(.+)$/);
  return {
    kw: m ? decodeURIComponent(m[1]) : "",
    page: Math.max(1, Number(new URLSearchParams(location.search).get("page") || 1) || 1),
  };
};

/** 与 shell.html 里服务端写的那份形状保持一致：有词 = ItemList，无词 = WebSite + SearchAction。
 *  爬虫不执行这段，它看到的始终是服务端渲染那一份；这里同步是为了"另存/分享这一页"时
 *  结构性数据跟当前词对得上，宁可新写一份也别留着旧的。 */
function setHead(sel: string, attr: string, val: string) {
  const el = document.head.querySelector(sel);
  if (el) el.setAttribute(attr, val);
}

function syncSeo(kw: string, d: SearchResult | null) {
  if (!kw) {
    document.title = boot.title;
    setHead('meta[name="description"]', "content", boot.description);
    setHead('link[rel="canonical"]', "href", boot.canonical);
    setHead('meta[property="og:title"]', "content", boot.title);
    setHead('meta[property="og:description"]', "content", boot.description);
    setHead('meta[property="og:url"]', "content", boot.canonical);
    return;
  }
  const one = location.origin + landingUrl(kw, 1);
  const items = d?.results || [];
  const title = `《${kw}》影视资源怎么找 - 追剧资源搜索`;
  const desc =
    `《${kw}》相关影视资源 ${items.length} 部，来自 ${(d?.sources_ok || 0)} 个采集接口，` +
    "含网盘、磁力与资源站直达入口。";
  document.title = title;
  setHead('link[rel="canonical"]', "href", one);
  setHead('meta[name="description"]', "content", desc);
  setHead('meta[property="og:title"]', "content", title);
  setHead('meta[property="og:description"]', "content", desc);
  setHead('meta[property="og:url"]', "content", one);
  const ld = document.querySelector('script[type="application/ld+json"]');
  if (ld) {
    ld.textContent = JSON.stringify({
      "@context": "https://schema.org",
      "@type": "ItemList",
      name: `《${kw}》相关影视资源`,
      numberOfItems: items.length,
      itemListElement: items.slice(0, 12).map((it, i) => ({
        "@type": "ListItem",
        position: i + 1,
        name: it.title,
        url: `${location.origin}/s/${encodeURIComponent(it.title)}`,
      })),
    });
  }
}

export default function App() {
  const locked = useGateLocked();
  const tick = useAuthTick();
  const [kw, setKw] = useState(boot.kw);
  const [page, setPage] = useState(boot.page || 1);
  const [tab, setTab] = useState<Tab>("vod");
  const [search, setSearch] = useState<{ data: SearchResult | null; loading: boolean; error: string; ms: number }>({
    data: null,
    loading: !!boot.kw,
    error: "",
    ms: 0,
  });
  const [deep, setDeep] = useState<DeeplinksResult | null>(null);
  const [cat, setCat] = useState<CatalogResult | null>(null);
  const [category, setCategory] = useState("");
  const [cloud, setCloud] = useState<CloudResult | null>(null);
  const [cloudState, setCloudState] = useState<"idle" | "loading" | "error">("idle");
  const [cloudError, setCloudError] = useState("");
  // 门闩用 ref 而不是 state：写进依赖里会让这个 effect 自己重跑一遍，
  // 于是刚发出的 /api/cloud 被自己的 cleanup abort 掉（第一版就是这么翻车的）
  const cloudDone = useRef<string | null>(null);
  const [spec, setSpec] = useState<DetailSpec | null>(null);
  const rf = useRefresh(boot.refresh);

  /* 关键词与页码是唯一的真相：URL、标题、取数全都跟着它们走。
     换词 push 一条历史（后退能回到上一个词），同一个词翻页只 replace
     （后退不该一格一格走过整本翻页）。 */
  const commit = useCallback((nextKw: string, nextPage: number, isNewWord: boolean) => {
    setKw(nextKw);
    setPage(nextPage);
    const url = nextKw ? landingUrl(nextKw, nextPage) : "/";
    if (location.pathname + location.search === url) return;
    if (isNewWord) history.pushState({ kw: nextKw, page: nextPage }, "", url);
    else history.replaceState({ kw: nextKw, page: nextPage }, "", url);
  }, []);

  const goSearch = useCallback(
    (raw: string) => {
      const next = raw.trim().slice(0, 60);
      if (next.length < 2) {
        toast.warning("关键词至少 2 个字");
        return;
      }
      if (next === kw) {
        commit(next, 1, false);
        return;
      }
      commit(next, 1, true);
    },
    [commit, kw],
  );

  const goHome = useCallback(() => {
    commit("", 1, true);
    setSearch({ data: null, loading: false, error: "", ms: 0 });
    setCloud(null);
    setCloudState("idle");
    setCloudError("");
    cloudDone.current = null;
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [commit]);

  useEffect(() => {
    const onPop = () => {
      const { kw: nkw, page: np } = parseUrl();
      setKw(nkw);
      setPage(np);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => syncSeo(kw, search.data), [kw, search.data]);

  useEffect(() => {
    if (!kw) return;
    const ac = new AbortController();
    const t0 = performance.now();
    setSearch((s) => ({ ...s, loading: true, error: "" }));
    api
      .search(kw, page, ac.signal)
      .then((d) => setSearch({ data: d, loading: false, error: "", ms: Math.round(performance.now() - t0) }))
      .catch((e) => {
        if ((e as Error).name === "AbortError") return;
        setSearch((s) => ({ ...s, loading: false, error: isGate(e) ? "等你验证完自动重查。" : (e as Error).message }));
      });
    return () => ac.abort();
  }, [kw, page, tick]);

  // 直达清单只要换了词就取一次：它不联网抓结果，只是一份带关键词的链接表，很便宜
  useEffect(() => {
    if (!kw) {
      setDeep(null);
      return;
    }
    const ac = new AbortController();
    api.deeplinks(kw, ac.signal).then(setDeep).catch(() => {});
    return () => ac.abort();
  }, [kw, tick]);

  // 网盘查询要十几秒，目录只是一份本地清单：都等真的切到那一栏再发
  useEffect(() => {
    if (tab !== "cloud" || cloudDone.current === kw) return;
    const ac = new AbortController();
    cloudDone.current = kw;
    setCloud(null);
    setCloudState("loading");
    setCloudError("");
    api
      .cloud(kw, ac.signal)
      .then((d) => {
        setCloud(d);
        setCloudState("idle");
      })
      .catch((e) => {
        if ((e as Error).name === "AbortError") {
          if (cloudDone.current === kw) cloudDone.current = null;
          return;
        }
        // 423 不算失败：验证过了 tick 会把这一栏重跑一遍
        if (!isGate(e)) {
          setCloudState("error");
          setCloudError((e as Error).message);
        }
        cloudDone.current = null; // 失败过就该让人再进来时重试，不然这一栏永远卡在错误上
      });
    return () => ac.abort();
  }, [tab, kw, tick]);

  useEffect(() => {
    if (tab !== "dir") return;
    const ac = new AbortController();
    api
      .catalog({ category, link_kw: kw }, ac.signal)
      .then(setCat)
      .catch(() => {});
    return () => ac.abort();
  }, [tab, category, kw, tick]);

  const openDetail = useCallback(
    (s: DetailSpec) => {
      sendClick({
        kind: "detail",
        kw,
        title: s.title,
        src: s.src || "",
        vid: String(s.vid ?? ""),
        place: s.from,
      });
      setSpec(s);
    },
    [kw],
  );

  if (locked && boot.locked) {
    return (
      <LockedView
        hours={boot.gate_hours}
        back={boot.back}
        description={boot.description}
      />
    );
  }

  const hot = boot.hot;
  const showSsr = !!kw && kw === boot.kw && !!boot.snapshot.items?.length;
  const groupOf = (kind: "movie" | "tv"): { rows: HotRow[]; total: number } & typeof hot => {
    const list = (hot[kind] || []) as HotRow[];
    return { ...hot, rows: list, total: (hot[`${kind}_total`] as number) ?? list.length };
  };

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b border-separator bg-surface/80 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-3 px-4 sm:px-6">
          <h1 className="flex items-baseline gap-2 text-sm font-semibold tracking-wide">
            追剧资源搜索
            <span className="rounded-full bg-default px-1.5 py-0.5 text-[10px] font-normal text-muted">本地版</span>
          </h1>
          <span className="flex-1" />
          <HowTo />
          <ThemeToggle />
          <a
            href="/admin"
            rel="nofollow"
            className="text-xs text-muted/70 transition hover:text-foreground"
            title="后台统计"
          >
            统计
          </a>
        </div>
      </header>

      <main className="mx-auto max-w-[1440px] px-4 pb-20 sm:px-6">
        <div className="pt-6">
          <SearchBar initial={boot.kw} onSearch={goSearch} onHome={goHome} />
          {rf ? <StatusLine b={rf} /> : null}
        </div>

        <Tabs
          className="mt-6 w-full"
          selectedKey={tab}
          onSelectionChange={(k) => setTab(k as Tab)}
        >
          <Tabs.ListContainer>
            <Tabs.List aria-label="四种查法" className="gap-1">
              {(
                [
                  ["vod", "影视资源"],
                  ["cloud", "网盘查询"],
                  ["deep", "网盘 · 磁力直达"],
                  ["dir", "资源站目录"],
                ] as [Tab, string][]
              ).map(([k, label]) => (
                <Tabs.Tab key={k} id={k}>
                  {label}
                  <Tabs.Indicator />
                </Tabs.Tab>
              ))}
            </Tabs.List>
          </Tabs.ListContainer>

          <Tabs.Panel id="vod" className="pt-5">
            {kw ? (
              <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
                <VodPanel
                  kw={kw}
                  data={search.data}
                  loading={search.loading}
                  error={search.error}
                  ms={search.ms}
                  page={page}
                  sourcesTotal={boot.sources.length}
                  onPage={(p) => commit(kw, p, false)}
                  onDetail={openDetail}
                />
                <aside className="order-first space-y-4 self-start xl:order-none xl:sticky xl:top-20">
                  {showSsr ? (
                    <section className="rounded-2xl bg-surface p-4 shadow-surface ring-1 ring-border">
                      <h2 className="text-[13px] font-semibold">《{kw}》的检索结果</h2>
                      <p className="mt-1.5 text-[11px] leading-relaxed text-muted">{boot.description}</p>
                      <ul className="mt-3 space-y-1.5">
                        {boot.snapshot.items!.map((it, i) => (
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
                    </section>
                  ) : null}
                  {search.data ? (
                    <SourcesPanel
                      rows={search.data.status}
                      sum={`${search.data.sources_ok}/${search.data.sources_total} 可用`}
                    />
                  ) : null}
                </aside>
              </div>
            ) : (
              <p className="rounded-2xl bg-surface px-4 py-3 text-xs text-muted ring-1 ring-border">
                输入片名回车即查，结果来自 <b className="num text-foreground">{boot.sources.length}</b> 个已实测可用的公开采集接口。
                <span className="text-foreground">下面「猜你想搜」</span>
                是最近一年上榜的成品，可以整行翻着挑。不清楚规矩就点右上角「怎么用」。
              </p>
            )}
          </Tabs.Panel>

          <Tabs.Panel id="cloud" className="pt-5">
            <CloudPanel data={cloud} loading={cloudState === "loading"} error={cloudError} />
          </Tabs.Panel>

          <Tabs.Panel id="deep" className="pt-5">
            <DeepPanel data={deep} kw={kw} />
          </Tabs.Panel>

          <Tabs.Panel id="dir" className="pt-5">
            <DirPanel
              data={cat}
              loading={!cat}
              error=""
              categories={boot.categories}
              category={category}
              onCategory={setCategory}
            />
          </Tabs.Panel>
        </Tabs>

        {!kw ? (
          <div className="mt-10 space-y-10">
            <p className="text-xs text-muted">{hotNote(hot)}</p>
            {groupOf("movie").rows.length ? (
              <HotSection kind="movie" label="电影" boot={groupOf("movie")} onDetail={openDetail} />
            ) : null}
            {groupOf("tv").rows.length ? (
              <HotSection kind="tv" label="电视剧" boot={groupOf("tv")} onDetail={openDetail} />
            ) : null}
            {hot.building ? (
              <p className="text-xs text-muted">近期榜单正在后台生成（约需 1–2 分钟，缓存 6 小时），稍后刷新即可看到。</p>
            ) : null}
          </div>
        ) : null}
      </main>

      <footer className="border-t border-separator py-6">
        <div className="mx-auto max-w-[1440px] px-4 text-[11px] leading-relaxed text-muted sm:px-6">
          <p>本工具只做第三方公开接口的聚合查询，不存储、不转发任何影视内容；结果链接指向外部站点，请注意甄别广告、跳转与个人信息安全。</p>
          <p className="mt-1 text-muted/70">
            仅供个人技术学习与找片参考，请支持正版。 · 本地运行，数据不出这台电脑 ·{" "}
            <a href="/admin" rel="nofollow" className="hover:text-foreground">
              统计
            </a>
          </p>
        </div>
      </footer>

      <DetailDrawer spec={spec} onClose={() => setSpec(null)} />
      <GateModal open={locked && !boot.locked} onok={() => {}} />
      <Toast.Provider placement="bottom" />
    </div>
  );
}
