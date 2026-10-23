import { useState } from "react";
import { Button, Label, SearchField, Tooltip } from "@heroui/react";

const EXAMPLES = ["庆余年", "流浪地球", "繁花", "甄嬛传", "灌篮高手", "科幻"];

export function SearchBar({
  initial,
  onSearch,
  onHome,
}: {
  initial: string;
  onSearch: (kw: string) => void;
  onHome: () => void;
}) {
  const [text, setText] = useState(initial);

  return (
    <form
      className="space-y-3"
      autoComplete="off"
      onSubmit={(e) => {
        e.preventDefault();
        onSearch(text);
      }}
    >
      <div className="flex items-center gap-2">
        <Tooltip>
          <Button
            variant="tertiary"
            isIconOnly
            aria-label="回主页"
            className="shrink-0 rounded-full"
            onPress={onHome}
          >
            <svg viewBox="0 0 24 24" className="size-4" aria-hidden="true">
              <path d="M3 10.6 12 3.4l9 7.2v9.4a1 1 0 0 1-1 1h-5v-6.2H9V21H4a1 1 0 0 1-1-1z" fill="currentColor" />
            </svg>
          </Button>
          <Tooltip.Content>
            <p>回主页 · 显示猜你想搜</p>
          </Tooltip.Content>
        </Tooltip>
        <SearchField
          value={text}
          onChange={setText}
          name="kw"
          maxLength={60}
          className="min-w-0 flex-1"
        >
          {/* 无障碍名字交给这条 sr-only 的 Label：再叠一个 aria-label 就成了
              "影视名称关键词 影视名称关键词"，读屏和快照里都会念两遍 */}
          <Label className="sr-only">影视名称关键词</Label>
          <SearchField.Group className="h-12 rounded-full bg-field-background px-3 shadow-field ring-1 ring-border focus-within:ring-2 focus-within:ring-accent">
            <SearchField.SearchIcon className="size-4 shrink-0 text-muted" />
            <SearchField.Input
              placeholder="例如：庆余年 / 流浪地球 / 繁花 / 灌篮高手"
              className="h-full min-w-0 flex-1 bg-transparent px-2 text-[15px] outline-none placeholder:text-field-placeholder"
            />
            <SearchField.ClearButton className="shrink-0" aria-label="清空关键词" />
          </SearchField.Group>
        </SearchField>
        <Button type="submit" className="h-12 shrink-0 rounded-full px-6" onPress={() => onSearch(text)}>
          搜索
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-2 pl-0.5">
        <span className="text-xs text-muted">试试：</span>
        {EXAMPLES.map((x) => (
          <Button
            key={x}
            size="sm"
            variant="tertiary"
            className="rounded-full"
            onPress={() => {
              setText(x);
              onSearch(x);
            }}
          >
            {x}
          </Button>
        ))}
      </div>
    </form>
  );
}
