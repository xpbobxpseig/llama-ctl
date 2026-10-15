//! The tauri command surface: every domain operation the frontend can invoke.
//!
//! This module is a thin adapter and nothing else. Each command:
//!
//! 1. takes the `App` out of managed state (Rust holds the truth),
//! 2. calls one function in [`llama_ctl_commands::snapshot`],
//! 3. wraps the result in the [`ipc`] envelope.
//!
//! No domain logic lives here, and no state is cached on this side: the
//! frontend caches form edits locally and re-fetches a Snapshot whenever it
//! needs to know anything. That one-way rule is what keeps "the UI shows
//! applied but the service did not change" impossible.
//!
//! Every command returns `Result<OkPayload, ErrorPayload>` rather than a bare
//! `Result<T, AppError>`, so the frontend can branch on `ok` without guessing
//! which shape came back. See [`ipc`] for the wire contract.
//!
//! The two long operations ([`restart`], [`install_update`]) run on a blocking
//! worker and stream one line per step; they must never sit on the webview's
//! thread, because a silent minute is indistinguishable from a hang.

use std::collections::BTreeMap;
use std::sync::Mutex;

use llama_ctl_commands::ipc::{self, ErrorPayload, OkPayload};
use llama_ctl_commands::snapshot::{self as cmd};
use llama_ctl_core::deps::{AppError, AppErrorKind};
use llama_ctl_core::persist::Settings;
use llama_ctl_core::real::RealDeps;
use llama_ctl_core::service::StartMode;
use serde::Deserialize;
use tauri::{AppHandle, Emitter, Manager, State};

/// The authoritative state, shared by every command.
pub struct AppState {
    inner: Mutex<cmd::App>,
}

impl AppState {
    pub fn new(app: cmd::App) -> Self {
        Self { inner: Mutex::new(app) }
    }

    /// Run `f` against the app. A poisoned mutex means a command panicked
    /// mid-write; keep answering anyway, because a dead lock would freeze the
    /// whole UI.
    pub fn with<T>(&self, f: impl FnOnce(&mut cmd::App) -> T) -> T {
        let mut guard = self.inner.lock().unwrap_or_else(|p| p.into_inner());
        f(&mut guard)
    }
}

/// The real `Deps`, injected as managed state so the command layer keeps its
/// `&impl Deps` signature (and so a test could hand it a `FakeDeps` instead).
pub struct DepsHandle {
    deps: RealDeps,
}

impl DepsHandle {
    pub fn new() -> Self {
        Self { deps: RealDeps::new() }
    }
    pub fn deps(&self) -> &RealDeps {
        &self.deps
    }
}

impl Default for DepsHandle {
    fn default() -> Self {
        Self::new()
    }
}

fn with_app<T>(state: &State<'_, AppState>, f: impl FnOnce(&mut cmd::App) -> T) -> T {
    state.with(f)
}

// ---- payloads the frontend sends ----

/// The form: the only thing the frontend owns. Rust never treats it as truth.
pub type FormValues = BTreeMap<String, String>;

#[derive(Debug, Clone, Deserialize)]
pub struct ApplyArgs {
    pub values: FormValues,
    #[serde(default)]
    pub extras: Vec<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SwitchArgs {
    pub service: String,
    pub values: Option<FormValues>,
    /// Store the abandoned form as a timestamped preset first (Auto backup).
    #[serde(default)]
    pub backup: bool,
}

#[derive(Debug, Clone, Deserialize)]
pub struct PresetArgs {
    pub name: String,
    pub values: FormValues,
}

/// The event names progress streams on. The frontend subscribes once and
/// renders lines as they arrive.
pub const EVENT_RESTART: &str = "llama-ctl://restart-progress";
pub const EVENT_UPDATE: &str = "llama-ctl://update-progress";

fn emit(app: &AppHandle, event: &str, line: &str) {
    // A closed or unsubscribed window is not an error — the operation it was
    // watching continues regardless.
    let _ = app.emit(event, line);
}

// ---- reads ----

/// The whole-state Snapshot. One fetch, everything one screen needs.
#[tauri::command]
pub fn get_snapshot(
    d: State<'_, DepsHandle>,
    app: State<'_, AppState>,
    values: Option<FormValues>,
) -> Result<OkPayload, ErrorPayload> {
    let snap = with_app(&app, |a| cmd::snapshot(d.deps(), a, values.as_ref()));
    Ok(OkPayload::new(&snap))
}

/// The tail of the selected service's `server.err`, plus the path it came
/// from so the UI can label the region. Costs one file read; the log region
/// polls it, it is not part of every Snapshot.
#[tauri::command]
pub fn tail_log(
    d: State<'_, DepsHandle>,
    app: State<'_, AppState>,
) -> Result<OkPayload, ErrorPayload> {
    let (lines, path) = with_app(&app, |a| {
        (cmd::tail_log(d.deps(), a), cmd::log_path(d.deps(), a))
    });
    #[derive(serde::Serialize)]
    struct Tail {
        lines: Vec<String>,
        path: Option<String>,
    }
    Ok(OkPayload::new(&Tail { lines, path }))
}

/// Re-enumerate the NSSM services. Costs one powershell call (~0.6 s), so call
/// it off the frame that paints the dropdown.
#[tauri::command]
pub fn refresh_services(
    d: State<'_, DepsHandle>,
    app: State<'_, AppState>,
) -> Result<OkPayload, ErrorPayload> {
    ipc::envelope(with_app(&app, |a| cmd::refresh_services(d.deps(), a)))
}

/// Switch the form to another service, optionally auto-backing-up the edits.
#[tauri::command]
pub fn switch_service(
    d: State<'_, DepsHandle>,
    app: State<'_, AppState>,
    args: SwitchArgs,
) -> Result<OkPayload, ErrorPayload> {
    ipc::envelope(with_app(&app, |a| {
        cmd::switch_service(d.deps(), a, &args.service, args.values.as_ref(), args.backup)
    }))
}

// ---- write-back ----

/// Apply the form: rebuild `AppParameters` and write it back.
#[tauri::command]
pub fn apply_changes(
    d: State<'_, DepsHandle>,
    app: State<'_, AppState>,
    args: ApplyArgs,
) -> Result<OkPayload, ErrorPayload> {
    ipc::envelope(with_app(&app, |a| cmd::apply(d.deps(), a, &args.values, &args.extras)))
}

/// Revert: discard the form and read the service again. Never writes.
#[tauri::command]
pub fn revert(
    d: State<'_, DepsHandle>,
    app: State<'_, AppState>,
) -> Result<OkPayload, ErrorPayload> {
    ipc::envelope(with_app(&app, |a| cmd::revert(d.deps(), a)))
}

// ---- service control ----

/// `sc start` / `sc stop`.
#[tauri::command]
pub fn service_action(
    d: State<'_, DepsHandle>,
    app: State<'_, AppState>,
    action: String,
) -> Result<OkPayload, ErrorPayload> {
    ipc::envelope(with_app(&app, |a| cmd::service_action(d.deps(), a, &action)))
}

/// Set the boot start mode. `mode` is `StartMode`'s own wire value (`"auto"` /
/// `"manual"` / `"disabled"`), the same spelling the Snapshot returns; an
/// unrecognised one falls back to `manual`, as the domain layer does.
#[tauri::command]
pub fn set_start_mode(
    d: State<'_, DepsHandle>,
    app: State<'_, AppState>,
    mode: String,
) -> Result<OkPayload, ErrorPayload> {
    let mode = match mode.as_str() {
        "auto" => StartMode::Auto,
        "disabled" => StartMode::Disabled,
        _ => StartMode::Manual,
    };
    ipc::envelope(with_app(&app, |a| cmd::set_start_mode(d.deps(), a, mode)))
}

/// Restart: stop, start, wait for the health probe — streaming one line per
/// step on [`EVENT_RESTART`].
///
/// Runs on a blocking worker: the wait can legitimately take a minute, and
/// doing that on the webview's thread would look like a frozen window.
#[tauri::command]
pub async fn restart(
    handle: AppHandle,
    values: Option<FormValues>,
) -> Result<OkPayload, ErrorPayload> {
    let form = values.unwrap_or_default();
    run_blocking(handle, EVENT_RESTART, move |d, a, sink| {
        cmd::restart(d, a, &form, sink).map(Some)
    })
    .await
}

// ---- presets ----

/// Load a preset into the form. Reads only — the service is untouched.
#[tauri::command]
pub fn load_preset(
    d: State<'_, DepsHandle>,
    app: State<'_, AppState>,
    name: String,
) -> Result<OkPayload, ErrorPayload> {
    ipc::envelope(with_app(&app, |a| cmd::load_preset(d.deps(), a, &name)))
}

/// Save the form as a preset. `false` when the name already exists.
#[tauri::command]
pub fn save_preset(
    d: State<'_, DepsHandle>,
    app: State<'_, AppState>,
    args: PresetArgs,
) -> Result<OkPayload, ErrorPayload> {
    ipc::envelope(with_app(&app, |a| cmd::save_preset(d.deps(), a, &args.name, &args.values)))
}

/// Delete a preset.
#[tauri::command]
pub fn delete_preset(
    d: State<'_, DepsHandle>,
    app: State<'_, AppState>,
    name: String,
) -> Result<OkPayload, ErrorPayload> {
    ipc::envelope(with_app(&app, |a| cmd::delete_preset(d.deps(), a, &name)))
}

// ---- settings ----

/// Persist preferences. A language change returns the new string table.
#[tauri::command]
pub fn save_settings(
    d: State<'_, DepsHandle>,
    app: State<'_, AppState>,
    settings: Settings,
) -> Result<OkPayload, ErrorPayload> {
    ipc::envelope(with_app(&app, |a| cmd::save_settings(d.deps(), a, &settings)))
}

// ---- updates ----

/// Check for a newer official build. **Never installs** (ADR-0001).
#[tauri::command]
pub fn check_update(
    d: State<'_, DepsHandle>,
    app: State<'_, AppState>,
) -> Result<OkPayload, ErrorPayload> {
    ipc::envelope(with_app(&app, |a| cmd::check_update(d.deps(), a)))
}

/// Install the release the last check found, streaming progress on
/// [`EVENT_UPDATE`].
#[tauri::command]
pub async fn install_update(handle: AppHandle) -> Result<OkPayload, ErrorPayload> {
    run_blocking(handle, EVENT_UPDATE, |d, a, sink| {
        cmd::install_update(d, a, sink).map(Some)
    })
    .await
}

/// Startup cleanup of stale download / backup directories.
#[tauri::command]
pub fn prune_update_dirs(
    d: State<'_, DepsHandle>,
    app: State<'_, AppState>,
) -> Result<OkPayload, ErrorPayload> {
    let removed = with_app(&app, |a| cmd::prune_update_dirs(d.deps(), a));
    Ok(OkPayload::new(&removed))
}

/// `true` when the form differs semantically from the service — lets the
/// frontend decide whether to offer Revert without a whole snapshot.
#[tauri::command]
pub fn is_dirty(
    d: State<'_, DepsHandle>,
    app: State<'_, AppState>,
    values: FormValues,
) -> Result<OkPayload, ErrorPayload> {
    let dirty = with_app(&app, |a| cmd::is_dirty(d.deps(), a, &values));
    Ok(OkPayload::new(&dirty))
}

// ---- long operations -------------------------------------------------------

/// Run a long command on a blocking worker, streaming `event` per progress line.
///
/// The command returns `Option<T>` so one that yields a snapshot and one that
/// reports only through its log can share this path.
async fn run_blocking<T>(
    handle: AppHandle,
    event: &'static str,
    f: impl FnOnce(&RealDeps, &mut cmd::App, &mut dyn FnMut(&str)) -> Result<Option<T>, AppError>
        + Send
        + 'static,
) -> Result<OkPayload, ErrorPayload>
where
    T: serde::Serialize + Send + 'static,
{
    let out = tauri::async_runtime::spawn_blocking(move || {
        let d = handle.state::<DepsHandle>();
        let app = handle.state::<AppState>();
        let mut sink = |line: &str| emit(&handle, event, line);
        app.with(|a| f(d.deps(), a, &mut sink))
    })
    .await
    .unwrap_or_else(|e| Err(AppError::new(AppErrorKind::Refused, format!("worker failed: {e}"))));

    match out {
        Ok(Some(v)) => Ok(OkPayload::new(&v)),
        Ok(None) => Ok(OkPayload::new(&serde_json::Value::Null)),
        Err(e) => Err(ErrorPayload::new(e)),
    }
}

/// The command list, for `invoke_handler`. Adding a command here is the only
/// thing needed to expose it.
pub fn handlers() -> impl Fn(tauri::ipc::Invoke<tauri::Wry>) -> bool + Send + Sync + 'static {
    tauri::generate_handler![
        get_snapshot,
        tail_log,
        refresh_services,
        switch_service,
        apply_changes,
        revert,
        service_action,
        set_start_mode,
        restart,
        load_preset,
        save_preset,
        delete_preset,
        save_settings,
        check_update,
        install_update,
        prune_update_dirs,
        is_dirty,
    ]
}

/// Kept so the wire types stay visibly serialisable: `OkPayload` /
/// `ErrorPayload` are what the frontend parses.
#[allow(dead_code)]
fn _wire_types_are_serializable() {
    fn is<T: serde::Serialize>() {}
    is::<OkPayload>();
    is::<ErrorPayload>();
}
