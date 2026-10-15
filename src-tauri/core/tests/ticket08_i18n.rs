//! Ticket 08 acceptance: Rust is the single source of truth for bilingual copy.
//!
//! The invariants are asserted over the whole table, not per key, so adding a
//! key cannot silently skip its translation — the same guarantee
//! `tests/test_strings.py` gives the Python table.

use std::collections::{BTreeSet, HashSet};
use std::sync::{Mutex, MutexGuard};

use llama_ctl_core::i18n::{Lang, STRINGS, entry, fmt, set_language, set_language_code, snapshot, t, t_in};

/// The active language is process-global, and `cargo test` runs the cases in
/// one binary concurrently. Every test that reads or writes it takes this
/// first, so the assertions cannot observe another case's language.
static LANG_LOCK: Mutex<()> = Mutex::new(());

fn lock() -> MutexGuard<'static, ()> {
    LANG_LOCK.lock().unwrap_or_else(|e| e.into_inner())
}

fn set(lang: Lang) {
    set_language(lang);
}

/// Placeholder names inside `{...}` — `upd.done` uses `{s}` and `{b}`, etc.
fn placeholders(s: &str) -> BTreeSet<&str> {
    let b = s.as_bytes();
    let mut out = BTreeSet::new();
    let mut i = 0;
    while i < b.len() {
        if b[i] != b'{' {
            i += 1;
            continue;
        }
        let Some(end) = s[i..].find('}').map(|e| i + e) else {
            break;
        };
        let name = &s[i + 1..end];
        if !name.is_empty() && name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
            out.insert(name);
        }
        i = end + 1;
    }
    out
}

// ---- completeness: asserted over the table, not a hand-picked key list ----

#[test]
fn every_key_resolves_in_both_languages_and_neither_side_is_blank() {
    for (key, zh, en) in STRINGS {
        assert!(!zh.is_empty(), "{key} has an empty zh string");
        assert!(!en.is_empty(), "{key} has an empty en string");
        assert_eq!(t_in(key, Lang::Zh), Some(*zh), "{key} zh lookup mismatch");
        assert_eq!(t_in(key, Lang::En), Some(*en), "{key} en lookup mismatch");
    }
}

#[test]
fn no_key_appears_twice() {
    // A duplicate would make "which translation wins" order-dependent.
    let mut seen: HashSet<&str> = HashSet::new();
    for (key, _, _) in STRINGS {
        assert!(seen.insert(key), "duplicate key: {key}");
    }
}

#[test]
fn keys_keep_the_namespace_dot_name_shape() {
    for (key, _, _) in STRINGS {
        // `browse` is a real bare key in `strings.py`; any key with a dot must
        // be `namespace.name` with both halves non-empty.
        let mut parts = key.split('.');
        let ns = parts.next().unwrap_or_default();
        assert!(!ns.is_empty(), "key {key} is blank");
        if key.contains('.') {
            let name = parts.next().unwrap_or_default();
            assert!(!name.is_empty(), "key {key} has no name after the namespace");
        }
    }
}

#[test]
fn zh_and_en_placeholders_are_identical() {
    // Switching language must never need a different argument set.
    for (key, zh, en) in STRINGS {
        assert_eq!(placeholders(zh), placeholders(en), "{key} placeholder sets differ");
    }
}

#[test]
fn a_snapshot_covers_every_key_and_matches_single_lookups() {
    for lang in Lang::ALL {
        let snap = snapshot(lang);
        assert_eq!(snap.len(), STRINGS.len(), "snapshot dropped or invented keys");
        for (key, _, _) in STRINGS {
            assert_eq!(snap.get(key).copied(), t_in(key, lang), "{key} differs in snapshot");
        }
    }
}

#[test]
fn the_table_covers_the_namespaces_the_ticket_names() {
    // Proof the ported subset is the real one: buttons, service rows, log
    // lines, the whole update section and the parameter explanations.
    for ns in ["btn", "svc", "log", "upd", "param"] {
        let prefix = format!("{ns}.");
        assert!(STRINGS.iter().any(|(k, _, _)| k.starts_with(&prefix)), "no keys in namespace {ns}");
    }
    for key in ["btn.start", "btn.stop", "btn.restart", "svc.label", "log.collapsed", "upd.section", "upd.done"] {
        assert!(entry(key).is_some(), "expected real key {key} to be ported");
    }
}

// ---- fallback for a missing key ----

#[test]
fn a_missing_key_renders_itself_never_blank() {
    let _g = lock();
    for lang in Lang::ALL {
        set(lang);
        let missing = "btn.does.not.exist";
        assert_eq!(t(missing), missing, "missing key must show the key, not blank");
        assert!(!t(missing).is_empty());
        assert_eq!(t(""), "?", "an empty key has nothing to echo");
    }
    set(Lang::Zh);
}

#[test]
fn a_missing_key_is_visible_in_every_lookup_path() {
    // The fallback is one rule inside `t`, so `fmt` inherits it: a missing key
    // cannot slip through as a blank formatted string either.
    let _g = lock();
    set(Lang::En);
    assert_eq!(fmt("upd.nope", &[]), "upd.nope");
    assert_eq!(fmt("upd.nope", &[("x", "1")]), "upd.nope");
    set(Lang::Zh);
}

// ---- switching language ----

#[test]
fn switching_language_changes_output() {
    let _g = lock();
    set(Lang::Zh);
    let zh = t("btn.start");
    set(Lang::En);
    let en = t("btn.start");
    assert_ne!(zh, en, "a translated key must actually change: {zh} / {en}");
    assert_eq!(zh, "启动");
    assert_eq!(en, "Start");
    set(Lang::Zh);
    assert_eq!(t("btn.start"), "启动", "switching back restores zh");
}

#[test]
fn every_non_param_key_shifts_between_languages() {
    // No zh/en pair was copy-pasted by accident — except the `param.*` ones,
    // which are meant to be identical.
    let mut checked = 0;
    for (key, zh, en) in STRINGS {
        if key.starts_with("param.") {
            continue;
        }
        assert_ne!(zh, en, "{key} is untranslated outside param.*");
        checked += 1;
    }
    assert!(checked > 50, "expected a meaningful ported subset, got {checked}");
}

#[test]
fn the_language_code_round_trips_and_an_unknown_code_falls_back_to_zh() {
    let _g = lock();
    assert_eq!(Lang::from_code("zh"), Some(Lang::Zh));
    assert_eq!(Lang::from_code("en"), Some(Lang::En));
    assert_eq!(set_language_code("en"), Lang::En);
    assert_eq!(t("svc.label"), "Svc");
    assert_eq!(set_language_code("klingon"), Lang::Zh, "unknown code must not blank the UI");
    assert_eq!(t("svc.label"), "服务");
}

// ---- parameter explanations stay Chinese in English mode ----

#[test]
fn parameter_explanations_stay_chinese_in_english_mode() {
    let _g = lock();
    set(Lang::En);
    let mut checked = 0;
    for (key, zh, en) in STRINGS {
        if !key.starts_with("param.") {
            continue;
        }
        assert_eq!(zh, en, "{key} must be identical in both languages");
        assert!(zh.chars().any(|c| c as u32 > 0x2FFF), "{key} is not Chinese: {zh}");
        assert_eq!(t(key), *zh, "{key} did not stay Chinese in en mode");
        checked += 1;
    }
    assert!(checked >= 5, "expected several param keys, got {checked}");
    set(Lang::Zh);
}

#[test]
fn a_real_help_key_is_chinese_under_both_languages() {
    // Spot check that the rule holds for an actual explanation string.
    let _g = lock();
    for lang in Lang::ALL {
        set(lang);
        let text = t("param.help.ngl");
        assert!(text.contains("显存"), "help text changed language: {text}");
    }
    set(Lang::Zh);
}

// ---- fmt ----

#[test]
fn placeholders_are_filled_in_both_languages() {
    let _g = lock();
    set(Lang::Zh);
    assert_eq!(fmt("upd.done", &[("s", "QwenLLM"), ("b", "10819")]), "更新完成：QwenLLM 已重启，当前 b10819。");
    set(Lang::En);
    assert_eq!(fmt("upd.done", &[("s", "QwenLLM"), ("b", "10819")]), "Update complete: QwenLLM restarted, now b10819.");
    set(Lang::Zh);
}

#[test]
fn an_unsupplied_placeholder_stays_visible_instead_of_vanishing() {
    let _g = lock();
    set(Lang::En);
    assert_eq!(fmt("upd.done", &[("s", "QwenLLM")]), "Update complete: QwenLLM restarted, now b{b}.");
    set(Lang::Zh);
}

#[test]
fn fmt_leaves_text_without_placeholders_alone() {
    let _g = lock();
    set(Lang::En);
    assert_eq!(fmt("upd.section", &[]), "Official updates");
    assert_eq!(fmt("log.restart.start", &[("x", "1")]), ">>> Starting...");
    set(Lang::Zh);
}
