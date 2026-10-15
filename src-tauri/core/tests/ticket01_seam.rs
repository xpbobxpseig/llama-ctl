//! Ticket 01 acceptance: the `Deps` seam is usable.
//!
//! These assert the *capabilities* later tickets depend on, not trivial
//! plumbing: that side effects can be scripted, that calls are recorded and
//! countable, and that a domain operation can run start-to-finish with zero
//! child processes.

use std::path::Path;

use llama_ctl_core::deps::{AppError, AppErrorKind, Deps, DepsError, DepsErrorKind, RegHive};
use llama_ctl_core::fake::{Call, FakeDeps};

/// Stand-in for a future domain operation: reads a service's facts from the
/// registry only, never spawning. Mirrors the Python `facts()` contract.
fn read_facts(d: &impl Deps, service: &str) -> Result<(Option<String>, Option<u32>), DepsError> {
    let path = format!(r"SYSTEM\CurrentControlSet\Services\{service}\Parameters");
    let app_dir = d.reg_read_string(RegHive::LocalMachine, &path, "AppDirectory")?;
    let start = d.reg_read_dword(RegHive::LocalMachine, &format!(r"SYSTEM\CurrentControlSet\Services\{service}"), "Start")?;
    Ok((app_dir, start))
}

#[test]
fn registry_read_records_calls_and_spawns_nothing() {
    let d = FakeDeps::new().with_reg_string(
        r"SYSTEM\CurrentControlSet\Services\QwenLLM\Parameters",
        "AppDirectory",
        Some(r"D:\llama.cpp".to_string()),
    );

    let (dir, _) = read_facts(&d, "QwenLLM").unwrap();

    // The 0-spawn criterion from the Python test suite is expressible here.
    assert_eq!(dir.as_deref(), Some(r"D:\llama.cpp"));
    assert_eq!(d.spawn_count(), 0, "facts must not spawn a child process");
    assert_eq!(d.calls().len(), 2, "one string read plus one dword read");
}

#[test]
fn spawn_output_is_raw_bytes_not_decoded_text() {
    // NSSM emits UTF-16LE; ticket 02 owns decoding. The seam must hand over
    // bytes untouched, or decoding can never be tested in isolation.
    let raw: Vec<u8> = b"S\x00E\x00R\x00V\x00I\x00C\x00E\x00_\x00R\x00U\x00N\x00N\x00I\x00N\x00G\x00".to_vec();
    let d = FakeDeps::new().with_spawn("nssm.exe", Ok(raw.clone()));

    let out = d.spawn("nssm.exe", &["get", "QwenLLM", "ObjectName"]).unwrap();

    assert_eq!(out, raw);
    assert_eq!(
        d.calls(),
        vec![Call::Spawn {
            program: "nssm.exe".to_string(),
            args: vec!["get".to_string(), "QwenLLM".to_string(), "ObjectName".to_string()],
        }]
    );
}

#[test]
fn spawn_failure_is_a_typed_error_carrying_a_display_message() {
    let d = FakeDeps::new().with_spawn(
        "nssm.exe",
        Err(DepsError::new(DepsErrorKind::SpawnFailed, "nssm.exe not found")),
    );

    let err = d.spawn("nssm.exe", &["get"]).unwrap_err();

    assert_eq!(err.kind, DepsErrorKind::SpawnFailed);
    assert_eq!(err.message, "nssm.exe not found");
    assert_eq!(err.to_string(), "nssm.exe not found");
}

#[test]
fn a_single_write_can_be_made_to_fail_while_others_succeed() {
    // Ticket 10 needs this: fail one replacement mid-transaction and assert the
    // previously replaced files were restored.
    let target = Path::new(r"D:\llama.cpp\llama-server.exe");
    let other = Path::new(r"D:\llama.cpp\ggml.dll");
    let d = FakeDeps::new().with_failing_write(target);

    assert!(d.write_file(target, b"new").is_err());
    assert!(d.write_file(other, b"new").is_ok());
    assert_eq!(d.file(other).as_deref(), Some(b"new".as_slice()));
}

#[test]
fn rename_moves_contents_atomically_enough_for_the_temp_file_pattern() {
    // The atomic-write contract: write to .tmp, then rename over the target.
    let tmp = Path::new(r"C:\Users\me\AppData\Roaming\llama-ctl\presets.json.tmp");
    let dst = Path::new(r"C:\Users\me\AppData\Roaming\llama-ctl\presets.json");
    let d = FakeDeps::new();

    d.write_file(tmp, br#"{"a":1}"#).unwrap();
    d.rename_file(tmp, dst).unwrap();

    assert_eq!(d.file(dst).as_deref(), Some(br#"{"a":1}"#.as_slice()));
    assert_eq!(d.file(tmp), None, "temp file must not linger");
    assert!(matches!(
        d.calls().last(),
        Some(Call::RenameFile { from, to }) if from == tmp && to == dst
    ));
}

#[test]
fn unscripted_network_fails_loudly_rather_than_returning_empty() {
    // A silent empty body would make "no releases found" indistinguishable from
    // "network broken".
    let d = FakeDeps::new();
    let err = d.http_get("https://example.invalid/releases").unwrap_err();
    assert_eq!(err.kind, DepsErrorKind::Network);
}

#[test]
fn clock_is_injectable_so_backup_timestamps_are_deterministic() {
    let d = FakeDeps::new().with_now(1_700_000_000_000);
    assert_eq!(d.now_millis(), 1_700_000_000_000);
}

#[test]
fn deps_error_converts_to_app_error_without_losing_the_message() {
    let e = DepsError::new(DepsErrorKind::FileWrite, r"access denied: C:\Program Files");
    let app: AppError = e.into();
    assert_eq!(app.kind, AppErrorKind::StorageFailed);
    assert_eq!(app.message, r"access denied: C:\Program Files");
}

#[test]
fn errors_survive_the_ipc_boundary_as_json() {
    // Ticket 11 promises "structured errors the frontend can render directly".
    let e = AppError::new(AppErrorKind::NoSuchService, "QwenLLM 不是 NSSM 服务");
    let json = serde_json::to_string(&e).unwrap();
    let back: AppError = serde_json::from_str(&json).unwrap();
    assert_eq!(back, e);
    assert!(json.contains("NoSuchService"));
}
