@echo off
REM =====================================================================
REM  SEO Bot - ONE COMMAND setup for a fresh Windows laptop.
REM  Run this file (double-click or:  setup.bat). It is safe to re-run:
REM  every step checks state first and skips what is already done.
REM
REM  What it does, in order:
REM    1. Installs Git (via winget) if missing
REM    2. Installs Docker Desktop (via winget) if missing
REM    3. Clones this repo if the project folder is missing
REM    4. Creates .env (asks for MONGO_URI_ATLAS once, same as your laptop)
REM    5. Builds the docker image (downloads Python deps + Chrome + driver)
REM    6. Runs the bot (interactive launcher: 1 website / 2 youtube / 3 backlinks)
REM =====================================================================
setlocal EnableDelayedExpansion

if defined SEO_BOT_REPO_URL (
  set "REPO_URL=%SEO_BOT_REPO_URL%"
) else (
  set "REPO_URL=https://github.com/soyuztechnologies/bot_project.git"
)
set "PROJECT_DIR=bot_project"

echo.
echo  ===== SEO Bot one-command setup =====
echo.

echo [1/6] Checking package manager (winget)...
where winget >nul 2>nul
if errorlevel 1 (
  echo ERROR: winget not found. Install "App Installer" from Microsoft Store, then re-run setup.bat.
  pause
  exit /b 1
)

echo [2/6] Checking Git...
git --version >nul 2>nul
if errorlevel 1 (
  echo Git missing - installing via winget...
  winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements
  echo.
  echo Git installed. Close this window, open a NEW terminal, and run setup.bat again.
  pause
  exit /b 0
)
echo Git OK.

echo [3/6] Checking Docker...
docker info >nul 2>nul
if errorlevel 1 (
  docker --version >nul 2>nul
  if errorlevel 1 (
    echo Docker missing - installing Docker Desktop via winget (needs admin approval)...
    winget install --id Docker.DockerDesktop -e --silent --accept-package-agreements --accept-source-agreements
    echo.
    echo ACTION NEEDED:
    echo   1. RESTART your laptop.
    echo   2. Start "Docker Desktop" and wait until it shows green "running".
    echo   3. Run setup.bat again (it resumes from here).
    pause
    exit /b 0
  ) else (
    echo Docker is installed but NOT running. Start "Docker Desktop", wait for green "running", then re-run setup.bat.
    pause
    exit /b 1
  )
)
echo Docker OK.

echo [4/6] Getting project code...
if not exist "%PROJECT_DIR%\.git" (
  if exist "%PROJECT_DIR%" (
    echo ERROR: folder "%PROJECT_DIR%" exists but is not a git repo. Rename or remove it, then re-run.
    pause
    exit /b 1
  )
  git clone "%REPO_URL%"
  if errorlevel 1 (
    echo ERROR: git clone failed. Check internet / repo URL / credentials.
    pause
    exit /b 1
  )
)
cd "%PROJECT_DIR%"
echo Code OK.

echo [5/6] Checking .env (database + secrets)...
if not exist ".env.example" (
  echo ERROR: .env.example not found in repo. Update the repo and re-run.
  pause
  exit /b 1
)
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Created .env from template.
)
REM A real URI looks like MONGO_URI_ATLAS=mongodb+srv://user:pass@...
REM The template placeholder (mongodb+srv://<username>...) must NOT count.
set "NEED_ENV=1"
findstr /R "^MONGO_URI_ATLAS=mongodb[+]srv://[^<]" ".env" >nul 2>nul
if not errorlevel 1 set "NEED_ENV=0"
if "%NEED_ENV%"=="1" (
  echo.
  echo One-time input needed: paste your MONGO_URI_ATLAS (same value as your working laptop).
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$u = Read-Host 'MONGO_URI_ATLAS'; if ([string]::IsNullOrWhiteSpace($u)) { Write-Host 'Empty value - aborting.'; exit 1 }; $p = '.env'; $lines = Get-Content -LiteralPath $p; $done = $false; $out = foreach ($l in $lines) { if (-not $done -and $l -match '^MONGO_URI_ATLAS=') { $done = $true; 'MONGO_URI_ATLAS=' + $u } else { $l } }; if (-not $done) { $out += 'MONGO_URI_ATLAS=' + $u }; Set-Content -LiteralPath $p -Value $out; Write-Host '.env saved.'"
  if errorlevel 1 (
    echo No URI provided - re-run setup.bat when ready.
    pause
    exit /b 1
  )
)
echo .env OK.

echo [6/6] Building image (first run downloads Python packages, Chrome and chromedriver)...
docker compose build
if errorlevel 1 (
  echo ERROR: docker build failed. See messages above.
  pause
  exit /b 1
)

echo.
echo ===== Setup complete. Starting the bot (pick 1, 2 or 3) =====
echo Tip: dashboard separately with:  docker compose up -d dashboard  (then open http://localhost:5050)
echo.
docker compose run --rm bot

echo.
echo Bot exited. Re-run setup.bat any time to start again.
pause
