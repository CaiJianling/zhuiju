import { useRef, useState } from "react";
import { Button, Input, Label, TextField } from "@heroui/react";
import { postForm } from "./api";
import type { AdminView } from "./types";
import { ThemeToggle } from "../components/ThemeToggle";

/** 登录那一屏。口令只在输入框和那一次 POST 里存在：不打印、不落 localStorage、不进 URL。
 *  失败文案原样用服务端那句（"口令不正确（还可尝试 N 次）"），
 *  因为"还剩几次"是服务端节流器算的，前端自己数会数错。 */
export function Login({ payload, csrf, onok }: { payload: AdminView; csrf: string; onok: () => void }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(payload.error ?? null);
  const [busy, setBusy] = useState(false);
  // 连击要用 ref 挡：setBusy 是异步的，同一次点击里第二次进来时 state 还是旧的
  const busyRef = useRef(false);

  async function submit() {
    if (!pw || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setErr(null);
    try {
      const r = await postForm("/admin/login", { password: pw }, csrf);
      if (r.ok) {
        if (r.redirect) location.href = r.redirect;
        else onok();
        return;
      }
      setErr(r.error || "口令不对");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      busyRef.current = false;
      setBusy(false);
      // 口令是一次性的：失败也清空，免得留一个能被人翻出来的值
      setPw("");
    }
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-[440px] flex-col justify-center px-4">
      <form
        className="space-y-4 rounded-3xl bg-surface p-6 text-surface-foreground shadow-surface ring-1 ring-border"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        autoComplete="off"
      >
        <div className="flex items-start justify-between gap-3">
          <h1 className="text-base font-semibold">后台统计</h1>
          <ThemeToggle />
        </div>
        <p className="text-xs leading-relaxed text-muted">
          这一页只统计本机这台服务上的查询与点击。需要口令才能进来。
        </p>
        {payload.temp ? (
          <p className="rounded-xl bg-warning/15 px-3 py-2 text-xs leading-relaxed text-warning">
            当前口令是首次启动自动生成的随机串。登录成功后会直接领你去改掉 ——
            它写在 <code className="num">zhuiju/data/admin.json</code> 里，忘了也能再去翻。
          </p>
        ) : null}
        <TextField className="w-full" type="password" name="password" autoComplete="current-password">
          <Label>后台口令</Label>
          <Input
            value={pw}
            onChange={(e) => setPw(e.currentTarget.value)}
            autoFocus
            required
            placeholder="口令"
            aria-invalid={err ? "true" : undefined}
          />
        </TextField>
        {err ? <p className="text-xs text-danger">{err}</p> : null}
        {/* type=submit 的按钮不要再挂 onPress：挂了两边各跑一次，
            同一次点击会发两个 POST —— 改口令那种"第二次已经用不上第一次的旧口令"的场景，
            现象就是明明改成功了却回一句"当前口令不对" */}
        <Button type="submit" className="w-full rounded-full" isPending={busy}>
          进入
        </Button>
        <p className="text-[11px] leading-relaxed text-muted">
          连续输错多次会被节流（同一来源冷却），这是为了让脚本猜不动口令。
          {payload.env_lock ? " 现在口令由环境变量 ZHUIJU_ADMIN_PASSWORD 指定，改文件不会生效。" : ""}
        </p>
      </form>
    </main>
  );
}

/** 改口令：三个框都是口令，同样一次都不落地。
 *  "先不改，进统计页"那条出口必须留着 —— 环境变量顶着口令时，改文件本来就不生效，
 *  不给人走开就等于把人关在门外。 */
export function Password({ view, first, envLock, minLen, ondone }: { view: AdminView | null; first: boolean; envLock: boolean; minLen: number; ondone: (to: string) => void }) {
  const [cur, setCur] = useState("");
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);

  async function submit() {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setErr(null);
    try {
      const r = await postForm("/admin/password", { current: cur, password: a, password2: b, first: first ? 1 : 0 }, view?.csrf || "");
      if (r.ok) {
        setMsg(r.msg || "已保存");
        setCur("");
        setA("");
        setB("");
        if (r.redirect) window.setTimeout(() => ondone(r.redirect as string), 900);
        return;
      }
      setErr(r.error || "没保存");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  const field = (label: string, value: string, set: (v: string) => void, min = 0) => (
    <TextField className="w-full" type="password" autoComplete="off">
      <Label>{label}</Label>
      <Input value={value} onChange={(e) => set(e.currentTarget.value)} minLength={min || undefined} required />
    </TextField>
  );

  return (
    <main className="mx-auto flex min-h-dvh max-w-[480px] flex-col justify-center px-4">
      <form
        className="space-y-4 rounded-3xl bg-surface p-6 text-surface-foreground shadow-surface ring-1 ring-border"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="flex items-start justify-between gap-3">
          <h1 className="text-base font-semibold">{first ? "先设置一个你自己知道的口令" : "修改后台口令"}</h1>
          <ThemeToggle />
        </div>
        <p className="text-xs leading-relaxed text-muted">
          新口令会直接写进 zhuiju/data/admin.json 的 password 字段，保存即生效，不用重启服务。
        </p>
        {envLock ? (
          <p className="rounded-xl bg-warning/15 px-3 py-2 text-xs leading-relaxed text-warning">
            现在口令由环境变量 ZHUIJU_ADMIN_PASSWORD 指定，改文件不会生效；要改用文件里的口令，
            请先去掉这个环境变量并重启服务。
          </p>
        ) : null}
        {field("当前口令", cur, setCur)}
        {field(`新口令（至少 ${minLen} 个字符）`, a, setA, minLen)}
        {field("再输一遍新口令", b, setB, minLen)}
        {err ? <p className="text-xs text-danger">{err}</p> : null}
        {msg ? <p className="text-xs text-success">{msg}</p> : null}
        <div className="flex items-center gap-3">
          <Button type="submit" className="rounded-full" isPending={busy}>
            保存
          </Button>
          <button type="button" className="text-xs text-muted underline" onClick={() => ondone("/admin")}>
            先不改，进统计页
          </button>
        </div>
        <p className="text-[11px] leading-relaxed text-muted">
          忘了当前口令：直接看 zhuiju/data/admin.json 里的 password。
          同文件里的 secret_key 那行不要动 —— 动了会让已登录的会话和门禁 cookie 全部失效。
        </p>
      </form>
    </main>
  );
}
