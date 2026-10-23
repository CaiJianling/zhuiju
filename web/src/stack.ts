import type { SearchResult, VodItem } from "./types";

/** 「往后追加页」用的那一叠结果。
 *
 *  服务端一次只合并**一页**（`search.merge(per_source, kw)`），所以第 2 页很可能又
 *  吐出同一部片 —— 另一家源的条目。直接铺在下面的话就是"同一张海报出现两次"，
 *  看着像 bug。这里按归一化片名把新页并进已有那一叠：同一部片就合来源，不新增卡片。
 *  合并规则跟着服务端那条：源按 id+vid 去重、信息更全的一条赢（有海报/年份/演员优先）。 */
export type Stack = {
  kw: string;
  /** URL 上那一页 = 这一叠的起始页（翻页按钮没了，但直链与后退还要认它） */
  from: number;
  /** 已经并进第几页 */
  pages: number;
  items: VodItem[];
  status: SearchResult["status"];
  sources_ok: number;
  sources_total: number;
  hits: number;
  dropped_noise: number;
  /** 各页耗时加起来：这一叠一共等了多久 */
  ms: number;
  /** 还有下一页吗（服务端那句 + "连着两页都是老片"也算完） */
  hasMore: boolean;
  /** 这一页并完一部新片都没加：那就是各源把这部剧翻到头了，别再自动往下要 */
  stalled: boolean;
};

/** 归一化片名：去空白与标点、大小写折叠。和服务端 title_key() 不必逐字节一致，
 *  这里只需要"同一部片的两种写法落到同一个键"，判得太狠反而会把季数分开。 */
const norm = (t: string) =>
  t.toLowerCase().replace(/[\s\-—–_:：·・‧.,，、!！?？~～'"\[\]【】()（）《》]/g, "");

/** 信息完整度，和服务端 _richness 同一个意思（有海报/年份/演员的那条说话） */
const rank = (it: { pic?: string; year?: string; actor?: string; remarks?: string }) =>
  (it.pic ? 4 : 0) + (it.year ? 2 : 0) + (it.actor ? 1 : 0) + (it.remarks ? 1 : 0);

export function stackFrom(d: SearchResult, spent: number): Stack {
  return {
    kw: d.keyword,
    from: d.page,
    pages: d.page,
    items: d.results,
    status: d.status,
    sources_ok: d.sources_ok,
    sources_total: d.sources_total,
    hits: d.hits,
    dropped_noise: d.dropped_noise,
    ms: spent,
    hasMore: d.has_more && d.results.length > 0,
    stalled: false,
  };
}

/** 把下一页并进这一叠，返回新的一份（不改入参：React 拿旧值还要能比出来） */
export function appendPage(cur: Stack, d: SearchResult, spent: number): Stack {
  const at = new Map<string, number>();
  const items = cur.items.slice();
  cur.items.forEach((it, i) => at.set(norm(it.title), i));

  let fresh = 0;
  for (const it of d.results) {
    const k = norm(it.title);
    const i = at.get(k);
    if (i === undefined) {
      at.set(k, items.length);
      items.push(it);
      fresh += 1;
      continue;
    }
    const base = items[i];
    const seen = new Set(base.sources.map((s) => `${s.id}:${s.vid ?? ""}`));
    const sources = base.sources.slice();
    for (const s of it.sources) {
      const id = `${s.id}:${s.vid ?? ""}`;
      if (!seen.has(id)) {
        seen.add(id);
        sources.push(s);
      }
    }
    const win = rank(it) > rank(base) ? it : base;
    items[i] = {
      ...base,
      ...(["year", "area", "type", "pic", "actor", "director", "remarks", "updated", "notes"] as const).reduce(
        (acc, key) => (win[key] ? { ...acc, [key]: win[key] } : acc),
        {} as Partial<VodItem>,
      ),
      sources,
    };
  }

  // 并完一部新的都没加 = 各源在往下重复同一批片，继续自动翻只是白花请求
  const stalled = fresh === 0 && items.length > 0;
  return {
    ...cur,
    items,
    pages: d.page,
    status: d.status,
    sources_ok: d.sources_ok,
    sources_total: d.sources_total,
    hits: cur.hits + d.hits,
    dropped_noise: cur.dropped_noise + d.dropped_noise,
    ms: cur.ms + spent,
    hasMore: d.has_more && !stalled,
    stalled,
  };
}
