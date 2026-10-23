import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@heroui/react";
import { api } from "../api";
import type { HotResult, HotRow } from "../types";
import { Poster, type DetailSpec } from "./Poster";
import { SectionHead } from "./ui";

interface Group {
  rows: HotRow[];
  total: number;
  since?: string;
  window_days?: number;
  candidates?: number;
  dropped_kind?: number;
  building?: boolean;
}

const reduced = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** 一颗海报在条里的宽度：三颗铺满手机、上限 176px（再宽就是把一张海报摊成墙），
 *  窄到 104px 时片名开始挤，所以那也是下限。整行横滚，不按断点重排 ——
 *  原来"一行正好铺满容器 + 整行换页"要先量有几列才知道该取几条，量不到还会白跳一次。 */
const CELL = "w-[31%] min-w-[104px] max-w-[176px] shrink-0 snap-start";

/** 每次补一批多少条：比最宽的一屏（1680 ÷ 176 ≈ 9）多一点 */
const BATCH = 12;

/** 猜你想搜：一行横着滚，滚到头自动补下一批。
 *
 *  以前是"整行换页"：上一页渐隐、下一页渐现。晃眼的原因在那次交叉淡入 ——
 *  三十几张海报同时改透明度，人眼会当成"整块在闪"。横滚之后所有内容一直实在那儿，
 *  只是视野在动，动的是位移不是透明度，读起来才是"往右翻了一页"。
 *
 *  每一批 12 条：比最宽的一屏（1680 ÷ 176 ≈ 9）多一点，取完这一批哨兵多半就
 *  滚出视野了，不会一次连发好几个请求；列表变短（6 小时缓存换档）时按 total 夹住，
 *  不会停在空的那一截。 */
export function HotSection({
  kind,
  label,
  boot,
  onDetail,
}: {
  kind: "movie" | "tv";
  label: string;
  boot: Group;
  onDetail: (s: DetailSpec, from?: HTMLElement | null) => void;
}) {
  const row = useRef<HTMLDivElement>(null);
  const tailRef = useRef<HTMLDivElement>(null);
  const loadingRef = useRef(false);
  const reqId = useRef(0);
  const [items, setItems] = useState<HotRow[]>(boot.rows);
  const [total, setTotal] = useState(boot.total || boot.rows.length);
  const [loading, setLoading] = useState(false);
  const [note, setNote] = useState("");
  const [atEnd, setAtEnd] = useState(false);
  // 已经拿到几条要能被 more() 当场读到（state 在这一轮里还是旧的），所以配一个 ref
  const gotRef = useRef(boot.rows.length);
  gotRef.current = items.length;

  // 同一部片可能在两批里都出现（各源上榜时间不同），按 片名+年份 去重，别铺两张卡
  const key = (x: HotRow) => `${x.title}#${x.year || ""}`;

  const more = useCallback(() => {
    const offset = gotRef.current;
    if (loadingRef.current || offset >= total) return;
    loadingRef.current = true;
    setLoading(true);
    const mine = ++reqId.current;
    api
      .hot(kind, offset, BATCH)
      .then((d: HotResult) => {
        if (mine !== reqId.current) return;
        const t = d.total ?? total;
        if (t !== total) {
          setTotal(t);
          setNote(`列表刚更新过：${total} → ${t} 条`);
        }
        setItems((prev) => {
          const seen = new Set(prev.map(key));
          const next = prev.slice();
          (d.items || []).forEach((x) => {
            if (!seen.has(key(x))) {
              seen.add(key(x));
              next.push(x);
            }
          });
          return next;
        });
      })
      .catch(() => {
        /* 取数失败就停在已拿到的那些，标题那行"正在补"会消失，不会假装还在取 */
      })
      .finally(() => {
        loadingRef.current = false;
        setLoading(false);
      });
  }, [kind, total]);

  /* 哨兵在滚动条右侧 260px 处露头就来下一批。
     root 必须是这条横滚容器（不是视口）：贴着视口的话，右边看不见的那截也算"在视野里"。
     每批到货后 items.length 变了 → 重挂一次 observer → 立刻重算可见性，
     于是"还露着哨兵"能连着补第二批，不需要等人再滚。 */
  useEffect(() => {
    const el = row.current;
    const tail = tailRef.current;
    if (!el || !tail || items.length >= total) return;
    if (typeof IntersectionObserver === "undefined") {
      more();   // 老浏览器没 IO：那就一次取满，不再指望滚动触发
      return;
    }
    const io = new IntersectionObserver((es) => {
      if (es.some((e) => e.isIntersecting)) more();
    }, { root: el, rootMargin: "0px 260px 0px 0px" });
    io.observe(tail);
    return () => io.disconnect();
  }, [items.length, total, more]);

  const scrollBy = (dir: number) => {
    const el = row.current;
    if (!el) return;
    el.scrollBy({ left: dir * Math.max(160, el.clientWidth * 0.86), behavior: reduced() ? "auto" : "smooth" });
  };

  if (!boot.rows.length && !boot.building) return null;

  return (
    <section className="space-y-3" aria-label="猜你想搜">
      <SectionHead
        title={label}
        note={
          <span className="num">
            已铺 {items.length} / {total} 部
            {loading ? <span className="text-accent"> · 正在补…</span> : ""}
            {note ? ` · ${note}` : ""}
          </span>
        }
        actions={
          <>
            <Button size="sm" variant="ghost" className="rounded-full" aria-label={`把${label}往回滚`}
                    onPress={() => scrollBy(-1)}>
              ‹
            </Button>
            <Button size="sm" variant="ghost" className="rounded-full" aria-label={`把${label}往后滚`}
                    isDisabled={loading || (atEnd && items.length >= total)}
                    onPress={() => { scrollBy(1); more(); }}>
              ›
            </Button>
          </>
        }
      />
      <div
        ref={row}
        onScroll={(e) => {
          const el = e.currentTarget;
          setAtEnd(el.scrollLeft + el.clientWidth >= el.scrollWidth - 8);
        }}
        className="scroll-thin snap-x flex gap-4 overflow-x-auto pb-1"
        aria-busy={loading}
      >
        {items.map((x) => (
          <div key={`${x.title}-${x.year}`} className={CELL}>
            <Poster
              title={x.title}
              pic={x.pic}
              href={x.url}
              meta={[x.year || x.type, x.rate ? `豆瓣 ${x.rate}` : "", x.n_sources > 1 ? `${x.n_sources} 源` : ""]}
              spec={{
                title: x.title,
                pic: x.pic,
                year: x.year,
                type: x.type,
                remarks: x.remarks,
                src: x.src,
                vid: x.vid,
                n: x.n_sources,
                sources: (x.sources || []).map((s) => ({ id: s.id, name: s.name, vid: s.vid ?? "" })),
                from: "hot",
              }}
              onDetail={onDetail}
            />
          </div>
        ))}
        <div ref={tailRef} aria-hidden="true" className="w-px shrink-0 self-stretch" />
        {loading ? (
          <div className="grid w-24 shrink-0 place-items-center text-[11px] text-muted" role="status">
            正在补…
          </div>
        ) : null}
      </div>
    </section>
  );
}

/** 那一行小字：说清楚页面上真能翻到的是电影 / 电视剧各多少部，
 *  以及候选池里被丢掉的那几条，别拿"共 346 条候选"这种数糊弄人。 */
export function hotNote(hot: { since?: string; window_days?: number; candidates?: number; dropped_kind?: number }) {
  const win = (hot.window_days || 0) >= 365 ? "一年" : "半年";
  return [
    `最近${win}`,
    hot.since ? `截至 ${hot.since} 起算` : "",
    hot.candidates ? `候选 ${hot.candidates} 条` : "",
    hot.dropped_kind ? `认不出类别丢掉 ${hot.dropped_kind} 条` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}
