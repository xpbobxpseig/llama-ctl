# 08: 文案与 i18n 权威源

**What to build:** 确定双语文案的**单一权威来源**并落地。决策方向：Rust 侧持有一份完整文案表（键 → 中/英），前端只按 key 查表渲染，不在前端另存一份翻译。用户视角：切换界面语言时所有骨架文案同步切换，不存在某处漏翻或两处译法不一致。

spec 里这条标为「待定」，本票要把它定下来。不约定的后果是前端 vue-i18n 与 Rust 侧错误消息各存一份，双语会随时间漂移。

**Blocked by:** 01

**Status:** done

- [x] 文案表集中于 Rust 侧，前端不持有第二份翻译
- [x] 界面骨架文案中英双语齐备（参数详解保持中文，与现状一致）
- [x] 键名沿用现有命名约定（`svc.*` / `btn.*` / `upd.*` / `log.*` 等）
- [x] 缺失 key 有明确回退行为（显示 key），不渲染空白
- [x] 迁移现有文案测试（表级不变量已迁移；en 长度审稿随前端布局票）
- [ ] 语言切换后展开状态、主题等偏好不丢失（转 settings 票：切语言只重建文案）
## Resolution

**决策：Rust 持有唯一完整文案表；前端只按 key 查表，不持有第二份翻译。**

落地：`src-tauri/core/src/i18n.rs`（`pub mod i18n`，已挂到 `src/lib.rs`）。

- 单一表：`STRINGS: &[(&str, &str, &str)]`，每项 `(key, zh, en)`，一条数据同时给出两种语言
  —— 结构上不可能「某 key 只翻了一半」。
- 语言：`enum Lang { Zh, En }`（默认 `Zh`），`set_language(Lang)` / `set_language_code(&str)`
  （未知 code 回退 `Zh`，与 `strings.set_lang` 同款容忍度）/ `language()`。
- 查表：`t(key)`（当前语言）、`t_in(key, Lang)`（显式语言，缺失返回 `None`）、`entry(key)`、`fmt(key, &[(&str, &str)])`（填 `{s}` `{b}` 等占位符）。
- 前端取数：启动时 `snapshot(Lang)` 拉一次 JSON 表当缓存，之后按 key 查。它是本表的**缓存**，
  不是第二份翻译——前端侧不允许再写一份 zh/en。
- 缺失 key 回退：`t(key)` 返回 **key 本身**（可见、可定位，绝不空白）；空 key 返回 `?`。
  回退只在 `t` 里写了一次，`fmt` 天然继承，不存在漏改的第二条路径。
- 键名沿用现有约定（`app.*` / `svc.*` / `boot.*` / `btn.*` / `log.*` / `status.*` / `upd.*`）。
- 参数详解保持中文：`param.help.*` / `param.opt.*` 的 zh 与 en **同文**（与现状一致，ADR-0005 范围）。
- 本票未动 `Deps`：纯逻辑模块，无 IO。

已迁移 90 个 key（顶栏按钮/服务标签/日志行/完整 `upd.*` 更新段落 + 7 个 `param.*` 详解样例），
全部 zh/en 齐备。测试 `tests/ticket08_i18n.rs` 16 例，覆盖点对表整体断言（不是逐 key 手写）：
双语言齐备且非空、无重复 key、命名空间形态、zh/en 占位符集合一致、snapshot 覆盖全表、
缺失 key 回退可见、切语言输出变化、`param.*` 英文模式下仍是中文、`fmt` 填参与缺参可见。

**未在本票收口**：「语言切换后展开状态/主题等偏好不丢失」属于设置持久化与 UI 重建（settings
层：切语言只重建文案，不重建 preference 字段），与文案表本身无关，转 settings 票处理；
`test_strings.py` 的 en 文案长度审稿（按钮 ≤28ch、状态行 ≤50ch）随前端布局票一起迁移。


**Status:** done
