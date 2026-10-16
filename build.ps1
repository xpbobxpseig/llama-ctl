# build.ps1 — 已被取代（superseded）
#
# 本脚本是旧 PyInstaller 打包入口（venv → pip install → PyInstaller llama_ctl.spec）。
# 桌面端现为 Tauri 2 + Vue 3 应用，打包入口改为：
#
#   cd frontend && npm install && npm run build
#   cd ..\src-tauri && cargo tauri build      # 产出 NSIS 安装包
#
# 见 README.md「构建」一节。本文件保留仅为历史参考，不再维护、不再使用。
# ponytail: 确认无人引用后可直接删除本文件。
$ErrorActionPreference = 'Stop'
Write-Host 'build.ps1 已被取代：请使用 README.md 中的 cargo tauri build 流程。' -ForegroundColor Yellow
Write-Host '(旧流程：clean venv -> pip install -> PyInstaller llama_ctl.spec)' -ForegroundColor DarkGray
exit 1
