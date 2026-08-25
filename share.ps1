# TriCV - expose the local app on a public URL.
#
#     .\share.ps1            open a Cloudflare quick tunnel (no account needed)
#     .\share.ps1 -UseNgrok  use ngrok instead (needs an authtoken)
#
# Tunnels port 5173 only. The web app calls the API with relative URLs and the
# dev server proxies them to port 8000, so one tunnel serves the whole thing.
#
# WARNING: this puts your machine on the public internet. Anyone with the URL
# can reach the HR login page and upload CVs on the careers page. Ctrl+C, or
# closing the window, takes it down.
#
# This file must stay ASCII-only and keep its BOM: Windows PowerShell 5.1
# reads .ps1 as ANSI otherwise and mis-parses non-ASCII characters.

param(
    [switch]$UseNgrok,
    [switch]$CheckOnly   # run every preflight check, but do not open the tunnel
)

function Say($msg, $colour = 'Cyan') { Write-Host "  $msg" -ForegroundColor $colour }
function Die($msg) { Write-Host "`n  $msg`n" -ForegroundColor Red; exit 1 }

# A freshly installed tool is often not on PATH yet: winget's portable
# installs do not always register a shim, and an MSI's PATH entry is invisible
# to any shell opened before the install. So search the usual install roots.
function Find-Tool($exeName) {
    $found = (Get-Command $exeName -ErrorAction SilentlyContinue).Source
    if ($found -and (Test-Path $found)) { return $found }

    $roots = @(
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'),
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)}
    ) | Where-Object { $_ -and (Test-Path $_) }

    foreach ($root in $roots) {
        $hit = Get-ChildItem -Path $root -Recurse -Filter $exeName -Depth 4 `
                             -ErrorAction SilentlyContinue |
               Select-Object -First 1 -ExpandProperty FullName
        if ($hit) { return $hit }
    }
    return $null
}

Write-Host "`nTriCV - public tunnel`n" -ForegroundColor White

# --- is the app actually running? ------------------------------------------
foreach ($port in 8000, 5173) {
    if (-not (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) {
        Die "nothing is listening on port $port - start the app first with:  .\start-dev.ps1"
    }
}
Say 'app is up on ports 8000 and 5173' 'Green'

# --- pick a tunnel ---------------------------------------------------------
if ($UseNgrok) {
    $tool = Find-Tool 'ngrok.exe'
    if (-not $tool) {
        Die "ngrok is not installed (or Windows Defender quarantined it). Run .\share.ps1 without -UseNgrok to use Cloudflare instead."
    }

    # ngrok refuses to tunnel without an authtoken. Read the config file
    # directly: 'ngrok config check' writes to stderr, and in PowerShell 5.1 a
    # native command's stderr can surface as a terminating error.
    $configured = $false
    foreach ($cfg in @((Join-Path $env:LOCALAPPDATA 'ngrok\ngrok.yml'),
                       (Join-Path $env:USERPROFILE '.ngrok2\ngrok.yml'),
                       (Join-Path $env:APPDATA 'ngrok\ngrok.yml'))) {
        if ((Test-Path $cfg) -and (Select-String -Path $cfg -Pattern '^\s*authtoken\s*:' -Quiet)) {
            $configured = $true; break
        }
    }
    if (-not $configured) {
        Die "ngrok has no authtoken. Sign up at https://dashboard.ngrok.com/signup, then run:`n         & '$tool' config add-authtoken YOUR_TOKEN"
    }

    $toolArgs = @('http', '5173')
    $label    = 'ngrok'
    $domain   = 'ngrok-free.app'
} else {
    $tool = Find-Tool 'cloudflared.exe'
    if (-not $tool) {
        Die "cloudflared is not installed. Run:  winget install --id Cloudflare.cloudflared -e"
    }
    # A quick tunnel needs no Cloudflare account and no login.
    $toolArgs = @('tunnel', '--url', 'http://localhost:5173')
    $label    = 'cloudflared'
    $domain   = 'trycloudflare.com'
}

Say "using $label" 'Green'
Say "  $tool" 'DarkGray'

if ($CheckOnly) {
    Write-Host ""
    Say 'all checks passed - re-run without -CheckOnly to open the tunnel' 'Green'
    Write-Host ""
    exit 0
}

Write-Host ""
Write-Host "  Watch for the https://....$domain URL below, then share:" -ForegroundColor White
Write-Host "    <url>/careers   the candidate-facing page" -ForegroundColor Green
Write-Host "    <url>/login     the HR dashboard" -ForegroundColor Green
Write-Host ""
Write-Host "  Your machine serves every request - keep it awake and online." -ForegroundColor DarkGray
Write-Host "  Ctrl+C closes the tunnel." -ForegroundColor DarkGray
Write-Host ""

& $tool @toolArgs
