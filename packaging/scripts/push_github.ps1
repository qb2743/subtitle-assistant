#Requires -Version 5.1
# Push to https://github.com/qb2743/subtitle-assistant (no gh required)
# First create empty repo at https://github.com/new name: subtitle-assistant

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root

$Remote = "https://github.com/qb2743/subtitle-assistant.git"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Install Git: https://git-scm.com/download/win"
    exit 1
}

$gitEmail = git config user.email 2>&1
if ([string]::IsNullOrWhiteSpace($gitEmail)) {
    git config user.name "qb2743"
    git config user.email "qb2743@users.noreply.github.com"
    Write-Host "Set git user to qb2743 for this repo."
}

if (-not (Test-Path (Join-Path $Root ".git"))) {
    git init
    git branch -M main
}

git rev-parse HEAD 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    git add -A
    git commit -m "subtitle-assistant 1.0.0 initial release"
}

$originUrl = ""
try {
    $originUrl = git remote get-url origin 2>&1 | Out-String
    $originUrl = $originUrl.Trim()
} catch {
    $originUrl = ""
}

if ([string]::IsNullOrWhiteSpace($originUrl)) {
    git remote add origin $Remote
    Write-Host "Added remote: $Remote"
}
elseif ($originUrl -ne $Remote) {
    git remote set-url origin $Remote
}

Write-Host ""
Write-Host "Pushing to GitHub..."
Write-Host ""

git push -u origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "OK: https://github.com/qb2743/subtitle-assistant"
    Write-Host "Upload setup exe to Releases tag v1.0.0"
}
else {
    Write-Host ""
    Write-Host "Push failed. Check:"
    Write-Host "  1) Empty repo subtitle-assistant exists on GitHub"
    Write-Host "  2) Use PAT as password: GitHub Settings -> Developer settings -> PAT (classic), scope repo"
    Write-Host "     Username qb2743, Password = token"
    Write-Host "  3) Or SSH: git remote set-url origin git@github.com:qb2743/subtitle-assistant.git"
    exit 1
}