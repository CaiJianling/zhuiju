import { useMemo } from "react";
import { ToggleButton, ToggleButtonGroup, toast, useTheme } from "@heroui/react";

/** 三态：跟随系统 / 亮色 / 暗色，一排图标按钮，当前那一档填色 —— 照 HeroUI 文档站顶部
 *  那个控件的样子（它也是一颗 rounded-full 的边框组里三枚 size-6.5 的圆钮，选中那枚上底色）。
 *  以前是"点一下循环三档"：省地方，但人看不出现在选的是哪档、也猜不到再点会到哪档，
 *  而这三档本来就是给人挑的，不是给人试的。
 *
 *  存储与 <html> 上的 class / data-theme 都由 HeroUI 的 useTheme 管（键名 heroui-theme），
 *  壳里那段内联脚本读的就是同一个键，所以首屏不会先白一下再翻黑。 */
const ORDER = ["system", "light", "dark"] as const;
type Mode = (typeof ORDER)[number];
const LABEL: Record<Mode, string> = { system: "跟随系统", light: "亮色", dark: "暗色" };

function Icon({ mode }: { mode: Mode }) {
  return (
    <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      {mode === "dark" ? (
        <path d="M20 14.5A8.5 8.5 0 1 1 9.8 4.2a7 7 0 0 0 10.2 10.3z" />
      ) : mode === "light" ? (
        <>
          <circle cx="12" cy="12" r="4.2" />
          <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4" />
        </>
      ) : (
        <>
          <rect x="2.6" y="4" width="18.8" height="12.4" rx="2" />
          <path d="M9 20h6M12 16.4V20" />
        </>
      )}
    </svg>
  );
}

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
  const intent: Mode = (ORDER as readonly string[]).includes(theme) ? (theme as Mode) : "system";

  function pick(next: Mode) {
    if (next === intent) return;
    // 只在切换这 300ms 里给全局挂过渡，之后立刻摘掉；常驻的话 hover 会被拖慢、长列表掉帧
    const root = document.documentElement;
    root.classList.add("theme-anim");
    window.setTimeout(() => root.classList.remove("theme-anim"), 380);
    setTheme(next);
    toast.success(canStore ? `已保存 · ${LABEL[next]}` : "这台浏览器不给存（无痕？），这次生效、关掉就忘");
  }

  return (
    <ToggleButtonGroup
      size="sm"
      aria-label="界面主题"
      // 文档站那组是 rounded-full 的边框药丸：HeroUI 的 attached group 会把首尾的圆角
      // 收进容器，这里只要把容器本身修圆、去掉按钮之间的缝
      className="rounded-full ring-1 ring-border"
    >
      {ORDER.map((m) => (
        <ToggleButton
          key={m}
          size="sm"
          isIconOnly
          isSelected={intent === m}
          onPress={() => pick(m)}
          aria-label={m === "system" ? `跟随系统（现在是${LABEL[resolvedTheme === "dark" ? "dark" : "light"]}）` : LABEL[m]}
        >
          {/* title 挂在里面的 span 上：RAC 的 ToggleButton 不透传 title */}
          <span title={m === "system" ? `跟随系统（现在是${LABEL[resolvedTheme === "dark" ? "dark" : "light"]}）` : LABEL[m]}>
            <Icon mode={m} />
          </span>
        </ToggleButton>
      ))}
    </ToggleButtonGroup>
  );
}
