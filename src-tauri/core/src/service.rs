//! Service facts and service control — Rust port of `nssm_adapter.py` (ticket 04).
//!
//! Glossary (see `CONTEXT.md`): a **Fact** is read-only state pulled from the
//! system — install directory, `AppParameters`, start mode, run state, health
//! probe result. It is *not* a **Snapshot**: the snapshot is the whole-state
//! copy ticket 11 sends to the frontend, and this module has no opinion about
//! its shape.
//!
//! Three rules here are load-bearing:
//!
//! 1. **Static facts come from the registry, not from a child process.**
//!    Reading a service's facts spawns nothing: `nssm get` costs a process
//!    each per value, and facts are read on every service switch. `nssm get`
//!    is only the fallback for a registry we cannot read.
//! 2. **The cache is dropped only after a write that succeeded.** A failed
//!    write-back must not make the next read re-read a service that did not
//!    change — that is how a user ends up looking at a value they never
//!    managed to save.
//! 3. **Every child process's bytes go through [`crate::decode::decode`].**
//!    NSSM emits UTF-16LE and `sc` the local code page (GBK); decoding them
//!    anywhere else silently mangles Chinese paths.
//!
//! `Deps` gaps, worked around or reported (see `## Resolution` in the ticket):
//!
//! - `Deps::spawn` cannot ask for `CREATE_NO_WINDOW`, which Python passes to
//!   *every* command so no console window flashes. The real implementation has
//!   to apply it unconditionally; nothing here can express it.
//! - `Deps::spawn` reports failure as `Err` with no exit code, so `nssm get`
//!   cannot test `rc == 0` the way Python does; a successful spawn counts as
//!   an answer.
//! - `Deps` has no environment access, so `LLAMA_CTL_NSSM_EXE` /
//!   `LLAMA_CTL_SERVICE` (which override [`NSSM_EXE`] / [`DEFAULT_SERVICE`] in
//!   Python) are not read. The service name is always an argument anyway.

use std::collections::BTreeMap;
use std::sync::{Mutex, MutexGuard};

use serde::Serialize;

use crate::decode::decode;
use crate::deps::{Deps, DepsError, RegHive};

/// The service the dropdown starts on (`DEFAULT_SERVICE` in Python).
pub const DEFAULT_SERVICE: &str = "QwenLLM";

/// Absolute path of `nssm.exe` (`NSSM_EXE` in Python).
pub const NSSM_EXE: &str = r"F:\llama.cpp\nssm\nssm-2.24\win64\nssm.exe";

/// `sc query` reported nothing usable (Python's `"UNKNOWN"`).
pub const UNKNOWN_STATE: &str = "UNKNOWN";
/// The only state that is allowed to answer the health probe.
pub const RUNNING_STATE: &str = "RUNNING";

/// Health detail for a service that was not probed (Python's `"未探活"`).
pub const NOT_PROBED: &str = "未探活";
/// Health detail when no port is configured (Python's `"无 port"`).
pub const NO_PORT: &str = "无 port";
/// Health detail when the port is open but never answered.
pub const NO_ANSWER: &str = "无响应";
/// Health detail for a probe that answered.
pub const ANSWERED: &str = "OK";

/// `HKLM\SYSTEM\CurrentControlSet\Services\<service>`
fn service_key(service: &str) -> String {
    format!(r"SYSTEM\CurrentControlSet\Services\{service}")
}

/// `HKLM\SYSTEM\CurrentControlSet\Services\<service>\Parameters` — where NSSM
/// keeps `AppDirectory` / `AppParameters` / `Application`.
fn params_key(service: &str) -> String {
    format!(r"SYSTEM\CurrentControlSet\Services\{service}\Parameters")
}

// ---- start mode ------------------------------------------------------------

/// Boot start mode of a service, i.e. the registry `Start` DWORD.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum StartMode {
    Auto,
    Manual,
    Disabled,
}

impl StartMode {
    /// `Start` DWORD -> mode. `2=auto / 3=manual / 4=disabled`; every other
    /// value, and an absent one, is `Manual` — the ticket's fallback rule and
    /// Python's `.get(raw, "manual")`.
    pub fn from_dword(raw: Option<u32>) -> Self {
        match raw {
            Some(2) => StartMode::Auto,
            Some(4) => StartMode::Disabled,
            _ => StartMode::Manual,
        }
    }

    /// `nssm get Start` text (`SERVICE_AUTO_START`, …) -> mode. Unrecognised
    /// text is `Manual`; Python returned `None` for a missing value only on the
    /// `nssm get` path, and the ticket folds that into the same fallback.
    pub fn from_nssm_text(raw: &str) -> Self {
        let upper = raw.to_ascii_uppercase();
        if upper.contains("AUTO") {
            StartMode::Auto
        } else if upper.contains("DEMAND") || upper.contains("MANUAL") {
            StartMode::Manual
        } else if upper.contains("DISABLED") {
            StartMode::Disabled
        } else {
            StartMode::Manual
        }
    }

    /// The full uppercase enum `nssm set Start` accepts.
    pub fn nssm_value(self) -> &'static str {
        match self {
            StartMode::Auto => "SERVICE_AUTO_START",
            StartMode::Manual => "SERVICE_DEMAND_START",
            StartMode::Disabled => "SERVICE_DISABLED",
        }
    }

    /// The persisted / wire value.
    pub fn id(self) -> &'static str {
        match self {
            StartMode::Auto => "auto",
            StartMode::Manual => "manual",
            StartMode::Disabled => "disabled",
        }
    }
}

// ---- facts -----------------------------------------------------------------

/// The static facts of one service.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Facts {
    /// `AppDirectory`; `None` when unset or empty (Python's `or None`).
    pub app_dir: Option<String>,
    /// `AppParameters` — the single source of truth for the form.
    pub app_params: String,
    pub start: StartMode,
}

/// Per-service fact cache.
///
/// Explicit rather than a module-level static: `cargo test` runs cases in
/// parallel threads inside one process, so a global cache would leak one
/// case's scripted registry into another's. It also drops Python's
/// `invalidate()`-between-tests ritual. The app holds one of these in its
/// state and hands it to every read.
#[derive(Debug, Default)]
pub struct FactsCache {
    by_service: Mutex<BTreeMap<String, Facts>>,
}

impl FactsCache {
    pub fn new() -> Self {
        Self::default()
    }

    /// A poisoned mutex still holds good facts: losing them would only make
    /// the next read slower, so take the data back rather than panicking.
    fn map(&self) -> MutexGuard<'_, BTreeMap<String, Facts>> {
        self.by_service.lock().unwrap_or_else(|p| p.into_inner())
    }

    pub fn get(&self, service: &str) -> Option<Facts> {
        self.map().get(service).cloned()
    }

    pub fn insert(&self, service: &str, facts: Facts) {
        self.map().insert(service.to_string(), facts);
    }

    /// Drop one service's facts, or every service's when `service` is `None`.
    pub fn invalidate(&self, service: Option<&str>) {
        let mut map = self.map();
        match service {
            Some(service) => {
                map.remove(service);
            }
            None => map.clear(),
        }
    }
}

/// Facts straight from the registry — zero child processes.
///
/// `None` when the key or either value is absent, which is what a foreign
/// service or a permission failure looks like; the caller falls back to
/// `nssm get`. Python raised `OSError` out of `winreg` in both cases, and
/// `Deps::reg_read_*` folds "absent" and "unreadable" into `None` / `Err`
/// respectively — both land here as `None`.
fn read_facts_registry(d: &impl Deps, service: &str) -> Option<Facts> {
    let key = params_key(service);
    // Python read both values and let either missing one raise, so both have
    // to be present for the registry to count as the answer.
    let app_dir = d.reg_read_string(RegHive::LocalMachine, &key, "AppDirectory").ok().flatten()?;
    let app_params = d.reg_read_string(RegHive::LocalMachine, &key, "AppParameters").ok().flatten()?;
    let start = d
        .reg_read_dword(RegHive::LocalMachine, &service_key(service), "Start")
        .ok()
        .flatten();
    Some(Facts {
        app_dir: if app_dir.is_empty() { None } else { Some(app_dir) },
        app_params,
        start: StartMode::from_dword(start),
    })
}

/// Facts from `nssm get` — one child process per value. Only used when the
/// registry gave us nothing.
fn read_facts_nssm(d: &impl Deps, service: &str) -> Facts {
    Facts {
        app_dir: nssm_get(d, service, "AppDirectory").filter(|s| !s.is_empty()),
        app_params: nssm_get(d, service, "AppParameters").unwrap_or_default(),
        start: StartMode::from_nssm_text(&nssm_get(d, service, "Start").unwrap_or_default()),
    }
}

/// Read a service's facts: registry first, `nssm get` when the registry is
/// unreadable. Never cached — [`facts`] is the cached entry point.
pub fn read_facts(d: &impl Deps, service: &str) -> Facts {
    read_facts_registry(d, service).unwrap_or_else(|| read_facts_nssm(d, service))
}

/// The service's facts, cached by service name. A cache hit touches neither
/// the registry nor a child process.
pub fn facts(d: &impl Deps, cache: &FactsCache, service: &str) -> Facts {
    if let Some(cached) = cache.get(service) {
        return cached;
    }
    let fresh = read_facts(d, service);
    cache.insert(service, fresh.clone());
    fresh
}

/// `AppDirectory`, for the GUI to derive the log path. `None` when unset.
pub fn app_directory(d: &impl Deps, cache: &FactsCache, service: &str) -> Option<String> {
    facts(d, cache, service).app_dir
}

/// The service's current `AppParameters` text.
pub fn get_app_parameters(d: &impl Deps, cache: &FactsCache, service: &str) -> String {
    facts(d, cache, service).app_params
}

pub fn get_start_mode(d: &impl Deps, cache: &FactsCache, service: &str) -> StartMode {
    facts(d, cache, service).start
}

// ---- write-back ------------------------------------------------------------

/// `nssm get <service> <param>`; `None` when nssm failed.
pub fn nssm_get(d: &impl Deps, service: &str, param: &str) -> Option<String> {
    // `Deps::spawn` has no exit code, so "failed" == `Err`.
    d.spawn(NSSM_EXE, &["get", service, param])
        .ok()
        .map(|raw| decode(&raw).trim().to_string())
}

/// `nssm set <service> <param> <value>`; the trimmed output on success.
pub fn nssm_set(d: &impl Deps, service: &str, param: &str, value: &str) -> Result<String, DepsError> {
    let raw = d.spawn(NSSM_EXE, &["set", service, param, value])?;
    Ok(decode(&raw).trim().to_string())
}

/// Write `AppParameters` back. **The cache is dropped only when nssm
/// succeeded** — after a failure the cached facts are still true, and re-read
/// them would be a lie about a service that did not change.
pub fn set_app_parameters(
    d: &impl Deps,
    cache: &FactsCache,
    service: &str,
    text: &str,
) -> Result<String, DepsError> {
    let out = nssm_set(d, service, "AppParameters", text)?;
    cache.invalidate(Some(service));
    Ok(out)
}

/// Switch the boot start mode. Same invalidate-only-on-success rule.
pub fn set_start_mode(
    d: &impl Deps,
    cache: &FactsCache,
    service: &str,
    mode: StartMode,
) -> Result<String, DepsError> {
    let out = nssm_set(d, service, "Start", mode.nssm_value())?;
    cache.invalidate(Some(service));
    Ok(out)
}

// ---- service control -------------------------------------------------------

/// The `STATE` word of `sc query` output — `RUNNING`, `STOPPED`,
/// `START_PENDING`, … `None` when there is no state line.
///
/// `sc` prints `STATE              : 4  RUNNING`; the numeric code sits
/// between the colon and the word, and the localised form keeps the same
/// shape, so match the shape rather than a language.
fn parse_state(out: &str) -> Option<&str> {
    let rest = out.split_once("STATE")?.1;
    let rest = rest.split_once(':')?.1;
    let word = rest.trim_start_matches(|c: char| c.is_ascii_digit() || c.is_ascii_whitespace());
    let end = word.find(|c: char| !(c.is_ascii_alphanumeric() || c == '_'))?;
    let word = &word[..end];
    (!word.is_empty()).then_some(word)
}

/// `sc query <service>` state word; [`UNKNOWN_STATE`] when `sc` failed or
/// printed nothing we recognise.
pub fn sc_query_state(d: &impl Deps, service: &str) -> String {
    match d.spawn("sc", &["query", service]) {
        Ok(raw) => parse_state(&decode(&raw)).unwrap_or(UNKNOWN_STATE).to_string(),
        Err(_) => UNKNOWN_STATE.to_string(),
    }
}

/// `sc <action> <service>` (start / stop); the trimmed output on success.
///
/// `sc stop` on an already-stopped service exits 1062, so a failure here is
/// not always a real failure — the caller decides, as Python's GUI does.
pub fn sc_action(d: &impl Deps, action: &str, service: &str) -> Result<String, DepsError> {
    let raw = d.spawn("sc", &[action, service])?;
    Ok(decode(&raw).trim().to_string())
}

/// Every NSSM-managed service on this machine — a service whose binary path
/// contains `nssm`. One `powershell` call, ~0.6 s, so it belongs on a worker
/// thread, never on the frame that paints the dropdown.
///
/// The default service is always first, whether or not powershell found it,
/// and a powershell failure degrades to just that entry rather than to an
/// empty dropdown.
pub fn list_nssm_services(d: &impl Deps) -> Vec<String> {
    let script = r#"Get-CimInstance Win32_Service | Where-Object { $_.PathName -like "*nssm*" } | ForEach-Object { $_.Name }"#;
    let mut names: Vec<String> = match d.spawn("powershell.exe", &["-NoProfile", "-Command", script]) {
        Ok(raw) => decode(&raw).lines().map(str::trim).filter(|l| !l.is_empty()).map(str::to_string).collect(),
        Err(_) => Vec::new(),
    };
    if !names.iter().any(|n| n == DEFAULT_SERVICE) {
        names.insert(0, DEFAULT_SERVICE.to_string());
    }
    names
}

// ---- health ----------------------------------------------------------------

/// The health probe: `GET /health` (`/healthz` on older builds).
///
/// `(ok, detail)`. `port == 0` means "no port configured" and is never probed.
/// A wildcard host (`""`, `0.0.0.0`, `::`) falls back to loopback, because
/// Windows refuses to connect to `http://0.0.0.0:port`.
///
/// The `/health` -> `/healthz` 404 fallback and the 3 s timeout live inside
/// `Deps::probe_health`; the detail string is all this side can report.
pub fn check_health(d: &impl Deps, host: &str, port: u16) -> (bool, String) {
    if port == 0 {
        return (false, NO_PORT.to_string());
    }
    let probe_host = match host {
        "" | "0.0.0.0" | "::" => "127.0.0.1",
        other => other,
    };
    match d.probe_health(probe_host, port) {
        Ok(true) => (true, ANSWERED.to_string()),
        Ok(false) => (false, NO_ANSWER.to_string()),
        Err(e) => (false, e.message),
    }
}

/// One status poll: service state plus the health verdict.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Status {
    /// `sc query` state word.
    pub state: String,
    /// `true` only when the service is `RUNNING` *and* answered the probe.
    pub ok: bool,
    pub detail: String,
}

/// Readiness of a service. Anything that is not `RUNNING` — `START_PENDING`
/// included — is never reported ready and is never probed: `sc` says RUNNING
/// before `llama-server` is listening, which is exactly the false "ready" the
/// probe exists to catch.
pub fn query_status(d: &impl Deps, service: &str, host: &str, port: u16) -> Status {
    let state = sc_query_state(d, service);
    if state == RUNNING_STATE {
        let (ok, detail) = check_health(d, host, port);
        Status { state, ok, detail }
    } else {
        Status { state, ok: false, detail: NOT_PROBED.to_string() }
    }
}
