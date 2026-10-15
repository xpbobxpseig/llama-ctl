//! Test double for `Deps`: in-memory, records every call, never touches the OS.
//!
//! Lives in the crate (not behind `#[cfg(test)]`) so integration tests in
//! `tests/` can use it too — that is where the migrated domain tests will go.

use std::cell::RefCell;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

use crate::deps::{Deps, DepsError, DepsErrorKind, DirEntry, RegHive};

/// One recorded invocation. Tests assert on these, e.g. "facts() spawned
/// nothing" becomes `fake.calls().iter().any(|c| c.is_spawn())`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Call {
    Spawn { program: String, args: Vec<String> },
    RegDword { path: String, value: String },
    RegString { path: String, value: String },
    ReadFile(PathBuf),
    WriteFile(PathBuf),
    RenameFile { from: PathBuf, to: PathBuf },
    RemoveFile(PathBuf),
    ListDir(PathBuf),
    CreateDirAll(PathBuf),
    HttpGet(String),
    ProbeHealth { host: String, port: u16 },
}

impl Call {
    pub fn is_spawn(&self) -> bool {
        matches!(self, Call::Spawn { .. })
    }
}

/// Scripted answers, keyed by call. When a key is absent the fake falls back to
/// `defaults` — tests only script what they care about.
#[derive(Debug, Default)]
pub struct FakeDeps {
    calls: RefCell<Vec<Call>>,
    spawn_out: HashMap<String, Result<Vec<u8>, DepsError>>,
    reg_dwords: HashMap<(String, String), Option<u32>>,
    reg_strings: HashMap<(String, String), Option<String>>,
    files: RefCell<HashMap<PathBuf, Vec<u8>>>,
    dirs: HashMap<PathBuf, Vec<DirEntry>>,
    http: HashMap<String, Result<Vec<u8>, DepsError>>,
    health: HashMap<(String, u16), bool>,
    now: u64,
    /// Simulated failures, applied by path so a test can make exactly one
    /// write fail and assert the transaction rolled back.
    failing_writes: HashMap<PathBuf, DepsError>,
}

impl FakeDeps {
    pub fn new() -> Self {
        Self::default()
    }

    // ---- scripting ----

    pub fn with_spawn(mut self, program: &str, out: Result<Vec<u8>, DepsError>) -> Self {
        self.spawn_out.insert(program.to_string(), out);
        self
    }

    pub fn with_reg_dword(mut self, path: &str, value: &str, v: Option<u32>) -> Self {
        self.reg_dwords.insert((path.to_string(), value.to_string()), v);
        self
    }

    pub fn with_reg_string(mut self, path: &str, value: &str, v: Option<String>) -> Self {
        self.reg_strings.insert((path.to_string(), value.to_string()), v);
        self
    }

    pub fn with_file(self, path: impl Into<PathBuf>, contents: Vec<u8>) -> Self {
        self.files.borrow_mut().insert(path.into(), contents);
        self
    }

    pub fn with_dir(mut self, path: impl Into<PathBuf>, entries: Vec<DirEntry>) -> Self {
        self.dirs.insert(path.into(), entries);
        self
    }

    pub fn with_http(mut self, url: &str, body: Result<Vec<u8>, DepsError>) -> Self {
        self.http.insert(url.to_string(), body);
        self
    }

    pub fn with_health(mut self, host: &str, port: u16, ok: bool) -> Self {
        self.health.insert((host.to_string(), port), ok);
        self
    }

    /// Make writes to `path` fail with a write error.
    pub fn with_failing_write(mut self, path: impl Into<PathBuf>) -> Self {
        self.failing_writes.insert(
            path.into(),
            DepsError::new(DepsErrorKind::FileWrite, "simulated write failure"),
        );
        self
    }

    pub fn with_now(mut self, millis: u64) -> Self {
        self.now = millis;
        self
    }

    // ---- assertions ----

    pub fn calls(&self) -> Vec<Call> {
        self.calls.borrow().clone()
    }

    /// The acceptance criterion "reading facts spawns zero child processes".
    pub fn spawn_count(&self) -> usize {
        self.calls().iter().filter(|c| c.is_spawn()).count()
    }

    pub fn file(&self, path: &Path) -> Option<Vec<u8>> {
        self.files.borrow().get(path).cloned()
    }
}

impl Deps for FakeDeps {
    fn spawn(&self, program: &str, args: &[&str]) -> Result<Vec<u8>, DepsError> {
        self.calls.borrow_mut().push(Call::Spawn {
            program: program.to_string(),
            args: args.iter().map(|a| a.to_string()).collect(),
        });
        match self.spawn_out.get(program) {
            Some(Ok(b)) => Ok(b.clone()),
            Some(Err(e)) => Err(e.clone()),
            None => Ok(Vec::new()),
        }
    }

    fn reg_read_dword(&self, _hive: RegHive, path: &str, value: &str) -> Result<Option<u32>, DepsError> {
        self.calls.borrow_mut().push(Call::RegDword {
            path: path.to_string(),
            value: value.to_string(),
        });
        Ok(self
            .reg_dwords
            .get(&(path.to_string(), value.to_string()))
            .copied()
            .flatten())
    }

    fn reg_read_string(
        &self,
        _hive: RegHive,
        path: &str,
        value: &str,
    ) -> Result<Option<String>, DepsError> {
        self.calls.borrow_mut().push(Call::RegString {
            path: path.to_string(),
            value: value.to_string(),
        });
        Ok(self
            .reg_strings
            .get(&(path.to_string(), value.to_string()))
            .cloned()
            .flatten())
    }

    fn read_file(&self, path: &Path) -> Result<Vec<u8>, DepsError> {
        self.calls.borrow_mut().push(Call::ReadFile(path.to_path_buf()));
        self.files
            .borrow()
            .get(path)
            .cloned()
            .ok_or_else(|| DepsError::new(DepsErrorKind::FileRead, format!("no such file: {}", path.display())))
    }

    fn write_file(&self, path: &Path, contents: &[u8]) -> Result<(), DepsError> {
        self.calls.borrow_mut().push(Call::WriteFile(path.to_path_buf()));
        if let Some(e) = self.failing_writes.get(path) {
            return Err(e.clone());
        }
        self.files.borrow_mut().insert(path.to_path_buf(), contents.to_vec());
        Ok(())
    }

    fn rename_file(&self, from: &Path, to: &Path) -> Result<(), DepsError> {
        self.calls.borrow_mut().push(Call::RenameFile {
            from: from.to_path_buf(),
            to: to.to_path_buf(),
        });
        let mut files = self.files.borrow_mut();
        let contents = files
            .remove(from)
            .ok_or_else(|| DepsError::new(DepsErrorKind::FileRead, format!("no such file: {}", from.display())))?;
        files.insert(to.to_path_buf(), contents);
        Ok(())
    }

    fn remove_file(&self, path: &Path) -> Result<(), DepsError> {
        self.calls.borrow_mut().push(Call::RemoveFile(path.to_path_buf()));
        self.files.borrow_mut().remove(path);
        Ok(())
    }

    fn list_dir(&self, path: &Path) -> Result<Vec<DirEntry>, DepsError> {
        self.calls.borrow_mut().push(Call::ListDir(path.to_path_buf()));
        Ok(self.dirs.get(path).cloned().unwrap_or_default())
    }

    fn create_dir_all(&self, path: &Path) -> Result<(), DepsError> {
        self.calls.borrow_mut().push(Call::CreateDirAll(path.to_path_buf()));
        Ok(())
    }

    fn http_get(&self, url: &str) -> Result<Vec<u8>, DepsError> {
        self.calls.borrow_mut().push(Call::HttpGet(url.to_string()));
        match self.http.get(url) {
            Some(Ok(b)) => Ok(b.clone()),
            Some(Err(e)) => Err(e.clone()),
            None => Err(DepsError::new(DepsErrorKind::Network, format!("unscripted url: {url}"))),
        }
    }

    fn probe_health(&self, host: &str, port: u16) -> Result<bool, DepsError> {
        self.calls.borrow_mut().push(Call::ProbeHealth {
            host: host.to_string(),
            port,
        });
        Ok(self.health.get(&(host.to_string(), port)).copied().unwrap_or(false))
    }

    fn now_millis(&self) -> u64 {
        self.now
    }
}
