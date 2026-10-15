//! Ticket 05 acceptance: version discovery, build variants, asset selection.
//!
//! Ported from the discovery half of `tests/test_updater.py`. Everything runs
//! offline: pages come from `FakeDeps::with_http`, the local exe from
//! `with_spawn`.

use std::path::Path;

use llama_ctl_core::deps::{AppErrorKind, DepsError, DepsErrorKind};
use llama_ctl_core::fake::FakeDeps;
use llama_ctl_core::updater::{
    Asset, DEFAULT_CHANNEL, RETIRED_CHANNELS, RELEASES_BASE, RELEASES_PAGE, Variant, channels,
    find_latest_release, get_installed_build, parse_build, parse_version_output, resolve_variant,
    select_assets,
};

fn asset(name: &str) -> Asset {
    Asset { name: name.to_string(), url: format!("https://x/{name}") }
}

fn names(v: &[Asset]) -> Vec<&str> {
    v.iter().map(|a| a.name.as_str()).collect()
}

/// Realistic releases page: newest nightly first, then an older nightly that
/// still ships CUDA, then a stable tag with no build number.
fn releases_page() -> String {
    r#"<html><body>
      <div class="Box">
        <h2 class="text-normal"><a href="/ggml-org/llama.cpp/releases/tag/b10820">b10820</a></h2>
        <h2 class="text-normal"><a href="/ggml-org/llama.cpp/releases/tag/b10819">b10819</a></h2>
        <h2 class="text-normal"><a href="/ggml-org/llama.cpp/releases/tag/v0.4.0">stable</a></h2>
      </div>
      <a href="/ggml-org/llama.cpp/commits/master">commits</a>
      </body></html>"#
        .to_string()
}

/// `expanded_assets/{tag}`: every zip upstream really publishes for the tag,
/// across all four variants plus decoys (arm64, rocm, other CUDA versions).
fn assets_page(tag: &str) -> String {
    format!(
        r#"<html><body>
      <li><a href="/ggml-org/llama.cpp/releases/download/{tag}/llama-{tag}-bin-win-cuda-12.4-x64.zip">bin</a></li>
      <li><a href="/ggml-org/llama.cpp/releases/download/{tag}/llama-{tag}-bin-win-cuda-13.4-x64.zip">bin</a></li>
      <li><a href="/ggml-org/llama.cpp/releases/download/{tag}/llama-{tag}-bin-win-cuda-13.4-arm64.zip">bin</a></li>
      <li><a href="/ggml-org/llama.cpp/releases/download/{tag}/llama-{tag}-bin-win-cpu-x64.zip">bin</a></li>
      <li><a href="/ggml-org/llama.cpp/releases/download/{tag}/llama-{tag}-bin-win-vulkan-x64.zip">bin</a></li>
      <li><a href="/ggml-org/llama.cpp/releases/download/{tag}/llama-{tag}-bin-win-rocm-10.0-x64.zip">bin</a></li>
      <li><a href="/ggml-org/llama.cpp/releases/download/{tag}/cudart-llama-bin-win-cuda-12.4-x64.zip">runtime</a></li>
      <li><a href="/ggml-org/llama.cpp/releases/download/{tag}/cudart-llama-bin-win-cuda-13.4-x64.zip">runtime</a></li>
      <li><a href="/ggml-org/llama.cpp/releases/download/{tag}/nightly-tag.txt">tag</a></li>
      </body></html>"#
    )
}

/// Newest nightly ships CPU only; the older one has the full CUDA set.
fn cuda_orphan_pages() -> FakeDeps {
    FakeDeps::new()
        .with_http(RELEASES_PAGE, Ok(releases_page().into_bytes()))
        .with_http(
            &format!("{RELEASES_BASE}expanded_assets/b10820"),
            Ok(r#"<a href="/ggml-org/llama.cpp/releases/download/b10820/llama-b10820-bin-win-cpu-x64.zip">CPU</a>"#.as_bytes().to_vec()),
        )
        .with_http(
            &format!("{RELEASES_BASE}expanded_assets/b10819"),
            Ok(assets_page("b10819").into_bytes()),
        )
}

// ---- variants / retired fallback ------------------------------------------

#[test]
fn default_variant_is_cuda_13_4_and_all_four_are_offered() {
    // The 13.3 outage: the default must be a variant upstream still publishes.
    assert_eq!(DEFAULT_CHANNEL, "win-cuda-13.4-x64");
    assert_eq!(Variant::DEFAULT.id(), DEFAULT_CHANNEL);
    assert_eq!(channels().len(), 4);
    assert_eq!(Variant::ALL.len(), 4);
}

#[test]
fn retired_variant_from_old_config_falls_back_to_default() {
    assert!(RETIRED_CHANNELS.contains(&"win-cuda-13.3-x64"));
    for retired in RETIRED_CHANNELS {
        assert!(Variant::from_id(retired).is_none(), "{retired} must not be offered");
        assert_eq!(resolve_variant(Some(retired)), Variant::DEFAULT);
    }
    // Garbage and absent values behave the same way, not as an error.
    assert_eq!(resolve_variant(Some("win-cuda-99-x64")), Variant::DEFAULT);
    assert_eq!(resolve_variant(None), Variant::DEFAULT);
    assert!(!channels().iter().any(|(id, _)| RETIRED_CHANNELS.contains(id)));
}

#[test]
fn every_offered_variant_round_trips_through_its_id() {
    // What the dropdown shows must survive a store/load cycle unchanged.
    for (id, _label) in channels() {
        assert_eq!(resolve_variant(Some(id)).id(), id);
    }
}

// ---- build / version parsing ----------------------------------------------

#[test]
fn build_number_is_parsed_from_a_release_tag() {
    assert_eq!(parse_build("b10819"), Some(10819));
    assert_eq!(parse_build("b5527"), Some(5527));
    assert_eq!(parse_build("v0.4.0"), None);
    assert_eq!(parse_build(""), None);
}

#[test]
fn build_number_is_parsed_from_version_output() {
    let text = "version: 0.4.0-dev (build 10813, commit 4acf4a4cb)";
    assert_eq!(parse_version_output(text), Some(10813));
    assert_eq!(parse_version_output("version: 1.2.3"), None);
    assert_eq!(parse_version_output(""), None);
}

// ---- asset selection -------------------------------------------------------

#[test]
fn each_of_the_four_variants_selects_exactly_its_own_assets() {
    let sets: &[(Variant, &[&str])] = &[
        (
            Variant::Cuda134,
            &[
                "llama-b10819-bin-win-cuda-13.4-x64.zip",
                "cudart-llama-bin-win-cuda-13.4-x64.zip",
                // Upstream sometimes ships the build-numbered runtime zip too.
                "cudart-llama-b10819-bin-win-cuda-13.4-x64.zip",
            ],
        ),
        (
            Variant::Cuda124,
            &[
                "llama-b10819-bin-win-cuda-12.4-x64.zip",
                "cudart-llama-bin-win-cuda-12.4-x64.zip",
            ],
        ),
        (Variant::Cpu, &["llama-b10819-bin-win-cpu-x64.zip"]),
        (Variant::Vulkan, &["llama-b10819-bin-win-vulkan-x64.zip"]),
    ];

    for (variant, expected) in sets {
        let picked = select_assets("b10819", &all_assets("b10819"), *variant);
        assert_eq!(names(&picked), *expected, "wrong assets for {variant}");
    }
}

fn all_assets(tag: &str) -> Vec<Asset> {
    vec![
        "nightly-tag.txt",
        &format!("llama-{tag}-bin-win-cuda-12.4-x64.zip"),
        &format!("llama-{tag}-bin-win-cuda-13.4-x64.zip"),
        &format!("llama-{tag}-bin-win-cuda-13.4-arm64.zip"),
        &format!("llama-{tag}-bin-win-cpu-x64.zip"),
        &format!("llama-{tag}-bin-win-cpu-arm64.zip"),
        &format!("llama-{tag}-bin-win-vulkan-x64.zip"),
        &format!("llama-{tag}-bin-win-rocm-10.0-x64.zip"),
        "cudart-llama-bin-win-cuda-12.4-x64.zip",
        "cudart-llama-bin-win-cuda-13.4-x64.zip",
        &format!("cudart-llama-{tag}-bin-win-cuda-13.4-x64.zip"),
    ]
    .into_iter()
    .map(asset)
    .collect()
}

#[test]
fn selection_needs_a_build_number_in_the_tag() {
    // Stable tags carry none of the nightly zips; selecting must stay empty.
    assert!(select_assets("v0.4.0", &[asset("nightly-tag.txt")], Variant::Cuda134).is_empty());
    assert!(select_assets("", &all_assets("b10819"), Variant::Cpu).is_empty());
}

#[test]
fn selection_never_picks_another_cuda_version_or_architecture() {
    // Exact match, or cuda-13.3/arm64/rocm decoys get downloaded instead.
    let picked = select_assets("b10819", &all_assets("b10819"), Variant::Cuda134);
    assert!(!picked.iter().any(|a| a.name.contains("arm64")));
    assert!(!picked.iter().any(|a| a.name.contains("rocm")));
    assert!(!picked.iter().any(|a| a.name.contains("12.4")));
}

// ---- find_latest_release ---------------------------------------------------

#[test]
fn find_latest_release_picks_the_newest_tag_that_ships_the_variant() {
    let d = cuda_orphan_pages();

    let rel = find_latest_release(&d, Variant::Cuda134).unwrap();

    assert_eq!(rel.tag, "b10819");
    assert_eq!(rel.build, 10819);
    assert_eq!(
        names(&rel.assets),
        vec![
            "llama-b10819-bin-win-cuda-13.4-x64.zip",
            "cudart-llama-bin-win-cuda-13.4-x64.zip",
        ]
    );
    assert_eq!(
        rel.assets[0].url,
        "https://github.com/ggml-org/llama.cpp/releases/download/b10819/llama-b10819-bin-win-cuda-13.4-x64.zip"
    );
    assert_eq!(rel.html_url, format!("{RELEASES_BASE}tag/b10819"));
}

#[test]
fn find_latest_release_uses_the_newest_tag_when_it_does_ship_the_variant() {
    let d = FakeDeps::new()
        .with_http(RELEASES_PAGE, Ok(releases_page().into_bytes()))
        .with_http(
            &format!("{RELEASES_BASE}expanded_assets/b10820"),
            Ok(assets_page("b10820").into_bytes()),
        );

    let rel = find_latest_release(&d, Variant::Vulkan).unwrap();

    assert_eq!(rel.tag, "b10820");
    assert_eq!(names(&rel.assets), vec!["llama-b10820-bin-win-vulkan-x64.zip"]);
}

#[test]
fn find_latest_release_fails_when_no_tag_ships_the_variant() {
    // b10820 ships CPU only and b10819 is unreachable: no CUDA nightly found.
    // A network error on a *later* page still wins over "no match", so the user
    // sees why the check failed rather than a bare "not found".
    let d = FakeDeps::new()
        .with_http(RELEASES_PAGE, Ok(releases_page().into_bytes()))
        .with_http(
            &format!("{RELEASES_BASE}expanded_assets/b10820"),
            Ok(r#"<a href="/ggml-org/llama.cpp/releases/download/b10820/llama-b10820-bin-win-cpu-x64.zip">CPU</a>"#.as_bytes().to_vec()),
        )
        .with_http(&format!("{RELEASES_BASE}expanded_assets/b10819"), Err(net_down()));

    let err = find_latest_release(&d, Variant::Cuda134).unwrap_err();

    assert_eq!(err.kind, AppErrorKind::UpdateFailed);
    assert_eq!(err.message, "网络错误：connection refused");
}

#[test]
fn no_release_for_the_variant_is_a_displayable_error_naming_it() {
    // Every nightly reachable, none shipping the variant: the user must be told
    // which variant we looked for, not a generic failure.
    let d = FakeDeps::new()
        .with_http(RELEASES_PAGE, Ok(releases_page().into_bytes()))
        .with_http(&format!("{RELEASES_BASE}expanded_assets/b10820"), Ok(Vec::new()))
        .with_http(&format!("{RELEASES_BASE}expanded_assets/b10819"), Ok(Vec::new()));

    let err = find_latest_release(&d, Variant::Cpu).unwrap_err();

    assert_eq!(err.kind, AppErrorKind::UpdateFailed);
    assert!(err.message.contains("win-cpu-x64"));
}

#[test]
fn a_retired_id_in_config_still_finds_a_release_on_the_default_variant() {
    // End-to-end version of the 13.3 outage: old settings say cuda-13.3, the
    // page only has 13.4 — the check must succeed on the default variant.
    let d = cuda_orphan_pages();
    let channel = resolve_variant(Some("win-cuda-13.3-x64"));

    let rel = find_latest_release(&d, channel).unwrap();

    assert_eq!(channel, Variant::Cuda134);
    assert_eq!(rel.tag, "b10819");
    assert_eq!(rel.assets[0].name, "llama-b10819-bin-win-cuda-13.4-x64.zip");
    assert!(!rel.assets.iter().any(|a| a.name.contains("13.3")));
}

#[test]
fn network_failure_surfaces_as_an_error_not_a_panic() {
    let d = FakeDeps::new().with_http(RELEASES_PAGE, Err(net_down()));
    let err = find_latest_release(&d, Variant::Cuda134).unwrap_err();

    assert_eq!(err.kind, AppErrorKind::UpdateFailed);
    assert_eq!(err.message, "网络错误：connection refused", "可展示：原样带到前端");
}

fn net_down() -> DepsError {
    DepsError::new(DepsErrorKind::Network, "网络错误：connection refused")
}

// ---- installed build -------------------------------------------------------

#[test]
fn installed_build_comes_from_the_exe_version_output() {
    let exe = Path::new(r"F:\llama.cpp\llama-server.exe");
    let d = FakeDeps::new().with_spawn(
        &exe.to_string_lossy(),
        Ok(b"version: 0.4.0-dev (build 10813, commit 4acf4a4cb)".to_vec()),
    );

    assert_eq!(get_installed_build(&d, exe), Some(10813));
    assert_eq!(d.calls().len(), 1, "one --version spawn, nothing else");
}

#[test]
fn unreadable_version_is_unknown_not_an_error() {
    // Missing exe, a crash, and unparsable output all mean "unknown".
    let exe = Path::new(r"F:\llama.cpp\llama-server.exe");
    let d = FakeDeps::new().with_spawn(
        &exe.to_string_lossy(),
        Err(DepsError::new(DepsErrorKind::SpawnFailed, "not found")),
    );
    assert_eq!(get_installed_build(&d, exe), None);

    let d = FakeDeps::new().with_spawn(&exe.to_string_lossy(), Ok(b"version: 1.2.3".to_vec()));
    assert_eq!(get_installed_build(&d, exe), None);

    let d = FakeDeps::new().with_spawn(&exe.to_string_lossy(), Ok(Vec::new()));
    assert_eq!(get_installed_build(&d, exe), None);

    assert_eq!(get_installed_build(&FakeDeps::new(), Path::new("")), None);
}
