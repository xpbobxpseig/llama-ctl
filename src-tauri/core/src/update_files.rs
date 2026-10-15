//! Official updater, file half (ticket 06).
//!
//! Port of `updater.py`'s second half: download with retry and backoff, zip
//! validation, conflict detection, per-file atomic replacement, timestamped
//! **Backup**, restore, and startup cleanup of stale download/backup
//! directories. Discovery (release lookup, asset selection) lives in
//! [`crate::updater`]; the transaction that sequences all of it is ticket 10.
//!
//! Terminology (CONTEXT.md): this module produces a **Backup** (the old files
//! copied aside before an update) and the primitives **Rollback** — ticket 10's
//! failure path — calls to put them back. Nothing here is user-triggerable.
//!
//! Every side effect goes through [`Deps`]. Two consequences of that seam are
//! load-bearing and recorded in the ticket's `## Resolution`:
//!
//! * `http_get` returns bytes only — no status, no headers — so there is no
//!   Content-Length (progress reports bytes received, not a percentage) and no
//!   `Range` (a retry re-fetches the whole asset instead of resuming).
//! * there is no `remove_dir`, so cleanup empties a stale directory rather
//!   than unlinking it.

use std::io::{Cursor, Read, Write};
use std::path::{Path, PathBuf};

use zip::CompressionMethod;
use zip::result::ZipError;
use zip::write::{SimpleFileOptions, ZipWriter};
use zip::ZipArchive;

use crate::deps::{AppError, AppErrorKind, AppResult, Deps, DepsError, DirEntry};

/// Subdirectories kept by [`cleanup_stale_dirs`] (`PRUNE_KEEP` in the GUI).
pub const PRUNE_KEEP: usize = 3;
pub const PART_SUFFIX: &str = ".part";
pub const NEW_SUFFIX: &str = ".llama_ctl_new";
pub const OLD_SUFFIX: &str = ".llama_ctl_old";

/// Retry budget. The release CDN drops connections mid-transfer often enough
/// that a single attempt would fail a real update (one cut per five attempts
/// was measured); backoff is `min(base * attempt, max)`, so 1.5s, 3s, 4.5s…
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DownloadOptions {
    pub attempts: usize,
    pub backoff_millis: u64,
    pub max_backoff_millis: u64,
}

impl Default for DownloadOptions {
    fn default() -> Self {
        Self { attempts: 10, backoff_millis: 1500, max_backoff_millis: 8000 }
    }
}

/// `attempts = 1, backoff = 0`: one shot, no waiting. For tests and for
/// callers that do their own retrying.
pub const NO_RETRY: DownloadOptions = DownloadOptions { attempts: 1, backoff_millis: 0, max_backoff_millis: 0 };

/// Result of [`download_asset`]. `cached` distinguishes "reused the file that
/// was already there" from "fetched it", which is the only way a caller can
/// tell a no-op update from a real download.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DownloadOutcome {
    pub path: PathBuf,
    pub cached: bool,
    /// Attempts spent, 0 when the cached file was reused.
    pub attempts: usize,
    pub bytes: u64,
}

// ---- download ----

/// Get `url` into `dest`, retrying with exponential backoff.
///
/// `progress` receives the number of bytes written so far, once per attempt.
/// The total is missing on purpose: the seam's `http_get` yields no
/// Content-Length, so a percentage would be invented.
///
/// Integrity, in order:
///
/// 1. a cached `dest` is reused **only** if [`is_valid_zip`] accepts it — this
///    is the `dc45c77` fix. A truncated download that counts as "cached" makes
///    every future attempt fail identically, i.e. the update breaks forever
///    rather than once. A cached file that fails validation is deleted.
/// 2. a leftover `.part` is promoted when it already validates; otherwise it is
///    discarded (no `Range` in the seam means no way to continue it).
/// 3. a freshly fetched body is written to `.part` and validated **before** the
///    rename, so `dest` never exists in a half-written state. Validation reads
///    every entry and checks its CRC: it catches both truncation and the
///    measured "right length, 92% zeroed payload" failure.
///
/// Every failure path leaves neither `dest` nor `.part` behind.
pub fn download_asset(
    d: &impl Deps,
    url: &str,
    dest: &Path,
    opts: &DownloadOptions,
    progress: Option<&mut dyn FnMut(u64)>,
) -> AppResult<DownloadOutcome> {
    let mut progress = progress;
    if let Some(parent) = dest.parent().filter(|p| !p.as_os_str().is_empty()) {
        d.create_dir_all(parent).map_err(update_error)?;
    }

    if is_valid_zip(d, dest) {
        let bytes = d.read_file(dest).map(|b| b.len() as u64).unwrap_or(0);
        return Ok(DownloadOutcome { path: dest.to_path_buf(), cached: true, attempts: 0, bytes });
    }
    let _ = d.remove_file(dest);

    let part = suffixed_path(dest, PART_SUFFIX);
    let attempts = opts.attempts.max(1);
    let mut last: Option<AppError> = None;

    for attempt in 0..attempts {
        if attempt > 0 {
            wait_backoff(d, (opts.backoff_millis * attempt as u64).min(opts.max_backoff_millis));
        }
        // A complete download abandoned by an interrupted run: promote it
        // without spending a request.
        if let Ok(bytes) = d.read_file(&part)
            && !bytes.is_empty()
            && is_valid_zip_bytes(&bytes)
        {
            d.rename_file(&part, dest).map_err(update_error)?;
            return Ok(DownloadOutcome {
                path: dest.to_path_buf(),
                cached: false,
                attempts: attempt + 1,
                bytes: bytes.len() as u64,
            });
        }
        let _ = d.remove_file(&part);

        let body = match d.http_get(url) {
            Ok(b) => b,
            Err(e) => {
                last = Some(update_error(e));
                continue;
            }
        };
        if let Err(e) = d.write_file(&part, &body) {
            let _ = d.remove_file(&part);
            last = Some(update_error(e));
            continue;
        }
        if let Some(cb) = progress.as_deref_mut() {
            cb(body.len() as u64);
        }
        if !is_valid_zip_bytes(&body) {
            let _ = d.remove_file(&part);
            last = Some(AppError::new(
                AppErrorKind::UpdateFailed,
                format!(
                    "下载内容校验失败：{} 不是有效的 zip（可能被截断或损坏），已丢弃，请重试",
                    file_name(dest)
                ),
            ));
            continue;
        }
        match d.rename_file(&part, dest) {
            Ok(()) => {
                return Ok(DownloadOutcome {
                    path: dest.to_path_buf(),
                    cached: false,
                    attempts: attempt + 1,
                    bytes: body.len() as u64,
                })
            }
            Err(e) => {
                let _ = d.remove_file(&part);
                last = Some(update_error(e));
            }
        }
    }

    let _ = d.remove_file(&part);
    Err(last.unwrap_or_else(|| {
        AppError::new(AppErrorKind::UpdateFailed, format!("下载失败：{}，请重试", file_name(dest)))
    }))
}

/// Whether `path` is a zip we can actually use.
///
/// Reads **every entry and checks its CRC**, not just the central directory: a
/// truncated file has no readable directory, and the measured zeroed-payload
/// failure has a perfectly readable one. Never raises — a corrupt file is a
/// `false`, not a panic, because callers use this to decide whether to reuse a
/// cache entry.
pub fn is_valid_zip(d: &impl Deps, path: &Path) -> bool {
    let Ok(bytes) = d.read_file(path) else { return false };
    is_valid_zip_bytes(&bytes)
}

/// Same as [`is_valid_zip`], over bytes already in hand.
pub fn is_valid_zip_bytes(bytes: &[u8]) -> bool {
    let Ok(mut archive) = open_archive(bytes) else { return false };
    for i in 0..archive.len() {
        let Ok(mut entry) = archive.by_index(i) else { return false };
        // `sink()` is not enough on its own — the CRC is only computed when the
        // reader reaches the end of the entry, so the data must be drained.
        if std::io::copy(&mut entry, &mut std::io::sink()).is_err() {
            return false;
        }
    }
    true
}

// ---- zip contents ----

/// Top-level file names of a zip, sorted. Direct entries and nested paths are
/// skipped: the official zips are flat, and writing `sub/x.dll` out would put
/// files where the service does not look.
pub fn zip_top_files(d: &impl Deps, zip_path: &Path) -> AppResult<Vec<String>> {
    let bytes = read(d, zip_path)?;
    let mut archive = open_archive(&bytes).map_err(|e| zip_error(zip_path, e))?;
    let mut names: Vec<String> = Vec::new();
    for i in 0..archive.len() {
        let Ok(entry) = archive.by_index(i) else { continue };
        if entry.is_dir() {
            continue;
        }
        let Ok(name) = entry.name() else { continue };
        if name.contains('/') || name.contains('\\') {
            continue;
        }
        names.push(name.into_owned());
    }
    names.sort();
    names.dedup();
    Ok(names)
}

/// The files already in `dest_dir` that extracting `zip_paths` would overwrite
/// — i.e. exactly what a Backup must hold.
///
/// Presence is `read_file`, not a directory listing: `Deps` has no `is_file`,
/// and `list_dir` answers for a different thing in the fake (see
/// [`crate::fake::FakeDeps::with_dir`]).
pub fn collect_conflicts(d: &impl Deps, zip_paths: &[PathBuf], dest_dir: &Path) -> AppResult<Vec<String>> {
    let mut names: Vec<String> = Vec::new();
    for zp in zip_paths {
        for name in zip_top_files(d, zp)? {
            if !names.contains(&name) {
                names.push(name);
            }
        }
    }
    let mut conflicts: Vec<String> = names
        .into_iter()
        .filter(|n| d.read_file(&dest_dir.join(n)).is_ok())
        .collect();
    conflicts.sort();
    Ok(conflicts)
}

/// Write one top-level entry of `zip_path` into `dest_dir`, atomically: the
/// bytes land in `<name>.llama_ctl_new` and are renamed over the target, so a
/// failure at any point leaves the target byte-identical and no partial file
/// behind.
pub fn extract_one(d: &impl Deps, zip_path: &Path, dest_dir: &Path, name: &str) -> AppResult<()> {
    let bytes = read_entry(d, zip_path, name)?;
    // `replace_atomically` already prefixes the file name.
    replace_atomically(d, dest_dir, name, &bytes, NEW_SUFFIX)
}

/// Extract every top-level entry. Returns the names written, in order, so a
/// caller can roll back precisely what this call replaced.
pub fn extract_top_level(d: &impl Deps, zip_path: &Path, dest_dir: &Path) -> AppResult<Vec<String>> {
    let mut written = Vec::new();
    for name in zip_top_files(d, zip_path)? {
        extract_one(d, zip_path, dest_dir, &name)?;
        written.push(name);
    }
    Ok(written)
}

// ---- backup / restore (primitives for ticket 10's rollback) ----

/// `<root>/<tag>/<YYYYmmdd_HHMMSS>`: one Backup directory per install attempt.
pub fn backup_dir(d: &impl Deps, root: &Path, tag: &str) -> PathBuf {
    root.join(tag).join(timestamp(d))
}

/// `YYYYmmdd_HHMMSS` (UTC) from the injected clock — the shape Python's
/// `strftime` produced, so directories read as dates and order by name.
pub fn timestamp(d: &impl Deps) -> String {
    stamp_from_millis(d.now_millis())
}

/// Copy `names` from `dest_dir` into `backup_dir`, one atomic write each.
///
/// Missing sources are skipped (nothing to restore later). A failure aborts
/// immediately and returns `Err`: the caller has not replaced anything yet, so
/// aborting here is what keeps "backup failed ⇒ nothing was touched" true.
///
/// Presence is `read_file`, not a `list_dir` set: the bytes are needed anyway,
/// so a separate existence probe would read every file twice.
pub fn backup_files(d: &impl Deps, names: &[String], dest_dir: &Path, backup_dir: &Path) -> AppResult<Vec<String>> {
    d.create_dir_all(backup_dir).map_err(update_error)?;
    let mut backed = Vec::new();
    for name in names {
        let Ok(bytes) = d.read_file(&dest_dir.join(name)) else {
            continue;
        };
        replace_atomically(d, backup_dir, name, &bytes, NEW_SUFFIX)?;
        backed.push(name.clone());
    }
    Ok(backed)
}


/// Put `names` back into `dest_dir` from `backup_dir` (the Rollback half).
///
/// Unlike [`backup_files`] this never stops at the first failure: every other
/// file still gets restored, and the errors are returned aggregated.
pub fn restore_files(
    d: &impl Deps,
    names: &[String],
    dest_dir: &Path,
    backup_dir: &Path,
) -> AppResult<Vec<String>> {
    d.create_dir_all(dest_dir).map_err(update_error)?;
    let mut restored = Vec::new();
    let mut errors = Vec::new();
    for name in names {
        let Ok(bytes) = d.read_file(&backup_dir.join(name)) else {
            continue;
        };
        match replace_atomically(d, dest_dir, name, &bytes, OLD_SUFFIX) {
            Ok(()) => restored.push(name.clone()),
            Err(e) => errors.push(format!("{name}: {}", e.message)),
        }
    }
    if !errors.is_empty() {
        return Err(AppError::new(AppErrorKind::UpdateFailed, errors.join("; ")));
    }
    Ok(restored)
}

/// Delete `names` from `dest_dir` — the cleanup for files an update added and
/// a Rollback must undo. Absent files count as already deleted, and the errors
/// of the rest are aggregated rather than stopping at the first one.
pub fn remove_files(d: &impl Deps, names: &[String], dest_dir: &Path) -> AppResult<Vec<String>> {
    let mut removed = Vec::new();
    let mut errors = Vec::new();
    for name in names {
        let target = dest_dir.join(name);
        // `Deps::remove_file` has no "missing" case in its contract, so absence
        // is probed by reading first — one failed read on a file we are about
        // to delete is cheaper than a second seam method.
        if d.read_file(&target).is_err() {
            continue;
        }
        match d.remove_file(&target) {
            Ok(()) => removed.push(name.clone()),
            Err(e) => errors.push(format!("{name}: {}", e.message)),
        }
    }
    if !errors.is_empty() {
        return Err(AppError::new(AppErrorKind::UpdateFailed, errors.join("; ")));
    }
    Ok(removed)
}

// ---- startup cleanup ----

/// Keep the newest `keep` subdirectories of `root`, empty out the rest.
///
/// Only subdirectories are ever considered; plain files in `root` are never
/// touched. Returns the directory names that were emptied. Failures are
/// aggregated into the `Err`, mirroring [`remove_files`]. `keep = 0` deletes
/// nothing — a caller passing 0 by accident must not wipe history.
pub fn prune_old_subdirs(d: &impl Deps, root: &Path, keep: usize) -> AppResult<Vec<String>> {
    let (removed, errors) = prune_subdirs(d, root, keep);
    if !errors.is_empty() {
        return Err(AppError::new(AppErrorKind::UpdateFailed, errors.join("; ")));
    }
    Ok(removed)
}

/// [`prune_old_subdirs`] one level down: for every subdirectory of `root`
/// (a release tag), keep its newest `keep` children.
///
/// The real backup layout is `backup/{tag}/{stamp}/`. Pruning only the root
/// would keep three tags forever while the timestamp directories inside them
/// grow without bound — ~1.3 GB per install of the same tag.
pub fn prune_nested_subdirs(d: &impl Deps, root: &Path, keep: usize) -> AppResult<Vec<String>> {
    let (removed, errors) = prune_nested(d, root, keep);
    if !errors.is_empty() {
        return Err(AppError::new(AppErrorKind::UpdateFailed, errors.join("; ")));
    }
    Ok(removed)
}

/// Startup cleanup of both trees, keeping [`PRUNE_KEEP`] of each.
///
/// Downloads are flat (`root/{tag}/file`), backups are nested
/// (`root/{tag}/{stamp}/file`). Never fails and never deletes a plain file: a
/// cleanup problem must not be what stops the app from starting. Returns the
/// removed directory names, for one log line.
pub fn cleanup_stale_dirs(
    d: &impl Deps,
    download_root: &Path,
    backup_root: &Path,
    keep: usize,
) -> Vec<String> {
    let mut removed = prune_subdirs(d, download_root, keep).0;
    removed.extend(prune_nested(d, backup_root, keep).0);
    removed
}

fn prune_subdirs(d: &impl Deps, root: &Path, keep: usize) -> (Vec<String>, Vec<String>) {
    if keep == 0 {
        return (Vec::new(), Vec::new());
    }
    // A root we cannot list is a root that does not exist yet — normal on the
    // first run, not an error.
    let Ok(entries) = d.list_dir(root) else {
        return (Vec::new(), Vec::new());
    };
    let mut dirs: Vec<DirEntry> = entries.into_iter().filter(|e| e.is_dir).collect();
    dirs.sort_by(|a, b| name_key(&b.path).cmp(&name_key(&a.path)));
    let mut removed = Vec::new();
    let mut errors = Vec::new();
    for entry in dirs.into_iter().skip(keep) {
        let name = file_name(&entry.path);
        match remove_dir_tree(d, &entry.path) {
            Ok(()) => removed.push(name),
            Err(e) => errors.push(format!("{name}: {}", e.message)),
        }
    }
    (removed, errors)
}

fn prune_nested(d: &impl Deps, root: &Path, keep: usize) -> (Vec<String>, Vec<String>) {
    if keep == 0 {
        return (Vec::new(), Vec::new());
    }
    let Ok(entries) = d.list_dir(root) else {
        return (Vec::new(), Vec::new());
    };
    let mut removed = Vec::new();
    let mut errors = Vec::new();
    for entry in entries.into_iter().filter(|e| e.is_dir) {
        let tag = file_name(&entry.path);
        let (gone, errs) = prune_subdirs(d, &entry.path, keep);
        removed.extend(gone.into_iter().map(|n| format!("{tag}/{n}")));
        // One unreadable tag must not stop the others.
        if !errs.is_empty() {
            errors.push(format!("{tag}: {}", errs.join("; ")));
        }
    }
    (removed, errors)
}

/// Best-effort delete of everything *inside* `dir`.
///
/// `ponytail:` the directory entry itself outlives the call — `Deps` exposes
/// `remove_file` but no `remove_dir`, so a pruned directory is emptied, not
/// unlinked. Ceiling: emptied directories pile up until the seam grows
/// `remove_dir_all`, which makes the tail of this function one line. Individual
/// failures are swallowed on purpose: a dll still mapped by the service must
/// not stop the rest of the cleanup.
fn remove_dir_tree(d: &impl Deps, dir: &Path) -> Result<(), DepsError> {
    for entry in d.list_dir(dir)? {
        if entry.is_dir {
            let _ = remove_dir_tree(d, &entry.path);
        } else {
            let _ = d.remove_file(&entry.path);
        }
    }
    Ok(())
}

// ---- atomic write ----

/// Write `bytes` to `<dir>/<name><suffix>`, then rename over `<dir>/<name>`.
///
/// The rename is the commit point: anything before it leaves the target exactly
/// as it was, and the temp file is removed so no half-written file survives to
/// be mistaken for the real one.
fn replace_atomically(
    d: &impl Deps,
    dir: &Path,
    name: &str,
    bytes: &[u8],
    suffix: &str,
) -> AppResult<()> {
    let tmp = suffixed_path(&dir.join(name), suffix);
    let failed = |e: DepsError| AppError::new(AppErrorKind::UpdateFailed, format!("{name}: {}", e.message));
    if let Err(e) = d.write_file(&tmp, bytes) {
        let _ = d.remove_file(&tmp);
        return Err(failed(e));
    }
    match d.rename_file(&tmp, &dir.join(name)) {
        Ok(()) => Ok(()),
        Err(e) => {
            let _ = d.remove_file(&tmp);
            Err(failed(e))
        }
    }
}

// ---- helpers ----

/// Wait `millis` on the injected clock. `Deps` has no sleep and tests must not
/// sleep, so the wait is a spin on `now_millis` — with a poll ceiling, because
/// a frozen test clock would otherwise hang forever.
const MAX_BACKOFF_POLLS: u32 = 64;

fn wait_backoff(d: &impl Deps, millis: u64) {
    if millis == 0 {
        return;
    }
    let deadline = d.now_millis().saturating_add(millis);
    let mut polls = 0;
    while d.now_millis() < deadline && polls < MAX_BACKOFF_POLLS {
        polls += 1;
    }
}

fn read(d: &impl Deps, path: &Path) -> AppResult<Vec<u8>> {
    d.read_file(path).map_err(update_error)
}

fn update_error(e: DepsError) -> AppError {
    AppError::new(AppErrorKind::UpdateFailed, e.message)
}

fn zip_error(path: &Path, e: ZipError) -> AppError {
    AppError::new(AppErrorKind::UpdateFailed, format!("无法读取更新包 {}: {}", path.display(), e))
}

fn read_entry(d: &impl Deps, zip_path: &Path, name: &str) -> AppResult<Vec<u8>> {
    let bytes = read(d, zip_path)?;
    let mut archive = open_archive(&bytes).map_err(|e| zip_error(zip_path, e))?;
    let index = (0..archive.len()).find(|&i| {
        archive
            .by_index(i)
            .ok()
            .and_then(|e| e.name().ok().map(|n| n.as_ref() == name))
            .unwrap_or(false)
    });
    let Some(i) = index else {
        return Err(AppError::new(
            AppErrorKind::UpdateFailed,
            format!("更新包 {} 中缺少文件 {}", zip_path.display(), name),
        ));
    };
    let mut entry = archive.by_index(i).map_err(|e| zip_error(zip_path, e))?;
    let mut out = Vec::new();
    // CRC is checked on the way out, so a damaged entry is an error here
    // instead of a silently zeroed binary on disk.
    entry.read_to_end(&mut out).map_err(|e| zip_error(zip_path, ZipError::Io(e)))?;
    Ok(out)
}

fn open_archive(bytes: &[u8]) -> Result<ZipArchive<Cursor<&[u8]>>, ZipError> {
    ZipArchive::new(Cursor::new(bytes))
}

/// Newest first. Python sorts by mtime; `DirEntry` carries no mtime, so the
/// numeric run in the name stands in (`20240101_120000` and `b11213` both order
/// correctly), ties break on the whole name so the result is stable.
fn name_key(path: &Path) -> (u64, String) {
    let name = file_name(path);
    (leading_number(&name), name)
}

fn leading_number(name: &str) -> u64 {
    let b = name.as_bytes();
    let start = b.iter().position(|c| c.is_ascii_digit()).unwrap_or(b.len());
    let end = (start..b.len()).find(|&i| !b[i].is_ascii_digit()).unwrap_or(b.len());
    name[start..end].parse().unwrap_or(0)
}

fn suffixed_path(path: &Path, suffix: &str) -> PathBuf {
    let mut os = path.as_os_str().to_os_string();
    os.push(suffix);
    PathBuf::from(os)
}

fn file_name(path: &Path) -> String {
    path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default()
}

fn stamp_from_millis(ms: u64) -> String {
    let secs = ms / 1000;
    let (y, m, d) = civil_from_days((secs / 86_400) as i64);
    let sod = secs % 86_400;
    format!("{y:04}{m:02}{d:02}_{:02}{:02}{:02}", sod / 3600, sod % 3600 / 60, sod % 60)
}

/// Days since 1970-01-01 to `(year, month, day)` — Howard Hinnant's
/// civil-from-days. std has no calendar and a dependency for one timestamp is
/// not worth it.
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

/// Build a zip in memory. Only used by this module's tests, but it lives here
/// so the tests cannot drift from how the module reads zips.
pub fn zip_bytes(entries: &[(&str, &[u8])]) -> Vec<u8> {
    let mut buf = Vec::new();
    {
        let mut w = ZipWriter::new(Cursor::new(&mut buf));
        // Stored, not deflated: the payload is then literal in the file, which
        // is what lets a test corrupt it in place.
        let opts = SimpleFileOptions::default().compression_method(CompressionMethod::Stored);
        for (name, data) in entries {
            w.start_file(*name, opts).expect("start_file");
            w.write_all(data).expect("write_all");
        }
        w.finish().expect("finish");
    }
    buf
}
