import { useEffect, useState } from "react";
import { fetchMap } from "./api";
import { Block, Card, Fold, Link, Num, Table, Txt, dash, filterUrl } from "./ui";
import type { AdminView } from "./types";

type Go = (u: string, replace?: boolean) => void;

/** 「5 行内联滚动」这一档在后台用得最多，收一个名字，别每处各写一个数 */
const R5 = 5;

/** 汇总卡片：进后台第一眼要回答的是"今天有没有人用、用得顺不顺"。
 *  「详情 / 观看点击」那格直接带去明细（换 scope 又换 tab，地址由服务端拼好）。 */
function StatCards({ v, onGo }: { v: AdminView; onGo: Go }) {
  const a = v.agg!;
  const ver = a.by_verified || {};
  const cells: [string, React.ReactNode][] = [
    ["查询次数", a.count],
    ["独立 IP", a.ips],
    ["关键词", a.kws],
    ["零结果", `${a.empty}（${v.pct_empty ?? 0}%）`],
    ["平均可用源", dash(a.avg_ok)],
    ["平均耗时", a.avg_ms === null ? "—" : `${Math.round(a.avg_ms)}ms`],
  ];
  return (
    <Block id="stat" title="汇总">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {cells.map(([k, val]) => (
          <Card key={k} className="py-3">
            <p className="text-[10px] uppercase tracking-wider text-muted">{k}</p>
            <p className="num mt-1 text-lg leading-none text-foreground">{val}</p>
          </Card>
        ))}
      </div>
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
        <span>
          真人验证放行 {ver.yes || 0} · 爬虫豁免 {ver.crawler || 0} · 门禁关着时 {ver.off || 0}
        </span>
        <Link href={v.links!.click_detail} onGo={onGo}>
          详情 {v.cagg?.detail ?? 0} 次 · 观看地址 {v.cagg?.play ?? 0} 次 →
        </Link>
        <span className="num">
          首次 {dash(a.first_ts)} · 最近 {dash(a.last_ts)}
        </span>
      </p>
    </Block>
  );
}

/** 按天：最新一天在最上面 —— "今天有没有人用"要先看见，不是画年报 */
function ByDay({ v, onGo }: { v: AdminView; onGo: Go }) {
  const days = v.agg!.by_day || [];
  const max = Math.max(1, ...days.map((d) => d.n));
  return (
    <Block id="days" title="按天" sub="最新一天在最上面">
      <Card>
        {!days.length ? (
          <p className="text-xs text-muted">还没有查询记录。去首页搜一部剧，这里就会有数据。</p>
        ) : (
          <Fold rows={R5}>
            <Table head={["日期", "次数", "独立 IP", "零结果", ""]}>
              <tbody>
                {days.map((d) => (
                  <tr key={d.day} className="border-b border-separator/70 last:border-0">
                    <Txt>
                      <Link href={filterUrl({ day_from: d.day, day_to: d.day, day: "" }, "detail")} onGo={onGo}>
                        {d.day}
                      </Link>
                    </Txt>
                    <Num zero={!d.n}>{d.n}</Num>
                    <Num>{d.ips}</Num>
                    <Num zero={d.empty > 0}>{d.empty}</Num>
                    <td className="w-32 px-2">
                      <span className="block h-1.5 rounded-full bg-accent/70" style={{ width: `${(d.n / max) * 100}%` }} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Fold>
        )}
      </Card>
    </Block>
  );
}

function TopKw({ v, onGo }: { v: AdminView; onGo: Go }) {
  const rows = v.agg!.top_kw || [];
  return (
    <Block id="top-kw" title="热门关键词">
      <Card>
        {!rows.length ? <p className="text-xs text-muted">无</p> : (
          <Fold rows={R5}>
            <Table head={["关键词", "次数", "IP", "平均结果"]}>
              <tbody>
                {rows.map((k) => (
                  <tr key={k.kw} className="border-b border-separator/70 last:border-0">
                    <Txt>
                      <Link href={filterUrl({ kw: k.kw }, "detail")} onGo={onGo}>{k.kw}</Link>
                    </Txt>
                    <Num>{k.n}</Num>
                    <Num>{k.ips}</Num>
                    <Num>{(k.avg_results ?? 0).toFixed(1)}</Num>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Fold>
        )}
      </Card>
    </Block>
  );
}

function TopIp({ v, onGo }: { v: AdminView; onGo: Go }) {
  const rows = v.agg!.top_ip || [];
  return (
    <Block id="top-ip" title="活跃 IP">
      <Card>
        {!rows.length ? <p className="text-xs text-muted">无</p> : (
          <Fold rows={R5}>
            <Table head={["IP", "次数", "关键词", "首 / 末次"]}>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.ip} className="border-b border-separator/70 last:border-0">
                    <Txt mono>
                      <Link href={filterUrl({ ip: r.ip }, "detail")} onGo={onGo}>{r.ip}</Link>
                    </Txt>
                    <Num>{r.n}</Num>
                    <Num>{r.kws}</Num>
                    <Txt dim mono>{`${r.first_day} ~ ${r.last_day}`}</Txt>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Fold>
        )}
      </Card>
    </Block>
  );
}

function Agents({ v, onGo }: { v: AdminView; onGo: Go }) {
  const rows = v.agg!.by_browser || [];
  return (
    <Block id="agents" title="浏览器 / 设备">
      <Card>
        {!rows.length ? <p className="text-xs text-muted">无</p> : (
          <Fold rows={R5}>
            <Table head={["浏览器", "系统", "设备", "次数", "IP"]}>
              <tbody>
                {rows.map((b) => (
                  <tr key={`${b.browser}-${b.os}-${b.device}`} className="border-b border-separator/70 last:border-0">
                    <Txt>
                      <Link href={filterUrl({ browser: b.browser }, "detail")} onGo={onGo}>{b.browser}</Link>
                      {b.bots ? <span className="ml-1 text-[10px] text-muted">含程序 {b.bots}</span> : null}
                    </Txt>
                    <Txt dim>{dash(b.os)}</Txt>
                    <Txt>
                      {b.device ? <Link href={filterUrl({ device: b.device }, "detail")} onGo={onGo}>{b.device}</Link> : "—"}
                    </Txt>
                    <Num>{b.n}</Num>
                    <Num>{b.ips}</Num>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Fold>
        )}
      </Card>
    </Block>
  );
}

function Refs({ v }: { v: AdminView }) {
  const rows = v.agg!.by_ref_src || [];
  return (
    <Block id="refs" title="来源页">
      <Card>
        {!rows.length ? <p className="text-xs text-muted">无</p> : (
          <Fold rows={R5}>
            <Table head={["来源", "类型", "次数", "IP", "最近"]}>
              <tbody>
                {rows.map((f) => (
                  <tr key={`${f.kind}-${f.label}`} className="border-b border-separator/70 last:border-0">
                    <Txt title={f.label}>{f.label}</Txt>
                    <Txt dim>{v.labels.ref_kind[f.kind] || f.kind}</Txt>
                    <Num>{f.n}</Num>
                    <Num>{f.ips}</Num>
                    <Txt dim mono>{f.last_day}</Txt>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Fold>
        )}
      </Card>
    </Block>
  );
}

/** 归属地地图：**服务端算好投影的一棵静态 SVG**，没有 canvas、没有绘制脚本 ——
 *  viewBox 360×180 等距圆柱，x/y/r 全来自 markers。
 *  底图那串路径与筛选无关，单独走 /api/admin/map 让浏览器缓存住：
 *  跟着 view 每次重传就是几百 KB，筛一次等一次。 */
function GeoMap({ v, onGo }: { v: AdminView; onGo: Go }) {
  const [base, setBase] = useState<{ d: string; by_iso: Record<string, string>; error: string | null } | null>(null);
  useEffect(() => {
    let alive = true;
    fetchMap()
      .then((m) => { if (alive) setBase(m); })
      .catch(() => { if (alive) setBase({ d: "", by_iso: {}, error: "底图取不出来" }); });
    return () => { alive = false; };
  }, []);
  const geo = v.geo;
  const markers = v.markers || [];

  return (
    <Block id="geo" title="IP 归属地地图" sub={`${markers.length} 个标记点`}>
      <Card>
        {!geo?.ready ? (
          <p className="text-xs leading-relaxed text-muted">
            归属地库还没准备好。跑一次 <code className="num">{v.fetch_cmd}</code> 就有了；
            没有它只是这张图空着，搜索照常。
          </p>
        ) : !base || !base.d ? (
          <p className="text-xs text-muted">{base?.error || "没有底图文件"}</p>
        ) : (
          <svg viewBox="0 0 360 180" className="w-full" role="img" aria-label="IP 归属地世界地图">
            <title>点击圆点或下方表里的国名，就把这一屏筛到这个归属地</title>
            <rect className="map-sea" x="0" y="0" width="360" height="180" />
            <path className="map-land" d={base.d} />
            {v.map_active ? <path className="map-land-on" d={v.map_active} /> : null}
            {[30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330].map((x) => (
              <line key={`v${x}`} className="map-grat" x1={x} y1="0" x2={x} y2="180" />
            ))}
            {[30, 60, 90, 120, 150].map((y) => (
              <line key={`h${y}`} className="map-grat" x1="0" y1={y} x2="360" y2={y} />
            ))}
            {markers.map((m) => (
              <circle
                key={`${m.iso}-${m.x}-${m.y}`}
                className="map-mk"
                cx={m.x}
                cy={m.y}
                r={m.r}
                onClick={() => onGo(filterUrl({ geo: m.iso || "--" }))}
              >
                <title>{`${m.name} · ${m.n} 次 · ${m.ips} 个 IP`}</title>
              </circle>
            ))}
          </svg>
        )}
        {v.offmap?.length ? (
          <p className="mt-2 text-[11px] text-muted">这些没落到图上（底图缺这块区域）：{v.offmap.map((o) => o.name).join("、")}</p>
        ) : null}
        {geo?.error ? <p className="mt-2 text-[11px] text-warning">{geo.error}</p> : null}
        {v.geo_warn ? (
          <p className="mt-2 text-[11px] leading-relaxed text-warning">
            {v.geo_warn}
            <br />
            搜索不受影响；重启服务会再试一次。
          </p>
        ) : null}
      </Card>
      <Card>
        <Fold rows={R5}>
          <Table head={["国家 / 地区", "次数", "IP", "关键词", "最近"]}>
            <tbody>
              {(v.agg!.by_geo || []).map((g) => (
                <tr key={`${g.iso}-${g.country}`} className="border-b border-separator/70 last:border-0">
                  <Txt>
                    {g.iso && g.iso.length === 2 ? (
                      <>
                        <Link href={filterUrl({ geo: g.iso })} onGo={onGo}>{g.country || g.iso}</Link>
                        <span className="ml-1 text-[10px] text-muted">{g.iso}</span>
                      </>
                    ) : (
                      <Link href={filterUrl({ geo: "--" })} onGo={onGo}>内网 / 保留地址</Link>
                    )}
                  </Txt>
                  <Num>{g.n}</Num>
                  <Num>{g.ips}</Num>
                  <Num>{g.kws}</Num>
                  <Txt dim mono>{g.last_day}</Txt>
                </tr>
              ))}
            </tbody>
          </Table>
        </Fold>
      </Card>
    </Block>
  );
}

export function Overview({ v, onGo }: { v: AdminView; onGo: Go }) {
  return (
    <div className="space-y-8">
      <StatCards v={v} onGo={onGo} />
      <ByDay v={v} onGo={onGo} />
      <TopKw v={v} onGo={onGo} />
      <TopIp v={v} onGo={onGo} />
      <Agents v={v} onGo={onGo} />
      <Refs v={v} />
      <GeoMap v={v} onGo={onGo} />
    </div>
  );
}
