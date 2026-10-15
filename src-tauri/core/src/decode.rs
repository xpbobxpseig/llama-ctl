//! Lossy decoding of child-process stdout (ticket 02).
//!
//! NSSM writes UTF-16LE; `sc`, `reg` and friends write the local code page
//! (GBK on a Chinese Windows). This is the single place those bytes become a
//! `String`, and it never fails: malformed input becomes U+FFFD, exactly like
//! Python's `errors="replace"` in `nssm_adapter._run`.
//!
//! Crate chosen: `encoding_rs` (the WHATWG Encoding Standard decoder Firefox
//! uses). It is the only Rust decoder that replaces malformed sequences in
//! *every* encoding, not just UTF-8, so UTF-16LE, GBK and the rest of the
//! Windows ANSI code pages share one code path. `String::from_utf8_lossy`
//! would only cover the UTF-8 half, and hand-rolled GBK tables would be a
//! second implementation to keep in sync with a spec we did not write.
//!
//! See `## Resolution` in
//! `.scratch/tauri2-migration/issues/02-spike-windows-decoding.md` for the
//! justification and the known boundaries.

#[cfg(windows)]
unsafe extern "system" {
    // kernel32 is in the default link set for every `*-pc-windows-*` target,
    // so asking the OS for its ANSI code page costs no dependency.
    fn GetACP() -> u32;
}

use encoding_rs::{UTF_16LE, UTF_8, Encoding};

/// Decode `raw` child-process stdout into text, lossily. Never fails, never
/// panics, never returns an error.
///
/// Sniffing rule, in order:
///
/// 1. a UTF-8 / UTF-16LE / UTF-16BE BOM decides it outright — a BOM is
///    authoritative, and the Python version has no rule for one;
/// 2. otherwise `raw[1] == 0x00` means UTF-16LE — byte-for-byte the Python
///    rule `raw[1:2] == b"\x00"`;
/// 3. otherwise the local ANSI code page, i.e. Python's `mbcs`.
///
/// `ponytail:` steps 2-3 are a two-byte heuristic with a known ceiling:
/// UTF-16LE output whose *first* character is non-ASCII (so `raw[1] != 0`) is
/// decoded as the local code page and comes out as mojibake, and a one-byte
/// answer is always read as the local code page. Both are also true of the
/// Python version and neither bites us — every NSSM value we read is a path, a
/// flag or an account name, so it starts with ASCII. Upgrade path if that ever
/// breaks: pass the expected encoding per command; do not add more sniffing.
pub fn decode(raw: &[u8]) -> String {
    decode_as(raw, ansi_code_page())
}

/// `decode`, with the ANSI code page pinned instead of read from the OS.
///
/// Exists because the answer depends on the host: `sc` emits CP936 on a Chinese
/// Windows, CP932 on a Japanese one, and UTF-8 on a box with the UTF-8 beta
/// flag set. Tests that assert GBK bytes must not silently start passing or
/// failing because the machine they ran on changed.
pub fn decode_as(raw: &[u8], ansi_code_page: u32) -> String {
    let (encoding, bytes) = sniff(raw, ansi_code_page);
    let (cow, _) = encoding.decode_without_bom_handling(bytes);
    cow.into_owned()
}

/// The ANSI code page of this machine — what Python's `mbcs` resolves to.
#[cfg(windows)]
pub fn ansi_code_page() -> u32 {
    // SAFETY: parameterless syscall, no preconditions, cannot fail.
    unsafe { GetACP() }
}

/// Tests and CI only: the deployment target is a Chinese Windows.
#[cfg(not(windows))]
pub fn ansi_code_page() -> u32 {
    936
}

/// Returns the encoding plus the input with any BOM removed.
fn sniff(raw: &[u8], ansi_code_page: u32) -> (&'static Encoding, &[u8]) {
    match Encoding::for_bom(raw) {
        Some((encoding, bom_len)) => (encoding, &raw[bom_len..]),
        None if raw.len() >= 2 && raw[1] == 0x00 => (UTF_16LE, raw),
        None => (local_encoding(ansi_code_page), raw),
    }
}

/// The encoding `mbcs` means for a given ANSI code page. Every page Windows
/// ships as an ANSI default is covered; anything else — including 65001, the
/// UTF-8 code page, and 0, "undetermined" — degrades to UTF-8, which is
/// lossless for ASCII and replaces the rest rather than inventing mojibake.
fn local_encoding(ansi_code_page: u32) -> &'static Encoding {
    let label = match ansi_code_page {
        936 | 20936 => "gbk",
        950 => "big5",
        932 => "shift-jis",
        949 | 51949 => "euc-kr",
        874 => "windows-874",
        1250 => "windows-1250",
        1251 => "windows-1251",
        1252 => "windows-1252",
        1253 => "windows-1253",
        1254 => "windows-1254",
        1255 => "windows-1255",
        1256 => "windows-1256",
        1257 => "windows-1257",
        1258 => "windows-1258",
        _ => "utf-8",
    };
    Encoding::for_label(label.as_bytes()).unwrap_or(UTF_8)
}
