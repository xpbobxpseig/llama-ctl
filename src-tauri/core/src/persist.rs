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
//! JSON goes through `serde_json::Value`: `presets.json` is a free-form
//! user-editable map rather than a fixed struct, but escape sequences and
//! surrogate pairs are exactly where a hand-rolled reader silently loses
//! someone's presets.

use serde_json::Value;
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
pub const MARKET_BASENAME: &str = "market.json";

/// Environment overrides, higher priority than the user data dir.
pub const SETTINGS_OVERRIDE_ENV: &str = "LLAMA_CTL_SETTINGS";
pub const PRESETS_OVERRIDE_ENV: &str = "LLAMA_CTL_PRESETS";
pub const MARKET_OVERRIDE_ENV: &str = "LLAMA_CTL_MARKET";

/// Environment the path resolution reads. Injectable so tests never mutate
/// the real process environment (which is global, and racy under `cargo test`).
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Env {
    pub appdata: Option<String>,
    pub userprofile: Option<String>,
    pub settings_override: Option<String>,
    pub presets_override: Option<String>,
    pub market_override: Option<String>,
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
            market_override: var(MARKET_OVERRIDE_ENV),
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
    /// Translucent window material (Mica); off = opaque surfaces.
    pub mica_enabled: bool,
    /// Check upstream releases on startup; only ever *notifies*.
    pub upd_check_on_startup: bool,
    /// Official binary variant, a key of `updater::channels()`.
    pub upd_channel: String,
    /// Last enumerated NSSM service names, so the first frame can render.
    pub services: Vec<String>,
    /// 模型市场：下载根目录（默认 F:\AI_Model）。
    pub market_download_root: String,
    /// HuggingFace 访问令牌（gated 仓库兜底）。
    pub market_hf_token: String,
    /// 魔搭访问令牌。
    pub market_ms_token: String,
    /// 上次使用的模型源："ms" | "hf"。
    pub market_last_hub: String,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            language: "zh".to_string(),
            appearance: "system".to_string(),
            geometry: None,
            last_preset: String::new(),
            motion_enabled: true,
            mica_enabled: true,
            upd_check_on_startup: true,
            upd_channel: DEFAULT_CHANNEL.to_string(),
            services: Vec::new(),
            market_download_root: r"F:\AI_Model".to_string(),
            market_hf_token: String::new(),
            market_ms_token: String::new(),
            market_last_hub: "ms".to_string(),
        }
    }
}

/// Read settings; missing / corrupt / wrong-typed keys fall back per key.
pub fn load_settings(d: &impl Deps, env: &Env) -> Settings {
    let mut out = Settings::default();
    let Ok(bytes) = d.read_file(&resolve_settings_file(env)) else {
        return out;
    };
    let Some(map) = parse_json(&bytes) else {
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
    if let Some(v) = map.get("mica_enabled").and_then(Value::as_bool) {
        out.mica_enabled = v;
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
    if let Some(v) = map.get("market_download_root").and_then(Value::as_str) {
        out.market_download_root = v.to_string();
    }
    if let Some(v) = map.get("market_hf_token").and_then(Value::as_str) {
        out.market_hf_token = v.to_string();
    }
    if let Some(v) = map.get("market_ms_token").and_then(Value::as_str) {
        out.market_ms_token = v.to_string();
    }
    if let Some(v) = map.get("market_last_hub").and_then(Value::as_str) {
        out.market_last_hub = v.to_string();
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
    map.insert("mica_enabled".to_string(), Value::Bool(settings.mica_enabled));
    map.insert("upd_check_on_startup".to_string(), Value::Bool(settings.upd_check_on_startup));
    map.insert("upd_channel".to_string(), Value::String(settings.upd_channel.clone()));
    map.insert(
        "services".to_string(),
        Value::Array(settings.services.iter().cloned().map(Value::String).collect()),
    );
    map.insert("market_download_root".to_string(), Value::String(settings.market_download_root.clone()));
    map.insert("market_hf_token".to_string(), Value::String(settings.market_hf_token.clone()));
    map.insert("market_ms_token".to_string(), Value::String(settings.market_ms_token.clone()));
    map.insert("market_last_hub".to_string(), Value::String(settings.market_last_hub.clone()));
    write_atomic(d, &resolve_settings_file(env), &to_json_bytes(&map))
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
    let Some(map) = parse_json(&bytes) else {
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
    write_atomic(d, &resolve_presets_file(env), &to_json_bytes(&map))
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
pub fn write_atomic(d: &dyn Deps, target: &Path, contents: &[u8]) -> Result<(), AppError> {
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
/// Parse a JSON object from bytes. `None` when unparseable or not an object —
/// callers treat that as "fall back to defaults", never as an error.
///
/// Uses `serde_json::Value` rather than a hand-rolled reader: these are user
/// preference files, and escape sequences / surrogate pairs / nesting depth are
/// exactly where a hand-written parser silently loses someone's presets.
fn parse_json(bytes: &[u8]) -> Option<BTreeMap<String, Value>> {
    let v: Value = serde_json::from_slice(bytes).ok()?;
    match v {
        Value::Object(map) => Some(map.into_iter().collect()),
        _ => None,
    }
}

/// Serialize pretty-printed with indent 2, matching Python `json.dump`.
fn to_json_bytes(map: &BTreeMap<String, Value>) -> Vec<u8> {
    let mut out = serde_json::to_vec_pretty(&Value::Object(map.clone().into_iter().collect())).unwrap_or_default();
    out.push(b'\n');
    out
}
