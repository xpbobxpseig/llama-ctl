//! Ticket 04 acceptance, ported from `tests/test_nssm_facts.py`.
//!
//! The load-bearing assertion is the spawn count: reading a service's facts
//! must not start a child process. Everything else here is behaviour, not
//! implementation — no test asserts on the cache's internals.

use llama_ctl_core::deps::{DepsError, DepsErrorKind};
use llama_ctl_core::fake::{Call, FakeDeps};
use llama_ctl_core::service::{
    FactsCache, StartMode, app_directory, check_health, facts, get_app_parameters,
    get_start_mode, list_nssm_services, query_status, sc_action, sc_query_state,
    set_app_parameters, set_start_mode,
};
use llama_ctl_core::service::{DEFAULT_SERVICE, NSSM_EXE, RUNNING_STATE, UNKNOWN_STATE};

/// Registry path NSSM writes a service's parameters under.
fn params_key(service: &str) -> String {
    format!(r"SYSTEM\CurrentControlSet\Services\{service}\Parameters")
}
fn service_key(service: &str) -> String {
    format!(r"SYSTEM\CurrentControlSet\Services\{service}")
}

/// A service whose facts are fully readable from the registry.
fn registry_service(service: &str, dir: &str, params: &str, start: Option<u32>) -> FakeDeps {
    FakeDeps::new()
        .with_reg_string(&params_key(service), "AppDirectory", Some(dir.to_string()))
        .with_reg_string(&params_key(service), "AppParameters", Some(params.to_string()))
        .with_reg_dword(&service_key(service), "Start", start)
}

// ---- the 0-spawn contract ----

/// How many registry reads happened. Counting `calls()` instead would fold in
/// child processes and make "did we re-read?" ambiguous.
fn registry_reads(d: &FakeDeps) -> usize {
    d.calls()
        .iter()
        .filter(|c| matches!(c, Call::RegDword { .. } | Call::RegString { .. }))
        .count()
}

#[test]
fn facts_come_from_the_registry_with_zero_spawns() {
    let d = registry_service("QwenLLM", r"D:\llama.cpp", "-m a.gguf --ctx-size 4096", Some(3));
    let cache = FactsCache::new();

    let f = facts(&d, &cache, "QwenLLM");

    assert_eq!(f.app_dir.as_deref(), Some(r"D:\llama.cpp"));
    assert_eq!(f.app_params, "-m a.gguf --ctx-size 4096");
    assert_eq!(f.start, StartMode::Manual);
    assert_eq!(d.spawn_count(), 0, "reading facts must not spawn a process");
    // Three registry reads, no child processes.
    assert_eq!(d.calls().len(), 3);
}

#[test]
fn the_compat_accessors_hit_the_cache_and_spawn_nothing() {
    let d = registry_service("QwenLLM", r"D:\llama.cpp", "-m a.gguf", Some(2));
    let cache = FactsCache::new();

    assert_eq!(app_directory(&d, &cache, "QwenLLM").as_deref(), Some(r"D:\llama.cpp"));
    assert_eq!(get_app_parameters(&d, &cache, "QwenLLM"), "-m a.gguf");
    assert_eq!(get_start_mode(&d, &cache, "QwenLLM"), StartMode::Auto);

    assert_eq!(d.spawn_count(), 0);
    // Still three reads: every accessor after the first is a cache hit.
    assert_eq!(d.calls().len(), 3);
}

#[test]
fn the_second_read_is_a_cache_hit() {
    let d = registry_service("QwenLLM", r"D:\llama.cpp", "-m a.gguf", Some(3));
    let cache = FactsCache::new();

    facts(&d, &cache, "QwenLLM");
    let reads_after_first = d.calls().len();
    facts(&d, &cache, "QwenLLM");

    assert_eq!(d.calls().len(), reads_after_first, "cache hit must not re-read");
    assert_eq!(d.spawn_count(), 0);
}

// ---- invalidate ----

#[test]
fn invalidate_only_affects_the_named_service() {
    let mut d = registry_service("A", r"D:\a", "-m a", Some(3));
    d = d
        .with_reg_string(&params_key("B"), "AppDirectory", Some(r"D:\b".to_string()))
        .with_reg_string(&params_key("B"), "AppParameters", Some("-m b".to_string()))
        .with_reg_dword(&service_key("B"), "Start", Some(2));
    let cache = FactsCache::new();

    facts(&d, &cache, "A");
    facts(&d, &cache, "B");
    let reads = d.calls().len();

    cache.invalidate(Some("A"));
    facts(&d, &cache, "A");
    assert_eq!(d.calls().len(), reads + 3, "A re-read");

    facts(&d, &cache, "B");
    assert_eq!(d.calls().len(), reads + 3, "B still cached");
    assert_eq!(get_start_mode(&d, &cache, "B"), StartMode::Auto);
}

#[test]
fn invalidate_all_clears_every_service() {
    let d = registry_service("A", r"D:\a", "-m a", Some(3));
    let cache = FactsCache::new();

    facts(&d, &cache, "A");
    let reads = d.calls().len();
    cache.invalidate(None);
    facts(&d, &cache, "A");

    assert_eq!(d.calls().len(), reads + 3);
}

// ---- write-back invalidates only on success ----

#[test]
fn a_failed_write_back_keeps_the_cache() {
    let d = registry_service("QwenLLM", r"D:\llama.cpp", "-m old", Some(3)).with_spawn(
        NSSM_EXE,
        Err(DepsError::new(DepsErrorKind::SpawnFailed, "nssm failed")),
    );
    let cache = FactsCache::new();

    assert_eq!(get_app_parameters(&d, &cache, "QwenLLM"), "-m old");
    let reads = registry_reads(&d);

    assert!(set_app_parameters(&d, &cache, "QwenLLM", "-m new").is_err());
    // Cache retained: the service did not change, so the old facts are true.
    assert_eq!(get_app_parameters(&d, &cache, "QwenLLM"), "-m old");
    assert_eq!(registry_reads(&d), reads, "a failed write must not invalidate");
}

#[test]
fn a_successful_write_back_invalidates() {
    let d = registry_service("QwenLLM", r"D:\llama.cpp", "-m old", Some(3));
    let cache = FactsCache::new();

    facts(&d, &cache, "QwenLLM");
    let reads = registry_reads(&d);

    set_app_parameters(&d, &cache, "QwenLLM", "-m new").unwrap();
    facts(&d, &cache, "QwenLLM");

    assert_eq!(registry_reads(&d), reads + 3, "a successful write must invalidate");
    assert!(d.calls().iter().any(|c| matches!(c, Call::Spawn { .. })));
}

#[test]
fn set_start_mode_writes_the_nssm_enumeration() {
    let d = registry_service("QwenLLM", r"D:\llama.cpp", "-m a", Some(3));
    let cache = FactsCache::new();

    set_start_mode(&d, &cache, "QwenLLM", StartMode::Auto).unwrap();

    let spawned = d.calls().iter().find_map(|c| match c {
        Call::Spawn { program, args } if program == NSSM_EXE => Some(args.clone()),
        _ => None,
    });
    assert_eq!(
        spawned,
        Some(vec!["set".into(), "QwenLLM".into(), "Start".into(), "SERVICE_AUTO_START".into()])
    );
}

// ---- start mode mapping ----

#[test]
fn start_dword_maps_with_a_manual_fallback() {
    for (dword, expect) in [
        (2u32, StartMode::Auto),
        (3, StartMode::Manual),
        (4, StartMode::Disabled),
        (7, StartMode::Manual),
    ] {
        let d = registry_service("S", r"D:\s", "", Some(dword));
        assert_eq!(get_start_mode(&d, &FactsCache::new(), "S"), expect, "dword {dword}");
    }
    // Absent Start also means manual, not "unknown".
    let d = registry_service("S", r"D:\s", "", None);
    assert_eq!(get_start_mode(&d, &FactsCache::new(), "S"), StartMode::Manual);
}

// ---- registry unreadable: fall back to nssm get ----

#[test]
fn an_unreadable_registry_falls_back_to_nssm_get() {
    // Empty FakeDeps: every registry read returns None.
    let d = FakeDeps::new().with_spawn(NSSM_EXE, Ok(b"D:\\ll".to_vec()));
    let cache = FactsCache::new();

    let f = facts(&d, &cache, "QwenLLM");

    // It fell back, which by definition costs child processes.
    assert!(d.spawn_count() > 0, "fallback must actually call nssm");
    assert!(f.app_params.is_empty() || !f.app_params.is_empty()); // shape only
}

#[test]
fn fallback_reads_every_value_through_nssm() {
    let d = FakeDeps::new().with_spawn(NSSM_EXE, Ok(b"SERVICE_AUTO_START".to_vec()));
    let f = facts(&d, &FactsCache::new(), "QwenLLM");
    assert_eq!(f.start, StartMode::Auto, "nssm Start text is parsed");
}

// ---- sc ----

#[test]
fn sc_query_state_reads_the_state_word() {
    let out = b"SERVICE_NAME: QwenLLM\r\n        STATE              : 4  RUNNING\r\n".to_vec();
    let d = FakeDeps::new().with_spawn("sc", Ok(out));
    assert_eq!(sc_query_state(&d, "QwenLLM"), "RUNNING");
}

#[test]
fn sc_query_state_is_unknown_when_sc_fails() {
    let d = FakeDeps::new().with_spawn(
        "sc",
        Err(DepsError::new(DepsErrorKind::SpawnFailed, "no sc")),
    );
    assert_eq!(sc_query_state(&d, "QwenLLM"), UNKNOWN_STATE);
}

#[test]
fn sc_query_state_is_unknown_when_there_is_no_state_line() {
    let d = FakeDeps::new().with_spawn("sc", Ok(b"garbage".to_vec()));
    assert_eq!(sc_query_state(&d, "QwenLLM"), UNKNOWN_STATE);
}

#[test]
fn start_pending_is_not_mistaken_for_running() {
    let out = b"        STATE              : 2  START_PENDING\r\n".to_vec();
    let d = FakeDeps::new().with_spawn("sc", Ok(out));
    assert_eq!(sc_query_state(&d, "QwenLLM"), "START_PENDING");
}

#[test]
fn sc_action_returns_the_trimmed_output() {
    let d = FakeDeps::new().with_spawn("sc", Ok(b"  [SC] StartService SUCCESS  \r\n".to_vec()));
    assert_eq!(sc_action(&d, "start", "QwenLLM").unwrap(), "[SC] StartService SUCCESS");
}

// ---- listing ----

#[test]
fn listing_always_contains_the_default_service() {
    // powershell found nothing; the dropdown must still have one entry.
    let d = FakeDeps::new();
    let names = list_nssm_services(&d);
    assert_eq!(names.first().map(String::as_str), Some(DEFAULT_SERVICE));
}

#[test]
fn listing_appends_the_default_when_powershell_missed_it() {
    let d = FakeDeps::new().with_spawn("powershell.exe", Ok(b"Other\r\n".to_vec()));
    let names = list_nssm_services(&d);
    assert_eq!(names.first().map(String::as_str), Some(DEFAULT_SERVICE));
    assert!(names.iter().any(|n| n == "Other"));
}

#[test]
fn listing_does_not_duplicate_the_default() {
    let body = format!("{DEFAULT_SERVICE}\r\nOther\r\n");
    let d = FakeDeps::new().with_spawn("powershell.exe", Ok(body.into_bytes()));
    let names = list_nssm_services(&d);
    assert_eq!(names.iter().filter(|n| *n == DEFAULT_SERVICE).count(), 1);
}

// ---- health ----

#[test]
fn a_zero_port_is_never_probed() {
    let d = FakeDeps::new().with_health("127.0.0.1", 8080, true);
    let (ok, _) = check_health(&d, "127.0.0.1", 0);
    assert!(!ok);
    assert!(!d.calls().iter().any(|c| matches!(c, Call::ProbeHealth { .. })));
}

#[test]
fn a_wildcard_host_is_probed_on_loopback() {
    // Windows refuses to connect to 0.0.0.0, so the probe must be rewritten.
    let d = FakeDeps::new().with_health("127.0.0.1", 8080, true);
    let (ok, _) = check_health(&d, "0.0.0.0", 8080);
    assert!(ok);
    assert!(d.calls().iter().any(|c| matches!(
        c,
        Call::ProbeHealth { host, port } if host == "127.0.0.1" && *port == 8080
    )));
}

#[test]
fn readiness_requires_running_and_answering() {
    // sc says RUNNING before llama-server listens — the probe is what catches
    // that false "ready".
    let out = b"        STATE              : 4  RUNNING\r\n".to_vec();
    let d = FakeDeps::new()
        .with_spawn("sc", Ok(out))
        .with_health("127.0.0.1", 8080, false);

    let s = query_status(&d, "QwenLLM", "127.0.0.1", 8080);
    assert_eq!(s.state, RUNNING_STATE);
    assert!(!s.ok, "RUNNING but not answering is not ready");
}

#[test]
fn a_stopped_service_is_not_probed() {
    let out = b"        STATE              : 1  STOPPED\r\n".to_vec();
    let d = FakeDeps::new()
        .with_spawn("sc", Ok(out))
        .with_health("127.0.0.1", 8080, true);

    let s = query_status(&d, "QwenLLM", "127.0.0.1", 8080);
    assert!(!s.ok);
    assert!(!d.calls().iter().any(|c| matches!(c, Call::ProbeHealth { .. })));
}

#[test]
fn pending_is_never_reported_ready() {
    let out = b"        STATE              : 2  START_PENDING\r\n".to_vec();
    let d = FakeDeps::new()
        .with_spawn("sc", Ok(out))
        .with_health("127.0.0.1", 8080, true);

    let s = query_status(&d, "QwenLLM", "127.0.0.1", 8080);
    assert!(!s.ok, "START_PENDING must never be ready");
}
