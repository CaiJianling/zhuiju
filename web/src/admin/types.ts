/** /api/admin/view 的响应形状。字段名与 zhuiju/app.py 的 _admin_ctx() 一一对应，
 *  不改名 —— 出问题时两边要能直接对上行号。 */

export interface Filters {
  ip: string; kw: string; via: string; geo: string; browser: string; os: string;
  device: string; ref_kind: string; who: string; day_from: string; day_to: string;
  title: string; host: string; place: string; kind: string; scope: string; per: number;
}

export interface TabInfo {
  id: string;
  label: string;
  blocks: [string, string][];
  href: string;
}

export interface ByDay { day: string; n: number; ips: number; empty: number }
export interface TopKw { kw: string; n: number; ips: number; avg_results: number | null }
export interface TopIp { ip: string; n: number; kws: number; first_day: string; last_day: string }
export interface Agent { browser: string; bots: number | null; os: string; device: string; n: number; ips: number }
export interface RefSrc { kind: string; label: string; n: number; ips: number; last_day: string }
export interface GeoRow { iso: string; country: string; n: number; ips: number; kws: number; last_day: string }
export interface WhoRow { who: string; n: number }

export interface Agg {
  count: number; ips: number; kws: number; empty: number;
  avg_ok: number | null; avg_ms: number | null; first_ts: string | null; last_ts: string | null;
  by_day: ByDay[]; top_kw: TopKw[]; top_ip: TopIp[];
  by_browser: Agent[]; by_ref: { kind: string; n: number }[]; by_ref_src: RefSrc[];
  by_geo: GeoRow[]; by_who: WhoRow[]; by_via: { via: string; n: number }[];
  by_verified: { yes?: number; crawler?: number; off?: number };
}

export interface ClickAgg {
  detail: number; play: number; count: number;
  by_kind: { kind: string; n: number; ips: number }[];
  by_host: { host: string; n: number }[];
}

export interface Reason { key: string; text: string; short: string; src: string }

export interface BehRow {
  ip: string; geo: string | null; n: number; kws: number; click_n: number; site_n: number;
  min_gap: number | null; avg_gap: number | null; sd_gap: number | null; cv: number | null;
  peak_min: number; who: string; who_ua: string; act_n: number; reasons: Reason[];
}

export interface ActRow {
  type: "click" | "query"; ts: string; ip: string; iso: string | null; geo: string | null;
  browser: string | null; os: string | null; device: string | null; who: string;
  place: string | null; ref_kind: string | null; ref_label: string | null;
  kw: string | null; title: string | null; src_name: string | null; line: string | null;
  ep: string | null; host: string | null; url: string | null; bot?: number | null;
  kind: string | null; via: string | null;
  results: number | null; hits: number | null; sources_ok: number | null; sources_total: number | null;
  ms: number | null;
}

export interface Marker { iso: string; name: string; n: number; ips: number; x: number; y: number; r: number }

export interface StrmPart {
  name: string; titles: number; files: number; zip_bytes: number | null;
  zip: string | null; zip_url: string | null; index_url: string | null; tree_url: string | null;
}
export interface StrmMeta {
  counts: { vods: number; titles: number; movies: number; shows: number; sources: number; urls: number; files: number; dirty: number };
  window_days: number; since: string;
  kinds: Record<string, { label: string; titles: number; files: number; parts: StrmPart[]; zip_hint?: string }>;
  cursor: { src: string; pg: number; stop: string; requests: number; last_time: string | null }[];
  sources: { id: string; name: string; vods: number; titles: number; m3u8_urls: number }[];
  ids?: Record<string, unknown>;
  nfo?: { write?: boolean; files?: number };
}
export interface StrmSpecRow {
  key: string; label: string; default: string | number | boolean; value: string | number | boolean;
  kind: string; lo?: number; hi?: number; secret?: boolean; filled?: boolean; help?: string;
}
export interface StrmJob {
  running: boolean; next_in: number | null; last_trigger: string | null; python?: string;
  settings: { enabled: boolean | number; min_interval_minutes: number; budget_seconds: number; window_days?: number };
  state: { at?: string | null; pages?: number; requests?: number; note?: string | null } | null;
  progress: { note?: string; requests?: number; pages?: number; rows_new?: number; rows_changed?: number; since?: string } | null;
  lines: { ids: string; nfo: string };
  counts?: StrmMeta["counts"];
  run_cmd?: string; check_cmd?: string; log?: string; script?: string;
}

export interface SetField { key: string; spec: { label: string; kind: string; min?: number; max?: number; env?: string; hint?: string }; value: string | number | boolean }

export interface AdminView {
  authed: boolean;
  csrf: string;
  tab: string;
  tabs: TabInfo[];
  error?: string;
  // 未登录时才有意义：还是不是首次生成的随机口令 / 口令被环境变量顶着 / 最短长度
  temp?: boolean;
  min_len?: number;
  env_lock?: boolean;
  flt?: Filters;
  rows?: { total: number; page: number; per: number; pages: number; scope: string; items: ActRow[] };
  agg?: Agg;
  cagg?: ClickAgg;
  beh?: BehRow[];
  beh_map?: Record<string, BehRow>;
  labels: {
    via: Record<string, string>; ref_kind: Record<string, string>; place: Record<string, string>;
    kind: Record<string, string>; scope: Record<string, string>; who: Record<string, string>;
  };
  thresholds?: { suspect: number; script: number };
  geo?: { ready: boolean; points: number; basemap: boolean; error?: string | null };
  markers?: Marker[];
  offmap?: { name: string }[];
  map_active?: string;
  geo_warn?: string | null;
  fetch_cmd?: string;
  smeta?: StrmMeta;
  sjob?: StrmJob;
  sspec?: StrmSpecRow[];
  smsg?: string | null;
  setfields?: SetField[];
  setsrc?: Record<string, string>;
  setinfo?: {
    hour: number; source: string; path: string; roll: string; logical_day: string; due: boolean;
    spec: { env?: string; hint?: string; min?: number; max?: number };
  };
  upd?: { python: string; python_why: string; last_trigger: string | null; retry_in: number; retry_minutes: number; retry_cmd: string };
  day_all?: boolean;
  day_window?: number;
  keep_days?: number;
  notice?: string | null;
  settings_err?: boolean;
  pct_empty?: number;
  links?: {
    prev: string | null; next: string | null; all_days: string;
    scopes: Record<string, string>; click_detail: string;
  };
}
