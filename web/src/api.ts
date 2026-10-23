import { markDenied } from "./auth";
import type {
  CatalogResult,
  Challenge,
  CloudResult,
  DeeplinksResult,
  DetailResult,
  HealthResult,
  HotResult,
  RefreshResult,
  SearchResult,
} from "./types";

/** 接口被门禁挡住（423）。不是错误，是"还没验过"，所以单独一个类，
 *  调用点可以只认它、把它和"网络不通""关键词太短"分开处理。 */
export class GateBlocked extends Error {
  constructor() {
    super("需要先通过真人验证");
    this.name = "GateBlocked";
  }
}

export function isGate(e: unknown): boolean {
  return e instanceof GateBlocked;
}

async function request<T>(path: string, init?: RequestInit, signal?: AbortSignal): Promise<T> {
  const r = await fetch(path, {
    credentials: "same-origin",
    ...init,
    signal,
    headers: { Accept: "application/json", ...(init?.headers || {}) },
  });
  if (r.status === 423) {
    markDenied();
    throw new GateBlocked();
  }
  let data: unknown = null;
  try {
    data = await r.json();
  } catch {
    /* 空体或非 JSON：下面按状态码报错 */
  }
  if (!r.ok) {
    const msg = (data as { error?: string })?.error || `接口返回 ${r.status}`;
    throw new Error(msg);
  }
  return data as T;
}

function qs(pairs: Record<string, string | number | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(pairs)) {
    if (v !== undefined && v !== "") p.set(k, String(v));
  }
  return p.toString();
}

const get = <T,>(path: string, params: Record<string, string | number | undefined>, signal?: AbortSignal) =>
  request<T>(`${path}?${qs(params)}`, undefined, signal);

export const api = {
  search: (kw: string, page = 1, signal?: AbortSignal) =>
    get<SearchResult>("/api/search", { kw, page }, signal),
  deeplinks: (kw: string, signal?: AbortSignal) => get<DeeplinksResult>("/api/deeplinks", { kw }, signal),
  catalog: (
    params: { kw?: string; category?: string; only_working?: 1; link_kw?: string },
    signal?: AbortSignal,
  ) => get<CatalogResult>("/api/catalog", params, signal),
  cloud: (kw: string, signal?: AbortSignal) => get<CloudResult>("/api/cloud", { kw }, signal),
  detail: (params: { src?: string; vid?: string | number; t?: string; kw?: string }, signal?: AbortSignal) =>
    get<DetailResult>("/api/detail", params, signal),
  hot: (kind: string, offset: number, limit: number, signal?: AbortSignal) =>
    get<HotResult>("/api/hot", { kind, offset, limit }, signal),
  refresh: (signal?: AbortSignal) => get<RefreshResult>("/api/refresh", {}, signal),
  health: (kw = "电影", signal?: AbortSignal) => get<HealthResult>("/api/health", { kw }, signal),
  challenge: () => request<Challenge>("/api/human/challenge", { method: "POST" }),
  verify: (body: { id: string; pct: number; ms: number; samples: number; keys: number }) =>
    request<{ ok: boolean; hours: number }>("/api/human/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

export interface ClickEvent {
  kind?: string;
  url?: string;
  kw?: string;
  title?: string;
  src?: string;
  src_name?: string;
  vid?: string | number;
  line?: string;
  ep?: string;
  place?: string;
}

/** 观看/详情埋点：发了就当没发，绝不能因为统计把界面卡住。
 *  sendBeacon 在页面已经跳走时也能送达，所以优先它；没有再退到 keepalive。 */
export function sendClick(ev: ClickEvent): void {
  const body = JSON.stringify(ev);
  try {
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/api/click", new Blob([body], { type: "application/json" }));
      return;
    }
    void fetch("/api/click", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    });
  } catch {
    /* 统计丢了就丢了 */
  }
}

/** 上游图床大多有防盗链，直接贴 <img src=外链> 一定是裂的；
 *  必须先让服务端 /img 认过这个地址，才走代理。空串表示"就没有海报"。 */
export function posterOf(pic: string | undefined): string {
  if (!pic) return "";
  return /^https?:\/\//i.test(pic) ? `/img?url=${encodeURIComponent(pic)}` : pic;
}

export function stars(n: number | undefined): string {
  const v = Number(n) || 0;
  return v > 0 ? "★".repeat(Math.min(5, Math.round(v))) : "";
}
