//! 硬件检测与适配等级（spec「Implementation Decisions · 适配等级规则」）。
//!
//! 检测：GPU 走 DXGI（无子进程，NVIDIA/AMD/Intel 通吃），内存走
//! GlobalMemoryStatusEx，CPU 名走注册表（经 `Deps`，可测）。
//! **Intel 核显的 `DedicatedVideoMemory` 是驱动虚构的 128MB 假值**（Intel
//! 官方 FAQ），检测层直接把它记为 0，评估只认独显。
//!
//! 评估是纯函数，表驱动单测覆盖全档边界。

use serde::{Deserialize, Serialize};

use crate::deps::{Deps, RegHive};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum GpuVendor {
    Nvidia,
    Amd,
    Intel,
    Other,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Gpu {
    pub name: String,
    pub vendor: GpuVendor,
    /// 独显专用显存；核显一律 0（假值不可信，评估走内存口径）。
    pub vram_bytes: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Hardware {
    pub gpus: Vec<Gpu>,
    pub ram_total: u64,
    pub cpu_name: Option<String>,
}

impl Hardware {
    /// 适配等级只认最大的独显显存。
    pub fn discrete_vram(&self) -> u64 {
        self.gpus.iter().map(|g| g.vram_bytes).max().unwrap_or(0)
    }
}

const VENDOR_NVIDIA: u32 = 0x10DE;
const VENDOR_AMD: u32 = 0x1002;
const VENDOR_INTEL: u32 = 0x8086;
/// Intel 核显假值的上限（官方 FAQ：驱动报告虚构的 128MB）。
const INTEGRATED_FAKE_VRAM: u64 = 256 * 1024 * 1024;

/// 检测本机硬件。DXGI/内存读取是进程内调用（非外效应），CPU 名走 `Deps`。
pub fn detect(deps: &dyn Deps) -> Hardware {
    Hardware {
        gpus: dxgi_gpus(),
        ram_total: system_memory(),
        cpu_name: deps
            .reg_read_string(
                RegHive::LocalMachine,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                "ProcessorNameString",
            )
            .ok()
            .flatten(),
    }
}

#[cfg(windows)]
fn dxgi_gpus() -> Vec<Gpu> {
    use windows::Win32::Graphics::Dxgi::{CreateDXGIFactory1, IDXGIFactory1};
    let Ok(factory) = (unsafe { CreateDXGIFactory1::<IDXGIFactory1>() }) else {
        return Vec::new();
    };
    let mut out = Vec::new();
    for i in 0..u32::MAX {
        let Ok(adapter) = (unsafe { factory.EnumAdapters1(i) }) else {
            break;
        };
        let Ok(desc) = (unsafe { adapter.GetDesc1() }) else {
            continue;
        };
        if desc.Flags & 1 != 0 {
            continue; // 软件适配器（Basic Render Driver 之类）
        }
        let vendor = match desc.VendorId {
            VENDOR_NVIDIA => GpuVendor::Nvidia,
            VENDOR_AMD => GpuVendor::Amd,
            VENDOR_INTEL => GpuVendor::Intel,
            _ => GpuVendor::Other,
        };
        let mut vram = desc.DedicatedVideoMemory as u64;
        if vendor == GpuVendor::Intel && vram <= INTEGRATED_FAKE_VRAM {
            vram = 0;
        }
        out.push(Gpu { name: String::from_utf16_lossy(&desc.Description), vendor, vram_bytes: vram });
    }
    out
}

#[cfg(not(windows))]
fn dxgi_gpus() -> Vec<Gpu> {
    Vec::new()
}

#[cfg(windows)]
fn system_memory() -> u64 {
    use windows::Win32::System::SystemInformation::{GlobalMemoryStatusEx, MEMORYSTATUSEX};
    let mut mem = MEMORYSTATUSEX {
        dwLength: std::mem::size_of::<MEMORYSTATUSEX>() as u32,
        ..Default::default()
    };
    if unsafe { GlobalMemoryStatusEx(&mut mem) }.is_ok() {
        mem.ullTotalPhys
    } else {
        0
    }
}

#[cfg(not(windows))]
fn system_memory() -> u64 {
    0
}

// ---- 适配等级 ----

pub const GI: u64 = 1024 * 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FitTier {
    /// 完全进显存（流畅）。
    FullGpu,
    /// 大部分进显存（部分 offload，能跑）。
    PartialGpu,
    /// 主要靠内存，CPU 推理（勉强）。
    CpuOnly,
    /// 内存也装不下。
    NotRecommended,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct FitVerdict {
    pub tier: FitTier,
    /// 一行依据（中文，直接进 UI）。
    pub reason: String,
    /// 建议的 GPU offload 比例（0–100）；CPU/不建议档为 None。
    pub offload_ratio: Option<u64>,
}

fn gb(bytes: u64) -> String {
    format!("{:.1}GB", bytes as f64 / GI as f64)
}

/// 适配等级。`weights_size` 为量化档全部文件（分片+mmproj）体积；
/// 余量 1.5GiB 补偿「静态估算不含 KV cache」的已知缺陷（LM Studio 同款惯例）。
pub fn assess(hw: &Hardware, weights_size: u64) -> FitVerdict {
    let budget = hw.discrete_vram();
    let need = weights_size + 3 * GI / 2;
    let ram = hw.ram_total;

    if budget > 0 && need <= budget * 9 / 10 {
        return FitVerdict {
            tier: FitTier::FullGpu,
            reason: format!(
                "权重 {}（含 1.5GB 余量）≈ 显存 {} 的 {}%，可全量 offload",
                gb(weights_size),
                gb(budget),
                need * 100 / budget.max(1)
            ),
            offload_ratio: Some(100),
        };
    }
    // 部分档：显存放权重，其余进内存。内存预算 = 总量 − 8GB 系统占用的 60%。
    let ram_headroom = ram.saturating_sub(8 * GI) * 6 / 10;
    if budget > 0 && need <= budget + ram_headroom {
        let ratio = (budget * 100 / need).min(100);
        return FitVerdict {
            tier: FitTier::PartialGpu,
            reason: format!(
                "权重 {} 超出显存 {}，约 {}% 可进显存，其余走内存（速度受 CPU/带宽限制）",
                gb(weights_size),
                gb(budget),
                ratio
            ),
            offload_ratio: Some(ratio),
        };
    }
    if need <= ram * 7 / 10 {
        return FitVerdict {
            tier: FitTier::CpuOnly,
            reason: format!(
                "显存装不下 {}，内存 {} 可容纳：仅 CPU 推理，速度有限",
                gb(need),
                gb(ram)
            ),
            offload_ratio: None,
        };
    }
    FitVerdict {
        tier: FitTier::NotRecommended,
        reason: format!("需 {}，显存 {} 与内存 {} 均装不下，不建议下载", gb(need), gb(budget), gb(ram)),
        offload_ratio: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hw(vram_gb: u64, ram_gb: u64) -> Hardware {
        Hardware {
            gpus: if vram_gb > 0 {
                vec![Gpu {
                    name: "Test GPU".into(),
                    vendor: GpuVendor::Nvidia,
                    vram_bytes: vram_gb * GI,
                }]
            } else {
                vec![]
            },
            ram_total: ram_gb * GI,
            cpu_name: None,
        }
    }

    #[test]
    fn full_gpu_tier() {
        // 4090 24G + 16GB 权重（27B Q4）→ 完全进显存（实测同款配置全量 offload）
        let v = assess(&hw(24, 64), 16 * GI);
        assert_eq!(v.tier, FitTier::FullGpu);
        assert_eq!(v.offload_ratio, Some(100));
        assert!(v.reason.contains("全量 offload"));
    }

    #[test]
    fn boundary_at_90pct() {
        // 21.6GB 需求 = 24GB 的 90% 恰好压线（+1.5GB 余量后 23.1 > 21.6 → 不到线）
        let v = assess(&hw(24, 64), 20 * GI); // 21.5 ≤ 21.6 全量档
        assert_eq!(v.tier, FitTier::FullGpu);
        let v = assess(&hw(24, 64), 21 * GI); // 22.5 > 21.6 → 掉档
        assert_eq!(v.tier, FitTier::PartialGpu);
    }

    #[test]
    fn partial_gpu_estimates_offload_ratio() {
        // 70B Q4 ≈ 40GB，24G 显存 + 64G 内存 → 部分档
        let v = assess(&hw(24, 64), 40 * GI);
        assert_eq!(v.tier, FitTier::PartialGpu);
        let r = v.offload_ratio.unwrap();
        assert!(r > 40 && r < 70, "ratio={r}");
        assert!(v.reason.contains("其余走内存"));
    }

    #[test]
    fn cpu_only_is_for_machines_without_discrete_gpu() {
        // 有 24G 独显时，42GB 权重依然是「部分进显存」（约 55% offload）——
        // 独显总能装几层，不存在「仅 CPU」。
        let v = assess(&hw(24, 64), 42 * GI);
        assert_eq!(v.tier, FitTier::PartialGpu);
        assert_eq!(v.offload_ratio, Some(55));
        // 120GB：显存 + 内存富余都装不下 → 不建议
        let v = assess(&hw(24, 64), 120 * GI);
        assert_eq!(v.tier, FitTier::NotRecommended);
        assert!(v.offload_ratio.is_none());
    }

    #[test]
    fn no_discrete_gpu_never_full_gpu() {
        // 无独显（或核显 vram=0）：即使小模型也不能标「完全进显存」
        let v = assess(&hw(0, 64), 1 * GI);
        assert_eq!(v.tier, FitTier::CpuOnly);
    }

    #[test]
    fn intel_fake_vram_is_zeroed_by_detection_contract() {
        // 检测层契约：核显一律 vram=0（这里验证评估层不误判）
        let h = Hardware {
            gpus: vec![Gpu {
                name: "Iris Xe".into(),
                vendor: GpuVendor::Intel,
                vram_bytes: 0,
            }],
            ram_total: 16 * GI,
            cpu_name: None,
        };
        assert_eq!(h.discrete_vram(), 0);
        assert_eq!(assess(&h, 2 * GI).tier, FitTier::CpuOnly);
    }
}
