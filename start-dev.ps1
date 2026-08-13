# TriCV - run the whole app locally, without Docker.
#
#     .\start-dev.ps1              start backend + frontend
#     .\start-dev.ps1 -Seed        reload the demo data first
#     .\start-dev.ps1 -Stop        stop everything
#     .\start-dev.ps1 -WithNer     also install the spaCy models (needs Python 3.12)
#
# Uses SQLite instead of PostgreSQL, so there is nothing to install beyond
# Python and Node. Redaction, scoring, exports and the widget all behave as
# they do under Docker.
#
# NOTE ON PYTHON VERSIONS
#   spaCy 3.8 does not support Python 3.13. On 3.13 this script installs
#   everything else and runs fine - redaction falls back to regex plus the
#   values typed into the form, which is weaker at catching bare city names.
#   For the full pipeline use Python 3.12, or use Docker.
#
# This file must stay ASCII-only and keep its BOM: Windows PowerShell 5.1
# reads .ps1 as ANSI otherwise and mis-parses non-ASCII characters.

param(
    [switch]$Seed,
    [switch]$Stop,
    [switch]$WithNer
)

$root     = $PSScriptRoot
$backend  = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$venv     = Join-Path $backend '.venv'
$python   = Join-Path $venv 'Scripts\python.exe'
$dataDir  = Join-Path $root 'data'

function Say($msg, $colour = 'Cyan') { Write-Host "  $msg" -ForegroundColor $colour }
function Die($msg) { Write-Host "`n  $msg`n" -ForegroundColor Red; exit 1 }

function Stop-TriCV {
    foreach ($port in 8000, 5173) {
        $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        foreach ($c in $conns) {
            Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
            Say "stopped whatever held port $port" 'Yellow'
        }
    }
}

if ($Stop) { Stop-TriCV; Say 'TriCV stopped.' 'Green'; exit 0 }

Write-Host "`nTriCV - local development`n" -ForegroundColor White

foreach ($exe in 'python', 'npm') {
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
        Die "'$exe' is not on your PATH. Install it and try again."
    }
}

# --- python environment ----------------------------------------------------
if (-not (Test-Path $python)) {
    Say 'creating the Python virtualenv (first run only)...'
    python -m venv $venv
    if (-not (Test-Path $python)) { Die 'could not create the virtualenv.' }
}

$pyVersion = (& $python -c "import sys; print(str(sys.version_info.major)+'.'+str(sys.version_info.minor))").Trim()
$spacyOk = [version]$pyVersion -lt [version]'3.13'

# Already usable? Cheap check, so restarts are instant.
& $python -c "import sqlalchemy, fastapi, reportlab, openpyxl, docx, fitz" 2>$null
if ($LASTEXITCODE -ne 0) {
    Say "installing backend dependencies for Python $pyVersion, this takes a few minutes..."
    $reqFile = Join-Path $backend 'requirements.txt'

    if (-not $spacyOk) {
        Say "Python $pyVersion cannot install spaCy - skipping it (see the note at the top of this script)" 'Yellow'
        $filtered = Join-Path $env:TEMP 'tricv-requirements-nospacy.txt'
        Get-Content $reqFile | Where-Object { $_ -notmatch '^\s*spacy' } | Set-Content $filtered -Encoding ascii
        $reqFile = $filtered
    }

    & $python -m pip install --quiet --upgrade pip
    & $python -m pip install --quiet -r $reqFile

    & $python -c "import sqlalchemy, fastapi, reportlab, openpyxl, docx, fitz" 2>$null
    if ($LASTEXITCODE -ne 0) { Die 'dependency install failed - scroll up for the pip error.' }
    Say 'dependencies installed' 'Green'
}

if ($WithNer) {
    if (-not $spacyOk) {
        Say "cannot install the spaCy models on Python $pyVersion - use Python 3.12 or Docker" 'Yellow'
    } else {
        Say 'downloading spaCy models (~80 MB)...'
        & $python -m spacy download fr_core_news_md
        & $python -m spacy download en_core_web_md
    }
}

# --- configuration ---------------------------------------------------------
# The API key and model come from .env, the same file Docker reads.
$envFile = Join-Path $root '.env'
if (-not (Test-Path $envFile)) { Copy-Item (Join-Path $root '.env.example') $envFile }

Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)$') {
        Set-Item -Path "Env:$($matches[1])" -Value $matches[2].Trim()
    }
}

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$env:DATABASE_URL = "sqlite+aiosqlite:///$($dataDir -replace '\\','/')/tricv.db"
$env:STORAGE_PATH = Join-Path $dataDir 'cv'
$env:CORS_ORIGINS = 'http://localhost:5173,http://localhost:8080,http://127.0.0.1:5173'
if (-not $env:JWT_SECRET) { $env:JWT_SECRET = 'dev-only-secret' }

if ($env:GEMINI_API_KEY) {
    $model = if ($env:LLM_MODEL) { $env:LLM_MODEL } else { 'provider default' }
    Say "LLM: $($env:LLM_PROVIDER) / $model" 'Green'
} else {
    Say 'no GEMINI_API_KEY in .env - seeded data works, but new CVs will not be scored' 'Yellow'
}
if (-not $spacyOk) { Say 'NER off: redaction uses regex and form values only' 'Yellow' }

Stop-TriCV

# --- database --------------------------------------------------------------
Push-Location $backend
& $python bootstrap_db.py
if ($LASTEXITCODE -ne 0) { Pop-Location; Die 'could not create the database schema.' }

if ($Seed) {
    Say 'loading demo data...'
    & $python -m app.seed
    if ($LASTEXITCODE -ne 0) { Pop-Location; Die 'seeding failed.' }
}

# --- start -----------------------------------------------------------------
Say 'starting the API on http://localhost:8000 ...'
$uvicornArgs = @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000')
Start-Process -FilePath $python -ArgumentList $uvicornArgs -WorkingDirectory $backend
Pop-Location

if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Say 'installing frontend dependencies (first run only)...'
    Push-Location $frontend
    npm install --no-audit --no-fund
    Pop-Location
}
Say 'starting the web app on http://localhost:5173 ...'
# Start-Process needs the real executable: on Windows 'npm' is a .cmd shim, and
# passing the bare name spawns a process that exits immediately without error.
$npmCmd = (Get-Command npm).Source
if ($npmCmd -notmatch '\.(cmd|bat|exe)$') { $npmCmd = "$npmCmd.cmd" }
Start-Process -FilePath $npmCmd -ArgumentList 'run', 'dev' -WorkingDirectory $frontend

# --- wait for the API before claiming success ------------------------------
$apiUp = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    try {
        if ((Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:8000/health' -TimeoutSec 3).StatusCode -eq 200) {
            $apiUp = $true; break
        }
    } catch { }
}

Write-Host ""
if ($apiUp) {
    Write-Host "  Careers page (candidates)  http://localhost:5173/careers" -ForegroundColor Green
    Write-Host "  HR dashboard               http://localhost:5173/login" -ForegroundColor Green
    Write-Host "  API docs                   http://localhost:8000/docs" -ForegroundColor Green
    Write-Host ""
    Write-Host "  login: $($env:SEED_ADMIN_EMAIL)  /  $($env:SEED_ADMIN_PASSWORD)" -ForegroundColor White
} else {
    Write-Host "  The API did not come up. Check the uvicorn window for the error." -ForegroundColor Red
}
Write-Host ""
Write-Host "  stop with:  .\start-dev.ps1 -Stop" -ForegroundColor DarkGray
Write-Host ""
