import type { Banner, CatalogCategory, HotResult, Snapshot } from "./types";

/** Flask 的壳（zhuiju/templates/shell.html）注进来的那一份首屏数据。
 *  只放"第一帧就要用"的东西，其余一律走 /api/*，免得壳越来越大。 */
export interface Boot {
  kw: string;
  page: number;
  site: string;
  canonical: string;
  title: string;
  description: string;
  /** 门禁没放行时为 true：内容一个字段都不给，前端只出滑块 */
  locked: boolean;
  /** 搜索引擎爬虫豁免的那条路：服务端已经把结果渲染进 HTML，前端不用再抓首屏 */
  crawler: boolean;
  /** 被门禁挡下时，验完该回哪儿（服务端记的就是用户原本要点开的那一页） */
  back: string;
  gate_hours: number;
  sources: { id: string; name: string; note: string; root: string }[];
  categories: CatalogCategory[];
  hot: HotResult;
  refresh: Banner | null;
  snapshot: Snapshot;
}

const EMPTY: Boot = {
  kw: "",
  page: 1,
  site: "",
  canonical: "",
  title: "追剧资源搜索",
  description: "",
  locked: false,
  crawler: false,
  back: "/",
  gate_hours: 12,
  sources: [],
  categories: [],
  hot: {},
  refresh: null,
  snapshot: {},
};

export function readBoot(): Boot {
  const el = document.getElementById("boot-data");
  if (!el?.textContent) return EMPTY;
  try {
    return { ...EMPTY, ...(JSON.parse(el.textContent) as Partial<Boot>) };
  } catch {
    // 解析不了就按"没有首屏"处理，让前端照样能从 /api/hot 取到数据
    return EMPTY;
  }
}

export const boot = readBoot();
