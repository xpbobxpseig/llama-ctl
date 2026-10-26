//! Ticket 06 acceptance: download integrity, zip validation, atomic replace,
//! Backup/restore, stale-directory cleanup.
//!
//! Ported from the file half of `tests/test_updater.py`. Everything runs
//! offline: bodies come from `FakeDeps::with_http`, the "disk" from
//! `with_file` / `with_dir`, and failures from `with_failing_write`.
//!
//! Two behaviours are regressions rather than features and are covered first:
//! a cached-but-corrupt zip must not be reused (`dc45c77`), and a failed
//! replacement must leave the previous file byte-identical.
use std::cell::Cell;
use std::path::{Path, PathBuf};
use llama_ctl_core::deps::{HttpBody, HttpStream, AppErrorKind, Deps, DepsError, DepsErrorKind, DirEntry, RegHive};
use llama_ctl_core::fake::{Call, FakeDeps};
use llama_ctl_core::update_files::{
    DownloadOptions, PART_SUFFIX, PRUNE_KEEP, backup_dir, backup_files, cleanup_stale_dirs,
    collect_conflicts, download_asset, extract_one, extract_top_level, is_valid_zip,
    is_valid_zip_bytes, prune_nested_subdirs, prune_old_subdirs, remove_files, restore_files,
    timestamp, zip_bytes, zip_top_files,
};

const URL: &str = "https://github.com/ggml-org/llama.cpp/releases/download/b11213/main.zip";

fn dest(name: &str) -> PathBuf {
    PathBuf::from(format!(r"F:\llama_ctl\downloads\b11213\{name}"))
}

/// A zip whose entries are stored (not deflated), so a test can corrupt the
/// payload in place — exactly the shape of the measured failure.
fn good_zip() -> Vec<u8> {
    zip_bytes(&[("llama-server.exe", b"BIN".as_slice()), ("ggml.dll", b"DLL".as_slice())])
}

fn corrupt_payload(zip: &[u8], payload: &[u8]) -> Vec<u8> {
    // Stored payloads are literal in the file, so the bytes can be found.
    let at = zip.windows(payload.len()).position(|w| w == payload).expect("payload present");
    let mut out = zip.to_vec();
    out[at..at + payload.len()].fill(0);
    out
}

fn one_shot() -> DownloadOptions {
    DownloadOptions { attempts: 1, backoff_millis: 0, max_backoff_millis: 0 }
}

// ---- zip validity ----

#[test]
fn a_real_zip_is_valid() {
    let d = FakeDeps::new().with_file(dest("main.zip"), good_zip());
    assert!(is_valid_zip(&d, &dest("main.zip")));
}

#[test]
fn a_truncated_zip_is_not_valid() {
    let zip = good_zip();
    let d = FakeDeps::new().with_file(dest("t.zip"), zip[..zip.len() / 3].to_vec());
    assert!(!is_valid_zip(&d, &dest("t.zip")));
}

#[test]
fn a_zip_with_zeroed_entry_data_is_not_valid() {
    // The measured failure: length and central directory are intact — only
    // reading every entry and checking its CRC catches it.
    let zip = good_zip();
    let corrupt = corrupt_payload(&zip, b"BIN");
    assert_eq!(corrupt.len(), zip.len(), "the corruption must not change the length");

    assert!(!is_valid_zip_bytes(&corrupt));
    assert!(is_valid_zip_bytes(&zip), "the uncorrupted original must still pass");
}

#[test]
fn validation_never_panics_on_junk_or_missing_files() {
    assert!(!is_valid_zip_bytes(b""));
    assert!(!is_valid_zip_bytes(b"not a zip at all"));
    assert!(!is_valid_zip(&FakeDeps::new(), &dest("missing.zip")));
}

#[test]
fn zip_top_files_ignores_dirs_and_nested_paths() {
    let d = FakeDeps::new().with_file(
        dest("a.zip"),
        zip_bytes(&[("llama-server.exe", b"B"), ("ggml.dll", b"D"), ("sub/deep.dll", b"X")]),
    );
    assert_eq!(zip_top_files(&d, &dest("a.zip")).unwrap(), vec!["ggml.dll", "llama-server.exe"]);
}

// ---- download: the dc45c77 regression ----

#[test]
fn a_cached_but_corrupt_zip_is_not_reused() {
    // The bug: `dest` existing was taken as "already downloaded". A truncated
    // download then made every future attempt fail identically — the update
    // broke permanently instead of once.
    let zip = good_zip();
    let d = FakeDeps::new()
        .with_file(dest("main.zip"), corrupt_payload(&zip, b"BIN"))
        .with_http(URL, Ok(zip.clone()));

    let out = download_asset(&d, URL, &dest("main.zip"), &one_shot(), None).unwrap();

    assert!(!out.cached, "a corrupt cache must not count as a hit");
    assert_eq!(d.file(&dest("main.zip")).as_deref(), Some(zip.as_slice()), "it must be re-fetched");
    assert_eq!(d.calls().iter().filter(|c| matches!(c, Call::HttpGet(u) if u == URL)).count(), 1);
}

#[test]
fn a_valid_cached_zip_is_reused_without_a_request() {
    let d = FakeDeps::new()
        .with_file(dest("main.zip"), good_zip())
        .with_http(URL, Err(DepsError::new(DepsErrorKind::Network, "must not be called")));

    let out = download_asset(&d, URL, &dest("main.zip"), &one_shot(), None).unwrap();

    assert!(out.cached);
    assert_eq!(out.attempts, 0);
    assert!(!d.calls().iter().any(|c| matches!(c, Call::HttpGet(_))), "no request for a good cache");
}

#[test]
fn a_truncated_download_never_becomes_the_destination() {
    let zip = good_zip();
    let d = FakeDeps::new().with_http(URL, Ok(zip[..zip.len() / 3].to_vec()));

    let err = download_asset(&d, URL, &dest("main.zip"), &one_shot(), None).unwrap_err();

    assert_eq!(err.kind, AppErrorKind::UpdateFailed);
    assert!(d.file(&dest("main.zip")).is_none(), "a partial file must not be promoted");
    assert!(d.file(&dest(&format!("main.zip{PART_SUFFIX}"))).is_none(), ".part must be cleaned up");
}

#[test]
fn a_full_length_but_corrupt_download_is_rejected() {
    let zip = good_zip();
    let d = FakeDeps::new().with_http(URL, Ok(corrupt_payload(&zip, b"BIN")));

    let err = download_asset(&d, URL, &dest("main.zip"), &one_shot(), None).unwrap_err();

    assert!(err.message.contains("校验失败"));
    assert!(d.file(&dest("main.zip")).is_none());
    assert!(d.file(&dest(&format!("main.zip{PART_SUFFIX}"))).is_none());
}

// ---- download: retry ----

#[test]
fn retries_spend_every_attempt_and_still_leave_nothing_behind() {
    let d = FakeDeps::new()
        .with_http(URL, Err(DepsError::new(DepsErrorKind::Network, "unreachable")));

    let err = download_asset(
        &d,
        URL,
        &dest("main.zip"),
        &DownloadOptions { attempts: 3, backoff_millis: 0, max_backoff_millis: 0 },
        None,
    )
    .unwrap_err();

    assert_eq!(err.message, "unreachable");
    assert_eq!(d.calls().iter().filter(|c| matches!(c, Call::HttpGet(_))).count(), 3);
    assert!(d.file(&dest("main.zip")).is_none());
    assert!(d.file(&dest(&format!("main.zip{PART_SUFFIX}"))).is_none());
}

#[test]
fn progress_reports_received_and_total_so_the_ui_can_show_a_percentage() {
    let mut seen: Vec<(u64, u64)> = Vec::new();
    let zip = good_zip();
    // A declared Content-Length is what makes a percentage possible; assert
    // both the received count and the total the UI divides by.
    let d = FakeDeps::new().with_http_len(URL, Ok(zip.clone()), Some(zip.len() as u64));

    download_asset(
        &d,
        URL,
        &dest("main.zip"),
        &one_shot(),
        Some(&mut |done: u64, total: u64| seen.push((done, total))),
    )
    .unwrap();

    assert_eq!(seen, vec![(zip.len() as u64, zip.len() as u64)]);
}

#[test]
fn a_complete_part_file_is_promoted_without_a_request() {
    let part = dest(&format!("main.zip{PART_SUFFIX}"));
    let d = FakeDeps::new().with_file(part.clone(), good_zip());

    let out = download_asset(&d, URL, &dest("main.zip"), &one_shot(), None).unwrap();

    assert_eq!(d.file(&dest("main.zip")).as_deref(), Some(good_zip().as_slice()));
    assert!(d.file(&part).is_none());
    assert!(!out.cached);
}

// ---- conflicts and atomic replace ----

#[test]
fn conflicts_are_the_existing_files_a_zip_would_overwrite() {
    let zp = dest("a.zip");
    let d = FakeDeps::new()
        .with_file(zp.clone(), zip_bytes(&[("new.exe", b"N"), ("shared.dll", b"D")]))
        .with_file(PathBuf::from(r"D:\llama.cpp\shared.dll"), b"OLD".to_vec())
        .with_file(PathBuf::from(r"D:\llama.cpp\old.exe"), b"OLD".to_vec());

    let conflicts = collect_conflicts(&d, &[zp], Path::new(r"D:\llama.cpp")).unwrap();

    assert_eq!(conflicts, vec!["shared.dll"], "old.exe is not in the zip, so it is not a conflict");
}

#[test]
fn extraction_overwrites_conflicts_and_leaves_the_rest_alone() {
    let zp = dest("a.zip");
    let root = Path::new(r"D:\llama.cpp");
    let d = FakeDeps::new()
        .with_file(zp.clone(), zip_bytes(&[("new.exe", b"NEW"), ("shared.dll", b"NEWDLL")]))
        .with_file(root.join("shared.dll"), b"OLD".to_vec())
        .with_file(root.join("old.exe"), b"OLD".to_vec());

    extract_top_level(&d, &zp, root).unwrap();

    assert_eq!(d.file(&root.join("new.exe")).as_deref(), Some(b"NEW".as_slice()));
    assert_eq!(d.file(&root.join("shared.dll")).as_deref(), Some(b"NEWDLL".as_slice()));
    assert_eq!(d.file(&root.join("old.exe")).as_deref(), Some(b"OLD".as_slice()));
}

#[test]
fn a_failed_write_leaves_the_target_untouched_and_no_temp_file() {
    // The rollback primitive: whatever was replaced before the failure is the
    // caller's to restore, but this file must still be the old one.
    let zp = dest("a.zip");
    let root = Path::new(r"D:\llama.cpp");
    let target = root.join("b.dll");
    let d = FakeDeps::new()
        .with_file(zp.clone(), zip_bytes(&[("a.dll", b"A"), ("b.dll", b"B")]))
        .with_file(target.clone(), b"OLD".to_vec())
        .with_failing_write(root.join("b.dll.llama_ctl_new"));

    let err = extract_top_level(&d, &zp, root).unwrap_err();

    assert_eq!(err.kind, AppErrorKind::UpdateFailed);
    assert_eq!(d.file(&target).as_deref(), Some(b"OLD".as_slice()), "must not be half-overwritten");
    assert!(d.file(&root.join("b.dll.llama_ctl_new")).is_none(), "temp file must not linger");
    // What succeeded before the failure is on disk — exactly what ticket 10's
    // replaced/added bookkeeping has to undo.
    assert_eq!(d.file(&root.join("a.dll")).as_deref(), Some(b"A".as_slice()));
}

#[test]
fn a_single_file_replace_is_atomic() {
    let zp = dest("a.zip");
    let root = Path::new(r"D:\llama.cpp");
    let d = FakeDeps::new()
        .with_file(zp.clone(), zip_bytes(&[("ggml.dll", b"NEW")]))
        .with_file(root.join("ggml.dll"), b"OLD".to_vec());

    extract_one(&d, &zp, root, "ggml.dll").unwrap();

    assert_eq!(d.file(&root.join("ggml.dll")).as_deref(), Some(b"NEW".as_slice()));
    let calls = d.calls();
    let writes: Vec<&PathBuf> = calls
        .iter()
        .filter_map(|c| match c {
            Call::WriteFile(p) => Some(p),
            _ => None,
        })
        .collect();

    assert_eq!(writes, vec![&root.join("ggml.dll.llama_ctl_new")], "the target is only ever renamed");
}

/// then succeed" needs a wrapper. This one delegates everything to a
/// `FakeDeps` (so `d.file()` still works for assertions) but fails the first
/// `fail_first` `http_get` calls.
struct FlakyNet<'a> {
    inner: &'a FakeDeps,
    fail_first: Cell<usize>,
}

impl Deps for FlakyNet<'_> {
    fn spawn(&self, program: &str, args: &[&str]) -> Result<Vec<u8>, DepsError> {
        self.inner.spawn(program, args)
    }
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
    fn reg_read_dword(
        &self,
        hive: RegHive,
        path: &str,
        value: &str,
    ) -> Result<Option<u32>, DepsError> {
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
    /// Every `http_get`, successful or not, goes through the inner fake so the
    /// call log stays complete; the first `fail_first` answers then fail.
    fn http_get(&self, url: &str) -> Result<HttpBody, DepsError> {
        let body = self.inner.http_get(url);
        if self.fail_first.get() > 0 {
            self.fail_first.set(self.fail_first.get() - 1);
            return Err(DepsError::new(DepsErrorKind::Network, "connection reset"));
        }
        body
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
    fn probe_health(&self, host: &str, port: u16) -> Result<bool, DepsError> {
        self.inner.probe_health(host, port)
    }
    fn now_millis(&self) -> u64 {
        self.inner.now_millis()
    }
}

#[test]
fn a_download_retries_after_a_dropped_connection_and_succeeds() {
    // The release CDN drops connections mid-transfer; one attempt must not be
    // the whole budget. Backoff is non-zero here to prove it waits on the
    // injected clock instead of sleeping — a real 1.5s sleep per retry would
    // make this suite crawl.
    let zip = good_zip();
    let fake = FakeDeps::new().with_http(URL, Ok(zip.clone())).with_now(1_700_000_000_000);
    let d = FlakyNet { inner: &fake, fail_first: Cell::new(1) };

    let out = download_asset(
        &d,
        URL,
        &dest("main.zip"),
        &DownloadOptions { attempts: 3, backoff_millis: 1500, max_backoff_millis: 8000 },
        None,
    )
    .unwrap();

    assert_eq!(out.attempts, 2, "one dropped connection, then the retry lands");
    assert!(!out.cached);
    assert_eq!(fake.file(&dest("main.zip")).as_deref(), Some(zip.as_slice()));
    assert_eq!(fake.calls().iter().filter(|c| matches!(c, Call::HttpGet(_))).count(), 2);
}
#[test]
fn a_missing_entry_is_an_error_not_a_partial_write() {
    let zp = dest("a.zip");
    let root = Path::new(r"D:\llama.cpp");
    let d = FakeDeps::new().with_file(zp.clone(), zip_bytes(&[("a.dll", b"A")]));

    let err = extract_one(&d, &zp, root, "nope.dll").unwrap_err();

    assert!(err.message.contains("nope.dll"));
    assert!(d.file(&root.join("nope.dll")).is_none());
}

// ---- backup / restore ----

#[test]
fn backup_then_restore_round_trips_the_old_bytes() {
    let root = Path::new(r"D:\llama.cpp");
    let d = FakeDeps::new()
        .with_file(root.join("a.dll"), b"OLD-A".to_vec())
        .with_file(root.join("b.dll"), b"OLD-B".to_vec());
    let bak = backup_dir(&d, Path::new(r"F:\llama_ctl\backup"), "b11213");

    let names = vec!["a.dll".to_string(), "b.dll".to_string()];
    let backed = backup_files(&d, &names, root, &bak).unwrap();
    assert_eq!(backed, names);

    d.write_file(&root.join("a.dll"), b"NEW-A").unwrap();
    d.write_file(&root.join("b.dll"), b"NEW-B").unwrap();

    let restored = restore_files(&d, &names, root, &bak).unwrap();

    assert_eq!(restored, names);
    assert_eq!(d.file(&root.join("a.dll")).as_deref(), Some(b"OLD-A".as_slice()));
    assert_eq!(d.file(&root.join("b.dll")).as_deref(), Some(b"OLD-B".as_slice()));
}

#[test]
fn the_backup_directory_is_timestamped_under_the_tag() {
    let d = FakeDeps::new().with_now(1_700_000_000_000);
    let dir = backup_dir(&d, Path::new(r"F:\llama_ctl\backup"), "b11213");
    assert_eq!(
        dir,
        PathBuf::from(format!(r"F:\llama_ctl\backup\b11213\{}", timestamp(&d)))
    );
    assert_eq!(timestamp(&d), "20231114_221320", "same shape as Python's strftime");
}

#[test]
fn backup_skips_sources_that_are_not_there() {
    let root = Path::new(r"D:\llama.cpp");
    let bak = Path::new(r"F:\llama_ctl\backup\b11213\stamp");
    let d = FakeDeps::new();

    assert_eq!(backup_files(&d, &["missing.dll".to_string()], root, bak).unwrap(), Vec::<String>::new());
    assert_eq!(restore_files(&d, &["missing.dll".to_string()], root, bak).unwrap(), Vec::<String>::new());
}

#[test]
fn a_backup_write_failure_aborts_before_anything_is_replaced() {
    // Ticket 10 relies on this: "backup failed ⇒ nothing was touched".
    let root = Path::new(r"D:\llama.cpp");
    let bak = Path::new(r"F:\llama_ctl\backup\b11213\stamp");
    let d = FakeDeps::new()
        .with_file(root.join("a.dll"), b"OLD-A".to_vec())
        .with_file(root.join("b.dll"), b"OLD-B".to_vec())
        .with_failing_write(bak.join("b.dll.llama_ctl_new"));

    let err = backup_files(&d, &["a.dll".to_string(), "b.dll".to_string()], root, bak).unwrap_err();

    assert!(err.message.contains("b.dll"));
    assert_eq!(d.file(&root.join("b.dll")).as_deref(), Some(b"OLD-B".as_slice()), "target untouched");
}

#[test]
fn restore_keeps_going_past_one_failure_and_reports_it() {
    let root = Path::new(r"D:\llama.cpp");
    let bak = Path::new(r"F:\llama_ctl\backup\b11213\stamp");
    let d = FakeDeps::new()
        .with_file(bak.join("a.dll"), b"OLD-A".to_vec())
        .with_file(bak.join("b.dll"), b"OLD-B".to_vec())
        .with_failing_write(root.join("a.dll.llama_ctl_old"));

    let err = restore_files(&d, &["a.dll".to_string(), "b.dll".to_string()], root, bak).unwrap_err();

    assert!(err.message.contains("a.dll"), "the failing file is named");
    assert_eq!(d.file(&root.join("b.dll")).as_deref(), Some(b"OLD-B".as_slice()), "the rest still restored");
}

#[test]
fn remove_files_deletes_only_the_named_files() {
    let root = Path::new(r"D:\llama.cpp");
    let d = FakeDeps::new()
        .with_file(root.join("new.dll"), b"NEW".to_vec())
        .with_file(root.join("keep.dll"), b"KEEP".to_vec());

    let removed = remove_files(&d, &["new.dll".to_string(), "never-existed.dll".to_string()], root).unwrap();

    assert_eq!(removed, vec!["new.dll"]);
    assert!(d.file(&root.join("new.dll")).is_none());
    assert_eq!(d.file(&root.join("keep.dll")).as_deref(), Some(b"KEEP".as_slice()));
}

// ---- stale-directory cleanup ----

fn sub(name: &str) -> DirEntry {
    DirEntry { path: PathBuf::from(format!(r"F:\llama_ctl\downloads\{name}")), is_dir: true }
}

fn plain(name: &str) -> DirEntry {
    DirEntry { path: PathBuf::from(format!(r"F:\llama_ctl\downloads\{name}.txt")), is_dir: false }
}

#[test]
fn cleanup_keeps_the_newest_three_subdirs() {
    let root = Path::new(r"F:\llama_ctl\downloads");
    let d = FakeDeps::new().with_dir(
        root,
        vec![sub("b11209"), sub("b11210"), sub("b11211"), sub("b11212"), sub("b11213")],
    );

    let removed = prune_old_subdirs(&d, root, PRUNE_KEEP).unwrap();

    assert_eq!(removed, vec!["b11210", "b11209"], "kept b11213, b11212, b11211");
}

#[test]
fn cleanup_never_deletes_plain_files() {
    let root = Path::new(r"F:\llama_ctl\downloads");
    let readme = plain("readme");
    let d = FakeDeps::new()
        .with_file(readme.path.clone(), b"keep me".to_vec())
        .with_dir(
            root,
            vec![sub("b11211"), sub("b11212"), sub("b11213"), readme.clone()],
        );
    let removed = prune_old_subdirs(&d, root, 1).unwrap();

    assert_eq!(removed, vec!["b11212", "b11211"]);
    // The fake keeps directory listings and file contents in separate maps, so
    // the readme has to be seeded as a file too for the "still there" half of
    // this assertion to mean anything.
    assert!(
        !d.calls().iter().any(|c| matches!(c, Call::RemoveFile(p) if p == &readme.path)),
        "a plain file is never a candidate for removal"
    );
    assert_eq!(d.file(&readme.path).as_deref(), Some(b"keep me".as_slice()));
}

#[test]
fn cleanup_covers_both_trees_and_keeps_three_of_each() {
    let downloads = Path::new(r"F:\llama_ctl\downloads");
    let backups = Path::new(r"F:\llama_ctl\backup");
    let d = FakeDeps::new()
        .with_dir(
            downloads,
            vec![sub("b11209"), sub("b11210"), sub("b11211"), sub("b11212"), sub("b11213")],
        )
        .with_dir(backups, vec![sub_at(backups, "b11213")])
        .with_dir(
            backups.join("b11213"),
            vec![
                DirEntry { path: backups.join("b11213").join("20231114_221320"), is_dir: true },
                DirEntry { path: backups.join("b11213").join("20231115_100000"), is_dir: true },
                DirEntry { path: backups.join("b11213").join("20231116_100000"), is_dir: true },
                DirEntry { path: backups.join("b11213").join("20231117_100000"), is_dir: true },
            ],
        )
        // The fake keeps directory listings and file contents in separate
        // maps, so the leaf directory has to list its own file too.
        .with_dir(
            backups.join("b11213").join("20231114_221320"),
            vec![DirEntry {
                path: backups.join("b11213").join("20231114_221320").join("ggml.dll"),
                is_dir: false,
            }],
        )
        .with_file(backups.join("b11213").join("20231114_221320").join("ggml.dll"), b"OLD".to_vec());


    let removed = cleanup_stale_dirs(&d, downloads, backups, PRUNE_KEEP);

    assert_eq!(removed, vec!["b11210", "b11209", "b11213/20231114_221320"]);
    assert!(
        d.file(&backups.join("b11213").join("20231114_221320").join("ggml.dll")).is_none(),
        "the stale backup's contents were deleted"
    );
}

#[test]
fn nested_cleanup_keeps_three_per_tag() {
    let root = Path::new(r"F:\llama_ctl\backup");
    let stamps: Vec<DirEntry> = (1..=5)
        .map(|i| DirEntry { path: root.join("b11213").join(format!("2023110{i}_100000")), is_dir: true })
        .collect();
    let d = FakeDeps::new()
        .with_dir(root, vec![sub_at(root, "b11213")])
        .with_dir(root.join("b11213"), stamps);

    let removed = prune_nested_subdirs(&d, root, PRUNE_KEEP).unwrap();

    assert_eq!(removed, vec!["b11213/20231102_100000", "b11213/20231101_100000"]);
}

fn sub_at(root: &Path, name: &str) -> DirEntry {
    DirEntry { path: root.join(name), is_dir: true }
}

#[test]
fn cleanup_is_a_no_op_for_a_missing_root_or_zero_keep() {
    let d = FakeDeps::new();
    let missing = Path::new(r"F:\llama_ctl\nope");
    assert_eq!(prune_old_subdirs(&d, missing, PRUNE_KEEP).unwrap(), Vec::<String>::new());
    assert_eq!(prune_nested_subdirs(&d, missing, PRUNE_KEEP).unwrap(), Vec::<String>::new());

    let root = Path::new(r"F:\llama_ctl\downloads");
    let d = FakeDeps::new().with_dir(root, vec![sub("b11211"), sub("b11212")]);
    assert_eq!(
        prune_old_subdirs(&d, root, 0).unwrap(),
        Vec::<String>::new(),
        "keep=0 must not wipe history"
    );
    assert_eq!(cleanup_stale_dirs(&d, root, root, 0), Vec::<String>::new());
}

#[test]
fn cleanup_returns_empty_when_there_is_nothing_stale() {
    let root = Path::new(r"F:\llama_ctl\downloads");
    let d = FakeDeps::new().with_dir(root, vec![sub("b11211"), sub("b11212")]);
    assert_eq!(prune_old_subdirs(&d, root, PRUNE_KEEP).unwrap(), Vec::<String>::new());
}
