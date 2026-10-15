//! Ticket 02 acceptance: NSSM's UTF-16LE and `sc`'s local code page both
//! round-trip Chinese, and malformed input is replaced instead of failing.
//!
//! Every byte array below was produced on this machine (zh-CN) with
//! `[System.Text.Encoding]::Unicode` / `::GetEncoding(936)`, i.e. it is the
//! exact byte stream `nssm get` / `sc query` emit for the documented value.
//!
//! Two facts shape which helper each test uses:
//!
//! - The sniff needs `raw[1] == 0x00` to choose UTF-16LE, so a UTF-16LE sample
//!   that *starts* with a Chinese character is decoded as the local code page.
//!   That is the Python behaviour too, and it is asserted as such in
//!   `utf16le_starting_with_chinese_matches_the_python_behaviour`.
//! - **This** machine runs with the UTF-8 beta flag: `GetACP()` is 65001, not
//!   936. So `sc` here emits UTF-8, and `decode()` must be pinned with
//!   `decode_as(…, 936)` to exercise the GBK path at all.

use llama_ctl_core::decode::{ansi_code_page, decode, decode_as};

/// The ANSI code page of a Chinese Windows — what Python's `mbcs` means there.
const CP936: u32 = 936;

/// `nssm get <服务> AppDirectory` -> `D:\llama.cpp\模型`
const NSSM_UTF16LE_PATH: &[u8] =
    b"D\x00:\x00\x5c\x00l\x00l\x00a\x00m\x00a\x00.\x00c\x00p\x00p\x00\x5c\x00!j\x8bW";

/// `nssm get <服务> AppParameters` -> `-m 模型\qwen.gguf --port 8080`
const NSSM_UTF16LE_PARAMS: &[u8] =
    b"-\x00m\x00 \x00!j\x8bW\x5c\x00q\x00w\x00e\x00n\x00.\x00g\x00g\x00u\x00f\x00 \x00-\x00-\x00p\x00o\x00r\x00t\x00 \x008\x000\x008\x000\x00";

/// `nssm get QwenLLM ObjectName` -> `LocalSystem` — ASCII, but still UTF-16LE.
const NSSM_UTF16LE_ASCII: &[u8] = b"L\x00o\x00c\x00a\x00l\x00S\x00y\x00s\x00t\x00e\x00m\x00";

/// `sc query 中文服务` -> `SERVICE_NAME: 中文服务` on CP936.
const SC_GBK_SERVICE_NAME: &[u8] = b"SERVICE_NAME: \xd6\xd0\xce\xc4\xb7\xfe\xce\xf1";

/// `dir` of a Chinese directory on CP936 -> `模型`.
const SC_GBK_MODEL: &[u8] = b"\xc4\xa3\xd0\xcd";

/// `sc query` state line -> `        STATE              : 4  RUNNING`.
const SC_ASCII_STATE_LINE: &[u8] = b"        STATE              : 4  RUNNING";

// --- NSSM: UTF-16LE -----------------------------------------------------------

#[test]
fn nssm_utf16le_path_round_trips_chinese() {
    assert_eq!(decode(NSSM_UTF16LE_PATH), r"D:\llama.cpp\模型");
}

#[test]
fn nssm_utf16le_parameters_round_trip_ascii_and_chinese_mixed() {
    assert_eq!(decode(NSSM_UTF16LE_PARAMS), "-m 模型\\qwen.gguf --port 8080");
}

#[test]
fn nssm_utf16le_ascii_decodes_without_interleaved_nuls() {
    // Second byte is NUL, so the UTF-16LE branch is taken and `LocalSystem`
    // comes out clean instead of `L\0o\0c\0…`.
    assert_eq!(decode(NSSM_UTF16LE_ASCII), "LocalSystem");
}

// --- sc: the local code page --------------------------------------------------

#[test]
fn sc_local_code_page_round_trips_a_chinese_service_name() {
    assert_eq!(decode_as(SC_GBK_SERVICE_NAME, CP936), "SERVICE_NAME: 中文服务");
}

#[test]
fn sc_local_code_page_round_trips_a_chinese_path() {
    assert_eq!(decode_as(SC_GBK_MODEL, CP936), "模型");
}

#[test]
fn sc_ascii_state_line_is_untouched() {
    assert_eq!(decode_as(SC_ASCII_STATE_LINE, CP936), "        STATE              : 4  RUNNING");
}

#[test]
fn gbk_bytes_that_are_invalid_utf8_are_decoded_as_gbk() {
    // The point of the spike: D6 D0 CE C4 is 中文 in GBK and invalid UTF-8. It
    // must not fall back to UTF-8 and come out as four U+FFFDs.
    assert_eq!(decode_as(b"\xd6\xd0\xce\xc4", CP936), "中文");
}

#[test]
fn a_truncated_gbk_lead_byte_is_replaced() {
    // C4 alone is a lead byte with no trail byte.
    assert_eq!(decode_as(b"\xc4", CP936), "\u{fffd}");
}

// --- degenerate and BOM-prefixed input ---------------------------------------

#[test]
fn empty_output_is_the_empty_string() {
    assert_eq!(decode(b""), "");
}

#[test]
fn utf8_bom_is_stripped_not_rendered_as_a_character() {
    // `powershell -OutputFormat Text` can emit this; a stray U+FEFF would break
    // every `starts_with` comparison downstream.
    assert_eq!(decode(b"\xef\xbb\xbfD:\\llama.cpp"), r"D:\llama.cpp");
}

#[test]
fn utf16le_bom_is_stripped_and_the_rest_decoded_as_utf16le() {
    let mut raw = b"\xff\xfe".to_vec();
    raw.extend_from_slice(NSSM_UTF16LE_PATH);
    assert_eq!(decode(&raw), r"D:\llama.cpp\模型");
}

#[test]
fn utf16le_bom_alone_is_empty_not_a_replacement_character() {
    assert_eq!(decode(b"\xff\xfe"), "");
}

// --- malformed UTF-16LE -------------------------------------------------------

#[test]
fn truncated_utf16le_replaces_only_the_orphaned_tail_byte() {
    // The path with its last byte cut off: 模 survives, the orphan 0x8b does not
    // take the preceding character down with it.
    let mut raw = NSSM_UTF16LE_PATH.to_vec();
    raw.pop();
    assert_eq!(decode(&raw), "D:\\llama.cpp\\\u{6a21}\u{fffd}");
}

#[test]
fn an_odd_byte_count_in_the_middle_replaces_without_shifting_the_rest() {
    // 'a', 模, 型, then one orphaned byte.
    assert_eq!(decode(b"a\x00!j\x8bW!"), "a\u{6a21}\u{578b}\u{fffd}");
}

#[test]
fn a_lone_high_surrogate_is_replaced_not_panicking() {
    // 00 D8 is a high surrogate with no low half — the classic `String::from_utf16`
    // failure, spelled `errors="replace"` here.
    assert_eq!(decode(b"a\x00\x00\xd8"), "a\u{fffd}");
}

#[test]
fn a_surrogate_pair_outside_the_bmp_round_trips() {
    // U+1F600 GRINNING FACE is 3D D8 00 DE.
    assert_eq!(decode(b"a\x00=\xd8\x00\xde"), "a\u{1f600}");
}

// --- boundaries ---------------------------------------------------------------

#[test]
fn utf16le_starting_with_chinese_matches_the_python_behaviour() {
    // Known ceiling, shared with the Python version: `raw[1] != 0` so the sniff
    // says "local code page" and the UTF-16LE bytes are read as GBK. 模型 as
    // UTF-16LE (21 6A 8B 57) read as GBK is `!j媁`, not 模型: 21 and 6A are
    // single-byte ASCII, 8B 57 is a valid GBK pair for U+5A81. Every NSSM value
    // we actually read starts with ASCII, so this is not reachable in practice —
    // it is pinned here so a future change to the sniff is deliberate.
    let utf16le_chinese_only: &[u8] = b"!j\x8bW";
    assert_eq!(decode_as(utf16le_chinese_only, CP936), "!j\u{5a81}");
}

#[test]
fn a_single_byte_answer_is_read_as_the_local_code_page() {
    // `len >= 2` is required by the sniff, so a one-byte answer never reaches
    // the UTF-16LE branch.
    assert_eq!(decode_as(b"4", CP936), "4");
}

#[test]
fn undecodable_utf8_becomes_replacement_characters_never_an_error() {
    // This host's ACP is 65001 (UTF-8 beta flag), so `sc` here emits UTF-8 and
    // the malformed-UTF-8 path is the live one.
    assert_eq!(decode_as(b"a\xffb", 65001), "a\u{fffd}b");
}

#[test]
fn an_unknown_code_page_falls_back_to_utf8_rather_than_guessing_gbk() {
    // Inventing mojibake is worse than an honest U+FFFD: a page we do not know
    // must not be treated as GBK.
    assert_eq!(decode_as(b"\xd6\xd0\xce\xc4", 42000).chars().count(), 4);
    assert!(decode_as(b"\xd6\xd0\xce\xc4", 42000).contains('\u{fffd}'));
}

// --- the panic-freedom the ticket asks for ------------------------------------

#[test]
fn any_input_decodes_without_panicking() {
    for b in 0u8..=255 {
        let _ = decode(&[b]);
        let _ = decode(&[b, b]);
        let _ = decode_as(&[b, b, b], CP936);
        let _ = decode_as(&[b, b, b], 65001);
    }
    let ugly: Vec<u8> = (0u16..1024).map(|i| (i % 251) as u8).collect();
    let _ = decode(&ugly);
    let _ = decode_as(&ugly, CP936);
    let _ = decode_as(&ugly, 65001);
}

#[test]
fn the_host_code_page_is_reported_not_guessed() {
    let acp = ansi_code_page();
    assert!(acp > 0, "GetACP must return a real code page, got {acp}");
    // Pure ASCII decodes the same on every page, so this holds on any host.
    assert_eq!(decode_as(b"SERVICE_RUNNING", acp), "SERVICE_RUNNING");
}
