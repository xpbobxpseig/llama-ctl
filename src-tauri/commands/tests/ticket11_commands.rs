//! Ticket 11 acceptance: the command layer is exercisable with `FakeDeps`.
//!
//! These are behaviour tests over the IPC surface, not unit tests of internals:
//! every case drives one or more real commands through the injected seam and
//! asserts on the snapshot / error that comes back. Nothing here touches the
//! OS — `FakeDeps` answers registry reads, `nssm`, `sc`, powershell and HTTP.
//!
//! The acceptance criteria map onto cases as:
//!
//! - "the snapshot carries everything one screen needs" -> [`a_snapshot_carries_the_whole_screen`]
//! - "structured errors the frontend can render" -> [`a_write_back_failure_is_a_structured_error`],
//!   [`every_failure_crosses_ipc_as_a_typed_error`]
//! - "long operations stream progress" -> [`a_restart_streams_progress_line_by_line`],
//!   [`install_update_streams_the_whole_transaction_and_reports_what_changed`]
//! - "the frontend never owns authoritative state" -> [`loading_a_preset_fills_the_form_and_touches_nothing_else`]
//! - "the seam from ticket 01 still holds" -> the whole file: every call takes
//!   `&impl Deps`, and [`Sc`] is a second `Deps` implementation written here.

use std::cell::Cell;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use llama_ctl_commands::fields;
use llama_ctl_commands::ipc::{self, ErrorPayload, OkPayload};
use llama_ctl_commands::snapshot::{
    self as cmd, App, apply, check_update, delete_preset, installed_build,
    install_update, load_preset, prune_update_dirs, refresh_services, restart, revert,
    save_preset, save_settings, service_action, set_start_mode, snapshot, switch_service,
};
use llama_ctl_core::deps::{HttpBody, AppErrorKind, Deps, DepsError, DepsErrorKind, RegHive};
use llama_ctl_core::fake::{Call, FakeDeps};
use llama_ctl_core::install::{InstallEnv, STOPPED_STATE};
use llama_ctl_core::params::{build_params, semantically_equal};
use llama_ctl_core::persist::{Env, Settings};
use llama_ctl_core::service::{NSSM_EXE, RUNNING_STATE, UNKNOWN_STATE};
use llama_ctl_core::updater::{RELEASES_BASE, RELEASES_PAGE};
use llama_ctl_core::update_files::zip_bytes;

// ---- fixtures --------------------------------------------------------------

const SERVICE: &str = "QwenLLM";
const OTHER: &str = "OtherLLM";
const DIR: &str = r"F:\llama.cpp";

fn params_key(service: &str) -> String {
    format!(r"SYSTEM\CurrentControlSet\Services\{service}\Parameters")
}
fn service_key(service: &str) -> String {
    format!(r"SYSTEM\CurrentControlSet\Services\{service}")
}

fn home() -> PathBuf {
    PathBuf::from(r"C:\Users\me\AppData\Roaming")
}
fn settings_file() -> PathBuf {
    home().join("llama-ctl").join("settings.json")
}
fn presets_file() -> PathBuf {
    home().join("llama-ctl").join("presets.json")
}
fn env() -> Env {
    Env { appdata: Some(home().to_string_lossy().into_owned()), ..Env::default() }
}

/// A fake with two NSSM services holding parameter sets, a health probe that
/// answers, and `sc` / powershell scripted.
///
/// The clock advances on every call: auto-backup names carry a timestamp, and
/// `save_preset` is deliberately a no-op for an existing name, so two cases
/// sharing one clock would collide and only the first backup would be written.
fn world(app_params: &str) -> FakeDeps {
    static TICK: AtomicU64 = AtomicU64::new(0);
    let tick = TICK.fetch_add(1, Ordering::Relaxed);
    let now = 1_700_000_000_000 + tick * 1000;
    FakeDeps::new()
        .with_reg_string(&params_key(SERVICE), "AppDirectory", Some(DIR.to_string()))
        .with_reg_string(&params_key(SERVICE), "AppParameters", Some(app_params.to_string()))
        .with_reg_dword(&service_key(SERVICE), "Start", Some(2))
        .with_reg_string(&params_key(OTHER), "AppDirectory", Some(DIR.to_string()))
        .with_reg_string(&params_key(OTHER), "AppParameters", Some("--ctx-size 8192".to_string()))
        .with_reg_dword(&service_key(OTHER), "Start", Some(3))
        .with_spawn("powershell.exe", Ok(format!("{SERVICE}\r\n{OTHER}\r\n").into_bytes()))
        .with_health("127.0.0.1", 8080, true)
        .with_now(now)
}

/// Boot the app the way the tauri layer does: settings (including the cached
/// service list) live on "disk", `App::new` reads them.
fn boot(d: &impl Deps, services: &[&str]) -> App {
    let settings = Settings {
        services: services.iter().map(|s| s.to_string()).collect(),
        ..Settings::default()
    };
    llama_ctl_core::persist::save_settings(d, &env(), &settings).unwrap();
    App::new(d, env(), InstallEnv { llama_dir: Some(PathBuf::from(DIR)) })
}

/// Both services known, `QwenLLM` selected.
fn boot_app(d: &impl Deps) -> App {
    let mut a2 = boot(d, &[SERVICE, OTHER]);
    a2.select(SERVICE);
    a2
}


/// `sc` is the one program whose answer has to change over time: `query`
/// reports the current state while `stop` / `start` move it. `FakeDeps` scripts
/// one answer per program, so this wrapper delegates everything to it (the call
/// log stays complete) and scripts `sc` on top.
struct Sc<'a> {
    inner: &'a FakeDeps,
    state: Cell<&'static str>,
    /// `sc start` returns success even when the service dies immediately — the
    /// real shape of "started but never RUNNING".
    start_sets_running: bool,
}

impl<'a> Sc<'a> {
    fn new(inner: &'a FakeDeps, state: &'static str) -> Self {
        Self { inner, state: Cell::new(state), start_sets_running: true }
    }
    fn never_running(mut self) -> Self {
        self.start_sets_running = false;
        self
    }
}

fn state_line(state: &str) -> Vec<u8> {
    let code = if state == RUNNING_STATE { 4 } else { 1 };
    format!("        STATE              : {code}  {state}\r\n").into_bytes()
}

impl Deps for Sc<'_> {
    fn spawn(&self, program: &str, args: &[&str]) -> Result<Vec<u8>, DepsError> {
        let recorded = self.inner.spawn(program, args);
        if program != "sc" {
            return recorded;
        }
        match args {
            ["query", _] => Ok(state_line(self.state.get())),
            ["stop", _] => {
                self.state.set(STOPPED_STATE);
                Ok(b"[SC] StopService SUCCESS".to_vec())
            }
            ["start", _] => {
                if self.start_sets_running {
                    self.state.set(RUNNING_STATE);
                }
                Ok(b"[SC] StartService SUCCESS".to_vec())
            }
            _ => recorded,
        }
    }
    fn reg_read_dword(&self, hive: RegHive, path: &str, value: &str) -> Result<Option<u32>, DepsError> {
        self.inner.reg_read_dword(hive, path, value)
    }
    fn reg_read_string(
        &self,
        hive: RegHive,
        path: &str,
        value: &str,
    ) -> Result<Option<String>, DepsError> {
        self.inner.reg_read_string(hive, path, value)
    }
    fn read_file(&self, path: &Path) -> Result<Vec<u8>, DepsError> {
        self.inner.read_file(path)
    }
    fn write_file(&self, path: &Path, contents: &[u8]) -> Result<(), DepsError> {
        self.inner.write_file(path, contents)
    }
    fn rename_file(&self, from: &Path, to: &Path) -> Result<(), DepsError> {
        self.inner.rename_file(from, to)
    }
    fn remove_file(&self, path: &Path) -> Result<(), DepsError> {
        self.inner.remove_file(path)
    }
    fn list_dir(&self, path: &Path) -> Result<Vec<llama_ctl_core::deps::DirEntry>, DepsError> {
        self.inner.list_dir(path)
    }
    fn create_dir_all(&self, path: &Path) -> Result<(), DepsError> {
        self.inner.create_dir_all(path)
    }
    fn http_get(&self, url: &str) -> Result<HttpBody, DepsError> {
        self.inner.http_get(url)
    }
    fn probe_health(&self, host: &str, port: u16) -> Result<bool, DepsError> {
        self.inner.probe_health(host, port)
    }
    fn now_millis(&self) -> u64 {
        self.inner.now_millis()
    }
}

/// The parameters the fixture service holds — deliberately *not* in canonical
/// form, so the tests exercise real normalisation.
fn app_params() -> &'static str {
    "-m F:\\models\\qwen.gguf --ctx-size 131072 --host 127.0.0.1 --port 8080"
}

fn values(pairs: &[(&str, &str)]) -> BTreeMap<String, String> {
    pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect()
}

/// The form as the frontend would hold it: the service's own parsed values,
/// with `overrides` applied on top. Starting from the snapshot is the only
/// honest starting point — a hand-written sparse form would smuggle in
/// different defaults (e.g. `jinja` ships ON, so an empty form means "off").
fn form_of(d: &impl Deps, app: &App, overrides: &[(&str, &str)]) -> BTreeMap<String, String> {
    let mut out = snapshot(d, app, None).values;
    for (k, v) in overrides {
        out.insert(k.to_string(), v.to_string());
    }
    out
}

fn nssm_set_calls(d: &FakeDeps) -> usize {
    d.calls()
        .iter()
        .filter(|c| {
            matches!(c, Call::Spawn { program, args }
                if program == NSSM_EXE && args.first().map(String::as_str) == Some("set"))
        })
        .count()
}

fn has(lines: &[String], needle: &str) -> bool {
    lines.iter().any(|l| l.contains(needle))
}

// ---- the snapshot ----------------------------------------------------------

#[test]
fn a_snapshot_carries_the_whole_screen() {
    let d = world(app_params());
    let sc = Sc::new(&d, RUNNING_STATE);
    let app = boot_app(&d);

    let s = snapshot(&sc, &app, None);

    // One fetch: services, selection, facts, status, form values, presets,
    // settings, variants and the string table. No second call needed.
    assert_eq!(s.services, vec![SERVICE, OTHER]);
    assert_eq!(s.selected, SERVICE);
    let facts = s.facts.as_ref().expect("facts");
    assert_eq!(facts.app_dir.as_deref(), Some(DIR));
    assert_eq!(facts.app_params, app_params());
    assert_eq!(facts.start, llama_ctl_core::service::StartMode::Auto);
    assert_eq!(s.status.state, RUNNING_STATE);
    assert!(s.status.ok, "RUNNING plus a healthy probe");
    assert_eq!(s.values.get("ctx_size").map(String::as_str), Some("131072"));
    assert_eq!(s.values.get("model").map(String::as_str), Some(r"F:\models\qwen.gguf"));
    assert!(s.extras.is_empty());
    assert!(s.warnings.is_empty());
    assert!(s.settings.upd_check_on_startup);
    assert_eq!(s.channels.len(), 4);
    // The whole string table for the active language, not a key to go fetch.
    assert_eq!(s.strings.get("app.title").map(String::as_str), Some("llama.cpp 服务控制台"));
    assert!(s.strings.len() > 50, "the frontend renders from this table: {}", s.strings.len());
    assert_eq!(s.lang, "zh");
}

#[test]
fn reading_a_service_facts_never_spawns_nssm() {
    // Ticket 04's headline criterion has to survive at this layer too: facts
    // come from the registry, not from `nssm get`.
    let d = world(app_params());
    let sc = Sc::new(&d, RUNNING_STATE);
    let app = boot_app(&d);

    let s = snapshot(&sc, &app, None);

    assert!(
        !d.calls().iter().any(|c| matches!(c, Call::Spawn { program, .. } if program == NSSM_EXE)),
        "facts must not spawn a child process"
    );
    assert_eq!(s.facts.as_ref().unwrap().app_params, app_params());
}

#[test]
fn a_snapshot_without_a_service_renders_an_empty_state_not_a_blank_window() {
    let d = FakeDeps::new();
    let app = boot(&d, &[]);

    let s = snapshot(&d, &app, None);

    assert_eq!(s.selected, "");
    assert!(s.facts.is_none());
    assert_eq!(s.status.state, UNKNOWN_STATE);
    assert!(s.values.values().all(String::is_empty));
}

#[test]
fn the_form_is_dirty_only_when_it_differs_semantically() {
    let d = world(app_params());
    let sc = Sc::new(&d, RUNNING_STATE);
    let app = boot_app(&d);

    // The service's own values, handed straight back: no prompt.
    let untouched = form_of(&sc, &app, &[]);
    let clean = snapshot(&sc, &app, Some(&untouched));
    assert!(!clean.facts.as_ref().unwrap().dirty, "the form equals the service");

    // A real value change must show up — that is what gates Revert and the
    // "unapplied changes" dot.
    let edited = form_of(&sc, &app, &[("ctx_size", "32768")]);
    let dirty = snapshot(&sc, &app, Some(&edited));
    assert!(dirty.facts.as_ref().unwrap().dirty);
    assert!(cmd::is_dirty(&sc, &app, &edited));
    assert!(!cmd::is_dirty(&sc, &app, &untouched));
}

#[test]
fn an_alias_only_rewrite_is_not_reported_as_a_change() {
    // The reason `dirty` is semantic: a hand-written `-c` where this tool
    // writes `--ctx-size` is not a difference the user should be nagged about.
    let d = world("-c 131072 --host 127.0.0.1 --port 8080");
    let sc = Sc::new(&d, STOPPED_STATE);
    let app = boot_app(&d);

    let s = snapshot(&sc, &app, None);
    assert!(!s.facts.as_ref().unwrap().dirty, "the parsed form is the service's own values");
    assert_eq!(s.values.get("ctx_size").map(String::as_str), Some("131072"));
}

// ---- apply / revert: the two comparisons -----------------------------------

#[test]
fn apply_writes_back_through_nssm_and_reports_what_it_did() {
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);
    let changed = form_of(&sc, &app, &[("ctx_size", "32768")]);

    let done = apply(&sc, &mut app, &changed, &[]).unwrap();

    assert!(done.written);
    assert!(!done.needs_restart, "a stopped service needs no restart");
    assert_eq!(nssm_set_calls(&d), 1, "exactly one write-back");
    assert_eq!(done.snapshot.selected, SERVICE);
}

#[test]
fn apply_is_textual_so_a_semantically_equal_legacy_form_is_still_normalised() {
    // CONTEXT.md: Apply's own no-change test is textual, because Apply *is* the
    // normalisation pass. A legacy `-c 4096 --ctx-size 131072` is semantically
    // equal to its own parsed form, and must still be rewritten.
    let legacy = "-c 4096 --ctx-size 131072";
    let d = world(legacy);
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);

    let parsed = snapshot(&sc, &app, None).values;
    let rebuilt = build_params(&parsed, &[], &fields::fields());
    assert!(semantically_equal(&rebuilt, legacy, &fields::fields()), "same meaning");
    assert_ne!(rebuilt, legacy, "different text — so Apply must write");

    let done = apply(&sc, &mut app, &parsed, &[]).unwrap();
    assert!(done.written, "the textual difference is exactly why Apply writes");
}

#[test]
fn apply_reports_no_change_when_the_service_text_is_already_canonical() {
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let app = boot_app(&d);
    let parsed = snapshot(&sc, &app, None).values;

    // A service whose AppParameters this tool already wrote: same text round.
    let canon = build_params(&parsed, &[], &fields::fields());
    let d = world(&canon);
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);

    let done = apply(&sc, &mut app, &parsed, &[]).unwrap();

    assert!(!done.written, "identical text -> nothing to write");
    assert_eq!(nssm_set_calls(&d), 0, "an unchanged form must not touch the service");
}

#[test]
fn a_running_service_reports_that_it_still_needs_a_restart() {
    let d = world(app_params());
    let sc = Sc::new(&d, RUNNING_STATE);
    let mut app = boot_app(&d);
    let changed = form_of(&sc, &app, &[("ctx_size", "32768")]);

    let done = apply(&sc, &mut app, &changed, &[]).unwrap();

    assert!(done.needs_restart, "stored but not in effect until restarted");
}

#[test]
fn a_write_back_failure_is_a_structured_error() {
    let d = world(app_params()).with_spawn(
        NSSM_EXE,
        Err(DepsError::new(DepsErrorKind::SpawnFailed, "nssm.exe 不可用")),
    );
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);
    let changed = form_of(&sc, &app, &[("ctx_size", "32768")]);

    let err = apply(&sc, &mut app, &changed, &[]).unwrap_err();

    assert_eq!(err.kind, AppErrorKind::Refused);
    assert!(err.message.contains("nssm.exe 不可用"), "{}", err.message);
}

#[test]
fn revert_re_reads_the_service_and_never_writes() {
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);
    let edited = form_of(&sc, &app, &[("ctx_size", "32768")]);
    assert!(snapshot(&sc, &app, Some(&edited)).facts.as_ref().unwrap().dirty);

    let s = revert(&sc, &mut app).unwrap();

    assert!(!s.facts.as_ref().unwrap().dirty, "the form is back to the service's values");
    assert_eq!(s.values.get("ctx_size").map(String::as_str), Some("131072"));
    // Revert itself reads; what it must not do is write. The reads it performs
    // (settings, the service's registry values, `sc query`) are the snapshot's
    // own, and Revert adds no write of any kind.
    let before = d.calls().len();
    let _ = revert(&sc, &mut app).unwrap();
    let spent = &d.calls()[before..];
    assert!(
        !spent.iter().any(|c| matches!(c, Call::WriteFile(_))) && nssm_set_calls(&d) == 0,
        "Revert touches nothing: {spent:?}"
    );
}

// ---- service control -------------------------------------------------------

#[test]
fn start_and_stop_go_through_sc() {
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);

    let s = service_action(&sc, &mut app, "start").unwrap();
    assert_eq!(s.selected, SERVICE);
    assert!(d.calls().iter().any(|c| matches!(
        c,
        Call::Spawn { program, args } if program == "sc" && args == &["start", SERVICE]
    )));

    let _ = service_action(&sc, &mut app, "stop").unwrap();
    assert!(d.calls().iter().any(|c| matches!(
        c,
        Call::Spawn { program, args } if program == "sc" && args == &["stop", SERVICE]
    )));
}

#[test]
fn an_action_other_than_start_or_stop_is_refused() {
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);
    let err = service_action(&sc, &mut app, "delete").unwrap_err();
    assert_eq!(err.kind, AppErrorKind::Refused);
}

#[test]
fn the_start_mode_switch_writes_through_nssm() {
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);
    // The registry says `auto`, so the snapshot after the switch shows `manual`
    // only if the fact cache was dropped — which `core` does on success only.
    let _ = set_start_mode(&sc, &mut app, llama_ctl_core::service::StartMode::Manual).unwrap();

    assert!(
        d.calls().iter().any(|c| matches!(
            c,
            Call::Spawn { program, args }
                if program == NSSM_EXE
                    && args.first().map(String::as_str) == Some("set")
                    && args.get(2).map(String::as_str) == Some("Start")
                    && args.get(3).map(String::as_str) == Some("SERVICE_DEMAND_START")
        )),
        "nssm set Start SERVICE_DEMAND_START was issued"
    );
}

#[test]
fn a_restart_streams_progress_line_by_line() {
    // The ticket's explicit requirement: a long operation must not block
    // silently. The sink is what the frontend renders.
    let d = world(app_params());
    let sc = Sc::new(&d, RUNNING_STATE);
    let mut app = boot_app(&d);
    let form = snapshot(&sc, &app, None).values;

    // `i18n`'s language is a process-global (one process serves one UI), so
    // these assertions use the language-independent parts: the step order and
    // the count. Asserting on the Chinese wording would make every other test
    // in the binary order-dependent.
    let mut lines = Vec::new();
    let s = restart(&sc, &mut app, &form, &mut |l| lines.push(l.to_string())).unwrap();

    assert_eq!(s.status.state, RUNNING_STATE);
    assert!(s.status.ok, "the health probe answered");
    assert!(lines.len() >= 3, "one line per step, not one line at the end: {lines:?}");
    assert!(!lines[0].is_empty() && !lines[1].is_empty(), "each step emits a line: {lines:?}");
    assert!(
        d.calls().iter().any(|c| matches!(c, Call::Spawn { program, args }
            if program == "sc" && args == &["stop", SERVICE])),
        "it stopped the service first"
    );
    assert!(
        d.calls().iter().any(|c| matches!(c, Call::Spawn { program, args }
            if program == "sc" && args == &["start", SERVICE])),
        "then started it"
    );
}

#[test]
fn a_restart_of_an_already_stopped_service_skips_the_stop() {
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);
    let form = snapshot(&sc, &app, None).values;

    let mut lines = Vec::new();
    let _ = restart(&sc, &mut app, &form, &mut |l| lines.push(l.to_string())).unwrap();

    let stops = d
        .calls()
        .iter()
        .filter(|c| {
            matches!(c, Call::Spawn { program, args }
                if program == "sc" && args.first().map(String::as_str) == Some("stop"))
        })
        .count();
    assert_eq!(stops, 0, "a stopped service is started, not stopped again");
    // Same reason as above: assert on the call, not on the wording.
    assert!(!lines.is_empty(), "it still reports the step it took: {lines:?}");
}

#[test]
fn a_restart_that_never_becomes_ready_says_so_instead_of_streaming_silence() {
    // `sc start` succeeds but the service never gets up: that must end with a
    // line the user can read, not with a minute of nothing.
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE).never_running();
    let mut app = boot_app(&d);
    let form = snapshot(&sc, &app, None).values;

    let mut lines = Vec::new();
    let s = restart(&sc, &mut app, &form, &mut |l| lines.push(l.to_string())).unwrap();

    assert!(!s.status.ok);
    // Language-independent, same reason as the two cases above: the give-up
    // line is the last one, and it is not a step line.
    assert!(lines.len() >= 3, "it reports the wait rather than staying silent: {lines:?}");
    assert!(!lines.last().unwrap().is_empty(), "{lines:?}");
}

// ---- switching services ----------------------------------------------------

#[test]
fn switching_clears_the_preset_the_form_came_from() {
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);
    let form = snapshot(&sc, &app, None).values;
    save_preset(&sc, &mut app, "whatever", &form).unwrap();
    load_preset(&sc, &mut app, "whatever").unwrap();

    let s = switch_service(&sc, &mut app, OTHER, None, false).unwrap();

    assert_eq!(s.selected, OTHER);
    assert_eq!(s.preset_loaded, "", "the form gets refilled from the new service");
    assert_eq!(s.values.get("ctx_size").map(String::as_str), Some("8192"));
}

#[test]
fn an_unknown_service_is_a_refusal_not_an_empty_form() {
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);

    let err = switch_service(&sc, &mut app, "NoSuchService", None, false).unwrap_err();

    assert_eq!(err.kind, AppErrorKind::NoSuchService);
    assert!(err.message.contains("NoSuchService"), "{}", err.message);
    assert_eq!(app.selected(), Some(SERVICE), "the selection is unchanged");
}

#[test]
fn switching_with_unapplied_changes_makes_a_timestamped_auto_backup() {
    // CONTEXT.md: an Auto backup is a *preset* with a timestamped name — not
    // the file Backup an update makes.
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);
    let edited = form_of(&sc, &app, &[("ctx_size", "32768")]);

    let _ = switch_service(&sc, &mut app, OTHER, Some(&edited), true).unwrap();

    let presets = llama_ctl_core::persist::load_presets(&sc, &env());
    let name = presets.keys().find(|n| n.contains("自动备份")).cloned().expect("an auto backup");
    assert!(name.contains(':'), "the name carries a timestamp: {name}");
    assert_eq!(presets[&name].get("ctx_size").map(String::as_str), Some("32768"));
}

#[test]
fn switching_an_unchanged_form_backs_up_nothing() {
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);
    let untouched = snapshot(&sc, &app, None).values;

    let _ = switch_service(&sc, &mut app, OTHER, Some(&untouched), true).unwrap();

    assert!(llama_ctl_core::persist::load_presets(&sc, &env()).is_empty());
}

#[test]
fn refresh_services_enumerates_and_persists_the_list() {
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot(&sc, &[]);

    let s = refresh_services(&sc, &mut app).unwrap();

    assert_eq!(s.services, vec![SERVICE, OTHER]);
    let on_disk = llama_ctl_core::persist::load_settings(&sc, &env());
    assert_eq!(on_disk.services, vec![SERVICE, OTHER]);
    assert!(d.file(&settings_file()).is_some(), "the list was written for the next startup");
}

// ---- presets ---------------------------------------------------------------

#[test]
fn save_list_and_delete_a_preset() {
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);
    let form = snapshot(&sc, &app, None).values;

    assert!(save_preset(&sc, &mut app, "long-context", &form).unwrap());
    assert_eq!(snapshot(&sc, &app, None).presets, vec!["long-context"]);

    // An existing name is a no-op, not an overwrite.
    assert!(!save_preset(&sc, &mut app, "long-context", &values(&[("ctx_size", "1")])).unwrap());
    assert_eq!(
        llama_ctl_core::persist::load_presets(&sc, &env())["long-context"]
            .get("ctx_size")
            .map(String::as_str),
        Some("131072"),
        "the existing preset was not clobbered"
    );

    assert!(delete_preset(&sc, &mut app, "long-context").unwrap());
    assert!(!delete_preset(&sc, &mut app, "long-context").unwrap());
}

#[test]
fn an_empty_preset_name_is_refused() {
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);
    let err = save_preset(&sc, &mut app, "  ", &values(&[])).unwrap_err();
    assert_eq!(err.kind, AppErrorKind::Refused);
}

#[test]
fn loading_a_preset_fills_the_form_and_touches_nothing_else() {
    // CONTEXT.md: loading a Preset is safe — it fills the form and nothing
    // else. The frontend still has to Apply.
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);
    let form = snapshot(&sc, &app, None).values;
    save_preset(&sc, &mut app, "long-context", &form).unwrap();
    let before = d.calls().len();

    let s = load_preset(&sc, &mut app, "long-context").unwrap();

    assert_eq!(s.values.get("ctx_size").map(String::as_str), Some("131072"));
    assert_eq!(s.preset_loaded, "long-context");
    assert!(!s.facts.as_ref().unwrap().dirty, "these are the service's own values");
    // The reads the snapshot needs (settings, the service's registry values,
    // `sc query`) are all reads; what must not appear is any write or any
    // `nssm set` — loading never reconfigures the service.
    let spent = &d.calls()[before..];
    assert!(
        !spent.iter().any(|c| matches!(c, Call::WriteFile(_))) && nssm_set_calls(&d) == 0,
        "loading must not write anything: {spent:?}"
    );
    assert!(
        spent.iter().any(|c| matches!(c, Call::ReadFile(p) if p == &presets_file())),
        "it did read the preset file: {spent:?}"
    );
}

#[test]
fn loading_an_unknown_preset_is_a_refusal() {
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);
    let err = load_preset(&sc, &mut app, "nope").unwrap_err();
    assert_eq!(err.kind, AppErrorKind::NoSuchService);
    assert!(err.message.contains("nope"), "{}", err.message);
}

#[test]
fn applying_a_preset_loaded_form_keeps_that_preset_in_sync() {
    // Story 28: a successful Apply overwrites the preset the form came from, so
    // the preset cannot drift from what is actually running.
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);
    let form = snapshot(&sc, &app, None).values;
    save_preset(&sc, &mut app, "long-context", &form).unwrap();

    let changed = form_of(&sc, &app, &[("ctx_size", "32768")]);
    let done = apply(&sc, &mut app, &changed, &[]).unwrap();

    assert_eq!(done.preset_synced, "long-context");
    assert_eq!(
        llama_ctl_core::persist::load_presets(&sc, &env())["long-context"]
            .get("ctx_size")
            .map(String::as_str),
        Some("32768")
    );
}

#[test]
fn applying_a_form_that_came_from_the_service_writes_no_preset() {
    // The mirror image, and the one that protects user data: a fresh start with
    // an auto-selected dropdown name must not overwrite that preset with values
    // that actually came from the service.
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    {
        let mut first = boot_app(&sc);
        save_preset(&sc, &mut first, "long-context", &values(&[("ctx_size", "1")])).unwrap();
    }
    let mut app = boot_app(&sc); // a fresh start: preset_loaded is empty
    let changed = form_of(&sc, &app, &[("ctx_size", "32768")]);

    let done = apply(&sc, &mut app, &changed, &[]).unwrap();

    assert_eq!(done.preset_synced, "");
    assert_eq!(
        llama_ctl_core::persist::load_presets(&sc, &env())["long-context"]
            .get("ctx_size")
            .map(String::as_str),
        Some("1"),
        "a preset the form did not come from is never written"
    );
}

#[test]
fn deleting_the_loaded_preset_stops_the_form_from_writing_it_back() {
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);
    let form = snapshot(&sc, &app, None).values;
    save_preset(&sc, &mut app, "gone", &form).unwrap();

    assert!(delete_preset(&sc, &mut app, "gone").unwrap());
    let done = apply(&sc, &mut app, &form, &[]).unwrap();

    assert_eq!(done.preset_synced, "");
    assert!(llama_ctl_core::persist::load_presets(&sc, &env()).is_empty());
}

// ---- settings --------------------------------------------------------------

#[test]
fn switching_the_language_comes_back_with_that_languages_table() {
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);
    let mut settings = snapshot(&sc, &app, None).settings;
    settings.language = "en".to_string();

    let s = save_settings(&sc, &mut app, &settings).unwrap();

    assert_eq!(s.lang, "en");
    assert_eq!(s.strings.get("app.title").map(String::as_str), Some("llama.cpp Service Console"));
    assert_eq!(
        llama_ctl_core::persist::load_settings(&sc, &env()).language,
        "en",
    );
    // `i18n` keeps the language in a process-global, so put it back: leaving
    // `en` behind would change the wording every later test in this binary
    // sees (they run in parallel threads).
    llama_ctl_core::i18n::set_language(llama_ctl_core::i18n::Lang::Zh);
}

#[test]
fn a_retired_build_variant_is_folded_onto_the_default_when_saved() {
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);
    let settings = Settings {
        upd_channel: "win-cuda-13.3-x64".to_string(),
        ..Settings::default()
    };

    let s = save_settings(&sc, &mut app, &settings).unwrap();

    assert_eq!(s.settings.upd_channel, "win-cuda-13.4-x64");
}

// ---- updates ---------------------------------------------------------------

const TAG: &str = "b11213";

fn releases_page(tag: &str) -> String {
    format!(
        r#"<html><body>
        <a href="/ggml-org/llama.cpp/releases/tag/{tag}">{tag}</a>
        </body></html>"#
    )
}

fn assets_page(tag: &str, variant: &str, build: u32) -> String {
    format!(
        r#"<html><body>
        <a href="/ggml-org/llama.cpp/releases/download/{tag}/llama-b{build}-bin-{variant}.zip">zip</a>
        </body></html>"#
    )
}

/// A world where an official update is available and downloadable.
fn update_world(zip: Vec<u8>) -> FakeDeps {
    let zip_path = PathBuf::from(DIR)
        .join("downloads")
        .join(TAG)
        .join("llama-b11213-bin-win-cuda-13.4-x64.zip");
    world(app_params())
        // The installed binaries the update will replace.
        .with_file(Path::new(DIR).join("llama-server.exe"), b"OLDBIN".to_vec())
        .with_file(Path::new(DIR).join("ggml.dll"), b"OLDDLL".to_vec())
        .with_http(RELEASES_PAGE, Ok(releases_page(TAG).into_bytes()))
        .with_http(
            &format!("{RELEASES_BASE}expanded_assets/{TAG}"),
            Ok(assets_page(TAG, "win-cuda-13.4-x64", 11213).into_bytes()),
        )
        .with_file(&zip_path, zip)
        // `llama-server --version` on the *old* binary.
        .with_spawn(
            &PathBuf::from(DIR).join("llama-server.exe").to_string_lossy(),
            Ok(b"version: 0.4.0-dev (build 10813, commit 4acf4a4cb)".to_vec()),
        )
}

#[test]
fn check_update_reports_the_newest_release_and_whether_we_are_behind() {
    let d = update_world(zip_bytes(&[("llama-server.exe", b"NEWBIN")]));
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);

    let check = check_update(&sc, &mut app).unwrap();

    let rel = check.release.expect("a release");
    assert_eq!(rel.tag, TAG);
    assert_eq!(rel.build, 11213);
    assert_eq!(check.installed, Some(10813));
    assert!(!check.up_to_date);
}

#[test]
fn check_update_never_installs_anything() {
    // ADR-0001 / story 52: a check only notifies.
    let d = update_world(zip_bytes(&[("llama-server.exe", b"NEWBIN")]));
    let sc = Sc::new(&d, RUNNING_STATE);
    let mut app = boot_app(&d);

    let before = d.calls().len();
    let _ = check_update(&sc, &mut app).unwrap();

    // Look-ups and a version probe, never a stop and never a write: the check
    // only reports.
    let spent = &d.calls()[before..];
    assert!(!spent.iter().any(|c| matches!(
        c,
        Call::Spawn { program, args } if program == "sc" && args.first().map(String::as_str) == Some("stop")
    )));
    assert!(!spent.iter().any(|c| matches!(c, Call::WriteFile(_))), "{spent:?}");
}

#[test]
fn install_update_streams_the_whole_transaction_and_reports_what_changed() {
    let d = update_world(zip_bytes(&[
        ("llama-server.exe", b"NEWBIN"),
        ("ggml.dll", b"NEWDLL"),
    ]));
    let sc = Sc::new(&d, RUNNING_STATE);
    let mut app = boot_app(&d);
    check_update(&sc, &mut app).unwrap();

    let mut lines = Vec::new();
    let report = install_update(&sc, &mut app, &mut |l| lines.push(l.to_string())).unwrap();

    assert_eq!(report.replaced, vec!["ggml.dll", "llama-server.exe"]);
    assert!(report.added.is_empty());
    assert!(has(&report.log, "备份"), "{:?}", report.log);
    assert!(has(&report.log, "解压"), "{:?}", report.log);
    assert!(report.log.len() >= 4, "one line per step: {:?}", report.log);
    assert_eq!(lines, report.log, "the frontend got every line the report kept");
}

#[test]
fn install_update_without_a_check_is_refused() {
    let d = update_world(zip_bytes(&[("llama-server.exe", b"NEWBIN")]));
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);

    let err = install_update(&sc, &mut app, &mut |_| {}).unwrap_err();

    // The user must never install a version they were not shown the changelog
    // for.
    assert_eq!(err.kind, AppErrorKind::UpdateFailed);
}

#[test]
fn changing_the_build_variant_after_a_check_invalidates_the_install() {
    let d = update_world(zip_bytes(&[("llama-server.exe", b"NEWBIN")]));
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);
    check_update(&sc, &mut app).unwrap();

    let mut settings = snapshot(&sc, &app, None).settings;
    settings.upd_channel = "win-cpu-x64".to_string();
    save_settings(&sc, &mut app, &settings).unwrap();

    let err = install_update(&sc, &mut app, &mut |_| {}).unwrap_err();
    assert_eq!(err.kind, AppErrorKind::UpdateFailed);
}

#[test]
fn the_installed_build_comes_from_the_service_own_directory() {
    let d = update_world(zip_bytes(&[("llama-server.exe", b"NEWBIN")]));
    let sc = Sc::new(&d, STOPPED_STATE);
    let app = boot_app(&d);
    assert_eq!(installed_build(&sc, &app), Some(10813));
}

#[test]
fn pruning_stale_update_dirs_never_fails() {
    // A cleanup problem must not stop the app from starting, so this returns
    // names rather than a Result.
    let d = FakeDeps::new();
    let app = App::new(&d, env(), InstallEnv { llama_dir: Some(PathBuf::from(DIR)) });

    assert!(prune_update_dirs(&d, &app).is_empty(), "an unreadable tree is simply skipped");
}

// ---- the IPC envelope ------------------------------------------------------

#[test]
fn every_failure_crosses_ipc_as_a_typed_error() {
    // The frontend renders `kind` + `message` directly; it must never have to
    // parse a string to decide what happened.
    let d = world(app_params());
    let sc = Sc::new(&d, STOPPED_STATE);
    let mut app = boot_app(&d);

    let result = switch_service(&sc, &mut app, "NoSuchService", None, false);
    let err: ErrorPayload = ipc::envelope(result).unwrap_err();

    assert!(!err.ok);
    assert_eq!(err.kind(), "NoSuchService");
    assert!(err.error.message.contains("NoSuchService"));
    // And the whole envelope survives serde, which is what actually crosses.
    let json = serde_json::to_string(&err).unwrap();
    let back: ErrorPayload = serde_json::from_str(&json).unwrap();
    assert_eq!(back, err);
}

#[test]
fn a_snapshot_crosses_ipc_without_losing_a_field() {
    let d = world(app_params());
    let sc = Sc::new(&d, RUNNING_STATE);
    let app = boot_app(&d);

    let payload: OkPayload = ipc::envelope(Ok(snapshot(&sc, &app, None))).unwrap();
    let json = serde_json::to_string(&payload).unwrap();

    assert!(json.contains("\"ok\":true"));
    for field in [
        "services",
        "selected",
        "facts",
        "status",
        "values",
        "extras",
        "warnings",
        "preset_loaded",
        "presets",
        "settings",
        "channels",
        "strings",
        "lang",
    ] {
        assert!(json.contains(&format!("\"{field}\"")), "{field} missing from the wire");
    }
    // The frontend consumes the same names it will hard-code in TS.
    let value: serde_json::Value = serde_json::from_str(&json).unwrap();
    let data = &value["data"];
    assert_eq!(data["selected"], SERVICE);
    assert_eq!(data["facts"]["start"], "auto");
    assert_eq!(data["status"]["state"], "RUNNING");
    assert_eq!(data["strings"]["app.title"], "llama.cpp 服务控制台");
}

// ---- the field table -------------------------------------------------------

#[test]
fn the_field_table_is_internally_consistent() {
    // The domain parses with this table and the form renders from it; a
    // duplicate key or a shared alias would silently drop a parameter.
    assert_eq!(fields::validate(), Vec::<String>::new());
    assert!(fields::fields().iter().any(|f| f.key == "ctx_size"));
    assert!(fields::is_slider("ngl"));
    assert!(!fields::is_slider("model"));
    assert_eq!(fields::group_of("ctx_size"), Some("上下文与显存"));
    assert!(fields::options_of("flash_attn").contains(&"auto"));
    assert!(fields::options_of("model").is_empty(), "a text field has no options");
}

#[test]
fn the_field_table_parses_and_rebuilds_a_real_parameter_string() {
    // Ticket 03 pinned the round trip for a 9-field table; the real 29-field
    // one must behave the same way for the fields a service actually uses.
    let text = "-m F:\\models\\qwen.gguf -ngl 99 --ctx-size 131072 --port 8080 --no-jinja";
    let fs = fields::fields();
    let (values, extras, warnings) = llama_ctl_core::params::parse_params(text, &fs);

    assert_eq!(values.get("model").map(String::as_str), Some(r"F:\models\qwen.gguf"));
    assert_eq!(values.get("ngl").map(String::as_str), Some("99"), "the alias -ngl maps to ngl");
    assert_eq!(values.get("ctx_size").map(String::as_str), Some("131072"));
    assert_eq!(values.get("jinja").map(String::as_str), Some(""), "--no-jinja turns it off");
    assert!(extras.is_empty(), "everything is a known field: {extras:?}");
    assert!(warnings.is_empty());

    let rebuilt = build_params(&values, &extras, &fs);
    assert!(semantically_equal(&rebuilt, text, &fs), "{rebuilt}");
    assert!(rebuilt.contains("--no-jinja"), "the negation is emitted explicitly: {rebuilt}");
}

// ---- the first-frame dropdown ----------------------------------------------
//
// Ported from tests/test_first_paint.py: the order the dropdown shows on the
// very first frame, before any enumeration has happened.

#[test]
fn an_empty_cache_shows_only_the_current_service() {
    assert_eq!(cmd::first_paint_services("Svc", &[]), vec!["Svc".to_string()]);
}

#[test]
fn a_cache_hit_keeps_the_cached_order() {
    let cached = ["A".to_string(), "B".to_string(), "C".to_string()];
    assert_eq!(cmd::first_paint_services("B", &cached), cached);
}

#[test]
fn a_cache_miss_prepends_the_current_service() {
    // Newly installed, or renamed while we were away: the current service must
    // appear rather than the dropdown painting a form for nothing.
    let cached = ["A".to_string(), "B".to_string()];
    assert_eq!(
        cmd::first_paint_services("Z", &cached),
        vec!["Z".to_string(), "A".to_string(), "B".to_string()]
    );
}

#[test]
fn empty_entries_are_dropped_from_the_cached_list() {
    let cached = ["".to_string(), "A".to_string(), "".to_string()];
    assert_eq!(
        cmd::first_paint_services("Svc", &cached),
        vec!["Svc".to_string(), "A".to_string()]
    );
}
