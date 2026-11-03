<#
.SYNOPSIS
  Builds the static frontend for the AWS deployment, uploads it to the S3
  bucket and invalidates CloudFront.

.DESCRIPTION
  Reads the bucket, distribution, URL and Google client ID from Terraform
  outputs (local state; no secrets). Builds with the API on the same origin
  (NEXT_PUBLIC_API_BASE_URL="/"), checks the build, then syncs: hashed assets
  under _next/static first with a long cache, then everything else with
  no-cache, then a CloudFront invalidation of /*.

  Nothing it handles is secret, and it prints no tokens, keys or env values.

.PARAMETER SkipUpload
  Build and check only; don't call AWS. Useful for testing the build.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\deploy_frontend.ps1
  powershell -ExecutionPolicy Bypass -File scripts\deploy_frontend.ps1 -SkipUpload
#>
param(
    [string]$AwsProfile = "consultrag",
    [switch]$SkipUpload
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$tfDir = Join-Path $repo "infra\terraform"
$frontend = Join-Path $repo "frontend"
$out = Join-Path $frontend "out"

function Fail([string]$message) {
    Write-Host "ERROR: $message" -ForegroundColor Red
    exit 1
}

function Get-TfOutput([string]$name) {
    $value = & terraform "-chdir=$tfDir" output -raw $name 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($value)) {
        Fail "Terraform output '$name' is missing. Run 'terraform apply' in infra\terraform first."
    }
    return $value.Trim()
}

# --- 1. Terraform outputs (all public values) ---------------------------------
if (-not (Get-Command terraform -ErrorAction SilentlyContinue)) { Fail "terraform is not on PATH." }
$bucket = Get-TfOutput "frontend_bucket"
$distributionId = Get-TfOutput "cloudfront_distribution_id"
$siteUrl = Get-TfOutput "cloudfront_url"
$clientId = Get-TfOutput "google_client_id"
Write-Host "Site: $siteUrl"
Write-Host "Bucket: $bucket   Distribution: $distributionId"

# --- 2. Build -------------------------------------------------------------------
# Every NEXT_PUBLIC_ value is set explicitly, because a defined process
# variable beats frontend/.env.local (which this script never reads). "/" means
# same origin: PowerShell deletes a variable set to "", so "" can't be used.
# A single space for the fallback list means "none" (it's trimmed away).
$env:NEXT_PUBLIC_API_BASE_URL = "/"
$env:NEXT_PUBLIC_GOOGLE_CLIENT_ID = $clientId
$env:NEXT_PUBLIC_FALLBACK_ENGAGEMENTS = " "

if (Test-Path $out) { Remove-Item -Recurse -Force $out }
Push-Location $frontend
try {
    & npm run build
    if ($LASTEXITCODE -ne 0) { Fail "npm run build failed; nothing was uploaded." }
} finally {
    Pop-Location
}

# --- 3. Check the build before anything is synced with --delete -------------------
$index = Join-Path $out "index.html"
if (-not (Test-Path $index)) { Fail "out\index.html is missing; refusing to upload." }
$fileCount = (Get-ChildItem -Recurse -File $out | Measure-Object).Count
if ($fileCount -lt 5) { Fail "out\ has only $fileCount files; refusing to upload." }

$textFiles = Get-ChildItem -Recurse -File $out -Include *.html, *.js, *.txt, *.json, *.css
$localhost = $textFiles | Select-String -SimpleMatch "localhost:8000" -List
if ($localhost) {
    Fail "The build still points at localhost:8000 (e.g. $($localhost[0].Path)); refusing to upload."
}
$hasClientId = $textFiles | Select-String -SimpleMatch $clientId -List
if (-not $hasClientId) { Fail "The Google client ID isn't in the build; refusing to upload." }
Write-Host "Build checked: $fileCount files, same-origin API, Google client ID present."

if ($SkipUpload) {
    Write-Host "SkipUpload: not calling AWS."
    exit 0
}

# --- 4. Upload and invalidate ---------------------------------------------------
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { Fail "aws (AWS CLI v2) is not on PATH." }

# Hashed assets first, so new HTML never references a file that isn't there yet.
& aws s3 sync (Join-Path $out "_next\static") "s3://$bucket/_next/static" `
    --delete --cache-control "public,max-age=31536000,immutable" --profile $AwsProfile --only-show-errors
if ($LASTEXITCODE -ne 0) { Fail "Uploading _next/static failed." }

& aws s3 sync $out "s3://$bucket" --delete --exclude "_next/static/*" `
    --cache-control "no-cache" --profile $AwsProfile --only-show-errors
if ($LASTEXITCODE -ne 0) { Fail "Uploading the pages failed." }

$invalidation = & aws cloudfront create-invalidation --distribution-id $distributionId `
    --paths "/*" --profile $AwsProfile --query "Invalidation.Id" --output text
if ($LASTEXITCODE -ne 0) { Fail "The CloudFront invalidation failed (the files are uploaded)." }

Write-Host "Uploaded. CloudFront invalidation $invalidation started; it usually completes in a few minutes."
Write-Host "Open $siteUrl"
