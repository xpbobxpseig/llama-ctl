//! Ticket 03 acceptance, ported from `tests/test_params.py` (41 cases).
//!
//! These are behaviour tests, not implementation tests: they assert what
//! `AppParameters` text means and what gets written back, never the shape of
//! internal structures.

use std::collections::BTreeMap;

use llama_ctl_core::params::Field;
use llama_ctl_core::params::{build_params, parse_params, semantically_equal};

fn fields() -> Vec<Field> {
    vec![
        Field::slider("ctx_size", &["-c", "--ctx-size"], 512.0, 131072.0, 512.0, 4096.0),
        Field::slider("n_gpu_layers", &["-ngl", "--n-gpu-layers"], 0.0, 999.0, 1.0, 999.0),
        Field::slider("threads", &["-t", "--threads"], 1.0, 128.0, 1.0, 8.0),
        Field::slider("temp", &["--temp"], 0.0, 2.0, 0.01, 0.8),
        Field::combo("kv_type", &["--kv-cache-type"]),
        Field::check("no_mmap", &["--no-mmap"]),
        // A "defaults on" pair: absent means ON, so turning it off must emit
        // the negation explicitly or the running server keeps it on.
        Field::check_with_off("jinja", &["--jinja"], &["--no-jinja"]),
        Field::text("model", &["-m", "--model"]),
        Field::text("seed", &["-s", "--seed"]),
    ]
}

/// A user-filled form. Deliberately sparse: only the keys the user touched, so
/// assertions never depend on slider defaults being backfilled.
fn vals(pairs: &[(&str, &str)]) -> BTreeMap<String, String> {
    pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect()
}

fn build(pairs: &[(&str, &str)], extras: &[&str]) -> String {
    let e: Vec<String> = extras.iter().map(|s| s.to_string()).collect();
    build_params(&vals(pairs), &e, &fields())
}

fn parse(text: &str) -> (BTreeMap<String, String>, Vec<String>, Vec<String>) {
    parse_params(text, &fields())
}

fn eq(a: &str, b: &str) -> bool {
    semantically_equal(a, b, &fields())
}

// ---- split_args: CommandLineToArgvW byte-for-byte ----

#[test]
fn quoted_json_keeps_its_spaces() {
    let (_, extras, _) = parse(r#"--override-tensor "a b c""#);
    // Unknown field, so it lands in extras — still one token, spaces kept.
    assert_eq!(extras, vec!["--override-tensor", "a b c"]);
}

#[test]
fn backslash_paths_are_literal_not_escapes() {
    // No spaces, so no quotes are needed — quoting only what needs it is what
    // keeps values byte-identical on the way back in.
    let out = build(&[("model", r"F:\models\qwen.gguf")], &[]);
    assert!(out.contains(r"F:\models\qwen.gguf"), "backslashes intact: {out}");
    assert_eq!(parse(&out).0["model"], r"F:\models\qwen.gguf");
}

#[test]
fn a_path_with_spaces_gets_quoted_and_roundtrips() {
    let p = r"C:\Program Files\llama\m.gguf";
    let out = build(&[("model", p)], &[]);
    assert!(out.contains(r#""C:\Program Files\llama\m.gguf""#), "quoted: {out}");
    assert_eq!(parse(&out).0["model"], p);
}

#[test]
fn unc_prefix_is_not_doubled_by_the_quoter() {
    // An earlier quoter doubled every backslash; four leading backslashes here
    // would mean the UNC prefix had been silently rewritten.
    let out = build(&[("model", r"\\NAS\share\model.gguf")], &[]);
    assert!(out.contains(r#"\\NAS\share\model.gguf"#), "UNC intact: {out}");
}

#[test]
fn unc_prefix_survives_a_roundtrip() {
    let unc = r"\\NAS\share\model.gguf";
    let v = vals(&[("model", unc)]);
    let first = build_params(&v, &[], &fields());
    assert_eq!(parse(&first).0["model"], unc);
    assert_eq!(build_params(&v, &[], &fields()), first, "same form rebuilds identically");
}

#[test]
fn escaped_quote_and_literal_backslash_together() {
    let raw = r#"a\"b\c"#;
    assert_eq!(parse(&build(&[("model", raw)], &[])).0["model"], raw);
}

#[test]
fn unterminated_quote_and_empty_input_do_not_crash() {
    // CommandLineToArgvW swallows an unterminated quote to end of string;
    // we must not "repair" it.
    let _ = parse(r#"--model "unterminated"#);
    let _ = parse("");
    let _ = parse("   ");
}

// ---- negative numbers are values, not flags ----

#[test]
fn negative_seed_parses_as_a_value() {
    let (v, extras, _) = parse("--seed -1 --ctx-size 4096");
    assert_eq!(v["seed"], "-1");
    assert_eq!(v["ctx_size"], "4096");
    assert!(extras.is_empty());
}

#[test]
fn negative_value_within_range_is_kept() {
    let f = vec![Field::slider("z", &["--z"], -10.0, 10.0, 0.5, 0.0)];
    assert_eq!(parse_params("--z -2.5", &f).0["z"], "-2.5");
}

#[test]
fn negative_value_out_of_range_falls_back_like_any_other_value() {
    // -0.05 is genuinely outside temp's [0,2] range; the sign earns no
    // exemption from the range rule.
    let (v, _, w) = parse("--temp -0.05");
    assert_eq!(v["temp"], "0.8");
    assert_eq!(w.len(), 1);
}

#[test]
fn negative_value_survives_three_roundtrips() {
    let mut text = "--seed -1 --ctx-size 8192".to_string();
    for _ in 0..3 {
        let (v, e, _) = parse(&text);
        assert_eq!(v["seed"], "-1");
        text = build_params(&v, &e, &fields());
    }
    assert!(text.contains("--seed"));
}

#[test]
fn negative_form_of_a_pair_switch_is_the_field_not_an_extra() {
    let (v, extras, _) = parse("--no-jinja");
    assert_eq!(v["jinja"], "", "negation means off");
    assert!(extras.is_empty(), "negation must not leak into extras");
}

#[test]
fn last_form_of_a_pair_switch_wins() {
    assert_eq!(parse("--no-jinja --jinja").0["jinja"], "1");
}

#[test]
fn pair_switch_defaults_to_on_when_both_forms_absent() {
    // llama.cpp ships jinja ON; ticking it off must write the negation, or
    // "off" and "absent" are indistinguishable at runtime.
    assert_eq!(parse("--ctx-size 4096").0["jinja"], "1");
    assert_eq!(build(&[("jinja", "")], &[]), "--no-jinja");
}

#[test]
fn write_back_never_flips_a_recognized_switch() {
    // End-to-end regression for the bug where a recognised negation got moved
    // to the end of extras and therefore inverted at runtime.
    let (v, e, _) = parse("--jinja --no-mmap --ctx-size 4096");
    let (v2, _, _) = parse(&build_params(&v, &e, &fields()));
    assert_eq!(v["no_mmap"], v2["no_mmap"]);
    assert_eq!(v["jinja"], v2["jinja"]);
}

// ---- sliders ----

#[test]
fn missing_slider_fills_its_default_with_integer_step() {
    let v = parse("--model m.gguf").0;
    assert_eq!(v["ctx_size"], "4096");
    assert_eq!(v["n_gpu_layers"], "999");
    assert_eq!(v["threads"], "8");
}

#[test]
fn out_of_range_slider_falls_back_with_a_warning() {
    let (v, _, w) = parse("--ctx-size 999999");
    assert_eq!(v["ctx_size"], "4096");
    assert_eq!(w.len(), 1);
    assert!(w[0].contains("超出范围"));
}

#[test]
fn float_step_slider_keeps_decimals() {
    assert_eq!(parse("--temp 0.65").0["temp"], "0.65");
}

// ---- ctx conflict ----

#[test]
fn ctx_conflict_keeps_the_last_and_warns() {
    let (v, _, w) = parse("-c 4096 --ctx-size 131072");
    assert_eq!(v["ctx_size"], "131072");
    assert_eq!(w.len(), 1);
    assert!(w[0].contains("冲突"));
}

#[test]
fn a_single_ctx_emits_no_warning() {
    assert!(parse("--ctx-size 131072").2.is_empty());
}

// ---- check flags & extras ----

#[test]
fn check_flag_rebuilds_as_its_flag_and_jinja_stays_explicit() {
    // A real form always carries a value for every field, so set jinja
    assert_eq!(build(&[("jinja", "1"), ("no_mmap", "1")], &[]), "--no-mmap --jinja");
    assert_eq!(build(&[("jinja", ""), ("no_mmap", "1")], &[]), "--no-mmap --no-jinja");
    assert_eq!(build(&[("jinja", ""), ("no_mmap", "1")], &[]), "--no-mmap --no-jinja");
}

#[test]
fn unchecked_flag_is_omitted_on_build() {
    assert!(!build(&[("ctx_size", "4096")], &[]).contains("--no-mmap"));
}

#[test]
fn extras_roundtrip_preserves_order() {
    let e = parse("--foo A --bar B").1;
    assert_eq!(e, vec!["--foo", "A", "--bar", "B"]);
    let out = build_params(&vals(&[("ctx_size", "4096")]), &e, &fields());
    assert!(out.ends_with("--foo A --bar B"));
}

// ---- semantic equivalence ----

#[test]
fn alias_forms_are_equivalent() {
    assert!(eq("--ctx-size 4096", "-c 4096"));
}

#[test]
fn reordered_flags_are_equivalent() {
    assert!(eq("--ctx-size 4096 --no-mmap", "--no-mmap --ctx-size 4096"));
}

#[test]
fn omitted_slider_default_is_equivalent_to_explicit() {
    assert!(eq("--model m.gguf", "--model m.gguf --threads 8"));
}

#[test]
fn a_real_value_difference_is_not_equivalent() {
    assert!(!eq("--ctx-size 4096", "--ctx-size 8192"));
}

#[test]
fn toggling_a_check_flag_is_not_equivalent() {
    assert!(!eq("--no-mmap", ""));
}

#[test]
fn added_or_removed_extras_are_not_equivalent() {
    assert!(!eq("--foo A", "--foo A --bar B"));
}

#[test]
fn extras_position_relative_to_fields_is_irrelevant() {
    assert!(eq("--foo A --ctx-size 4096", "--ctx-size 4096 --foo A"));
}

#[test]
fn legacy_conflicting_form_is_equivalent_to_normalized() {
    assert!(eq("-c 4096 --ctx-size 4096", "--ctx-size 4096"));
}

#[test]
fn a_garbage_slider_value_is_not_equivalent_to_a_good_one() {
    // "abc" falls back to the default, so it must NOT compare equal to an
    // explicit non-default value — otherwise a typo would be silently accepted.
    assert!(!eq("--ctx-size abc", "--ctx-size 8192"));
}

#[test]
fn empty_and_empty_are_equivalent() {
    assert!(eq("", ""));
}
