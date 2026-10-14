<#
.SYNOPSIS
  Single-step LogVault installer for Windows + Docker Desktop.

.DESCRIPTION
  Takes a fresh clone to a running stack:
    1. Preflight checks (docker, compose, daemon, conflicting ports)
    2. Creates .env from .env.example (keeps an existing one) and fills in
       generated LAST9_ENCRYPTION_KEY / JWT_SECRET plus the admin account
    3. Builds images and starts the stack (prod overlay by default)
    4. Waits for Postgres/Redis/API health, runs migrations + seed
    5. Verifies /ready and prints URLs + credentials

  Idempotent: safe to re-run. It never overwrites an existing .env and
  `up -d` / migrations / seed are all no-ops when already done.

.EXAMPLE
  .\install.ps1
  Interactive: prompts for the admin email/password.

.EXAMPLE
  .\install.ps1 -Yes
  Non-interactive: default admin (admin@logvault.local) with a generated
  password printed once at the end. Save it.

.EXAMPLE
  .\install.ps1 -Dev
  Hot-reloading dev stack instead of the prod overlay.

.EXAMPLE
  .\install.ps1 -AdminEmail me@company.com -AdminPassword "s3cret!"
#>
[CmdletBinding()]
param(
    [switch]$Dev,
    [switch]$Yes,
    [string]$AdminEmail = "",
    [string]$AdminPassword = "",
    [string]$ApiBase = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "  [ok] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Fail($msg) {
    Write-Host "  [FAIL] $msg" -ForegroundColor Red
    Write-Host "  Check: docker compose logs api worker  (or: docker compose logs -f <service>)"
    exit 1
}

# --- 1. Preflight -------------------------------------------------------------
Step "Preflight checks"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "docker not found. Install Docker Desktop and re-run."
}
Ok "docker present"

$composeOk = $false
try {
    docker compose version 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $composeOk = $true }
} catch {}
if (-not $composeOk) { Fail "'docker compose' not available. Update Docker Desktop." }
Ok "docker compose present"

try {
    docker info 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "daemon down" }
} catch {
    Fail "Docker daemon is not running. Start Docker Desktop and re-run."
}
Ok "docker daemon running"

# Ports this stack publishes (must match docker-compose.yml).
foreach ($port in @(5432, 6380, 8000, 3001)) {
    $inUse = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($inUse) {
        $proc = (Get-Process -Id $inUse[0].OwningProcess -ErrorAction SilentlyContinue).ProcessName
        Warn "port $port is already in use (by $proc). The stack may fail to start - free it or remap the port in docker-compose.yml."
    }
}
Ok "port check done"

# --- 2. .env ------------------------------------------------------------------
Step "Environment file (.env)"

$EnvFile = Join-Path $Root ".env"
$ExampleFile = Join-Path $Root ".env.example"
if (-not (Test-Path $ExampleFile)) { Fail ".env.example missing - are you in the repo root?" }

if (-not (Test-Path $EnvFile)) {
    Copy-Item $ExampleFile $EnvFile
    Ok "created .env from .env.example"
} else {
    Ok "existing .env kept (never overwritten)"
}

function Get-EnvValue($name) {
    $line = Select-String -Path $EnvFile -Pattern "^$name=(.*)$" | Select-Object -First 1
    if ($line) { return $line.Matches.Groups[1].Value.Trim() }
    return $null
}

function Set-EnvValue($name, $value) {
    $lines = Get-Content $EnvFile
    $found = $false
    $out = foreach ($ln in $lines) {
        if ($ln -match "^$name=") { "$name=$value"; $found = $true } else { $ln }
    }
    if (-not $found) { $out += "$name=$value" }
    Set-Content $EnvFile $out
}

function New-UrlSafeKey($bytes) {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $buf = New-Object byte[] $bytes
    $rng.GetBytes($buf)
    $rng.Dispose()
    return [Convert]::ToBase64String($buf).Replace("+", "-").Replace("/", "_").TrimEnd("=")
}

if ((Get-EnvValue "LAST9_ENCRYPTION_KEY") -in @($null, "", "replace-with-generated-fernet-key")) {
    Set-EnvValue "LAST9_ENCRYPTION_KEY" (New-UrlSafeKey 32)
    Ok "generated LAST9_ENCRYPTION_KEY"
}
if ((Get-EnvValue "JWT_SECRET") -in @($null, "", "replace-with-random-secret")) {
    Set-EnvValue "JWT_SECRET" (New-UrlSafeKey 48)
    Ok "generated JWT_SECRET"
}
# The web port in docker-compose.yml is 3001; the example file only allows
# 3000, which surfaces as a CORS error on login. Allow both.
Set-EnvValue "CORS_ORIGINS" "http://localhost:3000,http://localhost:3001"
Set-EnvValue "NEXT_PUBLIC_API_BASE_URL" $ApiBase

if ([string]::IsNullOrWhiteSpace($AdminEmail)) {
    if ($Yes) { $AdminEmail = "admin@logvault.local" }
    else {
        $input = Read-Host "Initial admin email [admin@logvault.local]"
        $AdminEmail = if ([string]::IsNullOrWhiteSpace($input)) { "admin@logvault.local" } else { $input.Trim() }
    }
}
$GeneratedPassword = $false
if ([string]::IsNullOrWhiteSpace($AdminPassword)) {
    if ($Yes) {
        $AdminPassword = "Logvault-" + (New-UrlSafeKey 12)
        $GeneratedPassword = $true
    } else {
        $sec = Read-Host "Initial admin password (input hidden)" -AsSecureString
        $AdminPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
        if ([string]::IsNullOrWhiteSpace($AdminPassword)) { Fail "admin password cannot be empty." }
    }
}
Set-EnvValue "INITIAL_ADMIN_EMAIL" $AdminEmail
Set-EnvValue "INITIAL_ADMIN_PASSWORD" $AdminPassword
Ok "admin account configured ($AdminEmail)"

# --- 3. Build + up ------------------------------------------------------------
Step "Build images"

$ComposeBase = @("compose", "-f", "docker-compose.yml")
if (-not $Dev) { $ComposeBase += @("-f", "docker-compose.prod.yml") }

& docker @ComposeBase build 2>&1 | Select-Object -Last 2
if ($LASTEXITCODE -ne 0) { Fail "image build failed (see output above)." }
Ok "images built ($(if ($Dev) { 'dev stack' } else { 'prod overlay' }))"

Step "Start stack"
& docker @ComposeBase up -d 2>&1 | Select-Object -Last 5
if ($LASTEXITCODE -ne 0) { Fail "'docker compose up -d' failed." }
Ok "containers started"

# --- 4. Wait for health -------------------------------------------------------
Step "Wait for services"

function Wait-For($label, $script, $timeoutSec) {
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            if (& $script) { Ok $label; return }
        } catch {}
        Start-Sleep -Seconds 3
    }
    Fail "$label did not become ready within ${timeoutSec}s."
}

Wait-For "postgres + redis healthy" {
    # `ps --format json` prints one object per line, not an array.
    $s = @(docker compose ps --format json 2>$null | ForEach-Object {
        try { $_ | ConvertFrom-Json } catch { $null }
    }) | Where-Object { $_ -ne $null }
    $pg = $s | Where-Object { $_.Service -eq "postgres" } | Select-Object -First 1
    $rd = $s | Where-Object { $_.Service -eq "redis" } | Select-Object -First 1
    ($pg -and ($pg.Health -eq "healthy" -or $pg.State -eq "running")) -and
    ($rd -and ($rd.Health -eq "healthy" -or $rd.State -eq "running"))
} 180

Wait-For "api /health" {
    (Invoke-WebRequest -Uri "$ApiBase/health" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200
} 240

# --- 5. Migrate + seed --------------------------------------------------------
Step "Database migrations + seed"
& docker @ComposeBase exec -T api alembic upgrade head 2>&1 | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) { Fail "alembic upgrade head failed." }
Ok "migrations at head"

& docker @ComposeBase exec -T api python -m app.seed 2>&1 | Select-Object -Last 2
if ($LASTEXITCODE -ne 0) { Warn "seed step failed (non-fatal) - the app still runs; see output above." }
else { Ok "seed done" }

# --- 6. Verify ----------------------------------------------------------------
Step "Verify"

try {
    $ready = Invoke-RestMethod -Uri "$ApiBase/ready" -TimeoutSec 10
    Ok "api /ready: $($ready.status)"
} catch {
    Fail "/ready check failed: $($_.Exception.Message)"
}

$WebPort = "3001"  # both stacks publish the web UI here (see docker-compose.yml)

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Green
Write-Host "  LogVault is up." -ForegroundColor Green
Write-Host "============================================================="
Write-Host "  Frontend :  http://localhost:$WebPort"
Write-Host "  API docs :  $ApiBase/docs"
Write-Host "  Login    :  $AdminEmail"
if ($GeneratedPassword) {
    Write-Host "  Password :  $AdminPassword   <-- generated; save it now" -ForegroundColor Yellow
} else {
    Write-Host "  Password :  (the one you entered)"
}
Write-Host ""
Write-Host "  Useful:"
Write-Host "    docker compose logs -f api worker     # follow logs"
Write-Host "    docker compose ps                     # status"
if (-not $Dev) {
    Write-Host "    ./deploy.sh <svc> (Git Bash)          # rebuild after code changes"
}
Write-Host "============================================================="
