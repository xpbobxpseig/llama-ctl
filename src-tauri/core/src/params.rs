//! `AppParameters` text <-> Field values, plus semantic equivalence.
//!
//! Ported from `params.py`. Two rules dominate everything here and must not be
//! "simplified" later:
//!
//! 1. `split_args` reproduces `CommandLineToArgvW` byte for byte, because the
//!    string is handed to that function by Windows before `llama-server.exe`
//!    ever sees it. POSIX splitting rules are wrong here.
//! 2. `build_params` quotes by doubling backslashes *only where a quote
//!    follows*. Doubling every backslash (an earlier bug) silently rewrote UNC
//!    prefixes and broke the inverse relationship with `split_args`.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Field {
    pub key: String,
    pub aliases: Vec<String>,
    pub kind: FieldKind,
    /// Slider bounds and step.
    pub min: Option<f64>,
    pub max: Option<f64>,
    pub step: Option<f64>,
    pub default: Option<f64>,
    /// Negated spellings for a switch that ships ON by default (e.g. `--jinja`
    /// / `--no-jinja`). Absent means ON; turning it off must emit the negation.
    pub off_aliases: Vec<String>,
    pub label: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum FieldKind {
    Slider,
    Combo,
    Check,
    Text,
}

impl Field {
    pub fn slider(key: &str, aliases: &[&str], min: f64, max: f64, step: f64, default: f64) -> Self {
        Self {
            key: key.into(),
            aliases: aliases.iter().map(|a| a.to_string()).collect(),
            kind: FieldKind::Slider,
            min: Some(min),
            max: Some(max),
            step: Some(step),
            default: Some(default),
            off_aliases: vec![],
            label: key.into(),
        }
    }

    pub fn combo(key: &str, aliases: &[&str]) -> Self {
        Self::plain(key, aliases, FieldKind::Combo)
    }

    pub fn check(key: &str, aliases: &[&str]) -> Self {
        Self::plain(key, aliases, FieldKind::Check)
    }

    pub fn text(key: &str, aliases: &[&str]) -> Self {
        Self::plain(key, aliases, FieldKind::Text)
    }

    pub fn check_with_off(key: &str, aliases: &[&str], off: &[&str]) -> Self {
        Self {
            off_aliases: off.iter().map(|a| a.to_string()).collect(),
            ..Self::plain(key, aliases, FieldKind::Check)
        }
    }

    fn plain(key: &str, aliases: &[&str], kind: FieldKind) -> Self {
        Self {
            key: key.into(),
            aliases: aliases.iter().map(|a| a.to_string()).collect(),
            kind,
            min: None,
            max: None,
            step: None,
            default: None,
            off_aliases: vec![],
            label: key.into(),
        }
    }
}

/// Split a command line exactly as `CommandLineToArgvW` does.
///
/// Rules (current CRT): whitespace separates except inside quotes; a backslash
/// is special *only* when adjacent to a quote — an even run before a quote
/// yields half as many backslashes and the quote acts as a delimiter, an odd
/// run yields half as many plus a literal quote. Elsewhere backslashes are
/// literal (this is what keeps `\\NAS\...` intact). An unterminated quote runs
/// to end of string, matching Windows rather than being "fixed".
pub fn split_args(text: &str) -> Vec<String> {
    let b = text.as_bytes();
    let mut out = Vec::new();
    let mut i = 0usize;
    while i < b.len() {
        while i < b.len() && (b[i] == b' ' || b[i] == b'\t') {
            i += 1;
        }
        if i >= b.len() {
            break;
        }
        let mut buf: Vec<u8> = Vec::new();
        let mut in_quotes = false;
        while i < b.len() {
            let c = b[i];
            if c == b'\\' {
                let mut k = 0usize;
                while i < b.len() && b[i] == b'\\' {
                    k += 1;
                    i += 1;
                }
                if i < b.len() && b[i] == b'"' {
                    buf.extend(std::iter::repeat_n(b'\\', k / 2));
                    if k % 2 == 1 {
                        buf.push(b'"');
                    } else {
                        in_quotes = !in_quotes;
                    }
                    i += 1;
                    continue;
                }
                buf.extend(std::iter::repeat_n(b'\\', k));
                continue;
            }
            if c == b'"' {
                in_quotes = !in_quotes;
                i += 1;
                continue;
            }
            if (c == b' ' || c == b'\t') && !in_quotes {
                break;
            }
            buf.push(c);
            i += 1;
        }
        out.push(String::from_utf8_lossy(&buf).into_owned());
    }
    out
}

fn is_number(s: &str) -> bool {
    // NaN/Inf parse via `parse::<f64>` but poison downstream integer handling.
    match s.parse::<f64>() {
        Ok(v) => v.is_finite(),
        Err(_) => false,
    }
}

/// `-1`, `-0.05` — but not `-`, `--foo`, `---`.
fn is_neg_number(t: &str) -> bool {
    t.starts_with('-') && !t.starts_with("--") && t.len() > 1 && is_number(&t[1..])
}

/// Parse `AppParameters` into (values, extras, warnings).
pub fn parse_params(text: &str, fields: &[Field]) -> (std::collections::BTreeMap<String, String>, Vec<String>, Vec<String>) {
    use std::collections::BTreeMap;

    let mut alias_map: std::collections::HashMap<&str, &Field> = std::collections::HashMap::new();
    let mut off_map: std::collections::HashMap<&str, &Field> = std::collections::HashMap::new();
    for f in fields {
        for a in &f.aliases {
            alias_map.insert(a.as_str(), f);
        }
        for a in &f.off_aliases {
            off_map.insert(a.as_str(), f);
        }
    }

    let mut values: BTreeMap<String, String> =
        fields.iter().map(|f| (f.key.clone(), String::new())).collect();
    let mut extras: Vec<String> = Vec::new();
    let mut warnings: Vec<String> = Vec::new();
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
    let mut ctx_seen: Vec<String> = Vec::new();

    let tokens = split_args(text);
    let mut i = 0usize;
    while i < tokens.len() {
        let tok = &tokens[i];
        if let Some(f) = off_map.get(tok.as_str()) {
            values.insert(f.key.clone(), String::new());
            seen.insert(f.key.clone());
            i += 1;
            continue;
        }
        if let Some(f) = alias_map.get(tok.as_str()) {
            let key = f.key.clone();
            if f.kind == FieldKind::Check {
                values.insert(key.clone(), "1".to_string());
                seen.insert(key);
                i += 1;
                continue;
            }
            let val = if i + 1 < tokens.len()
                && (!tokens[i + 1].starts_with('-') || is_neg_number(&tokens[i + 1]))
            {
                let v = tokens[i + 1].clone();
                i += 2;
                v
            } else {
                i += 1;
                String::new()
            };
            if key == "ctx_size" {
                ctx_seen.push(val.clone());
            }
            values.insert(key.clone(), val);
            seen.insert(key);
        } else {
            extras.push(tok.clone());
            i += 1;
        }
    }

    // A switch declaring off_aliases ships ON in llama.cpp; absent means on.
    for f in fields {
        if f.kind == FieldKind::Check && !f.off_aliases.is_empty() && !seen.contains(&f.key) {
            values.insert(f.key.clone(), "1".to_string());
        }
    }

    for f in fields {
        if f.kind != FieldKind::Slider {
            continue;
        }
        let v = values[&f.key].trim().to_string();
        let int_step = f.step.map(|s| s.fract() == 0.0).unwrap_or(false);
        let dflt = f.default.or(f.min).unwrap_or(0.0);
        let fallback = if int_step {
            format!("{}", dflt as i64)
        } else {
            format!("{}", dflt)
        };
        if v.is_empty() || !is_number(&v) {
            values.insert(f.key.clone(), fallback);
            continue;
        }
        let num: f64 = v.parse().unwrap();
        let (lo, hi) = (f.min.unwrap_or(f64::NEG_INFINITY), f.max.unwrap_or(f64::INFINITY));
        if num < lo || num > hi {
            warnings.push(format!(
                "{} 值 {} 超出范围[{},{}]，已回退默认。",
                f.label,
                v,
                f.min.unwrap_or(0.0),
                f.max.unwrap_or(0.0)
            ));
            values.insert(f.key.clone(), fallback);
        } else {
            values.insert(
                f.key.clone(),
                if int_step {
                    format!("{}", num as i64)
                } else {
                    format!("{}", num)
                },
            );
        }
    }

    if ctx_seen.len() > 1 {
        warnings.push(format!(
            "检测到冲突：-c 与 --ctx-size 同时出现 {} 次，已保留最后一项 '{}'（llama.cpp 以最后为准）。",
            ctx_seen.len(),
            ctx_seen.last().unwrap()
        ));
    }

    (values, extras, warnings)
}

/// Rebuild `AppParameters` from field values plus extras.
pub fn build_params(
    values: &std::collections::BTreeMap<String, String>,
    extras: &[String],
    fields: &[Field],
) -> String {
    let mut out: Vec<String> = Vec::new();
    let st = values.get("spec_type").cloned().unwrap_or_default();
    for f in fields {
        let v = values.get(&f.key).cloned().unwrap_or_default();
        let v = v.trim();
        // Draft-only fields are meaningless outside draft spec-decoding mode.
        if f.key.starts_with("spec_draft") && !st.starts_with("draft") {
            continue;
        }
        if f.kind == FieldKind::Check {
            let on = v == "1" || v == "true" || v == "on" || v == "yes";
            if on {
                out.push(f.aliases.last().cloned().unwrap_or_default());
            } else if let Some(off) = f.off_aliases.last() {
                out.push(off.clone());
            }
            continue;
        }
        if v.is_empty() {
            continue;
        }
        let primary = f
            .aliases
            .iter()
            .max_by_key(|a| a.len())
            .cloned()
            .unwrap_or_default();
        out.push(primary);
        out.push(v.to_string());
    }
    out.extend(extras.iter().cloned());
    out.iter()
        .map(|t| if needs_quotes(t) { quote(t) } else { t.clone() })
        .collect::<Vec<_>>()
        .join(" ")
}

/// Quote per CRT rules: double backslashes only immediately before a `"` or at
/// the very end. Doubling everywhere (an earlier bug) corrupts UNC prefixes.
fn quote(t: &str) -> String {
    let mut out = String::from("\"");
    let mut n_bs = 0usize;
    for ch in t.chars() {
        if ch == '\\' {
            n_bs += 1;
            continue;
        }
        if ch == '"' {
            out.extend(std::iter::repeat_n('\\', n_bs * 2 + 1));
            out.push('"');
            n_bs = 0;
            continue;
        }
        if n_bs > 0 {
            out.extend(std::iter::repeat_n('\\', n_bs));
            n_bs = 0;
        }
        out.push(ch);
    }
    out.extend(std::iter::repeat_n('\\', n_bs * 2));
    out.push('"');
    out
}

fn needs_quotes(t: &str) -> bool {
    t.contains(' ') || t.contains('\t') || t.contains('"')
}

/// Semantic (not textual) equality: decides "unapplied changes".
///
/// Aliases, ordering, omitted slider defaults and quoting differences all
/// disappear after parsing, so legacy / hand-written / other-tool parameter
/// sets are not falsely reported as modified. Real value differences, added or
/// removed check flags, and added or removed extras still register.
///
/// Extras compare by list order, not sorted: their order relative to known
/// fields is irrelevant (they are appended on build) but pairwise extras like
/// `--override-tensor A=B` carry meaning in their mutual order.
pub fn semantically_equal(a: &str, b: &str, fields: &[Field]) -> bool {
    let (va, ea, _) = parse_params(a, fields);
    let (vb, eb, _) = parse_params(b, fields);
    va == vb && ea == eb
}
