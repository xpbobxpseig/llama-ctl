fn main() {
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
