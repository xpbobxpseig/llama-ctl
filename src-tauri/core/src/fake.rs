//! Test double for `Deps`: in-memory, records every call, never touches the OS.
//!
//! Lives in the crate (not behind `#[cfg(test)]`) so integration tests in
//! `tests/` can use it too — that is where the migrated domain tests will go.

use std::cell::{Cell, RefCell};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

use crate::deps::{Deps, DepsError, DepsErrorKind, DirEntry, HttpBody, HttpStream, RegHive};

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
    HttpRequest { method: String, url: String, body: Option<String> },
    HttpOpenRange { url: String, range_from: u64 },
    AppendFile { path: PathBuf, len: usize },
    HashFile(PathBuf),
    FileSize(PathBuf),
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
    http: HashMap<String, Result<HttpBody, DepsError>>,
    http_req: HashMap<String, Result<HttpBody, DepsError>>,
    http_range: HashMap<String, RangeScript>,
    health: HashMap<(String, u16), bool>,
    now: u64,
    /// Simulated failures, applied by path so a test can make exactly one
    /// write fail and assert the transaction rolled back.
    failing_writes: HashMap<PathBuf, DepsError>,
}

/// Scripted download stream for [`Deps::http_open_range`]. `fail_first_after`
/// makes the *first* open die mid-read after N bytes (simulating a reset
/// connection); `no_resume` makes every open answer a plain `200` as if the
/// server ignored `Range`.
#[derive(Debug, Default)]
pub struct RangeScript {
    pub data: Vec<u8>,
    pub fail_first_after: Option<usize>,
    pub no_resume: bool,
    opens: Cell<u32>,
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
        self.http.insert(url.to_string(), body.map(|b| HttpBody::new(b, None)));
        self
    }

    /// Script a [`Deps::http_request`] call, keyed by `"{method} {url}"`. The
    /// request body is recorded (see `calls()`) but not part of the key.
    pub fn with_http_req(
        mut self,
        method: &str,
        url: &str,
        body: Result<Vec<u8>, DepsError>,
    ) -> Self {
        self.http_req
            .insert(format!("{method} {url}"), body.map(|b| HttpBody::new(b, None)));
        self
    }

    /// Same as [`with_http`] but declaring a `Content-Length`, which is what
    /// makes percentage progress testable.
    pub fn with_http_len(
        mut self,
        url: &str,
        body: Result<Vec<u8>, DepsError>,
        content_length: Option<u64>,
    ) -> Self {
        self.http
            .insert(url.to_string(), body.map(|b| HttpBody::new(b, content_length)));
        self
    }

    /// Script a [`Deps::http_open_range`] download supporting `Range`.
    pub fn with_http_range(mut self, url: &str, data: Vec<u8>) -> Self {
        self.http_range.insert(
            url.to_string(),
            RangeScript { data, ..RangeScript::default() },
        );
        self
    }

    /// Same, but the server ignores `Range` and always answers `200`.
    pub fn with_http_range_no_resume(mut self, url: &str, data: Vec<u8>) -> Self {
        self.http_range.insert(
            url.to_string(),
            RangeScript { data, no_resume: true, ..RangeScript::default() },
        );
        self
    }

    /// Same, but the first open dies mid-read after `fail_after` bytes.
    pub fn with_http_range_flaky(mut self, url: &str, data: Vec<u8>, fail_after: usize) -> Self {
        self.http_range.insert(
            url.to_string(),
            RangeScript { data, fail_first_after: Some(fail_after), ..RangeScript::default() },
        );
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

/// Stream over scripted download bytes, dying mid-read once `fail_after`
/// bytes have been served (a scripted connection reset).
struct ScriptedReader {
    data: Vec<u8>,
    pos: usize,
    fail_after: Option<usize>,
}

impl std::io::Read for ScriptedReader {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        if let Some(fa) = self.fail_after {
            if self.pos >= fa {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::ConnectionAborted,
                    "scripted connection reset",
                ));
            }
        }
        let mut n = buf.len().min(self.data.len() - self.pos);
        if let Some(fa) = self.fail_after {
            n = n.min(fa - self.pos); // 先把 fail_after 字节内的给完，下一次 read 才断
        }
        buf[..n].copy_from_slice(&self.data[self.pos..self.pos + n]);
        self.pos += n;
        Ok(n)
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

    fn spawn_split(&self, program: &str, args: &[&str]) -> Result<(Vec<u8>, Vec<u8>), DepsError> {
        self.calls.borrow_mut().push(Call::Spawn {
            program: program.to_string(),
            args: args.iter().map(|a| a.to_string()).collect(),
        });
        match self.spawn_out.get(program) {
            Some(Ok(b)) => Ok((b.clone(), Vec::new())),
            Some(Err(e)) => Err(e.clone()),
            None => Ok((Vec::new(), Vec::new())),
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

    fn http_get(&self, url: &str) -> Result<HttpBody, DepsError> {
        self.calls.borrow_mut().push(Call::HttpGet(url.to_string()));
        match self.http.get(url) {
            Some(Ok(b)) => Ok(b.clone()),
            Some(Err(e)) => Err(e.clone()),
            None => Err(DepsError::new(DepsErrorKind::Network, format!("unscripted url: {url}"))),
        }
    }

    fn http_request(&self, method: &str, url: &str, body: Option<&str>) -> Result<Vec<u8>, DepsError> {
        self.calls.borrow_mut().push(Call::HttpRequest {
            method: method.to_string(),
            url: url.to_string(),
            body: body.map(|b| b.to_string()),
        });
        let key = format!("{method} {url}");
        match self.http_req.get(&key) {
            Some(Ok(b)) => Ok(b.bytes.clone()),
            Some(Err(e)) => Err(e.clone()),
            None => Err(DepsError::new(
                DepsErrorKind::Network,
                format!("unscripted request: {key}"),
            )),
        }
    }

    fn http_open_range(&self, url: &str, range_from: u64) -> Result<HttpStream, DepsError> {
        self.calls.borrow_mut().push(Call::HttpOpenRange {
            url: url.to_string(),
            range_from,
        });
        let Some(script) = self.http_range.get(url) else {
            return Err(DepsError::new(
                DepsErrorKind::Network,
                format!("unscripted download: {url}"),
            ));
        };
        let open = script.opens.get() + 1;
        script.opens.set(open);
        if script.no_resume {
            let pos = if range_from > 0 && !script.data.is_empty() {
                // 200 意味着服务器忽略了 Range：从头给全量（调用方必须重下）。
                0
            } else {
                0
            };
            return Ok(HttpStream {
                reader: Box::new(std::io::Cursor::new(script.data[pos..].to_vec())),
                total: Some(script.data.len() as u64),
                resumed: false,
            });
        }
        let fail_after = if open == 1 { script.fail_first_after } else { None };
        let remaining: Vec<u8> = if range_from as usize >= script.data.len() {
            Vec::new()
        } else {
            script.data[range_from as usize..].to_vec()
        };
        Ok(HttpStream {
            reader: Box::new(ScriptedReader { data: remaining, pos: 0, fail_after }),
            total: Some(script.data.len() as u64),
            resumed: true,
        })
    }

    fn append_file(&self, path: &Path, bytes: &[u8]) -> Result<(), DepsError> {
        self.calls.borrow_mut().push(Call::AppendFile {
            path: path.to_path_buf(),
            len: bytes.len(),
        });
        self.files.borrow_mut().entry(path.to_path_buf()).and_modify(|v| v.extend_from_slice(bytes)).or_insert_with(|| bytes.to_vec());
        Ok(())
    }

    fn file_size(&self, path: &Path) -> Result<Option<u64>, DepsError> {
        self.calls.borrow_mut().push(Call::FileSize(path.to_path_buf()));
        Ok(self.files.borrow().get(path).map(|v| v.len() as u64))
    }

    fn hash_file(&self, path: &Path) -> Result<String, DepsError> {
        self.calls.borrow_mut().push(Call::HashFile(path.to_path_buf()));
        let bytes = self.files.borrow().get(path).cloned().ok_or_else(|| {
            DepsError::new(DepsErrorKind::FileRead, format!("no such file: {}", path.display()))
        })?;
        use sha2::Digest;
        let mut h = sha2::Sha256::new();
        h.update(&bytes);
        Ok(h.finalize().iter().map(|b| format!("{b:02x}")).collect())
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
