# 02: Spike — Windows 编码探测与解码

**What to build:** 一个原型验证，不是产品代码。验证 NSSM 的 UTF-16LE 输出与 `sc` 的本地代码页（GBK）输出在 Rust 里怎么正确解码，以及非法字节如何兜底而不 panic。产出是一个结论 + 一段可复用的解码函数，后续所有子进程调用都走它。

这是 spec 标记的最大低估风险。现有 Python 实现靠字节特征探测（第二个字节为 `\x00` 判 UTF-16LE），并用 `errors="replace"` 兜住非法字节。Rust 的 `String::from_utf8` 不宽容，且没有等价的一行兜底。这一块必须在领域层大规模开工前验证清楚，否则会在后期集中爆发。

**Blocked by:** 01

**Status:** done



- [x] 按字节特征探测 UTF-16LE 与本地代码页，行为与现有 Python 实现一致
- [x] 非法字节被替换而非让调用失败（Rust 侧需显式实现，不是默认行为）
- [x] 中文路径与中文服务名往返不乱码
- [x] 空输出、纯 ASCII 输出、混入 BOM 的输出都能正确处理
- [x] 附带测试：给定真实抓到的 NSSM / `sc` 原始字节样本，断言解码结果
- [x] 产出结论写进 spec 的 Further Notes：选定哪个 crate、为什么、有无已知边界
- [x] 若发现需要比 `encoding_rs` 更多的处理，明确指出并在票内给出方案

## Resolution

**Status:** done — `src-tauri/core/src/decode.rs`，22 个测试在 `tests/ticket02_decode.rs`，全绿。

### 选定 crate：`encoding_rs` 0.8.42

理由：它是唯一在**所有**编码（不只是 UTF-8）里把非法序列替换成 U+FFFD 的 Rust 解码器，
一行 `encoding.decode_without_bom_handling(bytes)` 就是 Python 的 `errors="replace"`。

- `String::from_utf8_lossy`：只覆盖 UTF-8 半边，GBK / UTF-16LE 完全不管。
- 手写 GBK 码表：等于自己维护一份没写过的规范的第二实现，是本次迁移最该避免的东西。
- `encoding_rs` 是 WHATWG Encoding Standard 的实现，Firefox 在用，GBK/Big5/Shift_JIS 的
  边界情况（0x80 欧元符、孤立代理项、截断的 lead byte）都已被规范钉死并有测试。

**没有比 `encoding_rs` 更多的处理需求。** 唯一额外写的两件事都很小：BOM 剥离（用
`Encoding::for_bom`，10 行）和 ACP → 编码名的映射表（15 行 `match`）。

### 探测规则（`decode.rs::sniff`）

依次判定，第一条命中即用：

1. `Encoding::for_bom(raw)` —— 有 UTF-8 / UTF-16LE / UTF-16BE BOM 就以它为准，并剥掉 BOM。
   Python 版没有这条（NSSM 不吐 BOM），但 `powershell` 会吐；留着 BOM 会让下游每个
   `starts_with` 比较失效。
2. 否则 `raw.len() >= 2 && raw[1] == 0x00` → UTF-16LE。**逐字节照抄 Python 的
   `raw[1:2] == b"\x00"`。**
3. 否则本地代码页，即 Python 的 `mbcs`。

Python 的两个 `except Exception` 兜底分支在 Rust 侧不需要：`encoding_rs` 的 decode 不会失败，
所以不存在“utf-16-le 失败→退 mbcs”“mbcs 失败→退 utf-8”这两条路径。这是本次迁移里少有的
“Rust 版比 Python 版简单”的地方。

### 一个发现：本机 ACP 不是 936

这台 `zh-CN` 机器 `GetACP()` 返回 **65001**（开了 UTF-8 beta 开关），不是 936。
所以 Python 的 `mbcs` 在本机其实等于 UTF-8，`sc` 吐的是 UTF-8 而不是 GBK。
结论：不能把 GBK 硬编码进去，必须问 OS。

- `decode(raw)` —— 走 `GetACP()`，生产用这个。
- `decode_as(raw, ansi_code_page)` —— 代码页由调用方钉死，测试用这个。
  没有它，GBK 断言会随宿主机的代码页开关而时绿时红。

ACP → 编码名覆盖 936/20936、950、932、949/51949、874、1250-1258；
其余（含 65001 与 0「未确定」）一律退 UTF-8 —— 猜 GBK 会造出乱码，比诚实的一个 U+FFFD 更糟。

### 已知边界

1. **UTF-16LE 输出若以非 ASCII 开头会被误判。** `模型` 的 UTF-16LE 是 `21 6A 8B 57`，
   `raw[1] == 0x6A != 0`，于是按 GBK 解出 `!j媁`。Python 版同样如此，实测
   `raw.decode('mbcs')` 得 `'!j\u5a81W'`。我们读的 NSSM 值（路径、标志、账号名）都以 ASCII
   开头，实际不可达；已用
   `utf16le_starting_with_chinese_matches_the_python_behaviour` 把它钉住，
   将来要改就是有意为之。真出问题时的升级路径是**按命令传 encoding**，不要再堆字节特征。
2. **单字节输出永远按本地代码页解**（`len >= 2` 是硬要求）。影响：无，ASCII 在任何代码页下
   都一致。
3. **非中文代码页上**：936 变成 932/949/950/125x，表里有，中文照样不乱码 —— 因为我们按 ACP
   查表而不是写死 GBK。反过来，在 GBK 机器上读 Big5 的旧数据仍会乱码，但这属于数据来源问题，
   不是解码器能解的。
4. **`encoding_rs` 的 UTF-16LE 是「符合规范」而非「宽容」**：孤立代理项给一个 U+FFFD、
   奇数尾字节给一个 U+FFFD，与 Python `errors="replace"` 一致（实测 `a\u{fffd}`）。
   它不会像 `String::from_utf16_lossy` 那样静默丢弃，也不会 panic。
5. `decode` 每次调用都做一次 `GetACP()`（一次 syscall + 一次表查找）。当前每次用户操作只调
   几次，不值得缓存；真到每帧调用再说。

### 后续票的用法

`Deps::spawn` 已经返回 `Vec<u8>`（ticket 01 定好的 seam，解码不在里面）。ticket 04
（nssm_adapter）里每个 `spawn` 后面接一句 `decode(&raw)` 即可，不要各自写解码。
