import { useEffect, useRef, useState } from "react";
import { Button } from "@heroui/react";
import { Card, filterUrl } from "./ui";
import type { AdminView, Filters as Flt } from "./types";

type Go = (u: string, replace?: boolean) => void;

const OPTS: [keyof Flt, string, [string, string][], string][] = [
  ["ref_kind", "来源类型", [["", "全部"], ["site", "站内上一页"], ["search", "搜索引擎"], ["out", "外部站点"], ["direct", "直接访问/无来源"]], ""],
  ["device", "设备", [["", "全部"], ["桌面", "桌面"], ["手机", "手机"], ["平板", "平板"], ["程序", "程序"]], ""],
  ["who", "真人 / 脚本", [["", "全部"], ["human", "像真人"], ["bot", "脚本/爬虫"], ["unknown", "说不清"]], "按 UA 那一档筛"],
  ["via", "入口", [["", "全部"], ["api", "交互搜索"], ["seo", "落地页快照"], ["cloud", "网盘查询"]], ""],
  ["per", "每页", [["25", "25"], ["50", "50"], ["100", "100"], ["200", "200"]], ""],
];

const TEXTS: [keyof Flt, string, string][] = [
  ["day_from", "起", "date"],
  ["day_to", "止", "date"],
  ["ip", "IP", "text"],
  ["geo", "归属地", "text"],
  ["browser", "浏览器", "text"],
  ["os", "系统", "text"],
  ["kw", "关键词", "text"],
];

/** 那一屏的筛选条件。GET 表单的等价物：填完点「筛选」就是换一个查询字符串，
 *  所以地址栏永远是可分享、可后退的 —— 和老模板一样，不多存一份状态。 */
export function FilterBar({ v, onGo }: { v: AdminView; onGo: Go }) {
  const f = v.flt!;
  const [draft, setDraft] = useState<Record<string, string>>(() => {
    const o: Record<string, string> = {};
    TEXTS.forEach(([k]) => { o[k] = String(f[k] ?? ""); });
    OPTS.forEach(([k]) => { o[k] = String(f[k] ?? ""); });
    return o;
  });
  const form = useRef<HTMLFormElement>(null);

  useEffect(() => {
    // 点翻页/换 tab 之后服务端可能把默认日期填回来（?day=all 被顶掉那种），
    // 条件变了就得让输入框跟着现实，不能抱着旧草稿不放
    TEXTS.forEach(([k]) => setDraft((d) => ({ ...d, [k]: String(f[k] ?? "") })));
    OPTS.forEach(([k]) => setDraft((d) => ({ ...d, [k]: String(f[k] ?? "") })));
  }, [f.day_from, f.day_to, f.ip, f.geo, f.browser, f.os, f.kw, f.per, f.via, f.who, f.device, f.ref_kind]);

  const input = "h-9 rounded-lg bg-field-background px-2 text-xs text-foreground outline-none ring-1 ring-border focus:ring-2 focus:ring-accent";

  return (
    <Card>
      <form
        ref={form}
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const patch: Record<string, string> = {};
          Object.entries(draft).forEach(([k, val]) => { patch[k] = val; });
          patch.page = "1";   // 换了条件还停在第 7 页，看到的多半是空表
          onGo(filterUrl(patch));
        }}
      >
        {TEXTS.map(([k, label, type]) => (
          <label key={k} className="flex flex-col gap-1 text-[10px] text-muted">
            {label}
            <input
              type={type}
              name={k}
              value={draft[k] ?? ""}
              onChange={(e) => setDraft((d) => ({ ...d, [k]: e.target.value }))}
              placeholder={k === "ip" ? "192.168.1.20" : k === "geo" ? "CN / US / --（内网）" : k === "kw" ? "庆余年" : k === "browser" ? "Chrome 124.0" : k === "os" ? "Windows 10/11" : undefined}
              className={`${input} ${type === "date" ? "num w-[9.5rem]" : "w-[8.5rem]"}`}
            />
          </label>
        ))}
        {OPTS.map(([k, label, vals, hint]) => (
          <label key={k} className="flex flex-col gap-1 text-[10px] text-muted" title={hint || undefined}>
            {label}
            <select
              name={k}
              value={draft[k] ?? ""}
              onChange={(e) => setDraft((d) => ({ ...d, [k]: e.target.value }))}
              className={`${input} min-w-[7rem]`}
            >
              {vals.map(([val, text]) => (
                <option key={val} value={val}>{text}</option>
              ))}
            </select>
          </label>
        ))}
        <div className="flex items-center gap-2">
          <Button type="submit" size="sm" className="rounded-full">筛选</Button>
          <Button size="sm" variant="ghost" className="rounded-full"
                  onPress={() => {
                    const clear: Record<string, string> = {};
                    [...TEXTS, ...OPTS].forEach(([k]) => { clear[k] = ""; });
                    clear.page = "1";
                    clear.day = v.day_all ? "all" : "";
                    onGo(filterUrl(clear));
                  }}>
            清空
          </Button>
        </div>
        {v.day_all ? <p className="text-[10px] text-muted">当前是「全部历史」，库里最多留 {v.keep_days} 天</p> : null}
      </form>
    </Card>
  );
}
