//! Settings and presets persistence — Rust port of `settings.py` + `presets.py`.
//!
//! Every file access goes through [`Deps`], so the whole module is testable
//! without a disk. Three behaviours are load-bearing and must survive later
//! editing:
//!
//! 1. **Atomic write**: write `<file>.tmp`, then rename over the target. A
//!    crash or a failure mid-write can never leave a partial JSON behind —
//!    the old file stays until the rename succeeds.
//! 2. **Per-key fallback**: a corrupt or unreadable file degrades to defaults
//!    key by key. It is never discarded wholesale (one bad key must not wipe
//!    the user's language, geometry and presets) and never panics.
//! 3. **Write failure is a value, not a panic**: save functions return
//!    `AppError` (the Python `(False, err)` tuple). The caller decides whether
//!    to surface it; a read-only directory must not abort the process.
//!
//! Storage location follows ticket 00's convention exactly (see
//! `.scratch/tauri2-migration/issues/00-migrate-user-data-dir.md`), so the
//! Python and Rust builds read and write the same files:
//!
//! ```text
//! %APPDATA%\llama-ctl\settings.json
//! %APPDATA%\llama-ctl\presets.json
//! ```
//!
//! `LLAMA_CTL_SETTINGS` / `LLAMA_CTL_PRESETS` override it entirely (no user
//! data dir, no migration), same priority as Python.
//!
//! JSON is parsed by a small hand-rolled reader instead of `serde_json`:
//! `serde_json` is a dev-dependency only, and `presets.json` holds free-form
//! user-editable maps that do not map onto a fixed struct anyway.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::deps::{AppError, AppErrorKind, Deps};
use crate::updater::DEFAULT_CHANNEL;

// ---- location (ticket 00 convention) ----

/// Subdirectory of `%APPDATA%` holding both files (`USER_DATA_DIRNAME`).
pub const USER_DATA_DIRNAME: &str = "llama-ctl";
pub const SETTINGS_BASENAME: &str = "settings.json";
pub const PRESETS_BASENAME: &str = "presets.json";

/// Environment overrides, higher priority than the user data dir.
pub const SETTINGS_OVERRIDE_ENV: &str = "LLAMA_CTL_SETTINGS";
pub const PRESETS_OVERRIDE_ENV: &str = "LLAMA_CTL_PRESETS";

/// Environment the path resolution reads. Injectable so tests never mutate
/// the real process environment (which is global, and racy under `cargo test`).
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Env {
    pub appdata: Option<String>,
    pub userprofile: Option<String>,
    pub settings_override: Option<String>,
    pub presets_override: Option<String>,
}

impl Env {
    /// The real process environment. Empty values count as unset, matching
    /// Python's `os.environ.get(...)` truthiness.
    pub fn from_process() -> Self {
        fn var(key: &str) -> Option<String> {
            std::env::var(key).ok().filter(|v| !v.is_empty())
        }
        Self {
            appdata: var("APPDATA"),
            userprofile: var("USERPROFILE"),
            settings_override: var(SETTINGS_OVERRIDE_ENV),
            presets_override: var(PRESETS_OVERRIDE_ENV),
        }
    }
}

fn non_empty(s: Option<&String>) -> Option<&str> {
    s.map(String::as_str).filter(|v| !v.is_empty())
}

/// `%APPDATA%\llama-ctl` — environment variables only, no Windows API, so the
/// Python and Rust builds can never disagree about where the data lives.
pub fn user_data_dir(env: &Env) -> PathBuf {
    let base = match non_empty(env.appdata.as_ref()) {
        Some(appdata) => PathBuf::from(appdata),
        None => match non_empty(env.userprofile.as_ref()) {
            Some(home) => PathBuf::from(home).join("AppData").join("Roaming"),
            // Both missing: stay relative rather than guess a drive. Python's
            // `expanduser` has further fallbacks we deliberately do not copy.
            None => PathBuf::new(),
        },
    };
    base.join(USER_DATA_DIRNAME)
}

/// Final `settings.json` path: `LLAMA_CTL_SETTINGS` > user data dir.
pub fn resolve_settings_file(env: &Env) -> PathBuf {
    match non_empty(env.settings_override.as_ref()) {
        Some(p) => PathBuf::from(p),
        None => user_data_dir(env).join(SETTINGS_BASENAME),
    }
}

/// Final `presets.json` path: `LLAMA_CTL_PRESETS` > user data dir.
pub fn resolve_presets_file(env: &Env) -> PathBuf {
    match non_empty(env.presets_override.as_ref()) {
        Some(p) => PathBuf::from(p),
        None => user_data_dir(env).join(PRESETS_BASENAME),
    }
}

// ---- settings ----

/// Tool preferences. Every field has a default, so a corrupt file degrades
/// instead of failing (mirrors `settings.DEFAULTS`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    /// "zh" | "en"
    pub language: String,
    /// "system" | "light" | "dark"
    pub appearance: String,
    /// "WxH+X+Y"; `None` = let the OS place the window.
    pub geometry: Option<String>,
    /// Last selected preset name.
    pub last_preset: String,
    /// Master animation switch (design-guide §5: off = jump straight to end).
    pub motion_enabled: bool,
    /// Check upstream releases on startup; only ever *notifies*.
    pub upd_check_on_startup: bool,
    /// Official binary variant, a key of `updater::channels()`.
    pub upd_channel: String,
    /// Last enumerated NSSM service names, so the first frame can render.
    pub services: Vec<String>,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            language: "zh".to_string(),
            appearance: "system".to_string(),
            geometry: None,
            last_preset: String::new(),
            motion_enabled: true,
            upd_check_on_startup: true,
            upd_channel: DEFAULT_CHANNEL.to_string(),
            services: Vec::new(),
        }
    }
}

/// Read settings; missing / corrupt / wrong-typed keys fall back per key.
pub fn load_settings(d: &impl Deps, env: &Env) -> Settings {
    let mut out = Settings::default();
    let Ok(bytes) = d.read_file(&resolve_settings_file(env)) else {
        return out;
    };
    let Some(Value::Object(map)) = parse_json(&String::from_utf8_lossy(&bytes)) else {
        return out;
    };

    // Per key: a bad value keeps its default, it does not poison the rest.
    if let Some(v) = map.get("language").and_then(Value::as_str) {
        out.language = v.to_string();
    }
    if let Some(v) = map.get("appearance").and_then(Value::as_str) {
        out.appearance = v.to_string();
    }
    if let Some(v) = map.get("geometry").and_then(Value::as_str) {
        out.geometry = Some(v.to_string());
    }
    if let Some(v) = map.get("last_preset").and_then(Value::as_str) {
        out.last_preset = v.to_string();
    }
    if let Some(v) = map.get("motion_enabled").and_then(Value::as_bool) {
        out.motion_enabled = v;
    }
    if let Some(v) = map.get("upd_check_on_startup").and_then(Value::as_bool) {
        out.upd_check_on_startup = v;
    }
    if let Some(v) = map.get("upd_channel").and_then(Value::as_str) {
        out.upd_channel = v.to_string();
    }
    if let Some(Value::Array(items)) = map.get("services") {
        // Python kept any list; a service name is a string, so non-strings are
        // dropped rather than carried into the dropdown.
        out.services = items.iter().filter_map(Value::as_str).map(str::to_string).collect();
    }
    out
}

/// Write settings back (atomic). Unknown keys are dropped.
pub fn save_settings(d: &impl Deps, env: &Env, settings: &Settings) -> Result<(), AppError> {
    let mut map = BTreeMap::new();
    map.insert("language".to_string(), Value::String(settings.language.clone()));
    map.insert("appearance".to_string(), Value::String(settings.appearance.clone()));
    map.insert(
        "geometry".to_string(),
        match &settings.geometry {
            Some(g) => Value::String(g.clone()),
            None => Value::Null,
        },
    );
    map.insert("last_preset".to_string(), Value::String(settings.last_preset.clone()));
    map.insert("motion_enabled".to_string(), Value::Bool(settings.motion_enabled));
    map.insert("upd_check_on_startup".to_string(), Value::Bool(settings.upd_check_on_startup));
    map.insert("upd_channel".to_string(), Value::String(settings.upd_channel.clone()));
    map.insert(
        "services".to_string(),
        Value::Array(settings.services.iter().cloned().map(Value::String).collect()),
    );
    write_atomic(d, &resolve_settings_file(env), &to_json_bytes(&Value::Object(map)))
}

// ---- presets ----

/// One preset's form values (`field key -> value`).
pub type PresetValues = BTreeMap<String, String>;
/// All presets, keyed by name. Sorted, so the dropdown order is stable.
pub type Presets = BTreeMap<String, PresetValues>;

/// Read all presets. Missing / corrupt / non-object file yields an empty map
/// (never an error — a broken file must not block startup).
pub fn load_presets(d: &impl Deps, env: &Env) -> Presets {
    let Ok(bytes) = d.read_file(&resolve_presets_file(env)) else {
        return Presets::new();
    };
    let Some(Value::Object(map)) = parse_json(&String::from_utf8_lossy(&bytes)) else {
        return Presets::new();
    };
    map.into_iter()
        .filter_map(|(name, v)| {
            let Value::Object(values) = v else { return None };
            let values: PresetValues = values
                .into_iter()
                .filter_map(|(k, v)| Some((k, v.as_str()?.to_string())))
                .collect();
            Some((name, values))
        })
        .collect()
}

/// Write the whole preset map back (atomic).
pub fn save_presets(d: &impl Deps, env: &Env, presets: &Presets) -> Result<(), AppError> {
    let map = presets
        .iter()
        .map(|(name, values)| {
            let inner = values.iter().map(|(k, v)| (k.clone(), Value::String(v.clone()))).collect();
            (name.clone(), Value::Object(inner))
        })
        .collect();
    write_atomic(d, &resolve_presets_file(env), &to_json_bytes(&Value::Object(map)))
}

/// Save one preset. **A name that already exists is a no-op** — it returns
/// `Ok(false)` and writes nothing, because the displayed name may be an
/// auto-selected dropdown entry whose values came from the service, not from
/// that preset (the `_on_preset_committed` / `_sync_preset_with_form` rules).
///
/// `Ok(true)` means it was stored.
pub fn save_preset(d: &impl Deps, env: &Env, name: &str, values: &PresetValues) -> Result<bool, AppError> {
    let mut all = load_presets(d, env);
    if all.contains_key(name) {
        return Ok(false);
    }
    all.insert(name.to_string(), values.clone());
    save_presets(d, env, &all)?;
    Ok(true)
}

/// Delete one preset. `Ok(false)` when there was nothing to delete (no write).
pub fn delete_preset(d: &impl Deps, env: &Env, name: &str) -> Result<bool, AppError> {
    let mut all = load_presets(d, env);
    if all.remove(name).is_none() {
        return Ok(false);
    }
    save_presets(d, env, &all)?;
    Ok(true)
}

/// Read one preset for **filling the form only**.
///
/// Deliberately read-only: it touches nothing but the file, never the service
/// (no spawn, no registry, no write). Wiring the values into the form and
/// writing parameters back to the service are separate steps owned by the
/// caller, so "load" can never silently reconfigure a running service.
pub fn load_preset_values(d: &impl Deps, env: &Env, name: &str) -> Option<PresetValues> {
    load_presets(d, env).get(name).cloned()
}

// ---- atomic write ----

/// Write `<target>.tmp`, then rename it over `target`.
///
/// The parent directory is created first (first run / moved install dir). A
/// failure at either step returns an `AppError` after removing the temp file —
/// it never panics and never leaves a partial file where the real one was.
pub fn write_atomic(d: &impl Deps, target: &Path, contents: &[u8]) -> Result<(), AppError> {
    let tmp = tmp_path(target);
    if let Some(parent) = target.parent()
        && !parent.as_os_str().is_empty()
    {
        d.create_dir_all(parent).map_err(storage_error)?;
    }
    if let Err(e) = d.write_file(&tmp, contents) {
        let _ = d.remove_file(&tmp);
        return Err(storage_error(e));
    }
    match d.rename_file(&tmp, target) {
        Ok(()) => Ok(()),
        Err(e) => {
            let _ = d.remove_file(&tmp);
            Err(storage_error(e))
        }
    }
}

fn tmp_path(target: &Path) -> PathBuf {
    let mut os = target.as_os_str().to_os_string();
    os.push(".tmp");
    PathBuf::from(os)
}

fn storage_error(e: crate::deps::DepsError) -> AppError {
    AppError::new(AppErrorKind::StorageFailed, e.message)
}

// ---- minimal JSON ----
//
// ponytail: hand-rolled reader/writer, ~120 lines, at the cost of not covering
// exotic JSON. Ceiling: no big-int precision beyond f64, no streaming. If the
// files ever need more, promote `serde_json` from dev-dependency and delete
// this section — nothing outside it uses `Value`.

#[derive(Debug, Clone, PartialEq)]
pub(crate) enum Value {
    Null,
    Bool(bool),
    Number(f64),
    String(String),
    Array(Vec<Value>),
    Object(BTreeMap<String, Value>),
}

impl Value {
    fn as_str(&self) -> Option<&str> {
        match self {
            Value::String(s) => Some(s),
            _ => None,
        }
    }

    fn as_bool(&self) -> Option<bool> {
        match self {
            Value::Bool(b) => Some(*b),
            _ => None,
        }
    }
}

/// Parse a complete JSON document. `None` on any syntax error — corrupt input
/// is a normal outcome here, not a bug to report.
fn parse_json(text: &str) -> Option<Value> {
    let mut p = Parser { b: text.as_bytes(), i: 0, depth: 0 };
    p.ws();
    let v = p.value().ok()?;
    p.ws();
    (p.i == p.b.len()).then_some(v)
}

/// Bounds the recursion so a hostile file cannot blow the stack.
const MAX_DEPTH: usize = 64;

struct Parser<'a> {
    b: &'a [u8],
    i: usize,
    depth: usize,
}

impl Parser<'_> {
    fn ws(&mut self) {
        while self.b.get(self.i).is_some_and(u8::is_ascii_whitespace) {
            self.i += 1;
        }
    }

    fn value(&mut self) -> Result<Value, ()> {
        if self.depth > MAX_DEPTH {
            return Err(());
        }
        match self.b.get(self.i).copied().ok_or(())? {
            b'{' => self.object(),
            b'[' => self.array(),
            b'"' => Ok(Value::String(self.string()?)),
            b't' => self.literal("true", Value::Bool(true)),
            b'f' => self.literal("false", Value::Bool(false)),
            b'n' => self.literal("null", Value::Null),
            _ => self.number(),
        }
    }

    fn literal(&mut self, word: &str, v: Value) -> Result<Value, ()> {
        if self.b[self.i..].starts_with(word.as_bytes()) {
            self.i += word.len();
            Ok(v)
        } else {
            Err(())
        }
    }

    fn object(&mut self) -> Result<Value, ()> {
        self.i += 1;
        self.depth += 1;
        let mut map = BTreeMap::new();
        let r = self.key_values(&mut map);
        self.depth -= 1;
        r.map(|()| Value::Object(map))
    }

    fn key_values(&mut self, map: &mut BTreeMap<String, Value>) -> Result<(), ()> {
        self.ws();
        if self.b.get(self.i) == Some(&b'}') {
            self.i += 1;
            return Ok(());
        }
        loop {
            self.ws();
            if self.b.get(self.i) != Some(&b'"') {
                return Err(());
            }
            let key = self.string()?;
            self.ws();
            if self.b.get(self.i) != Some(&b':') {
                return Err(());
            }
            self.i += 1;
            self.ws();
            map.insert(key, self.value()?);
            self.ws();
            match self.b.get(self.i) {
                Some(&b',') => self.i += 1,
                Some(&b'}') => {
                    self.i += 1;
                    return Ok(());
                }
                _ => return Err(()),
            }
        }
    }

    fn array(&mut self) -> Result<Value, ()> {
        self.i += 1;
        self.depth += 1;
        let mut items = Vec::new();
        let r = self.items(&mut items);
        self.depth -= 1;
        r.map(|()| Value::Array(items))
    }

    fn items(&mut self, items: &mut Vec<Value>) -> Result<(), ()> {
        self.ws();
        if self.b.get(self.i) == Some(&b']') {
            self.i += 1;
            return Ok(());
        }
        loop {
            self.ws();
            items.push(self.value()?);
            self.ws();
            match self.b.get(self.i) {
                Some(&b',') => self.i += 1,
                Some(&b']') => {
                    self.i += 1;
                    return Ok(());
                }
                _ => return Err(()),
            }
        }
    }

    /// A JSON string with escapes and surrogate pairs; raw UTF-8 kept as-is
    /// (same as Python's `ensure_ascii=False`).
    fn string(&mut self) -> Result<String, ()> {
        self.i += 1; // opening quote
        let mut out = String::new();
        let mut run = self.i;
        loop {
            let c = self.b.get(self.i).copied().ok_or(())?;
            match c {
                b'"' => {
                    out.push_str(self.slice(run, self.i)?);
                    self.i += 1;
                    return Ok(out);
                }
                b'\\' => {
                    out.push_str(self.slice(run, self.i)?);
                    self.i += 1;
                    out.push(self.escape()?);
                    run = self.i;
                }
                0..=0x1F => return Err(()),
                _ => self.i += 1,
            }
        }
    }

    fn slice(&self, from: usize, to: usize) -> Result<&str, ()> {
        std::str::from_utf8(&self.b[from..to]).map_err(|_| ())
    }

    fn escape(&mut self) -> Result<char, ()> {
        let e = self.b.get(self.i).copied().ok_or(())?;
        self.i += 1;
        match e {
            b'"' => Ok('"'),
            b'\\' => Ok('\\'),
            b'/' => Ok('/'),
            b'b' => Ok('\u{8}'),
            b'f' => Ok('\u{c}'),
            b'n' => Ok('\n'),
            b'r' => Ok('\r'),
            b't' => Ok('\t'),
            b'u' => self.unicode_escape(),
            _ => Err(()),
        }
    }

    fn hex4(&mut self) -> Result<u32, ()> {
        let mut cp = 0u32;
        for _ in 0..4 {
            let h = self.b.get(self.i).copied().ok_or(())?;
            cp = cp * 16
                + match h {
                    b'0'..=b'9' => (h - b'0') as u32,
                    b'a'..=b'f' => (h - b'a' + 10) as u32,
                    b'A'..=b'F' => (h - b'A' + 10) as u32,
                    _ => return Err(()),
                };
            self.i += 1;
        }
        Ok(cp)
    }

    fn unicode_escape(&mut self) -> Result<char, ()> {
        let hi = self.hex4()?;
        let cp = if (0xD800..0xDC00).contains(&hi) {
            if self.b.get(self.i..self.i + 2) != Some(b"\\u") {
                return Err(());
            }
            self.i += 2;
            let lo = self.hex4()?;
            if !(0xDC00..0xE000).contains(&lo) {
                return Err(());
            }
            0x10000 + ((hi - 0xD800) << 10) + (lo - 0xDC00)
        } else {
            hi
        };
        char::from_u32(cp).ok_or(())
    }

    fn number(&mut self) -> Result<Value, ()> {
        let start = self.i;
        if self.b.get(self.i) == Some(&b'-') {
            self.i += 1;
        }
        match self.b.get(self.i) {
            Some(&b'0') => self.i += 1,
            Some(c) if c.is_ascii_digit() => self.digits(),
            _ => return Err(()),
        }
        if self.b.get(self.i) == Some(&b'.') {
            self.i += 1;
            if !self.b.get(self.i).is_some_and(|c| c.is_ascii_digit()) {
                return Err(());
            }
            self.digits();
        }
        if matches!(self.b.get(self.i), Some(&b'e') | Some(&b'E')) {
            self.i += 1;
            if matches!(self.b.get(self.i), Some(&b'+') | Some(&b'-')) {
                self.i += 1;
            }
            if !self.b.get(self.i).is_some_and(|c| c.is_ascii_digit()) {
                return Err(());
            }
            self.digits();
        }
        self.slice(start, self.i)?.parse::<f64>().map(Value::Number).map_err(|_| ())
    }

    fn digits(&mut self) {
        while self.b.get(self.i).is_some_and(|c| c.is_ascii_digit()) {
            self.i += 1;
        }
    }
}

/// Serialize pretty-printed (`indent = 2`), like Python's `json.dump`.
fn to_json_bytes(v: &Value) -> Vec<u8> {
    let mut out = Vec::new();
    write_value(&mut out, v, 0);
    out
}

fn write_value(out: &mut Vec<u8>, v: &Value, indent: usize) {
    match v {
        Value::Null => out.extend_from_slice(b"null"),
        Value::Bool(true) => out.extend_from_slice(b"true"),
        Value::Bool(false) => out.extend_from_slice(b"false"),
        Value::Number(n) => out.extend_from_slice(format_number(*n).as_bytes()),
        Value::String(s) => write_json_string(out, s),
        Value::Array(items) => {
            if items.is_empty() {
                out.extend_from_slice(b"[]");
                return;
            }
            out.push(b'[');
            for (n, item) in items.iter().enumerate() {
                if n > 0 {
                    out.push(b',');
                }
                newline_indent(out, indent + 1);
                write_value(out, item, indent + 1);
            }
            newline_indent(out, indent);
            out.push(b']');
        }
        Value::Object(map) => {
            if map.is_empty() {
                out.extend_from_slice(b"{}");
                return;
            }
            out.push(b'{');
            for (n, (key, val)) in map.iter().enumerate() {
                if n > 0 {
                    out.push(b',');
                }
                newline_indent(out, indent + 1);
                write_json_string(out, key);
                out.extend_from_slice(b": ");
                write_value(out, val, indent + 1);
            }
            newline_indent(out, indent);
            out.push(b'}');
        }
    }
}

fn newline_indent(out: &mut Vec<u8>, indent: usize) {
    out.push(b'\n');
    out.extend(std::iter::repeat_n(b' ', indent * 2));
}

fn format_number(n: f64) -> String {
    // Non-finite has no JSON spelling; `null` at least keeps the file parseable.
    if !n.is_finite() {
        return "null".to_string();
    }
    if n.fract() == 0.0 && n.abs() < 1e15 {
        format!("{}", n as i64)
    } else {
        format!("{n}")
    }
}

fn write_json_string(out: &mut Vec<u8>, s: &str) {
    out.push(b'"');
    for c in s.chars() {
        match c {
            '"' => out.extend_from_slice(b"\\\""),
            '\\' => out.extend_from_slice(b"\\\\"),
            '\n' => out.extend_from_slice(b"\\n"),
            '\r' => out.extend_from_slice(b"\\r"),
            '\t' => out.extend_from_slice(b"\\t"),
            '\u{8}' => out.extend_from_slice(b"\\b"),
            '\u{c}' => out.extend_from_slice(b"\\f"),
            c if (c as u32) < 0x20 => out.extend_from_slice(format!("\\u{:04x}", c as u32).as_bytes()),
            c => {
                let mut buf = [0u8; 4];
                out.extend_from_slice(c.encode_utf8(&mut buf).as_bytes());
            }
        }
    }
    out.push(b'"');
}
