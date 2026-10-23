import type { AdminView } from "./types";

/** 后台的取数客户端。两条约定是后端定的，别自己改：
 *  1. POST 一律 `application/x-www-form-urlencoded` —— 那几个处理函数读的是 request.form；
 *  2. 带 `X-Requested-With: fetch`，服务端据此回 JSON 而不是重定向到 HTML
 *     （同一个接口同时服务没 JS 的老表单，见 app.py 的 _wants_json）。 */

export class NeedPassword extends Error {
  constructor(public msg = "需要口令") {
    super(msg);
    this.name = "NeedPassword";
  }
}

export async function fetchView(search: string): Promise<AdminView> {
  const r = await fetch(`/api/admin/view${search}`, {
    credentials: "same-origin",
    headers: { Accept: "application/json", "X-Requested-With": "fetch" },
  });
  // 423 = 门禁 cookie 到点了。这一页是整页数据，没有"只重取这一块"的意义，
  // 直接刷一次让服务端那套（未验证就回 locked 壳 + 滑块）接管，验完自然回到这里。
  if (r.status === 423) {
    location.reload();
    throw new NeedPassword("需要先通过真人验证");
  }
  const data = (await r.json().catch(() => ({}))) as AdminView;

  if (r.status === 401 || data.authed === false) {
    const err = new NeedPassword(data.error || "需要口令");
    (err as NeedPassword & { payload?: AdminView }).payload = data;
    throw err;
  }
  if (!r.ok) throw new Error(data.error || `接口返回 ${r.status}`);
  return data;
}

export async function fetchMap(): Promise<{ d: string; by_iso: Record<string, string>; error: string | null }> {
  const r = await fetch("/api/admin/map", {
    credentials: "same-origin",
    headers: { Accept: "application/json", "X-Requested-With": "fetch" },
  });
  return r.json();
}

export interface FormResult {
  ok?: boolean;
  error?: string | null;
  msg?: string | null;
  redirect?: string;
  running?: boolean;
}

/** 提交一个后台表单。csrf 从头里给（服务端 _csrf_ok 认头，也认表单里的同名字段）。 */
export async function postForm(action: string, fields: Record<string, string | number | boolean | undefined>, csrf: string): Promise<FormResult> {
  const body = new URLSearchParams();
  for (const [k, v] of Object.entries(fields)) {
    if (v !== undefined && v !== null) body.set(k, String(v));
  }
  const r = await fetch(action, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      "X-Requested-With": "fetch",
      Accept: "application/json",
      "X-CSRF-Token": csrf,
    },
    body,
  });
  const data = (await r.json().catch(() => ({}))) as FormResult;
  if (!r.ok && !data.error) return { ok: false, error: `接口返回 ${r.status}` };
  return data;
}

/** 口令只能在这几段话里被"提到"，永远不能被打印或存下来：
 *  登录失败回的是服务端写好的中文句子，直接原样显示，不要自己拼含口令的内容。 */
export function errText(e: unknown): string {
  if (e instanceof NeedPassword) return e.msg;
  return (e as Error)?.message || "网络不通，没取到数据";
}
