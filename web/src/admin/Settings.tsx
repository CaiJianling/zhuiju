import { useState } from "react";
import { Button } from "@heroui/react";
import { postForm } from "./api";
import { Block, Card } from "./ui";
import type { AdminView } from "./types";

/** 「设置」那一节。表单项目由后端从 settings.SPEC 生成（加一项只改 settings.py），
 *  这里照着渲染就行 —— 老模板也是这个意思，别在界面里写死一项。 */
export function Settings({ v }: { v: AdminView }) {
  const [msg, setMsg] = useState<string | null>(v.notice || null);
  const [busy, setBusy] = useState(false);
  const si = v.setinfo!;
  const upd = v.upd!;
  const SRC_CN: Record<string, string> = { env: "环境变量定的", file: `写在 ${si.path} 里`, default: "用的默认值" };

  return (
    <Block id="settings" title="运行设置" sub={`这台机器上的运行设置 · 存在 zhuiju/data/${si.path}，保存即生效，不用重启`}>
      <Card className="space-y-4">
        <p className="text-xs leading-relaxed text-muted">
          判断「今天该不该更新」看的是<b className="text-foreground">逻辑日</b>：每天 {String(si.hour).padStart(2, "0")}:00
          那道线之后算新的一天。下一道线 {si.roll}，当前逻辑日 {si.logical_day}，
          {si.due ? <span className="text-warning">所以现在差一轮更新</span> : <span className="text-success">所以现在不缺更新</span>}。
          <span className="text-muted">（{si.spec.hint || ""}）</span>
        </p>
        {v.settings_err ? (
          <p className="rounded-lg bg-danger/10 px-3 py-2 text-xs text-danger">
            有认不出来的取值，那一项一条都没写 —— 其余合法的已经存下了。
          </p>
        ) : null}
        {msg ? <p className="rounded-lg bg-accent/10 px-3 py-2 text-[11px] text-foreground">{msg}</p> : null}

        <form
          className="space-y-4"
          onSubmit={async (e) => {
            e.preventDefault();
            if (busy) return;
            setBusy(true);
            const data: Record<string, string> = {};
            (v.setfields || []).forEach((f) => {
              const el = e.currentTarget.elements.namedItem(f.key) as HTMLInputElement | HTMLSelectElement | null;
              if (el) data[f.key] = el.value;
            });
            try {
              const r = await postForm("/admin/settings", data, v.csrf);
              setMsg(r.ok ? r.msg || "已保存" : r.error || "没保存");
            } catch (err) {
              setMsg(`没保存：${(err as Error).message}`);
            } finally {
              setBusy(false);
            }
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            {(v.setfields || []).map((f) => {
              const src = (v.setsrc || {})[f.key];
              return (
                <div key={f.key} className="space-y-1">
                  <label className="block text-xs text-foreground" htmlFor={`st-${f.key}`}>
                    {f.spec.label}
                    <span className="ml-1 text-[10px] text-muted">{src === "env" ? `（被环境变量 ${f.spec.env} 顶着，改这里不生效）` : `（${SRC_CN[src] || src}）`}</span>
                  </label>
                  {f.spec.kind === "bool" ? (
                    <select id={`st-${f.key}`} name={f.key}
                            defaultValue={typeof f.value === "boolean" ? (f.value ? "1" : "0") : String(f.value)}
                            className="h-9 w-full rounded-lg bg-field-background px-2 text-xs text-foreground outline-none ring-1 ring-border">
                      <option value="1">开</option>
                      <option value="0">关</option>
                    </select>
                  ) : (
                    <input id={`st-${f.key}`} name={f.key} type="number" min={f.spec.min} max={f.spec.max} step={1}
                           defaultValue={String(f.value)}
                           className="num h-9 w-full rounded-lg bg-field-background px-2 text-xs text-foreground outline-none ring-1 ring-border" />
                  )}
                  {f.spec.hint && f.spec.kind !== "bool" ? <p className="text-[10px] leading-snug text-muted">{f.spec.hint}</p> : null}
                </div>
              );
            })}
          </div>
          <Button type="submit" size="sm" className="rounded-full" isPending={busy}>
            保存
          </Button>
        </form>

        <div className="space-y-1 border-t border-separator pt-3 text-[11px] leading-relaxed text-muted">
          <p>
            更新进程用的解释器：<span className="num text-foreground">{upd.python}</span>（{upd.python_why}）
          </p>
          <p>最近一次访问触发：{upd.last_trigger || "还没访问触发过"}</p>
          {upd.retry_in ? (
            <p className="text-warning">
              上一轮失败，约 {Math.floor((upd.retry_in + 59) / 60)} 分钟后才会再自动重试（{upd.retry_minutes} 分钟冷却，
              改完环境可跑 <span className="num">{upd.retry_cmd}</span> 立刻重试）
            </p>
          ) : null}
        </div>
      </Card>
    </Block>
  );
}
