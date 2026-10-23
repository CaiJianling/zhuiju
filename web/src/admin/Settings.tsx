import { useState } from "react";
import { Button, Switch } from "@heroui/react";
import { postForm } from "./api";
import { Block, Card, isOn } from "./ui";
import type { AdminView } from "./types";

/** 「设置」那一节。表单项目由后端从 settings.SPEC 生成（加一项只改 settings.py），
 *  这里照着渲染就行。布尔项是 Switch，不是 <select>：开关只有一个问题要问
 *  （"要不要"），下拉框把它读成"两个选项里的一个"，手机上还要多点一次。
 *  开关的值存在 state 里、提交时按 state 写，不去捞 React Aria 那颗隐藏 input。 */
export function Settings({ v }: { v: AdminView }) {
  const [msg, setMsg] = useState<string | null>(v.notice || null);
  const [busy, setBusy] = useState(false);
  const fields = v.setfields || [];
  const [bools, setBool] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(fields.filter((f) => f.spec.kind === "bool").map((f) => [f.key, isOn(f.value)])));
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
            fields.forEach((f) => {
              if (f.spec.kind === "bool") {
                data[f.key] = bools[f.key] ? "1" : "0";
                return;
              }
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
            {fields.map((f) => {
              const src = (v.setsrc || {})[f.key];
              const note = src === "env" ? `（被环境变量 ${f.spec.env} 顶着，改这里不生效）` : `（${SRC_CN[src] || src}）`;
              return (
                <div key={f.key} className="space-y-1">
                  {f.spec.kind === "bool" ? (
                    <>
                      <p className="block text-xs text-foreground">
                        {f.spec.label}
                        <span className="ml-1 text-[10px] text-muted">{note}</span>
                      </p>
                      <Switch
                        size="sm"
                        isSelected={!!bools[f.key]}
                        onChange={(on) => setBool((b) => ({ ...b, [f.key]: on }))}
                        aria-label={f.spec.label}
                        className={src === "env" ? "opacity-60" : ""}
                      >
                        <Switch.Content>
                          <Switch.Control>
                            <Switch.Thumb />
                          </Switch.Control>
                          <span className="num text-[11px]">{bools[f.key] ? "开" : "关"}</span>
                        </Switch.Content>
                      </Switch>
                    </>
                  ) : (
                    <>
                      <label className="block text-xs text-foreground" htmlFor={`st-${f.key}`}>
                        {f.spec.label}
                        <span className="ml-1 text-[10px] text-muted">{note}</span>
                      </label>
                      <input id={`st-${f.key}`} name={f.key} type="number" min={f.spec.min} max={f.spec.max} step={1}
                             defaultValue={String(f.value)}
                             className="num h-9 w-full rounded-lg bg-field-background px-2 text-xs text-foreground outline-none ring-1 ring-border" />
                      {f.spec.hint ? <p className="text-[10px] leading-snug text-muted">{f.spec.hint}</p> : null}
                    </>
                  )}
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
