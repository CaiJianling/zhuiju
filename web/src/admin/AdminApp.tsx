import { useCallback, useEffect, useState } from "react";
import { Button, Toast } from "@heroui/react";
import { NeedPassword, errText, fetchView, postForm } from "./api";
import { Link, useGo } from "./ui";
import { FilterBar } from "./Filters";
import { Login, Password } from "./Login";
import { Overview } from "./Overview";
import { DetailTab } from "./Detail";
import { StrmTab } from "./Strm";
import { Settings } from "./Settings";
import { ThemeToggle } from "../components/ThemeToggle";
import type { AdminView } from "./types";

interface Boot {
  authed: boolean;
  route: string;
  first?: boolean;
  min_len?: number;
  env_lock?: boolean;
  temp?: boolean;
}

/** 侧边目录：只列当前标签页里那几块（归属由 ADMIN_TABS 一处定义，服务端带来）。
 *  高亮哪一块靠"最后一个顶边越过判据线的块"，和老模板那段 scrollspy 同一个算法。
 *  这一栏在 xl 以上才出现：左边已经让掉了 176px 给菜单，再挤一条 200px 的话，
 *  十二列的明细表就只剩横向滚动条可看了。 */
function Toc({ v }: { v: AdminView }) {
  const tab = v.tabs.find((t) => t.id === v.tab) || v.tabs[0];
  const [active, setActive] = useState(tab.blocks[0]?.[0] || "");

  useEffect(() => {
    const onScroll = () => {
      const ids = tab.blocks.map((b) => b[0]);
      let cur = ids[0] || "";
      for (const id of ids) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= 84) cur = id;
      }
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) {
        cur = ids[ids.length - 1] || cur;
      }
      setActive(cur);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [tab]);

  return (
    <nav aria-label="本节目录" className="sticky top-20 hidden h-fit rounded-2xl bg-surface p-3 text-surface-foreground shadow-surface ring-1 ring-border xl:block">
      <p className="mb-2 text-[11px] font-semibold text-foreground">{tab.label}</p>
      <ul className="space-y-1">
        {tab.blocks.map(([id, name]) => (
          <li key={id}>
            <a
              href={`#${id}`}
              className={`block rounded-lg px-2 py-1 text-[11px] transition ${active === id ? "bg-accent/10 text-accent" : "text-muted hover:text-foreground"}`}
              onClick={(e) => {
                e.preventDefault();
                document.getElementById(id)?.scrollIntoView({ block: "start" });
              }}
            >
              {name}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** 左侧菜单：四个分区竖着排（照 HeroUI 文档站那样，左边选屏、右边看目录）。
 *  窄屏退化成顶部一条横滑 —— 菜单必须一直看得见，藏进汉堡里等于让人不知道后台分几块。 */
function Menu({ v, onGo }: { v: AdminView; onGo: (u: string, r?: boolean) => void }) {
  return (
    <nav
      aria-label="后台分区"
      className="scroll-thin -mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1 lg:sticky lg:top-20 lg:h-fit lg:w-[176px] lg:shrink-0 lg:flex-col lg:items-stretch lg:overflow-visible lg:px-0 lg:pb-0"
    >
      {v.tabs.map((t) => {
        const on = t.id === v.tab;
        return (
          <a
            key={t.id}
            href={t.href}
            aria-current={on ? "page" : undefined}
            onClick={(e) => {
              if (e.metaKey || e.ctrlKey || e.shiftKey) return;
              e.preventDefault();
              onGo(t.href);
            }}
            className={`shrink-0 truncate rounded-full px-3 py-2 text-left text-xs transition lg:py-1.5 ${
              on ? "bg-accent/12 font-medium text-accent" : "text-muted hover:bg-default hover:text-foreground"
            }`}
          >
            {t.label}
          </a>
        );
      })}
    </nav>
  );
}

export default function AdminApp({ boot }: { boot: Boot }) {
  const [view, setView] = useState<AdminView | null>(null);
  const [denied, setDenied] = useState<AdminView | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  // 换标签/换筛选时旧内容先留着，顶上那根条说"在取新的"：
  // STRM 那一屏要 3.7 秒（在自己的库里聚合），没有这句话就看着像卡死
  const [pending, setPending] = useState(false);

  const reload = useCallback(async () => {
    setPending(true);
    try {
      const v = await fetchView(location.search);
      setView(v);
      setDenied(null);
      setErr("");
    } catch (e) {
      if (e instanceof NeedPassword) {
        setView(null);
        setDenied((e as NeedPassword & { payload?: AdminView }).payload || ({ authed: false, csrf: "", tab: "overview", tabs: [], labels: { via: {}, ref_kind: {}, place: {}, kind: {}, scope: {}, who: {} } } as AdminView));
        return;
      }
      setErr(errText(e));
    } finally {
      setPending(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const onGo = useGo(reload);

  async function logout() {
    if (busy) return;
    setBusy(true);
    await postForm("/admin/logout", {}, view?.csrf || "");
    location.href = "/admin";
  }

  if (boot.route === "/admin/password") {
    return (
      <>
        <Password view={view} first={!!boot.first} envLock={!!boot.env_lock} minLen={boot.min_len || 8}
                  ondone={(to) => { location.href = to; }} />
        <Toast.Provider placement="bottom" />
      </>
    );
  }

  if (denied) {
    return (
      <>
        <Login payload={denied} csrf={denied.csrf} onok={() => void reload()} />
        <Toast.Provider placement="bottom" />
      </>
    );
  }

  if (err && !view) {
    return (
      <main className="mx-auto flex min-h-dvh max-w-[560px] flex-col justify-center gap-3 px-4 text-center">
        <h1 className="text-base font-semibold">后台没取到数据</h1>
        <p className="text-xs text-muted">{err}</p>
        <Button className="mx-auto rounded-full" onPress={() => void reload()}>再试一次</Button>
      </main>
    );
  }

  if (!view) {
    return <main className="mx-auto flex min-h-dvh items-center justify-center text-xs text-muted">正在读后台…</main>;
  }

  const tab = view.tab;
  const upd = view.upd;

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b border-separator bg-surface/80 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-[1680px] items-center gap-3 px-4 sm:px-6">
          <h1 className="flex items-baseline gap-2 text-sm font-semibold">
            后台统计
            <span className="num text-[11px] font-normal text-muted">已登录 · 命中 {view.agg?.count ?? 0} 条查询</span>
          </h1>
          <span className="flex-1" />
          <ThemeToggle />
          {/* 改口令是 /admin/password 那一屏，不是 /admin —— 写成后者等于点自己：
              useGo 看路径没变，只把同一条 URL 重新取一遍，现象就是"这颗按钮按了没反应" */}
          <Link href="/admin/password" onGo={(u, r) => onGo(u, r)} className="text-[11px]">改口令</Link>
          <a href="/" className="text-[11px] text-muted hover:text-foreground">回前台</a>
          <Button size="sm" variant="ghost" className="rounded-full" isPending={busy} onPress={() => void logout()}>
            退出登录
          </Button>
        </div>
        {pending ? (
          /* 只留那根条：文字说明是多余的，"在取新的"这件事进度条自己会说
              （STRM 那一屏要几秒，没有这根条看着就是卡死） */
          <div className="bar-run" role="status" aria-label="正在读后台数据" aria-hidden="false" />
        ) : null}
      </header>

      <main className="mx-auto max-w-[1680px] px-4 pb-20 sm:px-6">
        {view.notice ? <p className="mt-4 rounded-xl bg-success/12 px-3 py-2 text-xs text-success">{view.notice}</p> : null}
        {upd && upd.retry_in ? (
          <p className="mt-3 text-[11px] leading-relaxed text-warning">
            上一轮失败，约 {Math.floor((upd.retry_in + 59) / 60)} 分钟后才会再自动重试（{upd.retry_minutes} 分钟冷却，
            改完环境可跑 <span className="num">{upd.retry_cmd}</span> 立刻重试）
          </p>
        ) : null}

        {/* 三栏：左菜单（选屏）· 中正文（筛选 + 这一块）· 右目录（跳到某一节）。
            窄屏时这三栏就是竖着的三段，菜单退成横滑条。 */}
        <div className="mt-6 grid gap-6 lg:grid-cols-[176px_minmax(0,1fr)] xl:grid-cols-[176px_minmax(0,1fr)_200px]">
          <Menu v={view} onGo={onGo} />
          <div className="min-w-0 space-y-4">
            <FilterBar v={view} onGo={onGo} />
            <div className="space-y-8 pt-2">
              {tab === "overview" ? <Overview v={view} onGo={onGo} /> : null}
              {tab === "detail" ? <DetailTab v={view} onGo={onGo} /> : null}
              {tab === "strm" ? <StrmTab v={view} /> : null}
              {tab === "settings" ? <Settings v={view} /> : null}
            </div>
          </div>
          <Toc v={view} />
        </div>
      </main>
      <Toast.Provider placement="bottom" />
    </div>
  );
}
