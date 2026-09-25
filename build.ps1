# build.ps1 — 可复现打包：干净 venv → 装依赖 → PyInstaller
# 用法: pwsh -File build.ps1
# 目的: 避免构建机全局环境（numpy/playwright/yt_dlp…）被 PyInstaller 拖进包体
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$venv = Join-Path $PSScriptRoot '.venv'
$py   = Join-Path $venv 'Scripts\python.exe'

if (-not (Test-Path $py)) {
    Write-Host '==> 创建 .venv'
    py -3 -m venv $venv
}

Write-Host '==> 安装依赖'
& $py -m pip install --upgrade pip | Out-Null
& $py -m pip install -r requirements.txt

Write-Host '==> 清理旧产物'
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

Write-Host '==> PyInstaller 打包'
& $py -m PyInstaller llama_ctl.spec --noconfirm

$exe = Join-Path $PSScriptRoot 'dist\llama_ctl.exe'
if (Test-Path $exe) {
    $mb = [math]::Round((Get-Item $exe).Length / 1MB, 2)
    Write-Host "==> 完成: dist\llama_ctl.exe ($mb MB)"
} else {
    throw '打包失败：未生成 dist\llama_ctl.exe'
}
