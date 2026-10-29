# =====================================================================
#  SEO Automation Bot — First-Time Setup Script
#  Run via SETUP.bat (double-click). Safe to re-run: every step
#  checks state first and skips what is already done.
#
#  Steps:
#    1. Install Git           (if missing — winget or direct download)
#    2. Install Docker Desktop (if missing — winget or direct download)
#    3. Clone the project repo (if not already cloned)
#    4. Create .env            (asks for MongoDB URI + Gmail password)
#    5. Build Docker image     (Python + Chrome + all dependencies)
#    6. Start dashboard        (opens http://localhost:5050 in browser)
#
#  After first-time setup: use LAUNCH.bat to start the dashboard daily.
# =====================================================================

$ErrorActionPreference = "Stop"

# ---- Repo to clone (override via env var for custom forks) ----------
$RepoUrl    = if ($env:SEO_BOT_REPO_URL) { $env:SEO_BOT_REPO_URL } `
              else { "https://github.com/soyuztechnologies/bot_project.git" }
$ProjectDir = "bot_project"

# =====================================================================
# Helpers
# =====================================================================

function Test-Admin {
    $p = New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent())
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Have-Command($name) {
    return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Refresh-Path {
    # Reload PATH from registry so installers' changes are visible
    # in this same session without needing a new terminal.
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user    = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Write-Step($n, $total, $msg) {
    Write-Host ""
    Write-Host "  [$n/$total] $msg" -ForegroundColor Cyan
}

function Write-OK($msg) {
    Write-Host "         OK: $msg" -ForegroundColor Green
}

function Write-Info($msg) {
    Write-Host "       INFO: $msg" -ForegroundColor Yellow
}

function Install-GitDirect {
    Write-Info "winget not found — downloading latest Git for Windows directly..."
    $tag = (Invoke-RestMethod "https://api.github.com/repos/git-for-windows/git/releases/latest").tag_name
    $ver = $tag -replace "^v", "" -replace "\.windows\.\d+$", ""
    $url = "https://github.com/git-for-windows/git/releases/download/$tag/Git-$ver-64-bit.exe"
    $out = Join-Path $env:TEMP "git-setup.exe"
    Write-Info "Downloading Git from $url ..."
    Invoke-WebRequest -Uri $url -OutFile $out
    if ((Get-Item $out).Length -lt 10MB) { throw "Git download looks incomplete. Check internet and re-run." }
    Write-Info "Installing Git (silent, no restart needed)..."
    Start-Process $out -ArgumentList "/VERYSILENT", "/NORESTART", "/NOCANCEL", "/SP-" -Wait
}

# =====================================================================
# Elevate to Administrator (Git + Docker installers need it)
# =====================================================================
if (-not (Test-Admin)) {
    if ($env:SEO_BOT_ELEVATED -eq "1") {
        Write-Host "WARNING: not running as administrator — installs may fail." -ForegroundColor Red
    } else {
        Write-Host "  Requesting administrator rights (needed to install Git / Docker)..."
        $env:SEO_BOT_ELEVATED = "1"
        Start-Process powershell `
            -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ('"{0}"' -f $PSCommandPath) `
            -Verb RunAs
        exit 0
    }
}

# =====================================================================
# Banner
# =====================================================================
Clear-Host
Write-Host ""
Write-Host "  =============================================" -ForegroundColor Cyan
Write-Host "    SEO Automation Bot — First-Time Setup" -ForegroundColor Cyan
Write-Host "  =============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  This script will install everything needed and"
Write-Host "  open the dashboard when done."
Write-Host ""
Write-Host "  Estimated time: 5-15 minutes (depends on internet speed)"
Write-Host ""
Write-Host "  Press any key to start..." -ForegroundColor Yellow
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

# =====================================================================
# [1/6] Git
# =====================================================================
Write-Step 1 6 "Checking Git..."
Refresh-Path
if (-not (Have-Command "git")) {
    if (Have-Command "winget") {
        Write-Info "Installing Git via winget..."
        winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements
    } else {
        Install-GitDirect
    }
    Refresh-Path
}
if (-not (Have-Command "git")) {
    Write-Host ""
    Write-Host "  Git was installed but needs a fresh terminal to activate." -ForegroundColor Yellow
    Write-Host "  Please CLOSE this window, open a new one, and run SETUP.bat again." -ForegroundColor Yellow
    Write-Host ""
    pause
    exit 0
}
Write-OK "Git is ready."

# =====================================================================
# [2/6] Docker Desktop
# =====================================================================
Write-Step 2 6 "Checking Docker Desktop..."
Refresh-Path

$daemonUp = $false
try {
    docker info 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $daemonUp = $true }
} catch { $daemonUp = $false }

if (-not $daemonUp) {
    if (-not (Have-Command "docker")) {
        if (Have-Command "winget") {
            Write-Info "Installing Docker Desktop via winget..."
            winget install --id Docker.DockerDesktop -e --silent --accept-package-agreements --accept-source-agreements
        } else {
            # Enable WSL2 first (Docker needs it on Windows)
            try {
                wsl --status 2>$null | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    Write-Info "Enabling WSL2 (required by Docker Desktop)..."
                    wsl --install --no-distribution
                }
            } catch {
                Write-Info "WSL check skipped — Docker installer will handle it."
            }
            Write-Info "Downloading Docker Desktop (~500 MB)..."
            $url = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
            $out = Join-Path $env:TEMP "DockerDesktopInstaller.exe"
            Invoke-WebRequest -Uri $url -OutFile $out
            if ((Get-Item $out).Length -lt 100MB) { throw "Docker download looks incomplete. Check internet and re-run." }
            Write-Info "Installing Docker Desktop (silent)..."
            Start-Process $out -ArgumentList "install", "--quiet", "--accept-license" -Wait
            Refresh-Path
        }
    }

    # Docker is installed — start the engine and wait for it to be ready
    $desktopExe = Join-Path ${env:ProgramFiles} "Docker\Docker\Docker Desktop.exe"
    if (Test-Path $desktopExe) {
        Write-Info "Starting Docker Desktop engine, please wait..."
        Start-Process $desktopExe
        for ($i = 0; $i -lt 36 -and -not $daemonUp; $i++) {
            Start-Sleep -Seconds 5
            try {
                docker info 2>$null | Out-Null
                if ($LASTEXITCODE -eq 0) { $daemonUp = $true }
            } catch { $daemonUp = $false }
            if (-not $daemonUp) { Write-Host "    ... waiting for Docker engine ($([int]($i * 5 + 5))s)" }
        }
    }
}

if (-not $daemonUp) {
    Write-Host ""
    Write-Host "  Docker Desktop was installed but needs a RESTART to finish setup." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  ACTION NEEDED:" -ForegroundColor Yellow
    Write-Host "    1. RESTART your laptop." -ForegroundColor Yellow
    Write-Host "    2. Open 'Docker Desktop' from the Start menu." -ForegroundColor Yellow
    Write-Host "    3. Wait until the Docker icon shows green 'Running'." -ForegroundColor Yellow
    Write-Host "    4. Run SETUP.bat again — it will resume from this step." -ForegroundColor Yellow
    Write-Host ""
    pause
    exit 0
}
Write-OK "Docker Desktop is running."

# =====================================================================
# [3/6] Clone Repository
# =====================================================================
Write-Step 3 6 "Getting project code..."
$scriptDir = Split-Path -Parent $PSCommandPath

# If setup.ps1 is already inside the project folder, we are done
if (Test-Path (Join-Path $scriptDir ".git")) {
    Write-OK "Already inside the project folder — no clone needed."
    Set-Location $scriptDir
} elseif (Test-Path (Join-Path (Join-Path $scriptDir $ProjectDir) ".git")) {
    Write-OK "Project folder already exists."
    Set-Location (Join-Path $scriptDir $ProjectDir)
} else {
    if (Test-Path (Join-Path $scriptDir $ProjectDir)) {
        throw "Folder '$ProjectDir' exists but is not a git repo. Rename or delete it, then re-run SETUP.bat."
    }
    Write-Info "Cloning repository..."
    Set-Location $scriptDir
    git clone $RepoUrl
    Set-Location $ProjectDir
}
Write-OK "Project code is ready at: $(Get-Location)"

# =====================================================================
# [4/6] .env — Credentials Setup
# =====================================================================
Write-Step 4 6 "Setting up credentials (.env file)..."

if (-not (Test-Path ".env.example")) {
    throw ".env.example not found. Make sure the repo cloned correctly and re-run."
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Info "Created .env from template."
}

$raw = Get-Content -Raw -LiteralPath ".env"

# --- MongoDB URI ---
if ($raw -notmatch '(?m)^MONGO_URI_ATLAS=mongodb\+srv://[^<]') {
    Write-Host ""
    Write-Host "  -----------------------------------------------"
    Write-Host "  DATABASE CONNECTION (Required)" -ForegroundColor Yellow
    Write-Host "  -----------------------------------------------"
    Write-Host "  Paste your MongoDB Atlas connection string."
    Write-Host "  It looks like: mongodb+srv://user:pass@cluster.../seo_bot_db"
    Write-Host ""
    $mongoUri = Read-Host "  MONGO_URI_ATLAS"
    if ([string]::IsNullOrWhiteSpace($mongoUri)) {
        throw "MongoDB URI is required. Re-run SETUP.bat and paste it when prompted."
    }
    $lines = Get-Content -LiteralPath ".env"
    $found = $false
    $updated = foreach ($line in $lines) {
        if (-not $found -and $line -match "^MONGO_URI_ATLAS=") {
            $found = $true
            "MONGO_URI_ATLAS=$mongoUri"
        } else { $line }
    }
    if (-not $found) { $updated += "MONGO_URI_ATLAS=$mongoUri" }
    Set-Content -LiteralPath ".env" -Value $updated
    Write-Info "MongoDB URI saved to .env"
} else {
    Write-Info "MongoDB URI already set — skipping."
}

$raw = Get-Content -Raw -LiteralPath ".env"

# --- Gmail App Password (optional) ---
if ($raw -match '(?m)^GMAIL_APP_PASSWORD=\s*$') {
    Write-Host ""
    Write-Host "  -----------------------------------------------"
    Write-Host "  EMAIL REPORTS (Optional)" -ForegroundColor Yellow
    Write-Host "  -----------------------------------------------"
    Write-Host "  Enter your Gmail App Password to enable email reports."
    Write-Host "  Press ENTER to skip (you can add it later in .env)."
    Write-Host ""
    $gmailPass = Read-Host "  GMAIL_APP_PASSWORD"
    if (-not [string]::IsNullOrWhiteSpace($gmailPass)) {
        $lines = Get-Content -LiteralPath ".env"
        $found = $false
        $updated = foreach ($line in $lines) {
            if (-not $found -and $line -match "^GMAIL_APP_PASSWORD=") {
                $found = $true
                "GMAIL_APP_PASSWORD=$gmailPass"
            } else { $line }
        }
        if (-not $found) { $updated += "GMAIL_APP_PASSWORD=$gmailPass" }
        Set-Content -LiteralPath ".env" -Value $updated
        Write-Info "Gmail App Password saved."
    } else {
        Write-Info "Skipped — email reports disabled. Add GMAIL_APP_PASSWORD to .env later if needed."
    }
} else {
    Write-Info "Gmail App Password already set — skipping."
}

Write-OK ".env is ready."

# =====================================================================
# [5/6] Build Docker Image
# =====================================================================
Write-Step 5 6 "Building Docker image (first time: ~5-10 minutes)..."
Write-Info "This downloads Python packages, Chrome, and ChromeDriver."
Write-Info "Subsequent builds are much faster (layers are cached)."
Write-Host ""
docker compose build
if ($LASTEXITCODE -ne 0) { throw "Docker build failed. Check the output above and re-run SETUP.bat." }
Write-OK "Docker image built successfully."

# =====================================================================
# [6/6] Start Dashboard + Open Browser
# =====================================================================
Write-Step 6 6 "Starting dashboard..."

# Stop any old container first (graceful — ignore if not running)
docker compose down --remove-orphans 2>$null | Out-Null

docker compose up -d dashboard
if ($LASTEXITCODE -ne 0) { throw "Could not start dashboard container. Check the output above." }

Write-Info "Waiting for dashboard to be ready..."
Start-Sleep -Seconds 4

# Open browser
Start-Process "http://localhost:5050"

Write-Host ""
Write-Host "  =============================================" -ForegroundColor Green
Write-Host "    SETUP COMPLETE!" -ForegroundColor Green
Write-Host "  =============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Dashboard is running at: http://localhost:5050" -ForegroundColor Cyan
Write-Host ""
Write-Host "  For daily use — just double-click LAUNCH.bat" -ForegroundColor Yellow
Write-Host "  It starts the dashboard and opens the browser automatically."
Write-Host ""
