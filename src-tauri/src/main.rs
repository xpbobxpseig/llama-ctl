//! Binary entry point. Kept to one line: everything lives in the library so
//! `cargo test` can reach it.
//!
//! The process runs with a `requireAdministrator` manifest (ADR-0001), which
//! `build.rs` embeds — no on-demand UAC, no elevated sidecar.

fn main() {
    llama_ctl_lib::run();
}
