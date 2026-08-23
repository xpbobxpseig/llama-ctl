@echo off
cd /d F:\llama_ctl
python "F:\llama_ctl\llama_ctl_gui.py"
if errorlevel 1 (
  echo.
  echo Program exited with error. See message above.
  pause
)
