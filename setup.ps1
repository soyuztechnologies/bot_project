# =====================================================================
#  SEO Bot - ONE COMMAND setup for a fresh Windows laptop.
#  Started via setup.bat (double-click or .\setup.bat). Safe to re-run:
#  every step checks state first and skips what is already done.
#
#  The script elevates itself to administrator (installers need it),
#  then works through: Git -> Docker (+WSL2, auto-starts the engine) ->
#  clone -> .env -> docker build -> run the bot.
#
#  What it does, in order:
#    1. Installs Git if missing (winget fast-path, else direct download
#       of the latest Git-for-Windows installer from GitHub)
#    2. Installs Docker Desktop if missing (winget fast-path, else direct
#       download from Docker's official stable URL)
#    3. Clones this repo if the project folder is missing
#    4. Creates .env (asks for MONGO_URI_ATLAS once, same as your laptop)
#    5. Builds the docker image (Python deps + Chrome + chromedriver)
#    6. Runs the bot (interactive launcher: 1 website / 2 youtube / 3 backlinks)
# =====================================================================

$ErrorActionPreference = "Stop"

$RepoUrl = if ($env:SEO_BOT_REPO_URL) { $env:SEO_BOT_REPO_URL } `
           else { "https://github.com/soyuztechnologies/bot_project.git" }
$ProjectDir = "bot_project"

function Test-Admin {
    $p = New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent())
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Git/Docker installers need administrator rights. Relaunch elevated once;
# if the user declines UAC, continue anyway (installs may then fail loudly).
if (-not (Test-Admin)) {
    if ($env:SEO_BOT_ELEVATED -eq "1") {
        Write-Host "WARNING: not running as administrator - installs may fail."
    } else {
        Write-Host "Requesting administrator rights (needed to install Git/Docker)..."
        $env:SEO_BOT_ELEVATED = "1"
        Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", ('"' + $PSCommandPath + '"') -Verb RunAs
        exit 0
    }
}

function Have-Command($name) {
    return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Refresh-Path {
    # Pick up PATH changes made by installers in this same session.
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Install-GitDirect {
    Write-Host "winget not found - downloading latest Git directly..."
    $tag = (Invoke-RestMethod "https://api.github.com/repos/git-for-windows/git/releases/latest").tag_name
    $ver = $tag -replace "^v", "" -replace "\.windows\.\d+$", ""
    $url = "https://github.com/git-for-windows/git/releases/download/$tag/Git-$ver-64-bit.exe"
    $out = Join-Path $env:TEMP "git-setup.exe"
    Write-Host "Downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $out
    if ((Get-Item $out).Length -lt 10MB) { throw "Git download looks incomplete, aborting." }
    Write-Host "Installing Git (silent, no restart)..."
    Start-Process $out -ArgumentList "/VERYSILENT", "/NORESTART", "/NOCANCEL", "/SP-" -Wait
}

Write-Host ""
Write-Host " ===== SEO Bot one-command setup ===== "
Write-Host ""

# ---------- [1/6] Git ----------
Write-Host "[1/6] Checking Git..."
if (-not (Have-Command "git")) {
    if (Have-Command "winget") {
        Write-Host "Installing Git via winget..."
        winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements
    } else {
        Install-GitDirect
    }
    Refresh-Path
}
if (-not (Have-Command "git")) {
    Write-Host "Git installed but not on PATH yet. Close this window, open a NEW terminal, re-run setup."
    exit 0
}
Write-Host "Git OK."

# ---------- [2/6] Docker ----------
Write-Host "[2/6] Checking Docker..."
$daemonUp = $false
try {
    docker info 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $daemonUp = $true }
} catch { $daemonUp = $false }

if (-not $daemonUp) {
    if (-not (Have-Command "docker")) {
        if (Have-Command "winget") {
            Write-Host "Installing Docker Desktop via winget..."
            winget install --id Docker.DockerDesktop -e --silent --accept-package-agreements --accept-source-agreements
        } else {
            # Docker needs WSL2 - enable it best-effort first (Docker's own
            # installer also does this; this just makes the need explicit).
            try {
                wsl --status 2>$null | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    Write-Host "Enabling WSL (required by Docker Desktop)..."
                    wsl --install --no-distribution
                }
            } catch { Write-Host "WSL check skipped - the Docker installer will handle it." }
            Write-Host "winget not found - downloading Docker Desktop directly..."
            $url = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
            $out = Join-Path $env:TEMP "DockerDesktopInstaller.exe"
            Write-Host "Downloading Docker Desktop (large file, ~500MB)..."
            Invoke-WebRequest -Uri $url -OutFile $out
            if ((Get-Item $out).Length -lt 100MB) { throw "Docker download looks incomplete, aborting." }
            Write-Host "Installing Docker Desktop (silent)..."
            Start-Process $out -ArgumentList "install", "--quiet", "--accept-license" -Wait
        }
    }
    # Docker is installed but the engine is down - start it and wait,
    # so the user does not have to do this step by hand.
    $desktopExe = Join-Path ${env:ProgramFiles} "Docker\Docker\Docker Desktop.exe"
    if (Test-Path $desktopExe) {
        Write-Host "Starting Docker Desktop, waiting for the engine..."
        Start-Process $desktopExe
        for ($i = 0; $i -lt 30 -and -not $daemonUp; $i++) {
            Start-Sleep -Seconds 10
            try {
                docker info 2>$null | Out-Null
                if ($LASTEXITCODE -eq 0) { $daemonUp = $true }
            } catch { $daemonUp = $false }
        }
    }
}
if (-not $daemonUp) {
    Write-Host ""
    Write-Host "ACTION NEEDED:"
    Write-Host "  1. RESTART your laptop."
    Write-Host '  2. Start "Docker Desktop" and wait until it shows green "running".'
    Write-Host "  3. Run the same one-line command again (it resumes from here)."
    exit 0
}
Write-Host "Docker OK."

# ---------- [3/6] Code ----------
Write-Host "[3/6] Getting project code..."
if (-not (Test-Path (Join-Path $ProjectDir ".git"))) {
    if (Test-Path $ProjectDir) {
        throw "Folder '$ProjectDir' exists but is not a git repo. Rename or remove it, then re-run."
    }
    git clone $RepoUrl
}
Set-Location $ProjectDir
Write-Host "Code OK."

# ---------- [4/6] .env ----------
Write-Host "[4/6] Checking .env (database + secrets)..."
if (-not (Test-Path ".env.example")) { throw ".env.example not found in repo. Update the repo and re-run." }
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from template."
}
# A real URI looks like MONGO_URI_ATLAS=mongodb+srv://user:pass@...
# The template placeholder (mongodb+srv://<username>...) must NOT count.
$raw = Get-Content -Raw -LiteralPath ".env"
if ($raw -notmatch "(?m)^MONGO_URI_ATLAS=mongodb\+srv://[^<]") {
    Write-Host ""
    Write-Host "One-time input needed: paste your MONGO_URI_ATLAS (same value as your working laptop)."
    $u = Read-Host "MONGO_URI_ATLAS"
    if ([string]::IsNullOrWhiteSpace($u)) { throw "No URI provided - re-run setup when ready." }
    $lines = Get-Content -LiteralPath ".env"
    $done = $false
    $out = foreach ($l in $lines) {
        if (-not $done -and $l -match "^MONGO_URI_ATLAS=") { $done = $true; "MONGO_URI_ATLAS=" + $u }
        else { $l }
    }
    if (-not $done) { $out += "MONGO_URI_ATLAS=" + $u }
    Set-Content -LiteralPath ".env" -Value $out
    Write-Host ".env saved."
}
Write-Host ".env OK."

# ---------- [5/6] Build ----------
Write-Host "[5/6] Building image (first run downloads Python packages, Chrome and chromedriver)..."
docker compose build

# ---------- [6/6] Run ----------
Write-Host ""
Write-Host "===== Setup complete. Starting the bot (pick 1, 2 or 3) ====="
Write-Host "Tip: dashboard separately with:  docker compose up -d dashboard  (then open http://localhost:5050)"
Write-Host ""
docker compose run --rm bot

Write-Host ""
Write-Host "Bot exited. Re-run setup any time to start again."
