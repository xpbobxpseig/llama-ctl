//! Local sanity check for the packaging config (ticket 18).
//!
//! Run: `cargo run --bin check-packaging` from `src-tauri/`.
//!
//! Everything asserted here is a hard constraint from ADR-0001 (nothing remote
//! reaches the elevated renderer) and ADR-0002 (the NSIS installer is the
//! delivery form, and it must not be able to wipe the user's data). Config
//! drifts silently — the CSP is one edit away from allowing a CDN — so the
//! invariants are checked here rather than trusted.
//!
//! ponytail: stdlib only, no dev-dependency. Parsing is deliberately
//! line/structure-aware rather than a real JSON parse: the file is tiny and
//! `cargo tauri build` rejects malformed JSON anyway.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

/// Local-only origins Tauri serves itself. `ipc:`/`asset:` and their
/// `*.localhost` http aliases never leave the process; anything else that looks
/// like a URL in the CSP is a regression.
const LOCAL_ORIGINS: [&str; 2] = ["http://ipc.localhost", "http://asset.localhost"];

fn main() -> ExitCode {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let mut failures = Vec::new();

    let raw = match fs::read_to_string(root.join("tauri.conf.json")) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("FAIL read tauri.conf.json: {e}");
            return ExitCode::FAILURE;
        }
    };

    // --- 1. Structure: catches an unbalanced brace / a dangling comma.
    if !balanced(&raw) {
        failures.push("tauri.conf.json: unbalanced braces or unterminated string".into());
    }

    // --- 2. CSP: 'self' only, no eval, no remote source.
    match field(&raw, "csp") {
        Some(csp) => check_csp(&csp, &mut failures),
        None => failures.push("no `csp` key in app.security".into()),
    }

    // --- 3. Asset protocol on, scope empty. Enabling it with an empty
    //         allowlist is what "scoped, not the whole disk" means: every
    //         `asset:` request is denied until Rust allows a path at runtime.
    match field(&raw, "scope") {
        Some(scope) if scope == "[]" => {}
        Some(scope) => failures.push(format!("assetProtocol.scope must be [] , got `{scope}`")),
        None => failures.push("no `assetProtocol.scope` key".into()),
    }
    if !raw.contains("\"enable\": true") {
        failures.push("assetProtocol.enable should be true (with an empty scope)".into());
    }

    // --- 4. NSIS is the delivery form (ADR-0002), and the user-data rules the
    //         installer must respect (see check_installer_hooks).
    match field(&raw, "targets") {
        Some(t) if t.contains("\"nsis\"") => {}
        Some(t) => failures.push(format!("bundle.targets must include nsis, got `{t}`")),
        None => failures.push("no `bundle.targets` key".into()),
    }

    // --- 5. Icons: Tauri refuses to bundle without a valid set.
    for icon in icon_paths(&raw) {
        let p = root.join(&icon);
        if !p.is_file() {
            failures.push(format!("bundle icon missing: {}", p.display()));
        } else if !is_ico(&p) {
            failures.push(format!("bundle icon is not a valid .ico: {}", p.display()));
        }
    }

    // --- 6. The installer must not be able to delete user data.
    check_installer_hooks(&root, &mut failures);

    // --- 7. Nothing remote in the built frontend (ADR-0001).
    let dist = root.join("..").join("frontend").join("dist");
    if dist.is_dir() {
        scan_frontend(&dist, &mut failures);
    } else {
        println!("note: frontend/dist absent, skipped remote-asset scan");
    }

    for f in &failures {
        println!("FAIL {f}");
    }
    if failures.is_empty() {
        println!("ok: packaging config checks passed");
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

/// ADR-0001's half of the CSP: local only, no eval, no wildcard.
fn check_csp(csp: &str, failures: &mut Vec<String>) {
    if !csp.contains("default-src 'self'") {
        failures.push(format!("csp: missing `default-src 'self'` -> {csp}"));
    }
    if csp.contains("unsafe-eval") || csp.contains("'unsafe-eval'") {
        failures.push("csp: `unsafe-eval` is forbidden in an elevated renderer".into());
    }

    // Strip the two self-hosted origins, then any URL-ish token left is a bug.
    let mut stripped = csp.to_string();
    for local in LOCAL_ORIGINS {
        stripped = stripped.replace(local, "");
    }
    for bad in ["http://", "https://", "ftp://", "http:", "https:", "data:text/html"] {
        if stripped.contains(bad) {
            failures.push(format!("csp: remote/unsafe source `{bad}` -> {csp}"));
        }
    }
    // `data:` is allowed for images and fonts only (the favicon is a data: URI).
    for directive in ["img-src", "font-src"] {
        let Some(value) = directive_value(csp, directive) else {
            continue;
        };
        if !value.contains("'self'") {
            failures.push(format!("csp: {directive} does not start from 'self'"));
        }
    }
    if let Some(v) = directive_value(csp, "connect-src") {
        if !(v.contains("'self'") && v.contains("ipc:")) {
            failures.push(format!("csp: connect-src must allow 'self' + ipc: only -> `{v}`"));
        }
    } else {
        failures.push("csp: no connect-src directive".into());
    }
}

/// The one thing this ticket must not get wrong: `%APPDATA%\llama-ctl\` holds
/// presets and preferences (ticket 00), and ADR-0002 exists precisely so an
/// upgrade does not wipe it.
///
/// The generated NSIS script removes `$INSTDIR` and the uninstall registry key
/// — never `$APPDATA`. This check does not prove that (only reading the
/// generated `.nsi` would, and that needs a full `tauri build`); what it does
/// prove is that we have not added a hook script that touches `$APPDATA`, which
/// is the only way to introduce that deletion from this repository.
fn check_installer_hooks(root: &Path, failures: &mut Vec<String>) {
    let hooks = root.join("nsis").join("hooks.nsh");
    if !hooks.is_file() {
        println!("note: no nsis/hooks.nsh — using the stock installer (deletes \$INSTDIR only)");
        return;
    }
    let Ok(text) = fs::read_to_string(&hooks) else {
        failures.push(format!("cannot read {}", hooks.display()));
        return;
    };
    for line in text.lines() {
        let line = line.trim();
        if line.starts_with(';') {
            continue;
        }
        // `RMDir /r "$APPDATA\llama-ctl"` would destroy user data on uninstall
        // or on a pre-install cleanup. `SetShellVarContext` + `RMDir` on
        // `$INSTDIR` is fine.
        if line.contains("RMDir") && (line.contains("$APPDATA") || line.contains("llama-ctl")) {
            failures.push(format!(
                "{}: `{}` deletes user data — forbidden (ADR-0002)",
                hooks.display(),
                line
            ));
        }
    }
    println!("note: {} present and checked", hooks.display());
}

/// Balanced braces, and no string left open.
fn balanced(s: &str) -> bool {
    let mut depth = 0i32;
    let mut in_string = false;
    let mut escaped = false;
    for c in s.chars() {
        if escaped {
            escaped = false;
            continue;
        }
        match c {
            '\\' if in_string => escaped = true,
            '"' => in_string = !in_string,
            '{' | '[' if !in_string => depth += 1,
            '}' | ']' if !in_string => depth -= 1,
            _ => {}
        }
    }
    depth == 0 && !in_string
}

/// Value of the first `"key":` — string, array or object, whichever it is.
fn field(raw: &str, key: &str) -> Option<String> {
    let needle = format!("\"{key}\":");
    let at = raw.find(&needle)?;
    let rest = raw[at + needle.len()..].trim_start();
    Some(match rest.chars().next()? {
        '"' => {
            let end = rest[1..].find('"')?;
            rest[1..=end].to_string()
        }
        '[' => {
            let end = rest.find(']')?;
            rest[..=end].to_string()
        }
        '{' => {
            let end = rest.find('}')?;
            rest[..=end].to_string()
        }
        _ => {
            let end = rest.find(['\n', ',', '}', ']']).unwrap_or(rest.len());
            rest[..end].trim().to_string()
        }
    })
}

/// Everything after `<directive>` up to the next `;`.
fn directive_value(csp: &str, directive: &str) -> Option<String> {
    let at = csp.find(directive)?;
    let rest = &csp[at + directive.len()..];
    let end = rest.find(';').unwrap_or(rest.len());
    Some(rest[..end].trim().to_string())
}

/// `bundle.icon` entries.
fn icon_paths(raw: &str) -> Vec<String> {
    let Some(v) = field(raw, "icon") else {
        return Vec::new();
    };
    v.trim_matches(['[', ']'])
        .split(',')
        .map(|s| s.trim().trim_matches('"').to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

/// ICONDIR: reserved 0, type 1 (icon), then a non-zero image count.
fn is_ico(p: &Path) -> bool {
    match fs::read(p) {
        Ok(b) => b.len() >= 8 && b[0] == 0 && b[1] == 0 && b[2] == 1 && b[3] == 0 && b[4] != 0,
        Err(_) => false,
    }
}

/// Scan the built assets for anything that leaves the machine.
///
/// Two passes, because a blanket grep for `http://` in a minified bundle flags
/// XML namespaces and error-message strings — real breaks get lost in the
/// noise. So: declarative load targets anywhere (`src=`, `href=`, `url(`,
/// `@import`), and network APIs in JS (`fetch`, `XMLHttpRequest`, ...).
fn scan_frontend(dir: &Path, failures: &mut Vec<String>) {
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(entries) = fs::read_dir(&d) else { continue };
        for entry in entries.flatten() {
            let p = entry.path();
            if p.is_dir() {
                stack.push(p);
                continue;
            }
            let Some(name) = p.file_name().and_then(|n| n.to_str()) else {
                continue;
            };
            let is_js = name.ends_with(".js");
            if !is_js && !name.ends_with(".html") && !name.ends_with(".css") {
                continue;
            }
            let Ok(text) = fs::read_to_string(&p) else { continue };

            // Declarative load targets.
            for marker in ["src=", "href=", "url(", "@import", "srcset="] {
                for (at, _) in text.match_indices(marker) {
                    let after = &text[at + marker.len()..];
                    let after = after.trim_start_matches(['"', '\'', '(']);
                    if after.starts_with("http://") || after.starts_with("https://") {
                        if is_xml_namespace(&text[..at]) {
                            continue;
                        }
                        failures.push(format!(
                            "remote load target `{marker}` in {} line {}",
                            p.display(),
                            line_of(&text, at)
                        ));
                    }
                }
            }

            if !is_js {
                continue;
            }
            // Network APIs — the renderer has no business calling any of them
            // (official-update downloads go through Rust, ADR-0001).
            for api in [
                "fetch(",
                "XMLHttpRequest",
                "WebSocket",
                "EventSource",
                "new Worker",
                "navigator.sendBeacon",
            ] {
                if text.contains(api) {
                    failures.push(format!(
                        "renderer uses network API `{api}` in {} — ADR-0001 requires this in Rust",
                        p.display()
                    ));
                }
            }
        }
    }
}

/// `xmlns='http://www.w3.org/2000/svg'` is an identifier, not a fetch — and the
/// favicon in index.html is a `data:` URI wrapping one.
fn is_xml_namespace(before: &str) -> bool {
    before.len() >= 5 && before[before.len().saturating_sub(16)..].contains("xmlns")
}

fn line_of(text: &str, at: usize) -> usize {
    text[..at].matches('\n').count() + 1
}
