@echo off
REM =====================================================================
REM  SEO Bot - ONE COMMAND setup. Just run this file (double-click or
REM  setup.bat). All real work happens in setup.ps1 beside it; if that
REM  file is missing (fresh laptop one-liner), it is downloaded first.
REM  Safe to re-run: every step checks state and skips what is done.
REM =====================================================================
setlocal
set "PS1_URL=https://raw.githubusercontent.com/soyuztechnologies/bot_project/master/setup.ps1"
if not exist "%~dp0setup.ps1" (
  echo Downloading setup script...
  powershell -NoProfile -Command "Invoke-WebRequest -Uri '%PS1_URL%' -OutFile '%~dp0setup.ps1'"
  if errorlevel 1 (
    echo ERROR: could not download setup.ps1. Check internet and re-run.
    pause
    exit /b 1
  )
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
pause
