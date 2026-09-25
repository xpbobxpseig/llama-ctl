@echo off
rem 从源码运行（开发模式）。exe 用户无需本文件。
cd /d "%~dp0"
python "%~dp0llama_ctl_gui.py"
if errorlevel 1 (
  echo.
  echo Program exited with error. See message above.
  pause
)
