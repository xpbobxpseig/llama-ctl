fn main() {
    // `requireAdministrator` comes from ADR-0001: nearly every operation here
    // (`nssm set`, `sc start|stop`, replacing llama.cpp binaries) needs it, and
    // one UAC prompt at startup is better than dozens. The consequence the ADR
    // records — a high-integrity renderer — is what `tauri.conf.json`'s CSP and
    // the local-only frontend exist to contain.
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
</assembly>
"#,
        ),
    ))
    .expect("tauri-build failed");
}
