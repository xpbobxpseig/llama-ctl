/**
 * The **presentation** half of the Rust field table — what ticket 13 needs and
 * the Snapshot does not carry (see the ticket's own note).
 *
 * `commands::fields::FIELDS` (src-tauri/commands/src/fields.rs) is
 * authoritative for key, aliases, kind, slider bounds and the *Chinese* label.
 * `Snapshot.values` carries the values. What is missing over the wire is the
 * kind of a field, its group, its combo options and its explanation — none of
 * which are in `Snapshot` (verified: `commands::snapshot::Snapshot` has
 * `values` / `extras` / `warnings` / `strings` and nothing else field-shaped,
 * and the 16-command surface has no `get_fields`).
 *
 * So this file is a **labelled local copy of the presentation metadata**, and
 * it is deliberately thin:
 *
 *   - keys, groups and combo options are copied verbatim from
 *     `fields.rs` — `GROUP` uses the same `&'static str` values as
 *     `G_MODEL` … `G_ADV`, and `OPTIONS` the same arrays as `SPEC_TYPES`,
 *     `KV_TYPES`, `FLASH_ATTN`, `HOSTS`. A drift would show up as a group
 *     with no fields or an option list the parser rejects.
 *   - the explanations are the `help` / `option_help` entries of `FIELDS` in
 *     `llama_ctl_gui.py` L78-396, verbatim. Rust already owns four of them as
 *     `param.help.*` / `param.opt.*` in `core::i18n`, so the lookups below
 *     prefer Rust's string table when it has the key: migrating the rest is a
 *     one-line-per-entry move into Rust and a delete here, with no change to
 *     any component.
 *
 * ADR-0005: the explanations stay Chinese in both languages, exactly as
 * `core::i18n` already does for `param.*`. Only the field *labels* are
 * bilingual (`label` is Rust's; `label_en` is Python's).
 */

/** The seven collapsible groups, copied from `G_MODEL` … `G_ADV`. */
export const GROUP = {
  MODEL: '模型与视觉',
  ACCEL: '加速',
  CTX: '上下文与显存',
  CONC: '并发与吞吐',
  SAMPLE: '采样',
  NET: '网络',
  ADV: '高级',
}

/** Group order: the order `FIELDS` declares them in, which is the write-back order. */
export const GROUP_ORDER = [
  GROUP.MODEL,
  GROUP.ACCEL,
  GROUP.CTX,
  GROUP.CONC,
  GROUP.SAMPLE,
  GROUP.NET,
  GROUP.ADV,
]

/** `GROUP_NAMES` in llama_ctl_gui.py L398-406. The Chinese half is Rust's own. */
export const GROUP_LABEL = {
  [GROUP.MODEL]: { zh: '模型与视觉', en: 'Model & Vision' },
  [GROUP.ACCEL]: { zh: '加速', en: 'Acceleration' },
  [GROUP.CTX]: { zh: '上下文与显存', en: 'Context & VRAM' },
  [GROUP.CONC]: { zh: '并发与吞吐', en: 'Concurrency' },
  [GROUP.SAMPLE]: { zh: '采样', en: 'Sampling' },
  [GROUP.NET]: { zh: '网络', en: 'Network' },
  [GROUP.ADV]: { zh: '高级', en: 'Advanced' },
}

/**
 * The 29 fields in table order, with the metadata the widgets need.
 *
 * `zh` is `Field::label` verbatim; `en` is Python's `label_en`. `unit` is
 * Python's slider unit, shown next to the readout.
 */
export const FIELDS = [
  { key: 'model', group: GROUP.MODEL, kind: 'path', zh: '模型文件 (-m/--model)', en: 'Model file (-m/--model)' },
  { key: 'mmproj', group: GROUP.MODEL, kind: 'path', zh: '视觉投影 (--mmproj)', en: 'Vision projector (--mmproj)' },
  { key: 'alias', group: GROUP.MODEL, kind: 'text', zh: '模型别名 (-a/--alias)', en: 'Model alias (-a/--alias)' },

  { key: 'ngl', group: GROUP.ACCEL, kind: 'slider', min: 0, max: 200, step: 1, def: 99, unit: { zh: '层', en: 'layers' }, zh: 'GPU 层数 (-ngl)', en: 'GPU layers (-ngl)' },
  { key: 'spec_type', group: GROUP.ACCEL, kind: 'combo', zh: '投机解码 (-spec-type)', en: 'Speculative decoding (-spec-type)' },
  { key: 'spec_draft_model', group: GROUP.ACCEL, kind: 'path', zh: '草稿模型 (--spec-draft-model)', en: 'Draft model (--spec-draft-model)' },
  { key: 'spec_draft_n_max', group: GROUP.ACCEL, kind: 'slider', min: 1, max: 16, step: 1, def: 3, unit: { zh: 'tok', en: 'tok' }, zh: '草稿长度 (--spec-draft-n-max)', en: 'Draft length (--spec-draft-n-max)' },

  { key: 'ctx_size', group: GROUP.CTX, kind: 'slider', min: 512, max: 1048576, step: 512, def: 131072, unit: { zh: 'token', en: 'tokens' }, zh: '上下文长度 (-ctx-size)', en: 'Context length (-ctx-size)' },
  { key: 'ctk', group: GROUP.CTX, kind: 'combo', zh: 'KV cache 类型 K (-ctk)', en: 'KV cache type K (-ctk)' },
  { key: 'ctv', group: GROUP.CTX, kind: 'combo', zh: 'KV cache 类型 V (-ctv)', en: 'KV cache type V (-ctv)' },
  { key: 'flash_attn', group: GROUP.CTX, kind: 'combo', zh: 'Flash Attention (-fa)', en: 'Flash Attention (-fa)' },

  { key: 'parallel', group: GROUP.CONC, kind: 'slider', min: 1, max: 16, step: 1, def: 1, unit: { zh: '槽', en: 'slots' }, zh: '并发槽数 (-np)', en: 'Parallel slots (-np)' },
  { key: 'batch_size', group: GROUP.CONC, kind: 'slider', min: 128, max: 8192, step: 128, def: 2048, unit: { zh: 'tok', en: 'tok' }, zh: '批大小 (-b)', en: 'Batch size (-b)' },
  { key: 'ubatch_size', group: GROUP.CONC, kind: 'slider', min: 64, max: 2048, step: 64, def: 512, unit: { zh: 'tok', en: 'tok' }, zh: '物理批大小 (-ub)', en: 'Physical batch size (-ub)' },
  { key: 'threads', group: GROUP.CONC, kind: 'slider', min: 1, max: 64, step: 1, def: 16, unit: { zh: '线程', en: 'threads' }, zh: 'CPU 线程 (-t)', en: 'CPU threads (-t)' },

  { key: 'temperature', group: GROUP.SAMPLE, kind: 'slider', min: 0, max: 2, step: 0.05, def: 0.8, unit: { zh: '', en: '' }, zh: '温度 (--temp)', en: 'Temperature (--temp)' },
  { key: 'min_p', group: GROUP.SAMPLE, kind: 'slider', min: 0, max: 0.5, step: 0.01, def: 0.05, unit: { zh: '', en: '' }, zh: 'min-p (--min-p)', en: 'min-p (--min-p)' },
  { key: 'top_k', group: GROUP.SAMPLE, kind: 'slider', min: 0, max: 100, step: 1, def: 40, unit: { zh: '', en: '' }, zh: 'top-k (--top-k)', en: 'top-k (--top-k)' },
  { key: 'top_p', group: GROUP.SAMPLE, kind: 'slider', min: 0, max: 1, step: 0.01, def: 0.95, unit: { zh: '', en: '' }, zh: 'top-p (--top-p)', en: 'top-p (--top-p)' },
  { key: 'seed', group: GROUP.SAMPLE, kind: 'text', zh: '随机种子 (-s)', en: 'Random seed (-s)' },
  { key: 'jinja', group: GROUP.SAMPLE, kind: 'check', onByDefault: true, zh: 'Jinja 模板 (--jinja)', en: 'Jinja template (--jinja)' },
  { key: 'chat_template_kwargs', group: GROUP.SAMPLE, kind: 'text', zh: '模板参数 (--chat-template-kwargs)', en: 'Template args (--chat-template-kwargs)' },

  { key: 'host', group: GROUP.NET, kind: 'combo', zh: '监听地址 (--host)', en: 'Listen address (--host)' },
  { key: 'port', group: GROUP.NET, kind: 'text', zh: '端口 (--port)', en: 'Port (--port)' },

  { key: 'no_mmap', group: GROUP.ADV, kind: 'check', zh: '禁用 mmap (--no-mmap)', en: 'Disable mmap (--no-mmap)' },
  { key: 'mlock', group: GROUP.ADV, kind: 'check', zh: '锁定内存 (--mlock)', en: 'Lock memory (--mlock)' },
  { key: 'no_kv_offload', group: GROUP.ADV, kind: 'check', zh: '禁用 KV 卸载 (--no-kv-offload)', en: 'Disable KV offload (--no-kv-offload)' },
  { key: 'cpu_moe', group: GROUP.ADV, kind: 'check', zh: 'MoE 走 CPU (--cpu-moe)', en: 'MoE on CPU (--cpu-moe)' },
]

/**
 * Combo options, copied from `SPEC_TYPES` / `KV_TYPES` / `FLASH_ATTN` / `HOSTS`
 * in fields.rs. Dropdown order is Rust's, because that is the order a value is
 * written back in and the order the Python build showed.
 */
export const OPTIONS = {
  spec_type: [
    '', 'draft-mtp', 'draft-eagle3', 'draft-simple', 'draft-dflash', 'draft-dspark',
    'ngram-simple', 'ngram-map-k', 'ngram-map-k4v', 'ngram-mod', 'ngram-cache',
  ],
  ctk: ['', 'f16', 'f32', 'bf16', 'q8_0', 'q4_0', 'q4_1', 'iq4_nl', 'q5_0', 'q5_1'],
  ctv: ['', 'f16', 'f32', 'bf16', 'q8_0', 'q4_0', 'q4_1', 'iq4_nl', 'q5_0', 'q5_1'],
  flash_attn: ['auto', 'on', 'off'],
  host: ['127.0.0.1', '0.0.0.0', 'localhost'],
}

/** Fields whose value is a file path: they get the Browse button. */
export const PATH_FIELDS = new Set(['model', 'mmproj', 'spec_draft_model'])

/**
 * The explanations: `help` and `option_help` of `FIELDS` in llama_ctl_gui.py,
 * under the `param.help.*` / `param.opt.*` keys `core::i18n` already uses for
 * the four it owns. Chinese in both languages (ADR-0005).
 */
export const PARAM_COPY = {
  'param.help.model':
    '要加载的 GGUF 模型文件路径。这是最核心的参数——决定用哪个开源模型（如 Qwen、Llama、DeepSeek、GLM 等）。' +
    ' 模型越大、量化越高，占显存越多、效果与速度各异。路径必须是本机存在的 .gguf 文件。',
  'param.help.mmproj':
    '多模态投影文件（.gguf）。仅当模型支持看图/传图时才需要，例如 Qwen-VL 类模型。' +
    ' 填了之后服务才能接收图片。纯文本模型留空即可。',
  'param.help.alias':
    '给模型起一个对外暴露的名字（逗号可分隔多个）。调用 OpenAI 兼容 API 时用它做 model 字段，方便区分。' +
    ' 例如 qwen3.8-27b。可留空，服务会用模型自带 id。',
  'param.help.ngl':
    '把多少层模型权重放到显卡显存里。数值越大越快（显存够时尽量拉满）。' +
    ' 设 0 = 纯 CPU 推理（极慢）。设 99 表示尽量全部上 GPU。' +
    ' 若显存不足会 OOM 崩溃，此时调小。效果无影响，只影响速度。',
  'param.help.spec_type':
    '投机解码：让『草稿』先批量猜多个 token，主模型一次验证整批，从而提速。' +
    ' 常见选 draft-mtp（用模型自带的 MTP 头，无需额外文件）。' +
    ' 注意 MTP 会强制单槽（-np 1），且 LLM 类模型才有效；嵌入/小模型无需开。',
  'param.help.spec_draft_model':
    '投机解码用的『草稿模型』GGUF 文件路径。仅当 spec-type 选 draft-* 时需要：' +
    ' 例如 draft-dflash 要填 DFlash2 草稿文件，draft-eagle3 要填 EAGLE3 草稿文件。' +
    ' 填错或不填对应草稿文件，服务会启动失败。普通模式（none）留空即可。',
  'param.help.spec_draft_n_max':
    '每次投机最多猜测的草稿 token 数。越大单次验证越多、提速潜力越高，但草稿质量下降可能反噬。' +
    ' 默认 3 通常够用；draft-dflash 可试 4~8。仅 draft/ngram 模式生效。',
  'param.help.ctx_size':
    '上下文窗口大小，即可同时『记住』的最长对话长度（含历史）。' +
    ' 越大能处理的文档/对话越长，但占用显存越多、加载越慢。' +
    ' 常用档位：32K（轻量）/128K（本机 24G 稳妥）/256K（需配 KV 量化）/512K~1M（长文档，强烈建议 KV 量化）。' +
    ' 点下方快捷按钮即可一键跳到档位。注：旧参数里 \'-c\' 是 \'--ctx-size\' 简写，冲突时本工具只保留一个。',
  'param.help.ctk':
    'KV cache 是『注意力记忆』的缓存。量化它能大幅省显存、支撑更长上下文，但精度略降。' +
    ' 长上下文（≥64K）强烈建议 q4_0 / iq4_nl / q8_0。ctk/ctv 通常设为一致。',
  'param.help.ctv':
    'KV cache 的 V（Value）部分类型。一般与 ctk 设成相同量化。见上方 ctk 说明。',
  'param.help.flash_attn':
    'Flash Attention 是一种更高效的注意力计算方式：更快、更省显存。' +
    ' 现代显卡（如 RTX 40 系）建议 on；不确定就 auto。',
  'param.help.parallel':
    '服务能同时处理的请求『槽位』数。1 = 单用户独占；调大可并发服务多人，但每个槽都占显存/上下文。' +
    ' 开投机解码(MTP)时会被强制为 1。普通个人使用设 1~4。',
  'param.help.batch_size':
    '一次处理的最大逻辑 token 批量。影响吞吐（多人/长提示时）。调太大占显存。' +
    ' 默认 2048 通常够用；若要更高并发可适度上调。',
  'param.help.ubatch_size':
    '物理批大小，配合 batch-size 使用。一般保持为 batch 的约 1/4。默认 512 即可，调参会同时带动吞吐与显存。',
  'param.help.threads':
    '生成时使用的 CPU 线程数。仅在部分计算落到 CPU 时影响速度（如 ngl 没拉满）。' +
    ' 一般设为本机物理核心数；全 GPU 推理时影响不大。',
  'param.help.temperature':
    '随机性。低（0.2）= 更确定、更死板；高（1.0+）= 更发散、更有创意但易跑题。' +
    ' 日常对话 0.7~0.9；代码/事实问答可调低到 0.2~0.5；0 = 贪心（最确定）。',
  'param.help.min_p':
    '最低概率阈值：只从累计概率足够高的候选里采样，过滤垃圾 token。' +
    ' 0.05 是 llama.cpp 默认；调高更『保守』，调 0 关闭。与 temperature 配合控制质量。',
  'param.help.top_k':
    '只从概率最高的前 k 个候选里采样。k 越小输出越聚焦、越可预测；k 越大越发散。' +
    ' 默认 40；设 0 = 关闭 top-k（只看 top-p）。与 top-p 叠加使用，共同限制候选集。',
  'param.help.top_p':
    '核采样：只从累计概率达 p 的最小候选集里采样。p 越小越保守（如 0.9 只取覆盖 90% 概率的词），' +
    ' p=1.0 = 关闭。默认 0.95。与 top-k 配合：先按 top-k 截前 k 个，再在其中按 top-p 截概率。',
  'param.help.seed':
    '随机种子。固定一个整数可让生成『可复现』（同样输入同样输出）。-1 = 每次随机。' +
    '调试/评测时设固定值，日常留空或 -1。',
  'param.help.jinja':
    '启用服务端 Jinja 聊天模板渲染。参考配置（Qwen 官方示例）均带 --jinja，' +
    ' 能正确套用模型的对话/思考模板。本服务也应勾上，否则可能用错模板导致格式异常。',
  'param.help.chat_template_kwargs':
    '传给聊天模板的 JSON 参数，控制推理行为。Qwen3.8 常用：' +
    ' 关思考 \'{"enable_thinking":false}\'；调推理强度 \'{"reasoning_effort":"low|medium|xhigh"}\'' +
    '（默认 xhigh，无 high/max）。需写合法 JSON，含花括号与引号。留空=默认。',
  'param.help.host':
    '服务监听哪个网络地址。个人单机用 127.0.0.1 最安全；要让手机/其他电脑访问才用 0.0.0.0（务必同时设 api-key）。',
  'param.help.port':
    '服务监听的端口。默认 8080。若被占用就改一个（如 8081）。客户端连 http://地址:端口/v1 。',
  'param.help.no_mmap':
    '关闭内存映射加载。默认用 mmap 加载更快更省内存；某些特殊环境才需要关掉（会变慢）。一般保持关闭此选项。',
  'param.help.mlock':
    '强制把模型锁在物理内存，避免被系统换页到磁盘导致卡顿。仅在内存充足时有意义；本机显存/GPU 推理一般无需开。',
  'param.help.no_kv_offload':
    '不让 KV cache 卸载到 GPU（强制留 CPU）。仅在你明确想压低显存、牺牲速度时启用。常规使用保持关闭。',
  'param.help.cpu_moe':
    'MoE（混合专家）模型把专家权重留在 CPU。仅 MoE 架构模型（如 Qwen-MoE、DeepSeek-MoE）相关；非 MoE 模型忽略。' +
    '显存不够时可用，但会慢。',

  // ---- option explanations ----
  'param.opt.spec_type.none': '不启用投机解码（标准单 token 生成）。',
  'param.opt.spec_type.draft_mtp':
    'MTP：用模型内置的『预测下一 token』头做草稿，提速明显，无需额外文件。推荐 27B 类模型。',
  'param.opt.spec_type.draft_eagle3': 'EAGLE3 草稿模型：需配套 draft 模型文件，质量高但配置复杂。',
  'param.opt.spec_type.draft_simple': '简单草稿（同模型自预测），轻微提速。',
  'param.opt.spec_type.draft_dflash':
    'block-diffusion 草稿（DFlash2）：需配套的 draft 模型文件（用下方『草稿模型』填路径）。本机构建已支持，可试。',
  'param.opt.spec_type.draft_dspark': 'DeepSeek 系 spark 草稿。',
  'param.opt.spec_type.ngram_simple': 'n-gram 草稿：基于历史 token 的统计预测，零额外成本但提速有限。',
  'param.opt.spec_type.ngram_map_k': 'n-gram（map-k 变体）。',
  'param.opt.spec_type.ngram_map_k4v': 'n-gram（map-k4v 变体）。',
  'param.opt.spec_type.ngram_mod': 'n-gram（mod 变体）。',
  'param.opt.spec_type.ngram_cache': 'n-gram（cache 变体）。',

  'param.opt.ctk.none': '默认（f16，精度最高但最占显存）。',
  'param.opt.ctk.f16': '16 位浮点，精度最高、显存占用最大。',
  'param.opt.ctk.f32': '32 位浮点，精度最高、更占显存（一般没必要）。',
  'param.opt.ctk.bf16': 'bfloat16，精度接近 f32 但范围更稳，省显存略优于 f32。',
  'param.opt.ctk.q8_0': '8 位量化，几乎无损、显存减半。',
  'param.opt.ctk.q4_0': '4 位量化，显存大幅降低，长上下文首选，轻微精度损失。',
  'param.opt.ctk.q4_1': '4 位量化变体。',
  'param.opt.ctk.iq4_nl': '4 位重要性量化（non-linear），比 q4_0 更稳，省显存同时保持质量。',
  'param.opt.ctk.q5_0': '5 位量化，介于 q4 与 q8 之间。',
  'param.opt.ctk.q5_1': '5 位量化变体。',

  'param.opt.ctv.none': '默认（f16）。',
  'param.opt.ctv.f16': '16 位浮点，精度最高。',
  'param.opt.ctv.f32': '32 位浮点，最稳但最占显存。',
  'param.opt.ctv.bf16': 'bfloat16，省显存略优于 f32。',
  'param.opt.ctv.q8_0': '8 位量化，近乎无损。',
  'param.opt.ctv.q4_0': '4 位量化，省显存首选。',
  'param.opt.ctv.q4_1': '4 位量化变体。',
  'param.opt.ctv.iq4_nl': '4 位重要性量化，比 q4_0 更稳。',
  'param.opt.ctv.q5_0': '5 位量化。',
  'param.opt.ctv.q5_1': '5 位量化变体。',

  'param.opt.flash_attn.auto': '由 llama.cpp 自动判断是否启用（默认，最稳妥）。',
  'param.opt.flash_attn.on': '强制开启。现代 NVIDIA 显卡开启后更省显存、更快。',
  'param.opt.flash_attn.off': '关闭。极少数老卡或异常时回退用。',

  'param.opt.host.127_0_0_1': '仅本机可访问（最安全，推荐个人使用）。',
  'param.opt.host.0_0_0_0': '监听所有网卡，局域网/外网其他机器也能连（注意安全风险，需配 api-key）。',
  'param.opt.host.localhost': '等价本机回环。',
}

/** What a missing explanation renders as — visible, never blank (ADR-0005). */
export const NO_HELP = '（无说明）'

/**
 * The `param.opt.*` suffix for a raw option value.
 *
 * `''` → `none`, `-` → `_`, `.` → `_`, per the keys `core::i18n` already uses
 * (`param.opt.spec_type.none`, `param.opt.spec_type.draft_mtp`).
 */
export function optionSlug(value) {
  if (value === '' || value === null || value === undefined) return 'none'
  return String(value).replace(/-/g, '_').replace(/\./g, '_')
}

/**
 * A field's explanation. Rust's string table wins when it has the key, so
 * migrating an entry into `core::i18n` takes effect with no change here.
 *
 * @param {string} key
 * @param {Record<string,string>} [strings] the Snapshot's table
 */
export function paramHelp(key, strings) {
  const k = `param.help.${key}`
  return strings?.[k] ?? PARAM_COPY[k] ?? NO_HELP
}

/**
 * The explanation of one combo option, `''` when it has none.
 *
 * @param {string} key field key
 * @param {string} value the raw option value
 * @param {Record<string,string>} [strings]
 */
export function optionHelp(key, value, strings) {
  const k = `param.opt.${key}.${optionSlug(value)}`
  return strings?.[k] ?? PARAM_COPY[k] ?? ''
}
