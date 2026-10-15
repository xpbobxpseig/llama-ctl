//! The wire envelope every command replies with.
//!
//! Tauri serialises a `Result<T, E>` as a bare `T` on success and a bare `E` on
//! failure, and the frontend cannot tell those apart without guessing. This
//! envelope makes the distinction explicit and is the one shape the frontend has
//! to handle:
//!
//! ```json
//! {"ok": true,  "data": { ... }}
//! {"ok": false, "error": {"kind": "NoSuchService", "message": "..."}}
//! ```
//!
//! `error.kind` is the PascalCase enum variant name (`core::deps::AppErrorKind`
//! is already `Serialize` with no rename), so the frontend can branch on it —
//! e.g. offer "check the build variant" for `UpdateFailed`, or just show
//! `message` for everything else.
//!
//! Both halves are JSON values, not strings: the frontend must never parse a
//! payload by hand, and a nested object keeps one `JSON.parse` enough.

use serde::{Deserialize, Serialize};
use serde_json::Value;

use llama_ctl_core::deps::AppError;

/// A successful reply. `data` is the command's own return value.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OkPayload {
    pub ok: bool,
    pub data: Value,
}

/// A failed reply.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ErrorPayload {
    pub ok: bool,
    pub error: AppError,
}

impl OkPayload {
    pub fn new<T: Serialize>(data: &T) -> Self {
        // A value that cannot serialise is a programming error here, not a
        // runtime one: every type crossing this boundary is plain data. `null`
        // keeps the envelope well-formed rather than failing the whole call.
        Self { ok: true, data: serde_json::to_value(data).unwrap_or(Value::Null) }
    }
}

impl ErrorPayload {
    pub fn new(error: AppError) -> Self {
        Self { ok: false, error }
    }

    /// The `kind` as it appears on the wire, for tests and for the frontend's
    /// switch statements.
    pub fn kind(&self) -> String {
        serde_json::to_value(self.error.kind)
            .ok()
            .and_then(|v| v.as_str().map(str::to_string))
            .unwrap_or_default()
    }
}

/// Wrap a command result in the envelope.
pub fn envelope<T: Serialize>(result: Result<T, AppError>) -> Result<OkPayload, ErrorPayload> {
    match result {
        Ok(v) => Ok(OkPayload::new(&v)),
        Err(e) => Err(ErrorPayload::new(e)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use llama_ctl_core::deps::AppErrorKind;

    #[test]
    fn an_error_carries_a_branchable_kind_and_a_display_message() {
        let e = ErrorPayload::new(AppError::new(AppErrorKind::NoSuchService, "没有这个服务"));
        let json = serde_json::to_string(&e).unwrap();
        assert!(json.contains("\"ok\":false"), "{json}");
        assert_eq!(e.kind(), "NoSuchService");
        assert_eq!(e.error.message, "没有这个服务");
    }

    #[test]
    fn a_success_embeds_the_value_not_a_stringified_one() {
        let p = OkPayload::new(&vec!["a", "b"]);
        assert_eq!(p.data, serde_json::json!(["a", "b"]));
        assert!(p.ok);
    }
}
