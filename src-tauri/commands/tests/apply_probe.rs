//! 真网探针（默认忽略）：复现市场「启用」的 apply 链路，抓真实错误。
//! 会瞬时改写 NSSM AppParameters 并立即恢复——运行中的服务不受影响
//! （参数只在重启时生效），恢复后与原始值语义等价。

use llama_ctl_commands::snapshot as cmd;
use llama_ctl_core::install::InstallEnv;
use llama_ctl_core::persist::Env;
use llama_ctl_core::real::RealDeps;

#[test]
#[ignore]
fn probe_apply_qwen25() {
    let d = RealDeps::new();
    let mut app = cmd::App::new(&d, Env::from_process(), InstallEnv::from_process());
    let snap = cmd::snapshot(&d, &mut app, None);
    let original_values = snap.values.clone();
    let original_extras = snap.extras.clone();
    println!(
        "原始 model={:?} extras={:?}",
        original_values.get("model"),
        original_extras
    );

    let mut values = original_values.clone();
    values.insert(
        "model".into(),
        r"F:\AI_Model\Qwen2.5-0.5B-Instruct-GGUF\qwen2.5-0.5b-instruct-q2_k.gguf".into(),
    );
    match cmd::apply(&d, &mut app, &values, &original_extras) {
        Ok(r) => println!(
            "APPLY OK written={} needs_restart={}",
            r.written, r.needs_restart
        ),
        Err(e) => println!("APPLY 失败: kind={:?} msg={}", e.kind, e.message),
    }

    // 恢复原参数
    match cmd::apply(&d, &mut app, &original_values, &original_extras) {
        Ok(r) => println!("RESTORE OK written={}", r.written),
        Err(e) => println!("RESTORE 失败: kind={:?} msg={}", e.kind, e.message),
    }
}
