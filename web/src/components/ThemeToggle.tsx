import { useMemo } from "react";
import { toast, useTheme } from "@heroui/react";

/** 三态循环：跟随系统 → 亮色 → 暗色 → 跟随系统。
 *  存储与 <html> 上的 class / data-theme 都由 HeroUI 的 useTheme 管（键名 heroui-theme），
 *  壳里那段内联脚本读的就是同一个键，所以首屏不会先白一下再翻黑。 */
const ORDER = ["system", "light", "dark"] as const;
const LABEL: Record<string, string> = { system: "跟随系统", light: "亮色", dark: "暗色" };

function storageWorks(): boolean {
  try {
    localStorage.setItem("zhuiju-probe", "1");
    localStorage.removeItem("zhuiju-probe");
    return true;
  } catch {
    return false;
  }
}

export function ThemeToggle() {
  const { theme, resolvedTheme, setTheme } = useTheme("system");
  const canStore = useMemo(storageWorks, []);
  const intent = ORDER.includes(theme as (typeof ORDER)[number]) ? theme : "system";
  const next = ORDER[(ORDER.indexOf(intent as (typeof ORDER)[number]) + 1) % ORDER.length];
  const shown = intent === "system" ? `${LABEL.system} · ${LABEL[resolvedTheme ?? "light"]}` : LABEL[intent];

  function flip() {
    // 只在切换这 300ms 里给全局挂过渡，之后立刻摘掉；常驻的话 hover 会被拖慢、长列表掉帧
    const root = document.documentElement;
    root.classList.add("theme-anim");
    window.setTimeout(() => root.classList.remove("theme-anim"), 380);
    setTheme(next);
    toast.success(canStore ? `已保存 · ${LABEL[next]}` : "这台浏览器不给存（无痕？），这次生效、关掉就忘");
  }

  return (
    <button
      type="button"
      onClick={flip}
      title="点击在 跟随系统 / 亮色 / 暗色 之间切换"
      aria-label={`界面主题：${shown}`}
      className="inline-flex h-9 items-center gap-2 rounded-full px-2.5 text-xs text-muted transition hover:bg-default hover:text-foreground"
    >
      <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
        {intent === "dark" ? (
          <path d="M20 14.5A8.5 8.5 0 1 1 9.8 4.2a7 7 0 0 0 10.2 10.3z" />
        ) : intent === "light" ? (
          <>
            <circle cx="12" cy="12" r="4.2" />
            <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4" />
          </>
        ) : (
          <>
            <circle cx="12" cy="12" r="8.6" />
            <path d="M12 3.4a8.6 8.6 0 0 1 0 17.2z" fill="currentColor" stroke="none" />
          </>
        )}
      </svg>
      <span className="hidden sm:inline">{shown}</span>
    </button>
  );
}
