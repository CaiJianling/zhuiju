import { useCallback, useEffect, useRef, useState } from "react";
import { Modal } from "@heroui/react";
import { api } from "../api";
import { boot } from "../boot";
import { markPassed } from "../auth";
import type { Challenge } from "../types";

/** 真人滑块。裁决全在 zhuiju/human.py：缺口位置服务端随机、容差服务端定、
 *  挑战两分钟过期且提交一次就作废。这里那些"耗时/采样数"只是多给服务端几条依据，
 *  写在前端是为了让正常用户一次就过，不是为了防住谁。 */

const KNOB = 40;

interface Live {
  ch: Challenge | null;
  pct: number;
  down: number;
  spent: number;
  samples: number;
  keys: number;
  busy: boolean;
  idle: ReturnType<typeof setTimeout> | 0;
}

const fresh = (): Live => ({ ch: null, pct: 0, down: 0, spent: 0, samples: 0, keys: 0, busy: false, idle: 0 });

export function Slip({ onok }: { onok: () => void }) {
  const trackRef = useRef<HTMLDivElement>(null);
  const knobRef = useRef<HTMLButtonElement>(null);
  const spanRef = useRef(1);
  const live = useRef<Live>(fresh());
  const [hole, setHole] = useState<{ w: number; left: number } | null>(null);
  const [hint, setHint] = useState({ text: "正在准备验证…", tone: "" as "" | "bad" | "good" });
  const [locked, setLocked] = useState(true);

  const paint = useCallback((p: number) => {
    live.current.pct = p;
    const k = knobRef.current;
    if (!k) return;
    k.style.transform = `translateX(${Math.round(p * spanRef.current)}px)`;
    k.setAttribute("aria-valuenow", String(Math.round(p * 100)));
  }, []);

  /** 轨道宽度现量，不写常量：窄屏会把轨道加高、滑块加宽，写死一个数就成了
   *  "明明对准了却说不匹配"。滑块中心在 target*span + KNOB/2，缺口以它为中心铺开。 */
  const layout = useCallback(() => {
    const el = trackRef.current;
    if (!el) return;
    const w = knobRef.current?.offsetWidth || KNOB;
    const s = Math.max(1, el.getBoundingClientRect().width - w);
    spanRef.current = s;
    const ch = live.current.ch;
    if (ch) {
      const zone = ch.tol * 2 * s + w;
      setHole({ w: Math.round(zone), left: Math.round(ch.target * s + w / 2 - zone / 2) });
    }
    paint(live.current.pct);
  }, [paint]);

  const ask = useCallback(async () => {
    const c = live.current;
    if (c.busy) return;
    c.busy = true;
    setLocked(true);
    setHint({ text: "正在准备验证…", tone: "" });
    try {
      c.ch = await api.challenge();
      Object.assign(c, { pct: 0, samples: 0, keys: 0, down: 0, spent: 0 });
      layout();
      setLocked(false);
      setHint({
        text: "把滑块拖进虚线框里（不方便用鼠标就点一下滑块，再用左右方向键）",
        tone: "",
      });
    } catch (e) {
      setHint({ text: `拿不到验证（${(e as Error).message}），点这里重试`, tone: "bad" });
    } finally {
      c.busy = false;
    }
  }, [layout]);

  const submit = useCallback(async () => {
    const c = live.current;
    if (c.busy || !c.ch) return;
    const ch = c.ch;
    c.busy = true;
    setLocked(true);
    setHint({ text: "正在核对…", tone: "" });
    try {
      await api.verify({ id: ch.id, pct: c.pct, ms: Math.round(c.spent), samples: c.samples, keys: c.keys });
      setHint({ text: "验证通过，正在回去…", tone: "good" });
      markPassed();
      onok();
    } catch (e) {
      // 挑战是一次性的，失败后必须换一块新的：拿废挑战再拖一次永远过不去
      setHint({ text: `${(e as Error).message}，重来一次`, tone: "bad" });
      window.setTimeout(ask, 700);
    } finally {
      c.busy = false;
    }
  }, [ask, onok]);

  useEffect(() => {
    void ask();
    const el = trackRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => layout());
    ro.observe(el);
    return () => {
      ro.disconnect();
      const c = live.current;
      if (c.idle) window.clearTimeout(c.idle);
    };
  }, [ask, layout]);

  const moveTo = (clientX: number) => {
    const el = trackRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const p = (clientX - rect.left - KNOB / 2) / spanRef.current;
    paint(Math.max(0, Math.min(1, p)));
  };

  return (
    <div className="space-y-3">
      <div
        ref={trackRef}
        className="relative h-12 overflow-hidden rounded-full bg-default ring-1 ring-border"
      >
        {hole ? (
          <span
            aria-hidden="true"
            className="absolute inset-y-1.5 rounded-lg border-2 border-dashed border-accent/70 bg-accent/12"
            style={{ width: hole.w, left: hole.left }}
          />
        ) : null}
        <button
          ref={knobRef}
          type="button"
          role="slider"
          tabIndex={0}
          aria-label="拖动这里完成真人验证"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={0}
          disabled={locked}
          onPointerDown={(e) => {
            const c = live.current;
            if (c.busy || !c.ch) return;
            c.down = performance.now();
            c.spent = 0;
            c.samples = 0;
            try {
              e.currentTarget.setPointerCapture(e.pointerId);
            } catch {
              /* 合成事件没有活动指针，抓不住也能拖（move 会发给窗口） */
            }
            e.preventDefault();
          }}
          onPointerMove={(e) => {
            const c = live.current;
            if (!c.down) return;
            moveTo(e.clientX);
            c.samples += 1;
          }}
          onPointerUp={() => {
            const c = live.current;
            if (!c.down) return;
            // 时长必须在清 down 之前算：晚一步就是每次都上报 0ms，服务端按"太快"永远拒
            c.spent = performance.now() - c.down;
            c.down = 0;
            if (c.spent < 120 && c.samples < 3) return;
            void submit();
          }}
          onPointerCancel={() => {
            live.current.down = 0;
          }}
          onKeyDown={(e) => {
            const c = live.current;
            if (c.busy || !c.ch) return;
            if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
              e.preventDefault();
              if (!c.down) c.down = performance.now();
              const p = Math.max(0, Math.min(1, c.pct + (e.key === "ArrowRight" ? 0.02 : -0.02)));
              paint(p);
              c.keys += 1;
              if (c.idle) window.clearTimeout(c.idle);
              // 停手 0.6 秒自动核对，不用记着按回车；这段用时本身就是真人的证据
              c.idle = window.setTimeout(() => {
                c.spent = performance.now() - c.down;
                c.down = 0;
                void submit();
              }, 600);
            } else if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              if (c.down) c.spent = performance.now() - c.down;
              c.down = 0;
              void submit();
            }
          }}
          className="absolute top-1/2 left-0 -mt-5 grid size-10 cursor-grab touch-none select-none place-items-center rounded-full bg-surface text-muted shadow-surface ring-1 ring-border will-change-transform active:cursor-grabbing disabled:cursor-default"
        >
          <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M9 6l4 6-4 6M15 6l4 6-4 6" />
          </svg>
        </button>
      </div>
      <p
        onClick={() => {
          if (!live.current.busy) void ask();
        }}
        className={`text-xs ${
          hint.tone === "bad" ? "cursor-pointer text-danger" : hint.tone === "good" ? "text-success" : "text-muted"
        }`}
      >
        {hint.text}
      </p>
    </div>
  );
}

/** 首屏就被门禁挡住：主界面让位给这张卡。服务端在 /s/<词> 的门禁页里带上了
 *  **缓存里已有**的那份快照（seo.cached_snapshot，只读盘、不敲上游）——
 *  缓存里有的词把结果亮在滑块下面，分享与收录出去的链接不能只有一块滑块；
 *  没有的词 boot.snapshot 自然是空的。搜新词、看详情与播放地址仍然要先验证。 */
export function LockedView({ hours, back, description }: { hours: number; back: string; description: string }) {
  const cached = boot.locked ? boot.snapshot.items || [] : [];
  const onok = () => {
    // 回到被挡之前那一页；本来就是当前页时交给 App 重新取数，不用整页刷
    if (back && back !== window.location.pathname + window.location.search) {
      window.location.href = back;
      return;
    }
    window.location.reload();
  };
  return (
    <main className="mx-auto flex min-h-dvh max-w-[560px] flex-col justify-center px-4">
      <section className="rounded-3xl bg-surface p-6 text-surface-foreground shadow-surface ring-1 ring-border sm:p-8">
        <h1 className="text-lg font-semibold">追剧资源搜索</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted">{description}</p>
        <p className="mt-5 text-xs text-muted">
          拖一下滑块验证一次，之后 <b className="num text-foreground">{hours}</b> 小时之内不再问。
        </p>
        <div className="mt-3">
          <Slip onok={onok} />
        </div>
        <details className="mt-5 text-xs text-muted">
          <summary className="cursor-pointer text-foreground">这一步在浏览器里留了什么？</summary>
          <p className="mt-2 leading-relaxed">
            一枚本站签发的<b className="text-foreground">匿名</b> cookie：里面只有到期时间和一个签名，
            不含姓名、账号、搜索内容。它<b className="text-foreground">绑这台设备</b> ——
            来源地址与系统/设备类型都算进了签名，拷到另一台电脑上用不了。
          </p>
          <p className="mt-2 leading-relaxed">
            后台统计里只多一项：这条查询是「验证过 / 搜索引擎爬虫 / 门禁未开」中的哪一种，同样不含身份信息。
          </p>
          <p className="mt-2 leading-relaxed">它只为一件事：不让脚本把这里当免费的影视搜索接口刷。</p>
        </details>
        <p className="mt-4 text-xs leading-relaxed text-muted/90">
          已经验证过却还是看到这一页？多半是浏览器没把 cookie 带回来：无痕窗口、
          站点被设成"退出时清除 Cookie"、或者手动清过 Cookie。也可以直接
          <a className="text-foreground underline" href={back || "/"}>
            回到刚才那一页
          </a>
          再试一次。
        </p>
        <noscript>
          <p className="mt-3 text-xs text-danger">这块滑块需要 JavaScript。请在允许 JavaScript 的浏览器里打开。</p>
        </noscript>
      </section>
      {cached.length ? (
        <section className="mt-4 rounded-3xl bg-surface p-6 text-surface-foreground shadow-surface ring-1 ring-border sm:p-8">
          <h2 className="text-sm font-semibold">《{boot.snapshot.kw || boot.kw}》已有人搜过，先看缓存里的结果</h2>
          <p className="mt-1 text-xs leading-relaxed text-muted">
            这一份是服务端存的快照。要看详情、播放地址，或搜别的片名，先拖上面的滑块。
          </p>
          <ul className="mt-3 space-y-1.5">
            {cached.map((it, i) => (
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
    </main>
  );
}

/** 人在页面上一待就是十几个小时，cookie 到点：接口回 423，就地补一次验证，
 *  不用把人甩回门禁页重新来一遍。 */
export function GateModal({ open, onok }: { open: boolean; onok: () => void }) {
  return (
    <Modal>
      <Modal.Backdrop variant="blur" isDismissable={false} isOpen={open} onOpenChange={() => {}}>
        <Modal.Container size="sm">
          <Modal.Dialog>
            <Modal.Header>
              <Modal.Heading>需要再验一次你是真人</Modal.Heading>
            </Modal.Header>
            <Modal.Body>
              <p className="mb-4 text-sm text-muted">上次验证到现在已经过了，接口先不认这次的请求了。</p>
              <Slip onok={onok} />
            </Modal.Body>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
