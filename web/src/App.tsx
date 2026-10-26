import { useCallback, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { Tabs, toast, Toast } from "@heroui/react";
import { api, isGate, sendClick } from "./api";
import { useAuthTick, useGateLocked } from "./auth";
import { boot } from "./boot";
import { useRefresh } from "./hooks/useRefresh";
import { appendPage, stackFrom, type Stack } from "./stack";
import type { CatalogResult, CloudResult, DeeplinksResult, HotRow, Snapshot } from "./types";
import { DetailDrawer } from "./components/DetailDrawer";
import { GateModal, LockedView } from "./components/Gate";
import { HotSection, hotNote } from "./components/HotSection";
import { HowTo } from "./components/HowTo";
import { DeepPanel, CloudPanel, DirPanel } from "./components/OtherPanels";
import type { DetailSpec } from "./components/Poster";
import { SearchBar } from "./components/SearchBar";
import { SnapshotCard, SourcesPanel, VodPanel } from "./components/VodPanel";
import { StatusLine } from "./components/StatusLine";
import { ThemeToggle } from "./components/ThemeToggle";

type Tab = "vod" | "cloud" | "deep" | "dir";

/** 展开详情要不要用 View Transitions：
 *  没有 startViewTransition 的浏览器（老 Firefox）就没有揭示动画，弹框就地淡入；
 *  偏好减少动效的人也不给他揭示 —— 这两条都在这里一次判掉，别散在各点击点。 */
const vtOn =
  typeof document !== "undefined" &&
  "startViewTransition" in document &&
  !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** 把点击点写进 root 的 CSS 变量：弹框的环形揭示（styles.css 的 sheet-open/close）以它为
 *  圆心。弹框层的 clip-path 坐标是元素自己的盒子，所以取点击点在弹框本地的坐标
 *  （--vt-lx/--vt-ly）与「盖住弹框最远一角」的半径（--vt-r），圆撑到那一刻正好盖住弹框，
 *  速度曲线两端都是真的。 */
function setVtOrigin(cx: number, cy: number, sheet: HTMLElement | null) {
  if (!sheet) return;
  const r = sheet.getBoundingClientRect();
  if (!r.width) return;
  const root = document.documentElement.style;
  const lx = cx - r.left;
  const ly = cy - r.top;
  const far = Math.max(
    Math.hypot(lx, ly),
    Math.hypot(r.width - lx, ly),
    Math.hypot(lx, r.height - ly),
    Math.hypot(r.width - lx, r.height - ly),
  );
  root.setProperty("--vt-lx", `${Math.round(lx)}px`);
  root.setProperty("--vt-ly", `${Math.round(ly)}px`);
  root.setProperty("--vt-r", `${Math.ceil(far)}px`);
}

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

function syncSeo(kw: string, d: { items: { title: string }[]; sourcesOk: number } | null) {
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
  const items = d?.items || [];
  const title = `《${kw}》影视资源怎么找 - 追剧资源搜索`;
  const desc =
    `《${kw}》相关影视资源 ${items.length} 部，来自 ${(d?.sourcesOk || 0)} 个采集接口，` +
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
  // 结果不再一页换一页，而是**往后叠**：stack 就是已经叠好的那一叠 + 各页合起来的数
  const [stack, setStack] = useState<Stack | null>(null);
  // 服务端快照：直开 /s/<kw> 时首帧就有（boot 里那份），SPA 换词时由 /api/search
  // 第一页一并带回来。只认当前这个词 —— 上一份不能留在这儿冒充新的。
  const [snap, setSnap] = useState<Snapshot | null>(
    boot.kw && boot.snapshot?.items?.length ? boot.snapshot : null,
  );
  const [load, setLoad] = useState<{ loading: boolean; appending: boolean; error: string }>({
    loading: !!boot.kw,
    appending: false,
    error: "",
  });
  // 追加由 IntersectionObserver 触发，它可能连着回调好几次（哨兵一直露在视野里），
  // 而 setLoad 是异步的 —— 所以闸门用 ref，不用 state
  const appendingRef = useRef(false);
  // 重新起一叠时要掐掉还在飞的追加请求，否则旧那一叠的第 N+1 页会并到新叠上
  const appendAc = useRef<AbortController | null>(null);
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
  // 展开时那个共享元素（海报方框本体）与"该把焦点还给谁"，只在一次开合之间有效
  // 揭示的圆心 = 被点的海报（存元素本体，缩回时现量它的矩形）；vtBack 记「该把焦点还给谁」，
  // 都只在一次开合之间有效
  const vtHero = useRef<HTMLElement | null>(null);
  const vtBack = useRef<HTMLElement | null>(null);
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
    setStack(null);
    setLoad({ loading: false, appending: false, error: "" });
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

  useEffect(
    () => syncSeo(kw, stack ? { items: stack.items, sourcesOk: stack.sources_ok } : null),
    [kw, stack],
  );

  /* 换词、换 URL 上那一页、验证通过重查 —— 这三种都是"重新起一叠"，
     所以先把上一叠连同还在飞的追加请求一起丢掉。往后追加走 loadMore，不动这里。 */
  useEffect(() => {
    if (!kw) {
      setStack(null);
      setSnap(null);
      setLoad({ loading: false, appending: false, error: "" });
      return;
    }
    appendAc.current?.abort();
    appendingRef.current = false;
    const ac = new AbortController();
    const t0 = performance.now();
    // 换词/换起始页时先把上一叠收掉：否则加载的这几秒里，屏幕上还是上一个词的结果。
    // 同一个词重查（比如刚过完验证）则留着旧内容，边上那条说"正在重取这一叠"。
    setStack((cur) => (cur && cur.kw === kw && cur.from === page ? cur : null));
    // 快照同理：同一个词重查（过完验证）时留着，换词就先收掉，别把上一个词的摘要画在这儿
    setSnap((cur) => (cur && cur.kw === kw ? cur : null));
    setLoad((s) => ({ ...s, loading: true, error: "" }));
    api
      .search(kw, page, ac.signal)
      .then((d) => {
        setStack(stackFrom(d, Math.round(performance.now() - t0)));
        if (d.snapshot) setSnap(d.snapshot);
        setLoad((s) => ({ ...s, loading: false, error: "" }));
      })
      .catch((e) => {
        if ((e as Error).name === "AbortError") return;
        setLoad((s) => ({ ...s, loading: false, error: isGate(e) ? "等你验证完自动重查。" : (e as Error).message }));
      });
    return () => ac.abort();
  }, [kw, page, tick]);

  /** 滚到结果末尾时把下一页并进来。同一部片在第二页再出现一次不会多一张卡（stack.appendPage）。 */
  const loadMore = useCallback(() => {
    const cur = stack;
    if (!cur || !cur.hasMore || load.loading || appendingRef.current) return;
    appendingRef.current = true;
    setLoad((s) => ({ ...s, appending: true }));
    const ac = new AbortController();
    appendAc.current = ac;
    const t0 = performance.now();
    api
      .search(cur.kw, cur.pages + 1, ac.signal)
      .then((d) =>
        setStack((prev) => (prev && prev.kw === cur.kw ? appendPage(prev, d, Math.round(performance.now() - t0)) : prev)),
      )
      .catch((e) => {
        if ((e as Error).name === "AbortError") return;
        // 追加失败不毁掉已经看见的那一叠：说一声，就停在这儿
        toast.warning(isGate(e) ? "等你验证完自动接着取。" : `第 ${cur.pages + 1} 页没并进来：${(e as Error).message}`);
      })
      .finally(() => {
        appendingRef.current = false;
        appendAc.current = null;
        setLoad((s) => ({ ...s, appending: false }));
      });
  }, [stack, load.loading]);

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

  /* 详情是居中弹框，但它的出场是**从被点的海报那里环形揭示**的（安卓 material ripple
     那种）：弹框在原位不动（背后的遮罩是透明的，页面原样露着），一个以点击点为圆心的圆
     把弹框"荡"开，圆缘扫过弹框轮廓时荡出一圈水纹；缩回时同一个圆反向收拢回海报。
     圆心与半径在被点的海报矩形上现算（styles.css 的 sheet-open/close 以 --vt-* 为圆心），
     海报自己不再参与过渡 —— 弹框里那张就是同一张图，没有必要再让它飞一遍。
     不支持 startViewTransition 的浏览器（老 Firefox）走原来那条路：弹框就地淡入。 */
  const openDetail = useCallback(
    (s: DetailSpec, from?: HTMLElement | null) => {
      sendClick({
        kind: "detail",
        kw,
        title: s.title,
        src: s.src || "",
        vid: String(s.vid ?? ""),
        place: s.from,
      });
      vtBack.current = document.activeElement as HTMLElement | null;
      const hero = vtOn && from?.isConnected ? from : null;
      if (!hero) {
        setSpec(s);
        return;
      }
      vtHero.current = hero;
      const hr = hero.getBoundingClientRect();
      const cx = hr.left + hr.width / 2;
      const cy = hr.top + hr.height / 2;
      document.startViewTransition!(() => {
        // flushSync 是这里的关键：新状态的快照在回调返回后下一帧就拍，React 异步提交
        // 会赶不上那一拍 —— 捕获拿到的就是一块没有弹框的画面，揭示就无从谈起。
        // 同步提交完弹框才真的在快照里，然后量它的矩形、把两套圆心坐标写进变量
        // —— 捕获就在回调返回后那一帧，量完才赶得上。
        flushSync(() => setSpec(s));
        setVtOrigin(cx, cy, document.querySelector(".detail-sheet"));
      });
    },
    [kw],
  );

  /** 收回海报：同一个圆反向收拢（遮罩是透明的，页面原样露着），圆心仍是被点的那张海报。
   *  焦点也一起还回去：键盘/读屏的人点开的是哪颗按钮，回来就该停在那儿。 */
  const closeDetail = useCallback(() => {
    const hero = vtHero.current;
    vtHero.current = null;
    const back = vtBack.current;
    vtBack.current = null;
    const focusBack = () => {
      try {
        back?.focus();
      } catch {
        /* 那张卡已经被换掉了：没什么可还的 */
      }
    };
    if (!hero || !hero.isConnected) {
      setSpec(null);
      focusBack();
      return;
    }
    const hr = hero.getBoundingClientRect();
    // 弹框还挂着，先量：本地坐标与半径此刻就能量准
    setVtOrigin(hr.left + hr.width / 2, hr.top + hr.height / 2, document.querySelector(".detail-sheet"));
    document.startViewTransition!(() => {
      // 浮层必须先从绘制里整块拿掉：RAC 关闭时会把退出中的浮层多挂一小段，
      // 不拿掉的话新状态里仍有一个 detail-sheet 的影子，收拢动画对不上位置。
      const overlay = document.querySelector(".detail-backdrop");
      if (overlay instanceof HTMLElement) overlay.style.display = "none";
      flushSync(() => setSpec(null));
    }).finished.finally(() => {
      focusBack();
    });
  }, []);

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
  // 有当前这个词的快照才画那一块：直开时来自 boot，SPA 换词时来自 /api/search 第一页
  const hasSnap = !!snap && snap.kw === kw && !!snap.items?.length;
  const groupOf = (kind: "movie" | "tv"): { rows: HotRow[]; total: number } & typeof hot => {
    const list = (hot[kind] || []) as HotRow[];
    return { ...hot, rows: list, total: (hot[`${kind}_total`] as number) ?? list.length };
  };

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b border-separator bg-surface/80 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-[1680px] items-center gap-3 px-4 sm:px-6">
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

      <main className="mx-auto max-w-[1680px] px-4 pb-20 sm:px-6">
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
                  stack={stack}
                  loading={load.loading}
                  appending={load.appending}
                  error={load.error}
                  sourcesTotal={boot.sources.length}
                  onLoadMore={loadMore}
                  onDetail={openDetail}
                />
                <aside className="max-xl:contents xl:sticky xl:top-20 xl:self-start xl:space-y-4">
                  {/* 窄屏时这一栏是 display:contents：两块各自成为栅格项，跟着结果列表
                      依次排在后面 —— 接口状态在前、《xxx》的检索结果在后（两块默认都折起，
                      只占一行标题，不会把结果顶出屏幕）；宽屏才整栏排到右侧粘住。 */}
                  {stack ? (
                    <div>
                      <SourcesPanel
                        rows={stack.status}
                        sum={`${stack.sources_ok}/${stack.sources_total} 可用`}
                      />
                    </div>
                  ) : null}
                  {hasSnap && snap ? (
                    <div>
                      <SnapshotCard
                        kw={kw}
                        snapshot={snap}
                        description={snap.description || (kw === boot.kw ? boot.description : "")}
                      />
                    </div>
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
        <div className="mx-auto max-w-[1680px] px-4 text-[11px] leading-relaxed text-muted sm:px-6">
          <p>本工具只做第三方公开接口的聚合查询，不存储、不转发任何影视内容；结果链接指向外部站点，请注意甄别广告、跳转与个人信息安全。</p>
          <p className="mt-1 text-muted/70">
            仅供个人技术学习与找片参考，请支持正版。 · 本地运行，数据不出这台电脑 ·{" "}
            <a href="/admin" rel="nofollow" className="hover:text-foreground">
              统计
            </a>
          </p>
        </div>
      </footer>

      <DetailDrawer spec={spec} onClose={closeDetail} />
      <GateModal open={locked && !boot.locked} onok={() => {}} />
      <Toast.Provider placement="bottom" />
    </div>
  );
}
