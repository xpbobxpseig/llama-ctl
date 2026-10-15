//! Command-line driver for `llama-ctl-core`.
//!
//! Ticket 01's acceptance criteria include being able to invoke any domain
//! operation without a GUI, so the domain layer is demoable and verifiable on
//! its own. This is that entry point.
//!
//! It talks to the real system, so it needs the same privilege the GUI does
//! (ADR-0001).

use std::path::PathBuf;

use llama_ctl_core::deps::Deps;
use llama_ctl_core::real::RealDeps;
use llama_ctl_core::service::{
    list_nssm_services, query_status, read_facts, sc_action, sc_query_state,
};
use llama_ctl_core::updater::{Variant, find_latest_release, get_installed_build};

fn main() {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() {
        usage();
        return;
    }
    let cmd = args.remove(0);
    let d = RealDeps::new();
    let service = std::env::var("LLAMA_CTL_SERVICE").unwrap_or_else(|_| "QwenLLM".to_string());

    match cmd.as_str() {
        "services" => {
            for name in list_nssm_services(&d) {
                println!("{name}");
            }
        }
        "facts" => {
            let name = args.first().cloned().unwrap_or(service);
            let f = read_facts(&d, &name);
            println!("service:      {name}");
            println!("app_dir:      {}", f.app_dir.as_deref().unwrap_or("(none)"));
            println!("app_params:   {}", f.app_params);
            println!("start:        {:?}", f.start);
        }
        "state" => {
            let name = args.first().cloned().unwrap_or(service);
            println!("{}", sc_query_state(&d, &name));
        }
        "status" => {
            let name = args.first().cloned().unwrap_or(service);
            let port: u16 = args.get(1).and_then(|p| p.parse().ok()).unwrap_or(8080);
            let s = query_status(&d, &name, "127.0.0.1", port);
            println!("state:  {}", s.state);
            println!("ready:  {}", s.ok);
            println!("detail: {}", s.detail);
        }
        "start" | "stop" => {
            let name = args.first().cloned().unwrap_or(service);
            match sc_action(&d, &cmd, &name) {
                Ok(out) => println!("{out}"),
                Err(e) => {
                    eprintln!("failed: {e}");
                    std::process::exit(1);
                }
            }
        }
        "check-update" => {
            let variant = args
                .first()
                .and_then(|s| Variant::from_id(s))
                .unwrap_or(Variant::DEFAULT);
            match find_latest_release(&d, variant) {
                Ok(r) => {
                    println!("tag:    {}", r.tag);
                    println!("build:  b{}", r.build);
                    for a in &r.assets {
                        println!("asset:  {}", a.name);
                    }
                }
                Err(e) => {
                    eprintln!("failed: {e}");
                    std::process::exit(1);
                }
            }
        }
        "installed-build" => {
            let exe = args
                .first()
                .cloned()
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from(r"F:\llama.cpp\llama-server.exe"));
            match get_installed_build(&d, &exe) {
                Some(b) => println!("b{b}"),
                None => println!("unknown"),
            }
        }
        // Exercises the decode path (ticket 02) against a real child process.
        "raw" => {
            let program = args.first().cloned().unwrap_or_else(|| "sc".into());
            let rest: Vec<&str> = args.iter().skip(1).map(String::as_str).collect();
            match Deps::spawn(&d, &program, &rest) {
                Ok(bytes) => println!("{}", llama_ctl_core::decode::decode(&bytes)),
                Err(e) => {
                    eprintln!("failed: {e}");
                    std::process::exit(1);
                }
            }
        }
        _ => usage(),
    }
}

fn usage() {
    eprintln!(
        "usage: llama-ctl-core <command> [args]

  services                 list NSSM-managed services
  facts [service]          print install dir, AppParameters, start mode
  state [service]          print the sc query state word
  status [service] [port]  print state plus health-probe readiness
  start|stop [service]     start or stop a service
  check-update [variant]   print the latest official release and its assets
  installed-build [exe]    print the installed build number (bNNNN)
  raw <program> [args]     run a command and print its decoded output"
    );
}
