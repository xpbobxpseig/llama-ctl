# build.ps1 — official llama-ctl build entry.
#
# Tauri still uses its normal intermediate/working directories under
# src-tauri\target, but the two deliverables are copied to the repository root:
#
#   llama-ctl.exe                         portable app
#   llama-ctl_<version>_x64-setup.exe     NSIS installer
#
# This is the build configuration the README points at; run it from the
# repository root:  .\build.ps1

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$tauriDir = Join-Path $root 'src-tauri'
$targetDir = Join-Path $tauriDir 'target\release'
$appPath = Join-Path $targetDir 'llama-ctl.exe'
$bundleDir = Join-Path $targetDir 'bundle\nsis'
$rootApp = Join-Path $root 'llama-ctl.exe'

function Assert-NotRunning([string]$path) {
    $running = Get-Process -Name 'llama-ctl' -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and ([IO.Path]::GetFullPath($_.Path) -eq [IO.Path]::GetFullPath($path)) }
    if ($running) {
        $ids = ($running | ForEach-Object Id) -join ', '
        throw "llama-ctl is running from '$path' (PID $ids). Close it, then run .\build.ps1 again."
    }
}

if (-not (Test-Path $tauriDir)) { throw "Missing Tauri project directory: $tauriDir" }
Assert-NotRunning $appPath
Assert-NotRunning $rootApp

Push-Location $tauriDir
try {
    # Remove the previous app binary and old NSIS setup so a successful build
    # cannot silently leave a stale deliverable behind.
    if (Test-Path $appPath) { Remove-Item $appPath -Force }
    if (Test-Path $bundleDir) {
        Get-ChildItem $bundleDir -File -Filter '*setup.exe' -ErrorAction SilentlyContinue |
            Remove-Item -Force
    }

    Write-Host '==> cargo tauri build --ci' -ForegroundColor Cyan
    & cargo tauri build --ci
    if ($LASTEXITCODE -ne 0) { throw "cargo tauri build failed with exit code $LASTEXITCODE" }
}
finally {
    Pop-Location
}

if (-not (Test-Path $appPath)) { throw "Build finished but app exe is missing: $appPath" }

$installer = Get-ChildItem $bundleDir -File -Filter '*setup.exe' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $installer) { throw "Build finished but NSIS installer is missing under: $bundleDir" }

$rootInstaller = Join-Path $root $installer.Name
Copy-Item $appPath $rootApp -Force
Copy-Item $installer.FullName $rootInstaller -Force

$outputs = @(
    (Get-Item $rootApp),
    (Get-Item $rootInstaller)
)
foreach ($item in $outputs) {
    if ($item.Length -le 0) { throw "Zero-byte build deliverable: $($item.FullName)" }
}

Write-Host ''
Write-Host 'BUILD_OK — root deliverables:' -ForegroundColor Green
$outputs |
    Select-Object Name, @{N='SizeMB';E={[math]::Round($_.Length / 1MB, 2)}}, LastWriteTime |
    Format-Table -AutoSize
Write-Host 'Portable app: ' -NoNewline
Write-Host $rootApp -ForegroundColor Green
Write-Host 'Installer:    ' -NoNewline
Write-Host $rootInstaller -ForegroundColor Green
Write-Host ''
Write-Host 'Tauri intermediates remain under src-tauri\target\release; the two paths above are the supported outputs.'
