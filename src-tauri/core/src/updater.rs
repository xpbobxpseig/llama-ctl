//! Official updater, discovery half (ticket 05).
//!
//! Port of `updater.py`: build variants, GitHub Releases HTML scraping, asset
//! selection, and installed-build parsing. Every fetch goes through
//! [`Deps::http_get`], every child process through [`Deps::spawn`], so the
//! whole module is testable offline.
//!
//! Deliberately not here: download / extract / backup — that is ticket 06.

use std::path::Path;

use serde::Serialize;

use crate::deps::{AppError, AppErrorKind, Deps};

pub const RELEASES_PAGE: &str = "https://github.com/ggml-org/llama.cpp/releases";
pub const RELEASES_BASE: &str = "https://github.com/ggml-org/llama.cpp/releases/";
pub const DEFAULT_CHANNEL: &str = "win-cuda-13.4-x64";

/// Variants upstream stopped publishing. Old `settings.json` files still carry
/// these ids; [`resolve_variant`] must fold them onto the default instead of
/// failing the check forever (the b11201–b11213 cuda-13.3 outage).
pub const RETIRED_CHANNELS: &[&str] = &["win-cuda-13.3-x64"];

/// One downloadable file of a release.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Asset {
    pub name: String,
    /// Absolute download URL (`browser_download_url` in the Python dict).
    pub url: String,
}

/// A release that carries at least one asset for the wanted variant.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Release {
    pub tag: String,
    pub name: String,
    pub html_url: String,
    pub body: String,
    pub build: u32,
    pub published_at: String,
    pub assets: Vec<Asset>,
}

/// The four Windows binary variants we offer.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum Variant {
    Cuda134,
    Cuda124,
    Cpu,
    Vulkan,
}

impl Variant {
    /// All offered variants, in the order the UI shows them.
    pub const ALL: [Variant; 4] = [Variant::Cuda134, Variant::Cuda124, Variant::Cpu, Variant::Vulkan];
    pub const DEFAULT: Variant = Variant::Cuda134;

    /// The channel id, i.e. the `-bin-` suffix segment it matches in asset names.
    pub fn id(self) -> &'static str {
        match self {
            Variant::Cuda134 => "win-cuda-13.4-x64",
            Variant::Cuda124 => "win-cuda-12.4-x64",
            Variant::Cpu => "win-cpu-x64",
            Variant::Vulkan => "win-vulkan-x64",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Variant::Cuda134 => "CUDA 13.4 (x64)",
            Variant::Cuda124 => "CUDA 12.4 (x64)",
            Variant::Cpu => "CPU (x64)",
            Variant::Vulkan => "Vulkan (x64)",
        }
    }

    pub fn from_id(id: &str) -> Option<Variant> {
        Variant::ALL.into_iter().find(|v| v.id() == id)
    }
}

impl std::fmt::Display for Variant {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.id())
    }
}

/// `(id, label)` for every offered variant — what the dropdown is built from.
pub fn channels() -> [(&'static str, &'static str); 4] {
    Variant::ALL.map(|v| (v.id(), v.label()))
}

/// The variant a stored setting means: anything unknown or retired (an id
/// upstream no longer publishes) resolves to the default rather than failing.
pub fn resolve_variant(persisted: Option<&str>) -> Variant {
    persisted.and_then(Variant::from_id).unwrap_or(Variant::DEFAULT)
}

/// Build number inside a release tag (`b10819` -> 10819); `None` for stable
/// tags like `v0.4.0`, which never carry the nightly zips.
pub fn parse_build(tag: &str) -> Option<u32> {
    let b = tag.as_bytes();
    for i in 0..b.len() {
        if b[i] != b'b' {
            continue;
        }
        let mut end = i + 1;
        while end < b.len() && b[end].is_ascii_digit() {
            end += 1;
        }
        if end > i + 1 {
            return tag[i + 1..end].parse().ok();
        }
    }
    None
}

/// Build number inside `llama-server --version` output:
/// `version: 0.4.0-dev (build 10813, commit 4acf4a4cb)` -> 10813.
pub fn parse_version_output(text: &str) -> Option<u32> {
    let needle = "build";
    let mut rest = text;
    while let Some(at) = rest.find(needle) {
        let after = &rest[at + needle.len()..];
        let ws: usize = after.chars().take_while(|c| c.is_whitespace()).map(char::len_utf8).sum();
        let digits: String = after[ws..].chars().take_while(|c| c.is_ascii_digit()).collect();
        if ws > 0 && !digits.is_empty() {
            return digits.parse().ok();
        }
        rest = after;
    }
    None
}

/// Build number of the installed `llama-server.exe`, or `None` ("unknown") when
/// the exe is missing, fails to run, or prints nothing we can parse.
///
/// Python pre-checks `os.path.isfile`; `Deps` has no such probe, so a spawn
/// failure (which is what a missing exe produces) covers that case too.
pub fn get_installed_build(d: &impl Deps, exe_path: &Path) -> Option<u32> {
    if exe_path.as_os_str().is_empty() {
        return None;
    }
    let out = d.spawn(&exe_path.to_string_lossy(), &["--version"]).ok()?;
    parse_version_output(&String::from_utf8_lossy(&out))
}

/// Every `href` of every `<a>` in the page, in document order.
///
/// Hand-rolled because there is no HTML parser in stdlib and adding one is not
/// worth a dependency: it handles quoted/unquoted attribute values and entities,
/// enough for GitHub's own markup.
pub fn page_links(html: &str) -> Vec<String> {
    let b = html.as_bytes();
    let mut links = Vec::new();
    let mut i = 0;
    while i < b.len() {
        if b[i] != b'<' {
            i += 1;
            continue;
        }
        if html[i..].starts_with("<!--") {
            match html[i + 4..].find("-->") {
                Some(end) => i = i + 4 + end + 3,
                None => break,
            }
            continue;
        }
        let mut j = i + 1;
        if j < b.len() && b[j] == b'/' {
            j += 1;
        }
        let name_start = j;
        while j < b.len() && (b[j].is_ascii_alphanumeric() || b[j] == b'!') {
            j += 1;
        }
        let name = html[name_start..j].to_ascii_lowercase();
        let mut href = None;
        let mut k = j;
        while k < b.len() && b[k] != b'>' {
            if b[k].is_ascii_whitespace() {
                k += 1;
                continue;
            }
            let attr_start = k;
            while k < b.len() && !b[k].is_ascii_whitespace() && b[k] != b'=' && b[k] != b'>' {
                k += 1;
            }
            let attr = html[attr_start..k].to_ascii_lowercase();
            while k < b.len() && b[k].is_ascii_whitespace() {
                k += 1;
            }
            let mut value = String::new();
            if k < b.len() && b[k] == b'=' {
                k += 1;
                while k < b.len() && b[k].is_ascii_whitespace() {
                    k += 1;
                }
                if k < b.len() && (b[k] == b'"' || b[k] == b'\'') {
                    let quote = b[k];
                    k += 1;
                    let value_start = k;
                    while k < b.len() && b[k] != quote {
                        k += 1;
                    }
                    value = decode_entities(&html[value_start..k]);
                    if k < b.len() {
                        k += 1;
                    }
                } else {
                    let value_start = k;
                    while k < b.len() && !b[k].is_ascii_whitespace() && b[k] != b'>' {
                        k += 1;
                    }
                    value = decode_entities(&html[value_start..k]);
                }
            }
            // Python does `dict(attrs)`, so a repeated href keeps the last one.
            if attr == "href" && !value.is_empty() {
                href = Some(value);
            }
        }
        if name == "a"
            && let Some(href) = href {
                links.push(href);
            }
        i = if k < b.len() { k + 1 } else { k };
    }
    links
}

/// The zips this variant needs from a release: the main binary and, for CUDA
/// variants, the runtime zip. Exact name match — otherwise `arm64` or another
/// CUDA version is picked up by accident. Empty when the tag carries no build
/// number (stable releases have none of these assets).
pub fn select_assets(tag: &str, assets: &[Asset], variant: Variant) -> Vec<Asset> {
    let build = match parse_build(tag) {
        Some(b) => b,
        None => return Vec::new(),
    };
    let ch = variant.id();
    let wanted = [
        format!("llama-b{build}-bin-{ch}.zip"),
        format!("cudart-llama-bin-{ch}.zip"),
        format!("cudart-llama-b{build}-bin-{ch}.zip"),
    ];
    assets.iter().filter(|a| wanted.contains(&a.name)).cloned().collect()
}

/// Newest nightly on the releases page that actually ships this variant.
///
/// Tags are tried newest-first; a newer tag without the variant's assets is
/// skipped (that is the normal case after upstream drops a CUDA version).
pub fn find_latest_release(d: &impl Deps, variant: Variant) -> Result<Release, AppError> {
    let page = http_text(d, RELEASES_PAGE)?;
    let mut tags: Vec<String> = Vec::new();
    for href in page_links(&page) {
        let path = url_path(&href);
        let rest = match path.strip_prefix("/ggml-org/llama.cpp/releases/tag/") {
            Some(r) => r,
            None => continue,
        };
        if rest.contains('/') {
            continue;
        }
        let tag = percent_decode(rest);
        if parse_build(&tag).is_some() && !tags.contains(&tag) {
            tags.push(tag);
        }
    }

    for tag in tags.iter().take(30) {
        let assets_page = http_text(d, &format!("{RELEASES_BASE}expanded_assets/{tag}"))?;
        let mut assets = Vec::new();
        for href in page_links(&assets_page) {
            let path = url_path(&href);
            let rest = match path.strip_prefix("/ggml-org/llama.cpp/releases/download/") {
                Some(r) => r,
                None => continue,
            };
            let mut parts = rest.splitn(2, '/');
            let (owner_tag, name) = match (parts.next(), parts.next()) {
                (Some(t), Some(n)) => (t, n),
                _ => continue,
            };
            if owner_tag.contains('/') || name.contains('/') {
                continue;
            }
            if percent_decode(owner_tag) != *tag {
                continue;
            }
            let url = if href.starts_with("http") {
                href.clone()
            } else {
                format!("https://github.com{path}")
            };
            assets.push(Asset { name: percent_decode(name), url });
        }

        let picked = select_assets(tag, &assets, variant);
        if !picked.is_empty() {
            return Ok(Release {
                tag: tag.clone(),
                name: tag.clone(),
                html_url: format!("{RELEASES_BASE}tag/{tag}"),
                body: String::new(),
                build: parse_build(tag).unwrap_or(0),
                published_at: String::new(),
                assets: picked,
            });
        }
    }

    Err(AppError::new(
        AppErrorKind::UpdateFailed,
        format!("GitHub Releases 页面中未找到匹配资产（channel: {}）", variant.id()),
    ))
}

/// `GET` a page as text. A network failure becomes a displayable `AppError`;
/// it never panics and never silently yields an empty page.
fn http_text(d: &impl Deps, url: &str) -> Result<String, AppError> {
    let body = d
        .http_get(url)
        .map_err(|e| AppError::new(AppErrorKind::UpdateFailed, e.message))?;
    Ok(String::from_utf8_lossy(&body).into_owned())
}

/// Path part of a URL: drop scheme+host and anything from `?`/`#` on.
fn url_path(href: &str) -> &str {
    let s = match href.find("://") {
        Some(at) => match href[at + 3..].find('/') {
            Some(slash) => &href[at + 3 + slash..],
            None => "/",
        },
        None => href,
    };
    let end = s.find(['?', '#']).unwrap_or(s.len());
    &s[..end]
}

fn percent_decode(s: &str) -> String {
    if !s.contains('%') {
        return s.to_string();
    }
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len()
            && let (Some(hi), Some(lo)) = (hex_digit(b[i + 1]), hex_digit(b[i + 2])) {
                out.push(hi * 16 + lo);
                i += 3;
                continue;
            }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn hex_digit(c: u8) -> Option<u8> {
    match c {
        b'0'..=b'9' => Some(c - b'0'),
        b'a'..=b'f' => Some(c - b'a' + 10),
        b'A'..=b'F' => Some(c - b'A' + 10),
        _ => None,
    }
}

fn decode_entities(s: &str) -> String {
    if !s.contains('&') {
        return s.to_string();
    }
    let mut out = String::with_capacity(s.len());
    let mut chars = s.chars();
    while let Some(c) = chars.next() {
        if c != '&' {
            out.push(c);
            continue;
        }
        let mut name = String::new();
        let mut closed = false;
        for n in chars.by_ref() {
            if n == ';' {
                closed = true;
                break;
            }
            name.push(n);
            if name.len() > 8 {
                break;
            }
        }
        let mapped = match name.as_str() {
            "amp" => Some('&'),
            "lt" => Some('<'),
            "gt" => Some('>'),
            "quot" => Some('"'),
            "apos" | "#39" | "#x27" => Some('\''),
            _ if name.starts_with('#') => {
                let n = if let Some(hex) = name.strip_prefix("#x").or_else(|| name.strip_prefix("#X")) {
                    u32::from_str_radix(hex, 16).ok()
                } else {
                    name[1..].parse().ok()
                };
                n.and_then(char::from_u32)
            }
            _ => None,
        };
        match mapped {
            Some(ch) => out.push(ch),
            None => {
                out.push('&');
                out.push_str(&name);
                if closed {
                    out.push(';');
                }
            }
        }
    }
    out
}
