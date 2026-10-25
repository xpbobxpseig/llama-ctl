# llama.cpp Service Console 视觉规范

## 色彩令牌

### 浅色

```css
--page: #f4f4f6;
--surface: #ffffff;
--surface-2: #f7f7f9;
--border: #e6e6ea;
--border-strong: #d6d6dc;
--ink: #18181b;
--ink-2: #52525b;
--ink-3: #5f5f66;
--accent: #0b5cb0;
--accent-fill: #0a6fd6;
--accent-soft: #e8f2fe;
--ok: #0f7b3d;
--ok-soft: #e6f6ec;
--warn: #9a5b00;
--warn-soft: #fdf1de;
--err: #c2261c;
--err-soft: #fdecea;
```

### 深色

```css
--page: #121214;
--surface: #1c1c1f;
--surface-2: #26262a;
--border: #313136;
--border-strong: #43434a;
--ink: #f4f4f5;
--ink-2: #b4b4bd;
--ink-3: #8e8e97;
--accent: #4da3ff;
--accent-fill: #0a6fd6;
--accent-soft: #12293f;
--ok: #4ade80;
--ok-soft: #10291b;
--warn: #fbbf24;
--warn-soft: #33260c;
--err: #ff6b61;
--err-soft: #3a1a17;
```

## 字体

- Display: `"Segoe UI Variable Display", "Microsoft YaHei UI", sans-serif`
- Body: `"Segoe UI Variable Text", "Microsoft YaHei UI", "Segoe UI", sans-serif`
- Mono: `"Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace`

## 视觉语言

1. 使用 1px 发丝边框、12px 卡片圆角和 8px 控件圆角构成克制的 Windows 工具界面。
2. 层级主要由字重、灰阶和间距建立，不使用渐变或装饰阴影；仅设置对话框使用轻微阴影。
3. `--accent-fill` 只用于主操作按钮背景，`--accent` 只用于文字、链接和焦点状态。
4. 状态色仅表达运行、警告和错误，不作为装饰色使用。
5. 参数行采用固定帮助列、固定标签列、弹性控件列和右对齐等宽值列，所有右缘严格对齐。
