# =====================================================================
#  SEO Automation Bot — Automated Setup Script
# =====================================================================

$ErrorActionPreference = "Stop"

$RepoUrl    = if ($env:SEO_BOT_REPO_URL) { $env:SEO_BOT_REPO_URL } `
              else { "https://github.com/soyuztechnologies/bot_project.git" }
$ProjectDir = "bot_project"

function Test-Admin {
    $p = New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent())
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Have-Command($name) {
    return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Refresh-Path {
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
    Write-Info "winget not found - downloading Git for Windows directly..."
    $tag = (Invoke-RestMethod "https://api.github.com/repos/git-for-windows/git/releases/latest").tag_name
    $ver = $tag -replace "^v", "" -replace "\.windows\.\d+$", ""
    $url = "https://github.com/git-for-windows/git/releases/download/$tag/Git-$ver-64-bit.exe"
    $out = Join-Path $env:TEMP "git-setup.exe"
    Invoke-WebRequest -Uri $url -OutFile $out
    if ((Get-Item $out).Length -lt 10MB) { throw "Git download looks incomplete. Check internet and re-run." }
    Write-Info "Installing Git..."
    Start-Process $out -ArgumentList "/VERYSILENT", "/NORESTART", "/NOCANCEL", "/SP-" -Wait
}

# --- Elevate to Administrator if needed ---
if (-not (Test-Admin)) {
    if ($env:SEO_BOT_ELEVATED -eq "1") {
        Write-Host "WARNING: not running as administrator - installs may fail." -ForegroundColor Red
    } else {
        Write-Host "  Requesting administrator rights..."
        $env:SEO_BOT_ELEVATED = "1"
        Start-Process powershell `
            -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ('"{0}"' -f $PSCommandPath) `
            -Verb RunAs
        exit 0
    }
}

Clear-Host
Write-Host ""
Write-Host "  =============================================" -ForegroundColor Cyan
Write-Host "    SEO Automation Bot - Automated Setup" -ForegroundColor Cyan
Write-Host "  =============================================" -ForegroundColor Cyan

# =====================================================================
# [1/4] Git
# =====================================================================
Write-Step 1 4 "Checking Git..."
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
Write-OK "Git is ready."

# =====================================================================
# [2/4] Docker Desktop
# =====================================================================
Write-Step 2 4 "Checking Docker Desktop..."
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
            Write-Info "Downloading Docker Desktop (~500 MB)..."
            $url = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
            $out = Join-Path $env:TEMP "DockerDesktopInstaller.exe"
            Invoke-WebRequest -Uri $url -OutFile $out
            if ((Get-Item $out).Length -lt 100MB) { throw "Docker download looks incomplete." }
            Write-Info "Installing Docker Desktop..."
            Start-Process $out -ArgumentList "install", "--quiet", "--accept-license" -Wait
            Refresh-Path
        }
    }

    $desktopExe = Join-Path ${env:ProgramFiles} "Docker\Docker\Docker Desktop.exe"
    if (Test-Path $desktopExe) {
        Write-Info "Starting Docker Desktop..."
        Start-Process $desktopExe
        
        Write-Host ""
        Write-Host "  -------------------------------------------------------" -ForegroundColor Yellow
        Write-Host "  Please open Docker Desktop from your desktop/taskbar." -ForegroundColor Yellow
        Write-Host "  Wait until Docker Desktop shows 'Engine running'." -ForegroundColor Yellow
        Write-Host "  -------------------------------------------------------" -ForegroundColor Yellow
        Write-Host ""
        
        for ($i = 0; $i -lt 30 -and -not $daemonUp; $i++) {
            Start-Sleep -Seconds 5
            try {
                docker info 2>$null | Out-Null
                if ($LASTEXITCODE -eq 0) { $daemonUp = $true }
            } catch { $daemonUp = $false }
        }
    }
}

if (-not $daemonUp) {
    Write-Host ""
    Write-Host "  Docker engine is starting up or needs Docker Desktop to be opened." -ForegroundColor Yellow
    Write-Host "  Please open Docker Desktop and ensure it is running, then run SETUP.bat." -ForegroundColor Yellow
    Write-Host ""
} else {
    Write-OK "Docker Desktop is running."
}

# =====================================================================
# [3/4] Project Files
# =====================================================================
Write-Step 3 4 "Checking project files..."
$scriptDir = Split-Path -Parent $PSCommandPath

if (Test-Path (Join-Path $scriptDir "config.json")) {
    Write-OK "Project files located."
    Set-Location $scriptDir
} elseif (Test-Path (Join-Path (Join-Path $scriptDir $ProjectDir) "config.json")) {
    Write-OK "Project files located in $ProjectDir."
    Set-Location (Join-Path $scriptDir $ProjectDir)
} else {
    Write-Info "Cloning repository..."
    Set-Location $scriptDir
    git clone $RepoUrl
    Set-Location $ProjectDir
}

# =====================================================================
# [4/4] Environment (.env) Setup
# =====================================================================
Write-Step 4 4 "Checking environment credentials (.env)..."

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Info "Created .env file."
    }
}

$raw = Get-Content -Raw -LiteralPath ".env"
if ($raw -notmatch '(?m)^MONGO_URI_ATLAS=mongodb\+srv://[^<]') {
    Write-Host ""
    Write-Host "  Paste your MongoDB Atlas connection string:" -ForegroundColor Yellow
    $mongoUri = Read-Host "  MONGO_URI_ATLAS"
    if (-not [string]::IsNullOrWhiteSpace($mongoUri)) {
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
        Write-Info "MongoDB URI saved."
    }
}

Write-OK "Setup configuration ready!"
Write-Host ""
Write-Host "  =============================================" -ForegroundColor Green
Write-Host "    SETUP COMPLETE!" -ForegroundColor Green
Write-Host "  =============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  You can now double-click LAUNCH.bat to open the dashboard." -ForegroundColor Cyan
Write-Host ""
