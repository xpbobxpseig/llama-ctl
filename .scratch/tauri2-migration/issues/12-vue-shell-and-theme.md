# 12: Vue 骨架与 NaiveUI 主题 override

**What to build:** 搭起 Vue 3 前端骨架：路由/页面结构、NaiveUI 接入、以及**完全自定义的主题 override**。用户视角：新界面看起来就是现在这个工具，只是跑在 Web 上——圆角、配色、字阶都不变。

NaiveUI 的取舍是「只要组件，不要视觉」：用它的 slider / select / modal / popover 省掉自绘组件，但主题 token 全部按现有设计语言覆写。依据见 `docs/design/naiveui-vs-current.html` 的对照——NaiveUI 默认是 3px 圆角 + 绿色主色 + 14px 字阶，与现有 Apple 风不是一回事。

**Blocked by:** 09, 11

**Status:** ready-for-agent

- [ ] Vue 3 + NaiveUI 接入，浅/深双主题
- [ ] 主题 override 复刻现有 token：圆角 12px（卡片）/ 8px（控件）
- [ ] 主色 `#0a84ff`；状态色沿用（运行 `#30d158`、警告 `#ff9500`、错误 `#ff3b30`）
- [ ] 字阶六级严格递减：18 / 15 / 13 / 13 / 12 / 11
- [ ] 字体：界面用微软雅黑 UI，数值与日志用 Cascadia Mono（回退 Consolas）
- [ ] 主题切换（跟随系统 / 浅色 / 深色）生效且偏好持久化
- [ ] 窗口几何在重启后恢复
- [ ] 无 CDN、无运行时远程加载（ADR-0001）
- [ ] 视觉验收：与 `docs/design/naiveui-vs-current.html` 左面板对照，token 逐项一致
