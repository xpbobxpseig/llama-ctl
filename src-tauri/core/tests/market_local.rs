//! M6 集成测试：本地模型扫描（双布局/分片归组/mmproj 归附）、删除守卫与联动删除。

use std::path::Path;

use llama_ctl_core::deps::Deps;
use llama_ctl_core::fake::FakeDeps;
use llama_ctl_core::market::hwinfo::{Gpu, GpuVendor, Hardware};
use llama_ctl_core::market::local::{delete, is_current_model, scan};
use llama_ctl_core::market::hwinfo::GI;

const ROOT: &str = r"F:\AI_Model";

fn hw() -> Hardware {
    Hardware {
        gpus: vec![Gpu {
            name: "RTX 4090".into(),
            vendor: GpuVendor::Nvidia,
            vram_bytes: 24 * GI,
        }],
        ram_total: 64 * GI,
        cpu_name: None,
    }
}

fn bytes(n: u64) -> Vec<u8> {
    vec![0u8; n as usize]
}

#[test]
fn scan_two_layouts_with_mmproj() {
    let deps = FakeDeps::new()
        .with_dir(ROOT, vec![
            llama_ctl_core::deps::DirEntry { path: r"F:\AI_Model\Qwen3.8".into(), is_dir: true },
            llama_ctl_core::deps::DirEntry { path: r"F:\AI_Model\Qwen3.8-27B-Abliterated-Q4_K_M.gguf".into(), is_dir: false },
        ])
        .with_dir(r"F:\AI_Model\Qwen3.8", vec![
            llama_ctl_core::deps::DirEntry { path: r"F:\AI_Model\Qwen3.8\Qwen3.8-27B-CRACK-IQ4_XS.gguf".into(), is_dir: false },
            llama_ctl_core::deps::DirEntry { path: r"F:\AI_Model\Qwen3.8\mmproj-Qwen3.8-27B-f16.gguf".into(), is_dir: false },
        ])
        .with_file(r"F:\AI_Model\Qwen3.8-27B-Abliterated-Q4_K_M.gguf", bytes(16 * GI))
        .with_file(r"F:\AI_Model\Qwen3.8\Qwen3.8-27B-CRACK-IQ4_XS.gguf", bytes(15 * GI))
        .with_file(r"F:\AI_Model\Qwen3.8\mmproj-Qwen3.8-27B-f16.gguf", bytes(1 * GI));

    let out = scan(&deps, Path::new(ROOT), &hw()).unwrap();
    assert_eq!(out.len(), 2);
    // 体积降序：16G 的 Abliterated 在前
    assert_eq!(out[0].label, "Q4_K_M");
    assert!(!out[0].is_sharded);
    assert!(out[0].mmproj.is_none());
    // 子目录模型带 mmproj，fit 体积含 mmproj
    assert_eq!(out[1].label, "CRACK-IQ4_XS");
    assert_eq!(
        out[1].mmproj.as_ref().map(|p| p.to_string_lossy().contains("mmproj")),
        Some(true)
    );
    assert_eq!(out[1].fit.tier, llama_ctl_core::market::FitTier::FullGpu);
}

#[test]
fn scan_groups_shards_pointing_at_first() {
    let deps = FakeDeps::new()
        .with_dir(r"F:\AI_Model\Big", vec![
            llama_ctl_core::deps::DirEntry { path: r"F:\AI_Model\Big\m-Q4_K_M-00001-of-00002.gguf".into(), is_dir: false },
            llama_ctl_core::deps::DirEntry { path: r"F:\AI_Model\Big\m-Q4_K_M-00002-of-00002.gguf".into(), is_dir: false },
        ])
        .with_file(r"F:\AI_Model\Big\m-Q4_K_M-00001-of-00002.gguf", bytes(10 * GI))
        .with_file(r"F:\AI_Model\Big\m-Q4_K_M-00002-of-00002.gguf", bytes(8 * GI));

    let out = scan(&deps, Path::new(r"F:\AI_Model\Big"), &hw()).unwrap();
    assert_eq!(out.len(), 1);
    assert!(out[0].is_sharded);
    assert!(out[0].path.to_string_lossy().contains("00001"));
    assert_eq!(out[0].size, 18 * GI);
    // 18+1.5GB 余量 = 19.5GB ≤ 24GB 的 90% → 全量档
    assert_eq!(out[0].fit.tier, llama_ctl_core::market::FitTier::FullGpu);
}

#[test]
fn missing_root_is_empty_not_error() {
    let deps = FakeDeps::new();
    let out = scan(&deps, Path::new(r"F:\ nowhere"), &hw()).unwrap();
    assert!(out.is_empty());
}

#[test]
fn delete_guard_normalizes_separators_and_case() {
    assert!(is_current_model(Some("F:/AI_Model/m/model.gguf"), Path::new(r"F:\AI_Model\M\model.gguf")));
    assert!(!is_current_model(None, Path::new(r"F:\AI_Model\m\model.gguf")));
    assert!(!is_current_model(Some("F:/other.gguf"), Path::new(r"F:\AI_Model\m\model.gguf")));
}

#[test]
fn delete_removes_mmproj_and_shard_siblings() {
    let deps = FakeDeps::new()
        .with_dir(r"F:\AI_Model\Big", vec![
            llama_ctl_core::deps::DirEntry { path: r"F:\AI_Model\Big\m-Q4_K_M-00001-of-00002.gguf".into(), is_dir: false },
            llama_ctl_core::deps::DirEntry { path: r"F:\AI_Model\Big\m-Q4_K_M-00002-of-00002.gguf".into(), is_dir: false },
            llama_ctl_core::deps::DirEntry { path: r"F:\AI_Model\Big\mmproj-f16.gguf".into(), is_dir: false },
        ])
        .with_file(r"F:\AI_Model\Big\m-Q4_K_M-00001-of-00002.gguf", bytes(10))
        .with_file(r"F:\AI_Model\Big\m-Q4_K_M-00002-of-00002.gguf", bytes(8))
        .with_file(r"F:\AI_Model\Big\mmproj-f16.gguf", bytes(1));

    let out = scan(&deps, Path::new(r"F:\AI_Model\Big"), &hw()).unwrap();
    delete(&deps, &out[0]).unwrap();
    assert!(deps.file(Path::new(r"F:\AI_Model\Big\m-Q4_K_M-00001-of-00002.gguf")).is_none());
    assert!(deps.file(Path::new(r"F:\AI_Model\Big\m-Q4_K_M-00002-of-00002.gguf")).is_none());
    assert!(deps.file(Path::new(r"F:\AI_Model\Big\mmproj-f16.gguf")).is_none());
}

#[test]
fn disk_free_is_scripted_and_none_when_unknown() {
    let deps = FakeDeps::new().with_disk_free(r"F:\AI_Model", Some(1_073_741_824_000));
    assert_eq!(
        deps.disk_free(Path::new(r"F:\AI_Model")).unwrap(),
        Some(1_073_741_824_000),
    );
    // 未脚本化的路径（网络盘 / 拔掉的盘）→ None，绝不报错炸 UI。
    assert_eq!(deps.disk_free(Path::new(r"Q:\missing")).unwrap(), None);
}
