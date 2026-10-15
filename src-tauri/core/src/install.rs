//! Official update install transaction (ticket 10).
//!
//! Rust port of `installer.py`: the one place that sequences an official
//! update. Python's entry point is
//! `install(rel, service, target, bak, sink, download_dir, deps=None)`; here
//! [`Deps`] replaces `deps`, the three directories travel together in
//! [`InstallPaths`], and `sink` is a `&mut dyn FnMut(&str)`.
//!
//! Terminology, per `CONTEXT.md`: this module owns **Rollback** — the failure
//! path that puts replaced files back from the Backup. It is *not* **Revert**,
//! which is the GUI discarding form edits and never touches a file.
//!
//! The transaction, and why each step sits where it does:
//!
//! 1. **download, then stop.** Stopping the service is the visible cost, so it
//!    happens only once every asset is known-good on disk. A download failure
//!    therefore leaves the service running, untouched.
//! 2. **Backup before replace.** [`backup_files`] aborts on its first failure,
//!    which is what makes "backup failed ⇒ nothing was replaced" true.
//! 3. **replace file by file**, recording what was overwritten (`replaced`) and
//!    what is new (`added`), so a failure can Rollback exactly those.
//! 4. **restart and confirm RUNNING.** Not reaching RUNNING is a failure like
//!    any other: Rollback, then restart.
//!
//! The rule that must not be broken: from the stop onwards, **every** failure
//! path ends with [`try_restart_service`]. This function never returns on a
//! failure while the service is left stopped in silence.
//!
//! Divergences from Python are recorded in `## Resolution` in
//! `.scratch/tauri2-migration/issues/10-installer-transaction.md`. The two
//! that shape the code:
//!
//! * **no sleeping.** `Deps` has no sleep, so every wait is a bounded spin on
//!   the injected clock ([`wait_poll`]) — with a ceiling, because a frozen test
//!   clock would otherwise hang forever. Same trick ticket 06 uses for backoff.
//! * **`sc_action` reports failure as `Err`, not `(False, msg)`.** `Deps::spawn`
//!   carries no exit code, so `sc stop`'s "already stopped" exit 1062 cannot be
//!   told apart from a real refusal; the follow-up state query does that job.

use std::path::{Path, PathBuf};

use crate::deps::{AppError, AppErrorKind, AppResult, Deps};
use crate::i18n::{fmt, t};
use crate::service::{FactsCache, RUNNING_STATE, app_directory, sc_action, sc_query_state};
use crate::updater::{Release, get_installed_build};
use crate::update_files::{
    DownloadOptions, backup_files, collect_conflicts, download_asset, extract_one, remove_files,
    restore_files, zip_top_files,
};

/// `sc query` state word of a service that is down.
pub const STOPPED_STATE: &str = "STOPPED";

/// The binary the update replaces and whose build number is reported.
pub const SERVER_EXE: &str = "llama-server.exe";

/// Sentinel the frontend watches for: the service changed, re-read its status.
/// Python put the same literal on the log queue.
pub const REFRESH_SENTINEL: &str = "__REFRESH_STATUS__";

/// Fallback replacement target (`LLAMA_DIR` in the GUI) when neither the
/// service nor [`LLAMA_DIR_ENV`] says where llama.cpp lives.
pub const DEFAULT_LLAMA_DIR: &str = r"F:\llama.cpp";

/// Environment override for that fallback (`LLAMA_CTL_LLAMA_DIR`).
pub const LLAMA_DIR_ENV: &str = "LLAMA_CTL_LLAMA_DIR";

/// Poll budgets, in `sc query` calls: 40 × 0.5 s for the stop, 120 × 0.5 s for
/// the main RUNNING wait, 40 × 0.5 s for the best-effort recovery — which is
/// deliberately *shorter* than the main wait (Python's failure path used to
/// stack two 60 s waits and read as a hang).
pub const STOP_POLLS: u32 = 40;
pub const RUNNING_POLLS: u32 = 120;
pub const RESTART_POLLS: u32 = 40;

/// One `sc query` per this many polls gets a progress line, so a long wait
/// cannot be mistaken for a hang.
const PROGRESS_EVERY: u32 = 12;

/// Milliseconds one poll waits for (Python's `time.sleep(0.5)`).
const POLL_INTERVAL_MILLIS: u64 = 500;

/// Ceiling on the spin that stands in for that sleep: a frozen test clock must
/// not turn a poll into an infinite loop. Deliberately the same budget ticket
/// 06 gave download backoff.
const MAX_SPINS_PER_POLL: u32 = 64;

/// Where an install reads and writes. `backup_dir` is one timestamped
/// directory, already derived by the caller via
/// [`crate::update_files::backup_dir`].
#[derive(Debug, Clone, Copy)]
pub struct InstallPaths<'a> {
    /// Directory whose files get replaced.
    pub target: &'a Path,
    /// This attempt's Backup directory.
    pub backup_dir: &'a Path,
    /// Download cache root; assets land in `<root>/<tag>/`.
    pub download_dir: &'a Path,
}

/// Environment the replacement target falls back to. Injectable because `Deps`
/// has no environment access (same gap ticket 04 and 07 recorded); persist.rs
/// uses the same shape for its own overrides.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct InstallEnv {
    /// `LLAMA_CTL_LLAMA_DIR`.
    pub llama_dir: Option<PathBuf>,
}

impl InstallEnv {
    /// The real process environment. An empty value counts as unset, matching
    /// Python's `os.environ.get(...) or ...`.
    pub fn from_process() -> Self {
        Self {
            llama_dir: std::env::var(LLAMA_DIR_ENV).ok().filter(|v| !v.is_empty()).map(PathBuf::from),
        }
    }

    /// The fallback directory: the override, else [`DEFAULT_LLAMA_DIR`].
    pub fn dir(&self) -> PathBuf {
        self.llama_dir.clone().filter(|p| !p.as_os_str().is_empty()).unwrap_or_else(|| PathBuf::from(DEFAULT_LLAMA_DIR))
    }
}

/// What one install did — enough for the caller to log a summary and for the
/// tests to assert on the transaction's shape.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct InstallResult {
    /// Files that existed and were overwritten. Rollback restores these.
    pub replaced: Vec<String>,
    /// Files the update added. Rollback deletes these.
    pub added: Vec<String>,
    /// Assets that had to be fetched (0 when everything was cached).
    pub downloaded: usize,
    /// Build number reported by the new binary; `None` = unknown.
    pub build: Option<u32>,
}

/// Derive the replacement target: the service's own install directory when it
/// holds the server binary, otherwise the environment override /
/// [`DEFAULT_LLAMA_DIR`].
///
/// `ponytail:` "holds the server binary" is a `read_file` of
/// `<AppDirectory>/llama-server.exe`, because `Deps` exposes no `is_dir` probe
/// (the gap ticket 06 recorded). It is also the precondition that actually
/// matters — a directory without the binary is not a target we can update —
/// and unlike `list_dir` it is decidable in both directions through the seam.
/// Ceiling gone the moment the seam grows an `is_dir`.
pub fn target_dir(d: &impl Deps, cache: &FactsCache, service: &str, env: &InstallEnv) -> PathBuf {
    if let Some(dir) = app_directory(d, cache, service)
        && !dir.is_empty()
        && d.read_file(&Path::new(&dir).join(SERVER_EXE)).is_ok()
    {
        return PathBuf::from(dir);
    }
    env.dir()
}

/// Run one official update install. Blocking; the caller owns the thread.
///
/// Returns [`InstallResult`] on success. On failure the transaction has already
/// Rolled back what it replaced and tried to restart the service, so the `Err`
/// is safe to show the user as-is.
pub fn install(
    d: &impl Deps,
    rel: &Release,
    service: &str,
    paths: &InstallPaths,
    sink: &mut dyn FnMut(&str),
) -> AppResult<InstallResult> {
    // 1) assets, into `<download_dir>/<tag>/`. Before the stop, so a network
    //    problem never costs the user a service restart.
    let dl_dir = paths.download_dir.join(&rel.tag);
    let mut local_zips: Vec<PathBuf> = Vec::new();
    let mut downloaded = 0usize;
    for asset in &rel.assets {
        let dest = dl_dir.join(&asset.name);
        // Python emits 0/25/50/75/100 rather than every percent, so the log
        // stays readable on a 400 MB asset.
        let mut last_pct: i64 = -1;
        let mut progress = |done: u64, total: u64| {
            let pct = if total == 0 {
                100
            } else {
                (done as u128 * 100 / total as u128) as i64
            };
            let step = pct / 25 * 25;
            if step == last_pct {
                return;
            }
            last_pct = step;
            sink(&fmt(
                "upd.downloading",
                &[("n", asset.name.as_str()), ("p", &step.to_string())],
            ));
        };
        let out = download_asset(d, &asset.url, &dest, &DownloadOptions::default(), Some(&mut progress))?;
        if out.cached {
            sink(&format!("  {} (cached)", asset.name));
        } else {
            downloaded += 1;
        }
        local_zips.push(out.path);
    }

    // 2) stop. Windows refuses to replace a mapped binary.
    if let Err(e) = stop_service(d, service, sink) {
        // A stop that failed may still have landed: never leave it stopped.
        try_restart_service(d, service, sink);
        return Err(e);
    }

    // 3) Back up what the replace would overwrite. Any failure from here on
    //    has to restore the service, so each branch below ends the same way.
    let conflicts = match collect_conflicts(d, &local_zips, paths.target) {
        Ok(names) => names,
        Err(e) => {
            let msg = fmt("upd.zip.bad", &[("e", &e.message)]);
            sink(&msg);
            try_restart_service(d, service, sink);
            return Err(AppError::new(AppErrorKind::UpdateFailed, msg));
        }
    };
    if conflicts.is_empty() {
        try_restart_service(d, service, sink);
        return Err(AppError::new(AppErrorKind::UpdateFailed, t("upd.no.files").to_string()));
    }
    sink(&fmt("upd.backing", &[("d", &paths.backup_dir.display().to_string())]));
    if let Err(e) = backup_files(d, &conflicts, paths.target, paths.backup_dir) {
        let msg = fmt("upd.backup.fail", &[("m", &e.message)]);
        sink(&msg);
        try_restart_service(d, service, sink);
        return Err(AppError::new(AppErrorKind::UpdateFailed, msg));
    }

    // 4) replace, file by file: what was there first, then what is new.
    sink(t("upd.extracting"));
    let mut sources: Vec<(String, PathBuf)> = Vec::new();
    for zp in &local_zips {
        let names = match zip_top_files(d, zp) {
            Ok(names) => names,
            Err(e) => {
                let msg = fmt("upd.zip.bad", &[("e", &e.message)]);
                sink(&msg);
                try_restart_service(d, service, sink);
                return Err(AppError::new(AppErrorKind::UpdateFailed, msg));
            }
        };
        for name in names {
            // Same name in several zips: last one wins, as Python's
            // "extract each zip in order" did.
            if let Some(slot) = sources.iter_mut().find(|(n, _)| *n == name) {
                slot.1 = zp.clone();
            } else {
                sources.push((name, zp.clone()));
            }
        }
    }
    let mut ordered: Vec<(String, PathBuf)> = Vec::new();
    for name in &conflicts {
        if let Some((_, zp)) = sources.iter().find(|(n, _)| n == name) {
            ordered.push((name.clone(), zp.clone()));
        }
    }
    for (name, zp) in &sources {
        if !conflicts.contains(name) {
            ordered.push((name.clone(), zp.clone()));
        }
    }

    let mut replaced: Vec<String> = Vec::new();
    let mut added: Vec<String> = Vec::new();
    for (name, zp) in &ordered {
        let existed = d.read_file(&paths.target.join(name)).is_ok();
        if let Err(e) = extract_one(d, zp, paths.target, name) {
            sink(&fmt("upd.extract.fail", &[("e", &e.message)]));
            rollback(d, &replaced, &added, paths, sink);
            try_restart_service(d, service, sink);
            return Err(e);
        }
        if existed {
            replaced.push(name.clone());
        } else {
            added.push(name.clone());
        }
    }
    sink(REFRESH_SENTINEL);

    // 5) restart and confirm. Not RUNNING means the new binary is bad, so it
    //    is a failure like any other — Rollback, then restart.
    sink(&fmt("upd.starting", &[("s", service)]));
    if let Err(e) = sc_action(d, "start", service) {
        let msg = fmt("upd.start.fail", &[("m", &e.to_string())]);
        sink(&msg);
        rollback(d, &replaced, &added, paths, sink);
        try_restart_service(d, service, sink);
        return Err(AppError::new(AppErrorKind::UpdateFailed, msg));
    }
    if !wait_for_running(d, service, sink) {
        let msg = fmt("upd.not.running", &[("s", service)]);
        sink(&msg);
        rollback(d, &replaced, &added, paths, sink);
        try_restart_service(d, service, sink);
        return Err(AppError::new(AppErrorKind::UpdateFailed, msg));
    }

    let build = get_installed_build(d, &paths.target.join(SERVER_EXE));
    let label = match build {
        Some(b) => format!("b{b}"),
        None => "?".to_string(),
    };
    sink(&fmt("upd.done", &[("s", service), ("b", &label)]));
    Ok(InstallResult { replaced, added, downloaded, build })
}

// ---- steps ----

/// Stop `service` and wait for `STOPPED`; already stopped is a no-op.
fn stop_service(d: &impl Deps, service: &str, sink: &mut dyn FnMut(&str)) -> AppResult<()> {
    sink(&fmt("upd.stopping", &[("s", service)]));
    if sc_query_state(d, service) != STOPPED_STATE {
        // `sc stop` on a stopped service exits non-zero, so the follow-up
        // query — not the action's result — decides whether it worked.
        if let Err(e) = sc_action(d, "stop", service)
            && sc_query_state(d, service) != STOPPED_STATE
        {
            return Err(AppError::new(
                AppErrorKind::UpdateFailed,
                fmt("upd.stop.fail", &[("m", &e.to_string())]),
            ));
        }
    }
    if !wait_for(d, service, STOPPED_STATE, STOP_POLLS) {
        return Err(AppError::new(
            AppErrorKind::UpdateFailed,
            fmt("upd.stop.fail", &[("m", "timeout")]),
        ));
    }
    sink(t("upd.stopped"));
    Ok(())
}

/// Best-effort recovery on the way out of a failure: start the service *if it
/// is stopped* and wait briefly. Never fails, never reports — one line of
/// progress and out, because the caller's own error is what the user reads.
///
/// Python's `_try_restart_service`, minus its blanket `except`: nothing here
/// can raise.
fn try_restart_service(d: &impl Deps, service: &str, sink: &mut dyn FnMut(&str)) {
    if sc_query_state(d, service) != STOPPED_STATE {
        return;
    }
    sink(&fmt("upd.starting", &[("s", service)]));
    let _ = sc_action(d, "start", service);
    let _ = wait_for(d, service, RUNNING_STATE, RESTART_POLLS);
}

/// Undo a partial replace: put [`InstallResult::replaced`] back from the
/// Backup, delete what was added. Never fails — a Rollback that itself fails
/// only logs, because the service restart that follows matters more.
fn rollback(
    d: &impl Deps,
    replaced: &[String],
    added: &[String],
    paths: &InstallPaths,
    sink: &mut dyn FnMut(&str),
) {
    if replaced.is_empty() && added.is_empty() {
        return;
    }
    sink(t("upd.rollback"));
    if !replaced.is_empty() {
        match restore_files(d, replaced, paths.target, paths.backup_dir) {
            Ok(_) => sink(t("upd.rollback.done")),
            Err(e) => sink(&fmt(
                "upd.rollback.fail",
                &[("e", &e.message), ("d", &paths.backup_dir.display().to_string())],
            )),
        }
    }
    if !added.is_empty()
        && let Err(e) = remove_files(d, added, paths.target) {
            sink(&fmt(
                "upd.rollback.fail",
                &[("e", &e.message), ("d", &paths.target.display().to_string())],
            ));
        }
}

// ---- waiting ----

fn wait_for(d: &impl Deps, service: &str, wanted: &str, polls: u32) -> bool {
    for _ in 0..polls {
        if sc_query_state(d, service) == wanted {
            return true;
        }
        wait_poll(d);
    }
    sc_query_state(d, service) == wanted
}

/// [`wait_for`] for RUNNING, reporting progress every ~6 s. Silent waiting
/// here is what used to read as a hang: the modal is gone and the button grey
/// by then, so the user cannot tell "working" from "stuck".
fn wait_for_running(d: &impl Deps, service: &str, sink: &mut dyn FnMut(&str)) -> bool {
    for tick in 0..RUNNING_POLLS {
        if sc_query_state(d, service) == RUNNING_STATE {
            return true;
        }
        if tick > 0 && tick % PROGRESS_EVERY == 0 {
            sink(&fmt("upd.wait.running", &[("s", &(tick / 2).to_string())]));
        }
        wait_poll(d);
    }
    sc_query_state(d, service) == RUNNING_STATE
}

/// Wait one poll interval on the injected clock.
///
/// `ponytail:` `Deps` has no sleep, so this is a spin with a ceiling — with a
/// frozen clock (every test) it degenerates into `MAX_SPINS_PER_POLL` no-ops
/// instead of hanging. A real clock advances and the wait is the 0.5 s Python
/// slept; ticket 06 uses the same trick for download backoff.
fn wait_poll(d: &impl Deps) {
    let deadline = d.now_millis().saturating_add(POLL_INTERVAL_MILLIS);
    let mut spins = 0;
    while d.now_millis() < deadline && spins < MAX_SPINS_PER_POLL {
        spins += 1;
    }
}
