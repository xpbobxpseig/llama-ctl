//! llama-ctl — the Tauri 2 shell around the Rust domain layer.
//!
//! This crate wires the domain layer (ticket 01-10) and the command layer
//! (ticket 11) into a window. It contains no domain logic: [`commands`] is an
//! adapter, [`run`] builds the app, and everything else lives in
//! `llama-ctl-core` / `llama-ctl-commands`.
//!
//! ADR-0001 constrains the frontend half: the whole process runs elevated, so
//! the renderer must load **nothing** remote. The CSP lives in
//! `tauri.conf.json`, the asset protocol is scoped at startup, and no command
//! takes a URL.

pub mod commands;

use llama_ctl_commands::snapshot::{self as cmd, App};
use llama_ctl_core::install::InstallEnv;
use llama_ctl_core::persist::Env;
use llama_ctl_core::real::RealDeps;
use tauri::Manager;

/// Where settings and presets live: `%APPDATA%\llama-ctl` (ticket 00, the same
/// convention the Python build uses), with `LLAMA_CTL_SETTINGS` /
/// `LLAMA_CTL_PRESETS` winning outright.
fn env() -> Env {
    Env::from_process()
}

/// Where llama.cpp lives, for the update target fallback:
/// `LLAMA_CTL_LLAMA_DIR` else `F:\llama.cpp`.
fn install_env() -> InstallEnv {
    InstallEnv::from_process()
}

pub fn run() {
    let deps = RealDeps::new();
    // Boot state is read before the window exists, so the first frame already
    // has the right language and the persisted service list.
    let app = App::new(&deps, env(), install_env());

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(commands::DepsHandle::new())
        .manage(commands::AppState::new(app))
        .invoke_handler(commands::handlers())
        .setup(|app| {
            // 材质在首帧之前对齐：Acrylic 的明暗底色跟窗口主题标志走，浅色页
            // 必须显式设浅色主题，否则罩在系统深色模式的材质上会整体发灰；
            // 关掉半透明材质时摘掉窗口特效。
            {
                let window = app.get_webview_window("main");
                if let Some(w) = window {
                    let s = llama_ctl_core::persist::load_settings(&RealDeps::new(), &env());
                    let theme = match s.appearance.as_str() {
                        "light" => Some(tauri::Theme::Light),
                        "dark" => Some(tauri::Theme::Dark),
                        _ => None,
                    };
                    let _ = w.set_theme(theme);
                    if !s.mica_enabled {
                        let _ = w.set_effects(None);
                    }
                }
            }
            // Enumerating services costs one powershell call (~0.6 s) and the
            // startup cleanup walks directory trees, so both run on a worker
            // once the window is up rather than during setup.
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let _ = tauri::async_runtime::spawn_blocking(move || {
                    let d = handle.state::<commands::DepsHandle>();
                    let state = handle.state::<commands::AppState>();
                    state.with(|a| {
                        let _ = cmd::refresh_services(d.deps(), a);
                        let _ = cmd::prune_update_dirs(d.deps(), a);
                    });
                })
                .await;
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("failed to run llama-ctl");
}
