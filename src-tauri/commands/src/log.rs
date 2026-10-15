//! `server.err` log tail.
//!
//! Ticket 14 needs the log region to follow the real file, not just the
//! restart transcript. The path is derived the way Python derived it
//! (`llama_ctl_gui.py::_log_path`): `<AppDirectory>\server.err`, falling back
//! to `LLAMA_CTL_ERR_LOG` when the install directory is unknown.
//!
//! Reading goes through `Deps::read_file`, so the seam from ticket 01 still
//! holds and tests never touch a disk.

use std::path::{Path, PathBuf};

use llama_ctl_core::deps::Deps;
use llama_ctl_core::service::{FactsCache, app_directory};

/// How many lines the tail keeps. The GUI only ever shows a screenful, and the
/// file grows without bound while the service runs.
pub const TAIL_LINES: usize = 200;

/// `LLAMA_CTL_ERR_LOG`. An empty value counts as unset, matching Python's
/// `os.environ.get(...) or ...`.
pub fn err_log_from_env() -> Option<PathBuf> {
    let raw = std::env::var("LLAMA_CTL_ERR_LOG").ok()?;
    (!raw.trim().is_empty()).then(|| PathBuf::from(raw))
}

/// Where `server.err` lives for a service.
///
/// `app_dir` is the service's `AppDirectory` (already resolved, so this stays
/// free of `App`'s internals); the fallback is the environment override, then
/// the built-in path Python used.
pub fn log_path(app_dir: Option<&str>) -> PathBuf {
    if let Some(dir) = app_dir.map(str::trim).filter(|d| !d.is_empty()) {
        return Path::new(dir).join("server.err");
    }
    err_log_from_env().unwrap_or_else(|| PathBuf::from(r"F:\llama.cpp\server.err"))
}

/// The tail of `server.err` for a service, oldest line first.
///
/// An unreadable or missing file yields an empty vec, never an error: the log
/// region is decoration, and a missing file must not block startup or paint an
/// error the user cannot act on.
pub fn tail_log(d: &impl Deps, cache: &FactsCache, service: &str) -> Vec<String> {
    let dir = app_directory(d, cache, service);
    let path = log_path(dir.as_deref());
    let Ok(bytes) = d.read_file(&path) else {
        return Vec::new();
    };
    tail_lines(&String::from_utf8_lossy(&bytes), TAIL_LINES)
}

/// Split on both line endings, drop a trailing blank, keep the last `n`.
fn tail_lines(text: &str, n: usize) -> Vec<String> {
    let mut lines: Vec<String> = text
        .replace("\r\n", "\n")
        .split('\n')
        .map(str::to_string)
        .collect();
    // A file ending in "\n" yields one empty final element that is not a line.
    if lines.last().is_some_and(|l| l.is_empty()) {
        lines.pop();
    }
    let start = lines.len().saturating_sub(n);
    lines.split_off(start)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_path_follows_the_install_directory() {
        assert_eq!(log_path(Some(r"F:\llama.cpp")), PathBuf::from(r"F:\llama.cpp\server.err"));
    }

    #[test]
    fn an_empty_install_directory_falls_back() {
        // Must not produce "\server.err".
        assert_eq!(log_path(Some("")), log_path(None));
    }

    #[test]
    fn tail_keeps_the_last_lines_and_drops_a_trailing_blank() {
        assert_eq!(tail_lines("a\nb\nc\n", 10), vec!["a", "b", "c"]);
        assert_eq!(tail_lines("a\nb\nc\n", 2), vec!["b", "c"]);
    }

    #[test]
    fn crlf_is_normalised() {
        assert_eq!(tail_lines("a\r\nb\r\n", 10), vec!["a", "b"]);
    }

    #[test]
    fn an_empty_file_is_empty_lines() {
        assert!(tail_lines("", 10).is_empty());
    }

    #[test]
    fn requesting_more_lines_than_exist_keeps_them_all() {
        assert_eq!(tail_lines("a\nb", 100), vec!["a", "b"]);
    }

    #[test]
    fn blank_lines_in_the_middle_are_kept() {
        assert_eq!(tail_lines("a\n\nb", 10), vec!["a", "", "b"]);
    }
}
