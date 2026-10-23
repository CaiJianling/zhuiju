import { useEffect, useRef, useState } from "react";
import { Button, Drawer, Skeleton, useMediaQuery } from "@heroui/react";
import { api, sendClick } from "../api";
import type { DetailResult } from "../types";
import { PosterImage, type DetailSpec } from "./Poster";

/** 详情按 src+vid 缓一页：同一部片来回看不该反复打上游；缓存只在内存里，
 *  这一页活着有效，刷新就重新查（上游本来也在变）。 */
const cache = new Map<string, DetailResult>();

function dkey(src: string, vid: string | number, title: string) {
  return `${src}:${vid}:${title}`;
}

const cut = (v: string | undefined, n: number) => {
  const t = String(v || "");
  return t.length > n ? `${t.slice(0, n)}…` : t;
};

export function DetailDrawer({ spec, onClose }: { spec: DetailSpec | null; onClose: () => void }) {
  const wide = useMediaQuery("(min-width: 1024px)");
  // vid 从接口来是数字、从 data-* 读回来是字符串，比的时候两边都当字符串，否则选中态永远点不亮
  const [pick, setPick] = useState<{ src: string; vid: string }>({ src: "", vid: "" });
  const [data, setData] = useState<DetailResult | null>(null);
  const [error, setError] = useState("");
  const [fromCache, setFromCache] = useState(false);
  const [loading, setLoading] = useState(false);
  const [nonce, setNonce] = useState(0);
  const token = useRef(0);

  useEffect(() => {
    if (!spec) return;
    setPick({ src: spec.src || "", vid: String(spec.vid ?? "") });
  }, [spec?.title, spec?.src, spec?.vid]);

  const src = pick.src;
  const vid = pick.vid;
  const key = spec ? dkey(src, vid, spec.title) : "";

  useEffect(() => {
    if (!spec || !key) return;
    const mine = ++token.current;
    setError("");
    const hit = cache.get(key);
    if (hit) {
      setFromCache(true);
      setData(hit);
      setLoading(false);
      return;
    }
    setFromCache(false);
    setData(null);
    setLoading(true);
    const params = src && vid ? { src, vid, t: spec.title } : { kw: spec.title };
    api
      .detail(params)
      .then((d) => {
        if (mine !== token.current) return; // 已经切到别的源/别的片，这次结果不许再回填
        cache.set(key, d);
        setData(d);
        setError(d.ok === false ? d.error || "没取到详情" : "");
      })
      .catch((e) => {
        if (mine !== token.current) return;
        setError((e as Error).message || "没取到详情");
      })
      .finally(() => {
        if (mine === token.current) setLoading(false);
      });
  }, [key, nonce, spec, src, vid]);

  const sources = spec?.sources ?? [];
  const open = !!spec;
  const d = data;

  const rows: [string, string][] = d
    ? ([
        ["导演", cut(d.director, 40)],
        ["主演", cut(d.actor || spec?.actor, 64)],
        ["年份", d.year || spec?.year || ""],
        ["地区", d.area || spec?.area || ""],
        ["类型", d.type || spec?.type || ""],
        ["更新", d.notes || d.remarks || spec?.remarks || ""],
      ] as [string, string][]).filter((r) => r[1])
    : [];

  return (
    <Drawer>
      <Drawer.Backdrop variant="blur" isOpen={open} onOpenChange={(v) => !v && onClose()}>
        <Drawer.Content placement={wide ? "right" : "bottom"}>
          <Drawer.Dialog>
            <Drawer.Header className="flex-row items-center gap-2">
              {/* 返回在原海报那一侧：点开是从那儿长出来的，缩回去也按同一条路，
                  右上角那颗 CloseTrigger 留着（键盘 ESC 与鼠标习惯的人都找得到它） */}
              <button
                type="button"
                onClick={onClose}
                aria-label="返回海报列表"
                className="-ml-1 inline-flex h-8 shrink-0 items-center gap-1 rounded-full px-2 text-xs text-muted transition hover:bg-default hover:text-foreground"
              >
                <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                  <path d="M15 5l-7 7 7 7" />
                </svg>
                返回
              </button>
              <Drawer.Heading className="min-w-0 truncate">{spec?.title || "详情"}</Drawer.Heading>
              <Drawer.CloseTrigger aria-label="关闭详情" />
            </Drawer.Header>
            <Drawer.Body className="space-y-4">
              {spec ? (
                <>
                  <div className="flex gap-3">
                  {/* vt-hero：这一格带着 view-transition-name: cover-active（见 styles.css），
                      它就是海报"长过来"要落到的那个矩形 */}
                  <div className="vt-hero relative aspect-2/3 w-24 shrink-0 self-start overflow-hidden rounded-xl bg-default ring-1 ring-border">
                    <PosterImage pic={spec.pic} title={spec.title} />
                  </div>
                    <div className="min-w-0 space-y-1.5 text-xs">
                      <div className="flex flex-wrap gap-1.5">
                        {[spec.type, spec.year, spec.area, spec.remarks]
                          .filter(Boolean)
                          .map((t) => (
                            <span key={t} className="rounded-full bg-default px-2 py-0.5 text-muted">
                              {t}
                            </span>
                          ))}
                      </div>
                      {spec.n && spec.n > 1 ? <p className="text-muted">覆盖 {spec.n} 个采集源</p> : null}
                      {sources.length ? (
                        <div className="flex flex-wrap items-center gap-1.5 pt-1">
                          <span className="text-muted">{sources.length > 1 ? "换源看" : "来源"}</span>
                          {sources.map((x) => {
                            const on = String(x.id) === String(src) && String(x.vid) === String(vid);
                            return (
                              <Button
                                key={`${x.id}-${x.vid}`}
                                size="sm"
                                variant={on ? "primary" : "tertiary"}
                                className="rounded-full"
                                onPress={() => setPick({ src: x.id, vid: String(x.vid) })}
                              >
                                {x.name || x.id}
                              </Button>
                            );
                          })}
                        </div>
                      ) : null}
                    </div>
                  </div>

                  {loading ? (
                    <div className="space-y-2">
                      <Skeleton className="h-3 w-2/5 rounded" />
                      <Skeleton className="h-3 w-3/5 rounded" />
                      <Skeleton className="h-16 w-full rounded-lg" />
                      <p className="text-xs text-muted">
                        {src && vid
                          ? "正在读取这部片的详情…"
                          : "这条没留影片 ID，正在按片名把各检索源都打一遍再取详情，会慢几秒…"}
                      </p>
                    </div>
                  ) : error ? (
                    <p className="text-xs text-danger">
                      {error}{" "}
                      <Button
                        size="sm"
                        variant="ghost"
                        className="rounded-full"
                        onPress={() => {
                          cache.delete(key);
                          setNonce((n) => n + 1);
                        }}
                      >
                        重试
                      </Button>
                    </p>
                  ) : d ? (
                    <>
                      <p className="text-xs text-muted">
                        {fromCache ? "这一条本页已经查过，直接用缓存，不再请求。" : ""}
                      </p>
                      {rows.length ? (
                        <dl className="grid grid-cols-[4em_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-xs">
                          {rows.map(([k, v]) => (
                            <div key={k} className="contents">
                              <dt className="text-muted">{k}</dt>
                              <dd className="min-w-0 break-words text-foreground">{v}</dd>
                            </div>
                          ))}
                        </dl>
                      ) : null}
                      {d.blurb ? (
                        <p className="max-h-28 overflow-auto text-xs leading-relaxed text-muted">{d.blurb}</p>
                      ) : null}

                      <div className="space-y-2">
                        <p className="text-xs font-medium text-foreground">
                          观看地址 <span className="font-normal text-muted">· {d.lines.length} 条线路，点开看分集</span>
                        </p>
                        {d.lines.length ? (
                          <div className="space-y-1.5">
                            {d.lines.map((ln) => (
                              <Line key={ln.from} line={ln} spec={spec} d={d} src={src} />
                            ))}
                          </div>
                        ) : (
                          <p className="text-xs text-muted">{d.error || "该源没有返回可播放的线路"}</p>
                        )}
                      </div>

                      <p className="border-t border-separator pt-3 text-[11px] leading-relaxed text-muted">
                        以上信息来自 {d.source_name || "该源"}
                        {d.via === "kw" ? "（按片名定位到的）" : "（按影片 ID 直取）"}，第三方接口随时可能失效。{" "}
                        <a className="text-accent underline" href={`/s/${encodeURIComponent(spec.title)}`}>
                          按这个片名搜一遍
                        </a>
                      </p>
                    </>
                  ) : null}
                </>
              ) : null}
            </Drawer.Body>
          </Drawer.Dialog>
        </Drawer.Content>
      </Drawer.Backdrop>
    </Drawer>
  );
}

/** 一条线路。集数多的剧一次铺上百个 <a> 会把面板撑成长条、绝大多数没人点，
 *  所以默认只列线路名，展开时才铺（每线路截 120 集）。 */
function Line({ line, spec, d, src }: { line: { from: string; episodes: { name: string; url: string }[] }; spec: DetailSpec; d: DetailResult; src: string }) {
  const [open, setOpen] = useState(false);
  const eps = line.episodes || [];
  return (
    <div className="rounded-xl bg-surface-secondary/60 ring-1 ring-border">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-xs"
      >
        <span className="min-w-0 truncate text-foreground">
          {line.from} · <span className="num">{eps.length}</span> 条
        </span>
        <span className="shrink-0 text-muted">{open ? "收起" : "展开"}</span>
      </button>
      {open ? (
        eps.length ? (
          <div className="flex flex-wrap gap-1 px-3 pb-3">
            {eps.slice(0, 120).map((ep, i) => (
              <a
                key={`${ep.url}-${i}`}
                href={ep.url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() =>
                  sendClick({
                    kind: "play",
                    url: ep.url,
                    kw: spec.title,
                    title: spec.title,
                    src: src || d.source,
                    src_name: d.source_name,
                    vid: String(spec.vid ?? ""),
                    line: line.from,
                    ep: ep.name || "播放",
                    place: "panel",
                  })
                }
                className="num rounded-md bg-surface px-2 py-1 text-[11px] text-foreground ring-1 ring-border transition hover:bg-accent hover:text-accent-foreground"
              >
                {ep.name || "播放"}
              </a>
            ))}
            {eps.length > 120 ? (
              <span className="self-center text-[11px] text-muted">后面还有 {eps.length - 120} 集，去看完整页</span>
            ) : null}
          </div>
        ) : (
          <p className="px-3 pb-3 text-[11px] text-muted">这条线路没给可播放的地址</p>
        )
      ) : null}
    </div>
  );
}
