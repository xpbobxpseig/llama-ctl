//! llama-ctl command layer — the tauri command surface and the **Snapshot**
//! IPC contract (ticket 11).
//!
//! This crate is the only thing between the frontend and the domain layer. It
//! holds no domain logic of its own: everything is a composition of
//! `llama_ctl_core` operations, plus the wire types that cross the IPC
//! boundary.
//!
//! Layout:
//!
//! * [`snapshot`] — the Snapshot contract and every domain operation.
//! * [`fields`] — the Field table (which `AppParameters` exist, how each is
//!   rendered). Domain needs it for parse/build; the form needs it to render.
//! * [`copy`] — the message-box strings `core::i18n` does not carry yet.
//! * [`ipc`] — the JSON-over-string transport helpers, so the frontend's
//!   `invoke` shape and this crate's types stay in step.
//!
//! Testing: every operation takes `&impl Deps`, so
//! [`llama_ctl_core::fake::FakeDeps`] drives the whole layer — no OS, no
//! network, no service. See `tests/ticket11_commands.rs`.

pub mod copy;
pub mod fields;
pub mod ipc;
pub mod snapshot;

pub use ipc::{ErrorPayload, OkPayload};
pub use snapshot::{
    App, ApplyResult, FactsView, InstallReport, Snapshot, UpdateCheck,
};
