# TriCV - run the whole app locally, without Docker.
#
#     .\start-dev.ps1              start backend + frontend
#     .\start-dev.ps1 -Seed        reload the demo data first
#     .\start-dev.ps1 -Stop        stop everything
#     .\start-dev.ps1 -Fresh       WIPE the database and stored files, start empty
#     .\start-dev.ps1 -Check       run the pre-flight check and exit
#     .\start-dev.ps1 -WithNer     also install the spaCy models (needs Python 3.12)
#
# BEFORE A REAL TEST:  .\start-dev.ps1 -Fresh   then   .\start-dev.ps1 -Check
# -Fresh is what separates a real run from the demo - seeded candidates mixed in
# with real ones corrupt the grids and the talent pool. -Check reports what is
# still standing between this install and real candidate data.
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
    [switch]$Fresh,
    [switch]$Check,
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
# spaCy 3.8.15 supports Python 3.13; earlier 3.8.x did not. On demande donc a
# pip, plutot que de deduire d'un numero de version qui a change depuis.
& $python -c "import spacy" 2>$null
$spacyOk = $LASTEXITCODE -eq 0
if (-not $spacyOk) {
    # Pas encore installe : verifier si une version compatible existe.
    & $python -m pip install --dry-run --quiet "spacy>=3.8.15" 2>$null
    $spacyOk = $LASTEXITCODE -eq 0
}

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

# VITE_API_URL in .env exists for the Docker image, which bakes an absolute API
# URL in at build time because its nginx does not proxy /api. The dev server
# DOES proxy, so it must call the API on the same origin as the page - Vite
# exposes any VITE_-prefixed process variable through import.meta.env, so
# leaving this set would hardcode http://localhost:8000 into the bundle and
# break every visitor who is not on this machine (tunnels, LAN, colleagues).
$env:VITE_API_URL = ''

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
$nerModels = (& $python -c "import app.services.redaction as r, json; print(len(r.loaded_ner_models()))" 2>$null)
if ($spacyOk) {
    Say 'NER on: redaction uses spaCy, regex and form values' 'Green'
} else {
    Say 'NER off: redaction uses regex and form values only' 'Yellow'
}

# -Check reports on this install and exits. Placed here on purpose: it must see
# the same DATABASE_URL and STORAGE_PATH as the servers, which are set just
# above. Run before a real test, and again after fixing what it reports.
if ($Check) {
    Push-Location $backend
    & $python preflight.py
    $code = $LASTEXITCODE
    Pop-Location
    exit $code
}

Stop-TriCV

# --- database --------------------------------------------------------------
# -Fresh wipes the database and every stored file. This is the switch that
# turns a demo install into a real one: leaving seeded candidates behind mixes
# fictional dossiers into real grids and into the talent pool.
if ($Fresh) {
    if ($Seed) { Die '-Fresh and -Seed contradict each other. Pick one.' }
    $dbFile = Join-Path $dataDir 'tricv.db'
    $cvDir  = Join-Path $dataDir 'cv'
    Write-Host ""
    Write-Host "  This deletes the database and every stored CV under $dataDir." -ForegroundColor Yellow
    $reponse = Read-Host "  Type FRESH to confirm"
    if ($reponse -cne 'FRESH') { Die 'cancelled - nothing was deleted.' }
    if (Test-Path $dbFile) { Remove-Item $dbFile -Force }
    if (Test-Path $cvDir)  { Remove-Item $cvDir -Recurse -Force }
    Say 'database and stored files removed - starting empty' 'Green'
}

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
# Start-Process needs a real executable. Bare 'npm' spawns a process that exits
# immediately without error, and 'Get-Command npm' resolves to npm.ps1 - a
# script, which Start-Process also cannot launch. Ask for npm.cmd by name.
$npmCmd = (Get-Command 'npm.cmd' -ErrorAction SilentlyContinue).Source
if (-not $npmCmd) {
    $npmCmd = [IO.Path]::ChangeExtension((Get-Command npm).Source, 'cmd')
}
if (-not (Test-Path $npmCmd)) { Die "could not find npm.cmd (looked at '$npmCmd')." }
Start-Process -FilePath $npmCmd -ArgumentList 'run', 'dev' -WorkingDirectory $frontend

# --- wait for both before claiming success ---------------------------------
# Checking only the API once let this script report success while the web app
# had failed to start at all.
$apiUp = $false
$webUp = $false
for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 2
    if (-not $apiUp) {
        try {
            if ((Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:8000/health' -TimeoutSec 3).StatusCode -eq 200) {
                $apiUp = $true
            }
        } catch { }
    }
    if (-not $webUp) {
        $webUp = [bool](Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue)
    }
    if ($apiUp -and $webUp) { break }
}

Write-Host ""
if (-not $apiUp) { Write-Host "  The API did not come up. Check the uvicorn window for the error." -ForegroundColor Red }
if (-not $webUp) { Write-Host "  The web app did not come up. Check the npm window for the error." -ForegroundColor Red }

if ($apiUp -and $webUp) {
    Write-Host "  Careers page (candidates)  http://localhost:5173/careers" -ForegroundColor Green
    Write-Host "  HR dashboard               http://localhost:5173/login" -ForegroundColor Green
    Write-Host "  API docs                   http://localhost:8000/docs" -ForegroundColor Green
    Write-Host ""
    Write-Host "  login: $($env:SEED_ADMIN_EMAIL)  /  $($env:SEED_ADMIN_PASSWORD)" -ForegroundColor White
}
Write-Host ""
Write-Host "  stop with:   .\start-dev.ps1 -Stop" -ForegroundColor DarkGray
Write-Host "  before a real test:  .\start-dev.ps1 -Fresh   then   .\start-dev.ps1 -Check" -ForegroundColor DarkGray
Write-Host ""
