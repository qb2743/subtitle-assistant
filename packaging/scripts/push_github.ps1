#Requires -Version 5.1
<#
  初始化 git 并推送到 https://github.com/qb2743/subtitle-assistant
  前置:
    1. 在 GitHub 网页新建空仓库 subtitle-assistant（不要勾选 README）
    2. 安装 GitHub CLI: winget install GitHub.cli
    3. gh auth login
  或不用 gh: 手动在网页建仓库后执行本脚本（仅 git push）
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root

$Repo = "qb2743/subtitle-assistant"
$Remote = "https://github.com/$Repo.git"

if (-not (Test-Path (Join-Path $Root ".git"))) {
    git init
    git branch -M main
}

# 确保 logo.ico 存在（提交到仓库，方便 Inno 编译）
$ico = Join-Path $Root "resource/assets/logo.ico"
if (-not (Test-Path $ico)) {
    $py = Join-Path $Root ".venv/Scripts/python.exe"
    if (Test-Path $py) { & $py (Join-Path $Root "packaging/scripts/make_logo_ico.py") }
}

git add -A
git status
$confirm = Read-Host "Continue commit? (y/n)"
if ($confirm -ne "y") { exit 0 }

git commit -m "字幕助手 1.0.0 初始发布"

if (-not (git remote get-url origin 2>$null)) {
    if (Get-Command gh -ErrorAction SilentlyContinue) {
        gh repo create subtitle-assistant --public --source=. --remote=origin --push
        Write-Host "Created and pushed via gh."
        exit 0
    }
    git remote add origin $Remote
}

git push -u origin main
Write-Host "Pushed to $Remote"
Write-Host "Release: upload packaging\installer\output\SubtitleAssistant-1.0.0-setup.exe to GitHub Releases tag v1.0.0"