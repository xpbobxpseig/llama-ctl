fn main() {
    // tauri-build does not track the icon file: without this, a replaced icon
    // keeps embedding the stale compiled .res forever (the bug this fixed).
    println!("cargo:rerun-if-changed=icons/llama_icon.ico");
    // `requireAdministrator` comes from ADR-0001: nearly every operation here
    // (`nssm set`, `sc start|stop`, replacing llama.cpp binaries) needs it, and
    // one UAC prompt at startup is better than dozens. The consequence the ADR
    // records — a high-integrity renderer — is what `tauri.conf.json`'s CSP and
    // the local-only frontend exist to contain.
    //
    // `requestedExecutionLevel` alone is the UAC prompt. `dpiAware` /
    // `longPathAware` are not decoration: the services view renders long
    // command lines, and without long-path awareness a service whose binary
    // lives past MAX_PATH is misreported as missing.
    //
    // Common-Controls v6 is the one that bit us: `TaskDialogIndirect` — which
    // Tauri's dialogs and the WebView2 bootstrap call — exists only in
    // comctl32 v6, and Windows picks the version from this manifest. Without
    // the dependency the process dies at startup with
    // "无法定位程序输入点 TaskDialogIndirect", before any window is created.
    tauri_build::try_build(tauri_build::Attributes::new().windows_attributes(
        tauri_build::WindowsAttributes::new().app_manifest(
            r#"
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="requireAdministrator" uiAccess="false" />
      </requestedPrivileges>
    </security>
  </trustInfo>
  <dependency>
    <dependentAssembly>
      <assemblyIdentity
        type="win32"
        name="Microsoft.Windows.Common-Controls"
        version="6.0.0.0"
        processorArchitecture="*"
        publicKeyToken="6595b64144ccf1df"
        language="*"
      />
    </dependentAssembly>
  </dependency>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/pm</dpiAware>
      <longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
    </windowsSettings>
  </application>
</assembly>
"#,
        ),
    ))
    .expect("tauri-build failed");
}
