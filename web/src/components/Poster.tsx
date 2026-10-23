import { useCallback, useRef, useState } from "react";
import { Button, Skeleton, Spinner } from "@heroui/react";
import { posterOf } from "../api";
import { Flag, Meta } from "./ui";

export interface DetailSpec {
  title: string;
  pic?: string;
  year?: string;
  area?: string;
  type?: string;
  remarks?: string;
  actor?: string;
  director?: string;
  src?: string;
  vid?: string | number;
  n?: number;
  sources?: { id: string; name: string; vid: string | number }[];
  from: "card" | "hot";
}

interface Props {
  title: string;
  pic?: string;
  meta?: (string | number | undefined | false)[];
  flags?: (string | number | undefined | false)[];
  href?: string;
  spec: DetailSpec;
  /** 点海报开详情。from = 那张海报的方框本体：展开时要拿它当"从哪儿长出来"的那个元素
   *  （View Transitions 的共享元素）。浏览器不支持时 from 用不上，抽屉照常滑进来。 */
  onDetail: (spec: DetailSpec, from?: HTMLElement | null) => void;
}

/** 一张海报图片本体（父元素负责定位与形状）。列表卡与详情抽屉共用这一份，
 *  两处才长得不一样、也不会一处改了另一处忘了。
 *
 *  没落地的时候不给一个空黑块：那会让人以为这部片没有海报，
 *  而是给一块和海报同形状的 shimmer 骨架，图到了再换下来。
 *  已经躺在缓存里的图不会再发 load 事件（上一版靠全局 onload，缓存图永远不淡），
 *  所以在 ref 里当场问一句 complete —— 而且这种图**不再淡一次**，
 *  翻页时早就解码好的海报再淡一遍，看着就是整行"回闪"。 */
export function PosterImage({ pic, title }: { pic?: string; title: string }) {
  const src = posterOf(pic);
  const [st, setSt] = useState({ shown: false, instant: false });
  const [broken, setBroken] = useState(false);
  const attach = useCallback((node: HTMLImageElement | null) => {
    if (node?.complete && node.naturalWidth > 0) setSt({ shown: true, instant: true });
  }, []);

  if (!src || broken) {
    return (
      <span className="grid size-full place-items-center px-2 text-center text-xs text-muted">{title.slice(0, 8)}</span>
    );
  }
  return (
    <>
      {st.shown ? null : (
        // 空黑块会被读成"这部片没有海报"，所以骨架 + 一颗转着的 Spinner：
        // 骨架说"这里有东西要来"，Spinner 说"还在取"，两者一起才不会被读成"坏了"。
        // 整一屏就是三十几颗，所以它是装饰性的（aria-hidden）：海报本体 alt 也是空的，
        // 给每张卡挂一个 role=status 等于给读屏软件塞三十个实时区。
        <span className="absolute inset-0 grid place-items-center" aria-hidden="true">
          <Skeleton className="absolute inset-0" />
          <Spinner size="sm" className="relative text-accent" />
        </span>
      )}
      <img
        ref={attach}
        src={src}
        alt=""
        loading="lazy"
        decoding="async"
        onLoad={() => setSt((s) => ({ ...s, shown: true }))}
        onError={() => setBroken(true)}
        className={`poster-img size-full object-cover ${
          st.shown ? (st.instant ? "" : "poster-in") : "opacity-0"
        }`}
      />
    </>
  );
}

/** 海报卡：结果页与「猜你想搜」共用一个形状，两处才长得不一样。
 *  整张卡片不能做成 <a>：那样「详情」按钮就嵌在链接里（无效 HTML），点按钮会顺带跳走。
 *  所以图片区是纯 div，片名那两行才是链接，按钮浮在海报右下角。 */
export function Poster({ title, pic, meta, flags, href, spec, onDetail }: Props) {
  // 这个方框就是展开详情时"长出来"的那个元素：名字（view-transition-name）不写死在 CSS 上，
  // 由 App 在点开的那一刻临时挂上去 —— 一屏三十几张卡同时挂同一个名字的话，
  // 浏览器会判成重名、整个过渡直接不做（详情面板里那一份才是新状态里的持有者）
  const cover = useRef<HTMLDivElement>(null);
  const open = () => onDetail(spec, cover.current);
  return (
    <article className="group flex flex-col">
      <div ref={cover} className="cover-box relative aspect-2/3 overflow-hidden rounded-xl bg-default ring-1 ring-border transition group-hover:ring-accent/45">
        <PosterImage pic={pic} title={title} />
        {/* 整张海报都是点击区：只有右下角那颗小按钮的话，触屏上点海报什么也不会发生。
            这一层是个透明按钮（不是 div 加 onClick —— 键盘要能走到它），
            垫在「详情」那颗下面，两者都能开面板。 */}
        <button
          type="button"
          className="cover-hit absolute inset-0"
          aria-label={`《${title}》：看详情与观看地址`}
          onClick={open}
        />
        <Button
          size="sm"
          variant="secondary"
          className="dbtn absolute right-1.5 bottom-1.5 z-10 min-h-8 min-w-10 rounded-full"
          onPress={open}
          aria-label={`查看《${title}》的详情`}
        >
          详情
        </Button>
      </div>
      <div className="mt-2 min-w-0">
        {href ? (
          <a
            href={href}
            className="line-clamp-2 min-h-[2.5em] text-[13px] leading-[1.25rem] font-medium text-foreground hover:text-accent"
            title={title}
          >
            {title}
          </a>
        ) : (
          <p className="line-clamp-2 min-h-[2.5em] text-[13px] leading-[1.25rem] font-medium" title={title}>
            {title}
          </p>
        )}
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
          <Meta parts={meta ?? []} />
          {(flags ?? []).filter(Boolean).map((f) => (
            <Flag key={String(f)}>{f}</Flag>
          ))}
        </div>
      </div>
    </article>
  );
}
