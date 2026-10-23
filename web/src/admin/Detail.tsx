import { useState } from "react";
import { Button } from "@heroui/react";
import { Block, Card, Fold, Link, Num, ReasonChips, Table, Txt, WhoBadge, dash, filterUrl, useFoldMemo, whoMerge } from "./ui";
import type { AdminView, BehRow } from "./types";

type Go = (u: string, replace?: boolean) => void;

const SCOPE_NOTE: Record<string, string> = {
  all: "（搜索与点开合流，按时间倒序）",
  query: "（只看搜索）",
  click: "（只看点开）",
};

/** 「像脚本的行为特征」：UA 三档只是"它自己说的"，这一节按 IP 看节奏、跳转与点开比。
 *  默认收起、点开过就记住（同一个 localStorage 键，和老模板共用，别换名字）。 */
function Behavior({ v, onGo }: { v: AdminView; onGo: Go }) {
  const [open, setOpen] = useFoldMemo("zhuiju.admin.behaviorFold");
  const rows = v.beh || [];
  const th = v.thresholds!;
  const why = (b: BehRow) => `UA 那一档是「${v.labels.who[b.who_ua] || b.who_ua}」；命中 ${b.act_n} 条行为特征 → 这一档是「${v.labels.who[b.who] || b.who}」`;

  return (
    <Block id="behavior" title="像脚本的行为特征" sub={`命中 ${th.suspect} 条改判「行为像脚本」、${th.script} 条改判「脚本/爬虫」`}>
      <Card>
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          className="flex w-full items-center justify-between gap-3 text-left text-xs"
        >
          <span className="text-muted">
            {open ? "点击收起" : "点开看"}：按 IP 看请求节奏、站内跳转比例与点开比 —— 这几条不是 UA 能伪造的
          </span>
          <span className="num shrink-0 text-[11px] text-muted">{rows.length} 个 IP</span>
        </button>
        {open ? (
          rows.length ? (
            <div className="mt-3">
              <Fold rows={5}>
                <Table dense head={["IP", "归属地", "搜索", "词", "点开比", "站内跳转", "最快间隔", "平均间隔", "峰值", "分", "判读"]}>
                  <tbody>
                    {rows.map((b) => (
                      <tr key={b.ip} className={`border-b border-separator/70 last:border-0 ${b.reasons?.length ? "row-suspicious" : ""}`}>
                        <Txt mono>
                          <Link href={filterUrl({ ip: b.ip })} onGo={onGo}>{b.ip}</Link>
                        </Txt>
                        <Txt dim>{b.geo || "未解析"}</Txt>
                        <Num>{b.n}</Num>
                        <Num>{b.kws}</Num>
                        <Num>{((b.click_n / Math.max(1, b.n)) * 100).toFixed(0)}%</Num>
                        <Num>{Math.round((b.site_n / Math.max(1, b.n)) * 100)}%</Num>
                        <Num>{b.min_gap === null ? "—" : b.min_gap.toFixed(1)}</Num>
                        <Num>{b.avg_gap === null || b.sd_gap === null ? "—" : `${b.avg_gap.toFixed(1)} ± ${b.sd_gap.toFixed(1)}`}</Num>
                        <Num>{b.peak_min}</Num>
                        <td className="px-2 py-1 text-right">
                          <WhoBadge who={b.who} labels={v.labels.who} title={why(b)} />
                        </td>
                        <td className="px-2 py-1">
                          <ReasonChips reasons={b.reasons || []} onFilter={() => onGo(filterUrl({ ip: b.ip }))} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Fold>
              <p className="mt-2 text-[11px] leading-relaxed text-muted">
                「最快间隔」是同一 IP 两次查询之间最短的秒数；「峰值」是一分钟里最多几次。
                人手点不出 0.3 秒一次，但脚本会 —— 这两列比 UA 靠谱。
              </p>
            </div>
          ) : (
            <p className="mt-2 text-xs text-muted">这个条件下没有可分析的记录。</p>
          )
        ) : null}
      </Card>
    </Block>
  );
}

/** 明细：一行一次动作。搜索行与点开行合在一条时间线上，才看得出"这个人当时做了什么"。 */
function Detail({ v, onGo }: { v: AdminView; onGo: Go }) {
  const rows = v.rows!;
  const [jump, setJump] = useState(String(rows.page));
  const flt = v.flt!;
  const detailNote = flt.via || flt.ref_kind ? "（按入口/来源筛的是搜索记录，点开行没有这两列，已排除）" : "";

  function goPage(n: number) {
    const p = Math.max(1, Math.min(rows.pages, n));
    onGo(filterUrl({ page: String(p), per: String(flt.per) }));
  }

  return (
    <Block
      id="detail"
      title="明细"
      sub={
        <span>
          第 {rows.page} / {rows.pages} 页 · 共 {rows.total} 条 {SCOPE_NOTE[rows.scope] || ""}
          {detailNote}
        </span>
      }
    >
      {/* 范围三胶囊：换范围必须回第 1 页（两边条数不一样），所以地址由服务端拼好 */}
      <div className="flex flex-wrap items-center gap-2">
        {Object.entries(v.labels.scope).map(([k, label]) => (
          <Button key={k} size="sm" variant={rows.scope === k ? "primary" : "tertiary"} className="rounded-full"
                  onPress={() => onGo(v.links!.scopes[k])}>
            {label}
          </Button>
        ))}
        <span className="text-[11px] text-muted">
          {v.day_all
            ? `全部历史 · 库里最多留 ${v.keep_days} 天`
            : `最近 ${v.day_window} 天 · 库里最多留 ${v.keep_days} 天 · `}
          <Link href={v.links!.all_days} onGo={onGo}>看全部历史</Link>
        </span>
      </div>

      <Card>
        {!rows.items.length ? (
          <p className="text-xs leading-relaxed text-muted">
            这个条件下没有记录（当前范围是「{v.labels.scope[rows.scope]}」，切回「全部」再看看）。
            换个日期范围或清空筛选试试。
          </p>
        ) : (
          <Fold rows={10}>
            <Table dense head={["时间", "IP", "归属地", "浏览器", "系统", "来源页", "关键词 / 点了什么", "入口", "结果", "原始命中", "可用源", "耗时 ms"]}>
              <tbody>
                {rows.items.map((r, i) => {
                  const bh = (v.beh_map || {})[r.ip];
                  const w = whoMerge(bh, r.who);
                  const isClick = r.type === "click";
                  return (
                    <tr key={`${r.ts}-${i}`} className={`border-b border-separator/70 last:border-0 ${isClick ? "row-click" : ""}`}>
                      <Txt mono dim>{r.ts?.slice(5, 16)}</Txt>
                      <td className="px-2 py-1">
                        <span className="num block max-w-[28rem] truncate">{r.ip}</span>
                        {bh?.reasons?.length ? <ReasonChips reasons={bh.reasons} onlyAct /> : null}
                      </td>
                      <Txt dim>
                        {r.iso && r.iso.length === 2 ? <Link href={filterUrl({ geo: r.iso })} onGo={onGo}>{r.geo || r.iso}</Link> : (r.geo || "未解析")}
                      </Txt>
                      <td className="px-2 py-1">
                        <span className="block max-w-[12rem] truncate">{dash(r.browser ?? "未知")}</span>
                        <WhoBadge who={w.who} labels={v.labels.who} title={w.title}
                                  href={w.linkable ? filterUrl({ who: w.who }) : null} onGo={onGo} />
                      </td>
                      <Txt dim>{r.os || "未知"}</Txt>
                      <Txt dim title={r.ref_label || undefined}>
                        {r.ref_label || "直接访问 / 无来源"}
                        {r.ref_kind ? `（${v.labels.ref_kind[r.ref_kind] || r.ref_kind}）` : ""}
                      </Txt>
                      <td className="max-w-[22rem] px-2 py-1">
                        {isClick ? (
                          <span className="block truncate" title={r.url || undefined}>
                            <span className="text-muted">{v.labels.kind[r.kind || "play"] || "观看地址"}：</span>
                            {r.title || "（没带片名）"}
                            {r.host ? <span className="text-muted"> · {r.host}</span> : ""}
                            {r.ep ? <span className="text-muted"> · {r.ep}</span> : ""}
                            {r.bot ? <span className="text-muted">（程序）</span> : ""}
                          </span>
                        ) : (
                          <Link href={filterUrl({ kw: r.kw || "" })} onGo={onGo}>{r.kw}</Link>
                        )}
                      </td>
                      <Txt dim>{isClick ? (v.labels.place[r.place || "card"] || "卡片线路") : (v.labels.via[r.via || ""] || r.via || "")}</Txt>
                      <Num zero={r.results === 0}>{r.results === null || r.results === undefined ? "—" : r.results}</Num>
                      <Num>{dash(r.hits)}</Num>
                      <Num>{r.sources_ok === null || r.sources_ok === undefined ? "—" : `${r.sources_ok}/${r.sources_total ?? "—"}`}</Num>
                      <Num>{dash(r.ms)}</Num>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          </Fold>
        )}
      </Card>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Button size="sm" variant="tertiary" className="rounded-full" isDisabled={!v.links!.prev}
                onPress={() => v.links!.prev && onGo(v.links!.prev)}>
          ‹ 上一页
        </Button>
        <span className="num text-muted">第 {rows.page} / {rows.pages} 页 · 每页 {rows.per} 条</span>
        <Button size="sm" variant="tertiary" className="rounded-full" isDisabled={!v.links!.next}
                onPress={() => v.links!.next && onGo(v.links!.next)}>
          下一页 ›
        </Button>
        <input
          type="number"
          min={1}
          max={rows.pages}
          value={jump}
          aria-label="页码"
          onChange={(e) => setJump(e.target.value)}
          className="num h-8 w-20 rounded-full bg-field-background px-3 text-xs text-foreground outline-none ring-1 ring-border focus:ring-2 focus:ring-accent"
        />
        <Button size="sm" variant="ghost" className="rounded-full" onPress={() => goPage(Number(jump) || 1)}>
          跳
        </Button>
      </div>
    </Block>
  );
}

export function DetailTab({ v, onGo }: { v: AdminView; onGo: Go }) {
  return (
    <div className="space-y-8">
      <Behavior v={v} onGo={onGo} />
      <Detail v={v} onGo={onGo} />
    </div>
  );
}
