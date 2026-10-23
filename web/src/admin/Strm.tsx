import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@heroui/react";
import { postForm } from "./api";
import { Block, Card, Fold, Num, Table, Txt, dash } from "./ui";
import type { AdminView, StrmJob, StrmSpecRow } from "./types";

/** 本轮停下来的原因（游标表里那个 stop）。文案与老模板一致，别改字。 */
const STOP_CN: Record<string, string> = {
  cutoff: "已翻到窗口外",
  known: "全是老片，提前收",
  empty: "没有更多页了",
  budget: "预算用完，待续",
  slice: "这批翻满，等换手",
  error: "取不到",
  done: "本轮已收",
  "": "本轮还没开始",
};

const MIN = (s: number | null | undefined) => (s ? Math.floor((s + 59) / 60) : 0);

/** 采集状态那一句。四种情况必须分开说，否则"跑完在等间隔"会被读成"卡住了"。 */
function stateLine(job: StrmJob): React.ReactNode {
  const st = job.state || {};
  const pr = job.progress || {};
  if (job.running) {
    return (
      <>
        <span className="text-accent">正在后台采集</span>
        <span className="ml-2 text-muted">
          {(pr.note || "准备中")} · 本轮已发 {pr.requests || 0} 次请求 · 翻 {pr.pages || 0} 页 · 新增 {pr.rows_new || 0} 条 · 变更 {pr.rows_changed || 0} 条
        </span>
      </>
    );
  }
  if (!job.settings.enabled) {
    return (
      <>
        <span className="text-muted">采集开关是关的</span>
        <span className="ml-2 text-muted">已采的数据、已写出的文件和分卷包都留着，只是访问网站不再拉起采集</span>
      </>
    );
  }
  if (job.next_in) {
    return (
      <>
        <span className="text-warning">这一轮跑完了，在等最小间隔</span>
        <span className="ml-2 text-muted">
          约 {MIN(job.next_in)} 分钟后访问网站会自动接着采（间隔下限 {job.settings.min_interval_minutes} 分钟）
        </span>
      </>
    );
  }
  return (
    <>
      <span className="text-success">现在访问网站就会拉起一轮</span>
      <span className="ml-2 text-muted">
        上次结束 {dash(st.at || null)}
        {st.pages ? ` · 那轮翻了 ${st.pages} 页 / ${st.requests || 0} 次请求` : ""}
      </span>
    </>
  );
}

function Action({ csrf, action, label, extra, ondone }: { csrf: string; action: string; label: string; extra?: Record<string, string>; ondone: (msg: string | null, running?: boolean) => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size="sm"
      variant="tertiary"
      className="rounded-full"
      isPending={busy}
      onPress={async () => {
        setBusy(true);
        try {
          const r = await postForm(action, { ...(extra || {}) }, csrf);
          ondone(r.ok ? r.msg || "已提交" : r.error || "这次没提交上", r.running);
        } catch (e) {
          ondone(`这次没提交上：${(e as Error).message}`);
        } finally {
          setBusy(false);
        }
      }}
    >
      {label}
    </Button>
  );
}

/** STRM 那一节要自己滚数据：采集进程写的进度文件不在 view 里，只能轮 /api/strm/status。
 *  跑着 10 秒一次、空闲 60 秒一次；页面在后台标签里就不问（那是别人在用），
 *  切回来立刻补一次 —— 与老模板那段调度同口径。 */
function useStrmPoll(active: boolean) {
  const [job, setJob] = useState<StrmJob | null>(null);
  const fails = useRef(0);

  const tick = useCallback(async () => {
    if (document.hidden) return;
    try {
      const r = await fetch("/api/strm/status", { credentials: "same-origin", headers: { Accept: "application/json" } });
      const j = (await r.json()) as StrmJob;
      setJob(j);
      fails.current = 0;
      return j.running ? 10000 : 60000;
    } catch {
      fails.current += 1;
      return 20000;   // 失败退避；连败超过 5 次就停表，不给一个挂掉的服务添请求
    }
  }, []);

  useEffect(() => {
    if (!active) return;
    let timer = 0;
    let stop = false;
    const loop = async () => {
      const wait = await tick();
      if (stop) return;
      if (fails.current > 5) return;
      timer = window.setTimeout(loop, wait || 60000);
    };
    loop();
    const onVis = () => { if (!document.hidden) void tick(); };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      stop = true;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [active, tick]);

  return job;
}

function SpecForm({ rows, csrf, ondone }: { rows: StrmSpecRow[]; csrf: string; ondone: (msg: string | null) => void }) {
  const [busy, setBusy] = useState(false);
  const val = (f: StrmSpecRow) => (typeof f.value === "boolean" ? (f.value ? "1" : "0") : String(f.value ?? ""));
  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        if (busy) return;
        setBusy(true);
        const data = new URLSearchParams();
        rows.forEach((f) => {
          const el = e.currentTarget.elements.namedItem(f.key) as HTMLInputElement | HTMLSelectElement | null;
          if (el && !(f.secret && !el.value)) data.set(f.key, el.value);
        });
        try {
          const r = await postForm("/admin/strm/settings", Object.fromEntries(data), csrf);
          ondone(r.ok ? r.msg || "已保存" : r.error || "没保存");
        } catch (err) {
          ondone(`没保存：${(err as Error).message}`);
        } finally {
          setBusy(false);
        }
      }}
    >
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((f) => (
          <div key={f.key} className="space-y-1">
            <label className="block text-[11px] text-muted" htmlFor={`ss-${f.key}`}>
              {f.label}
              {String(f.default) !== String(f.value) ? <span className="num">（默认 {String(f.default)}）</span> : null}
            </label>
            {f.kind === "bool" ? (
              <select id={`ss-${f.key}`} name={f.key} defaultValue={val(f)}
                      className="h-9 w-full rounded-lg bg-field-background px-2 text-xs text-foreground outline-none ring-1 ring-border">
                <option value="1">开</option>
                <option value="0">关</option>
              </select>
            ) : f.secret ? (
              <input id={`ss-${f.key}`} name={f.key} type="password" value="" autoComplete="off"
                     placeholder={f.filled ? "已经存着了，留空=不改" : "还没配，留空就不查"}
                     className="h-9 w-full rounded-lg bg-field-background px-2 text-xs text-foreground outline-none ring-1 ring-border" />
            ) : (
              <input id={`ss-${f.key}`} name={f.key} type={f.kind === "int" ? "number" : "text"}
                     min={f.kind === "int" ? f.lo : undefined} max={f.kind === "int" ? f.hi : undefined}
                     defaultValue={val(f)}
                     placeholder={f.kind === "int" ? undefined : "huya,suoni"}
                     className="num h-9 w-full rounded-lg bg-field-background px-2 text-xs text-foreground outline-none ring-1 ring-border" />
            )}
            {f.help ? <p className="text-[10px] leading-snug text-muted/80">{f.help}</p> : null}
          </div>
        ))}
      </div>
      <Button type="submit" size="sm" className="rounded-full" isPending={busy}>
        保存设置
      </Button>
    </form>
  );
}

export function StrmTab({ v }: { v: AdminView }) {
  const live = useStrmPoll(true);
  const job = live || v.sjob!;
  const meta = v.smeta!;
  const [msg, setMsg] = useState<string | null>(v.smsg || null);
  const counts = job.counts || meta.counts;
  const kb = (b: number | null) => (b ? (b % 1024 === 0 ? `${b / 1024} KB` : `${Math.round(b / 1024)} KB`) : "—");

  return (
    <div className="space-y-8">
      <Block id="strm" title="采集与状态" sub="近一年电影 / 电视剧采集 → strm 目录树 → 分卷 zip">
        <Card className="space-y-3">
          <p className="text-xs">{stateLine(job)}</p>
          {msg ? <p className="rounded-lg bg-accent/10 px-2.5 py-1.5 text-[11px] text-foreground">{msg}</p> : null}
          <div className="flex flex-wrap items-center gap-2">
            <Action csrf={v.csrf} action="/admin/strm/run" label={`立刻采一轮（${job.settings.budget_seconds} 秒预算）`} ondone={setMsg} />
            <Action csrf={v.csrf} action="/admin/strm/export" label="现在合并导出 + 打包" ondone={setMsg} />
            <Action csrf={v.csrf} action="/admin/strm/export" label="全量重建（改了窗口就按这个）" extra={{ mode: "full" }} ondone={setMsg} />
            <Action csrf={v.csrf} action="/admin/strm/recheck" label="重查 TMDB 说『没有』的那些" ondone={setMsg} />
          </div>
          <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4 lg:grid-cols-8">
            {[
              ["源", counts.sources], ["条目", counts.vods], ["部", counts.titles],
              ["电影", counts.movies], ["剧集", counts.shows], ["可播地址", counts.urls],
              ["已写 strm", counts.files], ["待合并", counts.dirty],
            ].map(([k, val]) => (
              <div key={String(k)}>
                <p className="text-[10px] text-muted">{k}</p>
                <p className="num text-sm text-foreground">{String(val)}</p>
              </div>
            ))}
          </div>
          <p className="text-[11px] text-muted">
            窗口 {meta.window_days} 天 · 自 {meta.since} · TMDB 结论：{job.lines?.ids || "—"} · NFO：{job.lines?.nfo || "—"}
          </p>
          <details className="text-[11px] text-muted">
            <summary className="cursor-pointer">跑的是哪条命令、日志在哪儿</summary>
            <p className="num mt-2 break-all">{job.run_cmd}</p>
            <p className="num mt-1 break-all">{job.check_cmd}</p>
            <p className="num mt-1 break-all">日志 {job.log} · 解释器 {job.python || "—"}</p>
          </details>
        </Card>
      </Block>

      <Block id="strm-zips" title="分卷包" sub="movie01、movie02… / tv01、tv02…，一卷一个 zip">
        {["movie", "tv"].map((kind) => {
          const kv = meta.kinds?.[kind];
          return (
            <Card key={kind} className="mb-3">
              <h3 className="text-xs font-semibold text-foreground">{kv?.label || kind}</h3>
              {!(kv?.parts || []).length ? (
                <p className="mt-2 text-[11px] text-muted">{kv?.label || kind}还没有分卷：先跑一轮采集，攒够条目才会打包。</p>
              ) : (
                <div className="mt-2">
                  <Fold rows={6}>
                    <Table dense head={["卷", "部", "文件", "包", ""]} >
                      <tbody>
                        {kv!.parts.map((p) => (
                          <tr key={p.name} className="border-b border-separator/70 last:border-0">
                            <Txt mono>{p.name}</Txt>
                            <Num>{p.titles}</Num>
                            <Num>{p.files}</Num>
                            <Num>{kb(p.zip_bytes)}</Num>
                            <td className="px-2 py-1 text-[11px]">
                              {p.zip_url ? (
                                <>
                                  <a className="text-accent underline" href={p.zip_url} target="_blank" rel="noopener noreferrer">下载 {p.zip}</a>
                                  {" · "}
                                  <a className="text-accent underline" href={p.index_url || "#"} target="_blank" rel="noreferrer">看条目</a>
                                  {" · "}
                                  <a className="text-accent underline" href={p.tree_url || "#"} target="_blank" rel="noreferrer">文件清单</a>
                                </>
                              ) : (
                                <span className="text-muted">还没打包</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  </Fold>
                </div>
              )}
            </Card>
          );
        })}
      </Block>

      <Block id="strm-src" title="各源采集进度" sub="游标在 strm.db 的 cur 表里，跨天续采">
        <Card>
          {(meta.cursor || []).length ? (
            <Fold rows={6}>
              <Table dense head={["源", "下一跳页码", "本轮状态", "已翻页数", "翻到的最新更新时间"]}>
                <tbody>
                  {meta.cursor.map((c) => (
                    <tr key={c.src} className="border-b border-separator/70 last:border-0">
                      <Txt mono>{c.src}</Txt>
                      <Num>{c.pg}</Num>
                      <Txt dim>{STOP_CN[c.stop ?? ""] ?? (c.stop || "待续")}</Txt>
                      <Num>{c.requests}</Num>
                      <Txt dim mono>{dash(c.last_time)}</Txt>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Fold>
          ) : (
            <p className="text-xs text-muted">
              还没采过：一轮都没跑起来，游标是空的。
              <span className="ml-1">点开一轮采集（或访问一次首页）这里就会动起来。</span>
            </p>
          )}
        </Card>
        <Card className="mt-3">
          <h3 className="text-xs font-semibold text-foreground">覆盖度</h3>
          {(meta.sources || []).length ? (
            <div className="mt-2">
              <Fold rows={5}>
                <Table dense head={["源", "条目", "部", "可播地址"]}>
                  <tbody>
                    {meta.sources.map((s) => (
                      <tr key={s.id} className="border-b border-separator/70 last:border-0">
                        <Txt>{s.name}<span className="ml-1 text-[10px] text-muted">{s.id}</span></Txt>
                        <Num>{s.vods}</Num>
                        <Num>{s.titles}</Num>
                        <Num>{s.m3u8_urls}</Num>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Fold>
            </div>
          ) : (
            <p className="mt-2 text-xs text-muted">库里还没有任何源的条目。</p>
          )}
        </Card>
        <Card className="mt-3 space-y-3">
          <h3 className="text-xs font-semibold text-foreground">采集设置</h3>
          <p className="text-[11px] text-muted">存在 strm.db 里，保存即生效、不用重启</p>
          <SpecForm rows={v.sspec || []} csrf={v.csrf} ondone={setMsg} />
        </Card>
      </Block>
      <p className="text-[11px] text-muted">
        上一轮各源停在哪：{job.state?.note || "没有"} · 采集脚本 {job.script || "tools/collect_strm.py"} · 最近触发 {dash(job.last_trigger)}
      </p>
    </div>
  );
}
