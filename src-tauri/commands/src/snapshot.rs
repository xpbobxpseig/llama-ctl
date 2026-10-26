//! The **Snapshot** contract and every domain operation behind it (ticket 11).
//!
//! Glossary, because the two words are not interchangeable: a **Fact** is one
//! service's read-only state (`AppDirectory`, `AppParameters`, start mode);
//! a **Snapshot** is the whole-state copy this module sends to the frontend in
//! one fetch. Everything one screen needs comes back in it — the frontend never
//! needs a second round trip, and it never owns authoritative state (it only
//! caches form edits while the user is editing).
//!
//! That direction is deliberate. The Python GUI kept a second copy of the state
//! on the widget side and patched the two together with `semantically_equal`; a
//! one-way snapshot makes that class of bug structurally impossible: what the
//! user sees *is* what Rust just read.
//!
//! Three rules are load-bearing here:
//!
//! 1. **Rust writes `AppParameters` only through [`apply`].** Every other
//!    operation reads. "Load a preset" fills the form and nothing else — the
//!    frontend still has to Apply, so loading a preset can never reconfigure a
//!    running service by accident.
//! 2. **Unapplied changes are semantic, Apply's no-change check is textual.**
//!    `CONTEXT.md` settles both: the prompt is `!semantically_equal(form,
//!    AppParameters)`, while Apply compares the rebuilt text to the stored text
//!    so legacy parameters can still be normalised. Swapping the two produces
//!    either a prompt that never clears or one that never appears.
//! 3. **A service we switch to must exist.** [`switch_service`] refuses an
//!    unknown name instead of reading an empty registry key, which would look
//!    like "this service has no parameters" and invite an Apply that wipes them.
//!
//! Every fallible operation returns `AppResult`, so the frontend renders
//! `AppError { kind, message }` directly — no error-string parsing.
//!
//! `Deps` gaps this layer lives with (all recorded by earlier tickets, none
//! papered over):
//!
//! - No sleep: [`restart`] spins on the injected clock with a poll ceiling,
//!   exactly as `core::install` does.
//! - No environment access: `Env` / `InstallEnv` are injected, so tests and the
//!   app call the same functions without touching the real process environment.
//! - No `is_dir`: the update target is derived by `core::install::target_dir`.
//! - `http_get` carries no Content-Length: download progress reports "the body
//!   landed", not a percentage.

use std::collections::BTreeMap;

use serde::Serialize;

use llama_ctl_core::deps::{AppError, AppErrorKind, AppResult, Deps};
use llama_ctl_core::i18n::{self, Lang};
use llama_ctl_core::install::{self as inst, InstallEnv, InstallPaths};
use llama_ctl_core::params::{self, Field};
use llama_ctl_core::persist::{self, Env, Presets, Settings};
use llama_ctl_core::service::{self as svc, app_directory, FactsCache, StartMode, Status};
use llama_ctl_core::updater::{self, Release, Variant};
use llama_ctl_core::update_files;

pub use llama_ctl_core::deps::{AppError as Error, AppErrorKind as ErrorKind};

use crate::copy;
use crate::fields;

pub const PRUNE_KEEP: usize = update_files::PRUNE_KEEP;

/// How many `sc query` polls between two progress lines in [`restart`] — one
/// line every ~6 s, the same cadence `core::install` uses.
const PROGRESS_EVERY: u32 = 12;

// ---- snapshot --------------------------------------------------------------

/// Everything one screen needs, in a single fetch.
///
/// `Serialize` only: the frontend consumes a snapshot and never sends one back,
/// which is what "one-way" means.
///
/// With no service selected the form values are blank and `status` reports
/// `UNKNOWN`, so the frontend renders an empty state instead of a blank window.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Snapshot {
    /// Every known NSSM-managed service, default first.
    pub services: Vec<String>,
    /// The service the form is showing. `""` when none is known.
    pub selected: String,
    /// The selected service's facts. `None` when `selected` is empty.
    pub facts: Option<FactsView>,
    /// `sc query` state plus the health verdict.
    pub status: Status,
    /// The form values the UI should show: the user's in-progress edits when
    /// the caller passed them, else the parse of `AppParameters`. Returning the
    /// form is what lets `load_preset` actually fill the form.
    pub values: BTreeMap<String, String>,
    /// 服务**当前**的参数解析结果——与 `values`（表单/预填写）分离。
    /// 载入预设后两者不同，前端的差异计数与「应用更改」门槛都以它为准。
    #[serde(default)]
    pub service_values: BTreeMap<String, String>,
    /// Tokens of `AppParameters` no field claims; re-emitted verbatim.
    pub extras: Vec<String>,
    /// Parse warnings (out-of-range sliders, conflicting `-c` / `--ctx-size`).
    pub warnings: Vec<String>,
    /// The preset the form currently corresponds to, `""` for none. This is
    /// what allows — and bounds — the preset sync an Apply performs.
    pub preset_loaded: String,
    /// Preset names, sorted.
    pub presets: Vec<String>,
    pub settings: Settings,
    /// Build-variant ids and their display labels.
    pub channels: Vec<(String, String)>,
    /// The whole string table for the active language. Rust owns the copy; the
    /// frontend looks keys up and never edits (ticket 08 / ADR-0005).
    pub strings: BTreeMap<String, String>,
    /// `"zh"` / `"en"`, so the frontend never has to guess which table it got.
    pub lang: String,
}

/// The read-only facts of the selected service, in wire shape.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct FactsView {
    pub app_dir: Option<String>,
    pub app_params: String,
    pub start: StartMode,
    /// `true` when the form differs semantically from `app_params`.
    pub dirty: bool,
}

/// What Apply did, so the frontend can report it without guessing.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ApplyResult {
    /// `false` when the rebuilt text already equalled the stored one: nothing
    /// was written and the caller should say "no changes".
    pub written: bool,
    /// The service was RUNNING when Apply ran, so its parameters are stored but
    /// not in effect yet — the frontend should offer a restart.
    pub needs_restart: bool,
    /// The preset that was overwritten to match, `""` when none was.
    pub preset_synced: String,
    pub snapshot: Snapshot,
}

/// The outcome of an update check.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct UpdateCheck {
    /// `None` when the variant has no release carrying its assets.
    pub release: Option<Release>,
    /// Installed build number; `None` when `llama-server.exe` is unreadable.
    pub installed: Option<u32>,
    /// `true` when `installed` is known and already >= the release's build.
    pub up_to_date: bool,
}

/// What one install did. `replaced` / `added` come straight from
/// `core::install::InstallResult`; `log` is every progress line in order, so the
/// frontend can render the whole transcript after the fact, not just live.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct InstallReport {
    pub replaced: Vec<String>,
    pub added: Vec<String>,
    pub downloaded: usize,
    pub build: Option<u32>,
    pub log: Vec<String>,
}

// ---- app state -------------------------------------------------------------

/// The authoritative state Rust keeps: what the user is looking at, plus the
/// caches that make rereading cheap.
///
/// `Deps` is deliberately **not** stored — it is passed to each call, which is
/// what keeps the `FakeDeps` seam from ticket 01 usable at this layer.
#[derive(Debug)]
pub struct App {
    facts: FactsCache,
    env: Env,
    install_env: InstallEnv,
    /// Last known service list; seeds the first frame and is persisted.
    services: Vec<String>,
    selected: String,
    preset_loaded: String,
    /// The newest release the last [`check_update`] found. Consumed by
    /// [`install_update`], so the user installs the version they were shown.
    pending: Option<Release>,
    /// The variant that check used. Letting the user change the variant and
    /// then install would install something they never saw the notes for.
    pending_variant: Option<Variant>,
}

impl App {
    /// Boot state: settings come from disk and pick the language; the service
    /// list is whatever was persisted last (enumerating for real costs one
    /// powershell call and belongs on a worker thread).
    pub fn new(d: &impl Deps, env: Env, install_env: InstallEnv) -> Self {
        let settings = persist::load_settings(d, &env);
        i18n::set_language_code(&settings.language);
        Self {
            facts: FactsCache::new(),
            env,
            install_env,
            // Seeded through the same rule the GUI used, so the first frame
            // already has a usable dropdown even when the cache predates the
            // currently selected service.
            services: first_paint_services(
                &first_service(&settings.services).unwrap_or_default(),
                &settings.services,
            ),
            selected: first_service(&settings.services).unwrap_or_default(),
            preset_loaded: String::new(),
            pending: None,
            pending_variant: None,
        }
    }

    /// The service the form is showing, or `None` when nothing is known.
    pub fn selected(&self) -> Option<&str> {
        (!self.selected.is_empty()).then_some(self.selected.as_str())
    }

    /// Set the selected service directly. Tests and the window's startup path
    /// use it; the normal route is [`switch_service`], which validates first.
    pub fn select(&mut self, service: &str) {
        self.selected = service.to_string();
        self.preset_loaded.clear();
    }

    /// The last service list Rust knew about.
    pub fn services(&self) -> &[String] {
        &self.services
    }

    fn settings(&self, d: &impl Deps) -> Settings {
        persist::load_settings(d, &self.env)
    }

    fn variant(&self, d: &impl Deps) -> Variant {
        updater::resolve_variant(Some(&self.settings(d).upd_channel))
    }
}

fn first_service(names: &[String]) -> Option<String> {
    names.iter().find(|n| !n.is_empty()).cloned()
}

/// The dropdown's first-frame contents: the cached list in its own order, with
/// `current` moved to the front when the cache does not already contain it.
///
/// Ported from `llama_ctl_gui.py::_first_paint_services`. Two rules matter:
/// a cached list is shown verbatim (the user's last ordering), and a current
/// service the cache has never seen — newly installed, or renamed while we
/// were away — is prepended rather than dropped, so the form is never blank
/// on a machine whose cache predates the service.
pub fn first_paint_services(current: &str, cached: &[String]) -> Vec<String> {
    let cached: Vec<String> = cached.iter().filter(|n| !n.is_empty()).cloned().collect();
    if cached.iter().any(|n| n == current) {
        return cached;
    }
    let mut out = Vec::with_capacity(cached.len() + 1);
    if !current.is_empty() {
        out.push(current.to_string());
    }
    out.extend(cached);
    out
}
// ---- reads -----------------------------------------------------------------

/// Build a snapshot: everything one screen needs.
///
/// `editing` is the form the frontend is currently holding. It decides the
/// "unapplied changes" flag and the health-probe target, and it is never
/// written anywhere — passing [`Snapshot::values`] straight back is the normal
/// case and yields `dirty == false`.
pub fn snapshot(
    d: &impl Deps,
    app: &App,
    editing: Option<&BTreeMap<String, String>>,
) -> Snapshot {
    let fields = fields::fields();
    let settings = app.settings(d);
    i18n::set_language_code(&settings.language);
    let lang = i18n::language();

    let selected = app.selected().unwrap_or_default().to_string();
    let (facts, values, extras, warnings) = match app.selected() {
        Some(service) => {
            let facts = svc::facts(d, &app.facts, service);
            let (values, extras, warnings) = params::parse_params(&facts.app_params, &fields);
            (Some(facts), values, extras, warnings)
        }
        None => (None, blank_values(&fields), Vec::new(), Vec::new()),
    };

    // What the user is editing, else what the service actually holds.
    let form = editing.cloned().unwrap_or_else(|| values.clone());
    let service_values = values.clone();
    let dirty = match &facts {
        Some(f) => !params::semantically_equal(
            &params::build_params(&form, &extras, &fields),
            &f.app_params,
            &fields,
        ),
        None => false,
    };
    let (host, port) = host_port(&form);

    let status = match app.selected() {
        Some(service) => svc::query_status(d, service, &host, port),
        None => Status {
            state: svc::UNKNOWN_STATE.to_string(),
            ok: false,
            detail: svc::NOT_PROBED.to_string(),
        },
    };
    let facts = facts.map(|f| FactsView {
        app_dir: f.app_dir,
        app_params: f.app_params,
        start: f.start,
        dirty,
    });

    Snapshot {
        services: app.services.clone(),
        selected,
        facts,
        status,
        // The form, not the service's own parse: `editing` is what the user is
        // looking at, and it must survive a round trip — otherwise loading a
        // preset would fill the form with the service's values instead.
        values: form,
        service_values,
        extras,
        warnings,
        preset_loaded: app.preset_loaded.clone(),
        presets: persist::load_presets(d, &app.env).into_keys().collect(),
        settings,
        channels: updater::channels().map(|(id, l)| (id.to_string(), l.to_string())).to_vec(),
        strings: i18n::snapshot(lang)
            .into_iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect(),
        lang: lang.code().to_string(),
    }
}

/// The health-probe target, with Python's fallbacks (`host or "127.0.0.1"`,
/// `port or "8080"`).
fn host_port(form: &BTreeMap<String, String>) -> (String, u16) {
    let host = form.get("host").map(String::as_str).unwrap_or("");
    let port = form.get("port").and_then(|p| p.trim().parse::<u16>().ok()).unwrap_or(0);
    (
        if host.is_empty() { "127.0.0.1".to_string() } else { host.to_string() },
        if port == 0 { 8080 } else { port },
    )
}

fn blank_values(fields: &[Field]) -> BTreeMap<String, String> {
    fields.iter().map(|f| (f.key.clone(), String::new())).collect()
}

/// Re-enumerate the NSSM services (one powershell call, ~0.6 s — keep it off
/// the frame that paints anything) and persist the list so the next startup's
/// first frame already has a filled dropdown.
pub fn refresh_services(d: &impl Deps, app: &mut App) -> AppResult<Snapshot> {
    let names = svc::list_nssm_services(d);
    app.services = names.clone();
    // The selected service may have been uninstalled while we were not looking.
    if !names.iter().any(|n| n == &app.selected) {
        app.selected = first_service(&names).unwrap_or_default();
        app.preset_loaded.clear();
    }
    let mut s = app.settings(d);
    if s.services != names {
        s.services = names;
        persist::save_settings(d, &app.env, &s)?;
    }
    Ok(snapshot(d, app, None))
}

/// Switch the form to another service.
///
/// `editing` is the form being abandoned; when it differs semantically from the
/// current service's `AppParameters` and `backup` is set, it is stored under a
/// timestamped name first — the **Auto backup** of `CONTEXT.md`, which is a
/// preset and *not* the file Backup an update makes.
pub fn switch_service(
    d: &impl Deps,
    app: &mut App,
    service: &str,
    editing: Option<&BTreeMap<String, String>>,
    backup: bool,
) -> AppResult<Snapshot> {
    if !app.services.iter().any(|n| n == service) {
        // Not in the cached list: re-enumerate before refusing, because a
        // service installed while the app was open is a normal occurrence.
        let live = svc::list_nssm_services(d);
        if !live.iter().any(|n| n == service) {
            return Err(AppError::new(
                AppErrorKind::NoSuchService,
                copy::fmt("msg.svc.notfound", &[("s", service)]),
            ));
        }
        app.services = live;
    }

    if backup && service != app.selected
        && let Some(values) = editing
        && let Some(current) = app.selected().map(str::to_string)
    {
        auto_backup(d, app, values, &current)?;
    }

    app.selected = service.to_string();
    // The form is about to be refilled from the new service, so it no longer
    // corresponds to any preset. This is what stops the next Apply from
    // overwriting a preset the user never loaded.
    app.preset_loaded.clear();
    Ok(snapshot(d, app, None))
}

/// Store the abandoned form under a timestamped name — the Auto backup.
///
/// A no-op when the form is semantically identical to the service: an unchanged
/// form has nothing to preserve, and Python's rule is "only when there are
/// unapplied changes".
fn auto_backup(
    d: &impl Deps,
    app: &mut App,
    values: &BTreeMap<String, String>,
    current: &str,
) -> AppResult<()> {
    let facts = svc::facts(d, &app.facts, current);
    let fields = fields::fields();
    let (_, extras, _) = params::parse_params(&facts.app_params, &fields);
    let text = params::build_params(values, &extras, &fields);
    if params::semantically_equal(&text, &facts.app_params, &fields) {
        return Ok(());
    }
    let mut all = persist::load_presets(d, &app.env);
    // Two backups in the same second collide; skip rather than clobber.
    // `ponytail:` the stamp is the injected clock's `%m-%d %H:%M:%S`, i.e. the
    // Python `preset.autobackup` shape. Sub-second precision would need a
    // finer stamp, which the seam's `now_millis` already allows — the shape,
    // not the clock, is what is fixed here.
    let name = copy::fmt("preset.autobackup", &[("t", &stamp(d))]);
    if all.contains_key(&name) {
        return Ok(());
    }
    all.insert(name, values.clone());
    persist::save_presets(d, &app.env, &all)
}

/// `MM-DD HH:MM:SS` from the injected clock.
fn stamp(d: &impl Deps) -> String {
    let secs = d.now_millis() / 1000;
    let sod = secs % 86_400;
    let (_, m, day) = civil_from_days((secs / 86_400) as i64);
    format!("{:02}-{:02} {:02}:{:02}:{:02}", m, day, sod / 3600, sod % 3600 / 60, sod % 60)
}

/// Days since 1970-01-01 to `(year, month, day)` — Howard Hinnant's
/// civil-from-days. std has no calendar and a dependency for one stamp is not
/// worth it.
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let month = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if month <= 2 { y + 1 } else { y }, month, day)
}

// ---- write-back ------------------------------------------------------------

/// Apply the form: rebuild `AppParameters` and write it back.
///
/// Two different comparisons, and the distinction is the whole point
/// (`CONTEXT.md`): the no-change test is **textual**, because Apply is also the
/// normalisation pass (legacy `-c 4096 --ctx-size 131072` must still be
/// rewritten even though it is semantically equivalent); the "unapplied changes"
/// prompt is **semantic**, see [`FactsView::dirty`].
///
/// A successful write invalidates the service's fact cache — `core` does that
/// only on success, so a failed write cannot make the next read lie. When the
/// form really came from a preset of the same name, that preset is refreshed so
/// it cannot drift from what is running.
///
/// Deliberately does **not** restart: a RUNNING service reports
/// `needs_restart`, and the frontend calls the streaming [`restart`] command.
/// Python restarted inside Apply; that made a 60-second wait look like a frozen
/// button, which is exactly what the ticket asks us to stream instead.
pub fn apply(
    d: &impl Deps,
    app: &mut App,
    values: &BTreeMap<String, String>,
    extras: &[String],
) -> AppResult<ApplyResult> {
    let service = require_service(app)?.to_string();
    let fields = fields::fields();
    let new_text = params::build_params(values, extras, &fields);
    let current = svc::get_app_parameters(d, &app.facts, &service);
    if new_text == current {
        return Ok(ApplyResult {
            written: false,
            needs_restart: false,
            preset_synced: String::new(),
            snapshot: snapshot(d, app, Some(values)),
        });
    }

    let was_running = svc::sc_query_state(d, &service) == svc::RUNNING_STATE;
    svc::set_app_parameters(d, &app.facts, &service, &new_text).map_err(|e| {
        AppError::new(AppErrorKind::Refused, copy::fmt("msg.write.fail", &[("o", &e.message)]))
    })?;
    // Bookkeeping, never fatal: a preset that cannot be written must not make a
    // successful Apply look like a failure.
    let preset_synced = sync_preset(d, app, values).unwrap_or_default();
    // 应用成功 = 表单内容已成为服务参数：预填写（preset_loaded）被消费，
    // 「已载入」标记随之清除——它只表示「表单来自该预设且尚未生效」。
    app.preset_loaded.clear();

    Ok(ApplyResult {
        written: true,
        needs_restart: was_running,
        preset_synced,
        snapshot: snapshot(d, app, Some(values)),
    })
}

/// Overwrite the preset the form came from, and only that one.
///
/// Guarded by `preset_loaded`: overwriting a preset the form did not come from
/// would silently destroy user data, because the dropdown may be showing an
/// auto-selected name whose values actually came from the service.
fn sync_preset(
    d: &impl Deps,
    app: &mut App,
    values: &BTreeMap<String, String>,
) -> AppResult<String> {
    let name = app.preset_loaded.clone();
    if name.is_empty() {
        return Ok(String::new());
    }
    let mut all: Presets = persist::load_presets(d, &app.env);
    if !all.contains_key(&name) {
        return Ok(String::new());
    }
    all.insert(name.clone(), values.clone());
    persist::save_presets(d, &app.env, &all)?;
    Ok(name)
}

/// Revert: throw the form away and read `AppParameters` again. Never touches
/// the service.
///
/// The selected service's fact cache is dropped first, so the answer is what
/// the system holds *now* — a Revert that returned a stale cache would quietly
/// restore values the user thought they had discarded.
pub fn revert(d: &impl Deps, app: &mut App) -> AppResult<Snapshot> {
    let service = require_service(app)?.to_string();
    app.facts.invalidate(Some(&service));
    Ok(snapshot(d, app, None))
}

// ---- service control -------------------------------------------------------

/// `sc start` / `sc stop`.
pub fn service_action(d: &impl Deps, app: &mut App, action: &str) -> AppResult<Snapshot> {
    if !matches!(action, "start" | "stop") {
        return Err(AppError::new(
            AppErrorKind::Refused,
            copy::fmt("msg.bad.action", &[("a", action)]),
        ));
    }
    let service = require_service(app)?;
    svc::sc_action(d, action, service).map_err(|e| {
        AppError::new(AppErrorKind::Refused, copy::fmt("msg.sc.fail", &[("a", action), ("m", &e.message)]))
    })?;
    Ok(snapshot(d, app, None))
}

/// Set the boot start mode (`auto` / `manual` / `disabled`).
pub fn set_start_mode(d: &impl Deps, app: &mut App, mode: StartMode) -> AppResult<Snapshot> {
    let service = require_service(app)?;
    svc::set_start_mode(d, &app.facts, service, mode).map_err(|e| {
        AppError::new(AppErrorKind::Refused, copy::fmt("msg.auto.fail", &[("o", &e.message)]))
    })?;
    Ok(snapshot(d, app, None))
}

/// Stop, then start, then wait for the health probe — streaming one line per
/// step to `sink`.
///
/// Mirrors Python's `_restart_worker`: an unhealthy service is restarted anyway
/// (restarting *is* the fix), an already-stopped service skips the stop, and a
/// stop that will not land aborts instead of starting over a running service.
///
/// Not reaching a healthy RUNNING is **not** an error: `sc` reports the service
/// as up and the returned snapshot shows the truth, so a slow model load does
/// not read as a failure.
pub fn restart(
    d: &impl Deps,
    app: &mut App,
    values: &BTreeMap<String, String>,
    sink: &mut dyn FnMut(&str),
) -> AppResult<Snapshot> {
    let service = require_service(app)?.to_string();
    let (host, port) = host_port(values);

    if !svc::check_health(d, &host, port).0 {
        sink(i18n::t("log.restart.unhealthy"));
    }
    if svc::sc_query_state(d, &service) == inst::STOPPED_STATE {
        sink(&format!(
            "{}{}",
            i18n::fmt("log.restart.stop", &[("s", &service)]),
            i18n::t("log.restart.alreadystopped")
        ));
    } else {
        sink(&i18n::fmt("log.restart.stop", &[("s", &service)]));
        // `sc stop` on a stopped service exits 1062, so the follow-up query —
        // not the action's result — decides whether the stop worked.
        if let Err(e) = svc::sc_action(d, "stop", &service)
            && svc::sc_query_state(d, &service) != inst::STOPPED_STATE
        {
            let msg = i18n::fmt("log.restart.stopfail", &[("m", &e.message)]);
            sink(&msg);
            return Err(AppError::new(AppErrorKind::Refused, msg));
        }
        if !wait_for(d, &service, inst::STOPPED_STATE, inst::STOP_POLLS) {
            let msg = i18n::t("log.restart.stoptimeout").to_string();
            sink(&msg);
            return Err(AppError::new(AppErrorKind::Refused, msg));
        }
    }

    sink(i18n::t("log.restart.start"));
    if let Err(e) = svc::sc_action(d, "start", &service) {
        let msg = i18n::fmt("log.restart.startfail", &[("m", &e.message)]);
        sink(&msg);
        return Err(AppError::new(AppErrorKind::Refused, msg));
    }
    for tick in 0..inst::RUNNING_POLLS {
        if svc::sc_query_state(d, &service) == svc::RUNNING_STATE
            && let (true, detail) = svc::check_health(d, &host, port)
        {
            sink(&i18n::fmt("log.restart.ready", &[("d", &detail)]));
            return Ok(snapshot(d, app, None));
        }
        if tick > 0 && tick % PROGRESS_EVERY == 0 {
            sink(&copy::fmt("log.restart.waiting", &[("s", &(tick / 2).to_string())]));
        }
        wait_poll(d);
    }
    // Gave up waiting, not failed: say so instead of streaming silence for a
    // minute and then returning an empty result.
    sink(&i18n::fmt("log.restart.notready", &[("s", &service)]));
    Ok(snapshot(d, app, None))
}

/// Wait one poll interval on the injected clock.
///
/// `ponytail:` `Deps` has no sleep, so this is a spin with a ceiling — with a
/// frozen clock (every test) it degenerates into 64 no-ops instead of hanging.
/// A real clock advances and the wait is the 0.5 s Python slept; the same
/// budget `core::install` uses.
fn wait_poll(d: &impl Deps) {
    let deadline = d.now_millis().saturating_add(500);
    let mut spins = 0;
    while d.now_millis() < deadline && spins < 64 {
        spins += 1;
    }
}

fn wait_for(d: &impl Deps, service: &str, wanted: &str, polls: u32) -> bool {
    for _ in 0..polls {
        if svc::sc_query_state(d, service) == wanted {
            return true;
        }
        wait_poll(d);
    }
    svc::sc_query_state(d, service) == wanted
}

// ---- presets ---------------------------------------------------------------

/// Fill the form from a preset. **Reads only** — the service is untouched, so
/// the frontend still has to Apply.
///
/// Sets `preset_loaded`, which is what later lets an Apply keep that preset in
/// sync. An unknown name is a refusal, not an empty form.
pub fn load_preset(d: &impl Deps, app: &mut App, name: &str) -> AppResult<Snapshot> {
    let values = persist::load_preset_values(d, &app.env, name).ok_or_else(|| {
        AppError::new(AppErrorKind::NoSuchService, copy::fmt("msg.preset.miss", &[("n", name)]))
    })?;
    app.preset_loaded = name.to_string();
    Ok(snapshot(d, app, Some(&values)))
}

/// Store the form under `name`.
///
/// Returns `false` when the name already exists — `core::persist::save_preset`
/// is a no-op then, because an existing name may be an auto-selected dropdown
/// entry whose values came from the service, not from that preset.
pub fn save_preset(
    d: &impl Deps,
    app: &mut App,
    name: &str,
    values: &BTreeMap<String, String>,
) -> AppResult<bool> {
    if name.trim().is_empty() {
        return Err(AppError::new(AppErrorKind::Refused, copy::t("msg.preset.empty")));
    }
    let stored = persist::save_preset(d, &app.env, name, values)?;
    if stored {
        // The saved values are what the form holds, so the form now corresponds
        // to this preset — a later Apply may keep it in sync.
        app.preset_loaded = name.to_string();
    }
    Ok(stored)
}

/// Delete a preset. `false` when there was nothing to delete.
pub fn delete_preset(d: &impl Deps, app: &mut App, name: &str) -> AppResult<bool> {
    let deleted = persist::delete_preset(d, &app.env, name)?;
    if deleted && app.preset_loaded == name {
        // The form's values came from this preset; it must no longer be written
        // back to it.
        app.preset_loaded.clear();
    }
    Ok(deleted)
}

// ---- settings --------------------------------------------------------------

/// Persist preferences and re-read the snapshot — a language change has to come
/// back with the new string table, so the frontend never holds two
/// translations.
///
/// `upd_channel` goes through `core::updater::resolve_variant`: a retired id is
/// folded onto the default rather than failing every future check.
pub fn save_settings(d: &impl Deps, app: &mut App, settings: &Settings) -> AppResult<Snapshot> {
    let mut settings = settings.clone();
    settings.upd_channel = updater::resolve_variant(Some(&settings.upd_channel)).id().to_string();
    persist::save_settings(d, &app.env, &settings)?;
    i18n::set_language_code(&settings.language);
    Ok(snapshot(d, app, None))
}

// ---- updates ---------------------------------------------------------------

/// Look up the newest release for the configured variant and compare it with
/// the installed build. **Never installs** — ADR-0001 / story 52: a startup
/// check only notifies.
pub fn check_update(d: &impl Deps, app: &mut App) -> AppResult<UpdateCheck> {
    let variant = app.variant(d);
    let release = updater::find_latest_release(d, variant)?;
    let installed = installed_build(d, app);
    let up_to_date = matches!((installed, release.build), (Some(cur), newest) if newest <= cur);
    app.pending = Some(release.clone());
    app.pending_variant = Some(variant);
    Ok(UpdateCheck { release: Some(release), installed, up_to_date })
}

/// The installed build number, read from the service's own install directory
/// when it holds `llama-server.exe`, else the environment fallback.
pub fn installed_build(d: &impl Deps, app: &App) -> Option<u32> {
    let service = app.selected()?;
    let dir = inst::target_dir(d, &app.facts, service, &app.install_env);
    updater::get_installed_build(d, &dir.join(inst::SERVER_EXE))
}

/// The tail of the selected service's `server.err`.
///
/// Lives here rather than in [`crate::log`] because it needs `App`'s private
/// facts cache; the path derivation itself is unit-tested there.
///
/// A missing or unreadable file yields no lines and no error — the log region
/// is decoration, and a missing file must never block startup.
pub fn tail_log(d: &impl Deps, app: &App) -> Vec<String> {
    let Some(service) = app.selected() else {
        return Vec::new();
    };
    crate::log::tail_log(d, &app.facts, service)
}

/// Where `server.err` is being read from, so the UI can label the region.
pub fn log_path(d: &impl Deps, app: &App) -> Option<String> {
    let service = app.selected()?;
    let dir = app_directory(d, &app.facts, service);
    Some(crate::log::log_path(dir.as_deref()).to_string_lossy().into_owned())
}

/// Run the update install, streaming every progress line to `sink`.
///
/// Installs the release the last [`check_update`] found, so the user always
/// gets the version whose changelog they were shown. Changing the build variant
/// after that check invalidates it — the refusal is what keeps "I picked CPU"
/// from installing a CUDA build.
///
/// `core::install` already Rolls back what it replaced and restarts the service
/// on any failure, so the `Err` here is safe to show as-is.
pub fn install_update(
    d: &impl Deps,
    app: &mut App,
    sink: &mut dyn FnMut(&str),
) -> AppResult<InstallReport> {
    let service = require_service(app)?.to_string();
    let (Some(rel), Some(checked)) = (app.pending.clone(), app.pending_variant) else {
        return Err(AppError::new(AppErrorKind::UpdateFailed, i18n::t("upd.required").to_string()));
    };
    if checked != app.variant(d) {
        return Err(AppError::new(AppErrorKind::UpdateFailed, copy::t("msg.channel.changed")));
    }

    let target = inst::target_dir(d, &app.facts, &service, &app.install_env);
    let root = app.install_env.dir();
    let backup_dir = update_files::backup_dir(d, &root.join("backup"), &rel.tag);
    let paths = InstallPaths {
        target: &target,
        backup_dir: &backup_dir,
        download_dir: &root.join("downloads"),
    };
    // The confirmation copy the modal already showed; it belongs at the head of
    // the transcript so the log reads on its own afterwards.
    let mut log = Vec::new();
    let mut collect = |line: &str| {
        log.push(line.to_string());
        sink(line);
    };
    collect(&i18n::fmt(
        "upd.install.confirm",
        &[("s", &service), ("d", &backup_dir.display().to_string())],
    ));
    let result = inst::install(d, &rel, &service, &paths, &mut collect);

    // Files were replaced and the service was restarted either way, so every
    // cached fact is stale.
    app.facts.invalidate(None);
    let result = result?;

    Ok(InstallReport {
        replaced: result.replaced,
        added: result.added,
        downloaded: result.downloaded,
        build: result.build.or_else(|| installed_build(d, app)),
        log,
    })
}

/// Startup cleanup of stale download / backup directories. Never fails: a
/// cleanup problem must not stop the app from starting.
pub fn prune_update_dirs(d: &impl Deps, app: &App) -> Vec<String> {
    let root = app.install_env.dir();
    update_files::cleanup_stale_dirs(d, &root.join("downloads"), &root.join("backup"), PRUNE_KEEP)
}

// ---- helpers ---------------------------------------------------------------

fn require_service(app: &App) -> AppResult<&str> {
    app.selected().ok_or_else(|| AppError::new(AppErrorKind::NoSuchService, copy::t("msg.no.service")))
}

/// `true` when the form differs semantically from the service — the same
/// predicate [`FactsView::dirty`] uses, exposed so the frontend can check
/// before offering a Revert without building a whole snapshot.
pub fn is_dirty(d: &impl Deps, app: &App, values: &BTreeMap<String, String>) -> bool {
    let Some(service) = app.selected() else { return false };
    let fields = fields::fields();
    let text = params::build_params(values, &[], &fields);
    let current = svc::get_app_parameters(d, &app.facts, service);
    !params::semantically_equal(&text, &current, &fields)
}

/// The languages the settings page offers, as `(code, code)`.
pub fn languages() -> Vec<(String, String)> {
    Lang::ALL.map(|l| (l.code().to_string(), l.code().to_string())).to_vec()
}

/// 实测事务：服务在跑 → 停 → llama-bench → 按原状态恢复。
/// 失败路径尽力恢复服务，绝不静默留下停摆的服务。
pub fn bench_run(
    d: &impl Deps,
    app: &mut App,
    model_path: &std::path::Path,
    sink: &mut dyn FnMut(&str),
) -> AppResult<llama_ctl_core::market::BenchOutcome> {
    let service = app.selected().unwrap_or_default().to_string();
    let was_running =
        !service.is_empty() && svc::sc_query_state(d, &service) == svc::RUNNING_STATE;
    if was_running {
        sink("实测要独占显存：正在停止服务…");
        svc::sc_action(d, "stop", &service)
            .map_err(|e| AppError::new(AppErrorKind::Refused, format!("停止服务失败：{e}")))?;
    }
    let result = llama_ctl_core::market::bench::run(d, &app.install_env, model_path, sink);
    if was_running {
        sink("恢复服务…");
        if let Err(e) = svc::sc_action(d, "start", &service) {
            sink(&format!("服务恢复失败：{e}（请手动启动服务）"));
        } else {
            sink("服务已恢复");
        }
    }
    result
}
