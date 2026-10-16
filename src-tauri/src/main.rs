//!
//! Windows only: the release build must not allocate a console. Rust links a
//! `fn main` binary as subsystem CONSOLE (3), so Windows opens a cmd window
//! alongside the app — a second window behind the GUI, into which any crate
//! that writes to stderr (libpng, here) then prints. `windows_subsystem`
//! switches it to WINDOWS (2).
//!
//! Debug keeps the console on purpose: it is where the WebView and Rust
//! panics surface while developing.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! Binary entry point. Kept to one line: everything lives in the library so
//! `cargo test` can reach it.
//!
//! The process runs with a `requireAdministrator` manifest (ADR-0001), which
//! `build.rs` embeds — no on-demand UAC, no elevated sidecar.

fn main() {
    llama_ctl_lib::run();
}
