//! Ticket 07 acceptance: presets & settings persistence in Rust.
//!
//! Ported from `tests/test_presets.py` and the persistence half of
//! `tests/test_preset_safety.py`. Everything runs against `FakeDeps`, so no
//! test touches a real disk and every side effect is assertable as a `Call`.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use llama_ctl_core::deps::AppErrorKind;
use llama_ctl_core::fake::{Call, FakeDeps};
use llama_ctl_core::persist::{
    Env, Presets, Settings, delete_preset, load_preset_values, load_presets, load_settings,
    resolve_presets_file, resolve_settings_file, save_preset, save_presets, save_settings,
    user_data_dir,
};

const APPDATA: &str = r"C:\Users\someone\AppData\Roaming";

/// A machine with `APPDATA` set and no overrides: the normal case.
fn env() -> Env {
    Env {
        appdata: Some(APPDATA.to_string()),
        ..Env::default()
    }
}

fn settings_path() -> PathBuf {
    PathBuf::from(APPDATA).join("llama-ctl").join("settings.json")
}

fn presets_path() -> PathBuf {
    PathBuf::from(APPDATA).join("llama-ctl").join("presets.json")
}

fn tmp_of(p: &Path) -> PathBuf {
    let mut os = p.as_os_str().to_os_string();
    os.push(".tmp");
    PathBuf::from(os)
}

fn values(pairs: &[(&str, &str)]) -> BTreeMap<String, String> {
    pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect()
}

// ---- location: ticket 00's convention, reproduced ----

#[test]
fn both_files_resolve_under_the_user_data_dir() {
    // %APPDATA%\llama-ctl\<basename> — the exact convention ticket 00 fixed on
    // the Python side. Diverging here would silently split the user's data
    // between the two builds.
    assert_eq!(
        resolve_settings_file(&env()),
        PathBuf::from(r"C:\Users\someone\AppData\Roaming\llama-ctl\settings.json")
    );
    assert_eq!(
        resolve_presets_file(&env()),
        PathBuf::from(r"C:\Users\someone\AppData\Roaming\llama-ctl\presets.json")
    );
    assert_eq!(
        user_data_dir(&env()),
        PathBuf::from(r"C:\Users\someone\AppData\Roaming\llama-ctl")
    );
}

#[test]
fn appdata_missing_falls_back_to_userprofile_roaming() {
    let env = Env {
        userprofile: Some(r"C:\Users\someone".to_string()),
        ..Env::default()
    };
    assert_eq!(
        resolve_settings_file(&env),
        PathBuf::from(r"C:\Users\someone\AppData\Roaming\llama-ctl\settings.json")
    );
}

#[test]
fn override_env_wins_over_the_user_data_dir() {
    // Same priority as Python: the override bypasses the user data dir
    // entirely.
    let env = Env {
        appdata: Some(APPDATA.to_string()),
        settings_override: Some(r"D:\custom\settings.json".to_string()),
        presets_override: Some(r"D:\custom\presets.json".to_string()),
        ..Env::default()
    };
    assert_eq!(resolve_settings_file(&env), PathBuf::from(r"D:\custom\settings.json"));
    assert_eq!(resolve_presets_file(&env), PathBuf::from(r"D:\custom\presets.json"));
}

#[test]
fn an_empty_override_counts_as_unset() {
    // Python's `os.environ.get()` treats "" as falsy; a set-but-empty variable
    // must not redirect writes to the current directory.
    let env = Env {
        appdata: Some(APPDATA.to_string()),
        presets_override: Some(String::new()),
        ..Env::default()
    };
    assert_eq!(resolve_presets_file(&env), presets_path());
}

#[test]
fn reads_and_writes_go_to_the_resolved_path() {
    let d = FakeDeps::new().with_file(settings_path(), br#"{"language": "en"}"#.to_vec());

    let _ = load_settings(&d, &env());

    assert_eq!(d.calls(), vec![Call::ReadFile(settings_path())]);
}

// ---- corrupt / missing files fall back ----

#[test]
fn missing_settings_file_is_all_defaults() {
    let d = FakeDeps::new();
    assert_eq!(load_settings(&d, &env()), Settings::default());
}

#[test]
fn corrupt_settings_json_is_all_defaults_without_panicking() {
    // "{ not json" is the 10-byte corruption the Python suite uses.
    let d = FakeDeps::new().with_file(settings_path(), b"{ not json".to_vec());
    assert_eq!(load_settings(&d, &env()), Settings::default());
}

#[test]
fn corrupt_settings_file_falls_back_per_key_not_wholesale() {
    // One wrong-typed key must not wipe the keys that are fine (and must not
    // wipe the ones that are absent either — they keep their default).
    let file = br#"{"language": "en", "appearance": "dark", "motion_enabled": "yes",
                    "upd_channel": 7, "services": ["A", 3, "B"], "unknown": 1}"#;
    let d = FakeDeps::new().with_file(settings_path(), file.to_vec());

    let got = load_settings(&d, &env());

    assert_eq!(got.language, "en", "a good key is kept");
    assert_eq!(got.appearance, "dark", "a good key is kept");
    assert!(got.motion_enabled, "wrong type falls back to the default, not to panic");
    assert_eq!(got.upd_channel, "win-cuda-13.4-x64", "wrong type falls back to the default");
    assert_eq!(got.services, vec!["A".to_string(), "B".to_string()], "non-strings dropped in place");
    assert_eq!(got.geometry, None, "absent key keeps its default");
    assert_eq!(got.last_preset, "", "absent key keeps its default");
}

#[test]
fn corrupt_and_non_object_presets_files_are_empty() {
    let corrupt = FakeDeps::new().with_file(presets_path(), b"{ not json".to_vec());
    assert_eq!(load_presets(&corrupt, &env()), Presets::new());

    // A JSON array is well-formed but is not a name -> values map.
    let array = FakeDeps::new().with_file(presets_path(), b"[1, 2, 3]".to_vec());
    assert_eq!(load_presets(&array, &env()), Presets::new());

    let missing = FakeDeps::new();
    assert_eq!(load_presets(&missing, &env()), Presets::new());
}

#[test]
fn a_preset_entry_that_is_not_an_object_is_skipped_not_fatal() {
    let file = br#"{"Good": {"model": "g.gguf"}, "Bad": 42}"#;
    let d = FakeDeps::new().with_file(presets_path(), file.to_vec());

    let got = load_presets(&d, &env());

    assert_eq!(got.len(), 1, "one bad entry must not discard the good ones");
    assert_eq!(got["Good"], values(&[("model", "g.gguf")]));
}

#[test]
fn every_load_reads_the_file_again() {
    // No cache: an external rewrite (even same size, same timestamp tick) must
    // be visible. This is the regression the Python suite pins with a counter.
    let d = FakeDeps::new().with_file(presets_path(), br#"{"a": {}}"#.to_vec());

    load_presets(&d, &env());
    load_presets(&d, &env());
    load_presets(&d, &env());

    assert_eq!(d.calls().iter().filter(|c| matches!(c, Call::ReadFile(_))).count(), 3);
}

// ---- atomic write ----

#[test]
fn a_save_writes_tmp_then_renames_over_the_target() {
    let d = FakeDeps::new();
    let tmp = tmp_of(&presets_path());

    save_presets(&d, &env(), &Presets::new()).unwrap();

    assert_eq!(
        d.calls(),
        vec![
            Call::CreateDirAll(PathBuf::from(r"C:\Users\someone\AppData\Roaming\llama-ctl")),
            Call::WriteFile(tmp.clone()),
            Call::RenameFile { from: tmp.clone(), to: presets_path() },
        ],
        "the target is only ever reached by a rename, never by a direct write"
    );
    assert_eq!(d.file(&tmp), None, "the temp file must not linger");
    assert!(d.file(&presets_path()).is_some());
}

#[test]
fn settings_save_writes_tmp_then_renames_and_creates_the_dir() {
    let d = FakeDeps::new();
    let tmp = tmp_of(&settings_path());

    save_settings(&d, &env(), &Settings::default()).unwrap();

    assert!(matches!(
        d.calls().last(),
        Some(Call::RenameFile { from, to }) if *from == tmp && *to == settings_path()
    ));
    assert_eq!(d.file(&tmp), None);
}

#[test]
fn a_failed_write_is_an_error_not_a_panic_and_cleans_up_the_tmp() {
    // Python returns (False, err): a read-only dir must surface a message the
    // user can see, not abort the process.
    let tmp = tmp_of(&presets_path());
    let d = FakeDeps::new().with_failing_write(&tmp);

    let err = save_presets(&d, &env(), &Presets::new()).unwrap_err();

    assert_eq!(err.kind, AppErrorKind::StorageFailed);
    assert!(!err.message.is_empty(), "the error carries a displayable reason");
    assert_eq!(d.file(&tmp), None, "no temp file left behind");
    assert_eq!(d.file(&presets_path()), None, "the previous file was never touched");
}

#[test]
fn a_failed_settings_save_is_an_error_not_a_panic() {
    let tmp = tmp_of(&settings_path());
    let d = FakeDeps::new().with_failing_write(&tmp);

    assert!(save_settings(&d, &env(), &Settings::default()).is_err());
}

// ---- presets: save / load / delete ----

#[test]
fn a_preset_round_trips_through_save_then_load() {
    let d = FakeDeps::new();
    let mut all = Presets::new();
    all.insert("Alpha".to_string(), values(&[("model", "a.gguf"), ("ctx_size", "4096")]));

    save_presets(&d, &env(), &all).unwrap();

    assert_eq!(load_presets(&d, &env()), all);
}

#[test]
fn a_single_preset_round_trips_through_save_then_load_single() {
    let d = FakeDeps::new();

    assert!(save_preset(&d, &env(), "Alpha", &values(&[("model", "a.gguf")])).unwrap());

    assert_eq!(
        load_preset_values(&d, &env(), "Alpha"),
        Some(values(&[("model", "a.gguf")]))
    );
}

#[test]
fn saving_an_existing_preset_name_is_a_no_op() {
    // The displayed name may be an auto-selected dropdown entry whose values
    // came from the service. Overwriting would destroy the user's preset.
    let file = br#"{"Alpha": {"model": "ALPHA.gguf"}}"#;
    let d = FakeDeps::new().with_file(presets_path(), file.to_vec());
    let before = d.file(&presets_path());

    let stored = save_preset(&d, &env(), "Alpha", &values(&[("model", "SERVICE.gguf")])).unwrap();

    assert!(!stored, "an existing name must report no-op, not success");
    assert_eq!(d.file(&presets_path()), before, "the existing preset must be byte-identical");
    assert!(
        !d.calls().iter().any(|c| matches!(c, Call::WriteFile(_))),
        "no write at all: the file was never rewritten"
    );
    assert_eq!(load_presets(&d, &env())["Alpha"], values(&[("model", "ALPHA.gguf")]));
}

#[test]
fn loading_a_preset_only_reads_the_file() {
    // "载入只填表单、不写服务": loading must not spawn, not write, not touch
    // the registry — only fill the form from the file.
    let file = br#"{"Alpha": {"model": "a.gguf"}}"#;
    let d = FakeDeps::new().with_file(presets_path(), file.to_vec());

    let got = load_preset_values(&d, &env(), "Alpha").unwrap();

    assert_eq!(got, values(&[("model", "a.gguf")]));
    assert_eq!(d.spawn_count(), 0, "loading must not touch the service");
    assert!(!d.calls().iter().any(|c| matches!(c, Call::WriteFile(_) | Call::RenameFile { .. })));
    assert!(d.calls().iter().all(|c| matches!(c, Call::ReadFile(_))));
}

#[test]
fn loading_an_unknown_preset_name_is_none() {
    let d = FakeDeps::new().with_file(presets_path(), br#"{"Alpha": {}}"#.to_vec());
    assert_eq!(load_preset_values(&d, &env(), "Nope"), None);
}

#[test]
fn delete_removes_only_the_named_preset() {
    let file = br#"{"Alpha": {"model": "a.gguf"}, "Beta": {"model": "b.gguf"}}"#;
    let d = FakeDeps::new().with_file(presets_path(), file.to_vec());

    assert!(delete_preset(&d, &env(), "Alpha").unwrap());

    let left = load_presets(&d, &env());
    assert_eq!(left.len(), 1);
    assert_eq!(left["Beta"], values(&[("model", "b.gguf")]));
}

#[test]
fn deleting_a_missing_preset_is_a_no_op_without_a_write() {
    let d = FakeDeps::new().with_file(presets_path(), br#"{"Alpha": {}}"#.to_vec());

    assert!(!delete_preset(&d, &env(), "Nope").unwrap());
    assert!(!d.calls().iter().any(|c| matches!(c, Call::WriteFile(_))));
}

// ---- settings round trip ----

#[test]
fn settings_round_trip_through_save_then_load() {
    let d = FakeDeps::new();
    let s = Settings {
        language: "en".to_string(),
        geometry: Some("1200x800+10+20".to_string()),
        motion_enabled: false,
        services: vec!["QwenLLM".to_string()],
        ..Settings::default()
    };

    save_settings(&d, &env(), &s).unwrap();

    assert_eq!(load_settings(&d, &env()), s);
    // Geometry `None` must come back as `None`, not as "" or "null".
    let plain = Settings::default();
    save_settings(&d, &env(), &plain).unwrap();
    assert_eq!(load_settings(&d, &env()), plain);
}
