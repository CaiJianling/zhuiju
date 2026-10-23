import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
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

/** 猜你想搜：一行正好铺满容器，翻页是整行左右推入（不做横向滚动条）。
 *  每页张数直接问 CSS 网格实际几列，两边共用一个来源，不会算错行。
 *
 *  换页时**旧的那一行留在原地**，新数据到了才当场替换，并对容器做一次位移动画。
 *  上一版是 `key={page}` 强制重挂整个网格：取数那一瞬间格子里一个卡片都没有，
 *  区块高度塌成一行文字，文档变矮、浏览器把滚动位置往上顶 —— 现象就是
 *  "翻页时滚动条回闪 / 电视剧那一组直接跳"。 */
export function HotSection({
  kind,
  label,
  boot,
  onDetail,
}: {
  kind: "movie" | "tv";
  label: string;
  boot: Group;
  onDetail: (s: DetailSpec) => void;
}) {
  const gridRef = useRef<HTMLDivElement>(null);
  const dirRef = useRef(0);
  const [cols, setCols] = useState(0);
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(boot.total || boot.rows.length);
  const [byPage, setByPage] = useState<Record<number, HotRow[]>>({});
  const [paint, setPaint] = useState<{ page: number; rows: HotRow[] }>({ page: 0, rows: boot.rows });
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(false);
  const reqId = useRef(0);

  const measure = useCallback(() => {
    const el = gridRef.current;
    if (!el) return;
    const v = window.getComputedStyle(el).gridTemplateColumns || "";
    const n = v.split(" ").filter(Boolean).length;
    if (n > 0) setCols((c) => (c === n ? c : n));
  }, []);

  // 列数要在浏览器画第一帧之前就知道，否则首屏会先铺 12 张再缩成一行，白跳一次
  useLayoutEffect(() => {
    measure();
    const el = gridRef.current;
    if (!el) return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [measure]);

  // 列数变了，一页装哪几条就跟着变了：按列数作废，翻回来的页才不许变
  useEffect(() => {
    setByPage({});
  }, [cols]);

  // 首屏那一条服务端已经渲染进 HTML 了：够用就直接当第 0 页，不发请求；
  // 窗口特别宽（一行的数比首屏还多）时才回去补一次
  useLayoutEffect(() => {
    if (!cols || boot.rows.length < cols) return;
    setByPage((m) => (m[0] ? m : { ...m, 0: boot.rows.slice(0, cols) }));
  }, [cols, boot.rows]);

  useEffect(() => {
    const r = byPage[page];
    if (!r) return;
    if (paint.page === page) {
      setPaint({ page, rows: r }); // 同一页重铺（列数变了），不推
      dirRef.current = 0;
      return;
    }
    setPaint({ page, rows: r });
    const dir = dirRef.current;
    dirRef.current = 0;
    const el = gridRef.current;
    if (!el || !dir || reduced()) return;
    el.animate(
      [
        { opacity: 0, transform: `translateX(${dir > 0 ? 28 : -28}px)` },
        { opacity: 1, transform: "none" },
      ],
      { duration: 320, easing: "cubic-bezier(0.22, 0.61, 0.36, 1)" },
    );
  }, [byPage, page, paint.page]);

  useEffect(() => {
    if (!cols || byPage[page] || loading) return;
    const mine = ++reqId.current;
    setLoading(true);
    api
      .hot(kind, page * cols, cols)
      .then((d: HotResult) => {
        if (mine !== reqId.current) return;
        const t = d.total ?? total;
        const np = Math.max(1, Math.ceil(t / cols));
        if (t !== total) {
          setTotal(t);
          setNote(`列表刚更新过：${total} → ${t} 条`);
        }
        if (page > np - 1) {
          // 列表变短了还停在原来那一页，翻出来就是空白：夹回最后一页重取
          setPage(np - 1);
          setByPage({});
          return;
        }
        setByPage((m) => ({ ...m, [page]: d.items ?? [] }));
      })
      .catch(() => {
        /* 取数失败就停在原来那一行，页码标签会说"没取到" */
      })
      .finally(() => {
        if (mine === reqId.current) setLoading(false);
      });
  }, [cols, page, byPage, loading, kind, total]);

  if (!boot.rows.length && !boot.building) return null;

  const pages = Math.max(1, Math.ceil(total / (cols || paint.rows.length || 1)));
  const go = (delta: number) => {
    const next = Math.max(0, Math.min(pages - 1, page + delta));
    if (next === page) return;
    dirRef.current = delta;
    setPage(next);
  };

  return (
    <section className="space-y-3" aria-label="猜你想搜">
      <SectionHead
        title={label}
        note={
          <span>
            第 {page + 1} / {pages} 页
            {loading ? <span className="text-accent"> · 正在取…</span> : ""}
            {note ? ` · ${note}` : ""}
          </span>
        }
        actions={
          <>
            <Button
              size="sm"
              variant="ghost"
              className="rounded-full"
              isDisabled={page <= 0 || loading}
              onPress={() => go(-1)}
            >
              ‹ 上一页
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="rounded-full"
              isDisabled={page >= pages - 1 || loading}
              onPress={() => go(1)}
            >
              下一页 ›
            </Button>
          </>
        }
      />
      <div
        ref={gridRef}
        className="grid grid-cols-3 gap-x-4 gap-y-6 sm:grid-cols-4 lg:grid-cols-6"
        aria-busy={loading}
      >
        {paint.rows.map((x) => (
          <Poster
            key={`${x.title}-${x.year}`}
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
        ))}
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
