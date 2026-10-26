//! Ticket 10 acceptance: the official-update install transaction.
//!
//! Ported from `tests/test_installer.py`. The whole run is offline and
//! service-free: the "disk" is `FakeDeps::with_file`, the network is
//! `with_http`, one failing write is `with_failing_write`, and `sc` is a
//! wrapper that scripts the service state machine.
//!
//! The load-bearing assertions are the ones about what a failure *undoes*
//! (Rollback) and about never leaving the service stopped. Note the glossary:
//! **Rollback** here is this failure path; **Revert** is an unrelated GUI
//! action (discarding form edits) and appears nowhere in this module.

use std::cell::Cell;
use std::path::{Path, PathBuf};

use llama_ctl_core::deps::{HttpBody, HttpStream, AppErrorKind, AppResult, Deps, DepsError, DepsErrorKind, DirEntry, RegHive};
use llama_ctl_core::fake::{Call, FakeDeps};
use llama_ctl_core::install::{
    DEFAULT_LLAMA_DIR, InstallEnv, InstallPaths, InstallResult, REFRESH_SENTINEL, STOPPED_STATE,
    install, target_dir,
};
use llama_ctl_core::service::{FactsCache, RUNNING_STATE};
use llama_ctl_core::updater::{Asset, Release};
use llama_ctl_core::update_files::zip_bytes;

const SERVICE: &str = "QwenLLM";
const URL: &str = "https://github.com/ggml-org/llama.cpp/releases/download/b4583/main.zip";
const TAG: &str = "b4583";

fn target() -> PathBuf {
    PathBuf::from(r"D:\llama.cpp")
}
fn backup() -> PathBuf {
    PathBuf::from(r"F:\llama_ctl\backup\b4583\20231114_221320")
}
fn downloads() -> PathBuf {
    PathBuf::from(r"F:\llama_ctl\downloads")
}
fn asset_path() -> PathBuf {
    downloads().join(TAG).join("main.zip")
}
fn exe() -> String {
    target().join("llama-server.exe").to_string_lossy().into_owned()
}

fn release() -> Release {
    Release {
        tag: TAG.to_string(),
        name: TAG.to_string(),
        html_url: String::new(),
        body: String::new(),
        build: 4583,
        published_at: String::new(),
        assets: vec![Asset { name: "main.zip".to_string(), url: URL.to_string() }],
    }
}

/// The update package: the server binary plus one dll that is new to the
/// target directory.
fn zip() -> Vec<u8> {
    zip_bytes(&[("llama-server.exe", b"NEWBIN".as_slice()), ("ggml.dll", b"NEWDLL".as_slice())])
}

fn zip_with(extra: &[(&str, &[u8])]) -> Vec<u8> {
    let mut entries: Vec<(&str, &[u8])> = vec![("llama-server.exe", b"NEWBIN")];
    entries.extend_from_slice(extra);
    zip_bytes(&entries)
}

// ---- the sc wrapper ----

/// `sc` is the one program whose answer has to change over time: `query`
/// reports the current state, `stop` / `start` move it. `FakeDeps` scripts one
/// answer per program, so this wrapper delegates *everything* to it (the call
/// log stays complete) and scripts `sc` on top.
struct ScriptedSc<'a> {
    inner: &'a FakeDeps,
    state: Cell<&'static str>,
    stop_works: bool,
    start_succeeds: bool,
    /// `sc start` returns success even when the service crashes immediately —
    /// the real shape of "started but never RUNNING".
    start_sets_running: bool,
}

impl ScriptedSc<'_> {
    fn new<'a>(inner: &'a FakeDeps, state: &'static str) -> ScriptedSc<'a> {
        ScriptedSc {
            inner,
            state: Cell::new(state),
            stop_works: true,
            start_succeeds: true,
            start_sets_running: true,
        }
    }
    fn stop_fails(mut self) -> Self {
        self.stop_works = false;
        self
    }
    fn start_fails(mut self) -> Self {
        self.start_succeeds = false;
        self
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

impl Deps for ScriptedSc<'_> {
    fn http_request(&self, method: &str, url: &str, body: Option<&str>) -> Result<Vec<u8>, DepsError> {
        self.inner.http_request(method, url, body)
    }
    fn spawn_split(&self, program: &str, args: &[&str]) -> Result<(Vec<u8>, Vec<u8>), DepsError> {
        self.inner.spawn_split(program, args)
    }
    fn http_open_range(&self, url: &str, range_from: u64) -> Result<HttpStream, DepsError> {
        self.inner.http_open_range(url, range_from)
    }
    fn append_file(&self, path: &Path, bytes: &[u8]) -> Result<(), DepsError> {
        self.inner.append_file(path, bytes)
    }
    fn file_size(&self, path: &Path) -> Result<Option<u64>, DepsError> {
        self.inner.file_size(path)
    }
    fn hash_file(&self, path: &Path) -> Result<String, DepsError> {
        self.inner.hash_file(path)
    }
    fn disk_free(&self, path: &Path) -> Result<Option<u64>, DepsError> {
        self.inner.disk_free(path)
    }
    /// Records through the inner fake, then answers `sc` itself.
    fn spawn(&self, program: &str, args: &[&str]) -> Result<Vec<u8>, DepsError> {
        let recorded = self.inner.spawn(program, args);
        if program != "sc" {
            return recorded;
        }
        match args {
            ["query", _] => Ok(state_line(self.state.get())),
            ["stop", _] => {
                if self.stop_works {
                    self.state.set(STOPPED_STATE);
                    Ok(b"[SC] StopService SUCCESS".to_vec())
                } else {
                    Err(DepsError::new(DepsErrorKind::NonZeroExit, "access denied"))
                }
            }
            ["start", _] => {
                if !self.start_succeeds {
                    return Err(DepsError::new(DepsErrorKind::NonZeroExit, "access denied"));
                }
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
    fn list_dir(&self, path: &Path) -> Result<Vec<DirEntry>, DepsError> {
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

// ---- helpers ----

/// A target directory holding the old server binary, plus a fetchable zip.
fn base() -> FakeDeps {
    FakeDeps::new()
        .with_file(target().join("llama-server.exe"), b"OLDBIN".to_vec())
        .with_http(URL, Ok(zip()))
        // `llama-server --version` reports the freshly installed build.
        .with_spawn(&exe(), Ok(b"version: 0.4.0-dev (build 4583, commit 4acf4a4cb)".to_vec()))
}

/// Run one install through the scripted `sc` and collect the log lines.
fn run(sc: &ScriptedSc<'_>, rel: &Release) -> (AppResult<InstallResult>, Vec<String>) {
    let target_path = target();
    let bak = backup();
    let dl = downloads();
    let paths = InstallPaths { target: &target_path, backup_dir: &bak, download_dir: &dl };
    let mut lines: Vec<String> = Vec::new();
    let out = install(sc, rel, SERVICE, &paths, &mut |s| lines.push(s.to_string()));
    (out, lines)
}

/// Run an install with a default `sc` script, starting from `state`.
fn go(d: &FakeDeps, state: &'static str) -> (AppResult<InstallResult>, Vec<String>) {
    let sc = ScriptedSc::new(d, state);
    run(&sc, &release())
}

fn sc_verb(d: &FakeDeps, verb: &str) -> bool {
    d.calls().iter().any(|c| matches!(c, Call::Spawn { program, args } if program == "sc" && args.first().map(String::as_str) == Some(verb)))
}

/// Writes that landed inside `dir` — i.e. "was anything replaced / backed up".
fn writes_under(d: &FakeDeps, dir: &Path) -> Vec<PathBuf> {
    d.calls()
        .iter()
        .filter_map(|c| match c {
            Call::WriteFile(p) if p.starts_with(dir) => Some(p.clone()),
            _ => None,
        })
        .collect()
}

fn has(lines: &[String], needle: &str) -> bool {
    lines.iter().any(|l| l.contains(needle))
}

// ---- happy path ----

#[test]
fn the_happy_path_stops_backs_up_replaces_and_restarts() {
    let d = base();
    let (out, lines) = go(&d, RUNNING_STATE);

    let res = out.expect("the happy path must succeed");
    assert_eq!(res.replaced, vec!["llama-server.exe".to_string()]);
    assert_eq!(res.added, vec!["ggml.dll".to_string()]);
    assert_eq!(res.downloaded, 1);

    // Stop first, then start: the transaction bookends the replace.
    assert!(sc_verb(&d, "stop"), "the service must be stopped before the replace");
    assert!(sc_verb(&d, "start"), "the service must be restarted after it");
    // Backed up before anything was written into the target.
    assert!(!writes_under(&d, &backup()).is_empty(), "the old files must be backed up");
    assert!(!writes_under(&d, &target()).is_empty());

    assert_eq!(d.file(&target().join("llama-server.exe")).as_deref(), Some(b"NEWBIN".as_slice()));
    assert_eq!(d.file(&target().join("ggml.dll")).as_deref(), Some(b"NEWDLL".as_slice()));
    // The Backup still holds the old bytes, so a later Rollback has something
    // to restore.
    assert_eq!(d.file(&backup().join("llama-server.exe")).as_deref(), Some(b"OLDBIN".as_slice()));

    assert!(lines.iter().any(|l| l == REFRESH_SENTINEL), "the frontend must be told to re-read status");
    assert!(has(&lines, "更新完成"), "a completion line is emitted: {lines:?}");
    assert!(has(&lines, "b4583"), "the new build is reported: {lines:?}");
}

#[test]
fn progress_is_emitted_step_by_step() {
    let d = base();
    let (_, lines) = go(&d, RUNNING_STATE);

    for step in ["停止服务", "服务已停止", "备份旧文件到", "解压替换二进制", "重启服务", "更新完成"] {
        assert!(has(&lines, step), "missing progress line {step}: {lines:?}");
    }
    // Order matters: the frontend shows these as they arrive.
    let at = |n: &str| lines.iter().position(|l| l.contains(n)).unwrap_or(usize::MAX);
    assert!(at("停止服务") < at("备份旧文件到"), "stop precedes backup");
    assert!(at("备份旧文件到") < at("解压替换二进制"), "backup precedes replace");
    assert!(at("解压替换二进制") < at("重启服务"), "replace precedes restart");
}

#[test]
fn a_cached_asset_is_reused_without_a_request() {
    let d = FakeDeps::new()
        .with_file(target().join("llama-server.exe"), b"OLDBIN".to_vec())
        .with_file(asset_path(), zip())
        .with_spawn(&exe(), Ok(b"build 4583".to_vec()));

    let (out, lines) = go(&d, STOPPED_STATE);

    assert_eq!(out.unwrap().downloaded, 0, "a valid cache must not be re-fetched");
    assert!(!d.calls().iter().any(|c| matches!(c, Call::HttpGet(_))), "no request for a good cache");
    assert!(has(&lines, "(cached)"), "the cache hit is visible: {lines:?}");
}

#[test]
fn an_already_stopped_service_is_not_stopped_again() {
    let d = base();
    go(&d, STOPPED_STATE).0.expect("already stopped must still succeed");
    assert!(!sc_verb(&d, "stop"), "no stop when it is already down");
    assert!(sc_verb(&d, "start"));
}

// ---- Rollback ----

#[test]
fn a_mid_replace_write_failure_rolls_back_the_files_already_replaced() {
    // llama-server.exe is replaced first (it is the conflict); the write of
    // ggml.dll then fails.
    let d = base().with_failing_write(target().join("ggml.dll.llama_ctl_new"));
    let (out, lines) = go(&d, STOPPED_STATE);

    let err = out.expect_err("a failed replace must fail the install");
    assert_eq!(err.kind, AppErrorKind::UpdateFailed);
    assert!(has(&lines, "解压替换失败"), "the failure is reported: {lines:?}");
    assert!(has(&lines, "回滚"), "the Rollback is reported: {lines:?}");

    // The replaced file is back to its old bytes...
    assert_eq!(
        d.file(&target().join("llama-server.exe")).as_deref(),
        Some(b"OLDBIN".as_slice()),
        "the already-replaced file must be Rolled back"
    );
    // ...and the file the failure was about was never half-written.
    assert_eq!(d.file(&target().join("ggml.dll")), None);
    assert!(d.file(&target().join("ggml.dll.llama_ctl_new")).is_none(), "no temp file may linger");
}

#[test]
fn rollback_deletes_the_files_the_update_added() {
    // ordered = [llama-server.exe (conflict), a.dll (new), b.dll (new)];
    // b.dll's write fails, so llama-server.exe is restored and a.dll deleted.
    let d = FakeDeps::new()
        .with_file(target().join("llama-server.exe"), b"OLDBIN".to_vec())
        .with_http(URL, Ok(zip_with(&[("a.dll", b"NEWA"), ("b.dll", b"NEWB")])))
        .with_failing_write(target().join("b.dll.llama_ctl_new"));

    let out = go(&d, STOPPED_STATE).0;
    assert!(out.is_err());

    assert_eq!(d.file(&target().join("llama-server.exe")).as_deref(), Some(b"OLDBIN".as_slice()));
    assert_eq!(d.file(&target().join("a.dll")), None, "an added file must be removed by the Rollback");
    assert_eq!(d.file(&target().join("b.dll")), None);
}

#[test]
fn a_rollback_that_itself_fails_only_logs() {
    // The restore write is refused (a mapped dll, say): the transaction must
    // still finish its cleanup and restart rather than panic.
    let d = base()
        .with_failing_write(target().join("ggml.dll.llama_ctl_new"))
        .with_failing_write(target().join("llama-server.exe.llama_ctl_old"));

    let (out, lines) = go(&d, STOPPED_STATE);

    assert!(out.is_err());
    assert!(has(&lines, "回滚失败"), "a failed Rollback is logged, not swallowed: {lines:?}");
    assert!(sc_verb(&d, "start"), "the service is still restarted");
}

#[test]
fn the_service_is_never_left_stopped_after_a_failure() {
    // Every failure after the stop must try to bring the service back up.
    let d = base().with_failing_write(target().join("ggml.dll.llama_ctl_new"));
    go(&d, RUNNING_STATE).0.expect_err("this install fails");
    assert!(sc_verb(&d, "start"), "failure cleanup must attempt a restart");
}

// ---- abort before anything is replaced ----

#[test]
fn a_backup_failure_aborts_with_nothing_replaced() {
    let d = base().with_failing_write(backup().join("llama-server.exe.llama_ctl_new"));
    let (out, lines) = go(&d, STOPPED_STATE);

    assert_eq!(out.expect_err("a failed Backup must abort").kind, AppErrorKind::UpdateFailed);
    assert!(has(&lines, "备份旧文件失败"), "the abort is reported: {lines:?}");
    assert_eq!(
        d.file(&target().join("llama-server.exe")).as_deref(),
        Some(b"OLDBIN".as_slice()),
        "nothing may be replaced when the Backup failed"
    );
    assert!(writes_under(&d, &target()).is_empty(), "no write into the target at all");
    assert!(sc_verb(&d, "start"), "and the service is brought back up");
}

#[test]
fn a_download_failure_aborts_before_the_service_is_touched() {
    // No `with_http`: the fetch fails. Nothing about the service should happen.
    let d = FakeDeps::new().with_file(target().join("llama-server.exe"), b"OLDBIN".to_vec());
    let (out, _) = go(&d, RUNNING_STATE);

    assert!(out.is_err());
    assert_eq!(d.spawn_count(), 0, "a download failure must not stop the service");
    assert!(writes_under(&d, &backup()).is_empty());
    assert_eq!(d.file(&target().join("llama-server.exe")).as_deref(), Some(b"OLDBIN".as_slice()));
}

#[test]
fn a_stop_failure_aborts_before_the_backup() {
    let d = base();
    let sc = ScriptedSc::new(&d, RUNNING_STATE).stop_fails();
    let (out, _lines) = run(&sc, &release());

    let err = out.expect_err("a failed stop must abort");
    assert_eq!(err.kind, AppErrorKind::UpdateFailed);
    assert!(err.message.contains("停止服务失败"), "the stop failure is the error: {err:?}");
    assert!(writes_under(&d, &backup()).is_empty(), "no Backup after a failed stop");
    assert!(writes_under(&d, &target()).is_empty(), "no replace after a failed stop");
}

#[test]
fn a_package_that_matches_nothing_aborts_and_restarts() {
    // The zip holds no file the target has: nothing to replace.
    let d = FakeDeps::new()
        .with_file(target().join("llama-server.exe"), b"OLDBIN".to_vec())
        .with_http(URL, Ok(zip_bytes(&[("unrelated.dll", b"X")])));
    let (out, _) = go(&d, STOPPED_STATE);

    let err = out.expect_err("a package that matches nothing must abort");
    assert_eq!(err.kind, AppErrorKind::UpdateFailed);
    assert!(err.message.contains("没有需要替换的文件"), "the mismatch is the error: {err:?}");
    assert!(writes_under(&d, &target()).is_empty(), "nothing is replaced");
    assert!(sc_verb(&d, "start"), "the service is restarted");
}

// ---- restart ----

#[test]
fn a_start_that_fails_rolls_back_and_tries_to_recover() {
    let d = base();
    let sc = ScriptedSc::new(&d, RUNNING_STATE).start_fails();
    let (out, lines) = run(&sc, &release());

    assert!(out.expect_err("a failed start must fail the install").kind == AppErrorKind::UpdateFailed);
    assert!(has(&lines, "启动服务失败"), "the failure is reported: {lines:?}");
    // The new binary was already on disk — leaving it there with a stopped
    // service is exactly what this path exists to prevent.
    assert_eq!(d.file(&target().join("llama-server.exe")).as_deref(), Some(b"OLDBIN".as_slice()));
    assert_eq!(d.file(&target().join("ggml.dll")), None);
    assert!(
        d.calls()
            .iter()
            .filter(|c| matches!(c, Call::Spawn { program, args } if program == "sc" && args.first().map(String::as_str) == Some("start")))
            .count()
            >= 2,
        "the restart is attempted again on the way out"
    );
}

#[test]
fn a_service_that_never_reaches_running_rolls_back() {
    let d = base();
    let sc = ScriptedSc::new(&d, RUNNING_STATE).never_running();
    let (out, lines) = run(&sc, &release());

    assert!(out.expect_err("never RUNNING is a failure").kind == AppErrorKind::UpdateFailed);
    assert!(has(&lines, "未进入 RUNNING"), "the failure is reported: {lines:?}");
    assert_eq!(d.file(&target().join("llama-server.exe")).as_deref(), Some(b"OLDBIN".as_slice()));
    assert_eq!(d.file(&target().join("ggml.dll")), None);
}

#[test]
fn waiting_for_running_reports_progress_instead_of_hanging_silently() {
    // The modal is gone and the button grey by then, so a silent 60 s wait is
    // indistinguishable from a hang.
    let d = base();
    let sc = ScriptedSc::new(&d, RUNNING_STATE).never_running();
    let (_, lines) = run(&sc, &release());

    assert!(has(&lines, "等待服务进入 RUNNING"), "the wait must report progress: {lines:?}");
}

#[test]
fn an_unknown_installed_build_still_completes() {
    // `llama-server --version` prints nothing parseable: the update itself is
    // fine, only the reported version is unknown.
    let d = FakeDeps::new()
        .with_file(target().join("llama-server.exe"), b"OLDBIN".to_vec())
        .with_http(URL, Ok(zip()));

    let (out, lines) = go(&d, STOPPED_STATE);

    assert_eq!(out.expect("an unreadable version must not fail the update").build, None);
    assert!(has(&lines, "更新完成"), "completion is still reported: {lines:?}");
}

// ---- target derivation ----

fn params_key(service: &str) -> String {
    format!(r"SYSTEM\CurrentControlSet\Services\{service}\Parameters")
}

#[test]
fn the_target_comes_from_the_service_install_directory() {
    let d = FakeDeps::new()
        .with_reg_string(&params_key(SERVICE), "AppDirectory", Some(r"D:\llama.cpp".to_string()))
        .with_reg_string(&params_key(SERVICE), "AppParameters", Some("-m a.gguf".to_string()))
        .with_file(target().join("llama-server.exe"), b"OLD".to_vec());

    let dir = target_dir(&d, &FactsCache::new(), SERVICE, &InstallEnv::default());
    assert_eq!(dir, target(), "AppDirectory wins when it holds the server binary");
}

#[test]
fn an_install_directory_without_the_binary_falls_back_to_the_environment() {
    let d = FakeDeps::new()
        .with_reg_string(&params_key(SERVICE), "AppDirectory", Some(r"D:\empty".to_string()))
        .with_reg_string(&params_key(SERVICE), "AppParameters", Some("-m a.gguf".to_string()));
    let env = InstallEnv { llama_dir: Some(PathBuf::from(r"E:\other")) };

    assert_eq!(target_dir(&d, &FactsCache::new(), SERVICE, &env), PathBuf::from(r"E:\other"));
}

#[test]
fn with_no_service_and_no_environment_the_builtin_default_wins() {
    let d = FakeDeps::new();
    assert_eq!(target_dir(&d, &FactsCache::new(), SERVICE, &InstallEnv::default()), PathBuf::from(DEFAULT_LLAMA_DIR));
}
