# Builds the static frontend with explicit local settings and serves it on
# http://localhost:3000. Settings come from this process's environment, which
# Next.js prefers over frontend/.env.local, so that file is never needed or read.
#
# Usage (from anywhere):
#   powershell -File scripts\serve_frontend_local.ps1            # build, check, serve
#   powershell -File scripts\serve_frontend_local.ps1 -NoServe   # build and check only
#
# The Google client ID is public, not a secret. It must match the API's
# OAUTH_AUDIENCE; the script checks that against the running API container.
param(
    [string]$ClientId = "778432443327-tfr98qv01htq229443g0kjnvlkp2md4h.apps.googleusercontent.com",
    [string]$ApiBase = "http://localhost:8000",
    [string]$FallbackEngagements = "acme,globex",
    [int]$Port = 3000,
    [switch]$NoServe
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root "frontend"
$out = Join-Path $frontend "out"
$python = Join-Path $root ".venv\Scripts\python.exe"
function Fail([string]$msg) { Write-Host "FAILED: $msg"; exit 1 }

if (-not $ClientId.EndsWith(".apps.googleusercontent.com")) { Fail "ClientId doesn't look like a Google web client ID" }
$env:NEXT_PUBLIC_GOOGLE_CLIENT_ID = $ClientId
$env:NEXT_PUBLIC_API_BASE_URL = $ApiBase
$env:NEXT_PUBLIC_FALLBACK_ENGAGEMENTS = $FallbackEngagements

if (Test-Path $out) { Remove-Item -Recurse -Force $out }
Push-Location $frontend
try {
    & npm run build
    if ($LASTEXITCODE -ne 0) { Fail "npm run build exited $LASTEXITCODE" }
} finally { Pop-Location }

# The built pages must carry the client ID and the API base, or sign-in can't work.
$built = Get-ChildItem -Recurse -File $out -Include *.js, *.html
$hasId = [bool]($built | Select-String -SimpleMatch -Pattern $ClientId -List | Select-Object -First 1)
$hasApi = [bool]($built | Select-String -SimpleMatch -Pattern $ApiBase -List | Select-Object -First 1)
if (-not $hasId) { Fail "the build output doesn't contain the client ID" }
if (-not $hasApi) { Fail "the build output doesn't contain the API base URL" }
Write-Host "build output contains the client ID and $ApiBase"

try {
    Invoke-RestMethod "$ApiBase/health" -TimeoutSec 5 | Out-Null
    Write-Host "API health: ok"
} catch { Write-Host "WARNING: the API at $ApiBase isn't answering /health" }

# Compare with the API's OAUTH_AUDIENCE without printing it.
$docker = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe"
if (Test-Path $docker) {
    $probe = "import os; print(os.environ.get('OAUTH_AUDIENCE','') == '$ClientId')"
    $same = ($probe | & $docker exec -i consult-rag-api-1 python - 2>$null)
    if ($same -eq "True") { Write-Host "API OAUTH_AUDIENCE matches the client ID" }
    elseif ($same -eq "False") { Fail "the API's OAUTH_AUDIENCE is a different client ID" }
    else { Write-Host "WARNING: couldn't read OAUTH_AUDIENCE (is consult-rag-api-1 running?)" }
}

if ($NoServe) { exit 0 }
Write-Host "Serving $out on http://localhost:$Port (Ctrl+C to stop)"
& $python -m http.server $Port --bind 127.0.0.1 --directory $out
