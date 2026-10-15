//! `Deps` trait — the single seam through which every external side effect flows.
//!
//! Mirrors the shape proven by `installer.RealDeps` in the Python version:
//! domain logic never calls the system directly, so a fake implementation can
//! drive the whole install/rollback path with no network, no service, no UI.
//!
//! ADR-0003: this is deliberately Windows-only. There is no `cfg` branch and no
//! abstraction over "a service manager" — do not add one.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

/// Everything a domain operation is allowed to do to the outside world.
///
/// Implementors: one real (talks to Windows), one fake (records calls, used by
/// tests). The fake must be able to count invocations — several acceptance
/// criteria are phrased as "spawns zero child processes".
pub trait Deps {
    /// Run a command and capture its output.
    ///
    /// Returns raw bytes, not `String`: NSSM emits UTF-16LE while `sc` emits the
    /// local code page (GBK). Decoding is a separate concern (ticket 02) and
    /// must not be baked in here.
    ///
    /// stdout and stderr arrive merged, because `llama-server --version` writes
    /// to **stderr** — an implementation returning stdout alone would leave the
    /// installed build permanently "unknown".
    fn spawn(&self, program: &str, args: &[&str]) -> Result<Vec<u8>, DepsError>;

    /// Read a DWORD from the Windows registry. `None` when the key or value is
    /// absent — the caller decides whether to fall back to `nssm get`.
    fn reg_read_dword(&self, hive: RegHive, path: &str, value: &str) -> Result<Option<u32>, DepsError>;

    /// Read a string (REG_SZ / REG_EXPAND_SZ) from the Windows registry.
    fn reg_read_string(&self, hive: RegHive, path: &str, value: &str) -> Result<Option<String>, DepsError>;

    fn read_file(&self, path: &Path) -> Result<Vec<u8>, DepsError>;
    fn write_file(&self, path: &Path, contents: &[u8]) -> Result<(), DepsError>;
    fn rename_file(&self, from: &Path, to: &Path) -> Result<(), DepsError>;
    fn remove_file(&self, path: &Path) -> Result<(), DepsError>;
    fn list_dir(&self, path: &Path) -> Result<Vec<DirEntry>, DepsError>;
    fn create_dir_all(&self, path: &Path) -> Result<(), DepsError>;

    /// `GET` a URL and return the body. Used for release discovery only —
    /// binary downloads stream through `download`, never through the renderer.
    fn http_get(&self, url: &str) -> Result<Vec<u8>, DepsError>;

    /// `true` when the service answered `/healthz`.
    fn probe_health(&self, host: &str, port: u16) -> Result<bool, DepsError>;

    /// Monotonic wall clock, for backup-dir timestamps and retry backoff.
    /// Injectable so tests never sleep.
    fn now_millis(&self) -> u64;
}

/// Only the hive we actually need. Adding more is fine; adding a
/// platform-neutral "registry-like" abstraction is not (ADR-0003).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum RegHive {
    LocalMachine,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DirEntry {
    pub path: PathBuf,
    pub is_dir: bool,
}

/// A failure from the outside world, carrying a message fit for display.
///
/// Deliberately carries no source error: `std::io::Error` is not `Serialize`
/// and the frontend only ever needs the message.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DepsError {
    pub kind: DepsErrorKind,
    pub message: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum DepsErrorKind {
    SpawnFailed,
    NonZeroExit,
    Timeout,
    Registry,
    FileRead,
    FileWrite,
    Network,
    HealthProbe,
}

impl DepsError {
    pub fn new(kind: DepsErrorKind, message: impl Into<String>) -> Self {
        Self { kind, message: message.into() }
    }
}

impl std::fmt::Display for DepsError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl std::error::Error for DepsError {}

/// Domain-level error: what the user did wrong or what state we found, not how
/// the OS failed. Frontend renders `message` verbatim.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AppError {
    pub kind: AppErrorKind,
    pub message: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AppErrorKind {
    /// The service named by the user does not exist / is not NSSM-managed.
    NoSuchService,
    /// Parameters could not be parsed; `message` explains why.
    BadParameters,
    /// A write-back was rejected before touching the service.
    Refused,
    /// Something in the update transaction failed; state was rolled back.
    UpdateFailed,
    /// Preference or preset storage is unwritable (read-only dir, …).
    StorageFailed,
}

impl AppError {
    pub fn new(kind: AppErrorKind, message: impl Into<String>) -> Self {
        Self { kind, message: message.into() }
    }
}

impl std::fmt::Display for AppError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl std::error::Error for AppError {}

impl From<DepsError> for AppError {
    /// A raw OS failure surfaces to the user as-is; callers that know better
    /// should construct `AppError` themselves with a domain-specific message.
    fn from(e: DepsError) -> Self {
        AppError::new(AppErrorKind::StorageFailed, e.message)
    }
}

/// Every command returns this. The frontend never sees a bare error string.
pub type AppResult<T> = Result<T, AppError>;
