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
 *  高亮哪一块靠"最后一个顶边越过判据线的块"，和老模板那段 scrollspy 同一个算法。 */
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
    <nav className="sticky top-20 hidden h-fit rounded-2xl bg-surface p-3 text-surface-foreground shadow-surface ring-1 ring-border lg:block">
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
          <Link href="/admin" onGo={(u, r) => onGo(u, r)} className="text-[11px]">改口令</Link>
          <a href="/" className="text-[11px] text-muted hover:text-foreground">回前台</a>
          <Button size="sm" variant="ghost" className="rounded-full" isPending={busy} onPress={() => void logout()}>
            退出登录
          </Button>
        </div>
        {pending ? (
          <div role="status" aria-label="正在读后台数据">
            <div className="bar-run" aria-hidden="true" />
            <p className="num px-4 text-[10px] text-muted sm:px-6">正在读…（Emby STRM 那一屏要几秒，它在近一年的采集库里聚合）</p>
          </div>
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

        <div className="mt-4 flex flex-wrap gap-1.5">
          {view.tabs.map((t) => (
            <Button key={t.id} size="sm" variant={tab === t.id ? "primary" : "tertiary"} className="rounded-full"
                    onPress={() => onGo(t.href)}>
              {t.label}
            </Button>
          ))}
        </div>

        <div className="mt-4">
          <FilterBar v={view} onGo={onGo} />
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_200px]">
          <div className="min-w-0">
            {tab === "overview" ? <Overview v={view} onGo={onGo} /> : null}
            {tab === "detail" ? <DetailTab v={view} onGo={onGo} /> : null}
            {tab === "strm" ? <StrmTab v={view} /> : null}
            {tab === "settings" ? <Settings v={view} /> : null}
          </div>
          <Toc v={view} />
        </div>
      </main>
      <Toast.Provider placement="bottom" />
    </div>
  );
}
