/** 后端 JSON 的字段契约。命名一律跟 zhuiju/*.py 里的原始字符串一致（snake_case），
 *  前端不要改名，否则出问题时两边对不上号。 */

export interface SourceStatus {
  source: string;
  source_name: string;
  ok: boolean;
  count: number;
  ms: number;
  error: string | null;
}

export interface DeepLink {
  url: string;
  kind: string;
}

/** /api/search 的一条结果：同一个片名在多个源里合并成一行 */
export interface VodItem {
  title: string;
  type: string;
  year: string;
  area: string;
  remarks: string;
  actor: string;
  director: string;
  pic: string;
  notes: string;
  updated: string;
  slug: string;
  vid: string | number;
  source: string;
  source_name: string;
  link: string;
  sources: {
    id: string;
    name: string;
    link: string;
    remarks?: string;
    year?: string;
    vid?: string | number;
  }[];
  source_ids: string[];
  tier: number;
  exact: boolean;
  match: "exact" | "series" | "contains" | "other";
  key_len: number;
}

export interface SearchResult {
  keyword: string;
  page: number;
  results: VodItem[];
  dropped_noise: number;
  limit: number;
  has_more: boolean;
  status: SourceStatus[];
  sources_ok: number;
  sources_total: number;
  hits: number;
}

/** /api/deeplinks：把片名带到各家站内搜索页 */
export interface DeeplinkItem {
  name: string;
  category: string;
  dot: string;
  status: string;
  recommended: number;
  url: string;
  kind: string;
  featured: boolean;
  home: string;
}

export interface DeeplinksResult {
  keyword: string;
  items: DeeplinkItem[];
}

export interface CatalogRow {
  id: string;
  name: string;
  url: string;
  category: string;
  category_cn: string;
  tags: string[];
  scores: { more: number; speed: number; clean: number; stable: number; ease: number };
  recommended: number;
  featured: boolean;
  hints: string[];
  status: string;
  status_key: string;
  checked_at: string;
  dot: string;
  score: number;
  deep: DeepLink | null;
}

export interface CatalogCategory {
  name: string;
  total: number;
  working: number;
}

export interface CatalogResult {
  keyword: string;
  link_kw: string;
  total: number;
  items: CatalogRow[];
  categories: CatalogCategory[];
}

/** /api/cloud：服务端真的去各家网盘站抓一遍 */
export interface CloudSite {
  id: string;
  name: string;
  category: string;
  status: string;
  search_url?: string;
  kind: string;
  recommended?: number;
  home?: string;
  can_query?: boolean;
  items?: { title: string; link: string; host: string }[];
  count?: number;
  ok?: boolean;
  error?: string | null;
}

export interface CloudResult {
  keyword: string;
  mode?: "sites";
  sites: CloudSite[];
  total_sites: number;
  can_query?: number;
  with_results: number;
  entries: number;
  note?: string;
}

export interface Episode {
  name: string;
  url: string;
}

export interface Line {
  from: string;
  episodes: Episode[];
}

export interface DetailResult {
  ok: boolean;
  error: string | null;
  title: string;
  type: string;
  year: string;
  area: string;
  actor: string;
  director: string;
  pic: string;
  blurb: string;
  notes: string;
  /** 上游有时只给 remarks 不给 notes，两个都留着才能填「更新」那一行 */
  remarks?: string;
  lines: Line[];
  source: string;
  source_name: string;
  /** 只有「按片名兜底」那条路才带；带 kw 表示 ID 没取到、退而求其次搜到的 */
  via?: string;
  matched?: string;
  match?: string;
  n_sources?: number;
}

export interface HotRow {
  title: string;
  kind: string;
  year: string;
  type: string;
  remarks: string;
  pic: string;
  rate: string;
  douban: boolean;
  updated: string;
  n_sources: number;
  from_douban: boolean;
  src?: string;
  vid?: string | number;
  sources?: { id: string; name: string; vid: string | number }[];
  url: string;
}

/** /api/hot 无 kind 时是整包缓存，有 kind 时是分页切片，两种形状都要接得住 */
export interface HotResult {
  kind?: string;
  offset?: number;
  limit?: number;
  total?: number;
  items?: HotRow[];
  has_more?: boolean;
  next?: number;
  movie?: HotRow[];
  tv?: HotRow[];
  movie_total?: number;
  tv_total?: number;
  since?: string;
  window_days?: number;
  candidates?: number;
  dropped_kind?: number;
  sources_ok?: number;
  sources_total?: number;
  stale?: boolean;
  cached?: boolean;
  building?: boolean;
}

export interface HealthResult {
  keyword: string;
  results: {
    id: string;
    name: string;
    ok: boolean;
    mode: string;
    count: number;
    ms: number;
    error: string | null;
    sample: string[];
  }[];
}

export interface RefreshStep {
  key: string;
  label: string;
  state: string;
}

export interface RefreshProgress {
  running: boolean;
  pct: number;
  done: number;
  total: number;
  step_key: string;
  step_label: string;
  note: string;
  steps: RefreshStep[];
}

export interface RefreshResult {
  running: boolean;
  need_update: boolean;
  date: string;
  ok: boolean;
  finished_at: string;
  failed_steps: string[];
  progress: RefreshProgress | null;
  retry_in: number;
  [k: string]: unknown;
}

/** 页头横幅那一行：服务端算好的，前端不重算口径 */
export interface Banner {
  fresh: boolean;
  state: "running" | "never" | "fresh" | "failed" | "partial" | "stale";
  text: string;
  hint: string;
  progress: RefreshProgress | null;
}

/** GET /s/<kw> 那份服务端快照，爬虫与无 JS 的人看的就是它 */
export interface Snapshot {
  kw?: string;
  made_at?: string;
  sources_ok?: number;
  sources_total?: number;
  count?: number;
  items?: { title: string; year: string; type: string; remarks: string; n_sources: number; url: string }[];
  error?: string;
  from_cache?: boolean;
}

export interface Challenge {
  id: string;
  target: number;
  ttl: number;
  tol: number;
}
