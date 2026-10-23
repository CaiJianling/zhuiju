import { useCallback, useMemo, type ReactNode } from "react";
import { Table as HeroTable } from "@heroui/react";
import { useClamp } from "../hooks/useClamp";
import type { AdminView, BehRow, Filters, Reason } from "./types";

/** 后台的路由就是查询字符串本身：tab / 筛选 / 页码全在 URL 上，
 *  服务端（_admin_ctx）据此算出这一屏，链接也由它拼好。
 *  React 这边只做一件事 —— 拦下点击、换 URL、重取一次。 */
export function useGo(reload: () => void) {
  return useCallback(
    (url: string, replace = false) => {
      const u = new URL(url, location.origin);
      if (u.pathname !== location.pathname) {
        location.href = url;   // 跳出 /admin 本身（回前台、退出后的落地页）就正常走
        return;
      }
      history[replace ? "replaceState" : "pushState"]({}, "", u.pathname + u.search);
      reload();
    },
    [reload],
  );
}

export function Link({ href, onGo, children, className, title }: { href: string; onGo: (u: string, r?: boolean) => void; children: ReactNode; className?: string; title?: string }) {
  return (
    <a
      href={href}
      title={title}
      className={`text-accent underline-offset-2 hover:underline ${className ?? ""}`}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey) return;
        e.preventDefault();
        onGo(href);
      }}
    >
      {children}
    </a>
  );
}

/** 一小节。锚点 id 与侧边目录、滚动定位共用同一套名字（ADMIN_TABS 里那份）。 */
export function Block({ id, title, sub, children }: { id: string; title: string; sub?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-14 space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-sm font-semibold tracking-wide text-foreground">{title}</h2>
        {sub ? <span className="num text-[11px] text-muted">{sub}</span> : null}
      </div>
      {children}
    </section>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-2xl bg-surface p-4 text-surface-foreground shadow-surface ring-1 ring-border ${className ?? ""}`}>{children}</div>;
}

/** 后台每一张表都是这一份：HeroUI 的 Table + 「N 行内联滚动」+ 表头吸顶。
 *
 *  限高为什么落在 .table__scroll-container 这一层，而不是外面再套一个 div：
 *  Table.Root 自带 overflow-clip（它是 grid，给圆角用的），把限高写在外层的话，
 *  宽表是被**裁掉**而不是滚出来的；同时 sticky 的 th 只跟着"最近的滚动祖先"吸，
 *  外层滚、内层也滚的话表头就吸在看不见的位置上。所以这一层既是横向滚动条，
 *  也是纵向限高与吸顶的那个框。 */
export function Table({ head, children, dense, rows, label }: {
  head: ReactNode[];
  children: ReactNode;
  dense?: boolean;
  rows?: number;
  label?: string;
}) {
  // 限高那三件事（量第 N+1 行、补滚动条、不许用 rAF）收在 useClamp 里，前台的检索快照共用
  const calc = useCallback(
    (el: HTMLElement) => {
      if (rows === undefined) return null;
      const trs = el.querySelectorAll("tbody tr");
      if (trs.length <= rows) return null;
      const h = (trs[rows] as HTMLElement).offsetTop;
      el.style.maxHeight = `${h}px`;   // 先夹一次再量第二遍：滚动条一出现行会重排
      return h + (el.offsetHeight - el.clientHeight);
    },
    [rows],
  );
  const setBox = useClamp(calc);

  return (
    <HeroTable variant="secondary" className={dense ? "tbl-dense" : "tbl-plain"}>
      {/* relative 不是可有可无：offsetTop 量的是"相对最近的定位祖先"，
          不写就会一路找到页面外层，算出来的高度大得离谱，限高等于没限 */}
      <HeroTable.ScrollContainer ref={setBox} className="relative">
        <HeroTable.Content aria-label={label || head.filter(Boolean).join(" / ") || "统计表"}>
          <HeroTable.Header>
            {/* 表头吸顶：这些表都在自己那个框里滚，滚两行就认不出这一列是什么了。
                底色由 .table-root--secondary .table__column 给（必须不透明，否则行从字底下透过去）；
                分隔线用 inset box-shadow —— HeroUI 给列头画的是列间竖线，横着那条得自己补。 */}
            {head.map((h, i) => (
              <HeroTable.Column
                key={i}
                isRowHeader={i === 0}
                className="sticky top-0 z-10 text-start text-muted shadow-[inset_0_-1px_0_var(--border)] first:pl-0 last:pr-0"
              >
                {h}
              </HeroTable.Column>
            ))}
          </HeroTable.Header>
          <HeroTable.Body>{children}</HeroTable.Body>
        </HeroTable.Content>
      </HeroTable.ScrollContainer>
    </HeroTable>
  );
}

/** 一行。行与行之间的分隔线 HeroUI 已经画在 .table__row 上了，调用点别再写 border-b；
 *  但"点开行"和"命中行为特征的行"那两种着色必须走 .row-click / .row-suspicious
 *  （它们落在单元格上，写在 tr 上会被单元格的底色盖住）。 */
export function Row({ children, className }: { children: ReactNode; className?: string }) {
  return <HeroTable.Row className={className ?? ""}>{children}</HeroTable.Row>;
}

export const Cell = ({ children, className }: { children: ReactNode; className?: string }) => (
  <HeroTable.Cell className={className ?? ""}>{children}</HeroTable.Cell>
);

export const Num = ({ children, zero }: { children: ReactNode; zero?: boolean }) => (
  <HeroTable.Cell className={`num text-right tabular-nums ${zero ? "text-danger" : "text-foreground"}`}>{children}</HeroTable.Cell>
);
export const Txt = ({ children, dim, mono, title }: { children: ReactNode; dim?: boolean; mono?: boolean; title?: string }) => (
  <HeroTable.Cell className={`${dim ? "text-muted" : "text-foreground"} ${mono ? "num" : ""} max-w-[28rem] truncate`}>
    {/* title 挂在单元格里那层 span 上：RAC 的 Cell 不接受 title 属性，
        而悬停说明必须挂在能显示省略号的这一层，挂到 td 上会被 overflow 裁掉 */}
    {title ? <span title={title}>{children}</span> : children}
  </HeroTable.Cell>
);

/** 空值一律一个破折号：留白会让人以为"还没统计出来" */
export const dash = (v: ReactNode | null | undefined) => (v === null || v === undefined || v === "" ? "—" : v);

/** 表格里那些"点一下就是加一个筛选"的链接：在当前 URL 上改一两个参数，
 *  其余条件（日期范围、tab、per）原样带着 —— 否则点一个 IP 就把人筛没了。
 *  规则与老模板里 admin_url() 那个 Jinja 全局一致。 */
export function filterUrl(patch: Record<string, string>, tab?: string) {
  const u = new URL(location.href);
  for (const [k, v] of Object.entries(patch)) {
    if (v) u.searchParams.set(k, v);
    else u.searchParams.delete(k);
  }
  u.searchParams.set("tab", tab ?? (u.searchParams.get("tab") || "overview"));
  return `${u.pathname}?${u.searchParams}`;
}


/** 真人 / 脚本 / 说不清 / 行为像脚本 四档徽章。
 *  判据与文案全部由服务端算（labels.who + beh_map），这里只负责上色与是否挂筛选链接：
 *  「说不清」那一档不能挂 ?who= 链接 —— 那一行的 who 是被行为改判过的，筛不出来。 */
export function WhoBadge({ who, labels, title, href, onGo }: { who: string; labels: AdminView["labels"]["who"]; title?: string; href?: string | null; onGo?: (u: string) => void }) {
  const text = who === "unknown" ? "说不清" : (labels[who] || who);
  // 档位色集中在 styles.css 的 .who-* 这几条里：五档颜色在两张表上要用同一套，
  // 写在 Tailwind 类名上迟早会被复制成两份不同的红
  const tone =
    who === "bot" ? "who-bot" : who === "suspect" ? "who-suspect" : who === "unknown" ? "who-unknown" :
    who === "mixed" ? "who-mixed" : "who-human";
  const body = <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${tone}`} title={title}>{text}</span>;
  if (!href || !onGo) return body;
  return (
    <button type="button" className="cursor-pointer" onClick={() => onGo(href)}>
      {body}
    </button>
  );
}

/** 行为特征那几颗胶囊：命中了哪几条（short），完整理由在 title 里。
 *  src=='act' 的那几条才会出现在明细行上 —— 口径和行为表里那张保持一致。 */
export function ReasonChips({ reasons, onlyAct, onFilter }: { reasons: Reason[]; onlyAct?: boolean; onFilter?: (r: Reason) => void }) {
  const list = useMemo(() => (onlyAct ? reasons.filter((r) => r.src === "act") : reasons), [reasons, onlyAct]);
  if (!list.length) return <span className="text-[11px] text-muted">没看出异常</span>;
  return (
    <>
      {list.map((r) => (
        <button
          key={r.key}
          type="button"
          title={r.text}
          onClick={() => onFilter?.(r)}
          className="why-chip mr-1 rounded-full px-1.5 py-0.5 text-[10px]"
        >
          {r.short}
        </button>
      ))}
    </>
  );
}

export const gap = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v.toFixed(1)}`);

/** 设置里布尔项的取值：后端可能给 true / 1 / "1"，开关只看这几种。 */
export const isOn = (v: string | number | boolean | null | undefined) => v === true || v === 1 || String(v) === "1";

export function behHref(flt: Filters | undefined, ip: string, base: string) {

  const u = new URL(base, location.origin);
  Object.entries(flt || {}).forEach(([k, v]) => { if (v && k !== "ip") u.searchParams.set(k, String(v)); });
  u.searchParams.set("ip", ip);
  return `${u.pathname}?${u.searchParams.toString()}`;
}

export function whoMerge(row: BehRow | undefined, rWho: string): { who: string; title?: string; linkable: boolean } {
  // 只有"UA 说像真人、但这个 IP 同时命中脚本行为"才改判；其余照 UA 那一档写
  if (rWho === "human" && row && row.who !== "human") {
    return {
      who: row.who,
      title: `UA 是浏览器的样子，但这个 IP 同时命中 ${row.act_n} 条脚本行为特征（就是 IP 旁边那几颗胶囊），所以不写「像真人」`,
      linkable: false,
    };
  }
  return { who: rWho, linkable: rWho === "bot" || rWho === "unknown" };
}
