//! The Field table: which `AppParameters` exist and how each one is rendered.
//!
//! Ported from `FIELDS` in `llama_ctl_gui.py` — **order included**, because
//! [`llama_ctl_core::params::build_params`] emits fields in table order and a
//! reorder would silently rewrite every service's `AppParameters` on the next
//! Apply.
//!
//! Only what the domain layer needs lives here: key, aliases, kind, slider
//! bounds and the negated spellings of "ships ON" switches. Presentation
//! metadata (group heading, combo options, the Chinese label used in parse
//! warnings) rides along in the same table so the form and the parser cannot
//! drift apart. Help text stays in `i18n` (ADR-0005: `param.*` is Chinese in
//! both languages).
//!
//! `ponytail:` this table is data, rebuilt per call rather than cached in a
//! `static` — `Field` owns `String`s, so it cannot be `const`. One allocation
//! per snapshot is far below the noise floor next to a registry read; a lazy
//! `OnceLock` is the upgrade path if the table ever grows by an order of
//! magnitude.

use llama_ctl_core::params::{Field, FieldKind};

#[derive(Debug, Clone, Copy)]
enum Kind {
    Slider { min: f64, max: f64, step: f64, default: f64 },
    Combo,
    Check,
    Text,
}

const fn sl(min: f64, max: f64, step: f64, default: f64) -> Kind {
    Kind::Slider { min, max, step, default }
}

const COMBO: Kind = Kind::Combo;
const CHECK: Kind = Kind::Check;
const TEXT: Kind = Kind::Text;

const NONE: &[&str] = &[];

struct Def {
    key: &'static str,
    label: &'static str,
    group: &'static str,
    aliases: &'static [&'static str],
    off: &'static [&'static str],
    kind: Kind,
    options: &'static [&'static str],
}

const fn def(
    key: &'static str,
    label: &'static str,
    group: &'static str,
    aliases: &'static [&'static str],
    kind: Kind,
    options: &'static [&'static str],
) -> Def {
    Def { key, label, group, aliases, off: NONE, kind, options }
}

// ---- combo options ----

const SPEC_TYPES: &[&str] = &[
    "",
    "draft-mtp",
    "draft-eagle3",
    "draft-simple",
    "draft-dflash",
    "draft-dspark",
    "ngram-simple",
    "ngram-map-k",
    "ngram-map-k4v",
    "ngram-mod",
    "ngram-cache",
];
const KV_TYPES: &[&str] = &["", "f16", "f32", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"];
const FLASH_ATTN: &[&str] = &["auto", "on", "off"];
const HOSTS: &[&str] = &["127.0.0.1", "0.0.0.0", "localhost"];

// ---- groups ----

pub const G_MODEL: &str = "模型与视觉";
pub const G_ACCEL: &str = "加速";
pub const G_CTX: &str = "上下文与显存";
pub const G_CONC: &str = "并发与吞吐";
pub const G_SAMPLE: &str = "采样";
pub const G_NET: &str = "网络";
pub const G_ADV: &str = "高级";

/// `os.cpu_count() or 8`; `threads` bounds follow it, as in Python.
fn cpu_threads() -> f64 {
    std::thread::available_parallelism().map(|n| n.get() as f64).unwrap_or(8.0)
}

fn defs() -> Vec<Def> {
    let cpus = cpu_threads();
    vec![
        def("model", "模型文件 (-m/--model)", G_MODEL, &["-m", "--model"], TEXT, NONE),
        def("mmproj", "视觉投影 (--mmproj)", G_MODEL, &["--mmproj", "-mm"], TEXT, NONE),
        def("alias", "模型别名 (-a/--alias)", G_MODEL, &["-a", "--alias"], TEXT, NONE),
        def(
            "ngl",
            "GPU 层数 (-ngl)",
            G_ACCEL,
            &["-ngl", "--n-gpu-layers", "--gpu-layers"],
            sl(0.0, 200.0, 1.0, 99.0),
            NONE,
        ),
        def("spec_type", "投机解码 (-spec-type)", G_ACCEL, &["--spec-type"], COMBO, SPEC_TYPES),
        def(
            "spec_draft_model",
            "草稿模型 (--spec-draft-model)",
            G_ACCEL,
            &["--spec-draft-model", "-md", "--model-draft"],
            TEXT,
            NONE,
        ),
        def(
            "spec_draft_n_max",
            "草稿长度 (--spec-draft-n-max)",
            G_ACCEL,
            &["--spec-draft-n-max"],
            sl(1.0, 16.0, 1.0, 3.0),
            NONE,
        ),
        def(
            "ctx_size",
            "上下文长度 (-ctx-size)",
            G_CTX,
            &["--ctx-size", "-c"],
            sl(512.0, 1048576.0, 512.0, 131072.0),
            NONE,
        ),
        def("ctk", "KV cache 类型 K (-ctk)", G_CTX, &["-ctk", "--cache-type-k"], COMBO, KV_TYPES),
        def("ctv", "KV cache 类型 V (-ctv)", G_CTX, &["-ctv", "--cache-type-v"], COMBO, KV_TYPES),
        def("flash_attn", "Flash Attention (-fa)", G_CTX, &["-fa", "--flash-attn"], COMBO, FLASH_ATTN),
        def("parallel", "并发槽数 (-np)", G_CONC, &["-np", "--parallel"], sl(1.0, 16.0, 1.0, 1.0), NONE),
        def(
            "batch_size",
            "批大小 (-b)",
            G_CONC,
            &["-b", "--batch-size"],
            sl(128.0, 8192.0, 128.0, 2048.0),
            NONE,
        ),
        def(
            "ubatch_size",
            "物理批大小 (-ub)",
            G_CONC,
            &["-ub", "--ubatch-size"],
            sl(64.0, 2048.0, 64.0, 512.0),
            NONE,
        ),
        def(
            "threads",
            "CPU 线程 (-t)",
            G_CONC,
            &["-t", "--threads"],
            sl(1.0, cpus.max(8.0), 1.0, cpus),
            NONE,
        ),
        def(
            "temperature",
            "温度 (--temp)",
            G_SAMPLE,
            &["--temp", "--temperature"],
            sl(0.0, 2.0, 0.05, 0.8),
            NONE,
        ),
        def("min_p", "min-p (--min-p)", G_SAMPLE, &["--min-p"], sl(0.0, 0.5, 0.01, 0.05), NONE),
        def("top_k", "top-k (--top-k)", G_SAMPLE, &["--top-k"], sl(0.0, 100.0, 1.0, 40.0), NONE),
        def("top_p", "top-p (--top-p)", G_SAMPLE, &["--top-p"], sl(0.0, 1.0, 0.01, 0.95), NONE),
        def("seed", "随机种子 (-s)", G_SAMPLE, &["-s", "--seed"], TEXT, NONE),
        // `--jinja` ships ON in llama.cpp: turning it off has to emit the
        // negation, or "unchecked" silently means "still on".
        Def {
            key: "jinja",
            label: "Jinja 模板 (--jinja)",
            group: G_SAMPLE,
            aliases: &["--jinja"],
            off: &["--no-jinja"],
            kind: CHECK,
            options: NONE,
        },
        def(
            "chat_template_kwargs",
            "模板参数 (--chat-template-kwargs)",
            G_SAMPLE,
            &["--chat-template-kwargs"],
            TEXT,
            NONE,
        ),
        def("host", "监听地址 (--host)", G_NET, &["--host"], COMBO, HOSTS),
        def("port", "端口 (--port)", G_NET, &["--port"], TEXT, NONE),
        def("no_mmap", "禁用 mmap (--no-mmap)", G_ADV, &["--no-mmap"], CHECK, NONE),
        def("mlock", "锁定内存 (--mlock)", G_ADV, &["--mlock"], CHECK, NONE),
        def("no_kv_offload", "禁用 KV 卸载 (--no-kv-offload)", G_ADV, &["--no-kv-offload"], CHECK, NONE),
        def("cpu_moe", "MoE 走 CPU (--cpu-moe)", G_ADV, &["--cpu-moe"], CHECK, NONE),
    ]
}

/// The fields, in the order they are written back.
pub fn fields() -> Vec<Field> {
    defs()
        .into_iter()
        .map(|d| {
            let mut f = match d.kind {
                Kind::Slider { min, max, step, default } => {
                    Field::slider(d.key, d.aliases, min, max, step, default)
                }
                Kind::Combo => Field::combo(d.key, d.aliases),
                Kind::Check if d.off.is_empty() => Field::check(d.key, d.aliases),
                Kind::Check => Field::check_with_off(d.key, d.aliases, d.off),
                Kind::Text => Field::text(d.key, d.aliases),
            };
            // Python's parse warning quotes `fld["label"]`; keeping the label
            // here is what keeps those warnings readable.
            f.label = d.label.to_string();
            f
        })
        .collect()
}

/// The collapsible-group heading a field belongs to (ticket 13 renders these).
pub fn group_of(key: &str) -> Option<&'static str> {
    defs().into_iter().find(|d| d.key == key).map(|d| d.group)
}

/// The selectable values of a combo field, in dropdown order.
pub fn options_of(key: &str) -> &'static [&'static str] {
    defs().into_iter().find(|d| d.key == key).map(|d| d.options).unwrap_or(NONE)
}

/// `true` when the field is rendered as a slider.
pub fn is_slider(key: &str) -> bool {
    defs()
        .into_iter()
        .find(|d| d.key == key)
        .is_some_and(|d| matches!(d.kind, Kind::Slider { .. }))
}

/// Sanity: the table is what the domain layer parses and rebuilds with, so a
/// duplicate key or an alias collision is a bug here, not somewhere downstream.
pub fn validate() -> Vec<String> {
    let fs = fields();
    let mut problems = Vec::new();
    let mut seen_keys = std::collections::BTreeSet::new();
    let mut seen_aliases = std::collections::BTreeMap::new();
    for f in &fs {
        if !seen_keys.insert(f.key.as_str()) {
            problems.push(format!("duplicate field key: {}", f.key));
        }
        for a in &f.aliases {
            if let Some(prev) = seen_aliases.insert(a.as_str(), f.key.as_str())
                && prev != f.key
            {
                problems.push(format!("alias {a} claimed by both {prev} and {}", f.key));
            }
        }
        if f.kind == FieldKind::Combo && options_of(&f.key).is_empty() {
            problems.push(format!("combo field without options: {}", f.key));
        }
    }
    problems
}
