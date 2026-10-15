//! The real `Deps`: actual registry reads, child processes, HTTP and files.
//!
//! The other half of the seam from ticket 01. Everything here is Windows-only
//! by construction — no `cfg` branch, no abstraction over "a service manager"
//! (ADR-0003).


use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::deps::{Deps, DepsError, DepsErrorKind, DirEntry, HttpBody, RegHive};

/// Without this every `nssm` / `sc` / `powershell` call flashes a console
/// window — which is why Python passed it to *every* command.
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// `0x80070002` — the key or value simply is not there.
const HRESULT_FILE_NOT_FOUND: i32 = -2_147_478_360;

/// The real implementation. Stateless: everything is per-call.
#[derive(Debug, Default, Clone, Copy)]
pub struct RealDeps;

impl RealDeps {
    pub fn new() -> Self {
        Self
    }
}

/// Run a command with `CREATE_NO_WINDOW` and stderr merged into stdout.
///
/// The merge is not cosmetic: `llama-server --version` writes to **stderr**, so
/// a caller that only saw stdout would report the installed build as unknown.
fn run(program: &str, args: &[&str]) -> Result<Vec<u8>, DepsError> {
    let mut cmd = Command::new(program);
    cmd.args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let out = cmd
        .output()
        .map_err(|e| DepsError::new(DepsErrorKind::SpawnFailed, format!("{program}: {e}")))?;

    if !out.status.success() {
        // `sc` explains failures on stderr, so prefer it for the message.
        let stderr = crate::decode::decode(&out.stderr).trim().to_string();
        let stdout = crate::decode::decode(&out.stdout).trim().to_string();
        let detail = if stderr.is_empty() { stdout } else { stderr };
        return Err(DepsError::new(
            DepsErrorKind::NonZeroExit,
            if detail.is_empty() {
                format!("{program} exited with {}", out.status)
            } else {
                detail
            },
        ));
    }

    let mut merged = out.stdout;
    merged.extend_from_slice(&out.stderr);
    Ok(merged)
}

/// Open `HKLM\<path>` read-only.
fn open_key(path: &str) -> Result<windows_registry::Key, DepsError> {
    windows_registry::LOCAL_MACHINE
        .open(path)
        .map_err(|e| DepsError::new(DepsErrorKind::Registry, format!("{path}: {e}")))
}

/// An absent key or value is a normal outcome, not an error — the caller
/// decides whether to fall back to `nssm get`.
fn is_absent(e: &windows_result::Error) -> bool {
    e.code().0 == HRESULT_FILE_NOT_FOUND
}
/// Read a response body to bytes.
fn read_body(mut body: ureq::Body) -> Result<Vec<u8>, DepsError> {
    body.read_to_vec()
        .map_err(|e| DepsError::new(DepsErrorKind::Network, format!("read body: {e}")))
}
impl Deps for RealDeps {
    fn spawn(&self, program: &str, args: &[&str]) -> Result<Vec<u8>, DepsError> {
        run(program, args)
    }

    fn reg_read_dword(
        &self,
        _hive: RegHive,
        path: &str,
        value: &str,
    ) -> Result<Option<u32>, DepsError> {
        let key = open_key(path)?;
        match key.get_u32(value) {
            Ok(v) => Ok(Some(v)),
            Err(e) if is_absent(&e) => Ok(None),
            Err(e) => Err(DepsError::new(
                DepsErrorKind::Registry,
                format!(r"{path}\{value}: {e}"),
            )),
        }
    }

    fn reg_read_string(
        &self,
        _hive: RegHive,
        path: &str,
        value: &str,
    ) -> Result<Option<String>, DepsError> {
        let key = open_key(path)?;
        match key.get_string(value) {
            Ok(v) => Ok(Some(v)),
            Err(e) if is_absent(&e) => Ok(None),
            Err(e) => Err(DepsError::new(
                DepsErrorKind::Registry,
                format!(r"{path}\{value}: {e}"),
            )),
        }
    }

    fn read_file(&self, path: &Path) -> Result<Vec<u8>, DepsError> {
        std::fs::read(path).map_err(|e| {
            DepsError::new(DepsErrorKind::FileRead, format!("{}: {e}", path.display()))
        })
    }

    fn write_file(&self, path: &Path, contents: &[u8]) -> Result<(), DepsError> {
        std::fs::write(path, contents).map_err(|e| {
            DepsError::new(DepsErrorKind::FileWrite, format!("{}: {e}", path.display()))
        })
    }

    fn rename_file(&self, from: &Path, to: &Path) -> Result<(), DepsError> {
        std::fs::rename(from, to).map_err(|e| {
            DepsError::new(
                DepsErrorKind::FileWrite,
                format!("{} -> {}: {e}", from.display(), to.display()),
            )
        })
    }

    fn remove_file(&self, path: &Path) -> Result<(), DepsError> {
        std::fs::remove_file(path).map_err(|e| {
            DepsError::new(DepsErrorKind::FileWrite, format!("{}: {e}", path.display()))
        })
    }

    fn list_dir(&self, path: &Path) -> Result<Vec<DirEntry>, DepsError> {
        let rd = std::fs::read_dir(path).map_err(|e| {
            DepsError::new(DepsErrorKind::FileRead, format!("{}: {e}", path.display()))
        })?;
        let mut out = Vec::new();
        for entry in rd {
            let entry = entry.map_err(|e| {
                DepsError::new(DepsErrorKind::FileRead, format!("{}: {e}", path.display()))
            })?;
            let is_dir = entry.file_type().map(|t| t.is_dir()).unwrap_or(false);
            out.push(DirEntry { path: entry.path(), is_dir });
        }
        Ok(out)
    }

    fn create_dir_all(&self, path: &Path) -> Result<(), DepsError> {
        std::fs::create_dir_all(path).map_err(|e| {
            DepsError::new(DepsErrorKind::FileWrite, format!("{}: {e}", path.display()))
        })
    }

    fn http_get(&self, url: &str) -> Result<HttpBody, DepsError> {
        // GitHub rejects requests without a User-Agent.
        let resp = ureq::get(url)
            .header("User-Agent", "llama_ctl-updater/1.0")
            .call()
            .map_err(|e| DepsError::new(DepsErrorKind::Network, format!("{url}: {e}")))?;
        // The declared length is what lets the UI show a percentage. Fall back
        // to the received length when the server omitted it, so callers always
        // have a denominator.
        let content_length = resp
            .headers()
            .get("content-length")
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.parse::<u64>().ok());
        let bytes = read_body(resp.into_body())?;
        let len = content_length.unwrap_or(bytes.len() as u64);
        Ok(HttpBody::new(bytes, Some(len)))
    }

    fn probe_health(&self, host: &str, port: u16) -> Result<bool, DepsError> {
        // `/health` on current builds, `/healthz` on older ones.
        for path in ["/health", "/healthz"] {
            let url = format!("http://{host}:{port}{path}");
            let Ok(resp) = ureq::get(&url)
                .header("User-Agent", "llama_ctl-updater/1.0")
                .call()
            else {
                continue;
            };
            if resp.status().is_success() {
                return Ok(true);
            }
        }
        Ok(false)
    }

    fn now_millis(&self) -> u64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_millis() as u64)
            .unwrap_or(0)
    }
}
